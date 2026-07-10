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


_NUM_RE = re.compile(r"\(?[-+]?\d[\d,]*(?:\.\d+)?%?\)?")
_WORD_RE = re.compile(r"[a-z0-9]{4,}")
_ARITH_ALLOWED_RE = re.compile(r"[0-9\s\+\-\*\/\(\)\.]+")
_TEXT_STOPWORDS = {
    "that",
    "this",
    "with",
    "from",
    "were",
    "was",
    "have",
    "been",
    "which",
    "because",
    "report",
    "release",
    "quarter",
    "increase",
    "increased",
    "decrease",
    "decreased",
    "higher",
    "lower",
    "only",
    "says",
    "said",
    "about",
}


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


def _extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        v = _to_float(m.group(0))
        if v is not None:
            values.append(v)
    return values


def _eval_arithmetic_parts(expr: str) -> list[float]:
    values: list[float] = []
    for part in str(expr or "").split(";"):
        candidate = part.strip()
        if not candidate:
            continue
        if not _ARITH_ALLOWED_RE.fullmatch(candidate):
            continue
        try:
            value = eval(candidate, {"__builtins__": {}}, {})
        except Exception:  # noqa: BLE001
            continue
        try:
            values.append(float(value))
        except Exception:  # noqa: BLE001
            continue
    return values


def _numeric_close(pred: float, exp: float, tolerance: float) -> bool:
    tol = max(float(tolerance or 0.0), 1e-9)
    if abs(pred - exp) <= tol:
        return True
    # Handle percent scale ambiguity (0.2179 vs 21.79).
    if abs(pred * 100.0 - exp) <= tol:
        return True
    if abs(pred - exp * 100.0) <= tol:
        return True
    return False


def _dedupe_numbers(values: list[float]) -> list[float]:
    deduped: list[float] = []
    for v in values:
        if any(abs(v - x) < 1e-12 for x in deduped):
            continue
        deduped.append(v)
    return deduped


def _text_keyword_overlap(pred_text: str, expected_text: str) -> float:
    pred_words = set(_WORD_RE.findall(pred_text.lower()))
    exp_words = [
        w for w in _WORD_RE.findall(expected_text.lower())
        if w not in _TEXT_STOPWORDS and not w.isdigit()
    ]
    exp_set = set(exp_words)
    if not exp_set:
        return 0.0
    hits = sum(1 for w in exp_set if w in pred_words)
    return hits / max(len(exp_set), 1)


def score_case(case: FinancialEvalCase, result: dict[str, Any]) -> CaseScore:
    answer = str(result.get("answer", "")).strip()
    low_answer = answer.lower()
    expected = case.expected_answer.strip()
    low_expected = expected.lower()

    citation_present = len(result.get("citations", []) or []) > 0

    numeric_correct: bool | None = None
    if case.answer_type == "numeric":
        pred_values = _extract_numbers(answer)
        expected_values = _eval_arithmetic_parts(case.arithmetic_expression)
        expected_values.extend(_extract_numbers(expected))
        expected_values = _dedupe_numbers(expected_values)

        if pred_values and expected_values:
            numeric_correct = any(
                _numeric_close(pred, exp, case.tolerance)
                for pred in pred_values
                for exp in expected_values
            )
        else:
            numeric_correct = False

    if case.answer_type == "numeric":
        correct = bool(numeric_correct)
    else:
        if low_expected in {"yes", "no"}:
            correct = low_answer.startswith(low_expected)
        elif case.expected_event_order:
            positions: list[int] = []
            correct = True
            for token in case.expected_event_order:
                idx = low_answer.find(str(token).lower())
                if idx < 0:
                    correct = False
                    break
                positions.append(idx)
            if correct:
                correct = positions == sorted(positions)
        elif "not disclosed" in low_expected or "not separately disclosed" in low_expected:
            correct = ("not disclosed" in low_answer) or ("not separately disclosed" in low_answer)
        else:
            overlap = _text_keyword_overlap(low_answer, low_expected)
            correct = low_expected in low_answer or overlap >= 0.45

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
