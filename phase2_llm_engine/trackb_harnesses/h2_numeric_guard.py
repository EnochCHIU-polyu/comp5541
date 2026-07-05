"""H2 - Numeric and unit guard for Track B financial report questions."""

from __future__ import annotations

import re
from typing import Any

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase

_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def build_h2_prompt(
    question: str,
    context: str,
    hint_block: str = "",
) -> list[dict[str, str]]:
    """Build the H2 generation prompt with strict output and anti-hallucination rules."""
    return [
        {
            "role": "system",
            "content": (
                "You are a financial QA assistant for earnings and filings. "
                "Use only the provided Context. Do not use outside knowledge. "
                "If evidence is missing, conflicting, or too weak, do not guess. "
                "Keep the answer concise and preserve exact numeric scale/unit from the evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                f"{hint_block + '\n\n' if hint_block else ''}"
                "Context:\n"
                f"{context}\n\n"
                "Output format (strict):\n"
                "ANSWER: <short answer, <= 25 words>\n"
                "CITATIONS: <semicolon-separated direct snippets from Context>\n\n"
                "Hard constraints:\n"
                "- Do not invent numbers, entities, dates, or units.\n"
                "- Prefer exact table/disclosure values over rounded headline statements.\n"
                "- Every material claim in ANSWER must be grounded by CITATIONS text.\n"
                "- If evidence is insufficient, answer exactly:\n"
                "  ANSWER: INSUFFICIENT_EVIDENCE\n"
                "  CITATIONS: NONE"
            ),
        },
    ]


def _extract_first_number(text: str) -> float | None:
    m = _NUM_RE.search(text)
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


def _contains_unit_words(text: str) -> bool:
    low = text.lower()
    unit_tokens = ["million", "billion", "thousand", "万元", "亿元", "人民币", "rmb", "%"]
    return any(token in low for token in unit_tokens)


def _unit_bucket(text: str) -> str:
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


def _keyword_score(line: str, keywords: list[str] | None, question: str) -> int:
    score = 0
    low = line.lower()
    if keywords:
        for kw in keywords:
            token = str(kw).strip().lower()
            if token and token in low:
                score += 4
    q_words = {w for w in re.findall(r"[A-Za-z0-9%]+", question.lower()) if len(w) > 2}
    for word in q_words:
        if word in low:
            score += 1
    if _NUM_RE.search(line):
        score += 2
    return score


def build_numeric_hint(report_text: str, case: FinancialEvalCase, top_k: int = 3) -> str:
    """Build a short deterministic hint block with likely numeric evidence lines."""
    lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    if not lines:
        return ""
    ranked = sorted(
        lines,
        key=lambda line: _keyword_score(line, case.evidence_keywords, case.question),
        reverse=True,
    )
    picked = [line for line in ranked if _keyword_score(line, case.evidence_keywords, case.question) > 0][:top_k]
    if not picked:
        picked = ranked[:top_k]
    if not picked:
        return ""

    return (
        "Numeric evidence hints:\n"
        + "\n".join(f"- {line}" for line in picked)
        + (f"\nTarget unit: {case.expected_unit}" if case.expected_unit else "")
        + "\nInstruction: preserve the report's exact scale; do not round a table value into a headline approximation."
    )


def numeric_guard(answer: str, case: FinancialEvalCase) -> dict[str, Any]:
    """Return a deterministic numeric/unit sanity check for a case."""
    pred = _extract_first_number(answer)
    exp = _extract_first_number(case.expected_answer)
    numeric_match = None
    if case.answer_type == "numeric":
        if pred is None or exp is None:
            numeric_match = False
        else:
            numeric_match = abs(pred - exp) <= max(case.tolerance, 1e-9)

    unit_warning = False
    expected_bucket = _unit_bucket(case.expected_unit or case.expected_answer)
    answer_bucket = _unit_bucket(answer)
    if expected_bucket and answer_bucket and expected_bucket != answer_bucket:
        unit_warning = True
    elif case.expected_unit and case.expected_unit.lower() not in answer.lower():
        # Be lenient when the answer uses a synonymous scale (e.g. "million" vs "USD millions").
        if not answer_bucket:
            unit_warning = False
        else:
            unit_warning = expected_bucket != answer_bucket
    elif case.answer_type == "numeric" and _contains_unit_words(case.expected_answer):
        if not _contains_unit_words(answer):
            unit_warning = False

    return {
        "numeric_match": numeric_match,
        "unit_warning": unit_warning,
        "pred_value": pred,
        "expected_value": exp,
    }
