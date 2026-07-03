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


class TrackBRunCreateRequest(BaseModel):
    report_path: str = "data/report.md"
    cases_path: str = "data/trackb_eval_cases.jsonl"
    model: str = "deepseek-v3.2"
    temperature: float = 0.0
    max_cases: int = Field(default=0, ge=0)
    batch_size: int = Field(default=0, ge=0)
    profiles: List[TrackBProfile] = Field(default_factory=lambda: ["baseline"])


class TrackBUploadRunRequest(BaseModel):
    model: str = "deepseek-v3.2"
    temperature: float = 0.0
    max_cases: int = Field(default=0, ge=0)
    batch_size: int = Field(default=0, ge=0)
    profiles: List[TrackBProfile] = Field(default_factory=lambda: ["baseline"])


class TrackBRunCreateResponse(BaseModel):
    run_id: str
    status: str
    created_at: datetime
    profiles: List[TrackBProfile] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)


class TrackBProfileProgress(BaseModel):
    profile: TrackBProfile
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
    profiles: List[TrackBProfile] = Field(default_factory=list)
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
