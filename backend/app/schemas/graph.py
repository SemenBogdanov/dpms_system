"""Strict, bounded contracts for private graph documents."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CLIENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GraphViewport(StrictInput):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    scale: float = Field(ge=0.24, le=2.6, allow_inf_nan=False)


class GraphPosition(StrictInput):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class GraphNode(StrictInput):
    id: str = Field(min_length=1, max_length=100)
    type: Literal[
        "sticker",
        "list",
        "atom",
        "message",
        "personal",
        "queue",
        "note",
        "reminder",
        "tracker",
        "custom",
    ]
    title: str = Field(min_length=1, max_length=180)
    customTypeLabel: str = Field(default="", max_length=60)
    sourceRef: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=2000)
    shape: Literal["square", "rounded", "circle"]
    radius: float = Field(ge=0, le=36, allow_inf_nan=False)
    scale: float = Field(ge=0.5, le=2, allow_inf_nan=False)
    autoSize: bool = True
    width: float = Field(default=224, ge=96, le=1200, allow_inf_nan=False)
    height: float = Field(default=108, ge=64, le=900, allow_inf_nan=False)
    items: list[str] = Field(default_factory=list, max_length=200)
    pinned: bool = False
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)

    @field_validator("items")
    @classmethod
    def valid_items(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 180 for item in value):
            raise ValueError("Элементы списка должны содержать от 1 до 180 символов")
        return value


class GraphEdge(StrictInput):
    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    sourcePort: str | None = Field(default=None, pattern=r"^[nesw]:[0-4]$")
    targetPort: str | None = Field(default=None, pattern=r"^[nesw]:[0-4]$")
    label: str = Field(min_length=1, max_length=80)
    routing: Literal["curve", "orthogonal", "straight"] = "curve"
    points: list[GraphPosition] = Field(default_factory=list, max_length=20)


class GraphGroup(StrictInput):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=80)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    nodeIds: list[str] = Field(min_length=1, max_length=500)
    collapsed: bool = False

    @field_validator("nodeIds")
    @classmethod
    def unique_node_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Группа содержит повторяющиеся элементы")
        return value


class GraphView(StrictInput):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=60)
    layout: Literal["radial", "hierarchy", "compact"]
    positions: dict[str, GraphPosition] = Field(max_length=1500)
    viewport: GraphViewport
    focusNodeId: str | None = Field(default=None, max_length=100)
    focusDepth: Literal[0, 1, 2] = 0
    connectionLensEnabled: bool = False


class GraphAuditEntry(StrictInput):
    id: str = Field(min_length=1, max_length=160)
    at: datetime
    action: str = Field(min_length=1, max_length=240)


class GraphPayload(StrictInput):
    version: Literal[2, 3]
    id: str = Field(pattern=CLIENT_ID_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    createdAt: datetime
    updatedAt: datetime
    viewport: GraphViewport
    nodes: list[GraphNode] = Field(max_length=1500)
    edges: list[GraphEdge] = Field(max_length=3000)
    groups: list[GraphGroup] = Field(max_length=300)
    views: list[GraphView] = Field(min_length=1, max_length=30)
    activeViewId: str = Field(min_length=1, max_length=100)
    audit: list[GraphAuditEntry] = Field(max_length=200)

    @model_validator(mode="after")
    def graph_integrity(self):
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Граф содержит повторяющиеся ID элементов")
        node_id_set = set(node_ids)

        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Граф содержит повторяющиеся ID связей")
        edge_pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source == edge.target or edge.source not in node_id_set or edge.target not in node_id_set:
                raise ValueError("Связь ссылается на отсутствующий элемент")
            pair = (edge.source, edge.target)
            if pair in edge_pairs:
                raise ValueError("Граф содержит повторяющиеся связи")
            edge_pairs.add(pair)

        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Граф содержит повторяющиеся ID групп")
        claimed: set[str] = set()
        for group in self.groups:
            group_nodes = set(group.nodeIds)
            if not group_nodes.issubset(node_id_set):
                raise ValueError("Группа ссылается на отсутствующий элемент")
            if claimed.intersection(group_nodes):
                raise ValueError("Элемент не может входить в несколько групп")
            claimed.update(group_nodes)

        view_ids = [view.id for view in self.views]
        if len(view_ids) != len(set(view_ids)) or self.activeViewId not in set(view_ids):
            raise ValueError("Активный вид графа не найден")
        for view in self.views:
            if not set(view.positions).issubset(node_id_set):
                raise ValueError("Вид содержит позицию отсутствующего элемента")
            if view.focusNodeId is not None and view.focusNodeId not in node_id_set:
                raise ValueError("Фокус вида ссылается на отсутствующий элемент")
        return self


class GraphDocumentWrite(StrictInput):
    base_revision: int | None = Field(default=None, ge=1)
    payload: GraphPayload


class GraphMetadataRead(BaseModel):
    client_id: str
    title: str
    revision: int
    payload_bytes: int
    node_count: int
    edge_count: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GraphDocumentRead(GraphMetadataRead):
    id: UUID
    payload: GraphPayload


class GraphDeleteRead(BaseModel):
    deleted: bool = True
    client_id: str
