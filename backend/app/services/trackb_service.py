from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
import uuid
import shutil
import subprocess
import sys

from app.schemas.trackb import (
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


class TrackBService:
    def __init__(self) -> None:
        self._runs: Dict[str, TrackBRunState] = {}
        self._queues: Dict[str, List[asyncio.Queue[TrackBEvent]]] = {}
        self._lock = threading.Lock()

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

        return {
            "profile": profile,
            "metrics": metrics,
            "wrong_cases": wrong_cases[:5],
            "wrong_case_count": len(wrong_cases),
            "overall_accuracy": metrics.get("overall_accuracy", 0.0),
            "numeric_accuracy": metrics.get("numeric_accuracy", 0.0),
            "citation_rate": metrics.get("citation_rate", 0.0),
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
                profile=p,
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
            progress=progress,
        )

        with self._lock:
            self._runs[run_id] = state
            self._queues[run_id] = []

        asyncio.create_task(self._run_async(run_id))

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
            )
        )

    async def _run_async(self, run_id: str) -> None:
        try:
            with self._lock:
                state = self._runs[run_id]
                state.status = "running"
                state.stage = "running"
                state.started_at = datetime.now(timezone.utc)

            await self._publish(run_id, "trackb_started", "running", {"profiles": state.profiles})

            from phase1_data_pipeline.financial_report_dataset import load_financial_eval_cases
            from phase2_llm_engine.financial_trackb_workflow import (
                run_financial_workflow,
                run_financial_workflow_batch,
                workflow_result_to_dict,
            )
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
                with self._lock:
                    p = state.progress[profile]
                    p.status = "running"
                    p.cases_total = len(cases)
                    p.cases_completed = 0

                await self._publish(run_id, "trackb_profile_started", "running", {"profile": profile})

                flags = self._profile_flags(profile)
                variant = self._variant_summary(profile, flags)

                rows: List[Dict[str, Any]] = []
                scored = []

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

                        return await to_thread(
                            run_financial_workflow_batch,
                            report_text=report_text,
                            cases=case_batch,
                            model=state.model,
                            temperature=state.temperature,
                            use_h1_retrieval=flags["use_h1_retrieval"],
                            use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                            use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                            use_h4_verifier=flags["use_h4_verifier"],
                            progress_callback=_on_step,
                        )
                    except Exception as exc:  # noqa: BLE001
                        if not _is_context_length_error(exc):
                            if len(case_batch) == 1:
                                single = case_batch[0]

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

                                wf = await to_thread(
                                    run_financial_workflow,
                                    report_text=report_text,
                                    case=single,
                                    model=state.model,
                                    temperature=state.temperature,
                                    use_h1_retrieval=flags["use_h1_retrieval"],
                                    use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                    use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                    use_h4_verifier=flags["use_h4_verifier"],
                                    progress_callback=_on_single_step,
                                )
                                return [wf]
                            mid = max(1, len(case_batch) // 2)
                            left = await _run_batch_with_fallback(case_batch[:mid])
                            right = await _run_batch_with_fallback(case_batch[mid:])
                            return left + right

                        if len(case_batch) == 1:
                            single = case_batch[0]

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

                            wf = await to_thread(
                                run_financial_workflow,
                                report_text=report_text,
                                case=single,
                                model=state.model,
                                temperature=state.temperature,
                                use_h1_retrieval=True,
                                use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                use_h4_verifier=flags["use_h4_verifier"],
                                progress_callback=_on_single_step,
                            )
                            return [wf]

                        mid = max(1, len(case_batch) // 2)
                        left = await _run_batch_with_fallback(case_batch[:mid])
                        right = await _run_batch_with_fallback(case_batch[mid:])
                        return left + right

                completed = 0
                batch_size = max(1, int(state.batch_size or 1))
                loop = asyncio.get_running_loop()
                for start in range(0, len(cases), batch_size):
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

                            wf = await to_thread(
                                run_financial_workflow,
                                report_text=report_text,
                                case=single,
                                model=state.model,
                                temperature=state.temperature,
                                use_h1_retrieval=flags["use_h1_retrieval"],
                                use_h2_numeric_guard=flags["use_h2_numeric_guard"],
                                use_h3_chronology_guard=flags["use_h3_chronology_guard"],
                                use_h4_verifier=flags["use_h4_verifier"],
                                progress_callback=_on_single_step,
                            )
                            wf_batch.append(wf)
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
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                state = self._runs[run_id]
                state.status = "failed"
                state.stage = "failed"
                state.error = str(exc)
                state.finished_at = datetime.now(timezone.utc)
            await self._publish(run_id, "trackb_failed", "failed", {"error": str(exc)})

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
                for name in ("predictions.json", "metrics.json", "variant.json"):
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
