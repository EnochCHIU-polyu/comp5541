"""
Track B financial workflow with baseline and harness toggles.

This module provides:
- run_financial_workflow(...) for V0 and harness variants
- workflow_result_to_dict(...) for scorer/runner serialization
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Callable

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.llm_client import llm_process, query_llm
from phase2_llm_engine.trackb_harnesses.h0_baseline_prompt import (
    build_baseline_prompt,
    build_batch_prompt,
    extract_json_array,
    parse_answer,
)
from phase2_llm_engine.trackb_harnesses.h1_code_base import build_retrieval_context, retrieve_chunks
from phase2_llm_engine.trackb_harnesses.h2_prompt_base import build_h2_prompt, build_numeric_hint
from phase2_llm_engine.trackb_harnesses.h3_multi_llm_as_judge import (
    build_h3_batch_revision_prompt,
    build_h3_batch_judge_prompt,
    build_h3_review_prompts,
    chronology_guard,
)
from phase2_llm_engine.trackb_harnesses.h4_evidence_verifier import (
    canonicalize_numeric_answer,
    canonicalize_text_answer,
    h2_numeric_guard as numeric_guard,
    repair_answer_deterministic,
    verify_support,
)

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


def _query_llm_with_process(
    process_name: str,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
) -> str:
    with llm_process(process_name):
        return query_llm(messages, model=model, temperature=temperature)


def _normalize_h3_layers(
    h3_layers: list[dict[str, Any]] | None,
    h3_reviewer_model: str | None,
    default_model: str,
    default_batch: int,
) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for layer in h3_layers or []:
        if not isinstance(layer, dict):
            continue
        model = str(layer.get("model", "")).strip()
        if not model:
            continue
        batch_size = int(layer.get("batch_size", default_batch) or default_batch)
        layers.append(
            {
                "model": model,
                "batch_size": max(1, min(batch_size, 64)),
            }
        )

    if layers:
        return layers[:4]

    return [
        {
            "model": h3_reviewer_model or default_model,
            "batch_size": max(1, min(default_batch, 64)),
        }
    ]


def _chunk_list(items: list[str], size: int) -> list[list[str]]:
    n = max(1, int(size or 1))
    return [items[i : i + n] for i in range(0, len(items), n)]


def _is_arithmetic_case(case: FinancialEvalCase) -> bool:
    return bool((getattr(case, "arithmetic_expression", "") or "").strip())


def _is_timeline_case(case: FinancialEvalCase) -> bool:
    return bool(getattr(case, "expected_event_order", None))


def _is_unanswerable_case(case: FinancialEvalCase) -> bool:
    return (getattr(case, "answer_type", "") or "").strip().lower() == "unanswerable"


def _use_relaxed_h2_prompt(case: FinancialEvalCase) -> bool:
    return _is_arithmetic_case(case) or _is_timeline_case(case) or _is_unanswerable_case(case)


def _merge_keywords(primary: list[str] | None, fallback: list[str] | None) -> list[str] | None:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (primary or [], fallback or []):
        token = str(source).strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(token)
    return merged or None


def _effective_retrieval_top_k(base_top_k: int, case: FinancialEvalCase) -> int:
    bonus = 4 if (_is_arithmetic_case(case) or _is_timeline_case(case)) else 0
    return max(1, min(base_top_k + bonus, 20))


def _h3_reason_code(judge_answer: str) -> str:
    text = str(judge_answer or "").strip()
    if not text:
        return ""
    if "|" in text:
        return text.split("|", 1)[1].strip().upper()
    upper = text.upper()
    if upper.startswith("FAIL"):
        return "FAIL"
    if upper.startswith("PASS"):
        return "PASS"
    return ""


def _should_apply_h3_revision(
    judge_answer: str,
    case: FinancialEvalCase,
    pre_h3_numeric: dict[str, Any] | None,
) -> bool:
    upper = str(judge_answer or "").strip().upper()
    if not upper.startswith("FAIL"):
        return False

    reason = _h3_reason_code(judge_answer)
    numeric_match = bool((pre_h3_numeric or {}).get("numeric_match") is True)

    recoverable_reasons = {
        "BAD_CITATIONS",
        "ANSWER_FORMAT",
        "PERIOD_MISMATCH",
        "ENTITY_MISMATCH",
        "UNIT_MISMATCH",
        "UNSUPPORTED",
        "NUMERIC_MISMATCH",
        "INSUFFICIENT_EVIDENCE",
    }
    if reason and reason not in recoverable_reasons:
        return False

    if reason in {"NUMERIC_MISMATCH", "UNSUPPORTED"} and numeric_match:
        return False

    if reason == "INSUFFICIENT_EVIDENCE":
        if _is_unanswerable_case(case):
            return False
        if numeric_match:
            return False

    return True


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
    h1_config: dict[str, Any] | None = None,
    h3_layers: list[dict[str, Any]] | None = None,
    h3_reviewer_model: str | None = None,
    force_contextual_baseline: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> FinancialWorkflowResult:
    _emit_progress(progress_callback, case.case_id, "workflow", "started", {"batch": False})

    baseline_only = not (use_h1_retrieval or use_h2_numeric_guard or use_h3_chronology_guard or use_h4_verifier)
    if baseline_only:
        if force_contextual_baseline:
            context = _compact_context(report_text, case.question)
            raw = _query_llm_with_process(
                "baseline_single_answer_contextual",
                build_baseline_prompt(case.question, context),
                model=model,
                temperature=temperature,
            )
        else:
            raw = _query_llm_with_process(
                "baseline_single_answer",
                _build_independent_baseline_prompt(case.question),
                model=model,
                temperature=temperature,
            )
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
        cfg = h1_config or {}
        retrieval_top_k = int(cfg.get("top_k", 6) or 6)
        retrieval_keywords_cfg = cfg.get("evidence_keywords")
        if not isinstance(retrieval_keywords_cfg, list):
            retrieval_keywords_cfg = None
        retrieval_keywords = _merge_keywords(retrieval_keywords_cfg, case.evidence_keywords)
        chunks, context = build_retrieval_context(
            report_text,
            case.question,
            top_k=_effective_retrieval_top_k(max(1, min(retrieval_top_k, 20)), case),
            evidence_keywords=retrieval_keywords,
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
    if use_h2_numeric_guard:
        numeric_hint = build_numeric_hint(report_text, case, top_k=3)
        if numeric_hint:
            hint_blocks.append(numeric_hint)

    if use_h2_numeric_guard and not _use_relaxed_h2_prompt(case):
        messages = build_h2_prompt(case.question, context, hint_block="\n\n".join(hint_blocks))
    else:
        messages = build_baseline_prompt(case.question, context)
    raw = _query_llm_with_process("primary_answer", messages, model=model, temperature=temperature)
    answer, citations = _parse_answer(raw)
    _emit_progress(progress_callback, case.case_id, "llm_answer", "completed", {"batch": False})

    diagnostics: dict[str, Any] = {
        "retrieved_chunks": len(chunks) if use_h1_retrieval else 0,
    }

    if use_h2_numeric_guard:
        diagnostics["numeric"] = numeric_guard(answer, case)
        canonical_answer = canonicalize_numeric_answer(answer, case)
        if canonical_answer != answer:
            answer = canonical_answer
            diagnostics["numeric"] = numeric_guard(answer, case)
            diagnostics["numeric"]["canonicalized"] = True
        _emit_progress(
            progress_callback,
            case.case_id,
            "h2_numeric_guard",
            "completed",
            diagnostics["numeric"],
        )
    else:
        diagnostics["numeric"] = {"numeric_match": None, "unit_warning": False}

    text_canonical_answer = canonicalize_text_answer(answer, case)
    if text_canonical_answer != answer:
        answer = text_canonical_answer
        diagnostics["text_canonicalized"] = True

    if use_h3_chronology_guard:
        diagnostics["chronology_ok"] = chronology_guard(answer, case, report_text)
    else:
        diagnostics["chronology_ok"] = None

    if use_h3_chronology_guard:
        layers = _normalize_h3_layers(
            h3_layers,
            h3_reviewer_model,
            model,
            default_batch=1,
        )
        pre_h3_numeric = numeric_guard(answer, case)
        h3_review: dict[str, Any] = {
            "reviewer_layers": layers,
            "revision_applied": False,
        }
        judge_answer = ""
        for idx, layer in enumerate(layers, start=1):
            reviewer_model = str(layer["model"])
            judge_prompt, revise_prompt = build_h3_review_prompts(
                question=case.question,
                context=context,
                draft_answer=answer,
                draft_citations=citations,
            )
            judge_raw = _query_llm_with_process(
                f"h3_judge_layer_{idx}",
                judge_prompt,
                model=reviewer_model,
                temperature=0.0,
            )
            judge_answer, _ = _parse_answer(judge_raw)
            h3_review["judge_result"] = judge_answer
            h3_review["judge_raw"] = judge_raw
            h3_review["reviewer_model"] = reviewer_model
            h3_review["layer_index"] = idx
            _emit_progress(
                progress_callback,
                case.case_id,
                "h3_chronology_guard",
                "completed",
                {
                    "judge_result": judge_answer,
                    "layer_index": idx,
                    "layer_model": reviewer_model,
                },
            )
            if _should_apply_h3_revision(judge_answer, case, pre_h3_numeric):
                revise_raw = _query_llm_with_process(
                    f"h3_revision_layer_{idx}",
                    revise_prompt,
                    model=reviewer_model,
                    temperature=0.0,
                )
                revised_answer, revised_citations = _parse_answer(revise_raw)
                if revised_answer:
                    answer = revised_answer
                if revised_citations:
                    citations = revised_citations
                h3_review["revision_applied"] = True
                h3_review["revise_raw"] = revise_raw
                _emit_progress(
                    progress_callback,
                    case.case_id,
                    "h3_revision",
                    "completed",
                    {
                        "revision_applied": True,
                        "layer_index": idx,
                        "layer_model": reviewer_model,
                    },
                )
                continue
            break

        diagnostics["h3_review"] = h3_review
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
            allow_insufficient=_is_unanswerable_case(case),
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
                allow_insufficient=_is_unanswerable_case(case),
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
    h1_config: dict[str, Any] | None = None,
    h3_layers: list[dict[str, Any]] | None = None,
    h3_reviewer_model: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[FinancialWorkflowResult]:
    if not cases:
        return []

    baseline_only = not (use_h1_retrieval or use_h2_numeric_guard or use_h3_chronology_guard or use_h4_verifier)
    if baseline_only:
        batch_items = [
            {
                "case_id": case.case_id,
                "question": case.question,
                "hint_block": "",
                "context": "",
            }
            for case in cases
        ]
        for case in cases:
            _emit_progress(progress_callback, case.case_id, "llm_batch", "started", {"batch": True})

        raw = _query_llm_with_process(
            "baseline_batch_answer",
            build_batch_prompt(batch_items, strict=False),
            model=model,
            temperature=temperature,
        )
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
    case_by_id: dict[str, FinancialEvalCase] = {case.case_id: case for case in cases}
    context_by_case_id: dict[str, str] = {}
    cfg = h1_config or {}
    retrieval_top_k = max(1, min(int(cfg.get("top_k", 6) or 6), 20))
    retrieval_keywords_cfg = cfg.get("evidence_keywords")
    if not isinstance(retrieval_keywords_cfg, list):
        retrieval_keywords_cfg = None
    for case in cases:
        effective_top_k = _effective_retrieval_top_k(retrieval_top_k, case)
        effective_keywords = _merge_keywords(retrieval_keywords_cfg, case.evidence_keywords)
        if use_h1_retrieval:
            _, context = build_retrieval_context(
                report_text,
                case.question,
                top_k=effective_top_k,
                evidence_keywords=effective_keywords,
            )
        else:
            context = _compact_context(report_text, case.question)

        cap = 4200 if (_is_arithmetic_case(case) or _is_timeline_case(case)) else _BATCH_CONTEXT_CHARS_PER_CASE
        if len(context) > cap:
            context = context[:cap]

        hint_blocks: list[str] = []
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

    strict_items: list[dict[str, str]] = []
    relaxed_items: list[dict[str, str]] = []
    if use_h2_numeric_guard:
        for item in batch_items:
            case = case_by_id.get(item["case_id"])
            if case is not None and _use_relaxed_h2_prompt(case):
                relaxed_items.append(item)
            else:
                strict_items.append(item)
    else:
        relaxed_items = batch_items

    for case in cases:
        _emit_progress(progress_callback, case.case_id, "llm_batch", "started", {"batch": True})

    raw_parts: list[str] = []
    parsed_rows: list[dict[str, Any]] = []
    if strict_items:
        strict_raw = _query_llm_with_process(
            "batch_primary_answer_strict",
            build_batch_prompt(strict_items, strict=True),
            model=model,
            temperature=temperature,
        )
        raw_parts.append(strict_raw)
        parsed_rows.extend(extract_json_array(strict_raw))
    if relaxed_items:
        relaxed_raw = _query_llm_with_process(
            "batch_primary_answer_relaxed",
            build_batch_prompt(relaxed_items, strict=False),
            model=model,
            temperature=temperature,
        )
        raw_parts.append(relaxed_raw)
        parsed_rows.extend(extract_json_array(relaxed_raw))

    raw = "\n\n".join(raw_parts)
    by_id: dict[str, dict[str, Any]] = {}
    for row in parsed_rows:
        key = str(row.get("case_id", "")).strip()
        if key:
            by_id[key] = row

    judge_by_case: dict[str, str] = {}
    draft_by_case: dict[str, tuple[str, list[str]]] = {}
    revised_by_case: dict[str, tuple[str, list[str], str]] = {}
    effective_h3_layers: list[dict[str, Any]] = []
    pre_h3_numeric_by_case: dict[str, dict[str, Any]] = {}
    if use_h3_chronology_guard:
        layers = _normalize_h3_layers(
            h3_layers,
            h3_reviewer_model,
            model,
            default_batch=max(1, min(len(cases), 8)),
        )
        effective_h3_layers = layers

        for idx, case in enumerate(cases):
            row = by_id.get(case.case_id)
            if row is None and idx < len(parsed_rows):
                row = parsed_rows[idx]

            draft_answer = ""
            draft_citations: list[str] = []
            if isinstance(row, dict):
                draft_answer = str(row.get("answer", "")).strip()
                raw_citations = row.get("citations", [])
                if isinstance(raw_citations, list):
                    draft_citations = [str(c).strip() for c in raw_citations if str(c).strip()]
                elif isinstance(raw_citations, str):
                    draft_citations = [c.strip() for c in raw_citations.split(";") if c.strip()]

            draft_by_case[case.case_id] = (draft_answer, draft_citations)
            pre_h3_numeric_by_case[case.case_id] = numeric_guard(draft_answer, case)

        pending_case_ids = [case.case_id for case in cases]
        case_by_id = {case.case_id: case for case in cases}

        for layer_index, layer in enumerate(layers, start=1):
            if not pending_case_ids:
                break
            layer_model = str(layer["model"])
            layer_batch = int(layer["batch_size"])

            for chunk_ids in _chunk_list(pending_case_ids, layer_batch):
                judge_items: list[dict[str, str]] = []
                for case_id in chunk_ids:
                    case = case_by_id[case_id]
                    draft_answer, draft_citations = draft_by_case.get(case_id, ("", []))
                    judge_items.append(
                        {
                            "case_id": case.case_id,
                            "question": case.question,
                            "context": context_by_case_id.get(case.case_id, report_text),
                            "draft_answer": draft_answer,
                            "draft_citations": "; ".join(draft_citations) if draft_citations else "NONE",
                        }
                    )
                    _emit_progress(
                        progress_callback,
                        case.case_id,
                        "h3_batch_judge",
                        "started",
                        {
                            "batch": True,
                            "layer_index": layer_index,
                            "layer_model": layer_model,
                            "layer_batch_size": layer_batch,
                        },
                    )

                judge_raw = _query_llm_with_process(
                    f"h3_batch_judge_layer_{layer_index}",
                    build_h3_batch_judge_prompt(judge_items),
                    model=layer_model,
                    temperature=0.0,
                )
                judge_rows = extract_json_array(judge_raw)
                mapped: dict[str, str] = {}
                for row in judge_rows:
                    key = str(row.get("case_id", "")).strip()
                    judge = str(row.get("judge", "")).strip()
                    if key and judge:
                        mapped[key] = judge

                for idx, case_id in enumerate(chunk_ids):
                    if case_id in mapped:
                        judge_by_case[case_id] = mapped[case_id]
                    elif idx < len(judge_rows):
                        fallback = judge_rows[idx]
                        if isinstance(fallback, dict):
                            judge_by_case[case_id] = str(fallback.get("judge", "")).strip()
                    _emit_progress(
                        progress_callback,
                        case_id,
                        "h3_batch_judge",
                        "completed",
                        {
                            "judge_result": judge_by_case.get(case_id, ""),
                            "layer_index": layer_index,
                            "layer_model": layer_model,
                            "layer_batch_size": layer_batch,
                        },
                    )

            failed_case_ids = [
                case_id
                for case_id in pending_case_ids
                if _should_apply_h3_revision(
                    judge_by_case.get(case_id, ""),
                    case_by_id[case_id],
                    pre_h3_numeric_by_case.get(case_id),
                )
            ]

            for chunk_ids in _chunk_list(failed_case_ids, layer_batch):
                if not chunk_ids:
                    continue
                revision_items: list[dict[str, str]] = []
                for case_id in chunk_ids:
                    case = case_by_id[case_id]
                    draft_answer, draft_citations = draft_by_case.get(case_id, ("", []))
                    revision_items.append(
                        {
                            "case_id": case.case_id,
                            "question": case.question,
                            "context": context_by_case_id.get(case.case_id, report_text),
                            "draft_answer": draft_answer,
                            "draft_citations": "; ".join(draft_citations) if draft_citations else "NONE",
                        }
                    )
                    _emit_progress(
                        progress_callback,
                        case.case_id,
                        "h3_batch_revision",
                        "started",
                        {
                            "batch": True,
                            "layer_index": layer_index,
                            "layer_model": layer_model,
                            "layer_batch_size": layer_batch,
                        },
                    )

                revise_raw = _query_llm_with_process(
                    f"h3_batch_revision_layer_{layer_index}",
                    build_h3_batch_revision_prompt(revision_items),
                    model=layer_model,
                    temperature=0.0,
                )
                revise_rows = extract_json_array(revise_raw)
                revised_chunk: dict[str, tuple[str, list[str], str]] = {}
                for row in revise_rows:
                    key = str(row.get("case_id", "")).strip()
                    if not key:
                        continue
                    rev_answer = str(row.get("answer", "")).strip()
                    rev_citations: list[str] = []
                    raw_citations = row.get("citations", [])
                    if isinstance(raw_citations, list):
                        rev_citations = [str(c).strip() for c in raw_citations if str(c).strip()]
                    elif isinstance(raw_citations, str):
                        rev_citations = [c.strip() for c in raw_citations.split(";") if c.strip()]
                    revised_chunk[key] = (
                        rev_answer,
                        rev_citations,
                        json.dumps({"layer": layer_index, "row": row}, ensure_ascii=False),
                    )

                for idx, case_id in enumerate(chunk_ids):
                    if case_id in revised_chunk:
                        revised_by_case[case_id] = revised_chunk[case_id]
                    elif idx < len(revise_rows):
                        row = revise_rows[idx]
                        if isinstance(row, dict):
                            rev_answer = str(row.get("answer", "")).strip()
                            raw_citations = row.get("citations", [])
                            rev_citations: list[str] = []
                            if isinstance(raw_citations, list):
                                rev_citations = [str(c).strip() for c in raw_citations if str(c).strip()]
                            elif isinstance(raw_citations, str):
                                rev_citations = [c.strip() for c in raw_citations.split(";") if c.strip()]
                            revised_by_case[case_id] = (
                                rev_answer,
                                rev_citations,
                                json.dumps({"layer": layer_index, "row": row}, ensure_ascii=False),
                            )

                    revised = revised_by_case.get(case_id)
                    if revised:
                        rev_answer, rev_citations, _ = revised
                        draft_by_case[case_id] = (rev_answer or draft_by_case.get(case_id, ("", []))[0], rev_citations)
                        base = by_id.get(case_id)
                        if not isinstance(base, dict):
                            base = {"case_id": case_id}
                        if rev_answer:
                            base["answer"] = rev_answer
                        if rev_citations:
                            base["citations"] = rev_citations
                        by_id[case_id] = base

                    _emit_progress(
                        progress_callback,
                        case_id,
                        "h3_batch_revision",
                        "completed",
                        {
                            "revision_applied": case_id in revised_by_case,
                            "layer_index": layer_index,
                            "layer_model": layer_model,
                            "layer_batch_size": layer_batch,
                        },
                    )

            pending_case_ids = failed_case_ids

    results: list[FinancialWorkflowResult] = []
    for idx, case in enumerate(cases):
        row = by_id.get(case.case_id)
        if row is None and not use_h2_numeric_guard and idx < len(parsed_rows):
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
            "retrieved_chunks": retrieval_top_k if use_h1_retrieval else 0,
        }

        if use_h2_numeric_guard:
            diagnostics["numeric"] = numeric_guard(answer, case)
            canonical_answer = canonicalize_numeric_answer(answer, case)
            if canonical_answer != answer:
                answer = canonical_answer
                diagnostics["numeric"] = numeric_guard(answer, case)
                diagnostics["numeric"]["canonicalized"] = True
            _emit_progress(
                progress_callback,
                case.case_id,
                "h2_numeric_guard",
                "completed",
                diagnostics["numeric"],
            )
        else:
            diagnostics["numeric"] = {"numeric_match": None, "unit_warning": False}

        text_canonical_answer = canonicalize_text_answer(answer, case)
        if text_canonical_answer != answer:
            answer = text_canonical_answer
            diagnostics["text_canonicalized"] = True

        if use_h3_chronology_guard:
            diagnostics["chronology_ok"] = chronology_guard(answer, case, report_text)
        else:
            diagnostics["chronology_ok"] = None

        if use_h3_chronology_guard:
            judge_answer = judge_by_case.get(case.case_id, "")
            h3_review: dict[str, Any] = {
                "reviewer_model": h3_reviewer_model or model,
                "reviewer_layers": effective_h3_layers,
                "judge_result": judge_answer,
            }
            diagnostics["h3_review"] = h3_review
            _emit_progress(
                progress_callback,
                case.case_id,
                "h3_chronology_guard",
                "completed",
                {"judge_result": judge_answer},
            )
            if judge_answer.upper().startswith("FAIL"):
                revised = revised_by_case.get(case.case_id)
                if revised is not None:
                    revised_answer, revised_citations, revised_raw = revised
                    if revised_answer:
                        answer = revised_answer
                    if revised_citations:
                        citations = revised_citations
                    h3_review["revision_applied"] = True
                    h3_review["revise_raw"] = revised_raw
                else:
                    h3_review["revision_applied"] = False
                _emit_progress(
                    progress_callback,
                    case.case_id,
                    "h3_revision_apply",
                    "completed",
                    {"revision_applied": h3_review["revision_applied"]},
                )
            else:
                h3_review["revision_applied"] = False
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
                allow_insufficient=_is_unanswerable_case(case),
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
                    allow_insufficient=_is_unanswerable_case(case),
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
