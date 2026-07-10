from __future__ import annotations

import ast
import asyncio
import importlib
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.trackb import (
    TrackBArtifactsResponse,
    TrackBComparisonRequest,
    TrackBComparisonResponse,
    TrackBChatAskRequest,
    TrackBChatAskResponse,
    TrackBChatReportResponse,
    TrackBChatSessionCreateRequest,
    TrackBChatSessionCreateResponse,
    TrackBChatSessionResponse,
    TrackBHistoryResponse,
    TrackBH1CodeSection,
    TrackBH1ComponentsResponse,
    TrackBH1SourceSaveRequest,
    TrackBH1SourceSaveResponse,
    TrackBH2SourceResponse,
    TrackBH2SourceSaveRequest,
    TrackBH2SourceSaveResponse,
    TrackBH4SourceResponse,
    TrackBH4SourceSaveRequest,
    TrackBH4SourceSaveResponse,
    TrackBMetricsResponse,
    TrackBReproduceResponse,
    TrackBRunCreateRequest,
    TrackBRunCreateResponse,
    TrackBRunStatusResponse,
    TrackBUploadRunRequest,
)
from app.services.trackb_service import trackb_service
from app.utils.async_compat import to_thread


router = APIRouter(prefix="/api/v1/trackb", tags=["trackb"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _reload_trackb_workflow_modules() -> None:
    import phase2_llm_engine.financial_trackb_workflow as workflow_mod
    import phase2_llm_engine.trackb_harnesses.h4_evidence_verifier as h4_mod
    import phase2_llm_engine.trackb_harnesses.h2_prompt_base as h2_mod
    import phase2_llm_engine.trackb_harnesses.workflow as harness_workflow_mod

    importlib.reload(h4_mod)
    importlib.reload(h2_mod)
    importlib.reload(workflow_mod)
    importlib.reload(harness_workflow_mod)


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
    split_harnesses: str = Form(default="true"),
    h1_components: str = Form(default="[]"),
    h3_layers: str = Form(default="[]"),
) -> TrackBRunCreateResponse:
    try:
        parsed_profiles = json.loads(profiles)
        if not isinstance(parsed_profiles, list):
            raise ValueError("profiles must be a JSON array")
        parsed_h1_components = json.loads(h1_components)
        if not isinstance(parsed_h1_components, list):
            raise ValueError("h1_components must be a JSON array")
        parsed_h3_layers = json.loads(h3_layers)
        if not isinstance(parsed_h3_layers, list):
            raise ValueError("h3_layers must be a JSON array")
        split_value = split_harnesses.strip().lower()
        if split_value in {"true", "1", "yes", "on"}:
            parsed_split_harnesses = True
        elif split_value in {"false", "0", "no", "off"}:
            parsed_split_harnesses = False
        else:
            raise ValueError("split_harnesses must be a boolean string")
        req = TrackBUploadRunRequest(
            model=model,
            temperature=temperature,
            max_cases=max_cases,
            batch_size=batch_size,
            profiles=parsed_profiles,
            split_harnesses=parsed_split_harnesses,
            h1_components=parsed_h1_components,
            h3_layers=parsed_h3_layers,
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


@router.post("/chat/sessions/upload", response_model=TrackBChatSessionCreateResponse, status_code=201)
async def create_trackb_chat_session_upload(
    report_file: UploadFile = File(...),
    model: str = Form(default="DeepSeek-V3.2"),
    temperature: float = Form(default=0.0),
    h1_components: str = Form(default="[]"),
    h3_layers: str = Form(default="[]"),
) -> TrackBChatSessionCreateResponse:
    try:
        parsed_h1_components = json.loads(h1_components)
        if not isinstance(parsed_h1_components, list):
            raise ValueError("h1_components must be a JSON array")
        parsed_h3_layers = json.loads(h3_layers)
        if not isinstance(parsed_h3_layers, list):
            raise ValueError("h3_layers must be a JSON array")

        req = TrackBChatSessionCreateRequest(
            model=model,
            temperature=temperature,
            h1_components=parsed_h1_components,
            h3_layers=parsed_h3_layers,
        )

        with tempfile.TemporaryDirectory(prefix="trackb_chat_upload_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            report_path = tmp_root / (report_file.filename or "report.md")
            report_path.write_bytes(await report_file.read())
            return await trackb_service.create_chat_session(
                req,
                str(report_path),
                report_file.filename or "report.md",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Track B chat session create failed: {exc}") from exc


@router.post("/chat/sessions/{session_id}/ask", response_model=TrackBChatAskResponse)
async def ask_trackb_chat_session(
    session_id: str,
    req: TrackBChatAskRequest,
) -> TrackBChatAskResponse:
    try:
        return await to_thread(trackb_service.ask_chat_session, session_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B chat session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chat/sessions/{session_id}", response_model=TrackBChatSessionResponse)
async def get_trackb_chat_session(session_id: str) -> TrackBChatSessionResponse:
    try:
        return trackb_service.get_chat_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B chat session not found") from exc


@router.get("/chat/sessions/{session_id}/report", response_model=TrackBChatReportResponse)
async def get_trackb_chat_session_report(session_id: str) -> TrackBChatReportResponse:
    try:
        return trackb_service.get_chat_session_report(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B chat session not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/harnesses/h1/components", response_model=TrackBH1ComponentsResponse)
async def get_h1_harness_components() -> TrackBH1ComponentsResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h1_code_base.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H1 harness source file not found")

    full_source = source_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(full_source)
    except SyntaxError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse H1 harness source: {exc}") from exc

    lines = full_source.splitlines()
    sections: list[TrackBH1CodeSection] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "function"
        elif isinstance(node, ast.ClassDef):
            kind = "class"
        else:
            continue

        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        snippet = "\n".join(lines[start - 1 : end])
        sections.append(
            TrackBH1CodeSection(
                name=node.name,
                kind=kind,
                start_line=start,
                end_line=end,
                source=snippet,
            )
        )

    return TrackBH1ComponentsResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h1_code_base.py",
        full_source=full_source,
        sections=sections,
    )


@router.put("/harnesses/h1/source", response_model=TrackBH1SourceSaveResponse)
async def save_h1_harness_source(req: TrackBH1SourceSaveRequest) -> TrackBH1SourceSaveResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h1_code_base.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H1 harness source file not found")

    source_path.write_text(req.full_source, encoding="utf-8")
    return TrackBH1SourceSaveResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h1_code_base.py",
        bytes_written=len(req.full_source.encode("utf-8")),
    )


@router.get("/harnesses/h2/source", response_model=TrackBH2SourceResponse)
async def get_h2_harness_source() -> TrackBH2SourceResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h2_prompt_base.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H2 harness source file not found")

    return TrackBH2SourceResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h2_prompt_base.py",
        full_source=source_path.read_text(encoding="utf-8"),
    )


@router.put("/harnesses/h2/source", response_model=TrackBH2SourceSaveResponse)
async def save_h2_harness_source(req: TrackBH2SourceSaveRequest) -> TrackBH2SourceSaveResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h2_prompt_base.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H2 harness source file not found")

    try:
        tree = ast.parse(req.full_source)
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"H2 source has syntax error: {exc}") from exc

    required_names = {"build_h2_prompt", "build_numeric_hint"}
    declared = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    missing = sorted(required_names - declared)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "H2 source is missing required definitions: "
                + ", ".join(missing)
            ),
        )

    previous = source_path.read_text(encoding="utf-8")
    source_path.write_text(req.full_source, encoding="utf-8")

    try:
        _reload_trackb_workflow_modules()
    except Exception as exc:  # noqa: BLE001
        source_path.write_text(previous, encoding="utf-8")
        try:
            _reload_trackb_workflow_modules()
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"H2 source reload failed; change rolled back: {exc}",
        ) from exc

    return TrackBH2SourceSaveResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h2_prompt_base.py",
        bytes_written=len(req.full_source.encode("utf-8")),
        runtime_refreshed=True,
    )


