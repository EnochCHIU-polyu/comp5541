# Track B Harness Design

This directory contains the harness layers that wrap Track B financial QA generation. The harnesses are not separate products or models; they are narrow control layers used by [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py) to shape context, add guardrails, and verify support around an answer pass. Contributors should treat this directory as workflow infrastructure: each harness exists to target one failure class while staying cheap to ablate, debug, and revise independently.

## Clear Split: H0 Baseline vs H1-H4 Harnesses

- `H0` baseline prompt path is isolated in [phase2_llm_engine/trackb_harnesses/h0_baseline_prompt.py](h0_baseline_prompt.py).
- `H1-H4` are additive harnesses that can be toggled independently.
- In workflow:
  - `use_h2_numeric_guard=False` -> baseline prompt path (`H0`) is used.
  - `use_h2_numeric_guard=True` -> structured H2 prompt path is used.

This split is intentional so baseline is not accidentally using H2 prompt engineering.

## Quick Start For Contributors

Read these files first:

- [phase2_llm_engine/trackb_harnesses/h0_baseline_prompt.py](h0_baseline_prompt.py)
- [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py)
- [phase2_llm_engine/trackb_harnesses/h1_retrieval.py](h1_retrieval.py)
- [phase2_llm_engine/trackb_harnesses/h2_numeric_guard.py](h2_numeric_guard.py)
- [phase2_llm_engine/trackb_harnesses/h3_chronology_guard.py](h3_chronology_guard.py)
- [phase2_llm_engine/trackb_harnesses/h4_verifier.py](h4_verifier.py)

Run one small sanity check before changing logic:

```bash
.venv/bin/python scripts/run_financial_trackb.py --mode all --max-cases 1 --model deepseek-v4-flash --temperature 0
```

When you modify a harness, compare a narrow baseline and the affected variant:

```bash
.venv/bin/python scripts/run_financial_trackb.py --mode baseline --max-cases 20 --model deepseek-v4-flash --temperature 0
.venv/bin/python scripts/run_financial_trackb.py --mode all --max-cases 20 --model deepseek-v4-flash --temperature 0
```

## System Design Overview

The Track B workflow keeps the LLM call simple and moves deterministic behavior into harnesses. Orchestration is controlled by four flags in [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py): `use_h1_retrieval`, `use_h2_numeric_guard`, `use_h3_chronology_guard`, and `use_h4_verifier`.

Prompt ownership is explicit:

- H0 owns baseline prompt contract.
- H2 owns structured prompt contract.
- Workflow selects H0 vs H2 via `use_h2_numeric_guard`.

The harness stack is intentionally asymmetric:

- H1 changes the context seen by the model.
- H2 adds prompt hints before generation and diagnostics after generation.
- H3 does post-generation validation on answer ordering only.
- H4 does post-generation support checks and may trigger one revision pass.

This matters for contributors because not every harness is allowed to rewrite the same part of the pipeline. If you move responsibilities across harnesses, you make ablations harder to interpret.

## H1 Retrieval

### Problem It Solves

H1 reduces long-context misses by narrowing the report to chunks that are more likely to contain the answer. It targets the common case where a full-report prompt causes the model to answer from a nearby but wrong disclosure, or from a summary line instead of the exact evidence line.

### Inputs And Outputs

Public functions:

- `retrieve_chunks(report_text, question, top_k=5, evidence_keywords=None) -> list[str]`
- `build_retrieval_context(report_text, question, top_k=5, evidence_keywords=None) -> tuple[list[str], str]`

Inputs:

- `report_text`: full source report as raw text.
- `question`: evaluation question.
- `top_k`: maximum ranked blocks to keep.
- `evidence_keywords`: optional case-level keywords used as a retrieval boost.

Outputs:

- Ordered list of selected chunks.
- Joined context string for prompt injection.

### Internal Design

H1 splits the report into coarse blocks using blank-line structure, not sentence retrieval. It then scores each block by overlap with question tokens and adds a fixed boost for blocks containing evidence keywords. In parallel, it scans report lines for evidence keywords and captures small line windows around those hits. Ranked blocks and keyword windows are merged, normalized, and deduplicated with `OrderedDict`, then joined with `---` separators. If `evidence_keywords` is present, the retrieval context is prefixed with an `Evidence keywords:` line.

