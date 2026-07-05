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
                "You are Reviewer-A, a strict financial QA judge. "
                "Use Context only. Never use external knowledge or inference. "
                "Prioritize numeric fidelity: exact value, sign, scale, unit, currency, period/date, and entity."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                "Draft output:\n"
                f"ANSWER: {draft_answer}\n"
                f"CITATIONS: {'; '.join(draft_citations) if draft_citations else 'NONE'}\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Return exactly:\n"
                "ANSWER: PASS | <reason_code> OR FAIL | <reason_code>\n"
                "CITATIONS: <1-2 semicolon-separated verbatim snippets from Context; or NONE>\n\n"
                "Decision rules:\n"
                "- FAIL if any material claim is unsupported.\n"
                "- FAIL for any number mismatch (digit, decimal, sign, %, basis points, scale like thousand/million/billion, unit, currency, date/period, or entity).\n"
                "- FAIL if draft citations are missing, non-verbatim, or do not support the claim.\n"
                "- PASS only when fully supported and numerically consistent.\n"
                "- If evidence is genuinely missing, prefer FAIL | INSUFFICIENT_EVIDENCE.\n"
                "Use short reason codes such as SUPPORTED, NUMERIC_MISMATCH, UNIT_MISMATCH, PERIOD_MISMATCH, ENTITY_MISMATCH, UNSUPPORTED, BAD_CITATIONS, INSUFFICIENT_EVIDENCE."
            ),
        },
    ]

    revise_messages = [
        {
            "role": "system",
            "content": (
                "You are Reviewer-B, a conservative financial QA reviser. "
                "Use Context only and output the safest correct answer. "
                "Do not infer or guess beyond explicit evidence."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                "Prior draft:\n"
                f"ANSWER: {draft_answer}\n"
                f"CITATIONS: {'; '.join(draft_citations) if draft_citations else 'NONE'}\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Output format (strict):\n"
                "ANSWER: <short answer, <= 25 words>\n"
                "CITATIONS: <semicolon-separated direct snippets from Context>\n\n"
                "Hard constraints:\n"
                "- For numeric answers, copy exact value and qualifiers from Context (sign, decimal, scale, unit, currency, period/date, entity).\n"
                "- Do not recompute, normalize, or round unless Context explicitly states the transformed value.\n"
                "- Keep answer minimal (ideally one value + unit/time).\n"
                "- Do not invent facts not present in Context.\n"
                "- If evidence is insufficient for a reliable answer, output exactly:\n"
                "  ANSWER: INSUFFICIENT_EVIDENCE\n"
                "  CITATIONS: NONE"
            ),
        },
    ]

    return judge_messages, revise_messages


def build_h3_batch_judge_prompt(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Build one H3 judge prompt for multiple cases with strict JSON output."""
    sections: list[str] = []
    for idx, item in enumerate(items, start=1):
        sections.append(
            "\n".join(
                [
                    f"CASE {idx} | case_id={item['case_id']}",
                    "Question:",
                    item["question"],
                    "Draft output:",
                    f"ANSWER: {item.get('draft_answer', '')}",
                    f"CITATIONS: {item.get('draft_citations', 'NONE') or 'NONE'}",
                    "Context:",
                    item["context"],
                ]
            )
        )

    return [
        {
            "role": "system",
            "content": (
                "You are Reviewer-A, a strict financial QA batch judge. "
                "Use Context only. Enforce exact numeric fidelity (value, sign, scale, unit, currency, period/date, entity). "
                "Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Evaluate all cases below.\n\n"
                "Output format (strict JSON array):\n"
                "[\n"
                '  {"case_id":"...","judge":"PASS | <short reason> OR FAIL | <short reason>","citations":["..."]}\n'
                "]\n\n"
                "Rules:\n"
                "- PASS only if every material claim is directly supported by Context.\n"
                "- FAIL for any numeric mismatch: value, decimal, sign, %, basis points, scale (thousand/million/billion), unit, currency, period/date, or entity mismatch.\n"
                "- FAIL if draft citations are missing, non-verbatim, or not supporting the claim.\n"
                "- If Context is insufficient, output FAIL | INSUFFICIENT_EVIDENCE.\n"
                "- judge must start with PASS or FAIL; keep reason short using code-like labels.\n"
                "- citations must be an array: 1-2 short verbatim snippets from Context, or [\"NONE\"] when none.\n"
                "- No extra keys, prose, markdown, or code fences.\n\n"
                + "\n\n".join(sections)
            ),
        },
    ]


def build_h3_batch_revision_prompt(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Build one H3 revision prompt for multiple failed cases with strict JSON output."""
    sections: list[str] = []
    for idx, item in enumerate(items, start=1):
        sections.append(
            "\n".join(
                [
                    f"CASE {idx} | case_id={item['case_id']}",
                    "Question:",
                    item["question"],
                    "Prior draft:",
                    f"ANSWER: {item.get('draft_answer', '')}",
                    f"CITATIONS: {item.get('draft_citations', 'NONE') or 'NONE'}",
                    "Context:",
                    item["context"],
                ]
            )
        )

    return [
        {
            "role": "system",
            "content": (
                "You are Reviewer-B, a conservative financial QA batch reviser. "
                "Use Context only and return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Revise all failed cases below.\n\n"
                "Output format (strict JSON array):\n"
                "[\n"
                '  {"case_id":"...","answer":"<short answer, <= 25 words>","citations":["..."]}\n'
                "]\n\n"
                "Hard constraints:\n"
                "- For numeric cases, copy exact value and qualifiers from Context (sign, decimal, %, basis points, scale, unit, currency, period/date, entity).\n"
                "- Do not recompute, normalize, or round unless explicitly stated in Context.\n"
                "- Keep answer minimal and precise (prefer one value + unit/time).\n"
                "- Do not invent facts not present in Context.\n"
                "- citations must be an array of 1-2 short verbatim snippets that directly support the answer.\n"
                "- If evidence is insufficient, output answer exactly as INSUFFICIENT_EVIDENCE and citations as [\"NONE\"].\n"
                "- No extra keys, prose, markdown, or code fences.\n\n"
                + "\n\n".join(sections)
            ),
        },
    ]


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
