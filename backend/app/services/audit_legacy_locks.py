"""Lock only audit roots and projections participating in a historical transfer."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditAssignment, AuditAtom, AuditCase, AuditEvent, AuditTeamMember
from app.models.audit_legacy_transfer import AuditLegacyMetric
from app.models.user import User


async def lock_legacy_targets(
    db: AsyncSession, case_ids: Iterable[UUID], actor_ids: Iterable[UUID] = (),
) -> None:
    if db.bind.dialect.name != "postgresql":
        return
    cases = sorted({UUID(str(value)) for value in case_ids}, key=str)
    actors = sorted({UUID(str(value)) for value in actor_ids}, key=str)
    if cases:
        # FOR UPDATE conflicts with FK KEY SHARE when a concurrent writer adds
        # a child to these roots. Existing children need their own update locks.
        await db.execute(select(AuditCase.id).where(AuditCase.id.in_(cases))
                         .order_by(AuditCase.id).with_for_update())
        for model in (AuditAssignment, AuditAtom, AuditEvent, AuditLegacyMetric):
            await db.execute(select(model.id).where(model.case_id.in_(cases))
                             .order_by(model.id).with_for_update())
    if actors:
        await db.execute(select(User.id).where(User.id.in_(actors))
                         .order_by(User.id).with_for_update(read=True))
        await db.execute(select(AuditTeamMember.id).where(AuditTeamMember.user_id.in_(actors))
                         .order_by(AuditTeamMember.id).with_for_update(read=True))
