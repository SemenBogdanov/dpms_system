"""Business-time aggregation and read API tests using synthetic, isolated data."""

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, JSON, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.dialects.postgresql import UUID as SQLUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.api.routes import audit as routes
from app.models.audit import AuditAtom, AuditCase, AuditEvent
from app.models.audit_legacy_transfer import AuditLegacyMetric, AuditLegacyTransfer
from app.models.user import UserRole
from app.services.audit_statistics import (
    AuditStatisticsAtomRecord as Atom,
    AuditStatisticsCaseRecord as Case,
    AuditStatisticsLegacyMetric as Metric,
    AuditStatisticsReviewEvent as ReviewEvent,
    AuditStatisticsStateEvent as StateEvent,
    build_audit_statistics,
    period_start_utc,
)


def instant(day, hour=9, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


class LegacyStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.case = Case(uuid4(), "atomization", "alpha_review")
        self.transfer = uuid4()

    def atom(self, *, state="ready", effective=None, legacy=True):
        return Atom(uuid4(), self.case.id, state, "present", "confirmed", instant(8),
                    self.transfer if legacy else None, effective)

    def event(self, atom, day, previous="draft", state="ready", *, legacy=True):
        return StateEvent(atom.id, instant(8), previous, state,
                          instant(day) if day else None, self.transfer if legacy else None)

    def build(self, atoms, events=(), metrics=(), start=1, end=8, review_events=()):
        return build_audit_statistics([self.case], atoms, events, metrics=metrics,
                                     review_events=review_events,
                                     period_start=date(2026, 9, start), period_end=date(2026, 9, end))

    def test_undated_snapshot_changes_current_counts_not_import_day(self):
        result = self.build([self.atom()])
        self.assertEqual(result["atoms"]["verified"], 1)
        self.assertEqual(result["atoms"]["alpha_review_completed"], 1)
        self.assertEqual(result["undated_legacy_atoms"], 1)
        self.assertTrue(all(point["verified_count"] == point["cumulative_verified_count"] == 0
                            for point in result["trend"]))

    def test_confirmed_verification_date_seeds_day_and_prior_baseline(self):
        atom = self.atom(effective=instant(2))
        result = self.build([atom])
        self.assertEqual([point["verified_count"] for point in result["trend"]], [0, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result["undated_legacy_atoms"], 0)
        prior = self.build([atom], start=4)
        self.assertTrue(all(point["cumulative_verified_count"] == 1 for point in prior["trend"]))
        self.assertTrue(all(point["verified_count"] == 0 for point in prior["trend"]))

    def test_explicit_history_replaces_dated_or_undated_snapshot(self):
        for effective in (None, instant(1), instant(3), instant(5)):
            with self.subTest(effective=effective):
                atom = self.atom(effective=effective)
                result = self.build([atom], [self.event(atom, 3)])
                self.assertEqual([point["verified_count"] for point in result["trend"]], [0, 0, 1, 0, 0, 0, 0, 0])
                self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 1)
                self.assertEqual(result["undated_legacy_atoms"], 0)

    def test_old_historical_event_is_baseline_not_recent_import(self):
        atom = self.atom(effective=instant(6))
        result = self.build([atom], [self.event(atom, 2)], start=4)
        self.assertTrue(all(point["verified_count"] == 0 and point["cumulative_verified_count"] == 1
                            for point in result["trend"]))

    def test_source_history_mapped_to_existing_live_atom_has_no_creation_duplicate(self):
        atom = self.atom(legacy=False)
        result = self.build([atom], [self.event(atom, 2)])
        self.assertEqual(result["trend"][1]["verified_count"], 1)
        self.assertEqual(result["trend"][-1]["verified_count"], 0)
        self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 1)

    def test_live_transition_after_unknown_legacy_date_is_counted(self):
        atom = self.atom()
        result = self.build([atom], [self.event(atom, None), self.event(atom, 7, legacy=False)])
        self.assertEqual(result["undated_legacy_atoms"], 1)
        self.assertEqual(result["trend"][6]["verified_count"], 1)
        self.assertEqual(result["trend"][-1]["verified_count"], 0)
        self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 1)

    def test_unknown_exclusion_cannot_subtract_known_other_atom(self):
        known = self.atom(effective=instant(1))
        unknown = self.atom(state="excluded")
        result = self.build([known, unknown], [self.event(unknown, 5, "ready", "excluded", legacy=False)])
        self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 1)
        self.assertEqual(result["atoms"]["verified"], 1)

    def test_live_creation_fallback_and_occurred_at_override(self):
        atom = replace(self.atom(legacy=False), created_at=instant(1))
        for occurred, expected_index in ((None, 7), (instant(3), 2)):
            event = replace(self.event(atom, None, legacy=False), occurred_at=occurred)
            result = self.build([atom], [event])
            self.assertEqual(sum(point["verified_count"] for point in result["trend"]), 1)
            self.assertEqual(result["trend"][expected_index]["verified_count"], 1)

    def test_moscow_midnight_and_naive_utc(self):
        self.assertEqual(period_start_utc(date(2026, 9, 2)), instant(1, 21))
        for effective, index in ((instant(1, 20, 59), 0), (instant(1, 21), 1),
                                 (instant(1, 21).replace(tzinfo=None), 1)):
            with self.subTest(effective=effective):
                atom = self.atom(effective=effective)
                result = self.build([atom])
                self.assertEqual(result["trend"][index]["verified_count"], 1)
                historical = replace(self.event(atom, 1), occurred_at=effective)
                self.assertEqual(self.build([atom], [historical])["trend"][index]["verified_count"], 1)

    def test_future_transition_does_not_rewrite_past_current_totals_remain_current(self):
        atom = self.atom(state="excluded", effective=instant(2))
        result = self.build([atom], [self.event(atom, 8, "ready", "excluded", legacy=False)], end=7)
        self.assertEqual(result["atoms"]["excluded"], 1)
        self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 1)

    def test_mixed_and_aggregate_only_do_not_create_atoms_or_change_pipeline_counts(self):
        metrics = [Metric(self.case.id, date(2026, 9, 2), kind, value) for kind, value in (
            ("verified", 90), ("alpha_reviewed", 70), ("commission_reviewed", 50),
        )]
        for atoms in ([], [self.atom(), self.atom(effective=instant(2)), self.atom(legacy=False)]):
            result = self.build(atoms, metrics=metrics)
            without = self.build(atoms)
            for key in ("atoms", "contracts", "trend"):
                self.assertEqual(result[key], without[key])
            self.assertEqual(result["aggregate_trend"][1], {
                "date": "2026-09-02", "verified_count": None if atoms else 90,
                "alpha_reviewed_count": 70, "commission_reviewed_count": 50,
            })
        self.assertEqual(self.build([], metrics=[Metric(uuid4(), date(2026, 9, 2), "verified", 9)])["aggregate_trend"], [])

    def test_all_snapshot_states_and_date_presence_agree_with_aggregate_coverage(self):
        for state in ("draft", "ready", "excluded"):
            for dated in (False, True):
                for kind in ("verified", "alpha_reviewed", "commission_reviewed"):
                    with self.subTest(state=state, dated=dated, metric=kind):
                        atom = self.atom(state=state, effective=instant(2) if dated else None)
                        metric = Metric(self.case.id, date(2026, 9, 2), kind, 90)
                        result = self.build([atom], metrics=[metric])
                        verified = int(state == "ready" and dated)
                        conflict = int(bool(verified) and kind == "verified")
                        self.assertEqual(sum(p["verified_count"] for p in result["trend"]), verified)
                        self.assertEqual(result["atoms"]["verified"], int(state == "ready"))
                        self.assertEqual(result["aggregate_conflict_count"], conflict)
                        self.assertEqual(result["undated_legacy_atoms"], int(not dated))
                        if conflict:
                            self.assertEqual([point[f"{kind}_count"] for point in result["aggregate_trend"]], [None] * 8)
                        else:
                            self.assertEqual(result["aggregate_trend"][1][f"{kind}_count"], 90)

    def test_actual_snapshot_state_wins_over_later_current_state(self):
        atom = replace(self.atom(effective=instant(2)), legacy_snapshot_state="draft")
        result = self.build([atom])
        self.assertEqual(result["atoms"]["verified"], 1)
        self.assertEqual(sum(p["verified_count"] for p in result["trend"]), 0)
        initially_ready = replace(atom, state="excluded", legacy_snapshot_state="ready")
        metric = Metric(self.case.id, date(2026, 9, 2), "verified", 90)
        result = self.build([initially_ready], [self.event(initially_ready, 7, "ready", "excluded", legacy=False)], [metric])
        self.assertEqual(result["atoms"]["verified"], 0)
        self.assertEqual(result["trend"][1]["verified_count"], 1)
        self.assertEqual(result["trend"][-1]["cumulative_verified_count"], 0)
        self.assertEqual(result["aggregate_conflict_count"], 1)

    def test_explicit_history_moves_verification_coverage_off_snapshot_date(self):
        atom = self.atom(effective=instant(5))
        metrics = [Metric(self.case.id, date(2026, 9, day), "verified", 90) for day in (2, 5)]
        result = self.build([atom], [self.event(atom, 2)], metrics)
        self.assertEqual(result["aggregate_conflict_count"], 1)
        self.assertIsNone(result["aggregate_trend"][1]["verified_count"])
        self.assertEqual(result["aggregate_trend"][4]["verified_count"], 90)

    def test_backdated_review_coverage_is_metric_and_day_scoped(self):
        atom = replace(self.atom(), alpha_date=date(2026, 9, 2), commission_date=date(2026, 9, 3))
        metrics = [Metric(self.case.id, date(2026, 9, day), kind, 90)
                   for day in (2, 3) for kind in ("verified", "alpha_reviewed", "commission_reviewed")]
        result = self.build([atom], metrics=metrics)
        self.assertEqual(result["aggregate_conflict_count"], 2)
        self.assertIsNone(result["aggregate_trend"][1]["alpha_reviewed_count"])
        self.assertEqual(result["aggregate_trend"][1]["commission_reviewed_count"], 90)
        self.assertEqual(result["aggregate_trend"][2]["alpha_reviewed_count"], 90)
        self.assertIsNone(result["aggregate_trend"][2]["commission_reviewed_count"])
        absent_results = replace(atom, alpha_result=None, commission_result=None)
        self.assertEqual(self.build([absent_results], metrics=metrics)["aggregate_conflict_count"], 0)
        history = [ReviewEvent(atom.id, date(2026, 9, 2), "alpha_reviewed")]
        self.assertEqual(self.build([absent_results], metrics=metrics, review_events=history)["aggregate_conflict_count"], 1)

    def test_same_day_reverification_preserves_daily_and_net_counts(self):
        atom = self.atom()
        events = [self.event(atom, 3), self.event(atom, 3, "ready", "draft"), self.event(atom, 3)]
        point = self.build([atom], events)["trend"][2]
        self.assertEqual(point["verified_count"], 2)
        self.assertEqual(point["cumulative_verified_count"], 1)

    def test_aggregate_full_and_partial_exclusion_are_gaps_but_explicit_zero_is_retained(self):
        other_case = replace(self.case, id=uuid4())
        atom = replace(self.atom(effective=instant(1)),
                       alpha_date=date(2026, 9, 1), commission_date=date(2026, 9, 1))
        for kind in ("verified", "alpha_reviewed", "commission_reviewed"):
            for partial in (False, True):
                with self.subTest(kind=kind, partial=partial):
                    metrics = [Metric(self.case.id, date(2026, 9, day), kind, value)
                               for day, value in ((1, 100), (2, 7), (3, 0))]
                    if partial:
                        metrics.append(Metric(other_case.id, date(2026, 9, 1), kind, 5))
                    other_kind = "alpha_reviewed" if kind == "verified" else "verified"
                    metrics.append(Metric(other_case.id, date(2026, 9, 1), other_kind, 11))
                    result = build_audit_statistics(
                        [self.case, other_case], [atom], [], metrics=metrics,
                        period_start=date(2026, 9, 1), period_end=date(2026, 9, 4),
                    )
                    self.assertEqual(result["aggregate_conflict_count"], 1)
                    self.assertEqual([point[f"{kind}_count"] for point in result["aggregate_trend"]],
                                     [None, 7, 0, None])
                    self.assertEqual(result["aggregate_trend"][0][f"{other_kind}_count"], 11)
                    self.assertEqual(metrics[0].value, 100)


class LegacyStatisticsReadAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        metadata = MetaData()
        self.tables = {}
        for model, columns in (
            (AuditCase, ("id", "status", "workflow_stage")),
            (AuditAtom, ("id", "case_id", "state", "alpha_result", "commission_result", "created_at", "legacy_transfer_id", "legacy_effective_at", "alpha_date", "commission_date")),
        ):
            table = Table(model.__tablename__, metadata, *[
                Column(name, model.__table__.c[name].type, primary_key=name == "id") for name in columns
            ])
            self.tables[model] = table
        self.users = Table("users", metadata, Column("id", SQLUUID(as_uuid=True), primary_key=True), Column("full_name", String))
        Table("audit_import_batches", metadata, Column("id", SQLUUID(as_uuid=True), primary_key=True))
        self.sources = Table("audit_legacy_imports", metadata, Column("id", SQLUUID(as_uuid=True), primary_key=True))
        for model in (AuditLegacyTransfer, AuditLegacyMetric, AuditEvent):
            self.tables[model] = model.__table__.to_metadata(metadata)
        self.tables[AuditEvent].c.payload_json.type = JSON()
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        self.case_id, self.other_case_id, self.user_id, self.source_id, self.transfer_id = [uuid4() for _ in range(5)]
        self.user = SimpleNamespace(id=self.user_id, role=UserRole.admin)
        async with self.sessions.begin() as db:
            await db.execute(insert(self.users).values(id=self.user_id, full_name="Import administrator"))
            await db.execute(insert(self.sources).values(id=self.source_id))
            await db.execute(insert(self.tables[AuditCase]), [
                dict(id=case_id, status="atomization", workflow_stage="alpha_review")
                for case_id in (self.case_id, self.other_case_id)
            ])
            await db.execute(insert(self.tables[AuditLegacyTransfer]).values(
                id=self.transfer_id, source_id=self.source_id, namespace="synthetic",
                config={}, status="committed",
            ))

        async def database():
            async with self.sessions() as db:
                yield db

        async def member():
            return self.user

        app = FastAPI()
        app.include_router(routes.router, prefix="/api/audit")
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[routes.require_audit_workspace_member] = member
        self.app = app
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.case_patch = patch.object(routes, "_get_case_or_404", new=AsyncMock(return_value=SimpleNamespace(id=self.case_id)))
        self.case_patch.start()
        self.period_patch = patch.object(routes, "statistics_period", return_value=(date(2026, 9, 1), date(2026, 9, 8)))
        self.period_patch.start()

    async def asyncTearDown(self):
        self.period_patch.stop()
        self.case_patch.stop()
        await self.client.aclose()
        await self.engine.dispose()

    async def add_event(self, **overrides):
        values = dict(id=uuid4(), case_id=self.case_id, actor_id=self.user_id,
                      legacy_transfer_id=self.transfer_id, occurred_at=instant(2),
                      historical_actor_name="Historical reviewer", event_type="atom_status_changed",
                      message="Historical status change", created_at=instant(8),
                      payload_json={"previous_state": "draft", "state": "ready",
                                    "raw_source": "not public", "workbook": {"other_case": "not public"},
                                    "rows": [{"other_case": "not public"}], "fields": {"raw_source": "not public"}})
        values.update(overrides)
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditEvent]).values(**values))
        return values["id"]

    async def test_history_business_order_unknown_actor_and_admin_only_source(self):
        older = await self.add_event()
        unknown = await self.add_event(occurred_at=None, historical_actor_name=None)
        live = await self.add_event(legacy_transfer_id=None, occurred_at=None, historical_actor_name=None, created_at=instant(5))
        await self.add_event(case_id=self.other_case_id)
        for role in (UserRole.admin, UserRole.teamlead, UserRole.executor):
            self.user.role = role
            response = await self.client.get(f"/api/audit/cases/{self.case_id}/events")
            self.assertEqual(response.status_code, 200)
            events = response.json()
            self.assertEqual([item["id"] for item in events], list(map(str, (live, older, unknown))))
            self.assertEqual(events[0]["actor_name"], "Import administrator")
            self.assertEqual(events[0]["origin"], "live")
            self.assertEqual(events[0]["occurred_at"], events[0]["created_at"])
            self.assertEqual(events[0]["occurred_at"], "2026-09-05T09:00:00Z")
            self.assertIsNone(events[0]["imported_at"])
            self.assertEqual(events[1]["actor_name"], "Historical reviewer")
            self.assertIsNone(events[1]["actor_id"])
            self.assertEqual(events[1]["origin"], "legacy_import")
            self.assertNotEqual(events[1]["occurred_at"], events[1]["imported_at"])
            self.assertEqual(events[1]["occurred_at"], "2026-09-02T09:00:00Z")
            self.assertIsNone(events[2]["actor_name"])
            self.assertIsNone(events[2]["occurred_at"])
            self.assertNotIn("not public", str(events[1:]))
            self.assertEqual(events[1]["legacy_source_url"],
                             f"/audit?view=legacy-imports&batch={self.source_id}" if role == UserRole.admin else None)

    async def test_same_time_event_order_is_stable(self):
        lower = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
        upper = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
        await self.add_event(id=upper)
        await self.add_event(id=lower)
        for _ in range(2):
            response = await self.client.get(f"/api/audit/cases/{self.case_id}/events")
            self.assertEqual([event["id"] for event in response.json()], [str(upper), str(lower)])

    async def test_statistics_reads_business_dates_and_committed_metrics_only(self):
        atom_id = uuid4()
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditAtom]).values(
                id=atom_id, case_id=self.case_id, state="ready", created_at=instant(8),
                legacy_transfer_id=self.transfer_id, legacy_effective_at=instant(4),
            ))
            await db.execute(insert(self.tables[AuditLegacyMetric]).values(
                id=uuid4(), transfer_id=self.transfer_id, case_id=self.other_case_id,
                metric_date=date(2026, 9, 2), metric_type="verified", value=90,
            ))
        await self.add_event(atom_id=atom_id, occurred_at=instant(1, 21))
        await self.add_event(atom_id=atom_id, occurred_at=instant(4), event_type="legacy_atom_snapshot",
                             payload_json={"state": "ready", "snapshot_date_confirmed": True})
        result = (await self.client.get("/api/audit/statistics")).json()
        self.assertEqual(result["atoms"]["verified"], 1)
        self.assertEqual(result["trend"][1]["verified_count"], 1)
        self.assertEqual(sum(point["verified_count"] for point in result["trend"]), 1)
        self.assertEqual(result["aggregate_trend"][1]["verified_count"], 90)
        for status in ("draft", "previewed", "rolled_back"):
            async with self.sessions.begin() as db:
                await db.execute(update(self.tables[AuditLegacyTransfer]).values(status=status))
            self.assertEqual((await self.client.get("/api/audit/statistics")).json()["aggregate_trend"], [])
        async with self.sessions.begin() as db:
            await db.execute(delete(self.tables[AuditLegacyMetric]))
            await db.execute(update(self.tables[AuditLegacyTransfer]).values(status="committed"))
        self.assertEqual((await self.client.get("/api/audit/statistics")).json()["aggregate_trend"], [])

    async def test_metric_coverage_duplicate_rejected_but_other_case_allowed(self):
        values = dict(transfer_id=self.transfer_id, case_id=self.case_id,
                      metric_date=date(2026, 9, 2), metric_type="verified", value=90)
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditLegacyMetric]).values(id=uuid4(), **values))
        with self.assertRaises(IntegrityError):
            async with self.sessions.begin() as db:
                await db.execute(insert(self.tables[AuditLegacyMetric]).values(id=uuid4(), **values))
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditLegacyMetric]).values(id=uuid4(), **{**values, "case_id": self.other_case_id}))
        result = (await self.client.get("/api/audit/statistics")).json()
        self.assertEqual(result["aggregate_trend"][1]["verified_count"], 180)
        self.assertEqual(result["atoms"]["total"], 0)

    async def test_read_endpoints_keep_workspace_permission_gate(self):
        async def denied():
            raise HTTPException(status_code=403)
        self.app.dependency_overrides[routes.require_audit_workspace_member] = denied
        for path in ("/api/audit/statistics", f"/api/audit/cases/{self.case_id}/events"):
            self.assertEqual((await self.client.get(path)).status_code, 403)

    async def test_snapshot_payload_not_current_state_controls_verification(self):
        atom_id = uuid4()
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditAtom]).values(
                id=atom_id, case_id=self.case_id, state="ready", created_at=instant(8),
                legacy_transfer_id=self.transfer_id, legacy_effective_at=instant(2),
            ))
        await self.add_event(atom_id=atom_id, event_type="legacy_atom_snapshot", payload_json={"state": "draft"})
        result = (await self.client.get("/api/audit/statistics")).json()
        self.assertEqual(result["atoms"]["verified"], 1)
        self.assertEqual(sum(point["verified_count"] for point in result["trend"]), 0)

    async def test_review_events_cover_business_day_not_import_day(self):
        atom_id = uuid4()
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditAtom]).values(
                id=atom_id, case_id=self.case_id, state="draft", created_at=instant(8),
            ))
            for kind in ("alpha_reviewed", "commission_reviewed"):
                await db.execute(insert(self.tables[AuditLegacyMetric]).values(
                    id=uuid4(), transfer_id=self.transfer_id, case_id=self.case_id,
                    metric_date=date(2026, 9, 2), metric_type=kind, value=90,
                ))
        await self.add_event(atom_id=atom_id, event_type="commission_reviewed", occurred_at=instant(1, 21))
        await self.add_event(atom_id=atom_id, legacy_transfer_id=None, event_type="atom_alpha_decision_changed",
                             payload_json={"alpha_result": "present", "alpha_date": "2026-09-02"})
        response = await self.client.get("/api/audit/statistics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["aggregate_conflict_count"], 2)
        self.assertEqual(response.json()["aggregate_trend"][1], {
            "date": "2026-09-02", "verified_count": None,
            "alpha_reviewed_count": None, "commission_reviewed_count": None,
        })

    async def test_partial_actor_and_case_coverage_nulls_entire_cell_and_preserves_raw_metrics(self):
        kinds = ("verified", "alpha_reviewed", "commission_reviewed")
        async with self.sessions.begin() as db:
            await db.execute(insert(self.tables[AuditAtom]).values(
                id=uuid4(), case_id=self.case_id, state="ready", created_at=instant(1),
                alpha_result="present", alpha_date=date(2026, 9, 1),
                commission_result="confirmed", commission_date=date(2026, 9, 1),
            ))
            for kind in kinds:
                for case_id, actor, day, value in (
                    (self.case_id, "reviewer-a", 1, 100),
                    (self.case_id, "reviewer-b", 1, 5),
                    (self.other_case_id, "reviewer-c", 1, 7),
                    (self.other_case_id, "reviewer-c", 2, 7),
                    (self.other_case_id, "reviewer-c", 3, 0),
                ):
                    await db.execute(insert(self.tables[AuditLegacyMetric]).values(
                        id=uuid4(), transfer_id=self.transfer_id, case_id=case_id,
                        actor_name=actor, actor_scope=actor,
                        metric_date=date(2026, 9, day), metric_type=kind, value=value,
                    ))
            original = (await db.execute(select(AuditLegacyMetric).order_by(AuditLegacyMetric.id))).scalars().all()
            original_values = [(metric.id, metric.actor_scope, metric.value) for metric in original]
        response = await self.client.get("/api/audit/statistics")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["aggregate_conflict_count"], 6)
        for kind in kinds:
            self.assertEqual([point[f"{kind}_count"] for point in result["aggregate_trend"]],
                             [None, 7, 0, None, None, None, None, None])
        async with self.sessions() as db:
            remaining = (await db.execute(select(AuditLegacyMetric).order_by(AuditLegacyMetric.id))).scalars().all()
            self.assertEqual([(metric.id, metric.actor_scope, metric.value) for metric in remaining], original_values)


