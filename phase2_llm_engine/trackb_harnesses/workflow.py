"""Ablation-ready Track B harness workflow entrypoint."""

from __future__ import annotations

import re

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.trackb_harnesses.h1_code_base import build_retrieval_context
from phase2_llm_engine.trackb_harnesses.h2_prompt_base import build_h2_prompt, build_numeric_hint, numeric_guard
from phase2_llm_engine.trackb_harnesses.h3_multi_llm_as_judge import build_h3_review_prompts, chronology_guard
from phase2_llm_engine.trackb_harnesses.h4_evidence_verifier import repair_answer_deterministic, verify_support
from phase2_llm_engine.trackb_harnesses.types import HarnessState, WorkflowRuntime


_RUNTIME: WorkflowRuntime | None = None


def configure_runtime(report_text: str, cases: list[FinancialEvalCase]) -> None:
    """Configure global runtime for direct run_workflow usage in experiments."""
    global _RUNTIME
    _RUNTIME = WorkflowRuntime(
        report_text=report_text,
        cases_by_question={c.question.strip(): c for c in cases},
    )


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in messages)


def _build_independent_baseline_prompt(query: str) -> list[dict[str, str]]:
    """True baseline: single-call, no retrieval context, no harness dependencies."""
    return [
        {
            "role": "system",
            "content": "You are a financial QA assistant. Answer concisely.",
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{query}\n\n"
                "Return exactly:\n"
                "ANSWER: <short answer>\n"
                "CITATIONS: NONE"
            ),
        },
    ]


def _parse_answer(raw: str) -> tuple[str, list[str]]:
    answer = ""
    citations: list[str] = []
    for line in raw.splitlines():
        line_strip = line.strip()
        lower = line_strip.lower()
        if lower.startswith("answer:"):
            answer = line_strip.split(":", 1)[1].strip()
        if lower.startswith("citations:"):
            tail = line_strip.split(":", 1)[1].strip()
            if tail and tail.upper() != "NONE":
                citations = [c.strip() for c in tail.split(";") if c.strip()]
    if not answer:
        answer = raw.strip() or "INSUFFICIENT_EVIDENCE"
    return answer, citations


def call_llm(prompt: str) -> str:
    """Deterministic mock LLM used for local harness integration tests."""
    low = prompt.lower()

    if "pass or fail" in low:
        if "answer: insufficient_evidence" in low:
            return "ANSWER: FAIL | insufficient evidence\nCITATIONS: NONE"
        if "citations: none" in low:
            return "ANSWER: FAIL | missing citations\nCITATIONS: NONE"
        return "ANSWER: PASS | supported by context\nCITATIONS: reviewer accepted"

    if "produce a corrected final answer" in low:
        m = re.search(r"question:\s*(.*?)\s*(?:expected unit:|prior draft:)", prompt, flags=re.IGNORECASE | re.DOTALL)
        q = m.group(1).strip() if m else ""
        if q:
            return f"ANSWER: INSUFFICIENT_EVIDENCE\nCITATIONS: NONE"
        return "ANSWER: INSUFFICIENT_EVIDENCE\nCITATIONS: NONE"

    if "total revenues" in low and "109,896" in low and "q1 2026" in low:
        return "ANSWER: 109896 USD millions\nCITATIONS: Total revenues $ 90,234 $ 109,896"
    if "total revenues" in low and "90,234" in low and "q1 2025" in low:
        return "ANSWER: 90234 USD millions\nCITATIONS: Total revenues $ 90,234 $ 109,896"
    if "google cloud" in low and "20,028" in low and "revenue" in low:
        return "ANSWER: 20028 USD millions\nCITATIONS: Google Cloud  12,260  20,028"
    if "google cloud" in low and "6,598" in low and "operating income" in low:
        return "ANSWER: 6598 USD millions\nCITATIONS: Google Cloud  2,177  6,598"
    if "diluted net income per share" in low and "5.11" in low:
        return "ANSWER: 5.11 USD\nCITATIONS: Diluted net income per share $ 2.81 $ 5.11"
    if "dividend timeline" in low or "declaration date" in low:
        return (
            "ANSWER: april 27, 2026 -> june 8, 2026 -> june 15, 2026\n"
            "CITATIONS: On April 27, 2026 ... as of June 8, 2026 ... payable on June 15, 2026"
        )
    if "did" in low and "answer yes or no" in low and "increased 63%" in low:
        return "ANSWER: yes\nCITATIONS: Google Cloud ... revenues increased 63%"

    return "ANSWER: INSUFFICIENT_EVIDENCE\nCITATIONS: NONE"


