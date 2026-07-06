from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib
import json
import os
import re
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
import shutil
import subprocess
import sys

from app.schemas.trackb import (
    TrackBChatAskRequest,
    TrackBChatAskResponse,
    TrackBChatProfileAnswer,
    TrackBChatReportResponse,
    TrackBChatSessionCreateRequest,
    TrackBChatSessionCreateResponse,
    TrackBChatSessionResponse,
    TrackBChatTurn,
    TrackBH1ComponentConfig,
    TrackBH3LayerConfig,
    TrackBComparisonRequest,
    TrackBComparisonResponse,
    TrackBEvent,
    TrackBHistoryResponse,
    TrackBProfile,
    TrackBProfileProgress,
    TrackBReproduceResponse,
    TrackBRunCreateRequest,
    TrackBRunCreateResponse,
    TrackBRunStatusResponse,
    TrackBUploadRunRequest,
)
from app.utils.async_compat import to_thread


@dataclass
class TrackBRunState:
    run_id: str
    created_at: datetime
    report_path: str
    cases_path: str
    model: str
    temperature: float
    max_cases: int
    batch_size: int
    profiles: List[TrackBProfile]
    h1_components: List[TrackBH1ComponentConfig] = field(default_factory=list)
    h3_layers: List[TrackBH3LayerConfig] = field(default_factory=list)
    status: str = "queued"
    stage: str = "queued"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    seq: int = 0
    error: Optional[str] = None
    progress: Dict[str, TrackBProfileProgress] = field(default_factory=dict)
    events: List[TrackBEvent] = field(default_factory=list)
    metrics_by_profile: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    profile_output_dirs: Dict[str, str] = field(default_factory=dict)


@dataclass
class TrackBChatSessionState:
    session_id: str
    created_at: datetime
    report_path: str
    report_name: str
    model: str
    temperature: float
    h1_components: List[TrackBH1ComponentConfig] = field(default_factory=list)
    h3_layers: List[TrackBH3LayerConfig] = field(default_factory=list)
    turns: List[TrackBChatTurn] = field(default_factory=list)


