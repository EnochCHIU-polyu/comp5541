"""H1 - code based harness for financial QA."""

from __future__ import annotations

import re
from collections import OrderedDict

_SPLIT_RE = re.compile(r"\n{2,}|(?<=\n)\s*\n")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def _blocks(text: str) -> list[str]:
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if parts:
        return parts
    return [text.strip()] if text.strip() else []


def _score_chunk(chunk: str, question: str) -> int:
    q_words = {w for w in re.findall(r"[A-Za-z0-9%]+", question.lower()) if len(w) > 2}
    if not q_words:
        return 0
    c_low = chunk.lower()
    return sum(1 for w in q_words if w in c_low)


def _score_with_keywords(chunk: str, question: str, evidence_keywords: list[str] | None) -> int:
    score = _score_chunk(chunk, question)
    if _NUM_RE.search(chunk):
        score += 2
    if evidence_keywords:
        c_low = chunk.lower()
        for kw in evidence_keywords:
            token = str(kw).strip().lower()
            if token and token in c_low:
                score += 5
    return score


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def _keyword_windows(report_text: str, evidence_keywords: list[str] | None, window: int = 1) -> list[str]:
    if not evidence_keywords:
        return []
    lines = report_text.splitlines()
    hits: list[str] = []
    seen: set[str] = set()
    lowered = [str(k).strip().lower() for k in evidence_keywords if str(k).strip()]
    for idx, line in enumerate(lines):
        low = line.lower()
        if not any(kw in low for kw in lowered):
            continue
        start = max(0, idx - window)
        end = min(len(lines), idx + window + 1)
        snippet = "\n".join(lines[start:end]).strip()
        key = snippet.lower()
        if snippet and key not in seen:
            seen.add(key)
            hits.append(snippet)
    return hits


def retrieve_chunks(
    report_text: str,
    question: str,
    top_k: int = 5,
    evidence_keywords: list[str] | None = None,
) -> list[str]:
    """Select the most relevant text chunks for a financial question."""
    blocks = _blocks(report_text)
    if not blocks:
        return []

    ranked = sorted(
        (
            (idx, block, _score_with_keywords(block, question, evidence_keywords))
            for idx, block in enumerate(blocks)
        ),
        key=lambda x: (x[2], -x[0]),
        reverse=True,
    )
    picks = [block for _, block, score in ranked[:top_k] if score > 0]
    if not picks:
        picks = blocks[: min(top_k, len(blocks))]

    keyword_hits = _keyword_windows(report_text, evidence_keywords, window=1)
    merged = OrderedDict[str, None]()
    for item in keyword_hits + picks:
        item = _normalize(item)
        if item:
          merged[item] = None
    return list(merged.keys())[: max(top_k, len(keyword_hits))]


def build_retrieval_context(
    report_text: str,
    question: str,
    top_k: int = 5,
    evidence_keywords: list[str] | None = None,
) -> tuple[list[str], str]:
    chunks = retrieve_chunks(report_text, question, top_k=top_k, evidence_keywords=evidence_keywords)
    if not chunks:
        return [], report_text
    context = "\n\n---\n\n".join(chunks)
    if evidence_keywords:
        context = (
            f"Evidence keywords: {', '.join(str(k) for k in evidence_keywords if str(k).strip())}\n\n"
            f"{context}"
        )
    return chunks, context
