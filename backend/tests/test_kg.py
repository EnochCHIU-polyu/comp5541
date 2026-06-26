"""Tests for the Knowledge Graph API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /api/v1/kg/extract
# ---------------------------------------------------------------------------


def test_extract_requires_text_or_file() -> None:
    """POST without text or file should return 422."""
    response = client.post(
        "/api/v1/kg/extract",
        data={"title": "Test"},
    )
    assert response.status_code == 422


def test_extract_with_text_queues_job() -> None:
    """POST with plain text should return a graph_id and 'queued' status."""
    with patch("app.services.kg_service.run_kg_extraction", new_callable=AsyncMock):
        response = client.post(
            "/api/v1/kg/extract",
            data={
                "title": "Test Document",
                "text": "Reentrancy is a critical vulnerability in Solidity contracts.",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "graph_id" in data
    assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# /api/v1/kg/{graph_id}/snapshot
# ---------------------------------------------------------------------------


def test_snapshot_not_found() -> None:
    response = client.get("/api/v1/kg/00000000-0000-0000-0000-000000000000/snapshot")
    assert response.status_code == 404


def test_snapshot_exists_after_create() -> None:
    with patch("app.services.kg_service.run_kg_extraction", new_callable=AsyncMock):
        create_resp = client.post(
            "/api/v1/kg/extract",
            data={"title": "T", "text": "hello world"},
        )
    assert create_resp.status_code == 200
    graph_id = create_resp.json()["graph_id"]

    snap_resp = client.get(f"/api/v1/kg/{graph_id}/snapshot")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert snap["graph_id"] == graph_id
    assert snap["status"] in {"queued", "running", "completed", "failed"}


# ---------------------------------------------------------------------------
# /api/v1/kg/{graph_id}/graph
# ---------------------------------------------------------------------------


def test_graph_not_found() -> None:
    response = client.get("/api/v1/kg/00000000-0000-0000-0000-000000000001/graph")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# kg_extractor unit tests
# ---------------------------------------------------------------------------


def test_chunk_plain_text() -> None:
    from app.services.kg_extractor import chunk_plain_text

    long_text = ("This is paragraph number {}.\n\n" * 30).format(*range(30))
    chunks = chunk_plain_text(long_text, max_chars=500)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "text" in chunk
        assert "page" in chunk


def test_strip_code_fence() -> None:
    from app.services.kg_extractor import _strip_code_fence

    raw = '```json\n{"nodes": [], "edges": []}\n```'
    stripped = _strip_code_fence(raw)
    assert stripped.startswith("{")
    assert "nodes" in stripped


def test_parse_kg_response_valid() -> None:
    from app.services.kg_extractor import _parse_kg_response

    chunks = [{"chunk_id": "c1", "page": 1, "text": "Reentrancy example"}]
    raw = """{
        "nodes": [
            {
                "id": "reentrancy",
                "label": "Reentrancy",
                "node_type": "concept",
                "background_intro": "A critical vulnerability.",
                "source_refs": [{"chunk_id": "c1", "page": 1, "span": "Reentrancy"}]
            }
        ],
        "edges": []
    }"""
    nodes, edges = _parse_kg_response(raw, chunks)
    assert len(nodes) == 1
    assert nodes[0].id == "reentrancy"
    assert len(edges) == 0


def test_parse_kg_response_bad_json() -> None:
    from app.services.kg_extractor import _parse_kg_response

    nodes, edges = _parse_kg_response("not json at all", [])
    assert nodes == []
    assert edges == []


def test_parse_kg_response_rejects_dangling_edges() -> None:
    from app.services.kg_extractor import _parse_kg_response

    chunks = [{"chunk_id": "c1", "page": 1, "text": "text"}]
    raw = """{
        "nodes": [{"id": "a", "label": "A", "background_intro": "", "source_refs": []}],
        "edges": [{"source_id": "a", "target_id": "does_not_exist", "relation": "causes"}]
    }"""
    nodes, edges = _parse_kg_response(raw, chunks)
    assert len(nodes) == 1
    assert len(edges) == 0  # edge referencing unknown node must be dropped


# ---------------------------------------------------------------------------
# kg_retriever unit tests
# ---------------------------------------------------------------------------


def test_tfidf_retrieve_returns_topk() -> None:
    from app.services.kg_retriever import _tfidf_retrieve

    chunks = [
        {"chunk_id": "c1", "page": 1, "text": "Reentrancy attack drains funds via callback loops"},
        {"chunk_id": "c2", "page": 2, "text": "Integer overflow causes unexpected arithmetic"},
        {"chunk_id": "c3", "page": 3, "text": "Access control missing on admin functions"},
    ]
    results = _tfidf_retrieve(chunks, "reentrancy callback", top_k=2)
    assert len(results) >= 1
    assert results[0]["chunk_id"] == "c1"
    assert "score" in results[0]


def test_tfidf_retrieve_empty_corpus() -> None:
    from app.services.kg_retriever import _tfidf_retrieve

    results = _tfidf_retrieve([], "anything", top_k=5)
    assert results == []
