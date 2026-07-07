"""H2 - prompt building for financial QA."""

from __future__ import annotations

import re

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
                "You are a financial QA assistant for earnings releases, SEC filings, and investor disclosures. "
                "Answer using only the provided Context and quoted snippets from it. "
                "Do not use prior knowledge or unsupported assumptions. "
                "Ground every material claim in direct evidence, preserve exact units/scales/signs/time periods as written, and stay concise."
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
                "ANSWER: <short answer, <= 45 words>\n"
                "CITATIONS: <semicolon-separated direct verbatim snippets from Context>\n\n"
                "Hard constraints:\n"
                "- Use only facts explicitly present in Context.\n"
                "- Do not invent numbers, entities, dates, percentages, currencies, units, periods, or qualifiers.\n"
                "- Preserve exact numeric value and representation from Context (including commas, decimals, %, $, bps, million/billion, and sign).\n"
                "- Never rescale or normalize values (e.g., do not convert million<->billion) unless Context explicitly states the converted value.\n"
                "- Resolve scale ambiguities conservatively; if unclear, return INSUFFICIENT_EVIDENCE.\n"
                "- Prefer exact table/disclosure values over rounded narrative summaries when both exist.\n"
                "- Arithmetic is allowed only when all operands are explicitly present in Context (for ratios, differences, growth, and unit conversion).\n"
                "- When conversion is requested (million/billion/thousand/percent), output the converted value in the requested unit and cite source values.\n"
                "- For yes/no questions, ANSWER must begin with Yes or No, followed by <= 20 words of support.\n"
                "- Every material claim in ANSWER must be directly supported by the quoted CITATIONS snippets.\n"
                "- CITATIONS must be verbatim excerpts copied from Context; do not paraphrase in CITATIONS.\n"
                "- If multiple snippets support one claim, include multiple snippets separated by semicolons.\n"
                "- If evidence is insufficient, answer exactly:\n"
                "  ANSWER: INSUFFICIENT_EVIDENCE\n"
                "  CITATIONS: NONE"
            ),
        },
    ]


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

    yn_hint = ""
    if case.answer_type == "text" and "yes or no" in case.question.lower():
        yn_hint = "\nFor yes/no questions, answer exactly yes or no and support with direct quote."

    arithmetic_hint = ""
    if (getattr(case, "arithmetic_expression", "") or "").strip():
        arithmetic_hint = (
            "\nComputation rule: use only values explicitly quoted from Context for arithmetic "
            "(difference, ratio, growth, or scale conversion)."
        )

    return (
        "Numeric evidence hints:\n"
        + "\n".join(f"- {line}" for line in picked)
        + yn_hint
        + arithmetic_hint
        + "\nInstruction: preserve the report's exact scale; do not round a table value into a headline approximation."
    )
