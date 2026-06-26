# COMP5541 Smart Contract Audit Platform

COMP5541 is a full-stack smart-contract analysis workspace built around two connected experiences:

1. a contract auditing workflow for audits, benchmarks, and vulnerability submissions
2. a knowledge-graph workflow that turns documents into a browsable graph with evidence-grounded node explanations

The current design combines a FastAPI backend, a React + TypeScript frontend, and the existing data-pipeline / LLM-engine modules in this repository.

## What was built

### Harness 1: Document -> Knowledge Graph

- `kg_extractor.py` converts PDF pages or plain text into overlapping chunks, sends them through a strict LLM prompt, and parses the result into JSON with code-fence tolerance.
- `kg_service.py` orchestrates extraction asynchronously and emits SSE stage updates: `queued -> chunking -> extracting -> indexing -> completed/failed`.
- `kg_store.py` persists the chunk corpus and graph data as JSONL / JSON and exports Quartz-friendly markdown with per-node `.md` files and `graph.json`.

### Harness 2: Node Click -> Evidence-Grounded Explanation

- `kg_retriever.py` uses TF-IDF + cosine similarity to retrieve supporting chunks for a clicked node.
- The retriever returns `EVIDENCE_INSUFFICIENT` when no relevant source chunks are found, so the UI can warn instead of hallucinating an answer.

### Backend API

- `POST /api/v1/kg/extract`
- `GET /api/v1/kg/{id}/stream`
- `GET /api/v1/kg/{id}/snapshot`
- `GET /api/v1/kg/{id}/graph`
- `GET /api/v1/kg/{id}/nodes/{node_id}`
- `GET /api/v1/kg/{id}/quartz/graph.json`

### Frontend

- `/` landing page
- `/kg` knowledge-graph workspace
- `KGUploadPanel` for text paste and PDF upload with live SSE progress
- `KGGraphView` for the SVG force-directed graph
- `KGNodeDetailPanel` for background intro, AI explanation, source evidence, and evidence-insufficient warnings

## Project Structure

```text
comp5541/
├── main.py
├── config.py
├── requirements.txt
├── backend/
│   ├── app/
│   │   ├── api/routes/kg.py
│   │   ├── api/routes/audits.py
│   │   ├── api/routes/benchmark.py
│   │   ├── api/routes/vulnerabilities.py
│   │   ├── schemas/
│   │   └── services/
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/
│       ├── components/
│       └── features/
├── phase1_data_pipeline/
├── phase2_llm_engine/
├── phase3_hyperparameter/
├── phase4_evaluation/
├── supabase/
└── tests/
```

For implementation details, see:

- [frontend/README.md](frontend/README.md)
- [backend/README.md](backend/README.md)

## Requirements

- Python 3.10 or higher
- Node.js 18+ for the frontend
- Optional LLM and storage keys depending on the workflow you run

## Installation

```bash
git clone <repo-url>
cd comp5541
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want the web app, install the frontend dependencies as well:

```bash
cd frontend
npm install
```

## Run the App

Start the backend from the repository root:

```bash
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

The frontend uses `VITE_API_URL` and falls back to `http://localhost:8000`.

## Configuration

Create a `.env` file in the repository root for local secrets and provider settings. Common variables include:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `ETHERSCAN_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `DATA_BACKEND`
- `VITE_API_URL`

If you are using Supabase, run [supabase/schema.sql](supabase/schema.sql) in the SQL editor before switching `DATA_BACKEND` to `supabase`.

## Security

`graph_id` parameters are parsed with `uuid.UUID()` before any filesystem access, which prevents path traversal in the KG storage layer. The current CodeQL scan reports 0 alerts for that path.

## Tests

The KG implementation has dedicated coverage in [backend/tests/test_kg.py](backend/tests/test_kg.py), with 14 tests passing.

Run the available tests from the repository root:

```bash
pytest -q
```

## Related Docs

- [backend/README.md](backend/README.md)
- [frontend/README.md](frontend/README.md)
- [phase1_data_pipeline/README.md](phase1_data_pipeline/README.md)
- [phase2_llm_engine/README.md](phase2_llm_engine/README.md)
- [phase3_hyperparameter/README.md](phase3_hyperparameter/README.md)
- [phase4_evaluation/README.md](phase4_evaluation/README.md)
