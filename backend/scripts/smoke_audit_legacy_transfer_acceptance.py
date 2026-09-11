"""Real PostgreSQL + ASGI A1.9 acceptance, entirely inside a disposable database.

After rebuilding the local backend, run from /app (or backend):
  DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE=1 PYTHONDONTWRITEBYTECODE=1 \
    python -B -m scripts.smoke_audit_legacy_transfer_acceptance --allow-create-database

Consumes normal runtime configuration opaquely. Never pass a database URL or
source workbook. No lifespan, login, external HTTP, real-user fixtures or mocks.
Only safe check identifiers/counts are emitted; exception bodies are not logged.
"""

import argparse
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import sys
from time import perf_counter
import traceback
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from tests.audit_legacy_transfer_fixtures import (
    CURRENT_ACTOR, HISTORICAL_ACTOR, KINDS, combined_rows, transfer_config, workbook,
)


OPT_IN_ENV = "DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE"
TEMP_NAME = re.compile(r"^dpms_a19_acceptance_[0-9a-f]{12}$")
TRANSFER = "/api/audit/legacy-transfers"
SOURCE = "/api/audit/legacy-imports"
MOSCOW = ZoneInfo("Europe/Moscow")
TARGETS = (
    "audit_cases", "audit_atoms", "audit_assignments", "audit_events",
    "audit_legacy_metrics", "audit_team_members",
)
SCENARIOS = (
    "combined_preview_resolution", "assignment_eligibility", "aggregate_overlap",
    "invalid_taxonomy", "late_error_after_issue_cap",
    "combined_commit_persistence", "same_request_retry", "reordered_semantic_retry",
    "cross_batch_rollback_guard", "owned_rollback", "stale_preview_after_live_edit",
    "rollback_after_live_edit", "rollback_live_child_reference", "atomic_injected_failure",
    "concurrent_same_commit", "concurrent_cross_batch", "lost_commit_response",
    "load_1000_atoms",
    "alias_fill_empty_rollback", "event_only_final_projection",
    "reference_only_case_reuse", "unrelated_writes_not_blocked",
    "scoped_lock_helper_pg",
    "synthetic_contract_reference_privacy",
    "archived_case_assignment_policy", "assignment_timestamp_semantics",
)


class CheckFailed(Exception):
    """Contains only a hardcoded safe test identifier, never an API response."""


class Blocked(Exception):
    """Contains only a hardcoded preflight/cleanup blocker."""


def safe_exception_location(error):
    frames = traceback.extract_tb(error.__traceback__)
    return ",".join(f"{Path(frame.filename).name}:{frame.lineno}" for frame in frames[-3:])


class Results:
    def __init__(self):
        self.checks = 0
        self.passed = []
        self.failed = []

    def check(self, condition, identifier):
        self.checks += 1
        if not condition:
            raise CheckFailed(identifier)

    async def scenario(self, identifier, function):
        try:
            await function()
        except Blocked:
            raise
        except CheckFailed as error:
            self.failed.append(identifier)
            print(f"FAIL {identifier} check={error}", flush=True)
            return False
        except Exception as error:
            self.failed.append(identifier)
            print(f"FAIL {identifier} exception_type={type(error).__name__} locations={safe_exception_location(error)}", flush=True)
            return False
        self.passed.append(identifier)
        print(f"PASS {identifier}", flush=True)
        return True


def ensure_safe_target(url, allow_create):
    if not allow_create or os.environ.get(OPT_IN_ENV) != "1":
        raise Blocked("explicit_local_create_flag_and_env_required")
    if url.get_backend_name() != "postgresql":
        raise Blocked("postgresql_required")
    # The compose alias is accepted only from inside a container, never on a host.
    allowed = {"localhost", "127.0.0.1", "::1"}
    if Path("/.dockerenv").is_file():
        allowed.add("db")
    if (url.host or "") not in allowed or url.query:
        raise Blocked("local_only_host_without_connection_query_required")
    if url.database in {None, "", "postgres", "template0", "template1"}:
        raise Blocked("non_system_runtime_database_required")


def check_temp_name(name):
    if not TEMP_NAME.fullmatch(name):
        raise Blocked("unexpected_disposable_database_name")


async def database_lifecycle(url, name, *, drop=False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    check_temp_name(name)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", echo=False,
                                 hide_parameters=True, connect_args={"timeout": 10, "server_settings": {"statement_timeout": "15000", "lock_timeout": "5000"}})
    try:
        async with engine.connect() as connection:
            if drop:
                await connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name})
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            else:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def migrate(engine, results):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    directory = ScriptDirectory.from_config(config)
    heads = directory.get_heads()
    ancestors = {revision.revision for revision in directory.walk_revisions()}
    if len(heads) != 1 or "083_audit_legacy_transfer" not in ancestors:
        raise Blocked("migration_083_single_head_not_ready")
    # Avoid Alembic fileConfig, which may re-enable SQL/bind-value logging.
    config.config_file_name = None
    async with engine.connect() as connection:
        def upgrade(sync_connection):
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")
        await connection.run_sync(upgrade)
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        results.check(revision == heads[0], "migration_revision")
        for name in (*TARGETS, "audit_legacy_transfers", "audit_legacy_transfer_rows", "audit_legacy_provenance"):
            results.check(await connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"public.{name}"}) is not None, "migration_required_table")
    print("PASS migration_083", flush=True)


