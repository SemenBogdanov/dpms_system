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
    legacy_transfer_id: UUID | None = None
    legacy_effective_at: datetime | None = None
    legacy_snapshot_state: str | None = None
    alpha_date: date | None = None
    commission_date: date | None = None


@dataclass(frozen=True)
class AuditStatisticsStateEvent:
    atom_id: UUID
    created_at: datetime
    previous_state: str
    state: str
    occurred_at: datetime | None = None
    legacy_transfer_id: UUID | None = None

    @property
    def business_time(self) -> datetime | None:
        if self.legacy_transfer_id is not None:
            return self.occurred_at
        return self.occurred_at or self.created_at


@dataclass(frozen=True)
class AuditStatisticsLegacyMetric:
    case_id: UUID
    metric_date: date
    metric_type: str
    value: int


@dataclass(frozen=True)
class AuditStatisticsReviewEvent:
    atom_id: UUID
    metric_date: date
    metric_type: str


def statistics_period(days: int, *, today: date | None = None) -> tuple[date, date]:
    period_end = today or datetime.now(AUDIT_STATISTICS_TIMEZONE).date()
    return period_end - timedelta(days=days - 1), period_end


def period_start_utc(period_start: date) -> datetime:
    local_start = datetime.combine(period_start, datetime.min.time(), tzinfo=AUDIT_STATISTICS_TIMEZONE)
    return local_start.astimezone(timezone.utc)


def _local_date(value: datetime) -> date:
    return _utc(value).astimezone(AUDIT_STATISTICS_TIMEZONE).date()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
) -> tuple[list[dict[str, int | str]], set[tuple[UUID, date, str]]]:
    atoms_by_id = {atom.id: atom for atom in atoms}
    events_by_atom: dict[UUID, list[AuditStatisticsStateEvent]] = defaultdict(list)
    for event in events:
        if event.atom_id in atoms_by_id and event.business_time is not None:
            events_by_atom[event.atom_id].append(event)
    for atom_events in events_by_atom.values():
        atom_events.sort(key=lambda item: _utc(item.business_time))

    changes_by_day: dict[date, list[int]] = defaultdict(list)
    coverage: set[tuple[UUID, date, str]] = set()
    baseline_verified = 0
    for atom in atoms:
        atom_events = events_by_atom.get(atom.id, [])
        snapshot_time = atom.created_at if atom.legacy_transfer_id is None else atom.legacy_effective_at
        # This is a confirmed verification date, never the workbook/import date.
        # Explicit source transitions replace this fallback entirely.
        if any(
            event.legacy_transfer_id is not None
            for event in atom_events
        ):
            snapshot_time = None
        transitions = [
            (event.business_time, event.previous_state, event.state)
            for event in atom_events
        ]
        if snapshot_time is not None:
            initial_state = (
                atom.legacy_snapshot_state
                if atom.legacy_transfer_id is not None and atom.legacy_snapshot_state is not None
                else atom_events[0].previous_state if atom_events else atom.state
            )
            transitions.insert(0, (snapshot_time, None, initial_state))
        transitions.sort(key=lambda item: _utc(item[0]))
        # Track each atom independently: excluding an undated atom must not
        # subtract another atom's known historical verification.
        counted_ready = False
        for business_time, previous_state, state in transitions:
            day = _local_date(business_time)
            if day > period_end:
                break
            change = 0
            if previous_state != "ready" and state == "ready" and not counted_ready:
                counted_ready = True
                change = 1
                coverage.add((atom.case_id, day, "verified"))
            elif state != "ready" and counted_ready:
                counted_ready = False
                change = -1
            if day < period_start:
                baseline_verified += change
            else:
                changes_by_day[day].append(change)

    result: list[dict[str, int | str]] = []
    cumulative = baseline_verified
    current_day = period_start
    while current_day <= period_end:
        changes = changes_by_day.get(current_day, [])
        verified_today = sum(change == 1 for change in changes)
        cumulative += sum(changes)
        result.append(
            {
                "date": current_day.isoformat(),
                "verified_count": verified_today,
                "cumulative_verified_count": cumulative,
            }
        )
        current_day += timedelta(days=1)
    return result, coverage


def _aggregate_trend(
    metrics: Iterable[AuditStatisticsLegacyMetric],
    *,
    incomplete_cells: set[tuple[date, str]],
    period_start: date,
    period_end: date,
) -> list[dict]:
    by_day: dict[date, dict[str, int]] = defaultdict(dict)
    for metric in metrics:
        if period_start <= metric.metric_date <= period_end:
            values = by_day[metric.metric_date]
            values[metric.metric_type] = values.get(metric.metric_type, 0) + metric.value
    if not by_day and not incomplete_cells:
        return []
    result = []
    day = period_start
    while day <= period_end:
        result.append({
            "date": day.isoformat(),
            # Missing facts and partial sums are gaps, not observed zeroes.
            **{f"{kind}_count": (
                None if (day, kind) in incomplete_cells else by_day.get(day, {}).get(kind)
            ) for kind in (
                "verified", "alpha_reviewed", "commission_reviewed",
            )},
        })
        day += timedelta(days=1)
    return result


def build_audit_statistics(
    cases: Iterable[AuditStatisticsCaseRecord],
    atoms: Iterable[AuditStatisticsAtomRecord],
    events: Iterable[AuditStatisticsStateEvent],
    *,
    period_start: date,
    period_end: date,
    metrics: Iterable[AuditStatisticsLegacyMetric] = (),
    review_events: Iterable[AuditStatisticsReviewEvent] = (),
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
    dated_history_atom_ids = {
        event.atom_id for event in event_records
        if event.legacy_transfer_id is not None and event.occurred_at is not None
    }
    trend, coverage = _verification_trend(
        atom_records, event_records, period_start=period_start, period_end=period_end,
    )
    atom_by_id = {atom.id: atom for atom in atom_records}
    for atom in atom_records:
        for result, fact_date, metric_type in (
            (atom.alpha_result, atom.alpha_date, "alpha_reviewed"),
            (atom.commission_result, atom.commission_date, "commission_reviewed"),
        ):
            if result is not None and fact_date is not None:
                coverage.add((atom.case_id, fact_date, metric_type))
    for event in review_events:
        atom = atom_by_id.get(event.atom_id)
        if atom is not None:
            coverage.add((atom.case_id, event.metric_date, event.metric_type))
    visible_metrics = []
    incomplete_cells: set[tuple[date, str]] = set()
    aggregate_conflict_count = 0
    for metric in metrics:
        if metric.case_id not in case_stage_by_id or not period_start <= metric.metric_date <= period_end:
            continue
        # Live facts may be backdated after transfer commit. Keep imported facts
        # immutable, but never present overlapping coverage as additive history.
        if (metric.case_id, metric.metric_date, metric.metric_type) in coverage:
            aggregate_conflict_count += 1
            incomplete_cells.add((metric.metric_date, metric.metric_type))
        else:
            visible_metrics.append(metric)

    return {
        "date_from": period_start,
        "date_to": period_end,
        "aggregate_conflict_count": aggregate_conflict_count,
        "undated_legacy_atoms": sum(
            atom.legacy_transfer_id is not None
            and atom.legacy_effective_at is None
            and atom.id not in dated_history_atom_ids
            for atom in atom_records
        ),
        "aggregate_trend": _aggregate_trend(
            visible_metrics,
            incomplete_cells=incomplete_cells,
            period_start=period_start,
            period_end=period_end,
        ),
        "trend": trend,
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
