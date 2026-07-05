"""
Track B financial workflow with baseline and harness toggles.

This module provides:
- run_financial_workflow(...) for V0 and harness variants
- workflow_result_to_dict(...) for scorer/runner serialization
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.llm_client import query_llm
from phase2_llm_engine.trackb_harnesses.h0_baseline import (
    build_batch_prompt,
    extract_json_array,
    parse_answer,
)
from phase2_llm_engine.trackb_harnesses.h1_retrieval import build_retrieval_context, retrieve_chunks
from phase2_llm_engine.trackb_harnesses.h2_numeric_guard import build_h2_prompt, build_numeric_hint, numeric_guard
from phase2_llm_engine.trackb_harnesses.h3_chronology_guard import build_h3_review_prompts, chronology_guard
from phase2_llm_engine.trackb_harnesses.h4_verifier import repair_answer_deterministic, verify_support

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_BATCH_CONTEXT_CHARS_PER_CASE = 2400
ProgressCallback = Callable[[str, str, str, dict[str, Any] | None], None]


def _emit_progress(
    callback: ProgressCallback | None,
    case_id: str,
    step: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    try:
        callback(case_id, step, status, details or {})
    except Exception:  # noqa: BLE001
        # Progress reporting should never fail the workflow.
        return


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


def _compact_context(report_text: str, question: str, per_case_cap: int = _BATCH_CONTEXT_CHARS_PER_CASE) -> str:
    chunks = _retrieve_chunks(report_text, question, top_k=8)
    if not chunks:
        return report_text[:per_case_cap]

    selected: list[str] = []
    total = 0
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        next_len = len(chunk) + (3 if selected else 0)
        if total + next_len > per_case_cap:
            remain = per_case_cap - total
            if remain > 50:
                selected.append(chunk[:remain])
            break
        selected.append(chunk)
        total += next_len

    return "\n- ".join(["Top evidence snippets:", *selected]) if selected else report_text[:per_case_cap]


def _build_independent_baseline_prompt(question: str) -> list[dict[str, str]]:
    """Baseline prompt: one question, no retrieval context, no harness hints."""
    return [
        {
            "role": "system",
            "content": "You are a financial QA assistant. Answer concisely.",
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                "Return exactly:\n"
                "ANSWER: <short answer>\n"
                "CITATIONS: NONE"
            ),
        },
    ]


def _parse_answer(raw: str) -> tuple[str, list[str]]:
    return parse_answer(raw)


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
    h3_reviewer_model: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> FinancialWorkflowResult:
    _emit_progress(progress_callback, case.case_id, "workflow", "started", {"batch": False})

    baseline_only = not (use_h1_retrieval or use_h2_numeric_guard or use_h3_chronology_guard or use_h4_verifier)
    if baseline_only:
        raw = query_llm(_build_independent_baseline_prompt(case.question), model=model, temperature=temperature)
        answer, citations = _parse_answer(raw)
        _emit_progress(progress_callback, case.case_id, "llm_answer", "completed", {"batch": False})
        _emit_progress(progress_callback, case.case_id, "workflow", "completed", {"batch": False})
        return FinancialWorkflowResult(
            case_id=case.case_id,
            question=case.question,
            answer=answer,
            citations=citations,
            raw_response=raw,
            diagnostics={
                "retrieved_chunks": 0,
                "numeric": {"numeric_match": None, "unit_warning": False},
                "chronology_ok": None,
                "h3_review": {
                    "reviewer_model": None,
                    "judge_result": None,
                    "revision_applied": False,
                },
                "verification": {"applied": False, "verified": None},
            },
        )

    if use_h1_retrieval:
        chunks, context = build_retrieval_context(
            report_text,
            case.question,
            top_k=6,
            evidence_keywords=case.evidence_keywords,
        )
        _emit_progress(
            progress_callback,
            case.case_id,
            "h1_retrieval",
            "completed",
            {"retrieved_chunks": len(chunks)},
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

    if use_h2_numeric_guard:
        messages = build_h2_prompt(case.question, context, hint_block="\n\n".join(hint_blocks))
    else:
        messages = _build_independent_baseline_prompt(case.question)
    raw = query_llm(messages, model=model, temperature=temperature)
    answer, citations = _parse_answer(raw)
    _emit_progress(progress_callback, case.case_id, "llm_answer", "completed", {"batch": False})

    diagnostics: dict[str, Any] = {
        "retrieved_chunks": len(chunks) if use_h1_retrieval else 0,
    }

    if use_h2_numeric_guard:
        diagnostics["numeric"] = numeric_guard(answer, case)
        _emit_progress(
            progress_callback,
            case.case_id,
            "h2_numeric_guard",
            "completed",
            diagnostics["numeric"],
        )
    else:
        diagnostics["numeric"] = {"numeric_match": None, "unit_warning": False}

    if use_h3_chronology_guard:
        diagnostics["chronology_ok"] = chronology_guard(answer, case, report_text)
    else:
        diagnostics["chronology_ok"] = None

    if use_h3_chronology_guard:
        judge_prompt, revise_prompt = build_h3_review_prompts(
            question=case.question,
            context=context,
            draft_answer=answer,
            draft_citations=citations,
            expected_unit=case.expected_unit,
            evidence_keywords=case.evidence_keywords,
        )
        reviewer_model = h3_reviewer_model or model
        judge_raw = query_llm(judge_prompt, model=reviewer_model, temperature=0.0)
        judge_answer, _ = _parse_answer(judge_raw)
        diagnostics["h3_review"] = {
            "reviewer_model": reviewer_model,
            "judge_raw": judge_raw,
            "judge_result": judge_answer,
        }
        _emit_progress(
            progress_callback,
            case.case_id,
            "h3_chronology_guard",
            "completed",
            {"judge_result": judge_answer},
        )
        if judge_answer.upper().startswith("FAIL"):
            revise_raw = query_llm(revise_prompt, model=reviewer_model, temperature=0.0)
            revised_answer, revised_citations = _parse_answer(revise_raw)
            if revised_answer:
                answer = revised_answer
            if revised_citations:
                citations = revised_citations
            diagnostics["h3_review"]["revision_applied"] = True
            diagnostics["h3_review"]["revise_raw"] = revise_raw
            _emit_progress(
                progress_callback,
                case.case_id,
                "h3_revision",
                "completed",
                {"revision_applied": True},
            )
        else:
            diagnostics["h3_review"]["revision_applied"] = False
    else:
        diagnostics["h3_review"] = {
            "reviewer_model": None,
            "judge_result": None,
            "revision_applied": False,
        }

    if use_h4_verifier:
        initial_verification = verify_support(
            answer,
            citations,
            report_text,
            evidence_keywords=case.evidence_keywords,
            expected_unit=case.expected_unit,
        )
        diagnostics["verification"] = initial_verification
        _emit_progress(
            progress_callback,
            case.case_id,
            "h4_verifier",
            "completed",
            {
                "verified": bool(initial_verification.get("verified", False)),
                "reason": initial_verification.get("reason", ""),
            },
        )
        if not initial_verification.get("verified", False):
            repaired_answer, repaired_citations, repair_actions = repair_answer_deterministic(
                answer,
                citations,
                report_text,
                case,
            )
            answer = repaired_answer
            citations = repaired_citations
            revised_verification = verify_support(
                answer,
                citations,
                report_text,
                evidence_keywords=case.evidence_keywords,
                expected_unit=case.expected_unit,
            )
            revised_verification["revision_applied"] = bool(repair_actions)
            revised_verification["repair_actions"] = repair_actions
            revised_verification["initial_reason"] = initial_verification.get("reason", "")
            diagnostics["verification"] = revised_verification
            _emit_progress(
                progress_callback,
                case.case_id,
                "h4_repair",
                "completed",
                {"repair_actions": repair_actions},
            )
    else:
        diagnostics["verification"] = {
            "applied": False,
            "verified": None,
        }

    _emit_progress(progress_callback, case.case_id, "workflow", "completed", {"batch": False})

    return FinancialWorkflowResult(
        case_id=case.case_id,
        question=case.question,
        answer=answer,
        citations=citations,
        raw_response=raw,
        diagnostics=diagnostics,
    )


def run_financial_workflow_batch(
    report_text: str,
    cases: list[FinancialEvalCase],
    model: str,
    temperature: float,
    use_h1_retrieval: bool = False,
    use_h2_numeric_guard: bool = False,
    use_h3_chronology_guard: bool = False,
    use_h4_verifier: bool = False,
    h3_reviewer_model: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[FinancialWorkflowResult]:
    if not cases:
        return []

    baseline_only = not (use_h1_retrieval or use_h2_numeric_guard or use_h3_chronology_guard or use_h4_verifier)
    if baseline_only:
        results: list[FinancialWorkflowResult] = []
        for case in cases:
            _emit_progress(progress_callback, case.case_id, "llm_batch", "started", {"batch": True})
            raw = query_llm(_build_independent_baseline_prompt(case.question), model=model, temperature=temperature)
            answer, citations = _parse_answer(raw)
            _emit_progress(progress_callback, case.case_id, "llm_answer", "completed", {"batch": True})
            _emit_progress(progress_callback, case.case_id, "workflow", "completed", {"batch": True})
            results.append(
                FinancialWorkflowResult(
                    case_id=case.case_id,
                    question=case.question,
                    answer=answer,
                    citations=citations,
                    raw_response=raw,
                    diagnostics={
                        "retrieved_chunks": 0,
                        "numeric": {"numeric_match": None, "unit_warning": False},
                        "chronology_ok": None,
                        "h3_review": {
                            "reviewer_model": None,
                            "judge_result": None,
                            "revision_applied": False,
                        },
                        "verification": {"applied": False, "verified": None},
                    },
                )
            )
        return results

    batch_items: list[dict[str, str]] = []
    context_by_case_id: dict[str, str] = {}
    for case in cases:
        if use_h1_retrieval:
            _, context = build_retrieval_context(
                report_text,
                case.question,
                top_k=6,
                evidence_keywords=case.evidence_keywords,
            )
        else:
            context = _compact_context(report_text, case.question)

        if len(context) > _BATCH_CONTEXT_CHARS_PER_CASE:
            context = context[:_BATCH_CONTEXT_CHARS_PER_CASE]

        hint_blocks: list[str] = []
        if case.evidence_keywords:
            hint_blocks.append(f"Evidence keywords: {', '.join(case.evidence_keywords)}")
        if case.expected_unit:
            hint_blocks.append(f"Expected answer unit: {case.expected_unit}")
        if use_h2_numeric_guard:
            numeric_hint = build_numeric_hint(report_text, case, top_k=3)
            if numeric_hint:
                hint_blocks.append(numeric_hint)

        batch_items.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "hint_block": "\n".join(hint_blocks),
                "context": context,
            }
        )
        context_by_case_id[case.case_id] = context

    messages = build_batch_prompt(batch_items, strict=use_h2_numeric_guard)
    for case in cases:
        _emit_progress(progress_callback, case.case_id, "llm_batch", "started", {"batch": True})
    raw = query_llm(messages, model=model, temperature=temperature)
    parsed_rows = extract_json_array(raw)
    by_id: dict[str, dict[str, Any]] = {}
    for row in parsed_rows:
        key = str(row.get("case_id", "")).strip()
        if key:
            by_id[key] = row

    results: list[FinancialWorkflowResult] = []
    for idx, case in enumerate(cases):
        row = by_id.get(case.case_id)
        if row is None and idx < len(parsed_rows):
            row = parsed_rows[idx]

        answer = ""
        citations: list[str] = []
        if isinstance(row, dict):
            answer = str(row.get("answer", "")).strip()
            raw_citations = row.get("citations", [])
            if isinstance(raw_citations, list):
                citations = [str(c).strip() for c in raw_citations if str(c).strip()]
            elif isinstance(raw_citations, str):
                citations = [c.strip() for c in raw_citations.split(";") if c.strip()]

        _emit_progress(progress_callback, case.case_id, "llm_answer", "completed", {"batch": True})

        diagnostics: dict[str, Any] = {
            "retrieved_chunks": 6 if use_h1_retrieval else 0,
        }

        if use_h2_numeric_guard:
            diagnostics["numeric"] = numeric_guard(answer, case)
            _emit_progress(
                progress_callback,
                case.case_id,
                "h2_numeric_guard",
                "completed",
                diagnostics["numeric"],
            )
        else:
            diagnostics["numeric"] = {"numeric_match": None, "unit_warning": False}

        if use_h3_chronology_guard:
            diagnostics["chronology_ok"] = chronology_guard(answer, case, report_text)
        else:
            diagnostics["chronology_ok"] = None

        if use_h3_chronology_guard:
            judge_prompt, revise_prompt = build_h3_review_prompts(
                question=case.question,
                context=context_by_case_id.get(case.case_id, report_text),
                draft_answer=answer,
                draft_citations=citations,
                expected_unit=case.expected_unit,
                evidence_keywords=case.evidence_keywords,
            )
            reviewer_model = h3_reviewer_model or model
            judge_raw = query_llm(judge_prompt, model=reviewer_model, temperature=0.0)
            judge_answer, _ = _parse_answer(judge_raw)
            diagnostics["h3_review"] = {
                "reviewer_model": reviewer_model,
                "judge_raw": judge_raw,
                "judge_result": judge_answer,
            }
            _emit_progress(
                progress_callback,
                case.case_id,
                "h3_chronology_guard",
                "completed",
                {"judge_result": judge_answer},
            )
            if judge_answer.upper().startswith("FAIL"):
                revise_raw = query_llm(revise_prompt, model=reviewer_model, temperature=0.0)
                revised_answer, revised_citations = _parse_answer(revise_raw)
                if revised_answer:
                    answer = revised_answer
                if revised_citations:
                    citations = revised_citations
                diagnostics["h3_review"]["revision_applied"] = True
                diagnostics["h3_review"]["revise_raw"] = revise_raw
                _emit_progress(
                    progress_callback,
                    case.case_id,
                    "h3_revision",
                    "completed",
                    {"revision_applied": True},
                )
            else:
                diagnostics["h3_review"]["revision_applied"] = False
        else:
            diagnostics["h3_review"] = {
                "reviewer_model": None,
                "judge_result": None,
                "revision_applied": False,
            }

        if use_h4_verifier:
            initial_verification = verify_support(
                answer,
                citations,
                report_text,
                evidence_keywords=case.evidence_keywords,
                expected_unit=case.expected_unit,
            )
            diagnostics["verification"] = initial_verification
            _emit_progress(
                progress_callback,
                case.case_id,
                "h4_verifier",
                "completed",
                {
                    "verified": bool(initial_verification.get("verified", False)),
                    "reason": initial_verification.get("reason", ""),
                },
            )
            if not initial_verification.get("verified", False):
                repaired_answer, repaired_citations, repair_actions = repair_answer_deterministic(
                    answer,
                    citations,
                    report_text,
                    case,
                )
                answer = repaired_answer
                citations = repaired_citations
                revised_verification = verify_support(
                    answer,
                    citations,
                    report_text,
                    evidence_keywords=case.evidence_keywords,
                    expected_unit=case.expected_unit,
                )
                revised_verification["revision_applied"] = bool(repair_actions)
                revised_verification["repair_actions"] = repair_actions
                revised_verification["initial_reason"] = initial_verification.get("reason", "")
                diagnostics["verification"] = revised_verification
                _emit_progress(
                    progress_callback,
                    case.case_id,
                    "h4_repair",
                    "completed",
                    {"repair_actions": repair_actions},
                )
        else:
            diagnostics["verification"] = {
                "applied": False,
                "verified": None,
            }

        _emit_progress(progress_callback, case.case_id, "workflow", "completed", {"batch": True})

        results.append(
            FinancialWorkflowResult(
                case_id=case.case_id,
                question=case.question,
                answer=answer,
                citations=citations,
                raw_response=raw,
                diagnostics=diagnostics,
            )
        )

    return results


def workflow_result_to_dict(result: FinancialWorkflowResult) -> dict[str, Any]:
    return asdict(result)
