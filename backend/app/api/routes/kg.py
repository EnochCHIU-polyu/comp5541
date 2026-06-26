"""API routes for the Knowledge Graph (KG) learning system."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.schemas.kg import (
    KGExtractResponse,
    KGGraphResponse,
    KGNodeDetailResponse,
    KGSnapshot,
)
from app.services.kg_sse_manager import kg_sse_manager
from app.services.kg_store import load_graph, _quartz_dir

router = APIRouter(prefix="/api/v1/kg", tags=["knowledge-graph"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Extract (create) a new KG job
# ---------------------------------------------------------------------------

@router.post("/extract", response_model=KGExtractResponse)
async def extract_kg(
    title: str = Form(default="Untitled Document"),
    model: str = Form(default="deepseek-v3.2"),
    text: str = Form(default=""),
    file: UploadFile | None = None,
) -> KGExtractResponse:
    """
    Start a KG extraction job.  Supply either:
    - `text` (plain text) via form field, or
    - `file` (PDF upload).

    Returns a `graph_id` that can be used to stream progress and query results.
    """
    if not text and file is None:
        raise HTTPException(status_code=422, detail="Provide either 'text' or 'file'.")

    graph_id = str(uuid.uuid4())
    kg_sse_manager.create_job(graph_id)

    pdf_bytes: bytes | None = None
    plain_text: str | None = None

    if file is not None:
        pdf_bytes = await file.read()
    else:
        plain_text = text.strip() or None

    if not pdf_bytes and not plain_text:
        raise HTTPException(status_code=422, detail="Uploaded file is empty or text is blank.")

    from app.services.kg_service import run_kg_extraction

    asyncio.create_task(
        run_kg_extraction(
            graph_id=graph_id,
            title=title,
            text=plain_text,
            pdf_bytes=pdf_bytes,
            model=model,
        )
    )

    return KGExtractResponse(graph_id=graph_id, status="queued")


# ---------------------------------------------------------------------------
# SSE stream for a job
# ---------------------------------------------------------------------------

@router.get("/{graph_id}/stream")
async def stream_kg_events(graph_id: str) -> StreamingResponse:
    if not kg_sse_manager.exists(graph_id):
        raise HTTPException(status_code=404, detail="KG job not found")

    queue = await kg_sse_manager.subscribe(graph_id)

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield _sse_format(event.event, event.model_dump(mode="json"))
                    if event.event in {"kg_completed", "kg_failed"}:
                        break
                except asyncio.TimeoutError:
                    yield _sse_format("ping", {"graph_id": graph_id})
        finally:
            await kg_sse_manager.unsubscribe(graph_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Snapshot (non-streaming status)
# ---------------------------------------------------------------------------

@router.get("/{graph_id}/snapshot", response_model=KGSnapshot)
async def get_kg_snapshot(graph_id: str) -> KGSnapshot:
    if not kg_sse_manager.exists(graph_id):
        raise HTTPException(status_code=404, detail="KG job not found")
    return kg_sse_manager.snapshot(graph_id)


# ---------------------------------------------------------------------------
# Retrieve the full graph
# ---------------------------------------------------------------------------

@router.get("/{graph_id}/graph", response_model=KGGraphResponse)
async def get_kg_graph(graph_id: str) -> KGGraphResponse:
    graph = load_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Graph not found")
    return KGGraphResponse(
        graph_id=graph.graph_id,
        title=graph.title,
        nodes=graph.nodes,
        edges=graph.edges,
        created_at=graph.created_at,
    )


# ---------------------------------------------------------------------------
# Node detail (Harness 2)
# ---------------------------------------------------------------------------

@router.get("/{graph_id}/nodes/{node_id}", response_model=KGNodeDetailResponse)
async def get_node_detail(
    graph_id: str,
    node_id: str,
    query: str = Query(default="", max_length=500),
    top_k: int = Query(default=5, ge=1, le=20),
    model: str = Query(default="deepseek-v3.2"),
) -> KGNodeDetailResponse:
    from app.services.kg_retriever import get_node_details

    result = await get_node_details(
        graph_id=graph_id,
        node_id=node_id,
        query=query or None,
        top_k=top_k,
        model=model,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return KGNodeDetailResponse(**result)


# ---------------------------------------------------------------------------
# Quartz export download (returns graph.json)
# ---------------------------------------------------------------------------

@router.get("/{graph_id}/quartz/graph.json")
async def get_quartz_graph_json(graph_id: str):
    from app.services.kg_store import _safe_graph_id
    try:
        safe_id = _safe_graph_id(graph_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid graph_id format")
    path = _quartz_dir(safe_id) / "graph.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Quartz export not ready")
    return FileResponse(str(path), media_type="application/json")
