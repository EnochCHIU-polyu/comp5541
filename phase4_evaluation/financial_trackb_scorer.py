"""
Phase 4 - Evaluation: Track B scorer for financial report workflows.

Scores baseline and harness outputs with:
- text exact/contains checks
- numeric tolerance checks
- citation presence checks
- error-taxonomy signals (E1-E5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase


@dataclass
class CaseScore:
    case_id: str
    correct: bool
    numeric_correct: bool | None
    citation_present: bool
    error_codes: list[str]


_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def _to_float(num_text: str) -> float | None:
    raw = num_text.strip().replace(",", "")
    pct = raw.endswith("%")
    if pct:
        raw = raw[:-1]
    if not raw:
        return None
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    try:
        v = float(raw)
    except ValueError:
        return None
    return v / 100.0 if pct else v


def _extract_first_number(text: str) -> float | None:
    m = _NUM_RE.search(text)
    if not m:
        return None
    return _to_float(m.group(0))


def score_case(case: FinancialEvalCase, result: dict[str, Any]) -> CaseScore:
    answer = str(result.get("answer", "")).strip()
    low_answer = answer.lower()
    expected = case.expected_answer.strip()
    low_expected = expected.lower()

    citation_present = len(result.get("citations", []) or []) > 0

    numeric_correct: bool | None = None
    if case.answer_type == "numeric":
        pred = _extract_first_number(answer)
        exp = _to_float(expected)
        if pred is not None and exp is not None:
            numeric_correct = abs(pred - exp) <= max(case.tolerance, 1e-9)
        else:
            numeric_correct = False

    if case.answer_type == "numeric":
        correct = bool(numeric_correct)
    else:
        correct = low_expected in low_answer

    error_codes: list[str] = []

    retrieved_chunks = int((result.get("diagnostics", {}) or {}).get("retrieved_chunks", 0) or 0)
    if retrieved_chunks <= 1:
        error_codes.append("E1")

    num_diag = ((result.get("diagnostics", {}) or {}).get("numeric", {}) or {})
    if num_diag.get("unit_warning"):
        error_codes.append("E2")
    if num_diag.get("numeric_match") is False:
        error_codes.append("E3")

    chrono_ok = (result.get("diagnostics", {}) or {}).get("chronology_ok", None)
    if chrono_ok is False:
        error_codes.append("E4")

    verify = (result.get("diagnostics", {}) or {}).get("verification", {}) or {}
    if verify.get("applied") and verify.get("verified") is False:
        error_codes.append("E5")

    return CaseScore(
        case_id=case.case_id,
        correct=correct,
        numeric_correct=numeric_correct,
        citation_present=citation_present,
        error_codes=error_codes,
    )


def aggregate_scores(scored_cases: list[CaseScore]) -> dict[str, Any]:
    total = len(scored_cases)
    correct = sum(1 for c in scored_cases if c.correct)
    citation_rate = sum(1 for c in scored_cases if c.citation_present) / total if total else 0.0

    numeric_cases = [c for c in scored_cases if c.numeric_correct is not None]
    numeric_acc = (
        sum(1 for c in numeric_cases if c.numeric_correct) / len(numeric_cases)
        if numeric_cases
        else 0.0
    )

    error_counts: dict[str, int] = {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "E5": 0}
    for case in scored_cases:
        for code in case.error_codes:
            error_counts[code] = error_counts.get(code, 0) + 1

    return {
        "total_cases": total,
        "overall_accuracy": round(correct / total, 4) if total else 0.0,
        "numeric_accuracy": round(numeric_acc, 4),
        "citation_rate": round(citation_rate, 4),
        "error_counts": error_counts,
    }
