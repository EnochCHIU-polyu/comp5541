# Track B Harnesses

This directory contains the harness layers used by Track B financial QA.

Harnesses are small, composable controls around generation. They are designed for ablation testing and diagnostics, not as independent models.

Primary orchestration lives in [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py).

## What This Folder Owns

- H0 baseline prompt path
- H1 deterministic retrieval context selection
- H2 strict prompt contract and numeric hint generation
- H3 review/revision prompt builders and chronology check
- H4 deterministic evidence verification and deterministic repair helpers
- Shared workflow state types and a local harness workflow helper

## Canonical File Map

- [phase2_llm_engine/trackb_harnesses/h0_baseline_prompt.py](h0_baseline_prompt.py)
- [phase2_llm_engine/trackb_harnesses/h1_code_base.py](h1_code_base.py)
- [phase2_llm_engine/trackb_harnesses/h2_prompt_base.py](h2_prompt_base.py)
- [phase2_llm_engine/trackb_harnesses/h3_multi_llm_as_judge.py](h3_multi_llm_as_judge.py)
- [phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.py](h4_evidence_verifier.py)
- [phase2_llm_engine/trackb_harnesses/types.py](types.py)
- [phase2_llm_engine/trackb_harnesses/workflow.py](workflow.py)

Per-module docs:

- [phase2_llm_engine/trackb_harnesses/h0_baseline_prompt.README.md](h0_baseline_prompt.README.md)
- [phase2_llm_engine/trackb_harnesses/h1_code_base.README.md](h1_code_base.README.md)
- [phase2_llm_engine/trackb_harnesses/h2_prompt_base.README.md](h2_prompt_base.README.md)
- [phase2_llm_engine/trackb_harnesses/h3_multi_llm_as_judge.README.md](h3_multi_llm_as_judge.README.md)
- [phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.README.md](h4_evidence_verifier.README.md)
- [phase2_llm_engine/trackb_harnesses/types.README.md](types.README.md)
- [phase2_llm_engine/trackb_harnesses/workflow.README.md](workflow.README.md)

## Runtime Toggle Model

In [phase2_llm_engine/financial_trackb_workflow.py](../financial_trackb_workflow.py), harnesses are controlled by:

- use_h1_retrieval
- use_h2_numeric_guard
- use_h3_chronology_guard
- use_h4_verifier

Behavior split:

- No harness enabled: independent baseline prompt path.
- Any harness enabled: context-based generation path with optional harness stages.

## End-to-End Stage Order (Single Case)

1. H1 (optional): build retrieval context from report text.
2. H2 prompt mode (optional): build strict H2 prompt with optional numeric hints.
3. Primary LLM call: parse ANSWER and CITATIONS.
4. H2 numeric diagnostics (optional): run numeric guard diagnostics.
5. H3 chronology and review (optional): chronology diagnostic + judge/revision flow.
6. H4 verification (optional): verify support; if failed, run deterministic repair and re-verify.
7. Return FinancialWorkflowResult with answer, citations, raw response, diagnostics.

## Diagnostics Contract (Current)

Workflow diagnostics currently include:

- retrieved_chunks
- numeric
- chronology_ok
- h3_review
- verification

Keep these keys stable unless you intentionally version downstream consumers.

## Harness Responsibilities

- H1 chooses context.
- H2 shapes prompt contract and emits numeric diagnostics.
- H3 builds judge/revision prompts and performs chronology check.
- H4 verifies support and provides deterministic repair helpers.

Do not move responsibilities across harnesses without updating both docs and evaluation assumptions.

## Evaluation Entry Point

Main runner:

- [scripts/run_financial_trackb.py](../../scripts/run_financial_trackb.py)

Typical quick runs:

```bash
.venv/bin/python scripts/run_financial_trackb.py --mode baseline --max-cases 20 --model deepseek-v4-flash --temperature 0
.venv/bin/python scripts/run_financial_trackb.py --mode all --max-cases 20 --model deepseek-v4-flash --temperature 0
```

## Contributor Rules

- Keep harness logic deterministic unless there is a strong ablation reason.
- Keep modules narrow and testable.
- Add diagnostics rather than silent heuristics.
- Update module README files when behavior, contracts, or diagnostics change.
- Prefer small isolated changes so variant comparisons remain interpretable.
