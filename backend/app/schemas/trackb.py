from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TrackBProfile = Literal[
    "baseline",
    "h1",
    "h2",
    "h3",
    "h4",
    "all",
    "all_minus_h1",
    "all_minus_h2",
    "all_minus_h3",
    "all_minus_h4",
]

TrackBStage = Literal["queued", "running", "scoring", "completed", "failed"]

TrackBEventType = Literal[
    "trackb_started",
    "trackb_profile_started",
    "trackb_case_progress",
    "trackb_profile_completed",
    "trackb_scoring_done",
    "trackb_completed",
    "trackb_failed",
    "ping",
]


class TrackBH3LayerConfig(BaseModel):
    model: str = Field(min_length=1, max_length=100)
    batch_size: int = Field(default=8, ge=1, le=64)


class TrackBRunCreateRequest(BaseModel):
    report_path: str = "data/report.md"
    cases_path: str = "data/trackb_eval_cases.jsonl"
    model: str = "DeepSeek-V3.2"
    temperature: float = 0.0
    max_cases: int = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1)
    profiles: List[TrackBProfile] = Field(default_factory=lambda: ["baseline"])
    split_harnesses: bool = True
    h1_components: List["TrackBH1ComponentConfig"] = Field(default_factory=list)
    h3_layers: List["TrackBH3LayerConfig"] = Field(default_factory=list)


class TrackBUploadRunRequest(BaseModel):
    model: str = "DeepSeek-V3.2"
    temperature: float = 0.0
    max_cases: int = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1)
    profiles: List[TrackBProfile] = Field(default_factory=lambda: ["baseline"])
    split_harnesses: bool = True
    h1_components: List["TrackBH1ComponentConfig"] = Field(default_factory=list)
    h3_layers: List["TrackBH3LayerConfig"] = Field(default_factory=list)


class TrackBH1ComponentConfig(BaseModel):
    name: str
    enabled: bool = True
    top_k: int = Field(default=6, ge=1, le=20)
    evidence_keywords: List[str] = Field(default_factory=list)
    note: str = ""


class TrackBH1CodeSection(BaseModel):
    name: str
    kind: Literal["function", "class"]
    start_line: int
    end_line: int
    source: str


class TrackBH1ComponentsResponse(BaseModel):
    source_path: str
    full_source: str
    sections: List[TrackBH1CodeSection] = Field(default_factory=list)


class TrackBH1SourceSaveRequest(BaseModel):
    full_source: str


class TrackBH1SourceSaveResponse(BaseModel):
    source_path: str
    bytes_written: int


class TrackBH2SourceResponse(BaseModel):
    source_path: str
    full_source: str


class TrackBH2SourceSaveRequest(BaseModel):
    full_source: str


class TrackBH2SourceSaveResponse(BaseModel):
    source_path: str
    bytes_written: int
    runtime_refreshed: bool


class TrackBH4SourceResponse(BaseModel):
    source_path: str
    full_source: str


class TrackBH4SourceSaveRequest(BaseModel):
    full_source: str


class TrackBH4SourceSaveResponse(BaseModel):
    source_path: str
    bytes_written: int
    runtime_refreshed: bool


class TrackBRunCreateResponse(BaseModel):
    run_id: str
    status: str
    created_at: datetime
    profiles: List[str] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)


class TrackBProfileProgress(BaseModel):
    profile: str
    status: TrackBStage
    cases_total: int = 0
    cases_completed: int = 0


class TrackBRunStatusResponse(BaseModel):
    run_id: str
    status: TrackBStage
    stage: TrackBStage
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    report_path: str
    cases_path: str
    model: str
    temperature: float
    max_cases: int
    batch_size: int
    profiles: List[str] = Field(default_factory=list)
    progress: List[TrackBProfileProgress] = Field(default_factory=list)
    error: Optional[str] = None


class TrackBEvent(BaseModel):
    run_id: str
    event: TrackBEventType
    stage: TrackBStage
    seq: int
    ts: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


class TrackBArtifactsResponse(BaseModel):
    run_id: str
    output_dir: str
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    profiles: List[Dict[str, Any]] = Field(default_factory=list)


class TrackBMetricsResponse(BaseModel):
    run_id: str
    metrics_by_profile: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class TrackBHistoryResponse(BaseModel):
    runs: List[Dict[str, Any]] = Field(default_factory=list)


class TrackBComparisonRequest(BaseModel):
    run_id: str
    baseline_profile: TrackBProfile = "baseline"


class TrackBComparisonResponse(BaseModel):
    run_id: str
    baseline_profile: TrackBProfile
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    loo_impact: List[Dict[str, Any]] = Field(default_factory=list)


class TrackBReproduceResponse(BaseModel):
    run_id: str
    commands: Dict[str, str] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class TrackBChatSessionCreateRequest(BaseModel):
    model: str = "DeepSeek-V3.2"
    temperature: float = 0.0
    h1_components: List["TrackBH1ComponentConfig"] = Field(default_factory=list)
    h3_layers: List["TrackBH3LayerConfig"] = Field(default_factory=list)


class TrackBChatSessionCreateResponse(BaseModel):
    session_id: str
    status: Literal["ready"] = "ready"
    created_at: datetime
    report_path: str
    report_name: str
    model: str
    temperature: float


class TrackBChatProfileAnswer(BaseModel):
    profile: str
    answer: str
    citations: List[str] = Field(default_factory=list)
    evidence_lines: List[int] = Field(default_factory=list)
    primary_evidence_line: Optional[int] = None
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = 0.0


class TrackBChatTurn(BaseModel):
    turn_id: str
    question: str
    created_at: datetime
    answers: List[TrackBChatProfileAnswer] = Field(default_factory=list)


class TrackBChatAskRequest(BaseModel):
    question: str = Field(min_length=1)
    harnesses: List[Literal["baseline", "all", "h1", "h2", "h3", "h4"]] = Field(
        default_factory=lambda: ["all"]
    )
    model: Optional[str] = None
    temperature: Optional[float] = None
    h1_components: Optional[List["TrackBH1ComponentConfig"]] = None
    h3_layers: Optional[List["TrackBH3LayerConfig"]] = None


class TrackBChatAskResponse(BaseModel):
    session_id: str
    turn: TrackBChatTurn


class TrackBChatReportResponse(BaseModel):
    session_id: str
    report_path: str
    report_name: str
    line_count: int
    content: str


class TrackBChatSessionResponse(BaseModel):
    session_id: str
    created_at: datetime
    report_path: str
    report_name: str
    model: str
    temperature: float
    turns: List[TrackBChatTurn] = Field(default_factory=list)
