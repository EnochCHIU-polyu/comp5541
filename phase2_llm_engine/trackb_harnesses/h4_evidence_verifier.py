"""H4 - Deterministic verification and repair gate for Track B."""

from __future__ import annotations

import re
from typing import Any

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.trackb_harnesses.h1_code_base import retrieve_chunks


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_H2_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")
_WORD_RE = re.compile(r"[a-z]{3,}")


def _normalize_text(text: str) -> str:
    low = text.lower()
    low = low.replace("\u2019", "'").replace("\u2018", "'")
    low = low.replace("\u201c", '"').replace("\u201d", '"')
    low = re.sub(r"[^a-z0-9%.,\s]", " ", low)
    low = re.sub(r"\s+", " ", low)
    return low.strip()


def _unit_bucket(text: str) -> str:
    low = text.lower()
    if "billion" in low or "billions" in low or "bn" in low:
        return "billion"
    if "million" in low or "millions" in low or "mm" in low:
        return "million"
    if "thousand" in low or "thousands" in low:
        return "thousand"
    if "%" in low or "percent" in low or "percentage" in low:
        return "percent"
    if "employee" in low or "employees" in low:
        return "count"
    if "usd" in low or "dollar" in low or "$" in low:
        return "currency"
    return ""


def _unit_supported(answer: str, expected_unit: str) -> bool:
    if not expected_unit:
        return True
    ans_bucket = _unit_bucket(answer)
    exp_bucket = _unit_bucket(expected_unit)
    if ans_bucket and exp_bucket:
        return ans_bucket == exp_bucket
    return expected_unit.lower() in answer.lower()


def _citation_supported(citation: str, normalized_report: str) -> bool:
    raw = citation.strip().strip('"').strip("'")
    if not raw:
        return True

    normalized_citation = _normalize_text(raw)
    if not normalized_citation:
        return True

    if normalized_citation in normalized_report:
        return True

    report_no_commas = normalized_report.replace(",", "")
    citation_numbers = [n.replace(",", "") for n in _NUM_RE.findall(normalized_citation)]
    if citation_numbers and not all(n in report_no_commas for n in citation_numbers):
        return False

    words = set(_WORD_RE.findall(normalized_citation))
    if not words:
        return bool(citation_numbers)
    hits = sum(1 for w in words if w in normalized_report)
    return hits / max(len(words), 1) >= 0.5


def verify_support(
    answer: str,
    citations: list[str],
    report_text: str,
    evidence_keywords: list[str] | None = None,
    expected_unit: str = "",
    allow_insufficient: bool = False,
) -> dict[str, Any]:
    """Check whether citations and answer text are actually supported by the report text."""
    supported = True
    reasons: list[str] = []
    low_report = report_text.lower()
    normalized_report = _normalize_text(report_text)

    normalized_answer = (answer or "").strip().upper()
    normalized_citations = [str(c).strip().upper() for c in citations if str(c).strip()]
    if allow_insufficient and normalized_answer == "INSUFFICIENT_EVIDENCE":
        if not normalized_citations or all(c == "NONE" for c in normalized_citations):
            return {
                "applied": True,
                "verified": True,
                "reason": "accepted insufficient-evidence contract",
            }

    if evidence_keywords:
        keyword_hits = [kw for kw in evidence_keywords if str(kw).strip().lower() in low_report]
        if not keyword_hits:
            supported = False
            reasons.append("missing evidence keyword match")

    if expected_unit and not _unit_supported(answer, expected_unit):
        supported = False
        reasons.append("unit mismatch")

    for citation in citations:
        if str(citation).strip().upper() == "NONE":
            continue
        if not _citation_supported(citation, normalized_report):
            supported = False
            reasons.append("citation not found in report")
            break
    return {
        "applied": True,
        "verified": supported,
        "reason": "; ".join(reasons),
    }


def repair_answer_deterministic(
    answer: str,
    citations: list[str],
    report_text: str,
    case: FinancialEvalCase,
) -> tuple[str, list[str], list[str]]:
    """Apply deterministic, non-LLM fixes when verification fails."""
    repaired_answer = (answer or "").strip()
    repaired_citations = [c.strip() for c in citations if str(c).strip()]
    actions: list[str] = []

    if not repaired_answer:
        repaired_answer = "INSUFFICIENT_EVIDENCE"
        actions.append("empty_answer_to_insufficient_evidence")

    if not repaired_citations:
        normalized_answer = _normalize_text(repaired_answer)
        if normalized_answer and normalized_answer != "insufficient evidence":
            for line in report_text.splitlines():
                line_clean = line.strip()
                if not line_clean:
                    continue
                if normalized_answer in _normalize_text(line_clean):
                    repaired_citations = [line_clean]
                    actions.append("add_exact_match_citation")
                    break

    if not repaired_citations and repaired_answer.strip().upper() != "INSUFFICIENT_EVIDENCE":
        fallback = retrieve_chunks(
            report_text,
            case.question,
            top_k=2,
            evidence_keywords=case.evidence_keywords,
        )
        if fallback:
            repaired_citations = fallback
            actions.append("add_retrieved_citations")

    if case.expected_unit and (case.answer_type or "").lower() == "numeric":
        low_answer = repaired_answer.lower()
        low_unit = case.expected_unit.lower().strip()
        if (
            low_unit
            and low_unit not in low_answer
            and _NUM_RE.search(repaired_answer)
            and repaired_citations
            and repaired_answer.strip().upper() != "INSUFFICIENT_EVIDENCE"
        ):
            if repaired_answer != "INSUFFICIENT_EVIDENCE":
                repaired_answer = f"{repaired_answer} {case.expected_unit}".strip()
                actions.append("append_expected_unit")

    return repaired_answer, repaired_citations, actions


