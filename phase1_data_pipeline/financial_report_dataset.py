"""
Phase 1 - Data Pipeline: Track B financial report evaluation dataset loader.

Loads question/answer test cases used to compare:
- V0 baseline (single LLM call)
- Harness variants (retrieval, numeric guard, chronology checker, verifier)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class FinancialEvalCase:
    """Single Track B evaluation case."""

    case_id: str
    question: str
    answer_type: str
    expected_answer: str
    tolerance: float = 0.0
    expected_unit: str = ""
    arithmetic_expression: str = ""
    expected_event_order: list[str] | None = None
    evidence_keywords: list[str] | None = None


DEFAULT_CASES_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "trackb_eval_cases.jsonl",
)


def _to_case(record: dict[str, Any]) -> FinancialEvalCase:
    return FinancialEvalCase(
        case_id=str(record.get("case_id", "")).strip(),
        question=str(record.get("question", "")).strip(),
        answer_type=str(record.get("answer_type", "text")).strip(),
        expected_answer=str(record.get("expected_answer", "")).strip(),
        tolerance=float(record.get("tolerance", 0.0) or 0.0),
        expected_unit=str(record.get("expected_unit", "")).strip(),
        arithmetic_expression=str(record.get("arithmetic_expression", "")).strip(),
        expected_event_order=list(record.get("expected_event_order", []) or []),
        evidence_keywords=list(record.get("evidence_keywords", []) or []),
    )


def load_financial_eval_cases(path: str | None = None) -> list[FinancialEvalCase]:
    """
    Load Track B evaluation cases from JSONL.

    Each JSON line must contain:
    case_id, question, answer_type, expected_answer
    """
    file_path = path or DEFAULT_CASES_PATH
    file_path = os.path.normpath(file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Track B cases file not found: {file_path}")

    cases: list[FinancialEvalCase] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {file_path}:{line_no}: {exc}") from exc
            case = _to_case(obj)
            if not case.case_id:
                raise ValueError(f"Missing case_id in {file_path}:{line_no}")
            if not case.question:
                raise ValueError(f"Missing question in {file_path}:{line_no}")
            cases.append(case)

    if not cases:
        raise ValueError(f"No evaluation cases found in {file_path}")
    return cases
