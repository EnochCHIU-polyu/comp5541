"""H3 - Chronology guard for Track B financial report questions."""

from __future__ import annotations

import re

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase


def _normalize(text: str) -> str:
    low = text.lower()
    low = re.sub(r"[,/.-]", " ", low)
    low = re.sub(r"\s+", " ", low)
    return low.strip()


def build_h3_review_prompts(
    question: str,
    context: str,
    draft_answer: str,
    draft_citations: list[str],
    expected_unit: str = "",
    evidence_keywords: list[str] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Build H3 multi-LLM review prompts: judge stage and revise stage."""
    judge_messages = [
        {
            "role": "system",
            "content": (
                "You are Reviewer-A, a strict financial fact-check judge. "
                "Assess whether the draft answer is fully supported by the provided Context only. "
                "Do not use external knowledge and do not infer missing facts."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                f"Expected unit: {expected_unit or '(none)'}\n"
                f"Evidence keywords: {', '.join(evidence_keywords or []) or '(none)'}\n\n"
                "Draft output:\n"
                f"ANSWER: {draft_answer}\n"
                f"CITATIONS: {'; '.join(draft_citations) if draft_citations else 'NONE'}\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Return exactly:\n"
                "ANSWER: PASS | <short reason> OR FAIL | <short reason>\n"
                "CITATIONS: <semicolon-separated snippets from Context that justify the judgment; or NONE>\n\n"
                "Fail if any of these hold:\n"
                "- draft uses unsupported number/unit/date/entity\n"
                "- draft citation text is missing or inconsistent\n"
                "- evidence is insufficient for a precise answer"
            ),
        },
    ]

    revise_messages = [
        {
            "role": "system",
            "content": (
                "You are Reviewer-B, a skeptical reviser for financial QA. "
                "Produce a corrected final answer grounded only in Context. "
                "Never guess beyond explicit evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                f"Expected unit: {expected_unit or '(none)'}\n"
                f"Evidence keywords: {', '.join(evidence_keywords or []) or '(none)'}\n\n"
                "Prior draft:\n"
                f"ANSWER: {draft_answer}\n"
                f"CITATIONS: {'; '.join(draft_citations) if draft_citations else 'NONE'}\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Output format (strict):\n"
                "ANSWER: <short answer, <= 25 words>\n"
                "CITATIONS: <semicolon-separated direct snippets from Context>\n\n"
                "Hard constraints:\n"
                "- Keep exact scale/unit from evidence; do not round into a different magnitude.\n"
                "- Do not invent facts not present in Context.\n"
                "- If evidence is insufficient for a reliable answer, output exactly:\n"
                "  ANSWER: INSUFFICIENT_EVIDENCE\n"
                "  CITATIONS: NONE"
            ),
        },
    ]

    return judge_messages, revise_messages


def chronology_guard(answer: str, case: FinancialEvalCase, report_text: str) -> bool | None:
    """Check whether expected events appear in the order requested by the case."""
    order = case.expected_event_order or []
    if not order:
        return None

    # Validate chronology in the model answer, not in source-document order.
    low_answer = _normalize(answer)
    positions = []
    for token in order:
        idx = low_answer.find(_normalize(token))
        if idx < 0:
            return False
        positions.append(idx)
    return positions == sorted(positions)
