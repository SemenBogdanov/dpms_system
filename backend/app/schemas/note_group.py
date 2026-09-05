"""Bounded owner-only organization and explicit share contracts."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteGroupCreate(StrictInput):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Введите название группы")
        return value.strip()


class NoteGroupUpdate(StrictInput):
    base_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    collapsed: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        fields = self.model_fields_set - {"base_revision"}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError("Укажите изменение группы")
        if self.title is not None:
            self.title = NoteGroupCreate(title=self.title).title
        return self


class NoteGroupRead(BaseModel):
    id: UUID
    title: str
    position: int
    collapsed: bool
    archived: bool
    revision: int
    note_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class GroupRevision(StrictInput):
    id: UUID
    base_revision: int = Field(ge=1)


class NoteGroupOrder(StrictInput):
    groups: list[GroupRevision] = Field(min_length=1, max_length=500)

    @field_validator("groups")
    @classmethod
    def unique(cls, groups):
        if len({group.id for group in groups}) != len(groups):
            raise ValueError("Повторяющаяся группа")
        return groups


class NoteBulkMove(StrictInput):
    note_ids: list[UUID] = Field(min_length=1, max_length=100)
    group_id: UUID | None = None

    @field_validator("note_ids")
    @classmethod
    def unique(cls, ids):
        if len(set(ids)) != len(ids):
            raise ValueError("Повторяющаяся заметка")
        return ids


class NoteLinkCreate(StrictInput):
    target_type: Literal["entity", "personal_task"]
    target_id: UUID


class NoteSharePreviewCreate(StrictInput):
    note_ids: list[UUID] = Field(default_factory=list, max_length=100)
    group_id: UUID | None = None
    recipient_ids: list[UUID] = Field(min_length=1, max_length=20)
    project_id: UUID | None = None

    @model_validator(mode="after")
    def selection(self):
        if bool(self.note_ids) == bool(self.group_id):
            raise ValueError("Выберите заметки или одну группу")
        for ids in (self.note_ids, self.recipient_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("Повторяющиеся элементы")
        return self


class NoteSharePreviewRead(BaseModel):
    id: UUID
    expires_at: datetime
    notes: list[dict]
    recipients: list[dict]
    existing_share_count: int
    new_share_count: int
    policy: Literal["accepted_contacts"] = "accepted_contacts"
