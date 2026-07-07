# h2_prompt_base.py

## Purpose

H2 defines prompt-side controls for financial QA generation. It does two things:

- build a strict answer-and-citations prompt contract
- add deterministic numeric hints from report lines

## Public API

- build_h2_prompt(question, context, hint_block='') -> list[dict[str, str]]
- build_numeric_hint(report_text, case, top_k=3) -> str

## build_h2_prompt Behavior

Returns system + user messages with strict output format:

- ANSWER: short answer
- CITATIONS: semicolon-separated verbatim snippets

Hard constraints enforced in prompt text include:

- use Context only
- do not invent entities/numbers/units/periods
- preserve exact numeric representation and scale
- if evidence is insufficient, return:
	- ANSWER: INSUFFICIENT_EVIDENCE
	- CITATIONS: NONE

For yes/no questions, prompt requires ANSWER to start with Yes or No.

## build_numeric_hint Behavior

1. Score non-empty report lines using:
	 - question token overlap
	 - optional keyword overlap
	 - numeric token presence
2. Select top lines with positive score, fallback to top scored lines.
3. Return a compact hint block prefixed by Numeric evidence hints.
4. Append a scale-preservation instruction.

If the case is text and question contains yes or no, an additional yes/no hint sentence is appended.

## Determinism And Limits

- Deterministic ranking (no model call).
- Line scoring is lexical and shallow by design.
- This module does not verify model output correctness; verification and repair are handled by H4.

## Current Integration

- Used by phase2_llm_engine/trackb_harnesses/workflow.py before generation.
