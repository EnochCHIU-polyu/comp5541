"""Run Track B financial workflow experiments (baseline and harness variants)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DEFAULT_MODEL
from phase1_data_pipeline.financial_report_dataset import load_financial_eval_cases
from phase2_llm_engine.financial_trackb_workflow import (
    run_financial_workflow,
    workflow_result_to_dict,
)
from phase4_evaluation.financial_trackb_scorer import aggregate_scores, score_case


def _resolve_input_path(raw_path: str) -> str:
    """Resolve CLI file path with a fallback to repo-local data/ directory."""
    p = Path(raw_path)
    if p.exists():
        return str(p)

    data_fallback = ROOT / "data" / raw_path
    if data_fallback.exists():
        return str(data_fallback)

    return str(p)


def _mode_to_flags(mode: str) -> dict:
    flags = {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": False,
    }
    if mode == "h1":
        flags["use_h1_retrieval"] = True
    elif mode == "h2":
        flags["use_h2_numeric_guard"] = True
    elif mode == "h3":
        flags["use_h3_chronology_guard"] = True
    elif mode == "h4":
        flags["use_h4_verifier"] = True
    elif mode == "all":
        for k in list(flags.keys()):
            flags[k] = True
    return flags


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Track B financial baseline/harness workflow")
    parser.add_argument("--report", default="data/report.md", help="Path to source report text")
    parser.add_argument("--cases", default="data/trackb_eval_cases.jsonl", help="Path to JSONL cases")
    parser.add_argument("--mode", choices=["baseline", "h1", "h2", "h3", "h4", "all"], default="baseline")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", default="phase4_evaluation/results/trackb")
    parser.add_argument("--max-cases", type=int, default=0, help="Run only the first N cases (0 = all)")
    args = parser.parse_args()

    report_path = _resolve_input_path(args.report)
    cases_path = _resolve_input_path(args.cases)

    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    cases = load_financial_eval_cases(cases_path)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    flags = _mode_to_flags(args.mode)

    run_rows = []
    scored = []

    for idx, case in enumerate(cases, 1):
        print(f"[{idx}/{len(cases)}] Running case {case.case_id} ({args.mode})")
        wf = run_financial_workflow(
            report_text=report_text,
            case=case,
            model=args.model,
            temperature=args.temperature,
            **flags,
        )
        row = workflow_result_to_dict(wf)
        run_rows.append(row)
        scored.append(score_case(case, row))

    metrics = aggregate_scores(scored)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output, f"{args.mode}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(run_rows, f, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print("Report:", report_path)
    print("Cases:", cases_path)
    print("Saved run:", out_dir)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
