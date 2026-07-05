# workflow.py

Purpose: local ablation workflow helper for harness experimentation.

Main functions:

- configure_runtime(report_text, cases)
- call_llm(prompt) # deterministic mock for local harness tests
- run_workflow(query, use_h1=False, use_h2=False, use_h3=False, use_h4=False)

Notes:

- This is not the production API workflow path.
- Production orchestration is in phase2_llm_engine/financial_trackb_workflow.py.
