"""h1_3 - Chronology guard component for Harness 1 (Track B)."""

from __future__ import annotations

import re

from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase


def _normalize(text: str) -> str:
    low = text.lower()
    low = re.sub(r"[,/.-]", " ", low)
    low = re.sub(r"\s+", " ", low)
    return low.strip()


def chronology_guard(answer: str, case: FinancialEvalCase, report_text: str) -> bool | None:
    """Check whether expected events appear in the order requested by the case."""
    order = case.expected_event_order or []
    if not order:
        return None

    low_answer = _normalize(answer)
    positions = []
    for token in order:
        idx = low_answer.find(_normalize(token))
        if idx < 0:
            return False
        positions.append(idx)
    return positions == sorted(positions)
