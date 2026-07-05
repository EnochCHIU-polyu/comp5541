"""Shared state and diagnostics types for Track B harness workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase


class NumericDiag(TypedDict, total=False):
    numeric_match: bool | None
    unit_warning: bool
    pred_value: float | None
    expected_value: float | None


class H3Diag(TypedDict, total=False):
    judge_pass: bool
    judge_reason: str
    revise_applied: bool
    chronology_ok: bool | None


class VerifyDiag(TypedDict, total=False):
    applied: bool
    verified: bool | None
    reason: str
    repair_actions: list[str]
    reverified: bool


@dataclass(slots=True)
class HarnessState:
    query: str
    case: FinancialEvalCase | None = None
    report_text: str = ""
    context: str = ""
    retrieved_chunks: list[str] = field(default_factory=list)
    prompt_messages: list[dict[str, str]] = field(default_factory=list)
    raw_llm: str = ""
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    numeric_diag: NumericDiag = field(default_factory=dict)
    h3_diag: H3Diag = field(default_factory=dict)
    verify_diag: VerifyDiag = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)
    stage_trace: list[str] = field(default_factory=list)
    status: Literal["ok", "insufficient_evidence", "failed"] = "ok"


@dataclass(slots=True)
class WorkflowRuntime:
    report_text: str
    cases_by_question: dict[str, FinancialEvalCase]
