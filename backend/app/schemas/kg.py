"""Pydantic schemas for the Knowledge Graph (KG) learning system."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Job / SSE event types
# ---------------------------------------------------------------------------

KGStage = Literal["queued", "chunking", "extracting", "indexing", "completed", "failed"]
KGEventType = Literal["kg_started", "kg_progress", "kg_completed", "kg_failed", "ping"]


class KGEvent(BaseModel):
    graph_id: str
    event: KGEventType
    stage: KGStage
    seq: int
    ts: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Graph data models
# ---------------------------------------------------------------------------


class SourceRef(BaseModel):
    """One evidence span that supports a node or edge."""

    chunk_id: str
    page: int = 0
    span: str = ""  # short quoted text from the chunk
    text: str = ""  # full chunk text (for RAG retrieval)


class KGNode(BaseModel):
    id: str
    label: str
    node_type: str = "concept"
    background_intro: str = ""
    source_refs: List[SourceRef] = Field(default_factory=list)


class KGEdge(BaseModel):
    source_id: str
    target_id: str
    relation: str = "related_to"
    weight: float = 1.0


class KGGraph(BaseModel):
    graph_id: str
    title: str = ""
    nodes: List[KGNode] = Field(default_factory=list)
    edges: List[KGEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class KGExtractResponse(BaseModel):
    graph_id: str
    status: str


class KGGraphResponse(BaseModel):
    graph_id: str
    title: str
    nodes: List[KGNode]
    edges: List[KGEdge]
    created_at: datetime


class KGNodeDetailResponse(BaseModel):
    node_id: str
    label: str
    background_intro: str
    explanation: str
    evidence: List[Dict[str, Any]] = Field(default_factory=list)


class KGSnapshot(BaseModel):
    graph_id: str
    stage: KGStage
    status: str
    events: List[KGEvent] = Field(default_factory=list)
