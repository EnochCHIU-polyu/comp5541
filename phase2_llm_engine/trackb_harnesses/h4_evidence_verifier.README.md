# h4_evidence_verifier.py

## Purpose

H4 implements deterministic verification and lightweight repair helpers for Track B answers.

It verifies support quality (citations, units, keyword presence) and can apply non-LLM repairs before re-verification.

## Public API

- verify_support(answer, citations, report_text, evidence_keywords=None, expected_unit='') -> dict[str, Any]
- repair_answer_deterministic(answer, citations, report_text, case) -> tuple[str, list[str], list[str]]
- h2_numeric_guard(answer, case) -> dict[str, Any]

## verify_support Behavior

verify_support returns:

- applied: True
- verified: bool
- reason: semicolon-joined failure reasons

Checks performed:

1. evidence keyword presence in report text (when evidence_keywords provided)
2. unit compatibility between answer and expected_unit (bucket + fallback containment)
3. citation support using normalized containment, numeric token consistency, and word-overlap heuristic

## repair_answer_deterministic Behavior

When called after a failed verification, repair can:

1. convert empty answer to INSUFFICIENT_EVIDENCE
2. add exact-match citation line when answer text appears in report lines
3. fallback to H1 retrieve_chunks for citations when needed
4. append expected_unit to numeric answer when missing

Return values:

- repaired answer
- repaired citations
- list of repair action labels

## h2_numeric_guard Behavior

This helper performs deterministic numeric and unit diagnostics:

- parse first number from answer and expected answer
- numeric match for numeric cases using tolerance floor max(case.tolerance, 1e-9)
- unit_warning based on inferred unit buckets and expected unit text

Returned keys:

- numeric_match
- unit_warning
- pred_value
- expected_value

## Determinism And Limits

- All checks are heuristic and deterministic.
- Citation verification is text-normalization based, not semantic entailment.
- Numeric guard inspects first numeric token only.

## Current Integration

- Used by phase2_llm_engine/trackb_harnesses/workflow.py for:
	- post-generation verification
	- deterministic repair path
	- numeric diagnostics via h2_numeric_guard alias
