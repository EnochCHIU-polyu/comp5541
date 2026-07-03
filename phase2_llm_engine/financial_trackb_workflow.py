"""
Track B financial workflow with baseline and harness toggles.

This module provides:
- run_financial_workflow(...) for V0 and harness variants
- workflow_result_to_dict(...) for scorer/runner serialization
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.llm_client import query_llm
from phase2_llm_engine.trackb_harnesses.h1_retrieval import build_retrieval_context, retrieve_chunks
from phase2_llm_engine.trackb_harnesses.h2_numeric_guard import build_numeric_hint, numeric_guard
from phase2_llm_engine.trackb_harnesses.h3_chronology_guard import chronology_guard
from phase2_llm_engine.trackb_harnesses.h4_verifier import verify_support

_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def _score_chunk(chunk: str, question: str) -> int:
    q_words = {w for w in re.findall(r"[A-Za-z0-9%]+", question.lower()) if len(w) > 2}
    if not q_words:
        return 0
    c_low = chunk.lower()
    return sum(1 for w in q_words if w in c_low)


def _retrieve_chunks(report_text: str, question: str, top_k: int = 5) -> list[str]:
    sents = _sentences(report_text)
    if not sents:
        return []
    scored = sorted(((s, _score_chunk(s, question)) for s in sents), key=lambda x: x[1], reverse=True)
    picks = [s for s, score in scored[:top_k] if score > 0]
    return picks or sents[: min(top_k, len(sents))]


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
        v = float(raw)
    except ValueError:
        return None
    return v / 100.0 if pct else v


def _contains_unit_words(text: str) -> bool:
    low = text.lower()
    unit_tokens = ["million", "billion", "thousand", "万元", "亿元", "人民币", "rmb", "%"]
    return any(token in low for token in unit_tokens)


def _numeric_guard(answer: str, case: FinancialEvalCase) -> dict[str, Any]:
    pred = _extract_first_number(answer)
    exp = _extract_first_number(case.expected_answer)
    numeric_match = None
    if case.answer_type == "numeric":
        if pred is None or exp is None:
            numeric_match = False
        else:
            numeric_match = abs(pred - exp) <= max(case.tolerance, 1e-9)

    unit_warning = False
    if case.expected_unit:
        if case.expected_unit.lower() not in answer.lower():
            unit_warning = True
    elif case.answer_type == "numeric" and _contains_unit_words(case.expected_answer):
        if not _contains_unit_words(answer):
            unit_warning = True

    return {
        "numeric_match": numeric_match,
        "unit_warning": unit_warning,
        "pred_value": pred,
        "expected_value": exp,
    }


def _chronology_guard(answer: str, case: FinancialEvalCase, report_text: str) -> bool | None:
    order = case.expected_event_order or []
    if not order:
        return None
    low_report = report_text.lower()
    positions = []
    for token in order:
        idx = low_report.find(token.lower())
        if idx < 0:
            return False
        positions.append(idx)
    return positions == sorted(positions)


def _build_prompt(question: str, context: str, hint_block: str = "") -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a financial audit assistant. "
                "Answer in English. Provide concise answer and evidence lines. "
                "Prefer the exact table row or disclosure line that matches the question, not a rounded headline summary."
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
                "Return exactly in this format:\n"
                "ANSWER: <short answer>\n"
                "CITATIONS: <semicolon-separated quoted evidence snippets>"
            ),
        },
    ]


def _parse_answer(raw: str) -> tuple[str, list[str]]:
    answer = ""
    citations: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("answer:"):
            answer = stripped.split(":", 1)[1].strip()
        if low.startswith("citations:"):
            chunk = stripped.split(":", 1)[1].strip()
            citations = [c.strip() for c in chunk.split(";") if c.strip()]

    if not answer:
        m = re.search(r"(?im)^\s*(?:\*\*)?answer(?:\*\*)?\s*:\s*(.+)$", raw)
        if m:
            answer = m.group(1).strip()
    if not citations:
        m = re.search(r"(?im)^\s*(?:\*\*)?citations(?:\*\*)?\s*:\s*(.+)$", raw)
        if m:
            citations = [c.strip() for c in m.group(1).split(";") if c.strip()]

    if not answer:
        answer = _normalize_ws(raw)
    return answer, citations


@dataclass
class FinancialWorkflowResult:
    case_id: str
    question: str
    answer: str
    citations: list[str] = field(default_factory=list)
    raw_response: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)



def run_financial_workflow(
    report_text: str,
    case: FinancialEvalCase,
    model: str,
    temperature: float,
    use_h1_retrieval: bool = False,
    use_h2_numeric_guard: bool = False,
    use_h3_chronology_guard: bool = False,
    use_h4_verifier: bool = False,
) -> FinancialWorkflowResult:
    if use_h1_retrieval:
        chunks, context = build_retrieval_context(
            report_text,
            case.question,
            top_k=6,
            evidence_keywords=case.evidence_keywords,
        )
    else:
        chunks = []
        context = report_text

    hint_blocks: list[str] = []
    if case.evidence_keywords:
        hint_blocks.append(f"Evidence keywords: {', '.join(case.evidence_keywords)}")
    if case.expected_unit:
        hint_blocks.append(f"Expected answer unit: {case.expected_unit}")
    if use_h2_numeric_guard:
        numeric_hint = build_numeric_hint(report_text, case, top_k=3)
        if numeric_hint:
            hint_blocks.append(numeric_hint)

    messages = _build_prompt(case.question, context, hint_block="\n\n".join(hint_blocks))
    raw = query_llm(messages, model=model, temperature=temperature)
    answer, citations = _parse_answer(raw)

    diagnostics: dict[str, Any] = {
        "retrieved_chunks": len(chunks) if use_h1_retrieval else 0,
    }

    if use_h2_numeric_guard:
        diagnostics["numeric"] = numeric_guard(answer, case)
    else:
        diagnostics["numeric"] = {"numeric_match": None, "unit_warning": False}

    if use_h3_chronology_guard:
        diagnostics["chronology_ok"] = chronology_guard(answer, case, report_text)
    else:
        diagnostics["chronology_ok"] = None

    if use_h4_verifier:
        initial_verification = verify_support(
            answer,
            citations,
            report_text,
            evidence_keywords=case.evidence_keywords,
            expected_unit=case.expected_unit,
        )
        diagnostics["verification"] = initial_verification
        if not initial_verification.get("verified", False):
            revision_context = context
            revision_prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a skeptical financial reviewer. The previous answer was likely off by scale, unit, or by choosing a headline figure instead of the exact table value. "
                        "Revise only if you can support the answer directly from the provided evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{case.question}\n\n"
                        f"Evidence keywords: {', '.join(case.evidence_keywords or [])}\n"
                        f"Expected unit: {case.expected_unit}\n\n"
                        f"Previous answer:\n{answer}\n\n"
                        f"Evidence context:\n{revision_context}\n\n"
                        "Return exactly in this format:\n"
                        "ANSWER: <short answer>\n"
                        "CITATIONS: <semicolon-separated quoted evidence snippets>"
                    ),
                },
            ]
            revise_raw = query_llm(revision_prompt, model=model, temperature=temperature)
            revised_answer, revised_citations = _parse_answer(revise_raw)
            answer = revised_answer or answer
            if revised_citations:
                citations = revised_citations
            revised_verification = verify_support(
                answer,
                citations,
                report_text,
                evidence_keywords=case.evidence_keywords,
                expected_unit=case.expected_unit,
            )
            revised_verification["revision_applied"] = True
            revised_verification["initial_reason"] = initial_verification.get("reason", "")
            diagnostics["verification"] = revised_verification
    else:
        diagnostics["verification"] = {
            "applied": False,
            "verified": None,
        }

    return FinancialWorkflowResult(
        case_id=case.case_id,
        question=case.question,
        answer=answer,
        citations=citations,
        raw_response=raw,
        diagnostics=diagnostics,
    )


def workflow_result_to_dict(result: FinancialWorkflowResult) -> dict[str, Any]:
    return asdict(result)
