from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Harness2AnalysisProfile = Literal["baseline", "h1_all"]
Harness2HistorySort = Literal["created_at", "run_id", "symbol"]
Harness2SortOrder = Literal["asc", "desc"]


class Harness2BuildRequest(BaseModel):
    seed_url: str = Field(..., min_length=8)
    symbol: str = Field(..., min_length=1, description="Ticker symbol used for trend evaluation")
    max_reports: int = Field(default=5, ge=1, le=20)
    horizon_days: int = Field(default=30, ge=1, le=365)
    analysis_profile: Harness2AnalysisProfile = "baseline"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.0


class Harness2UploadBuildRequest(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker symbol used for trend evaluation")
    max_reports: int = Field(default=5, ge=1, le=20)
    horizon_days: int = Field(default=30, ge=1, le=365)
    analysis_profile: Harness2AnalysisProfile = "baseline"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.0


class Harness2ReportItem(BaseModel):
    title: str
    source_url: str
    pdf_path: str
    markdown_path: str
    internal_report_path: str
    report_date: Optional[str] = None
    predicted_trend: str = "flat"
    actual_trend: str = "unknown"
    trend_correct: Optional[bool] = None
    price_start: Optional[float] = None
    price_end: Optional[float] = None
    summary: str = ""
    overview: str = ""
    further_direction: str = ""
    rating: float = 0.0


class Harness2TrendPoint(BaseModel):
    date: str
    close: float


class Harness2Evaluation(BaseModel):
    root_link_ok: bool
    pdf_download_rate: float
    markdown_conversion_rate: float
    internal_report_rate: float
    trend_eval_coverage: float
    trend_direction_accuracy: float
    checklist: Dict[str, bool] = Field(default_factory=dict)


class Harness2BuildResponse(BaseModel):
    run_id: str
    created_at: datetime
    seed_url: str
    resolved_root_link: str
    symbol: str
    output_dir: str
    reports: List[Harness2ReportItem] = Field(default_factory=list)
    trend_points: List[Harness2TrendPoint] = Field(default_factory=list)
    evaluation: Harness2Evaluation
    notes: List[str] = Field(default_factory=list)
    download_script_path: str = ""
    download_script_code: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Harness2HistoryResponse(BaseModel):
    runs: List[Harness2BuildResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    q: Optional[str] = None
    symbol: Optional[str] = None
    sort: Harness2HistorySort = "created_at"
    order: Harness2SortOrder = "desc"
