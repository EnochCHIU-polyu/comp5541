# h1_code_base.py

Purpose: deterministic retrieval harness (H1) for question-focused context selection.

Main functions:

- retrieve_chunks(report_text, question, top_k=5, evidence_keywords=None)
- build_retrieval_context(report_text, question, top_k=5, evidence_keywords=None)

Design:

- Block-based lexical scoring with keyword boosts.
- Optional keyword windows around evidence lines.
- Deterministic deduplication and stable ordering.

Used by:

- phase2_llm_engine/financial_trackb_workflow.py
- phase2_llm_engine/trackb_harnesses/workflow.py
- phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.py
