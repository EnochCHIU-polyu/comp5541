"""Harness 2 – Knowledge Graph Retriever.

Given a node_id (and optional extra query text), retrieve the top-k most
relevant text chunks from the corpus stored for that graph, then use the
LLM to generate a faithful, evidence-grounded explanation.

Reuses the TF-IDF pattern from phase2_llm_engine.verification_rag.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from app.services.kg_store import load_chunks, load_graph

logger = logging.getLogger(__name__)
_NODE_DETAIL_CACHE: dict[tuple[str, str, str, int, str], dict] = {}
_MIN_EVIDENCE_SCORE = 0.08

# ---------------------------------------------------------------------------
# TF-IDF retrieval
# ---------------------------------------------------------------------------

def _tfidf_retrieve(chunks: list[dict], query: str, top_k: int = 5) -> list[dict]:
    """
    Return top-k chunks most similar to *query* using TF-IDF + cosine similarity.

    Each returned chunk gets an extra 'score' key.
    """
    if not chunks:
        return []

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    texts = [c.get("text", "") for c in chunks]
    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=8000)
        tfidf_matrix = vectorizer.fit_transform(texts)
        query_vec = vectorizer.transform([query])
        scores = cosine_similarity(query_vec, tfidf_matrix)[0]
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0.0:
                chunk = dict(chunks[idx])
                chunk["score"] = float(round(scores[idx], 4))
                results.append(chunk)
        return results
    except Exception as exc:
        logger.warning("TF-IDF retrieval failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LLM explanation generation
# ---------------------------------------------------------------------------

_EXPLANATION_SYSTEM = """\
You are a knowledgeable tutor. Your task is to explain a concept to a student \
using ONLY the provided source passages. If the passages do not contain \
sufficient information, output exactly: EVIDENCE_INSUFFICIENT

Rules:
1. Base your explanation ONLY on the provided passages – do not add outside knowledge.
2. Keep the explanation concise (3-6 sentences).
3. If evidence is insufficient, output exactly the string EVIDENCE_INSUFFICIENT.
"""


def _build_explanation_prompt(label: str, background_intro: str, evidence_texts: list[str]) -> str:
    evidence_block = "\n\n".join(
        f"[PASSAGE {i+1}]\n{t[:1200]}" for i, t in enumerate(evidence_texts)
    )
    return (
        f"Concept: {label}\n"
        f"Background: {background_intro}\n\n"
        f"SOURCE PASSAGES:\n{evidence_block}\n\n"
        f"Explain '{label}' based only on the passages above."
    )


def _call_explanation_llm(label: str, background_intro: str, evidence_texts: list[str], model: str) -> str:
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from phase2_llm_engine.llm_client import query_llm  # noqa: PLC0415

    messages = [
        {"role": "system", "content": _EXPLANATION_SYSTEM},
        {"role": "user", "content": _build_explanation_prompt(label, background_intro, evidence_texts)},
    ]
    return query_llm(messages, model=model, temperature=0.1, max_tokens=1024)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_node_details(
    graph_id: str,
    node_id: str,
    query: Optional[str] = None,
    top_k: int = 5,
    model: str = "deepseek-v3.2",
) -> dict:
    """
    Retrieve top-k evidence chunks for a node and generate a faithful explanation.

    Returns a dict with keys: node_id, label, background_intro, explanation, evidence.
    """
    cache_key = (graph_id, node_id, query or "", top_k, model)
    cached = _NODE_DETAIL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    graph = load_graph(graph_id)
    if graph is None:
        return {"error": f"Graph {graph_id} not found"}

    node = next((n for n in graph.nodes if n.id == node_id), None)
    if node is None:
        return {"error": f"Node {node_id} not found in graph {graph_id}"}

    chunks = load_chunks(graph_id)

    search_query = f"{node.label} {node.background_intro} {query or ''}".strip()
    top_chunks = _tfidf_retrieve(chunks, search_query, top_k=top_k)

    evidence = [
        {
            "chunk_id": c.get("chunk_id", ""),
            "page": c.get("page", 0),
            "score": c.get("score", 0.0),
            "text": c.get("text", "")[:600],
        }
        for c in top_chunks
    ]

    if not top_chunks:
        explanation = "EVIDENCE_INSUFFICIENT"
    elif float(top_chunks[0].get("score", 0.0)) < _MIN_EVIDENCE_SCORE:
        explanation = "EVIDENCE_INSUFFICIENT"
    else:
        evidence_texts = [c.get("text", "") for c in top_chunks]
        try:
            explanation = await asyncio.to_thread(
                _call_explanation_llm,
                node.label,
                node.background_intro,
                evidence_texts,
                model,
            )
        except Exception as exc:
            logger.error("Explanation LLM failed for node %s: %s", node_id, exc)
            explanation = "EVIDENCE_INSUFFICIENT"

    result = {
        "node_id": node_id,
        "label": node.label,
        "background_intro": node.background_intro,
        "explanation": explanation,
        "evidence": evidence,
    }
    _NODE_DETAIL_CACHE[cache_key] = result
    return result