Two design choices are deliberate:

- Retrieval is lexical and deterministic. There is no embedding index or learned reranker in this harness.
- Keyword windows are merged ahead of final truncation so direct evidence lines can survive even when block ranking is weak.

### Known Failure Modes

- Question-overlap scoring is shallow and can overvalue repeated surface tokens.
- Evidence keyword boosts can pull in the right region but still miss the exact table row.
- If `evidence_keywords` are too generic, keyword windows become noisy.
- If no block scores above zero, H1 falls back to the first `top_k` blocks, which is safe but often low precision.
- Deduplication is string-based after whitespace normalization, so near-duplicate chunks with meaningful formatting differences may collapse.

### Safe Modification Guidelines

- Keep retrieval deterministic. If you introduce stochastic ranking, you weaken ablation comparisons.
- Preserve both retrieval outputs: selected chunk list and prompt-ready context string.
- If you change scoring, keep keyword boosting and chunk deduplication behavior explicit and testable.
- Do not silently change the retrieval context prefix format unless you also update prompt assumptions in the workflow.
- Prefer small ranking changes over changing chunk granularity and ranking logic at the same time.

## H2 Numeric Guard

### Problem It Solves

H2 addresses numeric drift: wrong scale, wrong number extraction, or answers that paraphrase a nearby figure instead of the exact expected one. It does this in two places: a deterministic hint block before generation, and a deterministic numeric check after generation.

### Inputs And Outputs

Public functions:

- `build_numeric_hint(report_text, case, top_k=3) -> str`
- `numeric_guard(answer, case) -> dict[str, Any]`

Inputs:

- `report_text`: full report text.
- `case`: `FinancialEvalCase`, including `question`, `expected_answer`, `tolerance`, `expected_unit`, and `evidence_keywords`.
- `answer`: parsed model answer string for post-checking.

Outputs:

- A formatted hint block or an empty string.
- A diagnostics dictionary with `numeric_match`, `unit_warning`, `pred_value`, and `expected_value`.

### Internal Design

`build_numeric_hint` ranks report lines by a small deterministic score: evidence keyword hits, question token overlap, and presence of numeric tokens. It selects the top lines, formats them as `Numeric evidence hints:`, optionally appends `Target unit: ...`, and adds an instruction telling the model to preserve the report's exact scale rather than round to a headline approximation.

`numeric_guard` parses the first numeric token from both the answer and `case.expected_answer`. Parsing handles commas and percents, and returns decimal form for percentages. It then compares predicted and expected numeric values when `case.answer_type == "numeric"`, using `max(case.tolerance, 1e-9)` as the tolerance floor. Unit handling is bucket-based rather than exact-string-only: the code infers buckets such as `billion`, `million`, `thousand`, `percent`, `count`, and `currency`, then raises `unit_warning` when expected and answer buckets disagree.

This harness is intentionally limited: it checks the first number only and emits diagnostics instead of mutating the answer.

### Known Failure Modes

- Answers with multiple important numbers are reduced to the first numeric token.
- Unit buckets are coarse and English-centric, with partial Chinese support.
- Percentage normalization converts `12%` to `0.12`, which is correct internally but easy to mishandle if downstream consumers assume display form.
- Cases that encode the right number in a different syntactic shape may still trip `numeric_match` or `unit_warning`.
- If an answer omits a number entirely, H2 can only report the miss; it cannot recover the answer.

### Safe Modification Guidelines

- Keep the contract diagnostic-only. H2 should not start rewriting outputs unless the workflow is explicitly redesigned.
- If you extend numeric parsing, preserve current handling for commas, percents, and empty parses.
- Treat unit buckets as shared semantics. If you add a new bucket, consider whether H4 needs the same notion of unit support.
- Avoid broadening hint generation and numeric verification in one change; they affect different parts of the workflow.
- Validate changes on numeric cases only. Non-numeric cases should continue to return `numeric_match: None`.

