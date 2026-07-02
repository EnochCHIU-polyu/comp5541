# COMP5566 Security Audit Workspace

This repository now contains three practical workflows:

1. A React + FastAPI web app for smart-contract auditing and benchmark management.
2. A Track B financial-report workflow that scores LLM answers against evaluation cases.
3. A legacy but still supported smart-contract CLI and Streamlit review flow.

If you are starting fresh, read the quick-start path that matches what you want to do instead of reading the repo phase-by-phase.

---

## Choose Your Starting Path

| I want to... | Start here | Main command |
| --- | --- | --- |
| Run the full-stack app | [Full-Stack Quick Start](#full-stack-quick-start) | `python -m uvicorn app.main:app --app-dir backend --reload --port 8000` and `npm run dev` |
| Evaluate the Track B financial workflow | [Track B Quick Start](#track-b-quick-start) | `.venv/bin/python run_financial_trackb.py --mode all` |
| Convert a PDF report into markdown for Track B | [PDF to Markdown](#pdf-to-markdown) | `.venv/bin/python run_pdf_to_md.py --input your.pdf` |
| Audit a Solidity contract from the CLI | [Smart-Contract CLI](#smart-contract-cli) | `.venv/bin/python main.py audit --contract path/to/Contract.sol` |
| Use the older Streamlit review UI | [Streamlit UI](#streamlit-ui) | `.venv/bin/python -m streamlit run phase4_evaluation/ui_app.py` |

---

## Workspace Map

| Area | Role |
| --- | --- |
| `frontend/` | React + TypeScript + Vite client |
| `backend/` | FastAPI API layer and application services |
| `phase1_data_pipeline/` | Data loading, preprocessing, PDF conversion, Track B case loading |
| `phase2_llm_engine/` | Smart-contract audit engine, Track B workflow, backend audit helpers |
| `phase3_hyperparameter/` | Experiment config definitions for benchmark runs |
| `phase4_evaluation/` | Scoring, reports, benchmark runners, runtime metrics, Streamlit UI |
| `data/` | Benchmark inputs, markdown reports, Track B JSONL cases |
| `scripts/` | Operational entry points for Track B and batch benchmark runs |

---

## Common Setup

### Requirements

- Python 3.10+
- Node.js 18+
- A configured `.env` file for LLM-backed flows
- A virtual environment at `.venv` is recommended

### Install once

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### Minimal `.env`

The current project is configured around an OpenAI-compatible API, including Poe-style endpoints.

```dotenv
POE_API_KEY=poe_xxx
OPENAI_API_KEY=${POE_API_KEY}
OPENAI_BASE_URL=https://api.poe.com/v1

DEFAULT_MODEL=deepseek-v3.2
TEMPERATURE=0
MAX_CONTEXT_TOKENS=32000
API_PAUSE_SECONDS=13

DATA_BACKEND=local
```

Optional settings used by some paths:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN`

Restart any running Python process after changing `.env`.

---

## Full-Stack Quick Start

Use this path if you want the main browser-based application.

### 1. Start the backend

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

### 2. Start the frontend

```bash
cd frontend
npm run dev
```

### 3. Open the app

- Frontend: `http://localhost:5173`
- Backend health check: `http://localhost:8000/healthz`

If you need a custom backend URL:

```bash
export VITE_API_URL=http://localhost:8000
```

### What this path uses internally

- Frontend routes live in `frontend/src/pages/`
- Backend routes live in `backend/app/api/routes/`
- Audit orchestration is in `backend/app/services/audit_service.py`
- Shared smart-contract logic comes from `phase1_data_pipeline/`, `phase2_llm_engine/`, and `phase4_evaluation/`

See [frontend/README.md](frontend/README.md) and [backend/README.md](backend/README.md) for implementation detail.

---

## Track B Quick Start

Use this path if you want to evaluate LLM performance on financial-report question answering.

### Input files

- Source report markdown: `data/2026q1-alphabet-earnings-release.md`
- Evaluation cases: `data/trackb_eval_cases.jsonl`

### Run one variant

```bash
source .venv/bin/activate
.venv/bin/python run_financial_trackb.py \
   --mode all \
   --report data/2026q1-alphabet-earnings-release.md \
   --cases trackb_eval_cases.jsonl
```

### Supported variants

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

### Run a short smoke test

```bash
.venv/bin/python run_financial_trackb.py \
   --mode all_minus_h4 \
   --report data/2026q1-alphabet-earnings-release.md \
   --cases trackb_eval_cases.jsonl \
   --max-cases 3
```

### Output

Each run writes into `phase4_evaluation/results/trackb/` with:

- `predictions.json`
- `metrics.json`
- `variant.json`

### Track B module flow

1. `phase1_data_pipeline/financial_report_dataset.py` loads JSONL evaluation cases.
2. `phase2_llm_engine/financial_trackb_workflow.py` runs the selected harness variant.
3. `phase4_evaluation/financial_trackb_scorer.py` scores answers and error categories.
4. `scripts/run_financial_trackb.py` packages the run outputs.

---

## PDF to Markdown

Use this before Track B when your source material starts as a PDF.

```bash
source .venv/bin/activate
.venv/bin/python run_pdf_to_md.py --input path/to/report.pdf
```

By default, the converted markdown is written into `data/`.

Implementation path:

- CLI wrapper: `run_pdf_to_md.py`
- Script entry: `scripts/pdf_to_md.py`
- Converter: `phase1_data_pipeline/pdf_to_markdown.py`

---

## Smart-Contract CLI

Use this path if you want the original contract-audit workflow from the terminal.

### Audit a contract

```bash
source .venv/bin/activate
.venv/bin/python main.py audit --contract path/to/MyContract.sol
```

Useful variants:

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

### Load benchmark datasets

```bash
git clone https://github.com/smartbugs/smartbugs-curated.git data/benchmarks/smartbugs
git clone https://github.com/smartbugs/SolidiFI-benchmark data/benchmarks/solidifi

.venv/bin/python main.py download-benchmarks --dataset all
```

### Generate a report

```bash
.venv/bin/python main.py report --results results.json --output report.md
.venv/bin/python main.py report --results results.json --output report.html --format html
```

### Seed the vulnerability catalog

```bash
.venv/bin/python main.py seed-vulnerability-catalog
.venv/bin/python main.py seed-vulnerability-catalog --force
```

---

## Streamlit UI

The Streamlit app is still available for the older human-in-the-loop review flow.

```bash
source .venv/bin/activate
.venv/bin/python -m streamlit run phase4_evaluation/ui_app.py
```

Open `http://localhost:8501` after startup.

Use this path if you specifically want:

- manual contract paste/upload
- live review of flagged lines
- TP / FP / FN annotation
- Slither pre-scan injection into prompts
- Supabase-backed review queue experiments

---

## Tests

```bash
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -v
```

Or by phase:

```bash
.venv/bin/python -m pytest tests/test_phase1.py -v
.venv/bin/python -m pytest tests/test_phase2.py -v
.venv/bin/python -m pytest tests/test_phase3.py -v
.venv/bin/python -m pytest tests/test_phase4.py -v
```

These tests run offline and do not require live API calls.

---

## Phase Notes For Contributors

### Phase 1: Data Pipeline

- Smart-contract dataset helpers
- Contract normalization and token counting
- Synthetic contract generation
- PDF-to-markdown conversion
- Track B evaluation case loading

See [phase1_data_pipeline/README.md](phase1_data_pipeline/README.md).

### Phase 2: LLM Engine

- Smart-contract audit orchestration
- Track B workflow execution
- Verification, retrieval, and backend-only helper logic

See [phase2_llm_engine/README.md](phase2_llm_engine/README.md).

### Phase 3: Hyperparameter

- Benchmark tuning configs and experiment grid definitions

See [phase3_hyperparameter/README.md](phase3_hyperparameter/README.md).

### Phase 4: Evaluation

- Smart-contract scoring
- Track B scoring
- Benchmark execution and reports
- Runtime metrics logging
- Streamlit UI

See [phase4_evaluation/README.md](phase4_evaluation/README.md).
