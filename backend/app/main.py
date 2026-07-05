from __future__ import annotations

import logging
import os
from typing import Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .bootstrap import ensure_project_root_importable


if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

ensure_project_root_importable()

from .api.routes.audits import router as audits_router
from .api.routes.benchmark import router as benchmark_router
from .api.routes.trackb import router as trackb_router
from .api.routes.vulnerabilities import router as vulnerabilities_router


def _cors_origins() -> list[str]:
    raw = os.getenv("BACKEND_CORS_ORIGINS", "*").strip()
    if not raw:
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


app = FastAPI(
    title="Aegis Security Audit API",
    version="0.2.0",
    description="Backend API for audit streaming, benchmark execution, and vulnerability intake.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audits_router)
app.include_router(benchmark_router)
app.include_router(trackb_router)
app.include_router(vulnerabilities_router)


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}