@router.get("/harnesses/h4/source", response_model=TrackBH4SourceResponse)
async def get_h4_harness_source() -> TrackBH4SourceResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h4_evidence_verifier.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H4 harness source file not found")

    return TrackBH4SourceResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.py",
        full_source=source_path.read_text(encoding="utf-8"),
    )


@router.put("/harnesses/h4/source", response_model=TrackBH4SourceSaveResponse)
async def save_h4_harness_source(req: TrackBH4SourceSaveRequest) -> TrackBH4SourceSaveResponse:
    repo_root = Path(__file__).resolve().parents[4]
    source_path = repo_root / "phase2_llm_engine" / "trackb_harnesses" / "h4_evidence_verifier.py"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="H4 harness source file not found")

    candidate = req.full_source.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="H4 source cannot be empty")

    try:
        tree = ast.parse(req.full_source)
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"H4 source has syntax error: {exc}") from exc

    required_names = {
        "verify_support",
        "repair_answer_deterministic",
        "h2_numeric_guard",
    }
    declared = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    missing = sorted(required_names - declared)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "H4 source is missing required definitions: "
                + ", ".join(missing)
            ),
        )

    previous = source_path.read_text(encoding="utf-8")
    source_path.write_text(req.full_source, encoding="utf-8")

    try:
        _reload_trackb_workflow_modules()
    except Exception as exc:  # noqa: BLE001
        source_path.write_text(previous, encoding="utf-8")
        try:
            _reload_trackb_workflow_modules()
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"H4 source reload failed; change rolled back: {exc}",
        ) from exc

    return TrackBH4SourceSaveResponse(
        source_path="phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.py",
        bytes_written=len(req.full_source.encode("utf-8")),
        runtime_refreshed=True,
    )


@router.get("/runs/{run_id}", response_model=TrackBRunStatusResponse)
async def get_trackb_run(run_id: str) -> TrackBRunStatusResponse:
    try:
        return trackb_service.get_status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Track B run not found") from exc


@router.post("/runs/{run_id}/cancel", response_model=TrackBRunStatusResponse)
async def cancel_trackb_run(run_id: str) -> TrackBRunStatusResponse:
    try:
        return await trackb_service.cancel_run(run_id)
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
