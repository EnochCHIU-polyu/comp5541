# h2_prompt_base.py

Purpose: H2 prompt rules and prompt-side hint construction.

Main functions:

- build_h2_prompt(question, context, hint_block='')
- build_numeric_hint(report_text, case, top_k=3)

Design:

- Strict answer contract with anti-hallucination guidance.
- Numeric hint extraction from likely evidence lines.
- Deterministic numeric/unit verification is owned by H4.

Used by:

- phase2_llm_engine/financial_trackb_workflow.py
- phase2_llm_engine/trackb_harnesses/workflow.py