class TrackBService:
    def __init__(self) -> None:
        self._runs: Dict[str, TrackBRunState] = {}
        self._queues: Dict[str, List[asyncio.Queue[TrackBEvent]]] = {}
        self._run_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._cancel_reasons: Dict[str, str] = {}
        self._chat_sessions: Dict[str, TrackBChatSessionState] = {}
        self._lock = threading.Lock()

    def _current_cancel_reason(self, run_id: str) -> str:
        with self._lock:
            return self._cancel_reasons.get(run_id, "Track B run cancelled")

    def _is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._cancel_reasons

    def _raise_if_cancelled(self, run_id: str) -> None:
        if self._is_cancelled(run_id):
            raise asyncio.CancelledError(self._current_cancel_reason(run_id))

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _resolve_path(self, raw: str) -> str:
        p = Path(raw)
        if p.exists():
            return str(p)
        alt = self._repo_root() / raw
        if alt.exists():
            return str(alt)
        data_alt = self._repo_root() / "data" / raw
        if data_alt.exists():
            return str(data_alt)
        return str(p)

    def _reload_trackb_workflow_modules(self) -> None:
        import phase2_llm_engine.financial_trackb_workflow as workflow_mod
        import phase2_llm_engine.trackb_harnesses.h2_prompt_base as h2_mod
        import phase2_llm_engine.trackb_harnesses.workflow as harness_workflow_mod

        importlib.reload(h2_mod)
        importlib.reload(workflow_mod)
        importlib.reload(harness_workflow_mod)

    def _temp_run_dir(self, run_id: str) -> Path:
        root = self._repo_root() / "phase4_evaluation" / "results" / "trackb_runs" / run_id / "_uploads"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _convert_pdf_with_launcher(self, pdf_path: Path, output_dir: Path) -> Path:
        script = self._repo_root() / "run_pdf_to_md.py"
        cmd = [
            sys.executable,
            str(script),
            "--pdf",
            str(pdf_path),
            "--output-dir",
            str(output_dir),
            "--name",
            f"{pdf_path.stem}.md",
            "--overwrite",
        ]
        subprocess.run(cmd, check=True, cwd=str(self._repo_root()))
        return output_dir / f"{pdf_path.stem}.md"

    def _prepare_uploaded_file(self, source_path: str, target_dir: Path, preferred_name: str) -> Path:
        src = Path(source_path)
        dst = target_dir / preferred_name
        shutil.copy2(src, dst)
        return dst

    def _materialize_uploads(
        self,
        run_id: str,
        report_file: str,
        report_name: str,
        cases_file: str,
        cases_name: str,
    ) -> tuple[str, str]:
        upload_dir = self._temp_run_dir(run_id)
        report_src = self._prepare_uploaded_file(report_file, upload_dir, report_name)
        cases_src = self._prepare_uploaded_file(cases_file, upload_dir, cases_name)

        if report_src.suffix.lower() == ".pdf":
            report_md = self._convert_pdf_with_launcher(report_src, upload_dir)
        else:
            report_md = report_src

        return str(report_md), str(cases_src)

    async def _publish(self, run_id: str, event: str, stage: str, payload: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            state = self._runs[run_id]
            state.seq += 1
            entry = TrackBEvent(
                run_id=run_id,
                event=event,  # type: ignore[arg-type]
                stage=stage,  # type: ignore[arg-type]
                seq=state.seq,
                ts=datetime.now(timezone.utc),
                payload=payload or {},
            )
            state.events.append(entry)
            qs = list(self._queues.get(run_id, []))

        for q in qs:
            await q.put(entry)

    def _profile_flags(self, profile: TrackBProfile) -> Dict[str, bool]:
        mapping: Dict[str, Dict[str, bool]] = {
            "baseline": {
                "use_h1_retrieval": False,
                "use_h2_numeric_guard": False,
                "use_h3_chronology_guard": False,
                "use_h4_verifier": False,
            },
            "h1": {
                "use_h1_retrieval": True,
                "use_h2_numeric_guard": False,
                "use_h3_chronology_guard": False,
                "use_h4_verifier": False,
            },
            "h2": {
                "use_h1_retrieval": False,
                "use_h2_numeric_guard": True,
                "use_h3_chronology_guard": False,
                "use_h4_verifier": False,
            },
            "h3": {
                "use_h1_retrieval": False,
                "use_h2_numeric_guard": False,
                "use_h3_chronology_guard": True,
                "use_h4_verifier": False,
            },
            "h4": {
                "use_h1_retrieval": False,
                "use_h2_numeric_guard": False,
                "use_h3_chronology_guard": False,
                "use_h4_verifier": True,
            },
            "all": {
                "use_h1_retrieval": True,
                "use_h2_numeric_guard": True,
                "use_h3_chronology_guard": True,
                "use_h4_verifier": True,
            },
            "all_minus_h1": {
                "use_h1_retrieval": False,
                "use_h2_numeric_guard": True,
                "use_h3_chronology_guard": True,
                "use_h4_verifier": True,
            },
            "all_minus_h2": {
                "use_h1_retrieval": True,
                "use_h2_numeric_guard": False,
                "use_h3_chronology_guard": True,
                "use_h4_verifier": True,
            },
            "all_minus_h3": {
                "use_h1_retrieval": True,
                "use_h2_numeric_guard": True,
                "use_h3_chronology_guard": False,
                "use_h4_verifier": True,
            },
            "all_minus_h4": {
                "use_h1_retrieval": True,
                "use_h2_numeric_guard": True,
                "use_h3_chronology_guard": True,
                "use_h4_verifier": False,
            },
        }
        return mapping[profile]

    def _variant_summary(self, profile: TrackBProfile, flags: Dict[str, bool]) -> Dict[str, Any]:
        enabled = [name for name, on in flags.items() if on]
        disabled = [name for name, on in flags.items() if not on]
        return {
            "variant_name": profile,
            "enabled_harnesses": enabled,
            "disabled_harnesses": disabled,
            "is_baseline": profile == "baseline",
            "is_full_workflow": profile == "all",
            "is_leave_one_out_ablation": str(profile).startswith("all_minus_"),
        }

    def _effective_h1_config(self, components: List[TrackBH1ComponentConfig]) -> Dict[str, Any]:
        enabled = [component for component in components if component.enabled]
        if not enabled:
            return {"top_k": 6, "evidence_keywords": []}

        top_k = max(int(component.top_k) for component in enabled)
        keywords: list[str] = []
        seen: set[str] = set()
        for component in enabled:
            for raw in component.evidence_keywords:
                token = str(raw).strip()
                key = token.lower()
                if not token or key in seen:
                    continue
                seen.add(key)
                keywords.append(token)

        return {
            "top_k": max(1, min(top_k, 20)),
            "evidence_keywords": keywords,
        }

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()

    def _content_tokens(self, text: str) -> list[str]:
        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "were",
            "was",
            "are",
            "to",
            "of",
            "in",
            "or",
            "by",
            "on",
            "at",
            "as",
            "an",
            "a",
        }
        tokens = re.findall(r"[a-z]{3,}", self._normalize_text(text))
        return [token for token in tokens if token not in stop]

    def _numeric_tokens(self, text: str) -> list[str]:
        return [token.replace(",", "") for token in re.findall(r"\d[\d,]*(?:\.\d+)?%?", text)]

    def _candidate_score(
        self,
        candidate_text: str,
        content_tokens: list[str],
        numeric_tokens: list[str],
        exact_hit: bool,
    ) -> int | None:
        normalized_candidate = self._normalize_text(candidate_text)
        if not normalized_candidate:
            return None

        if numeric_tokens:
            compact_candidate = normalized_candidate.replace(",", "")
            if not all(token in compact_candidate for token in numeric_tokens):
                return None

        token_hits = sum(1 for token in set(content_tokens) if token in normalized_candidate)
        score = (4 if exact_hit else 0) + token_hits + (2 if numeric_tokens else 0)
        return score

    def _citation_line_matches(self, report_lines: list[str], citation: str) -> list[int]:
        normalized_citation = self._normalize_text(citation)
        if not normalized_citation:
            return []

        content_tokens = self._content_tokens(citation)
        numeric_tokens = self._numeric_tokens(citation)
        if len(normalized_citation) < 18 and not numeric_tokens:
            return []
        if len(content_tokens) < 2 and not numeric_tokens:
            return []

        normalized_lines = [self._normalize_text(line) for line in report_lines]
        candidates: list[tuple[list[int], int]] = []

        for idx, normalized_line in enumerate(normalized_lines):
            if normalized_citation not in normalized_line:
                continue
            score = self._candidate_score(normalized_line, content_tokens, numeric_tokens, exact_hit=True)
            if score is None:
                continue
            candidates.append(([idx + 1], score))

        if len(report_lines) > 1:
            for idx in range(len(report_lines) - 1):
                combined = self._normalize_text(f"{report_lines[idx]} {report_lines[idx + 1]}")
                if normalized_citation not in combined:
                    continue
                score = self._candidate_score(combined, content_tokens, numeric_tokens, exact_hit=True)
                if score is None:
                    continue
                candidates.append(([idx + 1, idx + 2], score))

        if not candidates and len(content_tokens) >= 3:
            for idx, normalized_line in enumerate(normalized_lines):
                overlap = sum(1 for token in set(content_tokens) if token in normalized_line)
                if overlap < 3:
                    continue
                score = self._candidate_score(normalized_line, content_tokens, numeric_tokens, exact_hit=False)
                if score is None:
                    continue
                candidates.append(([idx + 1], score))

        if not candidates:
            return []

        candidates.sort(key=lambda item: item[1], reverse=True)
        best_lines, best_score = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else -999

        # Prefer no anchor over ambiguous or weak anchors.
        if best_score < 5:
            return []
        if second_score >= 0 and abs(best_score - second_score) <= 1:
            return []

        return best_lines

    def _infer_evidence_lines(self, report_text: str, citations: List[str]) -> List[int]:
        report_lines = report_text.splitlines()
        if not report_lines or not citations:
            return []

        evidence_lines: set[int] = set()
        for citation in citations:
            raw = str(citation).strip()
            if not raw or raw.upper() == "NONE":
                continue
            for line in self._citation_line_matches(report_lines, raw):
                if line > 0:
                    evidence_lines.add(line)

        return sorted(evidence_lines)

    def _get_chat_session(self, session_id: str) -> TrackBChatSessionState:
        with self._lock:
            session = self._chat_sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def get_chat_session_report(self, session_id: str) -> TrackBChatReportResponse:
        session = self._get_chat_session(session_id)
        report_path = Path(session.report_path)
        if not report_path.exists():
            raise FileNotFoundError(session.report_path)

        content = report_path.read_text(encoding="utf-8")
        return TrackBChatReportResponse(
            session_id=session.session_id,
            report_path=session.report_path,
            report_name=session.report_name,
            line_count=len(content.splitlines()),
            content=content,
        )

    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _profile_artifact_summary(self, profile: str, profile_dir: Path, cases_path: str) -> Dict[str, Any]:
        from phase1_data_pipeline.financial_report_dataset import load_financial_eval_cases
        from phase4_evaluation.financial_trackb_scorer import score_case

        metrics = self._read_json_file(profile_dir / "metrics.json")
        predictions = self._read_json_file(profile_dir / "predictions.json")
        try:
            cases = {case.case_id: case for case in load_financial_eval_cases(cases_path)}
        except Exception:  # noqa: BLE001
            cases = {}

        wrong_cases: List[Dict[str, Any]] = []
        for row in predictions if isinstance(predictions, list) else []:
            if not isinstance(row, dict):
                continue
            case_id = str(row.get("case_id", ""))
            case = cases.get(case_id)
            if case is None:
                continue
            scored = score_case(case, row)
            if scored.correct:
                continue
            wrong_cases.append({
                "case_id": case_id,
                "question": case.question,
                "answer": row.get("answer", ""),
                "expected_answer": case.expected_answer,
                "correct": scored.correct,
                "numeric_correct": scored.numeric_correct,
                "citation_present": scored.citation_present,
                "error_codes": scored.error_codes,
            })

        llm_telemetry: list[Dict[str, Any]] = []
        llm_telemetry_path = profile_dir / "llm_telemetry.json"
        if llm_telemetry_path.exists():
            try:
                loaded = json.loads(llm_telemetry_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    llm_telemetry = [item for item in loaded if isinstance(item, dict)]
            except Exception:  # noqa: BLE001
                llm_telemetry = []

        success_rows = [row for row in llm_telemetry if bool(row.get("success", False))]
        total_requests = len(llm_telemetry)
        success_count = len(success_rows)
        failure_count = total_requests - success_count
        total_elapsed_ms = sum(float(row.get("elapsed_ms", 0.0) or 0.0) for row in success_rows)
        total_prompt_tokens = sum(
            int(((row.get("usage") or {}).get("prompt_tokens") or 0))
            for row in success_rows
            if isinstance(row.get("usage"), dict)
        )
        total_completion_tokens = sum(
            int(((row.get("usage") or {}).get("completion_tokens") or 0))
            for row in success_rows
            if isinstance(row.get("usage"), dict)
        )
        total_tokens = sum(
            int(((row.get("usage") or {}).get("total_tokens") or 0))
            for row in success_rows
            if isinstance(row.get("usage"), dict)
        )
        llm_telemetry_summary = {
            "total_requests": total_requests,
            "success_count": success_count,
            "failure_count": failure_count,
            "total_elapsed_ms": round(total_elapsed_ms, 2),
            "avg_elapsed_ms": round(total_elapsed_ms / success_count, 2) if success_count else 0.0,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
        }

        return {
            "profile": profile,
            "metrics": metrics,
            "wrong_cases": wrong_cases[:5],
            "wrong_case_count": len(wrong_cases),
            "overall_accuracy": metrics.get("overall_accuracy", 0.0),
            "numeric_accuracy": metrics.get("numeric_accuracy", 0.0),
            "citation_rate": metrics.get("citation_rate", 0.0),
            "llm_telemetry_summary": llm_telemetry_summary,
            "llm_telemetry_preview": llm_telemetry[-20:],
        }

    def _run_dir_history_entry(self, run_dir: Path) -> Dict[str, Any] | None:
        profile_dirs = [p for p in run_dir.iterdir() if p.is_dir() and (p / "metrics.json").exists()]
        if not profile_dirs:
            return None

        metrics_sample = self._read_json_file(profile_dirs[0] / "metrics.json")
        report_path = str(metrics_sample.get("report_path", ""))
        cases_path = str(metrics_sample.get("cases_path", ""))
        model = str(metrics_sample.get("model", ""))
        temperature = float(metrics_sample.get("temperature", 0.0) or 0.0)
        profiles: List[Dict[str, Any]] = []

        for profile_dir in sorted(profile_dirs, key=lambda p: p.name):
            profile = profile_dir.name
            profiles.append(self._profile_artifact_summary(profile, profile_dir, cases_path))

        status = "completed"
        if any(p.get("wrong_case_count", 0) == 0 for p in profiles):
            status = "completed"

        return {
            "run_id": run_dir.name,
            "created_at": datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc),
            "finished_at": datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc),
            "status": status,
            "report_path": report_path,
            "cases_path": cases_path,
            "model": model,
            "temperature": temperature,
            "profiles": profiles,
            "output_dir": str(run_dir),
        }

    def _restore_run_state_from_disk(self, run_id: str) -> TrackBRunState | None:
        """Rehydrate a completed run from artifacts so reload doesn't cause 404."""
        run_dir = self._repo_root() / "phase4_evaluation" / "results" / "trackb_runs" / run_id
        if not run_dir.exists() or not run_dir.is_dir():
            return None

        profile_dirs = [p for p in run_dir.iterdir() if p.is_dir() and (p / "metrics.json").exists()]
        if not profile_dirs:
            return None

        profile_dirs = sorted(profile_dirs, key=lambda p: p.name)
        metrics_by_profile: Dict[str, Dict[str, Any]] = {}
        output_dirs: Dict[str, str] = {}
        profiles: List[str] = []

        report_path = ""
        cases_path = ""
        model = ""
        temperature = 0.0
        max_cases = 0
        batch_size = 1
        cases_total = 0

        for profile_dir in profile_dirs:
            profile_name = profile_dir.name
            metrics = self._read_json_file(profile_dir / "metrics.json")
            metrics_by_profile[profile_name] = metrics
            output_dirs[profile_name] = str(profile_dir)
            profiles.append(profile_name)

            if not report_path:
                report_path = str(metrics.get("report_path", ""))
            if not cases_path:
                cases_path = str(metrics.get("cases_path", ""))
            if not model:
                model = str(metrics.get("model", ""))
            if temperature == 0.0:
                temperature = float(metrics.get("temperature", 0.0) or 0.0)
            if max_cases == 0:
                max_cases = int(metrics.get("cases_run", 0) or 0)
            if batch_size == 1:
                batch_size = int(metrics.get("batch_size", 1) or 1)
            if cases_total == 0:
                cases_total = int(metrics.get("cases_run", 0) or 0)

        ts = datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc)
        progress = {
            p: TrackBProfileProgress(
                profile=p,  # type: ignore[arg-type]
                status="completed",
                cases_total=cases_total,
                cases_completed=cases_total,
            )
            for p in profiles
        }

        return TrackBRunState(
            run_id=run_id,
            created_at=ts,
            report_path=report_path,
            cases_path=cases_path,
            model=model,
            temperature=temperature,
            max_cases=max_cases,
            batch_size=batch_size,
            profiles=profiles,  # type: ignore[arg-type]
            status="completed",
            stage="completed",
            started_at=ts,
            finished_at=ts,
            progress=progress,
            metrics_by_profile=metrics_by_profile,
            profile_output_dirs=output_dirs,
        )

    def _get_or_restore_state(self, run_id: str) -> TrackBRunState:
        with self._lock:
            state = self._runs.get(run_id)
        if state is not None:
            return state

        restored = self._restore_run_state_from_disk(run_id)
        if restored is None:
            raise KeyError(run_id)

        with self._lock:
            self._runs[run_id] = restored
            self._queues.setdefault(run_id, [])
            return self._runs[run_id]

    async def create_run(self, req: TrackBRunCreateRequest) -> TrackBRunCreateResponse:
        report_path = self._resolve_path(req.report_path)
        cases_path = self._resolve_path(req.cases_path)
        if not Path(report_path).exists():
            raise ValueError(f"Report not found: {report_path}")
        if not Path(cases_path).exists():
            raise ValueError(f"Cases file not found: {cases_path}")
        if not req.profiles:
            raise ValueError("At least one profile must be selected")
        allowed = {
            "baseline",
            "h1",
            "h2",
            "h3",
            "h4",
            "all",
            "all_minus_h1",
            "all_minus_h2",
            "all_minus_h3",
            "all_minus_h4",
        }
        invalid = [profile for profile in req.profiles if profile not in allowed]
        if invalid:
            raise ValueError(f"Unsupported profiles: {', '.join(invalid)}")
        if "all" in req.profiles and len(req.profiles) > 1:
            raise ValueError("Profile 'all' is a workflow preset, not a standalone comparison target")

        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        progress = {
            p: TrackBProfileProgress(profile=p, status="queued", cases_total=0, cases_completed=0)
            for p in req.profiles
        }
        state = TrackBRunState(
            run_id=run_id,
            created_at=now,
            report_path=report_path,
            cases_path=cases_path,
            model=req.model,
            temperature=req.temperature,
            max_cases=req.max_cases,
            batch_size=req.batch_size,
            profiles=req.profiles,
            h1_components=req.h1_components,
            h3_layers=req.h3_layers,
            progress=progress,
        )

        with self._lock:
            self._runs[run_id] = state
            self._queues[run_id] = []
            self._cancel_reasons.pop(run_id, None)

        task = asyncio.create_task(self._run_async(run_id))
        with self._lock:
            self._run_tasks[run_id] = task

        base = f"/api/v1/trackb/runs/{run_id}"
        return TrackBRunCreateResponse(
            run_id=run_id,
            status="queued",
            created_at=now,
            profiles=req.profiles,
            links={
                "status": base,
                "stream": f"{base}/stream",
                "metrics": f"{base}/metrics",
                "artifacts": f"{base}/artifacts",
                "compare": "/api/v1/trackb/compare",
                "reproduce": f"{base}/reproduce",
            },
        )

    async def create_uploaded_run(
        self,
        req: TrackBUploadRunRequest,
        report_file: str,
        report_name: str,
        cases_file: str,
        cases_name: str,
    ) -> TrackBRunCreateResponse:
        run_id = str(uuid.uuid4())
        report_path, cases_path = self._materialize_uploads(
            run_id,
            report_file,
            report_name,
            cases_file,
            cases_name,
        )
        return await self.create_run(
            TrackBRunCreateRequest(
                report_path=report_path,
                cases_path=cases_path,
                model=req.model,
                temperature=req.temperature,
                max_cases=req.max_cases,
                batch_size=req.batch_size,
                profiles=req.profiles,
                h1_components=req.h1_components,
                h3_layers=req.h3_layers,
            )
        )

    async def create_chat_session(
        self,
        req: TrackBChatSessionCreateRequest,
        report_file: str,
        report_name: str,
    ) -> TrackBChatSessionCreateResponse:
        session_id = str(uuid.uuid4())
        upload_dir = self._temp_run_dir(f"chat_{session_id}")
        report_src = self._prepare_uploaded_file(report_file, upload_dir, report_name)
        if report_src.suffix.lower() == ".pdf":
            report_md = self._convert_pdf_with_launcher(report_src, upload_dir)
        else:
            report_md = report_src

        created_at = datetime.now(timezone.utc)
        state = TrackBChatSessionState(
            session_id=session_id,
            created_at=created_at,
            report_path=str(report_md),
            report_name=report_name,
            model=req.model,
            temperature=req.temperature,
            h1_components=req.h1_components,
            h3_layers=req.h3_layers,
        )
        with self._lock:
            self._chat_sessions[session_id] = state

        return TrackBChatSessionCreateResponse(
            session_id=session_id,
            created_at=created_at,
            report_path=state.report_path,
            report_name=state.report_name,
            model=state.model,
            temperature=state.temperature,
        )

    def ask_chat_session(
        self,
        session_id: str,
        req: TrackBChatAskRequest,
    ) -> TrackBChatAskResponse:
        from phase1_data_pipeline.financial_report_dataset import FinancialEvalCase
        from phase2_llm_engine.financial_trackb_workflow import run_financial_workflow

        with self._lock:
            session = self._chat_sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)

        harnesses = req.harnesses or ["all"]
        allowed = {"baseline", "all", "h1", "h2", "h3", "h4"}
        invalid = [profile for profile in harnesses if profile not in allowed]
        if invalid:
            raise ValueError(f"Unsupported profiles: {', '.join(invalid)}")

        selected = set(harnesses)
        if "baseline" in selected and len(selected) > 1:
            raise ValueError("baseline cannot be combined with other harnesses")
        if "all" in selected and len(selected) > 1:
            raise ValueError("all cannot be combined with other harnesses")

        report_text = Path(session.report_path).read_text(encoding="utf-8")
        turn_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)

        case = FinancialEvalCase(
            case_id=f"chat_{turn_id[:8]}",
            question=req.question.strip(),
            answer_type="text",
            expected_answer="",
            tolerance=0.0,
            expected_unit="",
            arithmetic_expression="",
            expected_event_order=[],
            evidence_keywords=[],
        )

        h1_components = req.h1_components if req.h1_components is not None else session.h1_components
        h3_layers = req.h3_layers if req.h3_layers is not None else session.h3_layers
        model = (req.model or session.model).strip() or session.model
        temperature = req.temperature if req.temperature is not None else session.temperature

        if "all" in selected:
            selected = {"h1", "h2", "h3", "h4"}

        use_h1 = "h1" in selected
        use_h2 = "h2" in selected
        use_h3 = "h3" in selected
        use_h4 = "h4" in selected

        started = time.perf_counter()
        wf = run_financial_workflow(
            report_text=report_text,
            case=case,
            model=model,
            temperature=temperature,
            use_h1_retrieval=use_h1,
            use_h2_numeric_guard=use_h2,
            use_h3_chronology_guard=use_h3,
            use_h4_verifier=use_h4,
            h1_config=self._effective_h1_config(h1_components),
            h3_layers=[layer.model_dump() for layer in h3_layers],
            force_contextual_baseline=True,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        selected_label = "baseline" if not selected else "+".join(
            [name for name in ["h1", "h2", "h3", "h4"] if name in selected]
        )
        evidence_lines = self._infer_evidence_lines(report_text, wf.citations)
        answers = [
            TrackBChatProfileAnswer(
                profile=selected_label,
                answer=wf.answer,
                citations=wf.citations,
                evidence_lines=evidence_lines,
                primary_evidence_line=evidence_lines[0] if len(evidence_lines) == 1 else None,
                diagnostics=wf.diagnostics,
                elapsed_ms=elapsed_ms,
            )
        ]

        turn = TrackBChatTurn(
            turn_id=turn_id,
            question=req.question.strip(),
            created_at=created_at,
            answers=answers,
        )

        with self._lock:
            current = self._chat_sessions.get(session_id)
            if current is None:
                raise KeyError(session_id)
            current.turns.append(turn)

        return TrackBChatAskResponse(session_id=session_id, turn=turn)

    def get_chat_session(self, session_id: str) -> TrackBChatSessionResponse:
        session = self._get_chat_session(session_id)
        with self._lock:
            return TrackBChatSessionResponse(
                session_id=session.session_id,
                created_at=session.created_at,
                report_path=session.report_path,
                report_name=session.report_name,
                model=session.model,
                temperature=session.temperature,
                turns=list(session.turns),
            )

    async def _run_async(self, run_id: str) -> None:
        try:
            with self._lock:
                state = self._runs[run_id]
                state.status = "running"
                state.stage = "running"
                state.started_at = datetime.now(timezone.utc)

            self._raise_if_cancelled(run_id)

            # Ensure latest harness source edits (for example H2 prompt tuning)
            # are reflected before each new run starts.
            self._reload_trackb_workflow_modules()

            await self._publish(run_id, "trackb_started", "running", {"profiles": state.profiles})

            from phase1_data_pipeline.financial_report_dataset import load_financial_eval_cases
            from phase2_llm_engine.financial_trackb_workflow import (
                run_financial_workflow_batch,
                workflow_result_to_dict,
            )
            from phase2_llm_engine.llm_client import collect_llm_telemetry
            from phase4_evaluation.financial_trackb_scorer import aggregate_scores, score_case

            report_text = Path(state.report_path).read_text(encoding="utf-8")
            all_cases = await to_thread(load_financial_eval_cases, state.cases_path)
            cases = all_cases[: state.max_cases] if state.max_cases > 0 else all_cases
            if not cases:
                raise ValueError("No Track B cases available after applying max_cases filter")
            case_index_map = {c.case_id: i for i, c in enumerate(cases, start=1)}

            run_root = self._repo_root() / "phase4_evaluation" / "results" / "trackb_runs" / run_id
            run_root.mkdir(parents=True, exist_ok=True)

            for profile in state.profiles:
                self._raise_if_cancelled(run_id)
                with self._lock:
                    p = state.progress[profile]
                    p.status = "running"
                    p.cases_total = len(cases)
                    p.cases_completed = 0

                await self._publish(run_id, "trackb_profile_started", "running", {"profile": profile})

                flags = self._profile_flags(profile)
                variant = self._variant_summary(profile, flags)
                if flags["use_h1_retrieval"]:
                    variant["h1_config"] = self._effective_h1_config(state.h1_components)
                if flags["use_h3_chronology_guard"]:
                    variant["h3_layers"] = [layer.model_dump() for layer in state.h3_layers]

                rows: List[Dict[str, Any]] = []
                scored = []
                llm_telemetry_rows: List[Dict[str, Any]] = []
                llm_telemetry_lock = threading.Lock()

                def _on_llm_telemetry(entry: Dict[str, Any]) -> None:
                    tagged = dict(entry)
                    tagged["profile"] = str(profile)
                    with llm_telemetry_lock:
                        llm_telemetry_rows.append(tagged)

                async def _publish_case_step(
                    case_id: str,
                    step: str,
                    step_status: str,
                    details: Optional[Dict[str, Any]] = None,
                ) -> None:
                    await self._publish(
                        run_id,
                        "trackb_case_progress",
                        "running",
                        {
                            "profile": profile,
                            "case_id": case_id,
                            "case_index": case_index_map.get(case_id, completed),
                            "cases_total": len(cases),
                            "batch_size": batch_size,
                            "step": step,
                            "step_status": step_status,
                            "details": details or {},
                        },
                    )

                def _is_context_length_error(exc: Exception) -> bool:
                    err_text = str(exc).lower()
                    return (
                        "context_length_exceeded" in err_text
                        or "message is too long" in err_text
                        or "context length" in err_text
                    )

                async def _run_batch_with_fallback(case_batch: list[Any]) -> list[Any]:
                    try:
                        def _on_step(case_id: str, step: str, status: str, details: Dict[str, Any] | None = None) -> None:
                            asyncio.run_coroutine_threadsafe(
                                _publish_case_step(case_id, step, status, details),
                                loop,
                            )

                        def _run_batch_in_thread() -> list[Any]:
                            with collect_llm_telemetry(_on_llm_telemetry):
                                return run_financial_workflow_batch(
                                    report_text=report_text,
                                    cases=case_batch,
                                    model=state.model,
                                    temperature=state.temperature,
                                    use_h1_retrieval=flags["use_h1_retrieval"],
                                    use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                    use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                    use_h4_verifier=flags["use_h4_verifier"],
                                    h1_config=self._effective_h1_config(state.h1_components),
                                    h3_layers=[layer.model_dump() for layer in state.h3_layers],
                                    progress_callback=_on_step,
                                )

                        return await to_thread(_run_batch_in_thread)
                    except Exception as exc:  # noqa: BLE001
                        if not _is_context_length_error(exc):
                            if len(case_batch) == 1:
                                def _on_single_step(
                                    case_id: str,
                                    step: str,
                                    status: str,
                                    details: Dict[str, Any] | None = None,
                                ) -> None:
                                    asyncio.run_coroutine_threadsafe(
                                        _publish_case_step(case_id, step, status, details),
                                        loop,
                                    )

                                def _run_single_batch_in_thread() -> list[Any]:
                                    with collect_llm_telemetry(_on_llm_telemetry):
                                        return run_financial_workflow_batch(
                                            report_text=report_text,
                                            cases=case_batch,
                                            model=state.model,
                                            temperature=state.temperature,
                                            use_h1_retrieval=flags["use_h1_retrieval"],
                                            use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                            use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                            use_h4_verifier=flags["use_h4_verifier"],
                                            h1_config=self._effective_h1_config(state.h1_components),
                                            h3_layers=[layer.model_dump() for layer in state.h3_layers],
                                            progress_callback=_on_single_step,
                                        )

                                return await to_thread(_run_single_batch_in_thread)
                            mid = max(1, len(case_batch) // 2)
                            left = await _run_batch_with_fallback(case_batch[:mid])
                            right = await _run_batch_with_fallback(case_batch[mid:])
                            return left + right

                        if len(case_batch) == 1:
                            def _on_single_step(
                                case_id: str,
                                step: str,
                                status: str,
                                details: Dict[str, Any] | None = None,
                            ) -> None:
                                asyncio.run_coroutine_threadsafe(
                                    _publish_case_step(case_id, step, status, details),
                                    loop,
                                )

                            def _run_single_batch_in_thread() -> list[Any]:
                                with collect_llm_telemetry(_on_llm_telemetry):
                                    return run_financial_workflow_batch(
                                        report_text=report_text,
                                        cases=case_batch,
                                        model=state.model,
                                        temperature=state.temperature,
                                        use_h1_retrieval=True,
                                        use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                        use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                        use_h4_verifier=flags["use_h4_verifier"],
                                        h1_config=self._effective_h1_config(state.h1_components),
                                        h3_layers=[layer.model_dump() for layer in state.h3_layers],
                                        progress_callback=_on_single_step,
                                    )

                            return await to_thread(_run_single_batch_in_thread)

                        mid = max(1, len(case_batch) // 2)
                        left = await _run_batch_with_fallback(case_batch[:mid])
                        right = await _run_batch_with_fallback(case_batch[mid:])
                        return left + right

                completed = 0
                batch_size = max(1, int(state.batch_size or 1))
                loop = asyncio.get_running_loop()
                for start in range(0, len(cases), batch_size):
                    self._raise_if_cancelled(run_id)
                    case_batch = cases[start : start + batch_size]
                    for case in case_batch:
                        await _publish_case_step(case.case_id, "workflow", "started", {"batch": batch_size > 1})
                    wf_batch = await _run_batch_with_fallback(case_batch)
                    if case_batch and not wf_batch:
                        wf_batch = []
                        for single in case_batch:

                            def _on_single_step(
                                case_id: str,
                                step: str,
                                status: str,
                                details: Dict[str, Any] | None = None,
                            ) -> None:
                                asyncio.run_coroutine_threadsafe(
                                    _publish_case_step(case_id, step, status, details),
                                    loop,
                                )

                            def _run_single_batch_in_thread() -> list[Any]:
                                with collect_llm_telemetry(_on_llm_telemetry):
                                    return run_financial_workflow_batch(
                                        report_text=report_text,
                                        cases=[single],
                                        model=state.model,
                                        temperature=state.temperature,
                                        use_h1_retrieval=flags["use_h1_retrieval"],
                                        use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                        use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                        use_h4_verifier=flags["use_h4_verifier"],
                                        h1_config=self._effective_h1_config(state.h1_components),
                                        h3_layers=[layer.model_dump() for layer in state.h3_layers],
                                        progress_callback=_on_single_step,
                                    )

                            single_batch = await to_thread(_run_single_batch_in_thread)
                            wf_batch.extend(single_batch)
                    case_by_id = {c.case_id: c for c in case_batch}

                    for idx_in_batch, wf in enumerate(wf_batch):
                        case = case_by_id.get(wf.case_id)
                        if case is None:
                            case = case_batch[min(idx_in_batch, len(case_batch) - 1)]

                        row = workflow_result_to_dict(wf)
                        row["variant"] = variant
                        rows.append(row)
                        scored.append(score_case(case, row))

                        completed += 1
                        with self._lock:
                            p = state.progress[profile]
                            p.cases_completed = completed

                        await self._publish(
                            run_id,
                            "trackb_case_progress",
                            "running",
                            {
                                "profile": profile,
                                "case_index": completed,
                                "cases_total": len(cases),
                                "case_id": case.case_id,
                                "batch_size": batch_size,
                                "step": "case_completed",
                                "step_status": "completed",
                            },
                        )

                if len(cases) > 0 and completed == 0:
                    raise RuntimeError("No workflow outputs were produced for non-empty cases")

                metrics = aggregate_scores(scored)
                metrics["variant"] = variant
                metrics["report_path"] = state.report_path
                metrics["cases_path"] = state.cases_path
                metrics["model"] = state.model
                metrics["temperature"] = state.temperature
                metrics["cases_run"] = len(cases)

                profile_dir = run_root / str(profile)
                profile_dir.mkdir(parents=True, exist_ok=True)
                (profile_dir / "predictions.json").write_text(
                    json.dumps(rows, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                (profile_dir / "metrics.json").write_text(
                    json.dumps(metrics, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                (profile_dir / "variant.json").write_text(
                    json.dumps(variant, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                (profile_dir / "llm_telemetry.json").write_text(
                    json.dumps(llm_telemetry_rows, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                with self._lock:
                    state.metrics_by_profile[str(profile)] = metrics
                    state.profile_output_dirs[str(profile)] = str(profile_dir)
                    p = state.progress[profile]
                    p.status = "completed"

                await self._publish(
                    run_id,
                    "trackb_profile_completed",
                    "running",
                    {"profile": profile, "output_dir": str(profile_dir)},
                )

            with self._lock:
                state.stage = "scoring"
            await self._publish(run_id, "trackb_scoring_done", "scoring", {})

            with self._lock:
                state.status = "completed"
                state.stage = "completed"
                state.finished_at = datetime.now(timezone.utc)

            await self._publish(
                run_id,
                "trackb_completed",
                "completed",
                {"profiles": state.profiles},
            )
        except asyncio.CancelledError as exc:
            reason = str(exc) or self._current_cancel_reason(run_id)
            with self._lock:
                state = self._runs[run_id]
                state.status = "failed"
                state.stage = "failed"
                state.error = reason
                state.finished_at = datetime.now(timezone.utc)
            await self._publish(run_id, "trackb_failed", "failed", {"error": reason})
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                state = self._runs[run_id]
                state.status = "failed"
                state.stage = "failed"
                state.error = str(exc)
                state.finished_at = datetime.now(timezone.utc)
            await self._publish(run_id, "trackb_failed", "failed", {"error": str(exc)})
        finally:
            with self._lock:
                self._run_tasks.pop(run_id, None)
                self._cancel_reasons.pop(run_id, None)

    async def cancel_run(self, run_id: str, reason: str = "Cancelled by user") -> TrackBRunStatusResponse:
        state = self._get_or_restore_state(run_id)

        is_terminal = False
        with self._lock:
            is_terminal = state.status in {"completed", "failed"}
            if not is_terminal:
                self._cancel_reasons[run_id] = reason
                task = self._run_tasks.get(run_id)
                state.status = "failed"
                state.stage = "failed"
                state.error = reason
                state.finished_at = datetime.now(timezone.utc)
            else:
                task = None

        if is_terminal:
            return self.get_status(run_id)

        if task is not None and not task.done():
            task.cancel(reason)

        await self._publish(run_id, "trackb_failed", "failed", {"error": reason})
        return self.get_status(run_id)

    async def cancel_all_runs(self, reason: str = "Server shutdown") -> None:
        with self._lock:
            run_ids = list(self._run_tasks.keys())

        for run_id in run_ids:
            try:
                await self.cancel_run(run_id, reason=reason)
            except Exception:
                continue

    def get_status(self, run_id: str) -> TrackBRunStatusResponse:
        state = self._get_or_restore_state(run_id)
        with self._lock:
            progress = list(state.progress.values())
            return TrackBRunStatusResponse(
                run_id=run_id,
                status=state.status,  # type: ignore[arg-type]
                stage=state.stage,  # type: ignore[arg-type]
                created_at=state.created_at,
                started_at=state.started_at,
                finished_at=state.finished_at,
                report_path=state.report_path,
                cases_path=state.cases_path,
                model=state.model,
                temperature=state.temperature,
                max_cases=state.max_cases,
                batch_size=state.batch_size,
                profiles=state.profiles,
                progress=progress,
                error=state.error,
            )

    def get_metrics(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        state = self._get_or_restore_state(run_id)
        with self._lock:
            return dict(state.metrics_by_profile)

    def get_artifacts(self, run_id: str) -> Dict[str, Any]:
        state = self._get_or_restore_state(run_id)
        with self._lock:
            output_dir = str(self._repo_root() / "phase4_evaluation" / "results" / "trackb_runs" / run_id)

            artifacts: List[Dict[str, Any]] = []
            profiles: List[Dict[str, Any]] = []
            for profile, profile_dir in state.profile_output_dirs.items():
                for name in ("predictions.json", "metrics.json", "variant.json", "llm_telemetry.json"):
                    path = Path(profile_dir) / name
                    if path.exists():
                        artifacts.append(
                            {
                                "profile": profile,
                                "name": name,
                                "path": str(path),
                                "bytes": path.stat().st_size,
                            }
                        )
                profiles.append(self._profile_artifact_summary(profile, Path(profile_dir), state.cases_path))

            return {"output_dir": output_dir, "artifacts": artifacts, "profiles": profiles}

    def get_history(self, limit: int = 20) -> TrackBHistoryResponse:
        history_root = self._repo_root() / "phase4_evaluation" / "results" / "trackb_runs"
        if not history_root.exists():
            return TrackBHistoryResponse(runs=[])

        run_dirs = [p for p in history_root.iterdir() if p.is_dir()]
        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        rows: List[Dict[str, Any]] = []
        for run_dir in run_dirs:
            entry = self._run_dir_history_entry(run_dir)
            if entry is None:
                continue
            rows.append(entry)
            if len(rows) >= limit:
                break

        return TrackBHistoryResponse(runs=rows)

    def compare(self, req: TrackBComparisonRequest) -> TrackBComparisonResponse:
        state = self._get_or_restore_state(req.run_id)
        with self._lock:
            metrics = dict(state.metrics_by_profile)

        if not metrics:
            raise RuntimeError("Track B run is still in progress; metrics are not ready")

        baseline = metrics.get(req.baseline_profile)
        if not baseline:
            raise ValueError(f"Baseline profile not found in run: {req.baseline_profile}")

        b_overall = float(baseline.get("overall_accuracy", 0.0) or 0.0)
        b_numeric = float(baseline.get("numeric_accuracy", 0.0) or 0.0)
        b_citation = float(baseline.get("citation_rate", 0.0) or 0.0)

        rows: List[Dict[str, Any]] = []
        loo: List[Dict[str, Any]] = []

        for profile, m in metrics.items():
            overall = float(m.get("overall_accuracy", 0.0) or 0.0)
            numeric = float(m.get("numeric_accuracy", 0.0) or 0.0)
            citation = float(m.get("citation_rate", 0.0) or 0.0)
            row = {
                "profile": profile,
                "overall_accuracy": overall,
                "numeric_accuracy": numeric,
                "citation_rate": citation,
                "delta_overall_accuracy": round(overall - b_overall, 4),
                "delta_numeric_accuracy": round(numeric - b_numeric, 4),
                "delta_citation_rate": round(citation - b_citation, 4),
                "error_counts": m.get("error_counts", {}),
            }
            rows.append(row)
            if str(profile).startswith("all_minus_"):
                loo.append(
                    {
                        "profile": profile,
                        "removed_harness": str(profile).replace("all_minus_", "h"),
                        "delta_overall_accuracy": row["delta_overall_accuracy"],
                        "delta_numeric_accuracy": row["delta_numeric_accuracy"],
                        "delta_citation_rate": row["delta_citation_rate"],
                    }
                )

        rows.sort(key=lambda x: x["overall_accuracy"], reverse=True)
        loo.sort(key=lambda x: x["delta_overall_accuracy"])
        return TrackBComparisonResponse(
            run_id=req.run_id,
            baseline_profile=req.baseline_profile,
            rows=rows,
            loo_impact=loo,
        )

    def reproduce(self, run_id: str) -> TrackBReproduceResponse:
        state = self._get_or_restore_state(run_id)
        profiles_csv = ",".join(state.profiles)
        cmd = (
            f".venv/bin/python scripts/run_financial_trackb.py "
            f"--report '{state.report_path}' --cases '{state.cases_path}' "
            f"--model '{state.model}' --temperature {state.temperature}"
        )
        return TrackBReproduceResponse(
            run_id=run_id,
            commands={
                "single_variant_template": cmd + " --mode baseline",
                "api_submit": (
                    "curl -X POST http://localhost:8000/api/v1/trackb/runs "
                    "-H 'Content-Type: application/json' "
                    f"-d '{{\"report_path\":\"{state.report_path}\",\"cases_path\":\"{state.cases_path}\","
                    f"\"model\":\"{state.model}\",\"temperature\":{state.temperature},"
                    f"\"profiles\":[{','.join([f'\"{p}\"' for p in state.profiles])}]}}'"
                ),
                "profiles": profiles_csv,
            },
            config={
                "report_path": state.report_path,
                "cases_path": state.cases_path,
                "model": state.model,
                "temperature": state.temperature,
                "max_cases": state.max_cases,
                "batch_size": state.batch_size,
                "profiles": state.profiles,
                "h1_components": [component.model_dump() for component in state.h1_components],
                "h3_layers": [layer.model_dump() for layer in state.h3_layers],
            },
        )

    async def subscribe(self, run_id: str) -> asyncio.Queue[TrackBEvent]:
        self._get_or_restore_state(run_id)
        with self._lock:
            q: asyncio.Queue[TrackBEvent] = asyncio.Queue()
            self._queues.setdefault(run_id, []).append(q)
            return q

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue[TrackBEvent]) -> None:
        with self._lock:
            if run_id in self._queues and queue in self._queues[run_id]:
                self._queues[run_id].remove(queue)


trackb_service = TrackBService()
