"""Bounded V1 mail-import contracts. Public responses never expose credential hashes."""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, StrictBool, field_validator, model_validator


MAX_BATCH_ITEMS = 50
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ITEM_ATTACHMENT_BYTES = 20 * 1024 * 1024
Hex64 = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
Kind = Literal["mail", "meeting"]
SourceState = Literal["cached", "online", "offline"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def no_nul(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("NUL characters are not supported")
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Invalid Unicode text") from None
        return value


class DeviceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    include_body: StrictBool = False
    include_attachments: StrictBool = False

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Device name must not be blank")
        return value.strip()


class DeviceRead(StrictModel):
    id: UUID
    name: str
    status: Literal["pending", "active", "revoked", "expired"]
    include_body: bool
    include_attachments: bool = False
    mailbox_label: str | None
    created_at: AwareDatetime
    last_sync_at: AwareDatetime | None
    source_state: SourceState | None
    expires_at: AwareDatetime | None
    last_scan_complete: bool | None
    last_skipped_items: int = 0


class DeviceCreated(StrictModel):
    device: DeviceRead
    pairing_code: str = Field(repr=False)
    expires_at: AwareDatetime


class PairRequest(StrictModel):
    pairing_code: SecretStr = Field(min_length=43, max_length=43)

    @field_validator("pairing_code")
    @classmethod
    def code_format(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value.get_secret_value()):
            raise ValueError("Invalid pairing code")
        return value


class PairRead(StrictModel):
    device_id: UUID
    device_secret: str = Field(repr=False)
    owner_name: str
    include_body: bool
    include_attachments: bool = False
    protocol_version: Literal[1] = 1


class EmptyRequest(StrictModel):
    pass


class AttachmentInput(StrictModel):
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=200)
    data_base64: str = Field(max_length=4 * ((MAX_ATTACHMENT_BYTES + 2) // 3), repr=False)
    sha256: Hex64
    is_inline: StrictBool = False
    content_id: str = Field(default="", max_length=500)
    _data: bytes = PrivateAttr(default=b"")

    @field_validator("sha256")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def verify_data(self):
        try:
            data = base64.b64decode(self.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid attachment encoding") from None
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Attachment exceeds file byte limit")
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("Attachment checksum mismatch")
        self._data = data
        return self

    @property
    def decoded_data(self) -> bytes:
        return self._data


class AttachmentRead(StrictModel):
    id: UUID
    ordinal: int
    filename: str
    content_type: str
    sha256: str
    size: int
    is_inline: bool
    content_id: str


class ImportedItemInput(StrictModel):
    source_id: Hex64
    kind: Kind
    source_modified_at: AwareDatetime
    received_at: AwareDatetime
    subject: str = Field(max_length=1000)
    sender_name: str = Field(max_length=300)
    sender_address: str = Field(max_length=320)
    body_text: str | None = Field(default=None, max_length=2_000_000, repr=False)
    body_html: str | None = Field(default=None, max_length=2_000_000, repr=False)
    to_recipients: str = Field(default="", max_length=20000)
    cc_recipients: str = Field(default="", max_length=20000)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=100)
    source_is_read: StrictBool
    meeting_status: Literal["invited", "updated", "cancelled", "response"] | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    all_day: StrictBool = False
    location: str = Field(default="", max_length=1000)
    meeting_key: Hex64 | None = None
    is_recurring: StrictBool = False

    @field_validator("source_id", "meeting_key")
    @classmethod
    def normalize_hash(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @field_validator("source_modified_at", "received_at", "starts_at", "ends_at")
    @classmethod
    def normalize_time(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def schedule(self):
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("Both schedule endpoints are required")
        if self.starts_at is not None and self.ends_at < self.starts_at:
            raise ValueError("Schedule end precedes start")
        return self

    @model_validator(mode="after")
    def attachment_budget(self):
        if sum(len(attachment.decoded_data) for attachment in self.attachments) > MAX_ITEM_ATTACHMENT_BYTES:
            raise ValueError("Attachments exceed item byte limit")
        return self


class SyncRequest(StrictModel):
    protocol_version: Literal[1]
    mailbox_id: Hex64
    mailbox_label: str = Field(max_length=200)
    source_state: SourceState
    scan_complete: StrictBool = True
    skipped_items: int = Field(default=0, ge=0, le=5000, strict=True)
    items: list[ImportedItemInput] = Field(max_length=MAX_BATCH_ITEMS)

    @field_validator("protocol_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported protocol version")
        return value

    @field_validator("mailbox_id")
    @classmethod
    def normalize_mailbox(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def consistent_scan_status(self):
        if self.skipped_items and self.scan_complete:
            raise ValueError("A scan with skipped items cannot be complete")
        return self


class SyncRead(StrictModel):
    accepted: int
    created: int
    updated: int
    unchanged: int
    stale: int
    synced_at: AwareDatetime


class ImportedItemRead(ImportedItemInput):
    attachments: list[AttachmentRead] = Field(default_factory=list, max_length=100)
    id: UUID
    mailbox_label: str
    is_read: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def attachment_budget(self):
        # Public manifests carry sizes, never content or base64 data.
        if sum(attachment.size for attachment in self.attachments) > MAX_ITEM_ATTACHMENT_BYTES:
            raise ValueError("Attachments exceed item byte limit")
        return self


class ItemsRead(StrictModel):
    items: list[ImportedItemRead]
    total: int
    unread_count: int


class ItemReadRequest(StrictModel):
    is_read: StrictBool = True
