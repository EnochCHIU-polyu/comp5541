# h0_baseline_prompt.py

Purpose: baseline prompt/parsing utilities for Track B generation.

Main functions:

- build_baseline_prompt(question, context)
- build_batch_prompt(batch_items, strict=False)
- parse_answer(raw)
- extract_json_array(raw)

Used by:

- phase2_llm_engine/financial_trackb_workflow.py

Notes:

- Keep output contracts stable because downstream parsing relies on them.
- Batch JSON shape is consumed by extract_json_array and workflow mapping by case_id.