def run_workflow(query, use_h1=False, use_h2=False, use_h3=False, use_h4=False):
    """Run baseline + optional H1-H4 harnesses for one query (ablation-ready)."""
    if _RUNTIME is None:
        raise RuntimeError("Runtime not configured. Call configure_runtime(report_text, cases) first.")

    normalized_query = str(query).strip()
    case = _RUNTIME.cases_by_question.get(normalized_query)
    if case is None:
        case = FinancialEvalCase(
            case_id="ad_hoc",
            question=normalized_query,
            answer_type="text",
            expected_answer="",
        )

    state = HarnessState(
        query=normalized_query,
        case=case,
        report_text=_RUNTIME.report_text,
        context="",
    )
    state.stage_trace.append("start")

    baseline_only = not (use_h1 or use_h2 or use_h3 or use_h4)
    if baseline_only:
        state.prompt_messages = _build_independent_baseline_prompt(state.query)
        state.stage_trace.append("baseline_independent")
        state.raw_llm = call_llm(_messages_to_prompt(state.prompt_messages))
        state.answer, state.citations = _parse_answer(state.raw_llm)
        if not state.answer:
            state.answer = "INSUFFICIENT_EVIDENCE"
            state.citations = ["NONE"]
            state.status = "insufficient_evidence"
        state.stage_trace.append("done")
        return state

    if use_h1:
        chunks, context = build_retrieval_context(
            report_text=state.report_text,
            question=state.query,
            top_k=6,
            evidence_keywords=case.evidence_keywords,
        )
        state.retrieved_chunks = chunks
        state.context = context
        state.stage_trace.append("h1")

    hint_block = ""
    if use_h2:
        hint_block = build_numeric_hint(state.report_text, case, top_k=4)
        state.prompt_messages = build_h2_prompt(
            question=state.query,
            context=state.context,
            hint_block=hint_block,
        )
        state.stage_trace.append("h2_prompt")
    else:
        state.prompt_messages = _build_independent_baseline_prompt(state.query)
        state.stage_trace.append("baseline_prompt")

    state.raw_llm = call_llm(_messages_to_prompt(state.prompt_messages))
    state.answer, state.citations = _parse_answer(state.raw_llm)
    state.stage_trace.append("generate")

    if use_h2:
        state.numeric_diag = numeric_guard(state.answer, case)
        state.diagnostics["numeric_diag"] = state.numeric_diag
        state.stage_trace.append("h2_guard")

    if use_h3:
        chronology_ok = chronology_guard(state.answer, case, state.report_text)
        judge_msgs, revise_msgs = build_h3_review_prompts(
            question=state.query,
            context=state.context,
            draft_answer=state.answer,
            draft_citations=state.citations,
            expected_unit=case.expected_unit,
            evidence_keywords=case.evidence_keywords,
        )
        judge_raw = call_llm(_messages_to_prompt(judge_msgs))
        judge_answer, _ = _parse_answer(judge_raw)
        judge_pass = judge_answer.lower().startswith("pass")

        state.h3_diag = {
            "judge_pass": judge_pass,
            "judge_reason": judge_answer,
            "revise_applied": False,
            "chronology_ok": chronology_ok,
        }
        if not judge_pass:
            revise_raw = call_llm(_messages_to_prompt(revise_msgs))
            revised_answer, revised_citations = _parse_answer(revise_raw)
            if revised_answer:
                state.answer = revised_answer
            if revised_citations:
                state.citations = revised_citations
            state.h3_diag["revise_applied"] = True

        state.diagnostics["h3_diag"] = state.h3_diag
        state.stage_trace.append("h3")

    if use_h4:
        verify_before = verify_support(
            answer=state.answer,
            citations=state.citations,
            report_text=state.report_text,
            evidence_keywords=case.evidence_keywords,
            expected_unit=case.expected_unit,
        )
        verify_diag = dict(verify_before)
        if not verify_before.get("verified", False):
            repaired_answer, repaired_citations, actions = repair_answer_deterministic(
                answer=state.answer,
                citations=state.citations,
                report_text=state.report_text,
                case=case,
            )
            state.answer = repaired_answer
            state.citations = repaired_citations
            verify_after = verify_support(
                answer=state.answer,
                citations=state.citations,
                report_text=state.report_text,
                evidence_keywords=case.evidence_keywords,
                expected_unit=case.expected_unit,
            )
            verify_diag["repair_actions"] = actions
            verify_diag["reverified"] = bool(verify_after.get("verified", False))
            verify_diag["reason"] = verify_after.get("reason", verify_diag.get("reason", ""))

        state.verify_diag = verify_diag
        state.diagnostics["verify_diag"] = verify_diag
        state.stage_trace.append("h4")

    if not state.answer or state.answer.strip().upper() in {"", "N/A"}:
        state.answer = "INSUFFICIENT_EVIDENCE"
        state.citations = ["NONE"]
        state.status = "insufficient_evidence"
    elif state.answer.strip().upper() == "INSUFFICIENT_EVIDENCE":
        if not state.citations:
            state.citations = ["NONE"]
        state.status = "insufficient_evidence"

    state.stage_trace.append("done")
    return state
