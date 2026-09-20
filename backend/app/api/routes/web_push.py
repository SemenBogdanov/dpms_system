"""Authenticated iPhone Web Push subscription management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.web_push import WebPushSubscription
from app.services.web_push import endpoint_hash, public_key, save_subscription

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=128)
    auth: str = Field(min_length=20, max_length=64)


class SubscriptionInput(BaseModel):
    endpoint: str = Field(min_length=30, max_length=2048)
    keys: SubscriptionKeys


@router.get("/config")
async def get_config(user: User = Depends(get_current_user)):
    key = public_key()
    return {"available": key is not None, "public_key": key}


@router.post("/subscriptions", status_code=201)
async def subscribe(payload: SubscriptionInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if public_key() is None:
        raise HTTPException(503, "Push-уведомления пока не настроены")
    try:
        await save_subscription(db, user_id=user.id, endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth_value=payload.keys.auth)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await db.commit()
    return {"ok": True}


@router.delete("/subscriptions")
async def unsubscribe(payload: SubscriptionInput, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(WebPushSubscription).where(WebPushSubscription.user_id == user.id, WebPushSubscription.endpoint_hash == endpoint_hash(payload.endpoint)))
    await db.commit()
    return {"ok": True}
