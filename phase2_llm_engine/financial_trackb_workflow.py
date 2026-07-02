"""
Phase 2 - LLM Engine: Track B financial-report workflow.

Implements:
- V0 baseline: one LLM call over full report
- Harnesses:
  H1 retrieval (chunk + fetch relevant sections)
  H2 numeric/unit guard and deterministic arithmetic checks
  H3 chronology consistency check
  H4 skeptical verifier pass
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
from phase2_llm_engine.llm_client import query_llm

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_CHARS = int(os.getenv("TRACKB_MAX_CONTEXT_CHARS", "18000"))


@dataclass
class WorkflowResult:
    case_id: str
    question: str
    answer: str
    citations: list[str]
    confidence: float
    evidence_used: list[str]
    diagnostics: dict
    harness_flags: dict
    raw_response: str


_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")


def _clean_json_block(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_response_json(raw: str) -> tuple[str, list[str], float]:
    cleaned = _clean_json_block(raw)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return raw.strip(), [], 0.35
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return raw.strip(), [], 0.35

    answer = str(obj.get("answer", "")).strip()
    citations = [str(x).strip() for x in obj.get("citations", []) if str(x).strip()]
    confidence = float(obj.get("confidence", 0.5) or 0.5)
    if not answer:
        answer = raw.strip()
    return answer, citations, min(1.0, max(0.0, confidence))


def _parse_json_object_safely(raw: str) -> dict:
    """Best-effort JSON object parsing from model output without raising."""
    cleaned = _clean_json_block(raw)

    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass

    # Try non-greedy JSON object slices and return first valid dict.
    for m in re.finditer(r"\{.*?\}", cleaned, re.DOTALL):
        candidate = m.group(0)
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    return {}


def _split_chunks(report_text: str, max_chars: int = 2600) -> list[str]:
    lines = report_text.splitlines()
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    for line in lines:
        is_heading = bool(re.match(r"^\s*\d+(?:\.\d+)*\s+", line)) or line.strip().startswith("##")
        if is_heading and cur and cur_len > max_chars // 2:
            chunks.append("\n".join(cur).strip())
            cur = []
            cur_len = 0

        cur.append(line)
        cur_len += len(line) + 1
        if cur_len >= max_chars:
            chunks.append("\n".join(cur).strip())
            cur = []
            cur_len = 0

    if cur:
        chunks.append("\n".join(cur).strip())

    return [c for c in chunks if c]


def _keyword_overlap_score(text: str, query: str) -> int:
    q_tokens = {t for t in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", query.lower())}
    if not q_tokens:
        return 0
    low = text.lower()
    return sum(1 for t in q_tokens if t in low)


def _retrieve_chunks(report_text: str, question: str, top_k: int = 4) -> list[str]:
    chunks = _split_chunks(report_text)
    if not chunks:
        return []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(max_features=8192, ngram_range=(1, 2), min_df=1)
        mat = vec.fit_transform(chunks + [question])
        sims = cosine_similarity(mat[-1], mat[:-1]).ravel()
        idx = sims.argsort()[::-1][:top_k]
        return [chunks[i] for i in idx if 0 <= i < len(chunks)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("TF-IDF retrieval unavailable, fallback to keyword overlap: %s", exc)

    ranked = sorted(chunks, key=lambda c: _keyword_overlap_score(c, question), reverse=True)
    return ranked[:top_k]


def _detect_unit_multiplier(text: str) -> float:
    t = text.lower()
    if "人民幣千元" in text or "rmb thousand" in t or "thousand" in t:
        return 1_000.0
    if "人民幣百萬元" in text or "rmb million" in t or "million" in t:
        return 1_000_000.0
    if "萬元" in text:
        return 10_000.0
    if "億元" in text:
        return 100_000_000.0
    return 1.0


def _extract_numbers(text: str) -> list[str]:
    return [m.group(0) for m in _NUM_RE.finditer(text)]


def _to_float(num_text: str) -> Optional[float]:
    raw = num_text.strip().replace(",", "")
    pct = raw.endswith("%")
    if pct:
        raw = raw[:-1]
    if not raw:
        return None
    if raw.startswith("(") and raw.endswith(")"):
        raw = f"-{raw[1:-1]}"
    try:
        val = float(raw)
    except ValueError:
        return None
    if pct:
        return val / 100.0
    return val


def _safe_eval(expr: str) -> Optional[float]:
    if not expr.strip():
        return None

    allowed = {
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.Load,
        ast.Mod,
    }

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if type(node) not in allowed:  # noqa: E721
            return None

    try:
        result = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, {})
    except Exception:  # noqa: BLE001
        return None

    if isinstance(result, (int, float)) and math.isfinite(result):
        return float(result)
    return None


def _numeric_guard(answer: str, case: FinancialEvalCase) -> dict:
    diag = {
        "unit_multiplier": 1.0,
        "answer_numbers": [],
        "case_expected_float": None,
        "arith_expected": None,
        "numeric_match": None,
        "unit_warning": False,
    }

    diag["unit_multiplier"] = _detect_unit_multiplier(case.expected_unit)

    answer_nums = _extract_numbers(answer)
    diag["answer_numbers"] = answer_nums

    expected_float = _to_float(case.expected_answer)
    diag["case_expected_float"] = expected_float

    if case.arithmetic_expression:
        diag["arith_expected"] = _safe_eval(case.arithmetic_expression)

    cand_vals = [v for v in (_to_float(x) for x in answer_nums) if v is not None]
    expected_candidates = [x for x in [expected_float, diag["arith_expected"]] if x is not None]

    if cand_vals and expected_candidates:
        tol = max(case.tolerance, 1e-9)
        diag["numeric_match"] = any(abs(cv - ev) <= tol for cv in cand_vals for ev in expected_candidates)
    else:
        diag["numeric_match"] = None

    if case.expected_unit and case.expected_unit.lower() not in answer.lower():
        diag["unit_warning"] = True

    return diag


def _check_event_order(answer: str, expected_order: list[str]) -> bool | None:
    if not expected_order:
        return None
    low = answer.lower()
    positions = []
    for token in expected_order:
        p = low.find(token.lower())
        if p == -1:
            return False
        positions.append(p)
    return positions == sorted(positions)


def _build_answer_prompt(question: str, context: str) -> list[dict]:
    sys = (
        "You are a financial-report audit assistant. "
        "Answer ONLY from the provided report context. "
        "Do not invent facts. If uncertain, say UNKNOWN."
    )
    user = (
        "Use this JSON schema exactly: "
        '{"answer": "...", "citations": ["section or line phrase"], "confidence": 0.0}\n\n'
        "Question:\n"
        f"{question}\n\n"
        "Context:\n"
        f"{context}"
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def _shrink_context(context: str, max_chars: int = DEFAULT_MAX_CONTEXT_CHARS) -> str:
    """Shrink long context while preserving both opening and closing report sections."""
    if len(context) <= max_chars:
        return context
    half = max_chars // 2
    return (
        context[:half]
        + "\n\n[... CONTEXT TRUNCATED FOR TOKEN LIMIT ...]\n\n"
        + context[-half:]
    )


def _is_context_too_long_error(exc: Exception) -> bool:
    """Detect context limit errors even when wrapped by higher-level RuntimeError."""
    texts = [str(exc).lower()]
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        texts.append(str(cause).lower())
    joined = "\n".join(texts)
    return "context_length_exceeded" in joined or "too long" in joined


def _query_with_context_fallback(
    question: str,
    context: str,
    query_fn: Callable,
    model: Optional[str],
    temperature: float,
) -> tuple[str, str]:
    """Query the model and progressively shrink context when limits are exceeded."""
    budgets = [None, DEFAULT_MAX_CONTEXT_CHARS, 12000, 8000, 5000]
    last_exc: Exception | None = None

    for budget in budgets:
        candidate_context = context if budget is None else _shrink_context(context, budget)
        messages = _build_answer_prompt(question, candidate_context)
        try:
            return query_fn(messages, model=model, temperature=temperature), candidate_context
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_context_too_long_error(exc):
                raise
            logger.warning(
                "Context too long, retrying with smaller budget (budget=%s, chars=%d)",
                str(budget) if budget is not None else "full",
                len(candidate_context),
            )

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("LLM query failed with unknown context fallback error")


def _build_verify_prompt(question: str, answer: str, context: str) -> list[dict]:
    sys = "You are a skeptical verifier. Reject unsupported financial claims."
    user = (
        "Return JSON only: "
        '{"verified": true, "revised_answer": "...", "reason": "...", "confidence": 0.0}\n\n'
        f"Question:\n{question}\n\n"
        f"Candidate answer:\n{answer}\n\n"
        f"Evidence context:\n{context}"
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def run_financial_workflow(
    report_text: str,
    case: FinancialEvalCase,
    model: Optional[str] = None,
    temperature: float = 0.0,
    query_fn: Callable = query_llm,
    use_h1_retrieval: bool = False,
    use_h2_numeric_guard: bool = False,
    use_h3_chronology_guard: bool = False,
    use_h4_verifier: bool = False,
) -> WorkflowResult:
    """
    Execute baseline or harness-enhanced workflow for one financial QA case.
    """
    harness_flags = {
        "h1_retrieval": use_h1_retrieval,
        "h2_numeric_guard": use_h2_numeric_guard,
        "h3_chronology_guard": use_h3_chronology_guard,
        "h4_verifier": use_h4_verifier,
    }

    context_chunks = [report_text]
    if use_h1_retrieval:
        context_chunks = _retrieve_chunks(report_text, case.question, top_k=4)
        if not context_chunks:
            context_chunks = [report_text]

    context = "\n\n---\n\n".join(context_chunks)
    raw, context = _query_with_context_fallback(
        question=case.question,
        context=context,
        query_fn=query_fn,
        model=model,
        temperature=temperature,
    )
    answer, citations, confidence = _parse_response_json(raw)

    diagnostics: dict = {
        "retrieved_chunks": len(context_chunks),
        "numeric": {},
        "chronology_ok": None,
        "verification": {"applied": False, "verified": None, "reason": ""},
    }

    if use_h2_numeric_guard:
        diagnostics["numeric"] = _numeric_guard(answer, case)

    if use_h3_chronology_guard:
        diagnostics["chronology_ok"] = _check_event_order(answer, case.expected_event_order or [])

    if use_h4_verifier:
        verify_messages = _build_verify_prompt(case.question, answer, context)
        try:
            verify_raw = query_fn(verify_messages, model=model, temperature=0.0)
        except Exception as exc:  # noqa: BLE001
            if not _is_context_too_long_error(exc):
                raise
            short_context = _shrink_context(context, max_chars=12000)
            verify_messages = _build_verify_prompt(case.question, answer, short_context)
            try:
                verify_raw = query_fn(verify_messages, model=model, temperature=0.0)
            except Exception as exc2:  # noqa: BLE001
                if not _is_context_too_long_error(exc2):
                    raise
                tiny_context = _shrink_context(context, max_chars=7000)
                verify_messages = _build_verify_prompt(case.question, answer, tiny_context)
                verify_raw = query_fn(verify_messages, model=model, temperature=0.0)
        diagnostics["verification"]["applied"] = True

        obj = _parse_json_object_safely(verify_raw)

        verified = bool(obj.get("verified", False))
        revised = str(obj.get("revised_answer", "")).strip()
        reason = str(obj.get("reason", "")).strip()
        vconf = float(obj.get("confidence", confidence) or confidence)

        diagnostics["verification"] = {
            "applied": True,
            "verified": verified,
            "reason": reason,
        }

        if verified and revised:
            answer = revised
            confidence = min(1.0, max(0.0, vconf))

    return WorkflowResult(
        case_id=case.case_id,
        question=case.question,
        answer=answer,
        citations=citations,
        confidence=confidence,
        evidence_used=context_chunks,
        diagnostics=diagnostics,
        harness_flags=harness_flags,
        raw_response=raw,
    )


def workflow_result_to_dict(result: WorkflowResult) -> dict:
    return asdict(result)
