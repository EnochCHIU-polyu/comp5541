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
    run_financial_workflow_batch,
    workflow_result_to_dict,
)
from phase4_evaluation.financial_trackb_scorer import aggregate_scores, score_case

VARIANT_FLAGS = {
    "baseline": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": False,
    },
    "baseline_no_context": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": False,
    },
    "h1": {
        "use_h1_retrieval": True,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": False,
    },
    "h2": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": True,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": False,
    },
    "h3": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": True,
        "use_h4_verifier": False,
    },
    "h4": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": True,
    },
    "all": {
        "use_h1_retrieval": True,
        "use_h2_numeric_guard": True,
        "use_h3_chronology_guard": True,
        "use_h4_verifier": True,
    },
    "all_minus_h1": {
        "use_h1_retrieval": False,
        "use_h2_numeric_guard": True,
        "use_h3_chronology_guard": True,
        "use_h4_verifier": True,
    },
    "all_minus_h2": {
        "use_h1_retrieval": True,
        "use_h2_numeric_guard": False,
        "use_h3_chronology_guard": True,
        "use_h4_verifier": True,
    },
    "all_minus_h3": {
        "use_h1_retrieval": True,
        "use_h2_numeric_guard": True,
        "use_h3_chronology_guard": False,
        "use_h4_verifier": True,
    },
    "all_minus_h4": {
        "use_h1_retrieval": True,
        "use_h2_numeric_guard": True,
        "use_h3_chronology_guard": True,
        "use_h4_verifier": False,
    },
}


def _resolve_input_path(raw_path: str) -> str:
    """Resolve CLI file path with a fallback to repo-local data/ directory."""
    p = Path(raw_path)
    if p.exists():
        return str(p)

    data_fallback = ROOT / "data" / raw_path
    if data_fallback.exists():
        return str(data_fallback)

    name = p.name.lower()
    data_dir = ROOT / "data"
    if data_dir.exists():
      if name in {"report.md", "report.pdf", "report"}:
        candidates = [
            path for path in sorted(data_dir.glob("*.md"))
            if path.name.lower() not in {"readme.md"}
        ]
        if candidates:
            return str(candidates[0])
      if name in {"trackb_eval_cases.jsonl", "cases.jsonl"}:
        candidates = [
            path for path in sorted(data_dir.glob("*.jsonl"))
            if path.name.lower() not in {"readme.jsonl"}
        ]
        if candidates:
            return str(candidates[0])

    return str(p)


def _mode_to_flags(mode: str) -> dict:
    return dict(VARIANT_FLAGS[mode])


def _build_variant_summary(mode: str, flags: dict) -> dict:
    enabled = [name for name, on in flags.items() if on]
    disabled = [name for name, on in flags.items() if not on]
    return {
        "variant_name": mode,
        "enabled_harnesses": enabled,
        "disabled_harnesses": disabled,
        "is_baseline": mode == "baseline",
        "is_full_workflow": mode == "all",
        "is_leave_one_out_ablation": mode.startswith("all_minus_"),
    }


def _is_context_length_error(exc: Exception) -> bool:
    low = str(exc).lower()
    return (
        "context_length_exceeded" in low
        or "message is too long" in low
        or "context length" in low
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Track B financial baseline/harness workflow")
    parser.add_argument("--report", default="data/report.md", help="Path to source report text")
    parser.add_argument("--cases", default="data/trackb_eval_cases.jsonl", help="Path to JSONL cases")
    parser.add_argument(
        "--mode",
        choices=list(VARIANT_FLAGS.keys()),
        default="baseline",
        help="Workflow variant: baseline, single-harness, full workflow, or leave-one-out ablation",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", default="phase4_evaluation/results/trackb")
    parser.add_argument("--max-cases", type=int, default=0, help="Run only the first N cases (0 = all)")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Batch size for testing runs (0 = use maximum possible for selected cases)",
    )
    args = parser.parse_args()

    report_path = _resolve_input_path(args.report)
    cases_path = _resolve_input_path(args.cases)

    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    cases = load_financial_eval_cases(cases_path)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    flags = _mode_to_flags(args.mode)
    variant_summary = _build_variant_summary(args.mode, flags)

    run_rows: list[dict] = []
    scored = []

    if not cases:
        raise ValueError("No cases available to run.")

    batch_size = args.batch_size if args.batch_size and args.batch_size > 0 else len(cases)
    print(f"Running {len(cases)} cases in batch mode (batch_size={batch_size}) for mode={args.mode}")

    def _run_batch_with_fallback(case_batch):
        try:
            return run_financial_workflow_batch(
                report_text=report_text,
                cases=case_batch,
                model=args.model,
                temperature=args.temperature,
                **flags,
            )
        except Exception as exc:  # noqa: BLE001
            if len(case_batch) <= 1 or not _is_context_length_error(exc):
                raise
            mid = max(1, len(case_batch) // 2)
            left = _run_batch_with_fallback(case_batch[:mid])
            right = _run_batch_with_fallback(case_batch[mid:])
            return left + right

    for start in range(0, len(cases), batch_size):
        case_batch = cases[start : start + batch_size]
        wf_batch = _run_batch_with_fallback(case_batch)
        for offset, case in enumerate(case_batch, start=1):
            if offset - 1 >= len(wf_batch):
                continue
            wf = wf_batch[offset - 1]
            print(f"[{start + offset}/{len(cases)}] Running case {case.case_id} ({args.mode})")
            row = workflow_result_to_dict(wf)
            row["variant"] = variant_summary
            run_rows.append(row)
            scored.append(score_case(case, row))

    metrics = aggregate_scores(scored)
    metrics["variant"] = variant_summary
    metrics["report_path"] = report_path
    metrics["cases_path"] = cases_path
    metrics["model"] = args.model
    metrics["temperature"] = args.temperature
    metrics["cases_run"] = len(cases)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output, f"{args.mode}_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "predictions.json"), "w", encoding="utf-8") as f:
        json.dump(run_rows, f, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "variant.json"), "w", encoding="utf-8") as f:
        json.dump(variant_summary, f, indent=2, ensure_ascii=False)

    print("Report:", report_path)
    print("Cases:", cases_path)
    print("Variant:", json.dumps(variant_summary, ensure_ascii=False))
    print("Saved run:", out_dir)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