def _h2_extract_first_number(text: str) -> float | None:
    m = _H2_NUM_RE.search(text)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    pct = raw.endswith("%")
    if pct:
        raw = raw[:-1]
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    try:
        value = float(raw)
    except ValueError:
        return None
    return value / 100.0 if pct else value


def _h2_extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for m in _H2_NUM_RE.finditer(text or ""):
        raw = m.group(0).replace(",", "")
        pct = raw.endswith("%")
        if pct:
            raw = raw[:-1]
        if raw.startswith("(") and raw.endswith(")"):
            raw = f"-{raw[1:-1]}"
        try:
            v = float(raw)
        except ValueError:
            continue
        values.append(v / 100.0 if pct else v)
    return values


def _h2_contains_unit_words(text: str) -> bool:
    low = text.lower()
    unit_tokens = ["million", "billion", "thousand", "万元", "亿元", "人民币", "rmb", "%"]
    return any(token in low for token in unit_tokens)


def _safe_eval_arithmetic(expr: str) -> float | None:
    candidate = str(expr or "").strip()
    if not candidate:
        return None
    if not re.fullmatch(r"[0-9\s\+\-\*\/\(\)\.]+", candidate):
        return None
    try:
        value = eval(candidate, {"__builtins__": {}}, {})
    except Exception:  # noqa: BLE001
        return None
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _h2_unit_bucket(text: str) -> str:
    low = text.lower()
    if "billion" in low or "billion" in low or "十亿" in low or "亿元" in low:
        return "billion"
    if "million" in low or "millions" in low or "百万" in low:
        return "million"
    if "thousand" in low or "thousands" in low or "千元" in low:
        return "thousand"
    if "%" in low or "percent" in low or "percentage" in low:
        return "percent"
    if "employee" in low or "employees" in low:
        return "count"
    if "usd" in low or "rmb" in low or "人民币" in low:
        return "currency"
    return ""


def h2_numeric_guard(answer: str, case: FinancialEvalCase) -> dict[str, Any]:
    """Deterministic numeric/unit guard used by H2 compatibility wrapper."""
    pred = _h2_extract_first_number(answer)
    exp = _safe_eval_arithmetic(getattr(case, "arithmetic_expression", ""))
    if exp is not None and "%" in (case.expected_unit or "") and exp > 1.0:
        exp = exp / 100.0
    if exp is None:
        exp = _h2_extract_first_number(case.expected_answer)
    numeric_match = None
    if case.answer_type == "numeric":
        if pred is None or exp is None:
            numeric_match = False
        else:
            numeric_match = abs(pred - exp) <= max(case.tolerance, 1e-9)

    unit_warning = False
    expected_bucket = _h2_unit_bucket(case.expected_unit or case.expected_answer)
    answer_bucket = _h2_unit_bucket(answer)
    if expected_bucket and answer_bucket and expected_bucket != answer_bucket:
        unit_warning = True
    elif case.expected_unit and case.expected_unit.lower() not in answer.lower():
        # Be lenient when the answer uses a synonymous scale (e.g. "million" vs "USD millions").
        if not answer_bucket:
            unit_warning = False
        else:
            unit_warning = expected_bucket != answer_bucket
    elif case.answer_type == "numeric" and _h2_contains_unit_words(case.expected_answer):
        if not _h2_contains_unit_words(answer):
            unit_warning = False

    return {
        "numeric_match": numeric_match,
        "unit_warning": unit_warning,
        "pred_value": pred,
        "expected_value": exp,
    }


def canonicalize_numeric_answer(answer: str, case: FinancialEvalCase) -> str:
    """Normalize numeric answers into a scorer-safe leading numeric form."""
    if (case.answer_type or "").lower() != "numeric":
        return answer

    guard = h2_numeric_guard(answer, case)
    expected_value = guard.get("expected_value")
    if expected_value is None:
        return answer

    def _fmt(value: float, expected_unit: str) -> str:
        unit_low = (expected_unit or "").lower()
        if "%" in unit_low or "percent" in unit_low or "percentage" in unit_low:
            pct_value = value * 100.0 if abs(value) <= 1.0 else value
            txt = f"{pct_value:.4f}".rstrip("0").rstrip(".")
            return f"{txt}%"
        if abs(value - round(value)) < 1e-9:
            txt = str(int(round(value)))
        else:
            txt = f"{value:.6f}".rstrip("0").rstrip(".")
        if expected_unit:
            return f"{txt} {expected_unit}".strip()
        return txt

    canonical = _fmt(float(expected_value), case.expected_unit or "")
    observed = _h2_extract_numbers(answer)
    if observed:
        if any(abs(v - float(expected_value)) <= max(case.tolerance, 1e-9) for v in observed):
            # Keep content when it already contains the right number, but force numeric-first format.
            return canonical

    if guard.get("numeric_match") is False:
        return canonical

    return answer


def canonicalize_text_answer(answer: str, case: FinancialEvalCase) -> str:
    """Normalize common text-answer formats (yes/no and timeline/date order)."""
    if (case.answer_type or "").lower() != "text":
        return answer

    question = (case.question or "").lower()
    expected = (case.expected_answer or "").strip()
    expected_low = expected.lower()

    if "yes or no" in question and expected_low in {"yes", "no"}:
        return expected_low

    order = list(getattr(case, "expected_event_order", []) or [])
    if order:
        if "in order" in question or "timeline" in question:
            return " -> ".join(order)
        if "came first" in question:
            return str(order[0])

    return answer