class LegacyStatisticsTransferOrderTests(unittest.IsolatedAsyncioTestCase):
    async def check_order(self, kind, *, aggregate_first):
        from tests.test_audit_legacy_transfer import TransferTests
        fixture = TransferTests()
        await fixture.asyncSetUp()
        try:
            fixture.app.include_router(routes.router, prefix="/api/audit")
            fixture.app.dependency_overrides[routes.require_audit_workspace_member] = lambda: fixture.user
            async with fixture.sessions() as db:
                audit_case = AuditCase(title="Live case", digital_product="Product", workflow_stage="alpha_review")
                db.add(audit_case)
                await db.flush()
                atom = AuditAtom(case_id=audit_case.id, item_code="LIVE-1", title="Live atom",
                                 digital_product="Product", state="ready", created_at=instant(1))
                db.add(atom)
                await db.commit()
                case_id, atom_id, atom_version = audit_case.id, atom.id, atom.updated_at.isoformat()
            rows = {"daily_totals": [{"case_key": "LIVE", "metric_date": "2026-09-02", "metric_type": kind, "value": 90}]}
            transfer = await fixture.create(rows, config={"cases": {"LIVE": {
                "mode": "existing", "target_case_id": str(case_id), "title": "Live case", "digital_product": "Product",
            }}})
            field = "alpha" if kind == "alpha_reviewed" else "commission"
            with patch.object(routes, "statistics_period", return_value=(date(2026, 9, 1), date(2026, 9, 8))):
                if aggregate_first:
                    preview = await fixture.preview(transfer)
                    committed = await fixture.commit(preview)
                    self.assertEqual(committed.status_code, 200, committed.text)
                    before = (await fixture.client.get("/api/audit/statistics")).json()
                    self.assertEqual(before["aggregate_conflict_count"], 0)
                    self.assertEqual(before["aggregate_trend"][1][f"{kind}_count"], 90)
                saved = await fixture.client.patch(f"/api/audit/cases/{case_id}/atoms/{atom_id}", json={
                    "expected_updated_at": atom_version,
                    f"{field}_result": "present" if field == "alpha" else "confirmed",
                    f"{field}_date": "2026-09-02",
                })
                self.assertEqual(saved.status_code, 200, saved.text)
                if aggregate_first:
                    after = (await fixture.client.get("/api/audit/statistics")).json()
                    self.assertEqual(after["aggregate_conflict_count"], 1)
                    self.assertEqual([point[f"{kind}_count"] for point in after["aggregate_trend"]], [None] * 8)
                    async with fixture.sessions() as db:
                        metric = (await db.execute(select(AuditLegacyMetric))).scalar_one()
                        self.assertEqual(metric.value, 90)
                        self.assertEqual((await db.get(AuditLegacyTransfer, metric.transfer_id)).status, "committed")
                else:
                    blocked = await fixture.preview(transfer, ready=False)
                    self.assertIn("aggregate_coverage_overlap", {issue["code"] for issue in blocked["preview"]["issues"]})
                    self.assertEqual((await fixture.commit(blocked)).status_code, 409)
                    self.assertEqual(await fixture.model_count(AuditLegacyMetric), 0)
        finally:
            await fixture.asyncTearDown()

    async def test_committed_aggregate_then_backdated_live_review_keeps_fact_but_hides_overlap(self):
        for kind in ("alpha_reviewed", "commission_reviewed"):
            with self.subTest(kind=kind):
                await self.check_order(kind, aggregate_first=True)

    async def test_backdated_live_review_then_aggregate_commit_remains_blocked(self):
        for kind in ("alpha_reviewed", "commission_reviewed"):
            with self.subTest(kind=kind):
                await self.check_order(kind, aggregate_first=False)


if __name__ == "__main__":
    unittest.main()
