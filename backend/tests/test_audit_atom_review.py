"""Contract and persistence tests for sequential audit atom review."""

from datetime import date, datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes.audit import (
    bulk_update_audit_atom_status,
    create_audit_atom,
    start_audit_alpha_review,
    update_audit_atom,
)
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.audit import AuditAtom, AuditCase, AuditEvent
from app.models.user import User, UserRole
from app.schemas.audit import AuditAtomBulkStatusUpdate, AuditAtomCreate, AuditAtomUpdate


class AuditAtomReviewContractTests(unittest.TestCase):
    def test_openapi_exposes_alpha_review_start(self):
        paths = app.openapi()["paths"]

        self.assertIn("post", paths["/api/audit/cases/{case_id}/alpha-review/start"])

    def test_update_accepts_optimistic_lock_and_alpha_comment(self):
        timestamp = datetime.now(timezone.utc)

        payload = AuditAtomUpdate(
            expected_updated_at=timestamp,
            alpha_result="not_present",
            alpha_comment="Экран не найден в проверяемой системе",
        )

        self.assertEqual(payload.expected_updated_at, timestamp)
        self.assertEqual(payload.alpha_result, "not_present")
        self.assertEqual(payload.alpha_comment, "Экран не найден в проверяемой системе")

    def test_update_requires_optimistic_lock(self):
        with self.assertRaises(ValidationError):
            AuditAtomUpdate(state="ready")

    def test_bulk_versions_must_match_selected_atoms(self):
        with self.assertRaises(ValidationError):
            AuditAtomBulkStatusUpdate(
                atom_ids=[uuid4()],
                expected_updated_at_by_atom={},
                state="ready",
            )


