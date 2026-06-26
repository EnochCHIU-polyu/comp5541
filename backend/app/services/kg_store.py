"""JSONL / JSON file storage for KG graphs and chunk corpora."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from app.schemas.kg import KGGraph

logger = logging.getLogger(__name__)

_KG_STORE_DIR = Path(os.getenv("KG_STORE_DIR", "data/kg_store"))


def _graph_path(graph_id: str) -> Path:
    return _KG_STORE_DIR / "graphs" / f"{graph_id}.json"


def _chunks_path(graph_id: str) -> Path:
    return _KG_STORE_DIR / "chunks" / f"{graph_id}.jsonl"


def _quartz_dir(graph_id: str) -> Path:
    return _KG_STORE_DIR / "quartz" / graph_id


def save_graph(graph: KGGraph) -> None:
    path = _graph_path(graph.graph_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved KG graph %s to %s", graph.graph_id, path)


def load_graph(graph_id: str) -> Optional[KGGraph]:
    path = _graph_path(graph_id)
    if not path.exists():
        return None
    try:
        return KGGraph.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load graph %s: %s", graph_id, exc)
        return None


def save_chunks(graph_id: str, chunks: list[dict]) -> None:
    path = _chunks_path(graph_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk) + "\n")
    logger.info("Saved %d chunks for graph %s", len(chunks), graph_id)


def load_chunks(graph_id: str) -> list[dict]:
    path = _chunks_path(graph_id)
    if not path.exists():
        return []
    chunks: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return chunks


def save_quartz_markdown(graph_id: str, title: str, nodes_md: list[tuple[str, str]], graph_json: dict) -> None:
    """
    Write per-node markdown files and graph.json to the Quartz output directory.

    nodes_md: list of (filename, markdown_content) tuples
    """
    out_dir = _quartz_dir(graph_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in nodes_md:
        (out_dir / filename).write_text(content, encoding="utf-8")

    (out_dir / "graph.json").write_text(json.dumps(graph_json, ensure_ascii=False, indent=2), encoding="utf-8")

    index_md = f"# {title}\n\nKnowledge graph exported from StudyFlow.\n\n" + "\n".join(
        f"- [[{fn.replace('.md', '')}]]" for fn, _ in nodes_md
    )
    (out_dir / "index.md").write_text(index_md, encoding="utf-8")
    logger.info("Quartz export for graph %s written to %s", graph_id, out_dir)
