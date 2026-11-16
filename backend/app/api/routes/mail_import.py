"""Owner-only Inbox routes and a separate, narrowly scoped device bearer API."""
from contextlib import asynccontextmanager
import re
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.mail_import import (
    MAX_BATCH_BYTES, DeviceCreate, DeviceCreated, DeviceRead, EmptyRequest,
    ImportedItemRead, ItemReadRequest, ItemsRead, Kind, PairRead, PairRequest, SyncRead, SyncRequest,
)
from app.services import mail_import as service


class BoundedPrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            try:
                if request.method == "POST":
                    is_sync = request.url.path.endswith("/sync")
                    if is_sync:
                        headers = request.headers.getlist("authorization")
                        if len(headers) != 1 or re.fullmatch(r"(?i:Bearer) [A-Za-z0-9_-]{43}", headers[0]) is None:
                            raise service.error(401, "invalid_device")
                    maximum = MAX_BATCH_BYTES if is_sync else 16384
                    declared = request.headers.get("content-length")
                    if declared is not None:
                        if not declared.isascii() or not declared.isdigit() or len(declared) > 10:
                            raise service.error(400, "invalid_content_length")
                        if int(declared) > maximum:
                            raise service.error(413, "batch_too_large")
                    if request.headers.get("content-encoding", "identity").lower() != "identity":
                        raise service.error(415, "unsupported_content_encoding")
                    media = request.headers.get("content-type", "").partition(";")[0].strip().lower()
                    if media != "application/json":
                        raise service.error(415, "json_required")
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > maximum:
                            raise service.error(413, "batch_too_large")
                        chunks.append(chunk)
                    # Cache only the bounded bytes, before FastAPI calls request.json().
                    request._body = b"".join(chunks)
                response = await handler(request)
            except RequestValidationError:
                # FastAPI's default validation response echoes inputs, including codes/bodies.
                response = JSONResponse(status_code=422, content={"detail": {"code": "invalid_payload"}})
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
            response.headers["Cache-Control"] = "no-store"
            return response

        return bounded


router = APIRouter(route_class=BoundedPrivateRoute)
device_router = APIRouter(route_class=BoundedPrivateRoute)
device_bearer = HTTPBearer(auto_error=False, scheme_name="MailImportDevice")


@asynccontextmanager
async def committed(db: AsyncSession):
    try:
        yield
        # Do not rely on a yield dependency committing after response serialization.
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise service.error(503, "mail_import_unavailable") from None
    except BaseException:
        await db.rollback()
        raise


@router.get("/devices", response_model=list[DeviceRead])
async def devices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.list_devices(db, user)
    return result


@router.post("/devices", response_model=DeviceCreated, status_code=201)
async def create_device(body: DeviceCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.create_device(db, user, body)
    return result


@router.post("/devices/{device_id}/revoke", response_model=DeviceRead)
async def revoke_device(device_id: UUID, body: EmptyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.revoke_device(db, user, device_id)
    return result


@device_router.post("/pair", response_model=PairRead)
async def pair(body: PairRequest, db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.pair_device(db, body.pairing_code.get_secret_value())
    return result


@device_router.post("/sync", response_model=SyncRead)
async def sync(
    body: SyncRequest,
    bearer: HTTPAuthorizationCredentials | None = Depends(device_bearer),
    db: AsyncSession = Depends(get_db),
):
    if bearer is None or bearer.scheme.lower() != "bearer":
        raise service.error(401, "invalid_device")
    async with committed(db):
        result = await service.sync_items(db, bearer.credentials, body)
    return result


@router.get("/items", response_model=ItemsRead)
async def items(
    kind: Kind | None = None, unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    async with committed(db):
        result = await service.list_items(db, user, kind, unread_only, limit, offset)
    return result


@router.get("/items/{item_id}", response_model=ImportedItemRead)
async def item(item_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.read_item(db, user, item_id)
    return result


@router.post("/items/{item_id}/read", response_model=ImportedItemRead)
async def mark_read(item_id: UUID, body: ItemReadRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async with committed(db):
        result = await service.mark_read(db, user, item_id, body.is_read)
    return result


@router.get("/items/{item_id}/attachments/{attachment_id}")
async def download_attachment(
    item_id: UUID, attachment_id: UUID,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    async with committed(db):
        filename, data = await service.download_attachment(db, user, item_id, attachment_id)
    return Response(content=data, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename=\"attachment\"; filename*=UTF-8''" + quote(filename or "attachment", safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })


router.include_router(device_router)