@unittest.skipUnless(os.getenv("DPMS_RUN_DB_TESTS") == "1", "database route tests disabled")
class AuditAtomReviewPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await engine.dispose()

    async def _manager(self, db) -> User:
        manager = await db.scalar(
            select(User).where(User.role == UserRole.admin, User.is_active.is_(True)).limit(1)
        )
        self.assertIsNotNone(manager)
        return manager

    async def _case(self, db, manager: User, states: list[str]) -> tuple[AuditCase, list[AuditAtom]]:
        audit_case = AuditCase(
            created_by_id=manager.id,
            responsible_user_id=manager.id,
            title=f"Последовательная проверка {uuid4()}",
            digital_product="TEST",
            status="atomization",
            workflow_stage="atomization",
        )
        db.add(audit_case)
        await db.flush()

        atoms = [
            AuditAtom(
                case_id=audit_case.id,
                item_code=f"TEST-{index:03d}",
                title=f"Проверяемый атом {index}",
                digital_product="TEST",
                source_clause=f"1.{index}",
                source_evidence_text=f"Основание атома {index}",
                state=state,
                sort_order=index,
            )
            for index, state in enumerate(states, start=1)
        ]
        db.add_all(atoms)
        await db.flush()
        return audit_case, atoms

    async def test_alpha_review_rejects_unreviewed_drafts(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, _ = await self._case(db, manager, ["ready", "draft"])

                with self.assertRaises(HTTPException) as context:
                    await start_audit_alpha_review(audit_case.id, user=manager, db=db)

                self.assertEqual(context.exception.status_code, 409)
                self.assertIn("осталось 1", context.exception.detail)
                self.assertEqual(audit_case.workflow_stage, "atomization")
            finally:
                await db.rollback()

    async def test_alpha_review_starts_after_all_drafts_are_resolved(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, _ = await self._case(db, manager, ["ready", "excluded"])

                response = await start_audit_alpha_review(audit_case.id, user=manager, db=db)
                await db.flush()

                self.assertEqual(response.workflow_stage, "alpha_review")
                self.assertEqual(audit_case.workflow_stage, "alpha_review")
                event = await db.scalar(
                    select(AuditEvent)
                    .where(
                        AuditEvent.case_id == audit_case.id,
                        AuditEvent.event_type == "alpha_review_started",
                    )
                    .order_by(AuditEvent.created_at.desc())
                    .limit(1)
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.payload_json.get("atom_count"), 1)
            finally:
                await db.rollback()

    async def test_atom_update_rejects_stale_version(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, atoms = await self._case(db, manager, ["draft"])
                current_updated_at = atoms[0].updated_at
                if current_updated_at.tzinfo is None:
                    current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)

                with self.assertRaises(HTTPException) as context:
                    await update_audit_atom(
                        audit_case.id,
                        atoms[0].id,
                        AuditAtomUpdate(
                            expected_updated_at=current_updated_at - timedelta(seconds=1),
                            state="ready",
                        ),
                        user=manager,
                        db=db,
                    )

                self.assertEqual(context.exception.status_code, 409)
                self.assertEqual(atoms[0].state, "draft")
            finally:
                await db.rollback()

    async def test_alpha_decision_persists_comment_and_history(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, atoms = await self._case(db, manager, ["ready"])
                await start_audit_alpha_review(audit_case.id, user=manager, db=db)
                current_updated_at = atoms[0].updated_at

                response = await update_audit_atom(
                    audit_case.id,
                    atoms[0].id,
                    AuditAtomUpdate(
                        expected_updated_at=current_updated_at,
                        alpha_result="not_present",
                        alpha_comment="Элемент отсутствует в проверяемой версии",
                        alpha_date=date(2026, 8, 24),
                    ),
                    user=manager,
                    db=db,
                )
                await db.flush()

                self.assertEqual(response.alpha_result, "not_present")
                self.assertEqual(response.alpha_comment, "Элемент отсутствует в проверяемой версии")
                event = await db.scalar(
                    select(AuditEvent)
                    .where(
                        AuditEvent.atom_id == atoms[0].id,
                        AuditEvent.event_type == "atom_alpha_decision_changed",
                    )
                    .order_by(AuditEvent.created_at.desc())
                    .limit(1)
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.payload_json.get("alpha_result"), "not_present")
                self.assertEqual(
                    event.payload_json.get("alpha_comment"),
                    "Элемент отсутствует в проверяемой версии",
                )
            finally:
                await db.rollback()

    async def test_negative_alpha_decision_requires_comment(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, atoms = await self._case(db, manager, ["ready"])
                await start_audit_alpha_review(audit_case.id, user=manager, db=db)

                with self.assertRaises(HTTPException) as context:
                    await update_audit_atom(
                        audit_case.id,
                        atoms[0].id,
                        AuditAtomUpdate(
                            expected_updated_at=atoms[0].updated_at,
                            alpha_result="not_present",
                            alpha_date=date(2026, 8, 24),
                        ),
                        user=manager,
                        db=db,
                    )

                self.assertEqual(context.exception.status_code, 422)
                self.assertIn("комментарий", context.exception.detail)
            finally:
                await db.rollback()

    async def test_scope_edit_returns_case_to_atomization_and_clears_alpha(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, atoms = await self._case(db, manager, ["ready"])
                await start_audit_alpha_review(audit_case.id, user=manager, db=db)
                atoms[0].alpha_result = "present"
                atoms[0].alpha_date = date(2026, 8, 24)
                await db.flush()
                await db.refresh(atoms[0])

                response = await update_audit_atom(
                    audit_case.id,
                    atoms[0].id,
                    AuditAtomUpdate(
                        expected_updated_at=atoms[0].updated_at,
                        title="Уточненная формулировка атома",
                    ),
                    user=manager,
                    db=db,
                )

                self.assertEqual(response.title, "Уточненная формулировка атома")
                self.assertIsNone(response.alpha_result)
                self.assertIsNone(response.alpha_date)
                self.assertEqual(audit_case.workflow_stage, "atomization")
            finally:
                await db.rollback()

    async def test_new_atom_after_alpha_start_returns_case_to_atomization(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, _ = await self._case(db, manager, ["ready"])
                await start_audit_alpha_review(audit_case.id, user=manager, db=db)

                await create_audit_atom(
                    audit_case.id,
                    AuditAtomCreate(title="Новый атом", digital_product="TEST"),
                    user=manager,
                    db=db,
                )

                self.assertEqual(audit_case.workflow_stage, "atomization")
            finally:
                await db.rollback()

    async def test_bulk_update_rejects_stale_atom_version(self):
        async with AsyncSessionLocal() as db:
            try:
                manager = await self._manager(db)
                audit_case, atoms = await self._case(db, manager, ["draft"])
                current_updated_at = atoms[0].updated_at
                if current_updated_at.tzinfo is None:
                    current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)

                with self.assertRaises(HTTPException) as context:
                    await bulk_update_audit_atom_status(
                        audit_case.id,
                        AuditAtomBulkStatusUpdate(
                            atom_ids=[atoms[0].id],
                            expected_updated_at_by_atom={
                                atoms[0].id: current_updated_at - timedelta(seconds=1),
                            },
                            state="ready",
                        ),
                        user=manager,
                        db=db,
                    )

                self.assertEqual(context.exception.status_code, 409)
                self.assertEqual(atoms[0].state, "draft")
            finally:
                await db.rollback()


if __name__ == "__main__":
    unittest.main()
