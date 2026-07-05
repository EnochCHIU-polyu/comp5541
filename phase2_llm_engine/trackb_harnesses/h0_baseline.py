"""H0 - Baseline single-call prompt and parsing utilities for Track B."""

from __future__ import annotations

import json
import re
from typing import Any


def build_baseline_prompt(question: str, context: str) -> list[dict[str, str]]:
    """Build the simplest baseline prompt (single LLM call, minimal constraints)."""
    return [
        {
            "role": "system",
            "content": (
                "You are a financial QA assistant. "
                "Answer using only the provided context and cite supporting snippets."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                "Context:\n"
                f"{context}\n\n"
                "Return exactly in this format:\n"
                "ANSWER: <short answer>\n"
                "CITATIONS: <semicolon-separated supporting snippets>"
            ),
        },
    ]


def build_batch_prompt(batch_items: list[dict[str, str]], strict: bool = False) -> list[dict[str, str]]:
    """Build one prompt for multiple cases with JSON array output."""
    sections: list[str] = []
    for idx, item in enumerate(batch_items, start=1):
        hint = item.get("hint_block", "")
        sections.append(
            "\n".join(
                [
                    f"CASE {idx} | case_id={item['case_id']}",
                    "Question:",
                    item["question"],
                    "Hints:",
                    hint or "(none)",
                    "Context:",
                    item["context"],
                ]
            )
        )

    hard_constraints = ""
    if strict:
        hard_constraints = (
            "Rules:\n"
            "- Do not invent numbers, entities, dates, or units.\n"
            "- Keep exact scale/unit from evidence.\n"
            "- If evidence is insufficient, answer as INSUFFICIENT_EVIDENCE with citations NONE.\n"
        )

    return [
        {
            "role": "system",
            "content": (
                "You are a financial audit assistant. "
                "Answer each case independently and return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Solve all cases below.\n\n"
                "Output format (strict JSON array):\n"
                "[\n"
                '  {"case_id":"...","answer":"...","citations":["..."]}\n'
                "]\n\n"
                + hard_constraints
                + "\n\n".join(sections)
            ),
        },
    ]


def parse_answer(raw: str) -> tuple[str, list[str]]:
    """Parse ANSWER/CITATIONS format used across Track B prompts."""
    answer = ""
    citations: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("answer:"):
            answer = stripped.split(":", 1)[1].strip()
        if low.startswith("citations:"):
            chunk = stripped.split(":", 1)[1].strip()
            citations = [c.strip() for c in chunk.split(";") if c.strip()]

    if not answer:
        m = re.search(r"(?im)^\s*(?:\*\*)?answer(?:\*\*)?\s*:\s*(.+)$", raw)
        if m:
            answer = m.group(1).strip()
    if not citations:
        m = re.search(r"(?im)^\s*(?:\*\*)?citations(?:\*\*)?\s*:\s*(.+)$", raw)
        if m:
            citations = [c.strip() for c in m.group(1).split(";") if c.strip()]

    if not answer:
        answer = re.sub(r"\s+", " ", raw).strip()
    return answer, citations


def extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract first JSON array from model output."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
    except Exception:  # noqa: BLE001
        pass

    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return [p for p in parsed if isinstance(p, dict)]
        except Exception:  # noqa: BLE001
            pass

    return []
