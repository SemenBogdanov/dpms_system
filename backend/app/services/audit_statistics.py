"""Pure aggregation helpers for the audit statistics workspace."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID
from zoneinfo import ZoneInfo


AUDIT_STATISTICS_TIMEZONE = ZoneInfo("Europe/Moscow")
IN_PROGRESS_STAGES = {
    "atomization",
    "alpha_review",
    "commission_pending",
    "fixes_required",
    "fixing",
    "recommission_pending",
}
ALPHA_NEEDS_WORK_RESULTS = {"not_present", "partial", "needs_clarification"}
COMMISSION_NEEDS_WORK_RESULTS = {"not_confirmed", "deferred"}
FINAL_COMMISSION_RESULTS = {"confirmed", "not_applicable"}


@dataclass(frozen=True)
class AuditStatisticsCaseRecord:
    id: UUID
    status: str
    workflow_stage: str


@dataclass(frozen=True)
class AuditStatisticsAtomRecord:
    id: UUID
    case_id: UUID
    state: str
    alpha_result: str | None
    commission_result: str | None
    created_at: datetime


@dataclass(frozen=True)
class AuditStatisticsStateEvent:
    atom_id: UUID
    created_at: datetime
    previous_state: str
    state: str


def statistics_period(days: int, *, today: date | None = None) -> tuple[date, date]:
    period_end = today or datetime.now(AUDIT_STATISTICS_TIMEZONE).date()
    return period_end - timedelta(days=days - 1), period_end


def period_start_utc(period_start: date) -> datetime:
    local_start = datetime.combine(period_start, datetime.min.time(), tzinfo=AUDIT_STATISTICS_TIMEZONE)
    return local_start.astimezone(timezone.utc)


def _local_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(AUDIT_STATISTICS_TIMEZONE).date()


def _case_atom_counts(
    audit_case: AuditStatisticsCaseRecord,
    atoms: list[AuditStatisticsAtomRecord],
) -> dict[str, int]:
    active = [atom for atom in atoms if atom.state != "excluded"]
    ready = [atom for atom in active if atom.state == "ready"]
    alpha_reviewed = [atom for atom in ready if atom.alpha_result is not None]
    commission_reviewed = [atom for atom in ready if atom.commission_result is not None]
    final_confirmed = [atom for atom in ready if atom.commission_result in FINAL_COMMISSION_RESULTS]
    fully_atomized = bool(active) and len(ready) == len(active)
    return {
        "active": len(active),
        "ready": len(ready),
        "alpha_reviewed": len(alpha_reviewed),
        "commission_reviewed": len(commission_reviewed),
        "final_confirmed": len(final_confirmed),
        "alpha_complete": int(fully_atomized and len(alpha_reviewed) == len(ready)),
        "alpha_commission_complete": int(
            fully_atomized and len(commission_reviewed) == len(ready)
        ),
        "beta_commission_complete": int(
            audit_case.workflow_stage == "ready"
            and fully_atomized
            and len(final_confirmed) == len(ready)
        ),
    }


def _verification_trend(
    atoms: list[AuditStatisticsAtomRecord],
    events: list[AuditStatisticsStateEvent],
    *,
    period_start: date,
    period_end: date,
) -> list[dict[str, int | str]]:
    atoms_by_id = {atom.id: atom for atom in atoms}
    events_by_atom: dict[UUID, list[AuditStatisticsStateEvent]] = defaultdict(list)
    for event in events:
        if event.atom_id in atoms_by_id and period_start <= _local_date(event.created_at) <= period_end:
            events_by_atom[event.atom_id].append(event)
    for atom_events in events_by_atom.values():
        atom_events.sort(key=lambda item: item.created_at)

    transitions_by_day: dict[date, list[tuple[str | None, str]]] = defaultdict(list)
    baseline_verified = 0
    for atom in atoms:
        atom_events = events_by_atom.get(atom.id, [])
        created_day = _local_date(atom.created_at)
        if created_day >= period_start:
            initial_state = atom_events[0].previous_state if atom_events else atom.state
            if created_day <= period_end:
                transitions_by_day[created_day].append((None, initial_state))
        else:
            state_at_period_start = atom.state
            for event in reversed(atom_events):
                state_at_period_start = event.previous_state
            if state_at_period_start == "ready":
                baseline_verified += 1
        for event in atom_events:
            transitions_by_day[_local_date(event.created_at)].append(
                (event.previous_state, event.state)
            )

    result: list[dict[str, int | str]] = []
    cumulative = baseline_verified
    current_day = period_start
    while current_day <= period_end:
        verified_today = 0
        for previous_state, state in transitions_by_day.get(current_day, []):
            if previous_state != "ready" and state == "ready":
                verified_today += 1
                cumulative += 1
            elif previous_state == "ready" and state != "ready":
                cumulative = max(0, cumulative - 1)
        result.append(
            {
                "date": current_day.isoformat(),
                "verified_count": verified_today,
                "cumulative_verified_count": cumulative,
            }
        )
        current_day += timedelta(days=1)
    return result


def build_audit_statistics(
    cases: Iterable[AuditStatisticsCaseRecord],
    atoms: Iterable[AuditStatisticsAtomRecord],
    events: Iterable[AuditStatisticsStateEvent],
    *,
    period_start: date,
    period_end: date,
) -> dict:
    case_records = list(cases)
    atom_records = list(atoms)
    event_records = list(events)
    atoms_by_case: dict[UUID, list[AuditStatisticsAtomRecord]] = defaultdict(list)
    for atom in atom_records:
        atoms_by_case[atom.case_id].append(atom)

    case_counts = [
        _case_atom_counts(audit_case, atoms_by_case.get(audit_case.id, []))
        for audit_case in case_records
    ]
    active_atoms = [atom for atom in atom_records if atom.state != "excluded"]
    ready_atoms = [atom for atom in active_atoms if atom.state == "ready"]
    alpha_reviewed = [atom for atom in ready_atoms if atom.alpha_result is not None]
    commission_reviewed = [atom for atom in ready_atoms if atom.commission_result is not None]
    case_stage_by_id = {audit_case.id: audit_case.workflow_stage for audit_case in case_records}

    return {
        "date_from": period_start,
        "date_to": period_end,
        "trend": _verification_trend(
            atom_records,
            event_records,
            period_start=period_start,
            period_end=period_end,
        ),
        "contracts": {
            "total": len(case_records),
            "in_progress": sum(
                audit_case.status != "archived"
                and audit_case.workflow_stage in IN_PROGRESS_STAGES
                for audit_case in case_records
            ),
            "alpha_review_completed": sum(item["alpha_complete"] for item in case_counts),
            "alpha_commission_completed": sum(
                item["alpha_commission_complete"] for item in case_counts
            ),
            "beta_commission_completed": sum(
                item["beta_commission_complete"] for item in case_counts
            ),
        },
        "atoms": {
            "total": len(active_atoms),
            "excluded": sum(atom.state == "excluded" for atom in atom_records),
            "verified": len(ready_atoms),
            "alpha_review_completed": len(alpha_reviewed),
            "alpha_review_needs_work": sum(
                atom.alpha_result in ALPHA_NEEDS_WORK_RESULTS for atom in alpha_reviewed
            ),
            "alpha_commission_completed": len(commission_reviewed),
            "alpha_commission_needs_work": sum(
                atom.commission_result in COMMISSION_NEEDS_WORK_RESULTS
                for atom in commission_reviewed
            ),
            "beta_commission_completed": sum(
                atom.commission_result in FINAL_COMMISSION_RESULTS
                and case_stage_by_id.get(atom.case_id) == "ready"
                for atom in ready_atoms
            ),
        },
    }
