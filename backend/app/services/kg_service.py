"""KG extraction job orchestration.

Runs the full pipeline (chunk → extract → index → Quartz export) in the
background and publishes SSE stage events through KGSSEManager.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _node_slug(label: str) -> str:
    """Convert a node label to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", label.lower())
    return re.sub(r"[\s_-]+", "-", slug).strip("-") or "node"


async def run_kg_extraction(
    graph_id: str,
    title: str,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    model: str = "deepseek-v3.2",
) -> None:
    """
    Full KG extraction pipeline (to be run as a background asyncio task).

    Progress is emitted via kg_sse_manager.
    """
    from app.services.kg_sse_manager import kg_sse_manager
    from app.services.kg_extractor import (
        chunk_plain_text,
        extract_text_from_pdf,
        extract_graph,
    )
    from app.services.kg_store import save_chunks, save_graph, save_quartz_markdown

    await kg_sse_manager.publish(graph_id, "kg_started", "queued", {"message": "Job started"})

    try:
        # --- Stage 1: chunking ---
        await kg_sse_manager.publish(graph_id, "kg_progress", "chunking", {"message": "Splitting text into chunks"})
        if pdf_bytes:
            chunks = extract_text_from_pdf(pdf_bytes)
        elif text:
            chunks = chunk_plain_text(text)
        else:
            raise ValueError("Either text or pdf_bytes must be provided")

        save_chunks(graph_id, chunks)
        await kg_sse_manager.publish(
            graph_id, "kg_progress", "chunking",
            {"message": f"Created {len(chunks)} chunks", "chunk_count": len(chunks)},
        )

        # --- Stage 2: LLM extraction ---
        await kg_sse_manager.publish(graph_id, "kg_progress", "extracting", {"message": "Extracting graph with LLM"})
        graph = await extract_graph(graph_id, chunks, title, model=model)
        save_graph(graph)
        await kg_sse_manager.publish(
            graph_id, "kg_progress", "extracting",
            {
                "message": f"Extracted {len(graph.nodes)} nodes, {len(graph.edges)} edges",
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            },
        )

        # --- Stage 3: Quartz markdown export ---
        await kg_sse_manager.publish(graph_id, "kg_progress", "indexing", {"message": "Generating Quartz markdown"})

        node_id_map = {n.id: n for n in graph.nodes}
        nodes_md: list[tuple[str, str]] = []
        for node in graph.nodes:
            linked_ids = {e.target_id for e in graph.edges if e.source_id == node.id}
            linked_ids.update(e.source_id for e in graph.edges if e.target_id == node.id)
            links_md = "\n".join(
                f"- [[{_node_slug(node_id_map[lid].label)}]]"
                for lid in linked_ids
                if lid in node_id_map
            )
            refs_md = "\n".join(
                f"- Page {r.page}: _{r.span}_" for r in node.source_refs if r.span
            )
            md_content = (
                f"# {node.label}\n\n"
                f"{node.background_intro}\n\n"
                f"## Related Concepts\n\n{links_md or '_None_'}\n\n"
                f"## Source References\n\n{refs_md or '_None_'}\n"
            )
            filename = f"{_node_slug(node.label)}.md"
            nodes_md.append((filename, md_content))

        graph_json = {
            "nodes": [
                {"id": n.id, "label": n.label, "type": n.node_type}
                for n in graph.nodes
            ],
            "edges": [
                {"source": e.source_id, "target": e.target_id, "relation": e.relation}
                for e in graph.edges
            ],
        }
        save_quartz_markdown(graph_id, title, nodes_md, graph_json)

        # --- Done ---
        await kg_sse_manager.publish(
            graph_id, "kg_completed", "completed",
            {
                "message": "Extraction complete",
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "quartz_files": len(nodes_md) + 2,  # + index.md + graph.json
            },
        )

    except Exception as exc:
        logger.exception("KG extraction failed for graph %s: %s", graph_id, exc)
        await kg_sse_manager.publish(
            graph_id, "kg_failed", "failed",
            {"message": str(exc)},
        )
