"""Client-side diagnostics for browser runtime failures."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("dpms.client")

router = APIRouter()


class ClientEventPayload(BaseModel):
    event_type: str = Field(max_length=80)
    message: str = Field(default="", max_length=800)
    name: str | None = Field(default=None, max_length=120)
    stack: str | None = Field(default=None, max_length=2000)
    route: str | None = Field(default=None, max_length=300)
    release: str | None = Field(default=None, max_length=120)
    user_agent: str | None = Field(default=None, max_length=500)
    viewport: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None


@router.post("")
async def capture_client_event(payload: ClientEventPayload, request: Request):
    """Accept sanitized browser diagnostics and write them to backend logs."""
    logger.warning(
        "client_event event_type=%s name=%s route=%s release=%s viewport=%s ip=%s ua=%s message=%s stack=%s",
        payload.event_type,
        payload.name,
        payload.route,
        payload.release,
        payload.viewport,
        request.client.host if request.client else None,
        payload.user_agent,
        payload.message,
        payload.stack,
    )
    return {"ok": True, "received_at": datetime.now(timezone.utc)}