class Acceptance:
    def __init__(self, engine, sessions, app, results):
        self.engine, self.sessions, self.app, self.results = engine, sessions, app, results
        self.today = datetime.now(MOSCOW).date()
        self.rows = combined_rows(self.today)
        self.client = None
        self.admin = None
        self.users = {}
        self.base_case = None
        self.base_snapshot = None
        self.plan = None
        self.committed = None
        self.reused = None
        self.commit_payload = None

    check = lambda self, condition, identifier: self.results.check(condition, identifier)

    async def seed(self):
        from app.models.audit import AuditCase, AuditTeamMember
        from app.models.user import League, User, UserRole

        async with self.sessions() as db:
            for label, active, enabled, member in (
                ("admin", True, True, False), ("eligible", True, True, True),
                ("inactive", False, True, True), ("disabled", True, False, True),
                ("nonmember", True, True, False),
            ):
                user = User(full_name=f"Synthetic {label}", email=f"a19-{label}@example.invalid",
                            role=UserRole.admin if label == "admin" else UserRole.executor,
                            league=League.A, is_active=active, audit_enabled=enabled)
                db.add(user)
                await db.flush()
                self.users[label] = user.id
                if label == "admin":
                    self.admin = user
                if member:
                    db.add(AuditTeamMember(user_id=user.id, role="member", added_by_id=self.admin.id))
            case = AuditCase(title="Synthetic existing case", digital_product="Synthetic existing product", created_by_id=self.admin.id)
            db.add(case)
            await db.commit()
            self.base_case = case.id
        self.base_snapshot = await self.snapshot()

    async def snapshot(self, *, journal=False):
        from sqlalchemy import text

        result = {}
        async with self.sessions() as db:
            for table in TARGETS:
                # Only a newly-created, migrated and synthetic-seeded DB is reachable here.
                result[table] = [tuple(row) for row in (await db.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))).all()]
            result["users"] = [tuple(row) for row in (await db.execute(text("SELECT id, full_name, email, role, is_active, audit_enabled FROM users ORDER BY id"))).all()]
            if journal:
                for table in ("audit_legacy_provenance", "audit_legacy_transfer_rows"):
                    result[table] = [tuple(row) for row in (await db.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))).all()]
        return result

    async def request(self, method, path, *, expected=200, **kwargs):
        response = await asyncio.wait_for(self.client.request(method, path, **kwargs), timeout=45)
        if response.status_code != expected:
            try:
                code = response.json().get("detail", {}).get("code", "")
            except (ValueError, AttributeError):
                code = ""
            if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                print(f"response_error_code={code}", flush=True)
        self.check(response.status_code == expected, f"http_expected_{expected}_actual_{response.status_code}")
        if path.startswith((TRANSFER, SOURCE)) and response.status_code < 400:
            self.check(response.headers.get("cache-control") == "no-store", "private_response_header")
        if response.status_code == 204:
            return None
        return response.json()

    async def upload(self, rows=None, *, reordered=False):
        data, datasets = workbook(self.rows if rows is None else rows, reordered=reordered)
        source = await self.request("POST", SOURCE, files={"file": ("synthetic-acceptance.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        return source, datasets

    def config(self, datasets, namespace):
        return transfer_config(datasets, self.base_case, self.users["eligible"], namespace=namespace)

    async def preview(self, plan):
        return await self.request("POST", f"{TRANSFER}/{plan['id']}/preview", json={"revision": plan["revision"]})

    async def configure(self, plan, config):
        return await self.request("PUT", f"{TRANSFER}/{plan['id']}/config", json={"revision": plan["revision"], "config": config})

    def resolve_cases(self, preview, config, source_rows, *, reordered=False):
        decisions = config["cases"]
        source_cases = list(source_rows["cases"])
        if reordered:
            source_cases.reverse()
        config["cases"] = {}
        for row in preview["rows"]:
            if row["kind"] == "cases":
                self.check(row["row"] is not None, "case_source_row_available")
                source_key = source_cases[row["row"] - 2]["case_key"]
                config["cases"][row["changes"]["case_mapping_key"]] = decisions[source_key]

    async def prepare(self, namespace, rows=None, *, reordered=False, decisions=None):
        rows = self.rows if rows is None else rows
        source, datasets = await self.upload(rows, reordered=reordered)
        config = self.config(datasets, namespace)
        if decisions is not None:
            config["cases"] = deepcopy(decisions)
        initial = {**config, "cases": {}}
        plan = await self.request("POST", TRANSFER, json={"source_id": source["id"], "config": initial})
        plan = await self.preview(plan)
        self.resolve_cases(plan["preview"], config, rows, reordered=reordered)
        plan = await self.configure(plan, config)
        return await self.preview(plan)

    @staticmethod
    def payload(plan):
        return {"revision": plan["revision"], "preview_hash": plan["preview"]["preview_hash"], "confirm": True}

    async def commit(self, plan):
        self.check(plan["preview"]["ready"], "preview_not_ready")
        result = await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan))
        self.check(result["status"] == "committed", "commit_status")
        return result

    async def rollback(self, committed, *, expected=200, code=None):
        result = await self.request("POST", f"{TRANSFER}/{committed['id']}/rollback", expected=expected,
                                    json={"revision": committed["revision"], "reason": "Synthetic acceptance cleanup", "confirm": True})
        if expected == 200:
            self.check(result["status"] == "rolled_back", "rollback_status")
        elif code:
            self.check(result.get("detail", {}).get("code") == code, "rollback_conflict_reason")
        return result

    async def combined_preview_resolution(self):
        before = await self.snapshot(journal=True)
        source, datasets = await self.upload()
        self.check(len(source["inspection"]["sheets"]) == 5, "five_dataset_inspection")
        config = self.config(datasets, "a19-combined")
        unresolved = {**config, "cases": {}, "actors": {}}
        plan = await self.request("POST", TRANSFER, json={"source_id": source["id"], "config": unresolved})
        plan = await self.preview(plan)
        self.check(not plan["preview"]["ready"], "case_resolution_required")
        self.check("case_mapping_required" in {issue["code"] for issue in plan["preview"]["issues"]}, "case_resolution_issue")
        self.resolve_cases(plan["preview"], config, self.rows)
        plan = await self.configure(plan, {**config, "actors": {}})
        plan = await self.preview(plan)
        self.check(not plan["preview"]["ready"], "actor_resolution_required")
        self.check("actor_mapping_required" in {issue["code"] for issue in plan["preview"]["issues"]}, "actor_resolution_issue")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        plan = await self.configure(plan, config)
        plan = await self.preview(plan)
        self.check(plan["preview"]["ready"], "resolved_preview_ready")
        self.check(plan["preview"]["total_rows"] == 13, "combined_preview_13_rows")
        self.check(set(row["kind"] for row in plan["preview"]["rows"]) == set(KINDS), "preview_all_kinds")
        collected, offset = [], 0
        while offset is not None:
            page = await self.request("GET", f"{TRANSFER}/{plan['id']}/preview/rows", params={"offset": offset, "limit": 3})
            self.check(page["preview_hash"] == plan["preview"]["preview_hash"], "pagination_same_plan")
            collected.extend(row["row_key"] for row in page["rows"])
            next_offset = page["next_offset"]
            self.check(next_offset is None or next_offset > offset, "pagination_progress")
            offset = next_offset
        self.check(len(collected) == len(set(collected)) == 13, "pagination_complete_unique")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=422, json={**self.payload(plan), "confirm": False})
        self.check(await self.snapshot(journal=True) == before, "preview_no_target_or_provenance_mutation")
        self.plan = plan

    async def assignment_eligibility(self):
        before = await self.snapshot(journal=True)
        options = await self.request("GET", f"{TRANSFER}/options")
        by_id = {user["id"]: user for user in options["users"]}
        self.check(by_id[str(self.users["eligible"])]["eligible_current_assignment"], "eligible_option")
        for label in ("inactive", "disabled", "nonmember", "historical"):
            plan = await self.prepare(f"a19-ineligible-{label}")
            config = deepcopy(plan["config"])
            config["actors"][CURRENT_ACTOR] = (
                {"mode": "historical", "historical_name": "Synthetic current historical"}
                if label == "historical" else {"mode": "user", "user_id": str(self.users[label])}
            )
            plan = await self.configure(plan, config)
            plan = await self.preview(plan)
            self.check(not plan["preview"]["ready"], f"ineligible_{label}_blocked")
            self.check("current_assignment_ineligible" in {issue["code"] for issue in plan["preview"]["issues"]}, "ineligible_assignment_issue")
            await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        historical = await self.prepare("a19-current-disabled")
        config = {**historical["config"], "apply_current_assignments": False}
        historical = await self.configure(historical, config)
        historical = await self.preview(historical)
        self.check(historical["preview"]["ready"], "current_opt_in_disabled_ready")
        self.check(await self.snapshot(journal=True) == before, "ineligible_preview_no_mutation")

    async def archived_case_assignment_policy(self):
        from sqlalchemy import select
        from app.models.audit import AuditCase, AuditEvent

        async with self.sessions() as db:
            case = AuditCase(title="Synthetic archived assignment case", digital_product="Synthetic archived product", status="archived", created_by_id=self.admin.id)
            db.add(case)
            await db.commit()
            case_id = case.id
        baseline = await self.snapshot(journal=True)
        rows = {
            "cases": [{"case_key": "NEW", "title": "Synthetic archived assignment case", "digital_product": "Synthetic archived product"}],
            "assignments": [{"case_key": "NEW", "assignment_key": "ARCHIVED-1", "actor_name": CURRENT_ACTOR, "assigned_at": (self.today - timedelta(days=2)).isoformat(), "is_current": "true"}],
        }
        plan = await self.prepare("a19-archived-assignment", rows, decisions={"NEW": {"mode": "existing", "target_case_id": str(case_id)}})
        preview = plan["preview"]
        self.check(not preview["ready"], "archived_current_assignment_not_ready")
        assignment_rows = [row for row in preview["rows"] if row["kind"] == "assignments"]
        self.check(len(assignment_rows) == 1 and assignment_rows[0]["outcome"] == "blocked", "archived_current_assignment_row_blocked")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(await self.snapshot(journal=True) == baseline, "archived_current_assignment_no_mutation")

        # Disabling current application records history, even for an archived root.
        plan = await self.configure(plan, {**plan["config"], "apply_current_assignments": False})
        plan = await self.preview(plan)
        committed = await self.commit(plan)
        after = await self.snapshot()
        for table in (*TARGETS, "users"):
            if table != "audit_events":
                self.check(after[table] == baseline[table], "archived_historical_preserves_" + table)
        self.check(len(after["audit_events"]) == len(baseline["audit_events"]) + 1, "archived_historical_one_fact")
        async with self.sessions() as db:
            events = list((await db.scalars(select(AuditEvent).where(AuditEvent.legacy_transfer_id == UUID(committed["id"]), AuditEvent.case_id == case_id))).all())
            self.check(len(events) == 1 and events[0].event_type == "assignment", "archived_historical_assignment_persisted")
            self.check(events[0].payload_json["historical_only"] is True, "archived_assignment_historical_only")
            self.check(events[0].actor_id == self.users["eligible"], "archived_history_resolved_actor")
        await self.rollback(committed)
        self.check(await self.snapshot() == {table: baseline[table] for table in (*TARGETS, "users")}, "archived_history_rollback_exact")

    async def assignment_timestamp_semantics(self):
        from sqlalchemy import select
        from app.models.audit import AuditAssignment, AuditEvent

        baseline = await self.snapshot()
        day = (self.today - timedelta(days=2)).isoformat()
        original_time = f"{day}T09:00:00+03:00"
        changed_time = f"{day}T09:15:00+03:00"
        equivalent_time = f"{day}T06:00:00Z"
        rows = {
            "cases": [{"case_key": "NEW", "title": "Synthetic timestamp case", "digital_product": "Synthetic timestamp product"}],
            "assignments": [{"case_key": "NEW", "assignment_key": "TIMESTAMP-1", "actor_name": CURRENT_ACTOR, "is_current": "true"}],
        }
        # Exercise canonical timestamps through supported mapping defaults while
        # keeping the complete acceptance run within the real staging quota.
        source, datasets = await self.upload(rows)
        config = self.config(datasets, "a19-assignment-timestamp")
        for dataset in config["datasets"]:
            if dataset["kind"] == "assignments":
                dataset["defaults"] = {"assigned_at": original_time}
        initial = await self.request("POST", TRANSFER, json={"source_id": source["id"], "config": {**config, "cases": {}}})
        initial = await self.preview(initial)
        self.resolve_cases(initial["preview"], config, rows)
        initial = await self.configure(initial, config)
        initial = await self.preview(initial)
        original = await self.commit(initial)
        original_targets = await self.snapshot()
        case_id = UUID(next(row["target_id"] for row in initial["preview"]["rows"] if row["kind"] == "cases"))
        async with self.sessions() as db:
            assignment = await db.scalar(select(AuditAssignment).where(AuditAssignment.case_id == case_id))
            self.check(assignment is not None and assignment.scheduled_date == self.today - timedelta(days=2), "timestamp_original_calendar_day")
            history = list((await db.scalars(select(AuditEvent).where(AuditEvent.legacy_transfer_id == UUID(original["id"]), AuditEvent.event_type == "assignment"))).all())
            self.check(len(history) == 1 and history[0].occurred_at == datetime.fromisoformat(original_time), "timestamp_original_exact_instant")

        variants = {}
        for label, timestamp in (("changed", changed_time), ("equivalent", equivalent_time)):
            candidate = deepcopy(config)
            for dataset in candidate["datasets"]:
                if dataset["kind"] == "assignments":
                    dataset["defaults"]["assigned_at"] = timestamp
            plan = await self.request("POST", TRANSFER, json={"source_id": source["id"], "config": candidate})
            variants[label] = await self.preview(plan)

        changed = variants["changed"]
        self.check(not changed["preview"]["ready"], "timestamp_same_day_changed_instant_blocked")
        assignment_rows = [row for row in changed["preview"]["rows"] if row["kind"] == "assignments"]
        self.check(len(assignment_rows) == 1 and assignment_rows[0]["outcome"] == "blocked", "timestamp_changed_assignment_row_blocked")
        self.check("source_key_conflict" in {issue["code"] for issue in assignment_rows[0]["issues"]}, "timestamp_changed_source_key_conflict")
        before_rejection = await self.snapshot(journal=True)
        await self.request("POST", f"{TRANSFER}/{changed['id']}/commit", expected=409, json=self.payload(changed))
        self.check(await self.snapshot(journal=True) == before_rejection, "timestamp_conflict_no_mutation")

        equivalent = variants["equivalent"]
        self.check(equivalent["preview"]["ready"], "timestamp_equivalent_timezone_ready")
        self.check(equivalent["preview"]["total_rows"] == 2 and all(row["outcome"] == "duplicate" for row in equivalent["preview"]["rows"]), "timestamp_equivalent_timezone_semantic_dedup")
        duplicate = await self.commit(equivalent)
        self.check(await self.snapshot() == original_targets, "timestamp_equivalent_no_target_mutation")
        await self.rollback(duplicate)
        await self.rollback(original)
        self.check(await self.snapshot() == baseline, "timestamp_variants_rollback_exact")

    async def aggregate_overlap(self):
        before = await self.snapshot(journal=True)
        for metric_type, offset in (("verified", 7), ("alpha_reviewed", 6), ("commission_reviewed", 5)):
            rows = deepcopy(self.rows)
            rows["daily_totals"].append({"case_key": "DETAIL", "metric_date": (self.today - timedelta(days=offset)).isoformat(), "metric_type": metric_type, "value": 1})
            plan = await self.prepare(f"a19-overlap-{metric_type}", rows)
            self.check(not plan["preview"]["ready"], "aggregate_detail_overlap_blocked")
            self.check("aggregate_coverage_overlap" in {issue["code"] for issue in plan["preview"]["issues"]}, "aggregate_overlap_issue")
            await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(await self.snapshot(journal=True) == before, "overlap_no_mutation")

    async def invalid_taxonomy(self):
        before = await self.snapshot(journal=True)
        rows = deepcopy(self.rows)
        for field in ("state", "alpha_result", "commission_result"):
            rows["atoms"][0][field] = "synthetic-invalid-label"
        rows["events"][0]["event_type"] = "synthetic-invalid-event"
        plan = await self.prepare("a19-invalid-taxonomy", rows)
        preview = plan["preview"]
        self.check(not preview["ready"] and preview["counts"]["errors"] >= 4, "invalid_taxonomy_blocked")
        unknown_fields = {issue["field"] for issue in preview["issues"] if issue["code"] == "unknown_value"}
        self.check({"state", "alpha_result", "commission_result", "event_type"} <= unknown_fields, "invalid_taxonomy_all_fields_reported")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(await self.snapshot(journal=True) == before, "invalid_taxonomy_no_mutation")

    async def late_error_after_issue_cap(self):
        before = await self.snapshot(journal=True)
        rows = {"cases": [{"case_key": "NEW", "title": "Synthetic late error case", "digital_product": "Synthetic late error product"}],
                "atoms": [{"case_key": "NEW", "atom_key": f"LATE-{index}", "title": "Synthetic undated row", "state": "ready"} for index in range(501)]}
        rows["atoms"].append({"case_key": "NEW", "atom_key": "LATE-INVALID", "title": "Synthetic invalid final row", "state": "synthetic-invalid-label"})
        plan = await self.prepare("a19-late-error", rows)
        preview = plan["preview"]
        self.check(preview["total_rows"] == 503, "late_error_all_rows_checked")
        self.check(preview["counts"]["errors"] == 1 and preview["counts"]["warnings"] == 501, "late_error_exact_uncapped_counts")
        self.check(len(preview["issues"]) == 500, "late_error_visible_issue_cap")
        self.check(preview["issues"][0]["severity"] == "error" and preview["issues"][0]["row"] == 503 and preview["issues"][0]["field"] == "state", "late_error_prioritized_with_actionable_location")
        self.check(not preview["ready"], "late_hidden_error_blocks_ready")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(await self.snapshot(journal=True) == before, "late_error_no_mutation")

    async def combined_commit_persistence(self):
        from sqlalchemy import select
        from app.models.audit import AuditAtom, AuditAssignment, AuditEvent
        from app.models.audit_legacy_transfer import AuditLegacyMetric, AuditLegacyProvenance

        # Other drafts do not invalidate a plan; target changes must do so.
        self.commit_payload = self.payload(self.plan)
        self.committed = await self.commit(self.plan)
        async with self.sessions() as db:
            atoms = list((await db.scalars(select(AuditAtom).order_by(AuditAtom.item_code))).all())
            self.check(len(atoms) == 2, "two_persisted_atoms")
            dated, undated = atoms
            self.check(dated.state == undated.state == "ready", "ready_persisted")
            self.check(dated.alpha_result == "present" and dated.commission_result == "confirmed", "alpha_commission_persisted")
            self.check(dated.alpha_date == self.today - timedelta(days=6), "alpha_date_persisted")
            self.check(dated.commission_date == self.today - timedelta(days=5), "commission_date_persisted")
            self.check(dated.legacy_effective_at.astimezone(MOSCOW).date() == self.today - timedelta(days=7), "business_date_persisted")
            self.check(undated.legacy_effective_at is None, "unknown_date_not_ingested_date")
            self.check(all(str(atom.legacy_transfer_id) == self.committed["id"] for atom in atoms), "atoms_transfer_provenance")
            assignments = list((await db.scalars(select(AuditAssignment))).all())
            self.check(len(assignments) == 1 and assignments[0].assignee_id == self.users["eligible"], "eligible_current_only")
            self.check(assignments[0].case_id == undated.case_id, "current_assignment_target")
            self.check(assignments[0].scheduled_date == self.today - timedelta(days=2), "assignment_date_persisted")
            events = list((await db.scalars(select(AuditEvent).where(AuditEvent.historical_actor_name == HISTORICAL_ACTOR))).all())
            self.check(len(events) == 4, "unknown_historical_actor_four_events")
            self.check(all(event.actor_id is None for event in events), "unknown_historical_actor_no_login_link")
            self.check({event.event_type for event in events} == {"assignment", "atom_status_changed", "alpha_reviewed", "commission_reviewed"}, "historical_event_types")
            metrics = list((await db.scalars(select(AuditLegacyMetric))).all())
            self.check(len(metrics) == 3, "three_persisted_metrics")
            self.check({metric.metric_type: metric.value for metric in metrics} == {"verified": 7, "alpha_reviewed": 5, "commission_reviewed": 3}, "metric_values_persisted")
            self.check(all(metric.metric_date == self.today - timedelta(days=8) for metric in metrics), "aggregate_business_dates")
            provenance = list((await db.scalars(select(AuditLegacyProvenance))).all())
            self.check(len(provenance) == 13 and all(item.active for item in provenance), "provenance_13_rows")
            detail_id, new_id = dated.case_id, undated.case_id
        snapshot = await self.snapshot()
        self.check(snapshot["users"] == self.base_snapshot["users"], "no_new_login_or_user_change")
        self.check(snapshot["audit_team_members"] == self.base_snapshot["audit_team_members"], "no_implicit_team_membership")
        case = await self.request("GET", f"/api/audit/cases/{detail_id}")
        self.check(case["title"] == "Synthetic existing case" and case["digital_product"] == "Synthetic existing product", "existing_case_nonempty_preserved")
        self.check(case["contract_date"] == (self.today - timedelta(days=30)).isoformat(), "explicit_fill_empty_persisted")
        assigned_case = await self.request("GET", f"/api/audit/cases/{new_id}")
        self.check(assigned_case["responsible_user_id"] == str(self.users["eligible"]), "current_assignment_case_responsible_synchronized")
        self.check(assigned_case["workflow_stage"] == "atomization", "current_assignment_case_stage_synchronized")
        assigned_history = await self.request("GET", f"/api/audit/cases/{new_id}/events")
        assignment_facts = [event for event in assigned_history if event["event_type"] == "assignment" and event.get("historical_actor_name") == "Synthetic eligible"]
        self.check(len(assignment_facts) == 1, "current_assignment_history_fact")
        self.check(assignment_facts[0]["origin"] == "legacy_import", "current_assignment_history_origin")
        self.check(datetime.fromisoformat(assignment_facts[0]["occurred_at"].replace("Z", "+00:00")).astimezone(MOSCOW).date() == self.today - timedelta(days=2), "current_assignment_history_business_date")
        history = await self.request("GET", f"/api/audit/cases/{detail_id}/events")
        historical = [event for event in history if event.get("historical_actor_name") == HISTORICAL_ACTOR]
        self.check(len(historical) == 4, "history_api_historical_count")
        self.check(all(event["origin"] == "legacy_import" and event["actor_id"] is None and event["imported_at"] for event in historical), "history_api_origin_actor_import_time")
        statistics = await self.request("GET", "/api/audit/statistics", params={"days": 30})
        trend = {point["date"]: point for point in statistics["trend"]}
        self.check(trend[(self.today - timedelta(days=7)).isoformat()]["verified_count"] == 1, "historical_verification_single_count")
        self.check(trend[self.today.isoformat()]["verified_count"] == 0, "no_ingestion_spike")
        self.check(sum(point["verified_count"] for point in trend.values()) == 1, "detail_no_snapshot_event_double_count")
        self.check(statistics["undated_legacy_atoms"] == 1, "undated_visible")
        self.check(statistics["atoms"]["total"] == statistics["atoms"]["verified"] == 2, "aggregates_not_fake_atoms")
        self.check(statistics["atoms"]["alpha_review_completed"] == statistics["atoms"]["alpha_commission_completed"] == 1, "detail_results_statistics")
        aggregate = statistics["aggregate_trend"]
        nonzero = [point for point in aggregate if any(point[field] for field in ("verified_count", "alpha_reviewed_count", "commission_reviewed_count"))]
        self.check(len(nonzero) == 1 and nonzero[0] == {"date": (self.today - timedelta(days=8)).isoformat(), "verified_count": 7, "alpha_reviewed_count": 5, "commission_reviewed_count": 3}, "aggregate_trend_separate_exact")
        self.new_case = new_id

    async def same_request_retry(self):
        before = await self.snapshot(journal=True)
        result = await self.request("POST", f"{TRANSFER}/{self.committed['id']}/commit", json=self.commit_payload)
        self.check(result["id"] == self.committed["id"] and result["revision"] == self.committed["revision"], "same_commit_identity_revision")
        source, _ = await self.upload()
        self.check(source["id"] == self.committed["source_id"], "same_file_staging_dedup")
        self.check(await self.snapshot(journal=True) == before, "same_retry_zero_mutation")
        clone = await self.prepare("a19-combined")
        self.check(clone["source_id"] == self.committed["source_id"], "same_file_new_transfer_same_source")
        self.check(clone["preview"]["ready"] and all(row["outcome"] == "duplicate" for row in clone["preview"]["rows"]), "same_file_new_transfer_semantic_dedup")
        clone = await self.commit(clone)
        await self.rollback(clone)
        self.check(await self.snapshot() == {key: value for key, value in before.items() if key in (*TARGETS, "users")}, "same_file_new_transfer_no_target_mutation")

    async def reordered_semantic_retry(self):
        before = await self.snapshot()
        retry = await self.prepare("a19-combined", reordered=True)
        self.check(retry["source_id"] != self.committed["source_id"], "crossfile_distinct_bytes")
        self.check(retry["preview"]["ready"], "reordered_preview_ready")
        self.check(retry["preview"]["total_rows"] == 13, "reordered_all_rows")
        self.check(all(row["outcome"] == "duplicate" for row in retry["preview"]["rows"]), "reordered_semantic_all_duplicate")
        self.reused = await self.commit(retry)
        self.check(await self.snapshot() == before, "crossfile_zero_target_mutation")

    async def cross_batch_rollback_guard(self):
        self.check(self.reused is not None, "crossbatch_dependency_committed")
        before = await self.snapshot(journal=True)
        await self.rollback(self.committed, expected=409, code="rollback_cross_batch_reference")
        self.check(await self.snapshot(journal=True) == before, "crossbatch_block_zero_mutation")
        await self.rollback(self.reused)
        self.check(await self.snapshot() == {key: value for key, value in before.items() if key in (*TARGETS, "users")}, "reuse_rollback_preserves_original")

    async def owned_rollback(self):
        from sqlalchemy import text

        await self.rollback(self.committed)
        self.check(await self.snapshot() == self.base_snapshot, "owned_rollback_restores_exact_baseline")
        async with self.sessions() as db:
            self.check(await db.scalar(text("SELECT count(*) FROM audit_legacy_provenance WHERE active")) == 0, "rolled_back_provenance_inactive")
            self.check(await db.scalar(text("SELECT count(*) FROM audit_legacy_transfer_rows")) > 0, "rollback_journal_retained")

    async def stale_preview_after_live_edit(self):
        plan = await self.prepare("a19-stale", {"cases": [self.rows["cases"][0]]})
        self.check(plan["preview"]["ready"], "stale_initial_preview_ready")
        await self.request("PATCH", f"/api/audit/cases/{self.base_case}", json={"notes": "Synthetic live edit after preview"})
        before = await self.snapshot(journal=True)
        response = await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(response.get("detail", {}).get("code") == "stale_preview", "stale_preview_conflict_code")
        self.check(await self.snapshot(journal=True) == before, "stale_commit_atomic_no_mutation")

    async def rollback_after_live_edit(self):
        plan = await self.prepare("a19-rollback-edit", {"cases": [self.rows["cases"][1]]})
        committed = await self.commit(plan)
        new_case = plan["preview"]["rows"][0]["target_id"]
        await self.request("PATCH", f"/api/audit/cases/{new_case}", json={"notes": "Synthetic live edit after commit"})
        before = await self.snapshot(journal=True)
        await self.rollback(committed, expected=409, code="rollback_target_changed")
        self.check(await self.snapshot(journal=True) == before, "live_edit_rollback_zero_mutation")

    async def rollback_live_child_reference(self):
        from sqlalchemy import text

        # A separate namespace/case avoids dependencies on the previous guarded batch.
        rows = {"cases": [{"case_key": "NEW", "title": "Synthetic child owner", "digital_product": "Synthetic child product"}]}
        plan = await self.prepare("a19-live-child", rows)
        committed = await self.commit(plan)
        case_id = plan["preview"]["rows"][0]["target_id"]
        # Insert a real FK child without touching its parent, distinguishing child
        # reference guarding from parent updated_at/snapshot guarding.
        async with self.engine.begin() as connection:
            await connection.execute(text("INSERT INTO audit_events (id, case_id, event_type, message, actor_id, created_at) VALUES (:id, :case_id, 'acceptance_live_child', 'Synthetic live reference', :actor_id, now())"), {"id": uuid4(), "case_id": UUID(case_id), "actor_id": self.admin.id})
        before = await self.snapshot(journal=True)
        await self.rollback(committed, expected=409, code="rollback_live_reference")
        self.check(await self.snapshot(journal=True) == before, "live_child_rollback_zero_mutation")

    async def atomic_injected_failure(self):
        from sqlalchemy import text

        rows = {"cases": [{"case_key": "NEW", "title": "Synthetic atomic case", "digital_product": "Synthetic atomic product"}],
                "atoms": [{"case_key": "NEW", "atom_key": "FAIL-1", "title": "Synthetic injected failure", "state": "draft"}]}
        plan = await self.prepare("a19-injected-failure", rows)
        self.check(plan["preview"]["ready"], "injection_preview_ready")
        before = await self.snapshot(journal=True)
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE FUNCTION a19_acceptance_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic acceptance failure'; END $$"))
            await connection.execute(text("CREATE TRIGGER a19_acceptance_fail AFTER INSERT ON audit_atoms FOR EACH ROW WHEN (NEW.item_code = 'FAIL-1') EXECUTE FUNCTION a19_acceptance_fail()"))
        try:
            response = await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=503, json=self.payload(plan))
            self.check(response.get("detail", {}).get("code") == "transfer_storage_failed", "injected_failure_safe_error")
            self.check(await self.snapshot(journal=True) == before, "injected_failure_atomic_targets_provenance")
            state = await self.request("GET", f"{TRANSFER}/{plan['id']}")
            self.check(state["status"] == "previewed" and state["revision"] == plan["revision"], "injected_failure_draft_retriable")
        finally:
            async with self.engine.begin() as connection:
                await connection.execute(text("DROP TRIGGER a19_acceptance_fail ON audit_atoms"))
                await connection.execute(text("DROP FUNCTION a19_acceptance_fail()"))
        committed = await self.commit(plan)
        await self.rollback(committed)
        self.check(await self.snapshot() == {key: value for key, value in before.items() if key in (*TARGETS, "users")}, "injection_retry_rollback_restored")

    @staticmethod
    def small_rows():
        return {"cases": [{"case_key": "NEW", "title": "Synthetic transport case", "digital_product": "Synthetic transport product"}],
                "atoms": [{"case_key": "NEW", "atom_key": "TRANSPORT-1", "title": "Synthetic transport atom", "state": "draft"}]}

    def check_single_commit_delta(self, before, after):
        for table, delta in (("audit_cases", 1), ("audit_atoms", 1), ("audit_events", 1), ("audit_assignments", 0), ("audit_legacy_metrics", 0), ("users", 0), ("audit_team_members", 0), ("audit_legacy_provenance", 2), ("audit_legacy_transfer_rows", 3)):
            self.check(len(after[table]) - len(before[table]) == delta, "single_commit_exact_delta_" + table)

    async def concurrent_same_commit(self):
        plan = await self.prepare("a19-concurrent-same", self.small_rows())
        self.check(plan["preview"]["ready"], "concurrent_same_preview_ready")
        before = await self.snapshot(journal=True)
        start = asyncio.Event()

        async def commit_once():
            await start.wait()
            return await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan))

        tasks = [asyncio.create_task(commit_once()) for _ in range(2)]
        start.set()
        first, second = await asyncio.gather(*tasks)
        self.check(first["status"] == second["status"] == "committed", "concurrent_same_both_committed")
        self.check(first["id"] == second["id"] and first["revision"] == second["revision"], "concurrent_same_one_revision")
        self.check_single_commit_delta(before, await self.snapshot(journal=True))

    async def concurrent_cross_batch(self):
        first = await self.prepare("a19-concurrent-cross", self.small_rows())
        second = await self.prepare("a19-concurrent-cross", self.small_rows())
        self.check(first["preview"]["ready"] and second["preview"]["ready"], "concurrent_cross_both_preview_ready")
        before = await self.snapshot(journal=True)
        start = asyncio.Event()

        async def commit_once(plan):
            await start.wait()
            response = await asyncio.wait_for(self.client.post(f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan)), timeout=45)
            return plan, response

        tasks = [asyncio.create_task(commit_once(plan)) for plan in (first, second)]
        start.set()
        outcomes = await asyncio.gather(*tasks)
        self.check(sorted(response.status_code for _, response in outcomes) == [200, 409], "concurrent_cross_single_winner_stale_loser")
        loser, response = next(item for item in outcomes if item[1].status_code == 409)
        self.check(response.json().get("detail", {}).get("code") == "stale_preview", "concurrent_cross_loser_reason")
        self.check_single_commit_delta(before, await self.snapshot(journal=True))
        targets = await self.snapshot()
        loser = await self.preview(loser)
        self.check(loser["preview"]["ready"] and all(row["outcome"] == "duplicate" for row in loser["preview"]["rows"]), "concurrent_cross_repreview_duplicate")
        await self.commit(loser)
        self.check(await self.snapshot() == targets, "concurrent_cross_recovery_no_target_mutation")

    async def lost_commit_response(self):
        import httpx

        plan = await self.prepare("a19-lost-response", self.small_rows())
        self.check(plan["preview"]["ready"], "lost_response_preview_ready")
        before = await self.snapshot(journal=True)

        class DropResponse(httpx.AsyncBaseTransport):
            def __init__(self, app):
                self.inner = httpx.ASGITransport(app=app)

            async def handle_async_request(self, request):
                # Real handler and transaction finish, then only the transport fails.
                response = await self.inner.handle_async_request(request)
                await response.aread()
                await response.aclose()
                if response.status_code != 200:
                    raise CheckFailed("lost_response_initial_commit_status")
                raise httpx.ReadError("Synthetic response loss", request=request)

            async def aclose(self):
                await self.inner.aclose()

        lost = False
        async with httpx.AsyncClient(transport=DropResponse(self.app), base_url="http://localhost") as client:
            try:
                await asyncio.wait_for(client.post(f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan)), timeout=45)
            except httpx.ReadError:
                lost = True
        self.check(lost, "commit_response_actually_lost")
        after_loss = await self.snapshot(journal=True)
        self.check_single_commit_delta(before, after_loss)
        state = await self.request("GET", f"{TRANSFER}/{plan['id']}")
        self.check(state["status"] == "committed", "lost_response_server_committed")
        retry = await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan))
        self.check(retry["revision"] == state["revision"], "lost_response_retry_no_revision_bump")
        self.check(await self.snapshot(journal=True) == after_loss, "lost_response_retry_exact_no_mutation")

    async def load_1000_atoms(self):
        from sqlalchemy import text

        baseline = await self.snapshot()
        rows = deepcopy(self.rows)
        rows["cases"] = rows["cases"][1:]
        rows["atoms"] = [dict(self.rows["atoms"][0], case_key="NEW", atom_key=f"A-{index + 1}", title=f"Synthetic load atom {index + 1}") for index in range(1000)]
        for record in (*rows["assignments"], *rows["events"]):
            record["case_key"] = "NEW"
        started = perf_counter()
        plan = await self.prepare("a19-load-1000", rows)
        prepared = perf_counter()
        self.check(plan["preview"]["ready"], "load_preview_ready")
        self.check(plan["preview"]["total_rows"] == 1010, "load_preview_all_1010_rows")
        row_keys, offset = set(), 0
        while offset is not None:
            page = await self.request("GET", f"{TRANSFER}/{plan['id']}/preview/rows", params={"offset": offset, "limit": 500})
            for row in page["rows"]:
                self.check(row["row_key"] not in row_keys, "load_pagination_no_duplicate")
                row_keys.add(row["row_key"])
            next_offset = page["next_offset"]
            self.check(next_offset is None or next_offset > offset, "load_pagination_progress")
            offset = next_offset
        self.check(len(row_keys) == 1010, "load_pagination_complete")
        committing = perf_counter()
        committed = await self.commit(plan)
        committed_at = perf_counter()
        async with self.sessions() as db:
            params = {"transfer_id": UUID(committed["id"])}
            self.check(await db.scalar(text("SELECT count(*) FROM audit_atoms WHERE legacy_transfer_id = :transfer_id"), params) == 1000, "load_exact_1000_atoms")
            self.check(await db.scalar(text("SELECT count(*) FROM audit_events WHERE legacy_transfer_id = :transfer_id"), params) == 1005, "load_exact_1005_history_rows")
            self.check(await db.scalar(text("SELECT count(*) FROM audit_legacy_provenance WHERE transfer_id = :transfer_id"), params) == 1010, "load_exact_provenance")
        before_retry = await self.snapshot(journal=True)
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan))
        self.check(await self.snapshot(journal=True) == before_retry, "load_retry_exact_no_mutation")
        rolling_back = perf_counter()
        await self.rollback(committed)
        rolled_back_at = perf_counter()
        self.check(await self.snapshot() == baseline, "load_rollback_exact_baseline")
        print(f"PERF atoms=1000 datasets=5 rows=1010 prepare_ms={round((prepared - started) * 1000)} commit_ms={round((committed_at - committing) * 1000)} rollback_ms={round((rolled_back_at - rolling_back) * 1000)} total_ms={round((perf_counter() - started) * 1000)}", flush=True)

    async def alias_fill_empty_rollback(self):
        from app.models.audit import AuditAtom

        async with self.sessions() as db:
            atom = AuditAtom(case_id=self.base_case, item_code="LIVE-ALIAS", title="Synthetic alias target", digital_product="Synthetic existing product", state="draft")
            db.add(atom)
            await db.commit()
            atom_id = atom.id
        baseline = await self.snapshot()
        rows = {"cases": [{"case_key": key, "title": "Synthetic existing case", "digital_product": "Synthetic existing product"} for key in ("DETAIL", "NEW")],
                "atoms": [
                    {"case_key": "DETAIL", "atom_key": "ALIAS-1", "title": "Synthetic alias target", "state": "draft", "work_type": "Synthetic filled work"},
                    {"case_key": "NEW", "atom_key": "ALIAS-2", "title": "Synthetic alias target", "state": "draft", "object_type": "Synthetic filled object"},
                ]}
        decision = {"mode": "existing", "target_case_id": str(self.base_case)}
        plan = await self.prepare("a19-alias-fill", rows, decisions={"DETAIL": decision, "NEW": decision})
        config = deepcopy(plan["config"])
        for row in plan["preview"]["rows"]:
            if row["kind"] == "atoms":
                config["row_decisions"][row["row_key"]] = {"action": "fill_empty", "target_id": str(atom_id), "fill_empty": ["work_type" if row["row"] == 2 else "object_type"]}
        plan = await self.configure(plan, config)
        plan = await self.preview(plan)
        committed = await self.commit(plan)
        async with self.sessions() as db:
            current = await db.get(AuditAtom, atom_id)
            self.check(current.work_type == "Synthetic filled work" and current.object_type == "Synthetic filled object", "aliases_both_fields_persisted")
        await self.rollback(committed)
        self.check(await self.snapshot() == baseline, "aliases_rollback_restores_both_original_fields")

    def projection_events(self):
        return [
            {"case_key": "NEW", "atom_key": "TRANSPORT-1", "event_key": "PROJECTION-READY", "event_type": "atom_status_changed", "occurred_at": (self.today - timedelta(days=7)).isoformat(), "previous_state": "draft", "state": "ready", "actor_name": HISTORICAL_ACTOR},
            {"case_key": "NEW", "atom_key": "TRANSPORT-1", "event_key": "PROJECTION-ALPHA", "event_type": "alpha_reviewed", "occurred_at": (self.today - timedelta(days=6)).isoformat(), "alpha_result": "present", "actor_name": HISTORICAL_ACTOR},
            {"case_key": "NEW", "atom_key": "TRANSPORT-1", "event_key": "PROJECTION-COMMISSION", "event_type": "commission_reviewed", "occurred_at": (self.today - timedelta(days=5)).isoformat(), "commission_result": "confirmed", "actor_name": HISTORICAL_ACTOR},
        ]

    async def event_only_final_projection(self):
        from sqlalchemy import select
        from app.models.audit import AuditAtom

        baseline = await self.snapshot()
        rows = self.small_rows()
        del rows["atoms"][0]["state"]
        rows["events"] = self.projection_events()
        plan = await self.prepare("a19-event-projection", rows)
        committed = await self.commit(plan)
        case_id = next(row["target_id"] for row in plan["preview"]["rows"] if row["kind"] == "cases")
        async with self.sessions() as db:
            atom = await db.scalar(select(AuditAtom).where(AuditAtom.case_id == UUID(case_id)))
            self.check(atom.state == "ready", "event_only_projects_ready")
            self.check(atom.alpha_result == "present" and atom.commission_result == "confirmed", "event_only_projects_alpha_commission")
            self.check(atom.alpha_date == self.today - timedelta(days=6) and atom.commission_date == self.today - timedelta(days=5), "event_only_projects_business_dates")
        case = await self.request("GET", f"/api/audit/cases/{case_id}")
        self.check(len(case["atoms"]) == 1 and case["atoms"][0]["state"] == "ready", "event_only_projection_api_visible")
        await self.rollback(committed)
        self.check(await self.snapshot() == baseline, "event_only_new_atom_rollback_exact")
        contradictory = deepcopy(rows)
        contradictory["atoms"][0]["state"] = "excluded"
        plan = await self.prepare("a19-event-contradiction", contradictory)
        self.check(not plan["preview"]["ready"], "event_snapshot_contradiction_blocked")
        self.check("snapshot_state_conflict" in {issue["code"] for issue in plan["preview"]["issues"]}, "event_snapshot_contradiction_issue")
        await self.request("POST", f"{TRANSFER}/{plan['id']}/commit", expected=409, json=self.payload(plan))
        self.check(await self.snapshot() == baseline, "event_snapshot_contradiction_no_mutation")

    async def reference_only_case_reuse(self):
        first = await self.prepare("a19-reference-only", self.small_rows())
        await self.commit(first)
        case_id = next(row["target_id"] for row in first["preview"]["rows"] if row["kind"] == "cases")
        mapping_key = next(iter(first["config"]["cases"]))
        rows = {"events": self.projection_events()}
        source, datasets = await self.upload(rows)
        config = self.config(datasets, "a19-reference-only")
        config["cases"] = {mapping_key: {"mode": "existing", "target_case_id": case_id}}
        plan = await self.request("POST", TRANSFER, json={"source_id": source["id"], "config": config})
        plan = await self.preview(plan)
        self.check(plan["preview"]["ready"], "reference_only_case_not_source_conflict")
        before = await self.snapshot()
        await self.commit(plan)
        after = await self.snapshot()
        self.check(len(after["audit_cases"]) == len(before["audit_cases"]), "reference_only_no_new_case")
        self.check(len(after["audit_atoms"]) == len(before["audit_atoms"]), "reference_only_no_new_atom")
        self.check(len(after["audit_events"]) - len(before["audit_events"]) == 3, "reference_only_three_events_added")

    async def unrelated_writes_not_blocked(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from app.models.audit import AuditCase

        async with self.sessions() as db:
            unrelated = AuditCase(title="Synthetic unrelated lock case", digital_product="Synthetic unrelated product", created_by_id=self.admin.id)
            db.add(unrelated)
            await db.commit()
            unrelated_id = unrelated.id
        plan = await self.prepare("a19-lock-scope", self.small_rows())
        self.check(plan["preview"]["ready"], "lock_scope_preview_ready")
        gate_key = 19861983
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE FUNCTION a19_acceptance_gate() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(19861983); RETURN NEW; END $$"))
            await connection.execute(text("CREATE TRIGGER a19_acceptance_gate AFTER INSERT ON audit_atoms FOR EACH ROW WHEN (NEW.item_code = 'TRANSPORT-1') EXECUTE FUNCTION a19_acceptance_gate()"))
        blocked, errors, request_task, response = [], [], None, None
        observed = False
        try:
            async with self.engine.connect() as holder:
                await holder.execute(text("SELECT pg_advisory_lock(:gate)"), {"gate": gate_key})
                try:
                    request_task = asyncio.create_task(self.client.post(f"{TRANSFER}/{plan['id']}/commit", json=self.payload(plan)))
                    for _ in range(100):
                        async with self.engine.connect() as observer:
                            observed = bool(await observer.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :gate AND NOT granted AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"), {"gate": gate_key}))
                        if observed or request_task.done():
                            break
                        await asyncio.sleep(0.05)
                    if observed:
                        for label, statement, identifier in (
                            ("unrelated_user", "UPDATE users SET full_name = 'Synthetic temporary lock check' WHERE id = :id", self.users["nonmember"]),
                            ("unrelated_case", "UPDATE audit_cases SET notes = 'Synthetic temporary lock check' WHERE id = :id", unrelated_id),
                        ):
                            async with self.engine.connect() as writer:
                                transaction = await writer.begin()
                                try:
                                    await writer.execute(text("SET LOCAL lock_timeout = '700ms'"))
                                    await writer.execute(text(statement), {"id": identifier})
                                except DBAPIError as error:
                                    if getattr(error.orig, "sqlstate", None) == "55P03":
                                        blocked.append(label)
                                    else:
                                        errors.append(label)
                                finally:
                                    await transaction.rollback()
                finally:
                    await holder.execute(text("SELECT pg_advisory_unlock(:gate)"), {"gate": gate_key})
                    if request_task is not None:
                        try:
                            response = await asyncio.wait_for(request_task, timeout=45)
                        finally:
                            if not request_task.done():
                                request_task.cancel()
                                await asyncio.gather(request_task, return_exceptions=True)
        finally:
            async with self.engine.begin() as connection:
                await connection.execute(text("DROP TRIGGER a19_acceptance_gate ON audit_atoms"))
                await connection.execute(text("DROP FUNCTION a19_acceptance_gate()"))
        self.check(observed, "lock_scope_real_commit_reached_gate")
        self.check(response is not None and response.status_code == 200, "lock_scope_commit_completed")
        for label in blocked:
            print(f"LOCK_BLOCKED {label} lock_timeout_ms=700", flush=True)
        self.check(not errors, "lock_scope_unrelated_write_unexpected_error")
        self.check(not blocked, "lock_scope_unrelated_writes_blocked")

    async def scoped_lock_helper_pg(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from app.models.audit import AuditCase
        from app.services.audit_legacy_locks import lock_legacy_targets

        async with self.sessions() as db:
            cases = [AuditCase(title=f"Synthetic helper case {index}", digital_product="Synthetic helper product", created_by_id=self.admin.id) for index in range(2)]
            db.add_all(cases)
            await db.commit()
            case_a, case_b = [case.id for case in cases]
        baseline = await self.snapshot()
        async with self.sessions() as holder:
            await lock_legacy_targets(holder, [case_a], [self.users["eligible"]])
            try:
                for label, statement, params, should_wait in (
                    ("unrelated_user", "UPDATE users SET full_name = 'Synthetic helper temporary' WHERE id = :id", {"id": self.users["nonmember"]}, False),
                    ("unrelated_case", "UPDATE audit_cases SET notes = 'Synthetic helper temporary' WHERE id = :id", {"id": case_b}, False),
                    ("target_user", "UPDATE users SET full_name = 'Synthetic helper temporary' WHERE id = :id", {"id": self.users["eligible"]}, True),
                    ("target_case", "UPDATE audit_cases SET notes = 'Synthetic helper temporary' WHERE id = :id", {"id": case_a}, True),
                    ("target_child_fk", "INSERT INTO audit_events (id, case_id, event_type, message, created_at) VALUES (:id, :case_id, 'helper_child', 'Synthetic helper child', now())", {"id": uuid4(), "case_id": case_a}, True),
                ):
                    sqlstate = None
                    async with self.engine.connect() as writer:
                        transaction = await writer.begin()
                        try:
                            await writer.execute(text("SET LOCAL statement_timeout = '1000ms'"))
                            await writer.execute(text(statement), params)
                        except DBAPIError as error:
                            sqlstate = getattr(error.orig, "sqlstate", None)
                        finally:
                            await transaction.rollback()
                    self.check(sqlstate == "57014" if should_wait else sqlstate is None, "scoped_helper_" + label)
            finally:
                await holder.rollback()
        self.check(await self.snapshot() == baseline, "scoped_helper_no_fixture_mutation")
        print("LOCK_SCOPE unrelated_updates=2 target_waits=2 child_fk_waits=1 statement_timeout_ms=1000", flush=True)

    async def synthetic_contract_reference_privacy(self):
        from app.models.audit import AuditCase
        from app.services.audit_contract_reference import AuditContractReferenceError, decrypt_contract_reference

        full_number = "SYNTHETIC-A19-CONTRACT-2026-987654321"
        rows = self.small_rows()
        rows["cases"][0]["contract_reference"] = full_number
        baseline = await self.snapshot()
        plan = await self.prepare("a19-source-privacy", rows)
        self.check(plan["preview"]["ready"], "privacy_preview_ready")
        self.check(full_number not in json.dumps(plan), "privacy_preview_no_full_number")
        page = await self.request("GET", f"{TRANSFER}/{plan['id']}/preview/rows")
        self.check(full_number not in json.dumps(page), "privacy_preview_page_no_full_number")
        try:
            committed = await self.commit(plan)
        except AuditContractReferenceError as error:
            if error.code == "encryption_key_not_configured":
                raise Blocked("local_contract_reference_encryption_not_configured") from None
            raise
        self.check(full_number not in json.dumps(committed), "privacy_commit_response_no_full_number")
        case_id = next(row["target_id"] for row in plan["preview"]["rows"] if row["kind"] == "cases")
        async with self.sessions() as db:
            case = await db.get(AuditCase, UUID(case_id))
            self.check(bool(case.contract_reference_mask) and case.contract_reference_mask != full_number, "privacy_target_mask_persisted")
            self.check(bool(case.contract_reference_ciphertext) and full_number not in case.contract_reference_ciphertext, "privacy_target_encrypted_not_plaintext")
            self.check(bool(case.contract_reference_fingerprint) and len(case.contract_reference_fingerprint) == 64, "privacy_target_fingerprint_persisted")
            try:
                self.check(decrypt_contract_reference(case.contract_reference_ciphertext) == full_number, "privacy_runtime_encryption_roundtrip")
            except AuditContractReferenceError as error:
                if error.code == "encryption_key_not_configured":
                    raise Blocked("local_contract_reference_encryption_not_configured") from None
                raise
        for path in (f"/api/audit/cases/{case_id}", "/api/audit/cases", f"/api/audit/cases/{case_id}/events", f"{TRANSFER}/{plan['id']}", f"{TRANSFER}/options", f"{SOURCE}/{plan['source_id']}"):
            response = await self.request("GET", path)
            self.check(full_number not in json.dumps(response), "privacy_normal_reads_no_full_number")
        await self.rollback(committed)
        self.check(await self.snapshot() == baseline, "privacy_rollback_exact_baseline")

    async def run(self):
        import httpx
        from app.api.deps import get_current_user, get_db

        await self.seed()
        previous = dict(self.app.dependency_overrides)

        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

        async def current_user():
            return self.admin

        self.app.dependency_overrides[get_db] = database
        self.app.dependency_overrides[get_current_user] = current_user
        try:
            # ASGITransport does not start lifespan. All requests stay in process.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://localhost", timeout=45) as client:
                self.client = client
                required_ok = await self.results.scenario("combined_preview_resolution", self.combined_preview_resolution)
                await self.results.scenario("assignment_eligibility", self.assignment_eligibility)
                await self.results.scenario("aggregate_overlap", self.aggregate_overlap)
                await self.results.scenario("invalid_taxonomy", self.invalid_taxonomy)
                await self.results.scenario("late_error_after_issue_cap", self.late_error_after_issue_cap)
                if required_ok:
                    required_ok = await self.results.scenario("combined_commit_persistence", self.combined_commit_persistence)
                if self.committed is not None:
                    await self.results.scenario("same_request_retry", self.same_request_retry)
                    reused_ok = await self.results.scenario("reordered_semantic_retry", self.reordered_semantic_retry)
                    if reused_ok:
                        await self.results.scenario("cross_batch_rollback_guard", self.cross_batch_rollback_guard)
                    await self.results.scenario("owned_rollback", self.owned_rollback)
                # Independent cases continue even when a combined acceptance fails.
                await self.results.scenario("stale_preview_after_live_edit", self.stale_preview_after_live_edit)
                await self.results.scenario("rollback_after_live_edit", self.rollback_after_live_edit)
                await self.results.scenario("rollback_live_child_reference", self.rollback_live_child_reference)
                await self.results.scenario("atomic_injected_failure", self.atomic_injected_failure)
                await self.results.scenario("concurrent_same_commit", self.concurrent_same_commit)
                await self.results.scenario("concurrent_cross_batch", self.concurrent_cross_batch)
                await self.results.scenario("lost_commit_response", self.lost_commit_response)
                await self.results.scenario("load_1000_atoms", self.load_1000_atoms)
                await self.results.scenario("alias_fill_empty_rollback", self.alias_fill_empty_rollback)
                await self.results.scenario("event_only_final_projection", self.event_only_final_projection)
                await self.results.scenario("reference_only_case_reuse", self.reference_only_case_reuse)
                await self.results.scenario("unrelated_writes_not_blocked", self.unrelated_writes_not_blocked)
                await self.results.scenario("scoped_lock_helper_pg", self.scoped_lock_helper_pg)
                await self.results.scenario("synthetic_contract_reference_privacy", self.synthetic_contract_reference_privacy)
                await self.results.scenario("archived_case_assignment_policy", self.archived_case_assignment_policy)
                await self.results.scenario("assignment_timestamp_semantics", self.assignment_timestamp_semantics)
        finally:
            self.app.dependency_overrides.clear()
            self.app.dependency_overrides.update(previous)


async def execute(args, results):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.config import settings

    runtime_url = make_url(settings.DATABASE_URL)
    ensure_safe_target(runtime_url, args.allow_create_database)
    if settings.DB_SCHEMA:
        raise Blocked("default_public_schema_required")
    name = "dpms_a19_acceptance_" + uuid4().hex[:12]
    check_temp_name(name)
    admin_url = runtime_url.set(drivername="postgresql+asyncpg", database="postgres")
    temporary_url = runtime_url.set(drivername="postgresql+asyncpg", database=name)
    created, engine = False, None
    try:
        await database_lifecycle(admin_url, name)
        created = True
        # Fence even accidental application global sessions into the disposable DB.
        settings.DATABASE_URL = temporary_url.render_as_string(hide_password=False)
        settings.DEBUG = False
        engine = create_async_engine(temporary_url, echo=False, hide_parameters=True,
                                     connect_args={"timeout": 10, "server_settings": {"statement_timeout": "30000", "lock_timeout": "10000"}})
        await migrate(engine, results)
        from app.main import app
        from app.database import engine as application_engine
        results.check(application_engine.url.database == name, "application_global_engine_fenced")
        paths = app.openapi()["paths"]
        if TRANSFER not in paths or f"{TRANSFER}/{{transfer_id}}/commit" not in paths:
            raise Blocked("transfer_routes_not_registered_rebuild_backend")
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        suite = Acceptance(engine, sessions, app, results)
        await suite.run()
    finally:
        if engine is not None:
            await engine.dispose()
        module = sys.modules.get("app.database")
        if module is not None:
            await module.engine.dispose()
        if created:
            try:
                await database_lifecycle(admin_url, name, drop=True)
            except Exception:
                # The generated name is safe and necessary for precise cleanup.
                print(f"BLOCKED disposable_database_cleanup_failed database={name}", flush=True)
                raise Blocked("disposable_database_cleanup_failed") from None
            print("PASS disposable_database_dropped", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-create-database", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--check-fixtures", action="store_true", help="Check synthetic workbook normalization only, without a DB")
    args = parser.parse_args()
    if not 30 <= args.timeout_seconds <= 900:
        parser.error("timeout must be between 30 and 900 seconds")
    logging.disable(logging.CRITICAL)
    results = Results()
    blocker = None
    try:
        if args.check_fixtures:
            from app.services.audit_legacy_workbook import normalize_legacy_datasets
            rows = combined_rows(date(2026, 9, 8))
            original, mapping = workbook(rows)
            reordered, remapping = workbook(rows, reordered=True)
            first = normalize_legacy_datasets(original, mapping)
            second = normalize_legacy_datasets(reordered, remapping)
            results.check(original != reordered, "fixture_distinct_bytes")
            results.check(first["error_count"] == second["error_count"] == 0, "fixture_normalization_errors")
            results.check(first["total_rows"] == second["total_rows"] == 13, "fixture_normalization_rows")
            canonical = lambda result: sorted(json.dumps({"kind": row["kind"], "values": {key: value for key, value in row["values"].items() if value is not None}}, sort_keys=True) for row in result["records"])
            results.check(canonical(first) == canonical(second), "fixture_reordered_same_semantics")
            print(f"PASS fixture_preflight checks={results.checks} datasets=5 rows=13 db_created=0", flush=True)
            return 0
        asyncio.run(asyncio.wait_for(execute(args, results), timeout=args.timeout_seconds))
    except Blocked as error:
        blocker = str(error)
    except CheckFailed as error:
        blocker = f"preflight_check_{error}"
    except Exception as error:
        blocker = f"exception_type_{type(error).__name__}"
        print(f"locations={safe_exception_location(error)}", flush=True)
    skipped = len(SCENARIOS) - len(results.passed) - len(results.failed)
    status = "BLOCKED" if blocker else "FAIL" if results.failed or skipped else "PASS"
    print(f"{status} A1.9 acceptance scenarios_passed={len(results.passed)} scenarios_failed={len(results.failed)} scenarios_not_run={skipped} checks={results.checks}", flush=True)
    if blocker:
        print(f"blocker={blocker}", flush=True)
    return 0 if status == "PASS" else 2 if status == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
