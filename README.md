# COMP5541

This repository has three primary workflows:

1. Full-stack app (React + FastAPI) for smart-contract audit and benchmark operations.
2. Track B financial-report evaluation workflow (LLM + harnesses + scorer).
3. Legacy CLI and Streamlit flows for contract audit and review.

If you are new, start from the section that matches your goal.

---

## Overview

| Area | Purpose |
| --- | --- |
| `frontend/` | React + TypeScript + Vite client |
| `backend/` | FastAPI routes, schemas, and services |
| `phase1_data_pipeline/` | Data loaders, preprocessors, PDF-to-markdown, Track B case loading |
| `phase2_llm_engine/` | Audit engines and Track B harness workflow |
| `phase3_hyperparameter/` | Benchmark tuning configs |
| `phase4_evaluation/` | Scoring, experiment runners, reports, runtime metrics, Streamlit UI |
| `data/` | Input reports and Track B JSONL cases |
| `scripts/` | Runner scripts for benchmark and Track B tasks |

---

## Start Here

| I want to... | Jump to | Main command |
| --- | --- | --- |
| Run the full-stack app | [Full-Stack Quick Start](#full-stack-quick-start) | `python -m uvicorn app.main:app --app-dir backend --reload --port 8000` + `npm run dev` |
| Run Track B evaluation | [Track B Quick Start](#track-b-quick-start) | `.venv/bin/python run_financial_trackb.py --mode all` |
| Convert a PDF report for Track B | [PDF to Markdown](#pdf-to-markdown) | `.venv/bin/python run_pdf_to_md.py --input path/to/report.pdf` |
| Audit Solidity from CLI | [Smart-Contract CLI](#smart-contract-cli) | `.venv/bin/python main.py audit --contract path/to/Contract.sol` |
| Use legacy review UI | [Streamlit UI](#streamlit-ui) | `.venv/bin/python -m streamlit run phase4_evaluation/ui_app.py` |

---

## Common Setup

### Requirements

- Python 3.10+
- Node.js 18+
- `.venv` virtual environment (recommended)
- `.env` configured for your LLM provider

### Install once

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### Minimal `.env` (DeepSeek via OpenAI-compatible API)

```dotenv
POE_API_KEY = ${key}
OPENAI_API_KEY=${POE_API_KEY}
OPENAI_BASE_URL=https://api.poe.com/v1

DEFAULT_MODEL=deepseek-v3.2    
TEMPERATURE=0              
MAX_CONTEXT_TOKENS=64000
API_PAUSE_SECONDS=12      

```

Restart running Python services after changing `.env`.

---

## Full-Stack Quick Start

Use this when you want the browser application.

### 1. Start backend

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

### 2. Start frontend

```bash
cd frontend
npm run dev
```

### 3. Open app

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/healthz`

Optional API override:

```bash
export VITE_API_URL=http://localhost:8000
```

Related docs:
- [frontend/README.md](frontend/README.md)
- [backend/README.md](backend/README.md)

---

## Track B Quick Start

Use this to evaluate financial QA performance on the Track B dataset.

### Inputs

- Report markdown: `data/2026q1-alphabet-earnings-release.md`
- Cases JSONL: `data/trackb_eval_cases.jsonl`

### Run full harness profile

```bash
source .venv/bin/activate
.venv/bin/python run_financial_trackb.py \
   --mode all \
   --report data/2026q1-alphabet-earnings-release.md \
   --cases data/trackb_eval_cases.jsonl
```

### Variants

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

### Smoke test

```bash
.venv/bin/python run_financial_trackb.py \
   --mode all_minus_h4 \
   --report data/2026q1-alphabet-earnings-release.md \
   --cases data/trackb_eval_cases.jsonl \
   --max-cases 3
```

### Outputs

Run artifacts are written to `phase4_evaluation/results/trackb/`:

- `predictions.json`
- `metrics.json`
- `variant.json`

Track B internals:

1. `phase1_data_pipeline/financial_report_dataset.py`
2. `phase2_llm_engine/financial_trackb_workflow.py`
3. `phase4_evaluation/financial_trackb_scorer.py`
4. `scripts/run_financial_trackb.py`

Harness details:
- [phase2_llm_engine/trackb_harnesses/README.md](phase2_llm_engine/trackb_harnesses/README.md)

---

## PDF to Markdown

Use this when source content starts as PDF:

```bash
source .venv/bin/activate
.venv/bin/python run_pdf_to_md.py --input path/to/report.pdf
```

Output defaults to `data/`.

Implementation:
- `run_pdf_to_md.py`
- `scripts/pdf_to_md.py`
- `phase1_data_pipeline/pdf_to_markdown.py`

---

## Smart-Contract CLI

Use this for the original terminal-based audit flow.

### Audit

```bash
source .venv/bin/activate
.venv/bin/python main.py audit --contract path/to/MyContract.sol
```

Common variants:

```bash
.venv/bin/python main.py audit --contract path/to/MyContract.sol --mode binary
.venv/bin/python main.py audit --contract path/to/MyContract.sol --mode cot
.venv/bin/python main.py audit --contract path/to/MyContract.sol --verify
.venv/bin/python main.py audit --contract path/to/MyContract.sol --output results.json
```

### Generate synthetic contracts

```bash
.venv/bin/python main.py generate-synthetic --num-vulns 2
.venv/bin/python main.py generate-synthetic --num-vulns 15
```

### Download benchmark datasets

```bash
git clone https://github.com/smartbugs/smartbugs-curated.git data/benchmarks/smartbugs
git clone https://github.com/smartbugs/SolidiFI-benchmark data/benchmarks/solidifi

.venv/bin/python main.py download-benchmarks --dataset all
```

### Generate report

```bash
.venv/bin/python main.py report --results results.json --output report.md
.venv/bin/python main.py report --results results.json --output report.html --format html
```

### Seed vulnerability catalog

```bash
.venv/bin/python main.py seed-vulnerability-catalog
.venv/bin/python main.py seed-vulnerability-catalog --force
```

---

## Streamlit UI

Legacy human-in-the-loop review app:

```bash
source .venv/bin/activate
.venv/bin/python -m streamlit run phase4_evaluation/ui_app.py
```

Open `http://localhost:8501`.

---

## Tests

Run full suite:

```bash
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -v
```

Run by phase:

```bash
.venv/bin/python -m pytest tests/test_phase1.py -v
.venv/bin/python -m pytest tests/test_phase2.py -v
.venv/bin/python -m pytest tests/test_phase3.py -v
.venv/bin/python -m pytest tests/test_phase4.py -v
```

These tests run offline and do not require live API calls.

---

## Contributor Notes

Phase references:

- [phase1_data_pipeline/README.md](phase1_data_pipeline/README.md)
- [phase2_llm_engine/README.md](phase2_llm_engine/README.md)
- [phase3_hyperparameter/README.md](phase3_hyperparameter/README.md)
- [phase4_evaluation/README.md](phase4_evaluation/README.md)