## H3 Chronology Guard

### Problem It Solves

H3 catches answers that mention the right events but place them in the wrong order. The harness is deliberately narrow because chronology errors in Track B are often answer-order errors, not retrieval failures.

### Inputs And Outputs

Public function:

- `chronology_guard(answer, case, report_text) -> bool | None`

Inputs:

- `answer`: parsed model answer string.
- `case`: `FinancialEvalCase`, using `expected_event_order` when present.
- `report_text`: full report text.

Output:

- `None` when the case does not specify `expected_event_order`.
- `True` when all expected tokens appear in answer order.
- `False` when a token is missing or appears out of order.

### Internal Design

H3 normalizes text by lowercasing, flattening punctuation separators, and collapsing whitespace. It then searches for each expected event token in the normalized answer and compares token positions against sorted order. The important design constraint is that validation is done against the answer text, not against document order in the report. The `report_text` parameter is accepted by the function signature because the workflow passes it through, but the current logic does not use it.

### Known Failure Modes

- Paraphrases can fail if the expected token text does not appear literally enough after normalization.
- Repeated event names can produce misleading first-match positions.
- H3 validates order only; it does not verify dates, entities, or amounts.
- Cases with incomplete `expected_event_order` definitions will produce weak signals even when the logic is correct.

### Safe Modification Guidelines

- Keep the answer-based validation rule unless the benchmark contract changes.
- If you improve matching, do not silently switch from token-order checking to report-grounded fact checking; that would turn H3 into a different harness.
- Preserve the tri-state return contract. Downstream code relies on `None` meaning "not applicable".
- If you decide to use `report_text` in the future, document the semantic change clearly because it changes what H3 is measuring.

## H4 Verifier

### Problem It Solves

H4 is the skeptical support check. It targets answers that look plausible but are weakly supported, mis-scaled, or backed by citations that do not actually appear in the report. It is also the only current harness that can trigger a second LLM call.

### Inputs And Outputs

Public function:

- `verify_support(answer, citations, report_text, evidence_keywords=None, expected_unit="") -> dict[str, Any]`

Inputs:

- `answer`: parsed `ANSWER` string.
- `citations`: parsed `CITATIONS` list.
- `report_text`: full source report text.
- `evidence_keywords`: optional keyword expectations from the case.
- `expected_unit`: optional expected unit string.

Output:

- A dictionary including `applied`, `verified`, and `reason`.

### Internal Design

H4 is heuristic support checking, not semantic proof. It normalizes report text and then applies several checks:

- Evidence keyword support: if keywords are required, at least one must appear in the report text.
- Unit support: answer units are checked against a bucket inferred from `expected_unit`.
- Citation support: each citation is normalized and tested by containment, then by numeric token support, then by a keyword-overlap fallback threshold.

In the workflow, H4 runs after answer parsing. If the initial verification returns `verified: false`, the workflow sends one revision prompt to `deepseek-v4-flash`, asking for a more skeptical answer grounded in the provided evidence context. The revised answer and citations are then re-verified, and diagnostics record `revision_applied` plus the initial failure reason.

### Known Failure Modes

- Citation support is normalization-based and can reject aggressive paraphrases.
- Unit checking is bucket-level, so semantically close phrasings can still look mismatched.
- Evidence keyword checks only ask whether keywords appear in the report, not whether the answer used the right local evidence.
- Answers with no citations can still pass some support checks if other heuristics succeed.
- The single revision pass may still converge to a wrong but better-formatted answer.

### Safe Modification Guidelines

- Preserve the role split: H4 verifies support; the workflow owns revision policy.
- Keep failure reasons short and machine-readable enough for diagnostics comparison.
- If you tighten citation heuristics, test the revision path as well as the initial verdict.
- If you add new support checks, make sure they degrade to a clear `reason` instead of silent false negatives.
- Avoid coupling H4 to retrieval internals; it should verify the report text and parsed citations, not assume how context was built.

## Orchestration And Data Flow

The workflow entry point is `run_financial_workflow(...)` in [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py).

Execution order:

1. If H1 is enabled, call `build_retrieval_context(report_text, case.question, top_k=6, evidence_keywords=case.evidence_keywords)` and use the returned context instead of the full report.
2. Build prompt hints from `case.evidence_keywords`, `case.expected_unit`, and H2's `build_numeric_hint(...)` when enabled.
3. Query `deepseek-v4-flash` with a prompt that requires exactly two fields: `ANSWER:` and `CITATIONS:`.
4. Parse the raw response into `answer` and `citations`.
5. If H2 is enabled, run `numeric_guard(answer, case)` and store diagnostics.
6. If H3 is enabled, run `chronology_guard(answer, case, report_text)` and store diagnostics.
7. If H4 is enabled, run `verify_support(...)`. If verification fails, run exactly one revision pass, parse the revised output, and verify again.
8. Return a `FinancialWorkflowResult` with answer, citations, raw response, and diagnostics.

Current diagnostics exposed by the workflow:

- `retrieved_chunks`
- `numeric`
- `chronology_ok`
- `verification`

The diagnostics contract is part of the design. Contributors should treat it as stable evaluation output, not incidental logging.

## Evaluation Workflow And Commands

The main experiment runner is [scripts/run_financial_trackb.py](../../scripts/run_financial_trackb.py). It maps `--mode` values to harness flags and writes run artifacts under [phase4_evaluation/results/trackb](../../phase4_evaluation/results/trackb).

Useful modes:

- `baseline`
- `h1`
- `h2`
- `h3`
- `h4`
- `all`
- `all_minus_h1`
- `all_minus_h2`
- `all_minus_h3`
- `all_minus_h4`

Common commands:

```bash
.venv/bin/python scripts/run_financial_trackb.py --mode baseline --model deepseek-v4-flash --temperature 0
.venv/bin/python scripts/run_financial_trackb.py --mode all --model deepseek-v4-flash --temperature 0
.venv/bin/python scripts/run_financial_trackb.py --mode h2 --max-cases 20 --model deepseek-v4-flash --temperature 0
.venv/bin/python scripts/run_financial_trackb.py --mode all_minus_h4 --max-cases 20 --model deepseek-v4-flash --temperature 0
```

Saved outputs per run:

- `predictions.json`: per-case answers, citations, and diagnostics.
- `metrics.json`: aggregate scoring summary plus variant metadata.
- `variant.json`: enabled and disabled harness flags.

For harness work, the standard comparison pattern is:

1. Run `baseline`.
2. Run the single harness mode you changed, or `all` if the change only makes sense in composition.
3. If the harness affects combined behavior, run the relevant leave-one-out mode.
4. Inspect diagnostics before judging aggregate score movement.

## Adding A New Harness (H5+)

Add a new harness only if it owns a failure mode that is not already clearly covered by H1 through H4. The pattern to follow is:

1. Put the harness in this directory as a small module with one clear public contract.
2. Decide whether it is pre-generation, post-generation, or revision-only logic.
3. Add one explicit workflow flag in [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py).
4. Add diagnostics for the harness in the returned workflow result.
5. Add a new runner mode in [scripts/run_financial_trackb.py](../../scripts/run_financial_trackb.py) so contributors can isolate it.
6. Add at least one leave-one-out or single-harness evaluation path if the harness is expected to compose with others.

The design bar for H5+ is not "could this help". It is "can contributors measure its effect without ambiguity".

## Design Principles And Contributor Guardrails

- Keep harnesses narrow. Each harness should own one kind of control signal.
- Preserve deterministic behavior where possible. Reproducible ablations matter more than sophistication.
- Do not move scoring logic into harnesses. Harnesses emit workflow diagnostics; evaluation lives outside.
- Do not hide workflow behavior in helper functions that erase the harness boundary.
- Prefer adding diagnostics over adding silent heuristics.
- If a change affects prompt shape, diagnostics shape, or revision policy, document it in the same change.
- Keep examples and test runs pinned to `deepseek-v4-flash` unless the evaluation contract changes.

If you are unsure where a change belongs, use this split: H1 chooses context, H2 checks numbers, H3 checks order, H4 checks support, and the workflow composes them.
