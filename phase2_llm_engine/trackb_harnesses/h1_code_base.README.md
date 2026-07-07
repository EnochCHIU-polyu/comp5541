# h1_code_base.py

## Purpose

H1 is a deterministic retrieval harness for financial QA. It selects the most relevant report chunks for a question so downstream prompt building can use a smaller, evidence-focused context.

## Public API

- retrieve_chunks(report_text, question, top_k=5, evidence_keywords=None) -> list[str]
- build_retrieval_context(report_text, question, top_k=5, evidence_keywords=None) -> tuple[list[str], str]

## How It Works

1. Split report text into coarse blocks using blank-line boundaries.
2. Score each block with:
	- lexical overlap against question tokens
	- +2 bonus if any numeric token exists in the block
	- +5 per evidence keyword hit when evidence_keywords is provided
3. Pick highest-scoring blocks (up to top_k). If nothing scores above zero, fall back to the first blocks.
4. Independently collect keyword windows around matching lines (line +/- 1).
5. Merge keyword windows + ranked picks, normalize whitespace, and deduplicate using OrderedDict.
6. Truncate output length to max(top_k, number_of_keyword_windows).

build_retrieval_context joins selected chunks with a separator:

---

and returns both the list of chunks and the joined context string.

## Determinism And Limits

- Fully deterministic (no embeddings, no randomization).
- Retrieval is lexical, so synonym-heavy questions can still miss the best evidence row.
- Deduplication is whitespace-normalized string matching.

## Current Integration

- Used by phase2_llm_engine/trackb_harnesses/workflow.py through build_retrieval_context.
- Used by h4_evidence_verifier.py for fallback citation retrieval in deterministic repair.
