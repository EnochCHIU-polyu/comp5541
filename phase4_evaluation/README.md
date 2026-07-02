# Phase 4 - Evaluation and UI

Phase 4 now supports three responsibilities:

1. Smart-contract evaluation and benchmark runs.
2. Track B financial-report scoring.
3. Runtime logging and the older Streamlit review UI.

---

## Module Overview

| File | Role | Used by |
| --- | --- | --- |
| `experiment_runner.py` | Smart-contract benchmark grid runner | CLI benchmark workflow |
| `financial_trackb_scorer.py` | Track B case-level and aggregate scoring | `scripts/run_financial_trackb.py` |
| `report_generator.py` | Markdown and HTML audit report output | `main.py` |
| `runtime_metrics_logger.py` | Persist backend runtime metrics | FastAPI backend service |
| `scorer.py` | Smart-contract metrics and aggregate evaluation helpers | tests, benchmark flows |
| `swe_mapping.py` | Label mapping support for benchmark and backend reporting | backend benchmark service, scripts |
| `ui_app.py` | Streamlit review interface | manual HITL workflow |

---

## Start Here By Workflow

### Smart-contract benchmark path

Main modules:

1. `scorer.py`
2. `experiment_runner.py`
3. `report_generator.py`
4. `swe_mapping.py`

Typical entry points:

- `main.py report`
- `python -m phase4_evaluation.experiment_runner`
- `scripts/run_all_benchmark.py`
- `scripts/run_folder_benchmark.py`

### Track B financial path

Main modules:

1. `financial_trackb_scorer.py`

Typical entry points:

- `run_financial_trackb.py`
- `scripts/run_financial_trackb.py`

### Backend runtime path

Main modules:

1. `runtime_metrics_logger.py`
2. `swe_mapping.py`

These support API-side audit and benchmark reporting.

### Streamlit path

Main modules:

1. `ui_app.py`

Use this only if you want the legacy interactive review surface alongside the newer React app.

---

## Key Modules

### `scorer.py`

Purpose:

- compute precision, recall, F1, and related smart-contract metrics
- aggregate results across contracts and vulnerability classes
- support calibration and per-type breakdowns

Example:

```python
from phase4_evaluation.scorer import evaluate_batch

scores = evaluate_batch(audit_results, ground_truth)
```

### `experiment_runner.py`

Purpose:

- run benchmark datasets against a tuning grid
- save predictions, metrics, and timing files

CLI:

```bash
python -m phase4_evaluation.experiment_runner --dataset smartbugs --configs all
```

### `financial_trackb_scorer.py`

Purpose:

- score Track B predictions against case answers
- summarize accuracy, numeric correctness, citation rate, and error buckets

This module powers the results written into `phase4_evaluation/results/trackb/`.

### `report_generator.py`

Purpose:

- turn smart-contract audit outputs into markdown or HTML reports

CLI:

```bash
python main.py report --results results.json --output report.md
```

### `runtime_metrics_logger.py`

Purpose:

- append per-request runtime metrics from the FastAPI service

This module is used internally by backend audit services.

### `swe_mapping.py`

Purpose:

- keep vulnerability and benchmark labels aligned across scripts and backend responses

### `ui_app.py`

Purpose:

- provide the older Streamlit-based review workflow for Solidity auditing

Launch:

```bash
streamlit run phase4_evaluation/ui_app.py
```

---

## Output Layout

### Smart-contract benchmark runs

Typical contents:

- `config.json`
- `predictions.json`
- `metrics.json`
- `timing.json`

### Track B runs

Typical contents inside `results/trackb/<variant>_<timestamp>/`:

- `predictions.json`
- `metrics.json`
- `variant.json`

---

## Notes For Contributors

- This phase no longer includes a standalone `results_logger.py` module.
- Track B evaluation is now a first-class part of Phase 4 and should be documented whenever new runner modes are added.
- If you extend benchmark reporting, keep both the top-level README and this file aligned with the CLI entry points.

## 7. Output Directory Structure

```
results/
└── {config_name}_{timestamp}/
    ├── config.json          ← TuningConfig snapshot
    ├── predictions.json     ← per-contract, per-vuln predictions + confidence
    ├── metrics.json         ← aggregated scores (Precision, Recall, F1, AUC, …)
    └── timing.json          ← per-contract latency and token usage

results/
└── grid_{timestamp}/
    ├── T0-gpt4o-binary_{ts}/
    │   ├── config.json
    │   ├── predictions.json
    │   ├── metrics.json
    │   └── timing.json
    ├── T0-gpt4o-nonbinary_{ts}/
    │   └── …
    └── comparison.csv       ← cross-config summary table
```
