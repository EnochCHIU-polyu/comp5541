"""H4 - Skeptical verifier harness for Track B financial report questions."""

from __future__ import annotations

import re
from typing import Any


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
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
) -> dict[str, Any]:
    """Check whether citations and answer text are actually supported by the report text."""
    supported = True
    reasons: list[str] = []
    low_report = report_text.lower()
    normalized_report = _normalize_text(report_text)

    if evidence_keywords:
        keyword_hits = [kw for kw in evidence_keywords if str(kw).strip().lower() in low_report]
        if not keyword_hits:
            supported = False
            reasons.append("missing evidence keyword match")

    if expected_unit and not _unit_supported(answer, expected_unit):
        supported = False
        reasons.append("unit mismatch")

    for citation in citations:
        if not _citation_supported(citation, normalized_report):
            supported = False
            reasons.append("citation not found in report")
            break
    return {
        "applied": True,
        "verified": supported,
        "reason": "; ".join(reasons),
    }
