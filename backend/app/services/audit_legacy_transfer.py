"""Deterministic transfer planning and atomic, conservative commit/rollback.

The source workbook is read only here. Plans never create source documents or
put workbook keys/rows into public audit event payloads.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import re
from typing import get_args
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from anyio import CapacityLimiter
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models import Base
from app.models.audit import AuditAssignment, AuditAtom, AuditCase, AuditEvent, AuditTeamMember
from app.models.audit_legacy import AuditLegacyImport, utc_now
from app.models.audit_legacy_transfer import (
    AuditLegacyMetric, AuditLegacyProvenance, AuditLegacyTransfer, AuditLegacyTransferRow,
)
from app.models.user import User
from app.schemas.audit_legacy_transfer import TransferConfig, TransferField
from app.services import audit_legacy_workbook
from app.services.activity import record_activity_event
from app.services.audit_contract_reference import encrypt_contract_reference
from app.services.audit_import import build_contract_fields, mask_contract_reference, mask_system_url
from app.services.audit_legacy_locks import lock_legacy_targets


TRANSFER_LOCK_ID = 0x44504D53413139  # Shared with source staging/deletion.
PARSER_LIMITER = CapacityLimiter(1)
PAGE_SIZE = 500
MOSCOW = ZoneInfo("Europe/Moscow")
MODELS = {model.__tablename__: model for model in (
    AuditCase, AuditAtom, AuditAssignment, AuditEvent, AuditLegacyMetric,
)}
STATES = {"draft", "ready", "excluded"}
CANONICAL_LABELS = {
    "state": sorted(STATES), "previous_state": sorted(STATES),
    "alpha_result": ["present", "not_present", "partial", "not_applicable", "needs_clarification"],
    "commission_result": ["confirmed", "not_confirmed", "deferred", "not_applicable"],
    "metric_type": ["verified", "alpha_reviewed", "commission_reviewed"],
    "event_type": ["atom_status_changed", "alpha_reviewed", "commission_reviewed", "assignment"],
}
ATOM_FIELDS = {
    "title", "digital_product", "source_clause", "source_evidence_text", "work_type", "object_type",
    "system_url", "notes", "state", "alpha_result", "alpha_comment", "alpha_date",
    "commission_result", "commission_date",
}
PRIVATE_FIELDS = {"contract_reference", "contract_reference_ciphertext", "contract_reference_fingerprint"}


def json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def digest(value) -> str:
    return sha256(json.dumps(json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def case_ref(raw_key: str) -> str:
    """Opaque mapping key: confidential source case keys never leave the service."""
    return digest(["case", raw_key])


def source_identity(kind: str, values: dict) -> str:
    case = values.get("case_key")
    if kind == "cases":
        parts = [case]
    elif kind == "atoms":
        parts = [case, values.get("atom_key")]
    elif kind == "events":
        parts = [case, values.get("event_key")]
    elif kind == "assignments":
        parts = [case, values.get("assignment_key") or [
            values.get("assignee_email") or values.get("actor_name"), values.get("assigned_at"),
        ]]
    else:
        parts = [case, values.get("metric_date"), values.get("metric_type"), values.get("assignee_email") or values.get("actor_name") or ""]
    return digest(parts)


def _fail(code: str, message: str, status: int = 409):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


@asynccontextmanager
async def atomic_write(db: AsyncSession):
    try:
        async with asyncio.timeout(60):
            yield
            await db.commit()
    except BaseException as error:
        await db.rollback()
        if isinstance(error, TimeoutError):
            _fail("transfer_deadline_exceeded", "Превышено время операции. Изменения отменены; уменьшите пакет.", 503)
        if isinstance(error, SQLAlchemyError):
            _fail("transfer_storage_failed", "Не удалось сохранить перенос. Изменения отменены.", 503)
        raise


async def lock_transfers(db: AsyncSession):
    # SQLite is used only in isolated tests; PostgreSQL is the application backend.
    if db.bind.dialect.name == "postgresql":
        await db.execute(select(func.set_config("lock_timeout", "3s", True), func.set_config("statement_timeout", "30s", True)))
        await db.execute(select(func.pg_advisory_xact_lock(TRANSFER_LOCK_ID)))


def reference_tables():
    return sorted({
        table.name for table in Base.metadata.tables.values()
        if any(fk.target_fullname in {"audit_cases.id", "audit_atoms.id", "audit_events.id", "audit_assignments.id", "audit_legacy_metrics.id"}
               for fk in table.foreign_keys)
    } | set(MODELS) | {"audit_legacy_provenance", "audit_legacy_transfer_rows"})


async def lock_targets(db: AsyncSession, case_ids, actor_ids=()):
    await lock_legacy_targets(db, case_ids, actor_ids)


async def source_scope(db, config, records):
    wanted = defaultdict(set)
    mapping_keys = set()
    fingerprints = set()
    for record in records:
        values = record["values"]
        mapping_keys.add(case_ref(values["case_key"]))
        wanted["cases"].add(source_identity("cases", values))
        wanted[record["kind"]].add(source_identity(record["kind"], values))
        if record["kind"] == "events" and values.get("atom_key"):
            wanted["atoms"].add(source_identity("atoms", values))
        if values.get("contract_reference"):
            fingerprints.add(build_contract_fields(values["contract_reference"])[0])
    provenance = []
    for kind, identifiers in wanted.items():
        identifiers = sorted(identifiers)
        for offset in range(0, len(identifiers), 1000):
            provenance.extend((await db.execute(select(AuditLegacyProvenance).where(
                AuditLegacyProvenance.namespace == config["namespace"], AuditLegacyProvenance.kind == kind,
                AuditLegacyProvenance.source_key_hash.in_(identifiers[offset:offset + 1000]),
            ))).scalars())
    provenance.sort(key=lambda row: str(row.id))
    ids = {UUID(choice["target_case_id"]) for key, choice in config["cases"].items()
           if key in mapping_keys and choice.get("target_case_id")}
    ids.update(row.target_id for row in provenance if row.target_table == "audit_cases")
    return {"case_ids": ids, "provenance": provenance, "fingerprints": fingerprints}


async def get_source(db: AsyncSession, source_id: UUID, *, lock=False):
    query = select(AuditLegacyImport).where(AuditLegacyImport.id == source_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    source = (await db.execute(query)).scalar_one_or_none()
    if source is None:
        _fail("source_not_found", "Исходный файл не найден.", 404)
    return source


async def get_transfer(db: AsyncSession, transfer_id: UUID, *, lock=False):
    query = select(AuditLegacyTransfer).where(AuditLegacyTransfer.id == transfer_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    transfer = (await db.execute(query)).scalar_one_or_none()
    if transfer is None:
        _fail("transfer_not_found", "Перенос не найден.", 404)
    return transfer


def check_revision(transfer, revision, *, editable=False):
    if transfer.revision != revision:
        _fail("revision_conflict", "Конфигурация изменилась. Обновите перенос.")
    if editable and transfer.status not in ("draft", "previewed"):
        _fail("transfer_immutable", "Подтверждённый или отменённый перенос нельзя редактировать.")


def preview_page(transfer, offset=0, limit=PAGE_SIZE):
    if transfer.preview is None:
        _fail("preview_required", "Сначала выполните предварительную проверку.")
    rows = transfer.preview["rows"]
    end = min(offset + limit, len(rows))
    return {
        "revision": transfer.preview["revision"], "preview_hash": transfer.preview_hash,
        "rows": rows[offset:end], "total_rows": len(rows),
        "next_offset": end if end < len(rows) else None,
    }


def transfer_read(transfer):
    preview = None
    if transfer.preview is not None:
        preview = {**transfer.preview, **preview_page(transfer)}
    return json_value({
        key: getattr(transfer, key) for key in (
            "id", "source_id", "namespace", "status", "revision", "config", "summary",
            "committed_at", "rolled_back_at", "created_at", "updated_at",
        )
    } | {"preview": preview})


async def _users(db, selected_ids=None, *, lock=False):
    # Never load the User entity: it contains credential-bearing columns.
    query = select(
        User.id, User.full_name, User.email, User.is_active, User.audit_enabled,
    ).order_by(User.id)
    member_query = select(AuditTeamMember.user_id)
    if selected_ids is not None:
        query = query.where(User.id.in_(selected_ids))
        member_query = member_query.where(AuditTeamMember.user_id.in_(selected_ids))
    if lock:
        query = query.with_for_update(read=True)
        member_query = member_query.with_for_update(read=True)
    users = (await db.execute(query)).mappings().all()
    members = set((await db.execute(member_query)).scalars())
    return {str(row["id"]): json_value(dict(row)) | {
        "eligible_current_assignment": bool(row["is_active"] and row["audit_enabled"] and row["id"] in members),
    } for row in users}


async def options(db, source_id=None):
    source = await get_source(db, source_id) if source_id else None
    cases = (await db.execute(select(
        AuditCase.id, AuditCase.case_sequence, AuditCase.title, AuditCase.digital_product,
        AuditCase.contract_date, AuditCase.status,
    ).order_by(AuditCase.case_sequence))).mappings().all()
    return {
        "source_id": source_id, "inspection": source.inspection if source else None,
        "cases": json_value([dict(row) for row in cases]), "users": list((await _users(db)).values()),
        "kinds": ["cases", "atoms", "assignments", "events", "daily_totals"],
        "fields": list(get_args(TransferField)), "canonical_labels": CANONICAL_LABELS,
    }


async def record_journal(db, transfer, admin_id, event_type):
    await record_activity_event(db, admin_id, event_type, metadata={
        "transfer_id": str(transfer.id), "source_id": str(transfer.source_id),
        "revision": transfer.revision, "status": transfer.status,
        "counts": transfer.summary.get("counts", {}),
    })


async def create_transfer(db, payload, admin_id):
    await lock_transfers(db)
    await get_source(db, payload.source_id, lock=True)
    transfer = AuditLegacyTransfer(
        source_id=payload.source_id, namespace=payload.config.namespace,
        config=canonical_config(payload.config), revision=1, status="draft", created_by_id=admin_id,
    )
    db.add(transfer)
    await db.flush()
    await record_journal(db, transfer, admin_id, "audit_legacy_transfer_created")
    return transfer


async def update_config(db, transfer_id, payload, admin_id):
    await lock_transfers(db)
    transfer = await get_transfer(db, transfer_id, lock=True)
    check_revision(transfer, payload.revision, editable=True)
    transfer.config = canonical_config(payload.config)
    transfer.namespace = payload.config.namespace
    transfer.revision += 1
    transfer.preview = None
    transfer.preview_hash = None
    transfer.status = "draft"
    transfer.updated_at = utc_now()
    await record_journal(db, transfer, admin_id, "audit_legacy_transfer_configured")
    return transfer


def canonical_config(config):
    result = config.model_dump(mode="json")
    result["cases"] = {key if re.fullmatch(r"[0-9a-f]{64}", key) else case_ref(key): value
                       for key, value in result["cases"].items()}
    return result


async def _normalise(db, source, config):
    data = await db.scalar(select(AuditLegacyImport.source_bytes).where(AuditLegacyImport.id == source.id))
    try:
        async with PARSER_LIMITER:
            return await run_in_threadpool(audit_legacy_workbook.normalize_legacy_datasets, data, config["datasets"])
    except (ValueError, TypeError):
        _fail("invalid_workbook_mapping", "Не удалось обработать сопоставление книги.", 422)


async def _target_snapshot(db, config, scope):
    provenance, case_ids = scope["provenance"], scope["case_ids"]
    selected_users = [UUID(choice["user_id"]) for choice in config["actors"].values() if choice.get("user_id")]
    snapshot = {"users": await _users(db, selected_users), "provenance": [
        {column.name: json_value(getattr(row, column.name)) for column in row.__table__.columns}
        for row in provenance
    ]}
    for name, model in MODELS.items():
        column = model.id if model is AuditCase else model.case_id
        rows = (await db.execute(select(model.__table__).where(column.in_(case_ids)).order_by(model.id))).mappings().all()
        snapshot[name] = [json_value(dict(row)) for row in rows]
    # Fingerprint collision checks include cases outside the explicitly selected targets.
    snapshot["case_fingerprints"] = json_value([dict(row) for row in (await db.execute(select(
        AuditCase.id, AuditCase.contract_reference_fingerprint,
    ).where(AuditCase.contract_reference_fingerprint.in_(scope["fingerprints"])).order_by(AuditCase.id))).mappings()])
    return snapshot


def _issue(record, code, field=None, message=None, severity="error"):
    return {
        "sheet_id": record.get("sheet_id"), "row": record.get("row"), "field": field,
        "code": code, "severity": severity, "message": message or code,
    }


def _day(value):
    if not value:
        return None
    if len(value) == 10:
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(MOSCOW).date().isoformat()


def _date_value(value):
    return _day(value) if value else None


def _timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("canonical datetime must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


class Planner:
    def __init__(self, transfer, normalized, snapshot):
        self.transfer = transfer
        self.config = transfer.config
        self.normalized = normalized
        self.snapshot = snapshot
        self.targets = {table: {row["id"]: dict(row) for row in snapshot[table]} for table in MODELS}
        self.provenance = {(row["kind"], row["source_key_hash"]): row for row in snapshot["provenance"]}
        self.rows = []
        self.operations = []
        self.pending_operations = {}
        self.atom_codes = {(row["case_id"], row["item_code"]): row for row in snapshot["audit_atoms"]}
        self.receipts = {}
        self.issues = list(normalized["issues"])
        self.case_ids = {}
        self.case_rows = {}
        self.atom_ids = {}
        self.atom_sources = {}
        self.case_records = defaultdict(list)
        self.seen = {}
        self.coverage = defaultdict(list)
        self.aggregate = defaultdict(list)

    def block(self, record, row, code, field=None, message=None):
        issue = _issue(record, code, field, message)
        row["issues"].append(issue)
        row["outcome"] = "blocked"
        self.issues.append(issue)

    def new_row(self, record):
        key = source_identity(record["kind"], record["values"])
        row = {
            "row_key": record["kind"] + ":" + key, "kind": record["kind"],
            "sheet_id": record["sheet_id"], "row": record.get("row"), "source_key": key,
            "outcome": "create", "target_id": None, "changes": {}, "issues": [],
        }
        row["changes"]["case_mapping_key"] = case_ref(record["values"].get("case_key", ""))
        row["changes"]["source_case_mask"] = mask_contract_reference(record["values"].get("case_key", ""))
        for field in ("title", "digital_product"):
            if record["values"].get(field):
                row["changes"]["source_" + field] = record["values"][field]
        self.rows.append(row)
        return row

    def actor(self, record, row, *, required=False):
        values = record["values"]
        names = [values.get("assignee_email"), values.get("actor_name")]
        choices = [self.config["actors"][name] for name in names if name and name in self.config["actors"]]
        if not choices:
            if any(names) or required:
                self.block(record, row, "actor_mapping_required", "actor_name", "Явно сопоставьте автора с пользователем или историческим именем.")
                row["changes"]["actor_mapping_key"] = next((name for name in names if name), None)
            return None, None
        if any(choice != choices[0] for choice in choices):
            self.block(record, row, "actor_mapping_conflict", "actor_name")
            return None, None
        choice = choices[0]
        if choice["mode"] == "historical":
            return None, choice["historical_name"]
        user = self.snapshot["users"].get(choice["user_id"])
        if user is None:
            self.block(record, row, "actor_user_missing", "actor_name")
            return None, None
        return user["id"], user["full_name"]

    def operation(self, row, table, target_id, values, action="create", *, auxiliary=False):
        before = self.targets[table].get(target_id)
        op = {"row_key": row["row_key"] + (":event" if auxiliary else ""), "table": table,
              "id": target_id, "values": values, "action": action, "before": before}
        if action in ("create", "fill_empty"):
            pending = self.pending_operations.get((table, target_id))
            if pending:
                pending["values"].update(values)
                action = pending["action"]
            else:
                self.operations.append(op)
                self.pending_operations[(table, target_id)] = op
            self.targets[table][target_id] = {**(before or {}), **values, "id": target_id}
            if table == "audit_atoms":
                atom = self.targets[table][target_id]
                self.atom_codes[(atom["case_id"], atom["item_code"])] = atom
            receipt = self.receipts.get(row["row_key"])
            if receipt and receipt["before"] is None and action == "fill_empty":
                receipt["before"] = before
        if not auxiliary:
            row["outcome"] = action
            row["target_id"] = target_id
            row["changes"].update({k: v for k, v in values.items() if k not in PRIVATE_FIELDS})
        return op

    def existing_changes(self, record, row, existing, values, allowed):
        changes = {}
        for field, value in values.items():
            if value is None or value == "" or field in ("legacy_transfer_id", "legacy_effective_at"):
                continue
            actual = existing.get(field)
            if actual == value:
                continue
            if actual not in (None, ""):
                self.block(record, row, "target_value_conflict", field, "Непустое целевое значение отличается; перезапись запрещена.")
            elif field in allowed:
                changes[field] = value
            else:
                self.block(record, row, "fill_empty_decision_required", field, "Заполнение пустого поля требует явного решения.")
        return changes

    def deduplicate(self, record, row, semantic, table, expected_id=None, *, reference_only=False):
        content_hash = digest(semantic)
        identity = (record["kind"], row["source_key"])
        previous = self.provenance.get(identity)
        if reference_only and previous:
            content_hash = previous["content_hash"]
        seen = self.seen.get(identity)
        if seen:
            if seen[0] != content_hash:
                self.block(record, row, "duplicate_source_conflict", message="Один исходный ключ содержит разные значения.")
            else:
                row["outcome"] = "duplicate"
                row["target_id"] = seen[1]
            return True
        if previous:
            row["target_id"] = previous["target_id"]
            if not previous["active"]:
                self.block(record, row, "source_key_rolled_back", message="Ключ принадлежит отменённому переносу; измените namespace осознанно.")
            elif previous["content_hash"] != content_hash or previous["target_table"] != table:
                self.block(record, row, "source_key_conflict", message="Этот исходный ключ уже перенесён с другими данными или решениями.")
            elif expected_id and previous["target_id"] != expected_id:
                self.block(record, row, "source_target_conflict")
            elif previous["target_id"] not in self.targets[table]:
                self.block(record, row, "provenance_target_missing")
            else:
                row["outcome"] = "duplicate"
                self.receipts[row["row_key"]] = {
                    "row": row, "table": table, "target_id": previous["target_id"],
                    "content_hash": content_hash, "provenance_id": previous["id"], "before": None,
                }
            self.seen[identity] = (content_hash, row["target_id"])
            return True
        self.seen[identity] = (content_hash, expected_id)
        self.receipts[row["row_key"]] = {
            "row": row, "table": table, "target_id": expected_id, "content_hash": content_hash,
            "provenance_id": None, "before": self.targets[table].get(expected_id),
        }
        return False

    def deterministic_id(self, row, suffix=""):
        return str(uuid5(self.transfer.id, row["row_key"] + suffix))

    def prepare_case(self, raw_key, records):
        record = records[0] if records else {"kind": "cases", "sheet_id": "config", "row": None, "values": {"case_key": raw_key}}
        record = {**record, "kind": "cases", "values": {**record["values"], "case_key": raw_key}}
        row = self.new_row(record)
        self.case_rows[raw_key] = row
        choice = self.config["cases"].get(case_ref(raw_key))
        if not choice:
            self.block(record, row, "case_mapping_required", "case_key", "Выберите существующую карточку или явно подтвердите создание.")
            return
        merged = {}
        for source in records:
            for field, value in source["values"].items():
                if field == "case_key" or value in (None, ""):
                    continue
                if field in merged and merged[field] != value:
                    self.block(record, row, "case_source_conflict", field)
                merged[field] = value
        if row["outcome"] == "blocked":
            return
        for field in ("title", "digital_product"):
            if merged.get(field):
                row["changes"]["source_" + field] = merged[field]
        values = {field: choice.get(field) or merged.get(field) for field in ("title", "digital_product", "contract_date")}
        for field in ("notes", "workflow_stage"):
            if merged.get(field) is not None:
                values[field] = merged[field]
        values = {field: value for field, value in values.items() if value is not None}
        if "contract_date" in values:
            values["contract_date"] = _date_value(values["contract_date"])
        existing_provenance = self.provenance.get(("cases", row["source_key"]))
        target_id = choice.get("target_case_id") or (existing_provenance["target_id"] if existing_provenance else self.deterministic_id(row))
        if choice["mode"] == "create":
            values.setdefault("title", values.get("digital_product"))
            if not values.get("title") or not values.get("digital_product"):
                self.block(record, row, "case_creation_fields_required", "digital_product")
                return
        if merged.get("contract_reference"):
            fingerprint, mask = build_contract_fields(merged["contract_reference"])
            if any(item["contract_reference_fingerprint"] == fingerprint and item["id"] != target_id for item in self.snapshot["case_fingerprints"]):
                self.block(record, row, "contract_reference_exists", "contract_reference")
            values.update(contract_reference=merged["contract_reference"], contract_reference_fingerprint=fingerprint, contract_reference_mask=mask)
        if self.deduplicate(record, row, {"values": values, "target_id": target_id}, "audit_cases", target_id,
                            reference_only=not records and not values and choice["mode"] == "existing"):
            if row["outcome"] != "blocked":
                self.case_ids[raw_key] = target_id
            return
        if choice["mode"] == "existing":
            existing = self.targets["audit_cases"].get(target_id)
            if not existing:
                self.block(record, row, "target_case_missing")
                return
            if "contract_reference" in values:
                if existing.get("contract_reference_fingerprint") != values["contract_reference_fingerprint"]:
                    self.block(record, row, "contract_reference_conflict", "contract_reference")
                values = {key: value for key, value in values.items() if key not in PRIVATE_FIELDS and key != "contract_reference_mask"}
            changes = self.existing_changes(record, row, existing, values, choice["fill_empty"])
            if row["outcome"] == "blocked":
                return
            self.operation(row, "audit_cases", target_id, changes, "fill_empty" if changes else "reuse")
        else:
            stage = values.get("workflow_stage", "unassigned")
            if stage not in audit_legacy_workbook.TRANSFER_ENUMS["workflow_stage"].values():
                self.block(record, row, "unsupported_workflow_stage", "workflow_stage")
                return
            self.operation(row, "audit_cases", target_id, {**values, "status": "ready" if stage == "ready" else "draft", "workflow_stage": stage})
        self.case_ids[raw_key] = target_id

    def plan_record(self, record):
        row = self.new_row(record)
        values = record["values"]
        choice = self.config["row_decisions"].get(row["row_key"], {"action": "create", "fill_empty": []})
        if choice["action"] == "skip":
            row["outcome"] = "skip"
            return
        case_id = self.case_ids.get(values.get("case_key"))
        if case_id is None:
            self.block(record, row, "case_mapping_unresolved", "case_key")
            return
        method = getattr(self, "plan_" + record["kind"])
        method(record, row, choice, case_id)

    def plan_atoms(self, record, row, choice, case_id):
        values = record["values"]
        actor_id, actor_name = self.actor(record, row)
        if row["outcome"] == "blocked":
            return
        desired = {field: values[field] for field in ATOM_FIELDS if values.get(field) not in (None, "")}
        explicit_target = self.targets["audit_atoms"].get(choice.get("target_id"), {})
        desired.setdefault("state", explicit_target.get("state", "draft"))
        desired.setdefault("digital_product", self.targets["audit_cases"][case_id]["digital_product"])
        desired.update(case_id=case_id, item_code=str(values["atom_key"]))
        if desired.get("system_url"):
            desired["system_url"] = mask_system_url(desired["system_url"])
        for field in ("alpha_date", "commission_date"):
            if field in desired:
                desired[field] = _date_value(desired[field])
        effective = _timestamp(values.get("occurred_at"))
        if effective is None:
            warning = _issue(record, "snapshot_date_unknown", "occurred_at", "Дата снимка неизвестна; дата загрузки не заменяет историческую дату.", "warning")
            row["issues"].append(warning)
            self.issues.append(warning)
        prior = self.provenance.get(("atoms", row["source_key"]))
        target_id = choice.get("target_id") or (prior["target_id"] if prior else self.deterministic_id(row))
        semantic = {"values": desired, "effective_at": effective, "actor_id": actor_id, "actor_name": actor_name}
        if self.deduplicate(record, row, semantic, "audit_atoms", target_id):
            if row["outcome"] != "blocked":
                self.atom_ids[(values["case_key"], values["atom_key"])] = row["target_id"]
            return
        collision = self.atom_codes.get((case_id, desired["item_code"]))
        if choice["action"] in ("reuse", "fill_empty"):
            existing = self.targets["audit_atoms"].get(target_id)
            if not existing or existing["case_id"] != case_id:
                self.block(record, row, "target_atom_missing_or_wrong_case")
                return
            desired.pop("item_code")  # Explicit ID mapping may use a different live item code.
            changes = self.existing_changes(record, row, existing, desired, choice.get("fill_empty", []))
            if row["outcome"] == "blocked":
                return
            self.operation(row, "audit_atoms", target_id, changes, "fill_empty" if changes else "reuse")
        elif collision:
            row["target_id"] = collision["id"]
            self.block(record, row, "atom_exists_decision_required", "atom_key")
            return
        else:
            desired.update(legacy_transfer_id=str(self.transfer.id), legacy_effective_at=effective, source_refs_json=[])
            self.operation(row, "audit_atoms", target_id, desired)
            self.atom_sources[target_id] = (record, row)
        self.atom_ids[(values["case_key"], values["atom_key"])] = target_id
        # A snapshot is deliberately not a state transition.
        self.operation(row, "audit_events", self.deterministic_id(row, ":snapshot"), {
            "case_id": case_id, "atom_id": target_id, "actor_id": actor_id,
            "historical_actor_name": actor_name, "legacy_transfer_id": str(self.transfer.id),
            "occurred_at": effective, "event_type": "legacy_atom_snapshot",
            "message": "Исторический снимок атома",
            "payload_json": {"state": desired["state"], "snapshot_date_confirmed": effective is not None},
        }, auxiliary=True)

    def event_atom(self, record, row, case_id, required=False):
        atom_key = record["values"].get("atom_key")
        if not atom_key:
            if required:
                self.block(record, row, "event_atom_required", "atom_key")
            return None
        target_id = self.atom_ids.get((record["values"]["case_key"], atom_key))
        if target_id is None:
            source_key = source_identity("atoms", record["values"])
            prior = self.provenance.get(("atoms", source_key))
            if prior and prior["active"]:
                target_id = prior["target_id"]
            else:
                # Never infer a live atom by label/item code without an explicit mapping.
                decision = self.config["row_decisions"].get("atoms:" + source_key, {})
                if decision.get("action") == "reuse":
                    target_id = decision.get("target_id")
        atom = self.targets["audit_atoms"].get(target_id)
        if atom is None or atom["case_id"] != case_id:
            self.block(record, row, "event_atom_mapping_required", "atom_key")
            return None
        return target_id

    def plan_events(self, record, row, choice, case_id):
        values = record["values"]
        kind = values["event_type"]
        if kind not in CANONICAL_LABELS["event_type"]:
            self.block(record, row, "unsupported_event_type", "event_type")
            return
        actor_id, name = self.actor(record, row)
        atom_id = self.event_atom(record, row, case_id, required=kind != "assignment")
        payload = {}
        if kind == "atom_status_changed":
            if values.get("previous_state") not in STATES or values.get("state") not in STATES or values["previous_state"] == values["state"]:
                self.block(record, row, "explicit_transition_required", "previous_state")
            else:
                payload = {"previous_state": values["previous_state"], "state": values["state"]}
        elif kind in ("alpha_reviewed", "commission_reviewed"):
            field = "alpha_result" if kind == "alpha_reviewed" else "commission_result"
            if values.get(field) not in CANONICAL_LABELS[field]:
                self.block(record, row, "event_result_required", field)
            else:
                payload = {field: values[field]}
        if row["outcome"] == "blocked":
            return
        desired = {
            "case_id": case_id, "atom_id": atom_id, "actor_id": actor_id,
            "historical_actor_name": name, "occurred_at": _timestamp(values["occurred_at"]),
            "event_type": kind, "message": "Историческое событие аудита", "payload_json": payload,
        }
        prior = self.provenance.get(("events", row["source_key"]))
        target_id = prior["target_id"] if prior else self.deterministic_id(row)
        if self.deduplicate(record, row, desired, "audit_events", target_id):
            return
        if choice["action"] != "create":
            self.block(record, row, "immutable_event_create_or_skip_only")
            return
        self.operation(row, "audit_events", target_id, {**desired, "legacy_transfer_id": str(self.transfer.id)})

    def plan_assignments(self, record, row, choice, case_id):
        values = record["values"]
        actor_id, name = self.actor(record, row, required=True)
        current = values.get("is_current") is True and self.config["apply_current_assignments"] and not values.get("ended_at")
        assigned_at = values["assigned_at"]
        assigned_at = _timestamp(assigned_at) if len(assigned_at) > 10 else datetime.combine(date.fromisoformat(assigned_at), datetime.min.time(), MOSCOW).astimezone(timezone.utc).isoformat()
        ended_at = _timestamp(values.get("ended_at"))
        scheduled_date = _date_value(assigned_at)
        historical_payload = {"scheduled_date": scheduled_date, "ended_at": ended_at, "historical_only": not current}
        if current and not (actor_id and self.snapshot["users"][actor_id]["eligible_current_assignment"]):
            self.block(record, row, "current_assignment_ineligible", "assignee_email", "Текущее назначение требует активного участника аудита с включённым доступом.")
        case = self.targets["audit_cases"][case_id]
        if current and case.get("status") == "archived":
            self.block(record, row, "current_assignment_archived_case", "case_key", "Для архивной карточки доступна только история назначений, без изменения текущего календаря.")
        if current and case.get("responsible_user_id") not in (None, actor_id):
            self.block(record, row, "current_responsible_conflict", "assignee_email", "У карточки уже указан другой ответственный.")
        if row["outcome"] == "blocked":
            return
        table = "audit_assignments" if current else "audit_events"
        desired = {"case_id": case_id, "assignee_id": actor_id, "scheduled_date": scheduled_date} if current else {
            "case_id": case_id, "atom_id": None, "actor_id": actor_id, "historical_actor_name": name,
            "event_type": "assignment", "message": "Историческое назначение",
            "occurred_at": assigned_at,
            "payload_json": historical_payload,
        }
        prior = self.provenance.get(("assignments", row["source_key"]))
        target_id = choice.get("target_id") or (prior["target_id"] if prior else self.deterministic_id(row))
        semantic = {
            "values": desired, "current": current, "assigned_at": assigned_at, "ended_at": ended_at,
            "history": {"actor_id": actor_id, "historical_actor_name": name, "payload_json": historical_payload},
        }
        if self.deduplicate(record, row, semantic, table, target_id):
            return
        existing = next((item for item in self.targets["audit_assignments"].values() if item["case_id"] == case_id), None) if current else None
        if existing:
            if choice["action"] != "reuse" or target_id != existing["id"] or any(existing.get(k) != v for k, v in desired.items()):
                self.block(record, row, "assignment_exists_explicit_reuse_required")
                return
            self.operation(row, table, target_id, {}, "reuse")
        else:
            if choice["action"] != "create":
                self.block(record, row, "assignment_target_missing")
                return
            if not current:
                desired["legacy_transfer_id"] = str(self.transfer.id)
            self.operation(row, table, target_id, desired)
        if current:
            changes = {}
            if case.get("responsible_user_id") is None:
                changes["responsible_user_id"] = actor_id
            if case.get("workflow_stage") == "unassigned":
                changes["workflow_stage"] = "atomization"
            if changes:
                case_row = self.case_rows[values["case_key"]]
                self.operation(case_row, "audit_cases", case_id, changes, "fill_empty")
            self.operation(row, "audit_events", self.deterministic_id(row, ":history"), {
                "case_id": case_id, "atom_id": None, "actor_id": actor_id, "historical_actor_name": name,
                "legacy_transfer_id": str(self.transfer.id), "event_type": "assignment",
                "message": "Историческое назначение, применённое в текущем календаре",
                "occurred_at": assigned_at,
                "payload_json": historical_payload,
            }, auxiliary=True)

    def replay_new_atoms(self):
        histories = defaultdict(list)
        for event in self.targets["audit_events"].values():
            if event.get("atom_id") in self.atom_sources and event.get("occurred_at") and event["event_type"] != "legacy_atom_snapshot":
                histories[event["atom_id"]].append(event)
        for atom_id, events in histories.items():
            record, row = self.atom_sources[atom_id]
            source = record["values"]
            events.sort(key=lambda item: (item["occurred_at"], item["id"]))
            changes = {}
            transitions = [event for event in events if event["event_type"] == "atom_status_changed"]
            effective = _timestamp(source.get("occurred_at"))
            if transitions:
                if source.get("state") is not None:
                    known_at_snapshot = [event for event in transitions if effective is None or event["occurred_at"] <= effective]
                    snapshot_state = known_at_snapshot[-1]["payload_json"]["state"] if known_at_snapshot else transitions[0]["payload_json"]["previous_state"]
                    if snapshot_state != source["state"]:
                        self.block(record, row, "snapshot_state_conflict", "state", "Подтверждённый снимок противоречит последовательности событий.")
                if not effective or transitions[-1]["occurred_at"] >= effective or source.get("state") is None:
                    changes["state"] = transitions[-1]["payload_json"]["state"]
            for event_type, result_field, date_field in (("alpha_reviewed", "alpha_result", "alpha_date"), ("commission_reviewed", "commission_result", "commission_date")):
                reviews = [event for event in events if event["event_type"] == event_type]
                if not reviews:
                    continue
                snapshot_date = source.get(date_field)
                if source.get(result_field) is not None:
                    known = [event for event in reviews if not snapshot_date or _day(event["occurred_at"]) <= snapshot_date]
                    if known and known[-1]["payload_json"].get(result_field) != source[result_field]:
                        self.block(record, row, "snapshot_result_conflict", result_field)
                if not snapshot_date or _day(reviews[-1]["occurred_at"]) >= snapshot_date or source.get(result_field) is None:
                    changes[result_field] = reviews[-1]["payload_json"][result_field]
                    changes[date_field] = _day(reviews[-1]["occurred_at"])
            if changes and row["outcome"] != "blocked":
                self.operation(row, "audit_atoms", atom_id, changes, "fill_empty")
                if effective is None:
                    snapshot_id = self.deterministic_id(row, ":snapshot")
                    snapshot = self.pending_operations[("audit_events", snapshot_id)]
                    snapshot["values"]["payload_json"]["state"] = self.targets["audit_atoms"][atom_id]["state"]

    def plan_daily_totals(self, record, row, choice, case_id):
        values = record["values"]
        actor_id, name = self.actor(record, row)
        if row["outcome"] == "blocked":
            return
        desired = {"case_id": case_id, "metric_date": _date_value(values["metric_date"]),
                   "metric_type": values["metric_type"], "value": values["value"], "actor_name": name,
                   "actor_scope": digest(["user", actor_id]) if actor_id else digest(["historical", name]) if name else ""}
        if desired["metric_type"] not in CANONICAL_LABELS["metric_type"] or type(desired["value"]) is not int or not 0 <= desired["value"] <= 2147483647:
            self.block(record, row, "invalid_aggregate_metric")
            return
        prior = self.provenance.get(("daily_totals", row["source_key"]))
        target_id = prior["target_id"] if prior else self.deterministic_id(row)
        if self.deduplicate(record, row, desired, "audit_legacy_metrics", target_id):
            return
        if choice["action"] != "create":
            self.block(record, row, "aggregate_create_or_skip_only")
            return
        self.operation(row, "audit_legacy_metrics", target_id, {**desired, "transfer_id": str(self.transfer.id)})

    def validate_coverage(self):
        for atom in self.targets["audit_atoms"].values():
            effective = atom.get("legacy_effective_at") if atom.get("legacy_transfer_id") else atom.get("created_at")
            if atom.get("state") == "ready" and effective:
                self.coverage[(atom["case_id"], _day(effective), "verified")].append(atom["id"])
            for field, metric in (("alpha_date", "alpha_reviewed"), ("commission_date", "commission_reviewed")):
                if atom.get(field) and atom.get(field.replace("date", "result")) is not None:
                    self.coverage[(atom["case_id"], _day(atom[field]), metric)].append(atom["id"])
        transitions = defaultdict(list)
        for event in self.targets["audit_events"].values():
            timestamp = event.get("occurred_at") or (event.get("created_at") if not event.get("legacy_transfer_id") else None)
            if not timestamp or not event.get("atom_id"):
                continue
            payload = event.get("payload_json") or {}
            kind = event["event_type"]
            metric = "verified" if kind == "atom_status_changed" and payload.get("state") == "ready" else kind
            if metric in CANONICAL_LABELS["metric_type"]:
                self.coverage[(event["case_id"], _day(timestamp), metric)].append(event["id"])
            if kind == "atom_status_changed":
                transitions[event["atom_id"]].append((timestamp, payload.get("previous_state"), payload.get("state")))
        for metric in self.targets["audit_legacy_metrics"].values():
            key = (metric["case_id"], metric["metric_date"], metric["metric_type"])
            self.aggregate[key].append(metric.get("actor_scope", ""))
        bad_keys = {key for key, scopes in self.aggregate.items()
                    if len(scopes) != len(set(scopes)) or ("" in scopes and len(scopes) > 1) or self.coverage.get(key)}
        if bad_keys:
            self.issues.append(_issue({}, "aggregate_coverage_overlap", message="Дневной показатель пересекается с атомами, событиями или другим агрегатом по карточке, дате и типу."))
            for row in self.rows:
                if row["kind"] == "daily_totals" and row["outcome"] != "skip":
                    row["outcome"] = "blocked"
        for events in transitions.values():
            events.sort()
            for earlier, later in zip(events, events[1:]):
                if earlier[0] == later[0] or earlier[2] != later[1]:
                    self.issues.append(_issue({}, "transition_history_conflict", message="Последовательность исторических переходов неоднозначна или противоречива."))
                    break

    def validate_lengths(self):
        for operation in self.operations:
            table = MODELS[operation["table"]].__table__
            for name, value in operation["values"].items():
                if name == "contract_reference":
                    limit = 255
                else:
                    limit = getattr(table.c[name].type, "length", None)
                if limit and isinstance(value, str) and len(value) > limit:
                    self.issues.append(_issue({}, "target_field_too_long", field=name))

    def build(self):
        records = self.normalized["records"]
        all_cases = dict.fromkeys(record["values"].get("case_key", "") for record in records)
        for record in records:
            if record["kind"] == "cases":
                self.case_records[record["values"]["case_key"]].append(record)
        for key in all_cases:
            self.prepare_case(key, self.case_records[key])
            primary = self.rows[-1]
            for record in self.case_records[key][1:]:
                extra = self.new_row(record)
                extra.update(outcome="blocked" if primary["outcome"] == "blocked" else "duplicate",
                             target_id=primary["target_id"], changes=dict(primary["changes"]), issues=list(primary["issues"]))
        for kind in ("atoms", "assignments", "events", "daily_totals"):
            for record in records:
                if record["kind"] == kind:
                    self.plan_record(record)
        self.replay_new_atoms()
        self.validate_lengths()
        self.validate_coverage()
        counts = dict(Counter(row["outcome"] for row in self.rows))
        counts.update(total=len(self.rows), errors=sum(issue["severity"] == "error" for issue in self.issues),
                      warnings=sum(issue["severity"] == "warning" for issue in self.issues))
        result = {"revision": self.transfer.revision, "preview_hash": "", "ready": counts["errors"] == 0 and bool(self.rows),
                  "counts": counts, "issues": self.issues, "rows": self.rows,
                  "total_rows": len(self.rows), "next_offset": None}
        return result


async def build_preview(db, transfer, *, for_commit=False):
    source = await get_source(db, transfer.source_id, lock=True)
    normalized = await _normalise(db, source, transfer.config)
    if normalized["error_count"]:
        # The parser's errors are capped; the exact counter is the safety gate.
        result = {
            "revision": transfer.revision, "preview_hash": "", "ready": False,
            "counts": {"total": normalized["total_rows"], "errors": normalized["error_count"], "warnings": normalized["warning_count"]},
            "issues": normalized["issues"], "rows": [{
                "row_key": record["kind"] + ":" + source_identity(record["kind"], record["values"]),
                "kind": record["kind"], "sheet_id": record["sheet_id"], "row": record["row"],
                "source_key": source_identity(record["kind"], record["values"]), "outcome": "blocked",
                "target_id": None, "changes": {"case_mapping_key": case_ref(record["values"].get("case_key", ""))},
                "issues": [],
            } for record in normalized["records"]], "total_rows": len(normalized["records"]), "next_offset": None,
        }
        result["preview_hash"] = digest([source.sha256, source.revision, transfer.revision, transfer.config, result])
        return result, None
    scope = await source_scope(db, transfer.config, normalized["records"])
    if for_commit:
        actor_ids = [UUID(choice["user_id"]) for choice in transfer.config["actors"].values() if choice.get("user_id")]
        await lock_targets(db, scope["case_ids"], actor_ids)
    snapshot = await _target_snapshot(db, transfer.config, scope)
    planner = Planner(transfer, normalized, snapshot)
    try:
        result = planner.build()
    except (ValueError, KeyError, TypeError):
        _fail("invalid_canonical_records", "Нормализованные данные не соответствуют контракту переноса.", 422)
    result["preview_hash"] = digest([source.sha256, source.revision, transfer.revision, transfer.config,
                                      normalized["parser_version"], snapshot, result, planner.operations])
    return result, planner


async def preview_transfer(db, transfer_id, revision, admin_id):
    await lock_transfers(db)
    transfer = await get_transfer(db, transfer_id, lock=True)
    check_revision(transfer, revision, editable=True)
    result, _ = await build_preview(db, transfer)
    transfer.preview = result
    transfer.preview_hash = result["preview_hash"]
    transfer.status = "previewed"
    transfer.updated_at = utc_now()
    await record_journal(db, transfer, admin_id, "audit_legacy_transfer_previewed")
    return transfer


def database_values(table, values):
    result = {}
    for name, value in values.items():
        column = table.c[name]
        if value is None:
            result[name] = None
        elif column.type.python_type is UUID:
            result[name] = UUID(value) if isinstance(value, str) else value
        elif column.type.python_type is datetime:
            result[name] = datetime.fromisoformat(value)
        elif column.type.python_type is date:
            result[name] = date.fromisoformat(value)
        else:
            result[name] = value
    return result


async def target_row(db, table_name, target_id):
    table = MODELS[table_name].__table__
    row = (await db.execute(select(table).where(table.c.id == UUID(str(target_id))))).mappings().one_or_none()
    return json_value(dict(row)) if row else None


async def bulk_insert(db, table, rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(sorted(row))].append(row)
    for group in groups.values():
        for offset in range(0, len(group), 1000):
            await db.execute(table.insert(), group[offset:offset + 1000])


async def target_rows(db, ids_by_table):
    result = {}
    for table_name, identifiers in ids_by_table.items():
        table = MODELS[table_name].__table__
        identifiers = sorted({UUID(str(value)) for value in identifiers})
        for offset in range(0, len(identifiers), 1000):
            rows = (await db.execute(select(table).where(table.c.id.in_(identifiers[offset:offset + 1000])))).mappings()
            result.update({(table_name, str(row["id"])): json_value(dict(row)) for row in rows})
    return result


async def commit_transfer(db, transfer_id, payload, admin_id):
    await lock_transfers(db)
    transfer = await get_transfer(db, transfer_id, lock=True)
    commit_key = digest([str(transfer.id), payload.revision, payload.preview_hash])
    if transfer.status == "committed" and transfer.commit_key == commit_key:
        return transfer
    check_revision(transfer, payload.revision, editable=True)
    if not transfer.preview or not transfer.preview["ready"] or payload.preview_hash != transfer.preview_hash:
        _fail("valid_preview_required", "Нужен актуальный preview без блокирующих ошибок.")
    result, planner = await build_preview(db, transfer, for_commit=True)
    if result["preview_hash"] != payload.preview_hash or not result["ready"]:
        _fail("stale_preview", "Исходник, цели или доступ сотрудников изменились. Повторите preview.")
    inserts = defaultdict(list)
    for operation in planner.operations:
        table = MODELS[operation["table"]].__table__
        values = dict(operation["values"])
        if "contract_reference" in values:
            values["contract_reference_ciphertext"] = encrypt_contract_reference(values.pop("contract_reference"))
        if operation["action"] == "create":
            values["id"] = operation["id"]
            if operation["table"] == "audit_cases":
                values["created_by_id"] = str(admin_id)
            if operation["table"] == "audit_assignments":
                values["assigned_by_id"] = str(admin_id)
            inserts[operation["table"]].append(database_values(table, values))
        else:
            await db.execute(update(table).where(table.c.id == UUID(operation["id"])).values(**database_values(table, values)))
    for table_name in ("audit_cases", "audit_atoms", "audit_assignments", "audit_events", "audit_legacy_metrics"):
        await bulk_insert(db, MODELS[table_name].__table__, inserts[table_name])
    target_ids = defaultdict(set)
    for receipt in planner.receipts.values():
        if receipt["row"]["target_id"]:
            target_ids[receipt["table"]].add(receipt["row"]["target_id"])
    for operation in planner.operations:
        target_ids[operation["table"]].add(operation["id"])
    postimages = await target_rows(db, target_ids)
    provenances, journal_rows = [], []
    mutation_receipts = set()
    for receipt in planner.receipts.values():
        row = receipt["row"]
        if row["outcome"] in ("skip", "blocked"):
            continue
        provenance_id = receipt["provenance_id"]
        if provenance_id is None:
            provenance_id = uuid4()
            provenances.append(dict(
                id=provenance_id, transfer_id=transfer.id, namespace=transfer.namespace, kind=row["kind"],
                source_key=row["source_key"], source_key_hash=row["source_key"], content_hash=receipt["content_hash"],
                target_table=receipt["table"], target_id=UUID(row["target_id"]), active=True,
            ))
        target_key = (receipt["table"], row["target_id"])
        mutation = planner.pending_operations.get(target_key) if target_key not in mutation_receipts else None
        if mutation:
            mutation_receipts.add(target_key)
        journal_rows.append(dict(
            id=uuid4(),
            transfer_id=transfer.id, row_key=row["row_key"], provenance_id=UUID(str(provenance_id)),
            target_table=receipt["table"], target_id=UUID(row["target_id"]), outcome=mutation["action"] if mutation else "reuse",
            owned=bool(mutation and mutation["action"] == "create"), before=mutation["before"] if mutation else None,
            after=postimages[(receipt["table"], row["target_id"])],
        ))
    # Auxiliary snapshot events are import-owned and receive their own rollback receipts.
    for operation in planner.operations:
        if operation["row_key"].endswith(":event"):
            journal_rows.append(dict(
                id=uuid4(), provenance_id=None,
                transfer_id=transfer.id, row_key=operation["row_key"], target_table=operation["table"],
                target_id=UUID(operation["id"]), outcome="create", owned=True, before=None,
                after=postimages[(operation["table"], operation["id"])],
            ))
    await bulk_insert(db, AuditLegacyProvenance.__table__, provenances)
    await bulk_insert(db, AuditLegacyTransferRow.__table__, journal_rows)
    transfer.status = "committed"
    transfer.commit_key = commit_key
    transfer.committed_revision = payload.revision
    transfer.revision += 1
    transfer.committed_at = utc_now()
    transfer.committed_by_id = admin_id
    transfer.updated_at = utc_now()
    transfer.summary = {"counts": result["counts"]}
    await db.flush()
    await record_journal(db, transfer, admin_id, "audit_legacy_transfer_committed")
    return transfer


async def rollback_transfer(db, transfer_id, payload, admin_id):
    await lock_transfers(db)
    transfer = await get_transfer(db, transfer_id, lock=True)
    if transfer.status == "rolled_back" and payload.revision == transfer.revision - 1 and payload.reason == transfer.rollback_reason:
        return transfer
    check_revision(transfer, payload.revision)
    if transfer.status != "committed":
        _fail("committed_transfer_required", "Отмена доступна только для подтверждённого переноса.")
    rows = list((await db.execute(select(AuditLegacyTransferRow).where(AuditLegacyTransferRow.transfer_id == transfer.id))).scalars())
    case_ids = {row.target_id if row.target_table == "audit_cases" else UUID(row.after["case_id"])
                for row in rows if row.target_table == "audit_cases" or row.after and row.after.get("case_id")}
    await lock_targets(db, case_ids)
    changed = [row for row in rows if row.owned or row.outcome == "fill_empty"]
    owned = {(row.target_table, str(row.target_id)) for row in rows if row.owned}
    provenance_ids = set((await db.execute(select(AuditLegacyProvenance.id).where(AuditLegacyProvenance.transfer_id == transfer.id))).scalars())
    dependencies = (await db.execute(select(AuditLegacyTransferRow).join(
        AuditLegacyTransfer, AuditLegacyTransferRow.transfer_id == AuditLegacyTransfer.id,
    ).where(
        AuditLegacyTransfer.id != transfer.id, AuditLegacyTransfer.status == "committed",
    ))).scalars()
    touched = {(row.target_table, str(row.target_id)) for row in changed}
    for row in dependencies:
        if row.provenance_id in provenance_ids or (row.target_table, str(row.target_id)) in touched:
            _fail("rollback_cross_batch_reference", "Другой перенос использует эти данные; сначала отмените зависимый перенос.")
    ids_by_table = defaultdict(set)
    for row in changed:
        ids_by_table[row.target_table].add(row.target_id)
    current_rows = await target_rows(db, ids_by_table)
    for row in changed:
        if current_rows.get((row.target_table, str(row.target_id))) != row.after:
            _fail("rollback_target_changed", "Данные после переноса изменены или удалены; автоматическая отмена запрещена.")
    # Discover every mapped FK, batching the checks instead of querying per atom.
    for table in Base.metadata.tables.values():
        for foreign in table.foreign_keys:
            target_table = foreign.target_fullname.rsplit(".", 1)[0]
            identifiers = sorted(ids_by_table.get(target_table, set()))
            for offset in range(0, len(identifiers), 1000):
                references = (await db.execute(select(table.c.id).where(foreign.parent.in_(identifiers[offset:offset + 1000])))).scalars()
                if any((table.name, str(identifier)) not in owned for identifier in references):
                    _fail("rollback_live_reference", "Есть живые события, документы или внешние ссылки; отмена запрещена.")
    # Delete children before parents and use Core to avoid ORM cascade side effects.
    for table_name in ("audit_events", "audit_assignments", "audit_legacy_metrics", "audit_atoms", "audit_cases"):
        table = MODELS[table_name].__table__
        deleted_ids = []
        for row in changed:
            if row.target_table != table_name:
                continue
            if row.owned:
                deleted_ids.append(row.target_id)
            else:
                before = {k: v for k, v in row.before.items() if k != "id"}
                await db.execute(update(table).where(table.c.id == row.target_id).values(**database_values(table, before)))
        for offset in range(0, len(deleted_ids), 1000):
            await db.execute(delete(table).where(table.c.id.in_(deleted_ids[offset:offset + 1000])))
    await db.execute(update(AuditLegacyProvenance).where(AuditLegacyProvenance.transfer_id == transfer.id).values(active=False))
    transfer.status = "rolled_back"
    transfer.revision += 1
    transfer.rolled_back_at = utc_now()
    transfer.rolled_back_by_id = admin_id
    transfer.rollback_reason = payload.reason
    transfer.updated_at = utc_now()
    await record_journal(db, transfer, admin_id, "audit_legacy_transfer_rolled_back")
    return transfer
