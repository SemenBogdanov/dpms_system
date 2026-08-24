"""Contract tests for the audit assignment matrix."""

from datetime import date, datetime, timezone
import os
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes.audit import (
    _assignment_read,
    _serialize_case,
    assign_audit_responsible,
    list_audit_assignments,
    replace_audit_assignment_cell,
)
from app.database import AsyncSessionLocal, engine
from app.models.audit import AuditAssignment, AuditCase, AuditEvent, AuditTeamMember
from app.models.user import League, User, UserRole
from app.schemas.audit import AuditAssignmentCellUpdate, AuditResponsibleUpdate


class AuditAssignmentSchemaTests(unittest.TestCase):
    def test_cell_rejects_duplicate_contracts(self):
        case_id = uuid4()

        with self.assertRaises(ValidationError):
            AuditAssignmentCellUpdate(
                scheduled_date=date(2026, 8, 23),
                assignee_id=uuid4(),
                expected_case_ids=[],
                case_ids=[case_id, case_id],
            )

    def test_cell_rejects_transfer_for_unselected_contract(self):
        with self.assertRaises(ValidationError):
            AuditAssignmentCellUpdate(
                scheduled_date=date(2026, 8, 23),
                assignee_id=uuid4(),
                expected_case_ids=[],
                case_ids=[],
                transfer_case_ids=[uuid4()],
            )

    def test_response_uses_current_contract_stage(self):
        now = datetime.now(timezone.utc)
        assignment = SimpleNamespace(
            id=uuid4(),
            case_id=uuid4(),
            assignee_id=uuid4(),
            scheduled_date=date(2026, 8, 23),
            assigned_by_id=None,
            created_at=now,
            updated_at=now,
        )
        audit_case = SimpleNamespace(
            id=assignment.case_id,
            case_number="AUD-0042",
            title="Проверка продукта",
            digital_product="DASH",
            status="atomization",
            workflow_stage="alpha_review",
        )
        assignee = SimpleNamespace(id=assignment.assignee_id, full_name="Иван Петров")

        result = _assignment_read(assignment, audit_case, assignee, atoms_count=17)

        self.assertEqual(result.case_status, "atomization")
        self.assertEqual(result.workflow_stage, "alpha_review")
        self.assertEqual(result.atoms_count, 17)
        audit_case.status = "ready"
        self.assertEqual(_assignment_read(assignment, audit_case, assignee).case_status, "ready")


class AuditAssignmentRangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_reversed_period_before_database_query(self):
        with self.assertRaises(HTTPException) as context:
            await list_audit_assignments(
                date_from=date(2026, 8, 24),
                date_to=date(2026, 8, 23),
                _=SimpleNamespace(),
                db=SimpleNamespace(),
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("раньше", context.exception.detail)

    async def test_rejects_period_longer_than_92_days(self):
        with self.assertRaises(HTTPException) as context:
            await list_audit_assignments(
                date_from=date(2026, 1, 1),
                date_to=date(2026, 4, 3),
                _=SimpleNamespace(),
                db=SimpleNamespace(),
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("92", context.exception.detail)


@unittest.skipUnless(os.getenv("DPMS_RUN_DB_TESTS") == "1", "database route tests disabled")
class AuditAssignmentPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await engine.dispose()

    async def _load_or_create_fixture(self, db):
        manager = await db.scalar(
            select(User).where(User.role == UserRole.admin, User.is_active.is_(True)).limit(1)
        )
        self.assertIsNotNone(manager)

        assignee = await db.scalar(
            select(User)
            .join(AuditTeamMember, AuditTeamMember.user_id == User.id)
            .where(User.is_active.is_(True))
            .limit(1)
        )
        if assignee is None:
            assignee = User(
                full_name="Тестовый аудитор",
                email=f"audit-assignee-{uuid4()}@example.test",
                league=League.C,
                role=UserRole.executor,
                audit_enabled=True,
                is_active=True,
            )
            db.add(assignee)
            await db.flush()
            db.add(
                AuditTeamMember(
                    user_id=assignee.id,
                    role="member",
                    added_by_id=manager.id,
                )
            )
            await db.flush()

        audit_case = await db.scalar(
            select(AuditCase).where(AuditCase.status != "archived").limit(1)
        )
        if audit_case is None:
            audit_case = AuditCase(
                created_by_id=manager.id,
                title="Тестовый договор назначения",
                digital_product="TEST",
                status="draft",
                workflow_stage="unassigned",
            )
            db.add(audit_case)
            await db.flush()

        return manager, assignee, audit_case

    async def test_new_assignment_updates_responsible_and_writes_both_events(self):
        scheduled_date = date(2099, 12, 30)
        async with AsyncSessionLocal() as db:
            try:
                manager, assignee, audit_case = await self._load_or_create_fixture(db)

                audit_case.responsible_user_id = None
                audit_case.status = "draft"
                audit_case.workflow_stage = "unassigned"
                current = list(
                    (
                        await db.scalars(
                            select(AuditAssignment).where(
                                (AuditAssignment.case_id == audit_case.id)
                                | (
                                    (AuditAssignment.assignee_id == assignee.id)
                                    & (AuditAssignment.scheduled_date == scheduled_date)
                                )
                            )
                        )
                    ).all()
                )
                for assignment in current:
                    await db.delete(assignment)
                await db.flush()

                await replace_audit_assignment_cell(
                    AuditAssignmentCellUpdate(
                        scheduled_date=scheduled_date,
                        assignee_id=assignee.id,
                        expected_case_ids=[],
                        case_ids=[audit_case.id],
                    ),
                    manager=manager,
                    db=db,
                )
                await db.refresh(audit_case)

                self.assertEqual(audit_case.responsible_user_id, assignee.id)
                self.assertEqual(audit_case.workflow_stage, "atomization")
                self.assertEqual(audit_case.status, "atomization")
                events = list(
                    (
                        await db.scalars(
                            select(AuditEvent).where(AuditEvent.case_id == audit_case.id)
                        )
                    ).all()
                )
                matching = {
                    event.event_type
                    for event in events
                    if event.payload_json.get("scheduled_date") == scheduled_date.isoformat()
                }
                self.assertIn("assignment_created", matching)
                self.assertIn("responsible_changed", matching)
            finally:
                await db.rollback()

    async def test_contract_reference_is_redacted_outside_audit_team(self):
        async with AsyncSessionLocal() as db:
            try:
                _, assignee, audit_case = await self._load_or_create_fixture(db)
                audit_case.contract_reference_mask = "AB****42"
                await db.flush()

                hidden = await _serialize_case(
                    db,
                    audit_case,
                    include_atoms=False,
                    can_view_contract_reference=False,
                )
                visible = await _serialize_case(
                    db,
                    audit_case,
                    include_atoms=False,
                    can_view_contract_reference=True,
                )

                self.assertIsNone(hidden.contract_reference_mask)
                self.assertEqual(visible.contract_reference_mask, "AB****42")
                self.assertIsNotNone(assignee.id)
            finally:
                await db.rollback()

    async def test_contract_requires_explicit_transfer_and_keeps_one_assignment(self):
        first_date = date(2099, 12, 28)
        second_date = date(2099, 12, 29)
        async with AsyncSessionLocal() as db:
            try:
                manager, first_assignee, audit_case = await self._load_or_create_fixture(db)

                audit_case.status = "atomization"
                audit_case.workflow_stage = "unassigned"
                audit_case.responsible_user_id = None

                second_assignee = User(
                    full_name="Тестовый аудитор передачи",
                    email=f"audit-transfer-{uuid4()}@example.test",
                    league=League.C,
                    role=UserRole.executor,
                    audit_enabled=True,
                    is_active=True,
                )
                db.add(second_assignee)
                await db.flush()
                db.add(
                    AuditTeamMember(
                        user_id=second_assignee.id,
                        role="member",
                        added_by_id=manager.id,
                    )
                )
                await db.flush()

                existing = list(
                    (
                        await db.scalars(
                            select(AuditAssignment).where(AuditAssignment.case_id == audit_case.id)
                        )
                    ).all()
                )
                for assignment in existing:
                    await db.delete(assignment)
                await db.flush()

                await replace_audit_assignment_cell(
                    AuditAssignmentCellUpdate(
                        scheduled_date=first_date,
                        assignee_id=first_assignee.id,
                        expected_case_ids=[],
                        case_ids=[audit_case.id],
                    ),
                    manager=manager,
                    db=db,
                )

                with self.assertRaises(HTTPException) as responsible_context:
                    await assign_audit_responsible(
                        audit_case.id,
                        AuditResponsibleUpdate(user_id=second_assignee.id),
                        manager=manager,
                        db=db,
                    )
                self.assertEqual(responsible_context.exception.status_code, 409)
                self.assertIn("Назначения", responsible_context.exception.detail)

                with self.assertRaises(HTTPException) as context:
                    await replace_audit_assignment_cell(
                        AuditAssignmentCellUpdate(
                            scheduled_date=second_date,
                            assignee_id=second_assignee.id,
                            expected_case_ids=[],
                            case_ids=[audit_case.id],
                        ),
                        manager=manager,
                        db=db,
                    )
                self.assertEqual(context.exception.status_code, 409)

                await replace_audit_assignment_cell(
                    AuditAssignmentCellUpdate(
                        scheduled_date=second_date,
                        assignee_id=second_assignee.id,
                        expected_case_ids=[],
                        case_ids=[audit_case.id],
                        transfer_case_ids=[audit_case.id],
                    ),
                    manager=manager,
                    db=db,
                )

                assignments = list(
                    (
                        await db.scalars(
                            select(AuditAssignment).where(AuditAssignment.case_id == audit_case.id)
                        )
                    ).all()
                )
                self.assertEqual(len(assignments), 1)
                self.assertEqual(assignments[0].assignee_id, second_assignee.id)
                self.assertEqual(assignments[0].scheduled_date, second_date)
                await db.refresh(audit_case)
                self.assertEqual(audit_case.responsible_user_id, second_assignee.id)
                self.assertEqual(audit_case.workflow_stage, "atomization")

                transferred_event = await db.scalar(
                    select(AuditEvent)
                    .where(
                        AuditEvent.case_id == audit_case.id,
                        AuditEvent.event_type == "assignment_transferred",
                    )
                    .order_by(AuditEvent.created_at.desc())
                    .limit(1)
                )
                self.assertIsNotNone(transferred_event)
                self.assertEqual(
                    transferred_event.payload_json.get("previous_scheduled_date"),
                    first_date.isoformat(),
                )

                await replace_audit_assignment_cell(
                    AuditAssignmentCellUpdate(
                        scheduled_date=second_date,
                        assignee_id=second_assignee.id,
                        expected_case_ids=[audit_case.id],
                        case_ids=[],
                    ),
                    manager=manager,
                    db=db,
                )
                await db.refresh(audit_case)
                self.assertIsNone(
                    await db.scalar(
                        select(AuditAssignment.id).where(AuditAssignment.case_id == audit_case.id)
                    )
                )
                self.assertIsNone(audit_case.responsible_user_id)
                self.assertEqual(audit_case.workflow_stage, "unassigned")
            finally:
                await db.rollback()


if __name__ == "__main__":
    unittest.main()
