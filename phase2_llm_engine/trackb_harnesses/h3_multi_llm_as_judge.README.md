# h3_multi_llm_as_judge.py

Purpose: H3 judge/revision prompt builders and chronology check.

Main functions:

- build_h3_review_prompts(...)
- build_h3_batch_judge_prompt(items)
- build_h3_batch_revision_prompt(items)
- chronology_guard(answer, case, report_text)

Design:

- Keeps batch setup for judge/revision paths.
- Judge output JSON keys: case_id, judge, citations.
- Revision output JSON keys: case_id, answer, citations.

Used by:

- phase2_llm_engine/financial_trackb_workflow.py
- phase2_llm_engine/trackb_harnesses/workflow.py
