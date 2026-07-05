from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.schemas.harness2 import (
    Harness2BuildRequest,
    Harness2BuildResponse,
    Harness2HistoryResponse,
    Harness2UploadBuildRequest,
)
from app.services.harness2_history_service import harness2_history_service
from app.utils.async_compat import to_thread


router = APIRouter(prefix="/api/v1/harness2", tags=["harness2"])


@router.post("/history/build", response_model=Harness2BuildResponse)
async def build_harness2_history(req: Harness2BuildRequest) -> Harness2BuildResponse:
    try:
        return await to_thread(harness2_history_service.build_history_bundle, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Harness 2 build failed: {exc}") from exc


@router.post("/history/upload-build", response_model=Harness2BuildResponse)
async def build_harness2_history_upload(
    source_file: UploadFile = File(...),
    symbol: str = Form(...),
    max_reports: int = Form(default=5),
    horizon_days: int = Form(default=30),
    analysis_profile: str = Form(default="baseline"),
    model: str = Form(default="deepseek-v4-flash"),
    temperature: float = Form(default=0.0),
) -> Harness2BuildResponse:
    try:
        req = Harness2UploadBuildRequest(
            symbol=symbol,
            max_reports=max_reports,
            horizon_days=horizon_days,
            analysis_profile=analysis_profile,
            model=model,
            temperature=temperature,
        )

        with tempfile.TemporaryDirectory(prefix="harness2_upload_") as tmp_dir:
            tmp_path = Path(tmp_dir) / (source_file.filename or "source.md")
            tmp_path.write_bytes(await source_file.read())
            return await to_thread(
                harness2_history_service.build_history_bundle_from_file,
                req,
                str(tmp_path),
                source_file.filename or "source.md",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Harness 2 upload build failed: {exc}") from exc


@router.get("/history", response_model=Harness2HistoryResponse)
async def get_harness2_history(
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
) -> Harness2HistoryResponse:
    try:
        return await to_thread(
            harness2_history_service.get_history,
            limit,
            q,
            symbol,
            sort,
            order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Harness 2 history lookup failed: {exc}") from exc
