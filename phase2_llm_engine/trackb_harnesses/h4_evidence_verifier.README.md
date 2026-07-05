# h4_evidence_verifier.py

Purpose: deterministic evidence verification and lightweight repair helpers.

Main functions:

- verify_support(answer, citations, report_text, evidence_keywords=None, expected_unit='')
- repair_answer_deterministic(answer, citations, report_text, case)

Design:

- Verifies citation support and unit consistency.
- Applies non-LLM repairs (fallback citations, unit append, insufficient-evidence guard).

Used by:

- phase2_llm_engine/financial_trackb_workflow.py
- phase2_llm_engine/trackb_harnesses/workflow.py
