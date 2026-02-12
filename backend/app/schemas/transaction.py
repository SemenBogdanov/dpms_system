"""Схемы для журнала Q-транзакций."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.transaction import WalletType


class QTransactionRead(BaseModel):
    """Чтение записи транзакции (только чтение, запись через сервис)."""
    id: UUID
    user_id: UUID
    amount: Decimal
    wallet_type: WalletType
    reason: str
    task_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
