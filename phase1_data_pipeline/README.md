# Phase 1 - Data Pipeline

Phase 1 now serves two different workflows:
1. The Track B financial-report stack.

This README focuses on what is actively in use today and where each module fits.

---

## Module Overview

| File | Role | Used by |
| --- | --- | --- |
| `benchmark_datasets.py` | Loads SmartBugs and SolidiFI benchmark datasets | `main.py`, benchmark scripts, backend benchmark service |
| `contract_normalizer.py` | Cleans and line-numbers Solidity source | smart-contract CLI and evaluation helpers |
| `contract_preprocessor.py` | Token-limit preprocessing for contracts | smart-contract audit pipeline |
| `dataset_loader.py` | Local `.sol` and `.json` contract loading helpers | tests and utility flows |
| `financial_report_dataset.py` | Loads Track B JSONL evaluation cases | Track B runner, workflow, scorer |
| `pdf_to_markdown.py` | Converts PDF reports into markdown files | `scripts/pdf_to_md.py`, `run_pdf_to_md.py` |
| `supabase_store.py` | Shared DB loader and submission helpers | backend services, Streamlit UI |
| `synthetic_contracts.py` | Generates labeled synthetic Solidity contracts | `main.py`, tests |
| `token_counter.py` | Token counting with fallback behavior | preprocessors and prompt sizing |

---

## Start Here By Workflow

### Smart-contract benchmark path

Use these modules when working on the original Solidity pipeline:

1. `benchmark_datasets.py`
2. `dataset_loader.py`
3. `contract_normalizer.py`
4. `contract_preprocessor.py`
5. `token_counter.py`
6. `synthetic_contracts.py`

Typical entry points:

- `main.py`
- `scripts/run_all_benchmark.py`
- `scripts/run_folder_benchmark.py`

### Track B financial path

Use these modules when working on the financial-report workflow:

1. `pdf_to_markdown.py`
2. `financial_report_dataset.py`

Typical entry points:

- `run_pdf_to_md.py`
- `scripts/pdf_to_md.py`
- `run_financial_trackb.py`
- `scripts/run_financial_trackb.py`

### Shared app data path

Use `supabase_store.py` when the backend or Streamlit UI should read or write shared records.

---

## Key Modules

### `benchmark_datasets.py`

Purpose:

- load SmartBugs
- load SolidiFI
- normalize labels into the internal vulnerability taxonomy

Example:

```python
from phase1_data_pipeline.benchmark_datasets import load_benchmark

contracts = load_benchmark("smartbugs")
```

### `contract_normalizer.py`

Purpose:

- strip comments
- normalize whitespace
- standardize pragma formatting
- add stable line numbers for citation-based prompts

Example:

```python
from phase1_data_pipeline.contract_normalizer import normalize_contract

normalized = normalize_contract(source_code, add_line_nums=True)
```

### `contract_preprocessor.py`

Purpose:

- count tokens
- normalize contract text
- truncate oversized inputs before LLM calls

Example:

```python
from phase1_data_pipeline.contract_preprocessor import preprocess_contract

prepared = preprocess_contract(source_code=raw_source, max_tokens=32000)
```

### `dataset_loader.py`

Purpose:

- load local contract files from disk
- keep lightweight utility behavior for tests and offline development

Example:

```python
from phase1_data_pipeline.dataset_loader import load_contracts_from_dir

contracts = load_contracts_from_dir("data/vulnerable_contracts/")
```

### `financial_report_dataset.py`

Purpose:

- read Track B case files from JSONL
- validate the case structure used by the financial workflow

Example:

```python
from phase1_data_pipeline.financial_report_dataset import load_financial_eval_cases

cases = load_financial_eval_cases("data/trackb_eval_cases.jsonl")
```

### `pdf_to_markdown.py`

Purpose:

- convert uploaded or local PDF reports into markdown
- write the markdown into `data/` for later Track B runs

Example:

```python
from phase1_data_pipeline.pdf_to_markdown import convert_pdf_to_markdown

result = convert_pdf_to_markdown("report.pdf")
```

### `supabase_store.py`

Purpose:

- shared contract loading
- review-queue storage
- shared vulnerability catalog support

This module is mainly used by the FastAPI backend and the Streamlit UI.

### `synthetic_contracts.py`

Purpose:

- create offline test contracts with injected vulnerabilities
- save them into `data/synthetic_contracts/`

Example:

```python
from phase1_data_pipeline.synthetic_contracts import generate_synthetic_contracts

contracts = generate_synthetic_contracts(num_vulns=2)
```

### `token_counter.py`

Purpose:

- estimate or count tokens safely
- support truncation logic across prompt-building flows

---

## Notes For Contributors

- This phase no longer contains a contract chunker module.
- PDF conversion and Track B case loading are active, first-class parts of Phase 1.
- If you add a new ingestion path, document the entry point in the top-level README as well as here.
| `labels[].swc_id`    | `str \| null` | SWC identifier (e.g. `"SWC-107"`)                            |
| `labels[].severity`  | `str`         | `critical \| high \| medium \| low \| info`                  |
| `labels[].lines`     | `list[int]`   | 1-indexed affected line numbers                              |
| `labels[].function`  | `str \| null` | Affected function name                                       |
| `source`             | `str`         | `smartbugs \| solidifi \| etherscan \| synthetic`            |
| `split`              | `str`         | `train \| val \| test`                                       |
