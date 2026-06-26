"""Harness 1 – Knowledge Graph Extractor.

Pipeline:
  raw text / PDF bytes → text chunks with page metadata
  → strict LLM prompt → JSON graph (nodes, edges, background_intro, source_refs)
  → KGGraph

Reuses the code-fence stripping pattern from phase2_llm_engine.output_parser.
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from typing import Optional

from app.schemas.kg import KGEdge, KGGraph, KGNode, SourceRef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF / text chunking
# ---------------------------------------------------------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Extract pages from a PDF and return a list of chunk dicts.

    Each chunk: {chunk_id, page, text}
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF extraction. Run: pip install pypdf") from exc

    reader = PdfReader(io.BytesIO(pdf_bytes))
    chunks: list[dict] = []
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()
        if not text:
            continue
        chunks.append({
            "chunk_id": f"p{page_num}",
            "page": page_num,
            "text": text,
        })
    return chunks


def chunk_plain_text(text: str, max_chars: int = 2000, overlap: int = 200) -> list[dict]:
    """
    Split plain text into overlapping chunks.

    Returns list of {chunk_id, page, text}.
    """
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[dict] = []
    current = ""
    chunk_idx = 1

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append({"chunk_id": f"c{chunk_idx}", "page": chunk_idx, "text": current})
            chunk_idx += 1
            # Keep overlap from the end
            current = current[-overlap:] + "\n\n" + para if overlap else para
        else:
            current = (current + "\n\n" + para).strip() if current else para

    if current:
        chunks.append({"chunk_id": f"c{chunk_idx}", "page": chunk_idx, "text": current})

    return chunks


# ---------------------------------------------------------------------------
# LLM extraction prompt
# ---------------------------------------------------------------------------

_KG_SYSTEM_PROMPT = """\
You are an expert knowledge engineer. Given lecture / textbook text chunks, \
extract a structured knowledge graph.

OUTPUT FORMAT (strict JSON, no markdown wrapper):
{
  "nodes": [
    {
      "id": "<slug, e.g. 'reentrancy'>",
      "label": "<human-readable name>",
      "node_type": "<concept|person|event|formula|other>",
      "background_intro": "<2-3 sentences explaining this concept>",
      "source_refs": [
        {"chunk_id": "<chunk_id>", "page": <int>, "span": "<short quoted phrase>"}
      ]
    }
  ],
  "edges": [
    {
      "source_id": "<node id>",
      "target_id": "<node id>",
      "relation": "<e.g. 'requires', 'causes', 'is_part_of'>",
      "weight": <float 0.0-1.0>
    }
  ]
}

RULES:
1. Extract 5-20 nodes (key concepts only – avoid trivial terms).
2. Each node MUST include a background_intro and at least one source_ref citing a chunk_id.
3. Edges must reference existing node ids only.
4. Output ONLY the JSON object – no preamble, no code fences.
"""


def _build_kg_prompt(chunks: list[dict], title: str) -> str:
    chunk_text = "\n\n".join(
        f"[CHUNK {c['chunk_id']} | page {c['page']}]\n{c['text'][:1500]}"
        for c in chunks[:20]  # cap at 20 chunks per call
    )
    return (
        f"Document title: {title}\n\n"
        f"TEXT CHUNKS:\n{chunk_text}\n\n"
        "Extract the knowledge graph from the above text."
    )


# ---------------------------------------------------------------------------
# Response parser (reuses code-fence stripping from output_parser)
# ---------------------------------------------------------------------------

def _strip_code_fence(raw: str) -> str:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return m.group(1)
    m2 = re.search(r"\{.*\}", raw, re.DOTALL)
    if m2:
        return m2.group(0)
    return raw.strip()


def _parse_kg_response(raw: str, chunks: list[dict]) -> tuple[list[KGNode], list[KGEdge]]:
    """Parse LLM JSON into KGNode / KGEdge lists."""
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("KG JSON parse failed: %s | raw=%s", exc, raw[:300])
        return [], []

    chunk_map = {c["chunk_id"]: c for c in chunks}

    nodes: list[KGNode] = []
    node_ids: set[str] = set()
    for raw_node in data.get("nodes", []):
        node_id = str(raw_node.get("id", "")).strip()
        if not node_id:
            continue
        refs: list[SourceRef] = []
        for sr in raw_node.get("source_refs", []):
            cid = str(sr.get("chunk_id", ""))
            chunk = chunk_map.get(cid, {})
            refs.append(SourceRef(
                chunk_id=cid,
                page=int(sr.get("page", chunk.get("page", 0))),
                span=str(sr.get("span", ""))[:300],
                text=chunk.get("text", ""),
            ))
        nodes.append(KGNode(
            id=node_id,
            label=str(raw_node.get("label", node_id)),
            node_type=str(raw_node.get("node_type", "concept")),
            background_intro=str(raw_node.get("background_intro", "")),
            source_refs=refs,
        ))
        node_ids.add(node_id)

    edges: list[KGEdge] = []
    for raw_edge in data.get("edges", []):
        src = str(raw_edge.get("source_id", ""))
        tgt = str(raw_edge.get("target_id", ""))
        if src not in node_ids or tgt not in node_ids:
            continue
        edges.append(KGEdge(
            source_id=src,
            target_id=tgt,
            relation=str(raw_edge.get("relation", "related_to")),
            weight=float(raw_edge.get("weight", 1.0)),
        ))

    return nodes, edges


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

async def extract_graph(
    graph_id: str,
    chunks: list[dict],
    title: str,
    model: str = "deepseek-v3.2",
) -> KGGraph:
    """
    Call the LLM to extract a KGGraph from pre-built chunks.

    Uses the same LLM client as the audit pipeline.
    """
    import asyncio
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import asyncio
    from phase2_llm_engine.llm_client import query_llm

    prompt = _build_kg_prompt(chunks, title)
    messages = [
        {"role": "system", "content": _KG_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_response = await asyncio.to_thread(
            query_llm, messages, model, 0.2, 4096
        )
    except Exception as exc:
        logger.error("LLM call failed for graph %s: %s", graph_id, exc)
        raise

    nodes, edges = _parse_kg_response(raw_response, chunks)

    from datetime import datetime
    return KGGraph(
        graph_id=graph_id,
        title=title,
        nodes=nodes,
        edges=edges,
        created_at=datetime.utcnow(),
    )
