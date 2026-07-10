# h3_multi_llm_as_judge.py

## Purpose

H3 provides post-generation review prompt builders and a deterministic chronology check.

It does not execute model calls itself; it only builds prompt messages and exposes chronology_guard.

## Public API

- build_h3_review_prompts(question, context, draft_answer, draft_citations, expected_unit='', evidence_keywords=None) -> tuple[list[dict[str, str]], list[dict[str, str]]]
- build_h3_batch_judge_prompt(items) -> list[dict[str, str]]
- build_h3_batch_revision_prompt(items) -> list[dict[str, str]]
- chronology_guard(answer, case, report_text) -> bool | None

## Prompt Builder Contracts

Single-case review prompts:

- judge prompt asks for PASS/FAIL with short reason code and supporting snippets
- revision prompt asks for a conservative corrected answer + citations

Batch prompts require strict JSON-only output.

Expected batch judge item shape:

- case_id
- judge
- citations

Expected batch revision item shape:

- case_id
- answer
- citations

## chronology_guard Semantics

chronology_guard checks ordering in the model answer, not report order.

- Returns None when case.expected_event_order is empty.
- Returns False if any expected token is missing from normalized answer.
- Returns True only when token positions are non-decreasing.

report_text is accepted for interface compatibility but is not used in the current chronology logic.

## Determinism And Limits

- Prompt builders are deterministic string assembly.
- chronology_guard is deterministic token-order checking.
- Matching is normalization + substring based, so paraphrases may fail.

## Current Integration

- Used by phase2_llm_engine/trackb_harnesses/workflow.py:
	- build_h3_review_prompts drives judge/revise calls
	- chronology_guard emits chronology diagnostic
