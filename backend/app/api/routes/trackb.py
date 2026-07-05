from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.trackb import (
    TrackBArtifactsResponse,
    TrackBComparisonRequest,
    TrackBComparisonResponse,
    TrackBHistoryResponse,
    TrackBMetricsResponse,
    TrackBReproduceResponse,
    TrackBRunCreateRequest,
    TrackBRunCreateResponse,
    TrackBRunStatusResponse,
    TrackBUploadRunRequest,
)
from app.services.trackb_service import trackb_service


router = APIRouter(prefix="/api/v1/trackb", tags=["trackb"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/runs", response_model=TrackBRunCreateResponse, status_code=202)
async def create_trackb_run(req: TrackBRunCreateRequest) -> TrackBRunCreateResponse:
    try:
        return await trackb_service.create_run(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/upload", response_model=TrackBRunCreateResponse, status_code=202)
async def create_trackb_run_upload(
    report_file: UploadFile = File(...),
    cases_file: UploadFile = File(...),
    model: str = Form(default="DeepSeek-V3.2"),
    temperature: float = Form(default=0.0),
    max_cases: int = Form(default=0),
    batch_size: int = Form(default=1),
    profiles: str = Form(default='["baseline"]'),
) -> TrackBRunCreateResponse:
    try:
        parsed_profiles = json.loads(profiles)
        if not isinstance(parsed_profiles, list):
            raise ValueError("profiles must be a JSON array")
        req = TrackBUploadRunRequest(
            model=model,
            temperature=temperature,
            max_cases=max_cases,
            batch_size=batch_size,
            profiles=parsed_profiles,
        )

        with tempfile.TemporaryDirectory(prefix="trackb_upload_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            report_path = tmp_root / report_file.filename
            cases_path = tmp_root / cases_file.filename
            report_path.write_bytes(await report_file.read())
            cases_path.write_bytes(await cases_file.read())
            return await trackb_service.create_uploaded_run(
                req,
                str(report_path),
                report_file.filename or "report.pdf",
                str(cases_path),
                cases_file.filename or "cases.jsonl",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Track B upload run failed: {exc}") from exc


@router.get("/runs/{run_id}", response_model=TrackBRunStatusResponse)
async def get_trackb_run(run_id: str) -> TrackBRunStatusResponse:
    try:
        return trackb_service.get_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc


@router.get("/runs/{run_id}/metrics", response_model=TrackBMetricsResponse)
async def get_trackb_metrics(run_id: str) -> TrackBMetricsResponse:
    try:
        return TrackBMetricsResponse(run_id=run_id, metrics_by_profile=trackb_service.get_metrics(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc


@router.get("/runs/{run_id}/artifacts", response_model=TrackBArtifactsResponse)
async def get_trackb_artifacts(run_id: str) -> TrackBArtifactsResponse:
    try:
        data = trackb_service.get_artifacts(run_id)
        return TrackBArtifactsResponse(
            run_id=run_id,
            output_dir=data["output_dir"],
            artifacts=data["artifacts"],
            profiles=data.get("profiles", []),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc


@router.get("/runs/{run_id}/reproduce", response_model=TrackBReproduceResponse)
async def get_trackb_reproduce(run_id: str) -> TrackBReproduceResponse:
    try:
        return trackb_service.reproduce(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc


@router.post("/compare", response_model=TrackBComparisonResponse)
async def compare_trackb_runs(req: TrackBComparisonRequest) -> TrackBComparisonResponse:
    try:
        return trackb_service.compare(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history", response_model=TrackBHistoryResponse)
async def get_trackb_history(limit: int = 20) -> TrackBHistoryResponse:
    return trackb_service.get_history(limit=limit)


@router.get("/runs/{run_id}/stream")
async def stream_trackb_events(run_id: str) -> StreamingResponse:
    try:
        queue = await trackb_service.subscribe(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    payload = event.model_dump(mode="json")
                    yield _sse_format(event.event, payload)
                    if event.event in {"trackb_completed", "trackb_failed"}:
                        break
                except asyncio.TimeoutError:
                    heartbeat = {
                        "run_id": run_id,
                        "event": "ping",
                        "stage": "running",
                        "seq": -1,
                        "payload": {},
                    }
                    yield _sse_format("ping", heartbeat)
        finally:
            await trackb_service.unsubscribe(run_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
