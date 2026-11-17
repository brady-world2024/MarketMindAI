from __future__ import annotations

import json
from contextlib import closing
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles

from ..run_control import RunControl, use_run_control
from ..graph import MarketMindGraph
from ..symbols import SymbolResolution
from .catalog import build_provider_catalog
from .models import AnalysisRequest, RunCreatedResponse, ValidateKeyRequest, ValidateKeyResponse, ReviewRequest, ReviseRequest
from ..graph.review import ReviewConflict
from ..dataflows.source_store import SourceStore, SnapshotIntegrityError, snapshot_fingerprint
from ..dataflows.source_policy import aware_time
from .report_export import render_report_html
from .jobs import JobStore
from .runner import SnapshotBuilder, iso_now, resolve_request_symbol, to_core_request
from .symbols_router import router as symbols_router


STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    configured = os.getenv("MARKETMIND_WEB_ALLOWED_ORIGINS", "")
    if configured.strip():
        return [item.strip() for item in configured.split(",") if item.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


class RunSession:
    def __init__(self, run_id: str, model_call_limit: int | None = None):
        self.run_id = run_id
        self.started_at = iso_now()
        self.control = RunControl(model_call_limit=model_call_limit)
        self._condition = threading.Condition()
        self._history: list[dict[str, Any]] = []
        self._latest_snapshot: dict[str, Any] | None = None
        self._done = False

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._condition:
            event = {"type": event_type, "payload": payload}
            self._history.append(event)
            if event_type == "snapshot":
                self._latest_snapshot = payload
            self._condition.notify_all()

    def finish(self) -> None:
        with self._condition:
            self._done = True
            self._condition.notify_all()

    @property
    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._condition:
            return self._latest_snapshot

    def view(self, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None or snapshot.get("status") not in {"queued", "running"}:
            return snapshot
        snapshot = {**snapshot, "model_usage": self.control.usage_snapshot()}
        reason = self.control.reason
        if not reason:
            return snapshot
        return {**snapshot, "job_status": "stopping", "stop_reason": reason,
                "latest_update": {
                    "timed_out": "Time limit reached. Waiting for active calls to return.",
                    "cancelled": "Cancellation requested. Waiting for active calls to return.",
                    "budget_exhausted": "Model call limit reached. Waiting for active calls to return.",
                }[reason]}

    def stream_events(self) -> Iterator[dict[str, Any]]:
        index = 0
        reported_stop = False
        while True:
            with self._condition:
                if index >= len(self._history) and not self._done:
                    self._condition.wait(timeout=0.5)
                batch = self._history[index:]
                latest, done = self._latest_snapshot, self._done
            for event in batch:
                if event["type"] == "snapshot":
                    payload = self.view(event["payload"])
                    reported_stop |= payload.get("job_status") == "stopping"
                    event = {**event, "payload": payload}
                yield event
                index += 1
            if done:
                return
            if not reported_stop:
                status = self.view(latest)
                if status and status.get("job_status") == "stopping":
                    reported_stop = True
                    yield {"type": "snapshot", "payload": status}


class RunRegistry:
    def __init__(self, capacity: int = 2):
        self._capacity = capacity
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()

    def create(self, model_call_limit: int | None = None) -> RunSession:
        session, _ = self.claim(uuid.uuid4().hex[:12], model_call_limit=model_call_limit)
        assert session is not None
        return session

    def claim(self, run_id: str, *, can_start: Callable[[], bool] | None = None, model_call_limit: int | None = None) -> tuple[RunSession | None, bool]:
        with self._lock:
            if run_id in self._sessions:
                return self._sessions[run_id], False
            if can_start is not None and not can_start():
                return None, False
            if len(self._sessions) >= self._capacity:
                raise HTTPException(status_code=503, detail="Two research jobs are already running. Try again when one finishes.",
                                    headers={"Retry-After": "10"})
            session = RunSession(run_id, model_call_limit)
            self._sessions[run_id] = session
            return session, True

    def get(self, run_id: str) -> RunSession | None:
        with self._lock:
            return self._sessions.get(run_id)

    def discard(self, session: RunSession) -> None:
        with self._lock:
            if self._sessions.get(session.run_id) is session:
                self._sessions.pop(session.run_id)


AnalysisThread = threading.Thread


def _to_sse(event: dict[str, Any]) -> bytes:
    payload = json.dumps(event["payload"], ensure_ascii=False)
    return f"event: {event['type']}\ndata: {payload}\n\n".encode("utf-8")


def _persist_snapshot(workflow: MarketMindGraph, run_id: str, snapshot: dict[str, Any]) -> None:
    workflow.archive.save_web_snapshot(run_id, snapshot)


def _load_persisted_snapshot(workflow: MarketMindGraph, run_id: str) -> dict[str, Any] | None:
    return workflow.archive.load(run_id)


def _recover_interrupted(workflow: MarketMindGraph, job: dict) -> dict:
    if job.get("job_status") not in {"interrupted", "cancelled", "timed_out", "budget_exhausted"} or job.get("data_snapshot"):
        return job
    if not all(job.get(key) for key in ("run_id", "ticker", "data_mode", "analysis_date", "started_at")):
        return job
    store = SourceStore(workflow.paths.root / "sources")
    saved = store.find_for_run(job["run_id"], symbol=job["ticker"], data_mode=job["data_mode"],
                               requested_date=job["analysis_date"], started_at=job.get("started_at"))
    if saved is None:
        return job
    return {**job, "research_cutoff": saved.cutoff, "data_snapshot": {
        "snapshot_id": saved.snapshot_id, "manifest_sha256": snapshot_fingerprint(saved),
        "policy_version": saved.policy_version, "processing_version": saved.processing_version,
        "format_version": saved.format_version, "origin_run_id": saved.origin_run_id,
    }, "latest_update": ("Use the saved data to run this research again."
                          if job["job_status"] == "interrupted" else job["latest_update"])}


def _archived_or_interrupted(workflow: MarketMindGraph, run_id: str, job: dict | None) -> dict | None:
    archived = _load_persisted_snapshot(workflow, run_id)
    if job and job.get("job_status") == "interrupted":
        finished = aware_time((archived or {}).get("finished_at"))
        started = aware_time(job.get("started_at"))
        if archived is None or (archived.get("status") == "error"
                                and (not finished or (started and finished < started))):
            return _recover_interrupted(workflow, job)
    return archived or job


def _resolve_snapshot(workflow: MarketMindGraph, run_id: str, runs: RunRegistry, jobs: JobStore) -> dict[str, Any] | None:
    durable = workflow.reviews.load(run_id)
    if durable is not None:
        return durable
    session = runs.get(run_id)
    job = jobs.get(run_id)
    if session is not None:
        return session.view(session.latest_snapshot or job)
    return _archived_or_interrupted(workflow, run_id, job)


def _resolution_http_detail(resolved: SymbolResolution) -> dict[str, Any]:
    return {
        "status": resolved.status,
        "message": resolved.reason,
        "resolution": resolved.to_dict(),
    }


def _safe_run_error(payload: dict) -> None:
    if payload.get("error") != "AI connection could not be initialized. Check provider credentials and settings.":
        payload["error"] = "Analysis failed. Check the provider connection and try again."


def _hide_final_decision(payload: dict) -> None:
    payload.update(final_signal=None, final_decision=None, final_structured_decision=None, review=None,
                   report_verification=None, report_quality=None, evidence_ledger=[])
    payload["reports"] = [report for report in payload.get("reports", []) if report["key"] != "final_trade_decision"]


def _run_analysis_thread(session: RunSession, workflow: MarketMindGraph, request: AnalysisRequest,
                         resolution: SymbolResolution, jobs: JobStore, runs: RunRegistry) -> None:
    archived = False
    final_snapshot = None
    last_progress = None
    try:
        core_request = to_core_request(request)
        with use_run_control(session.control), closing(workflow.stream(core_request, run_id=session.run_id)) as iterator:
            session.control.check()
            for snapshot in iterator:
                payload = snapshot.to_dict()
                payload["model_usage"] = session.control.usage_snapshot()
                if payload["status"] == "error":
                    _safe_run_error(payload)
                if payload["status"] != "completed":
                    _hide_final_decision(payload)
                if request.snapshot_id and not payload.get("data_snapshot"):
                    payload["data_snapshot"] = {"snapshot_id": request.snapshot_id}
                if payload["status"] in {"completed", "error"}:
                    final_snapshot = payload
                    continue
                progress = (payload["status"], payload.get("current_agent"), payload.get("data_snapshot"), payload["model_usage"])
                if progress != last_progress and payload["status"] in {"queued", "running"}:
                    jobs.save({**payload, "started_at": session.started_at}, request.api_key)
                    last_progress = progress
                session.publish("snapshot", payload)
                session.control.check()
        if final_snapshot:
            session.control.seal()
            _persist_snapshot(workflow, session.run_id, final_snapshot)
            archived = True
            session.publish("snapshot", final_snapshot)
            session.publish("complete", final_snapshot)
    except Exception:
        latest = dict(final_snapshot or session.latest_snapshot or {
            "run_id": session.run_id,
            "status": "error",
            "original_input": request.ticker,
            "ticker": resolution.resolved_symbol or request.ticker,
            "analysis_date": request.analysis_date,
            "provider": request.llm_provider,
            "quick_model": request.quick_model,
            "deep_model": request.deep_model,
            "output_language": request.output_language,
            "selected_analysts": request.analysts,
            "research_objective": request.research_objective,
            "research_horizon": request.research_horizon,
            "started_at": "",
            "finished_at": "",
            "current_agent": None,
            "latest_update": "Analysis failed.",
            "agents": [],
            "messages": [],
            "tool_calls": [],
            "reports": [],
            "final_signal": None,
            "final_decision": None,
        })
        latest["status"] = "error"
        _safe_run_error(latest)
        latest["finished_at"] = iso_now()
        latest["latest_update"] = "Analysis failed."
        reason = session.control.finish_reason()
        latest["model_usage"] = session.control.usage_snapshot()
        if reason:
            _hide_final_decision(latest)
            latest.update(job_status=reason, stop_reason=reason,
                          error={
                              "cancelled": "Research cancelled.",
                              "timed_out": "Research timed out.",
                              "budget_exhausted": "Model call limit reached. No recommendation was generated.",
                          }[reason])
            latest["latest_update"] = latest["error"]
            latest = _recover_interrupted(workflow, latest)
        _persist_snapshot(workflow, session.run_id, latest)
        session.publish("snapshot", latest)
        archived = True
        session.publish("error", {"message": latest["error"]})
    finally:
        session.finish()
        try:
            if archived:
                jobs.remove(session.run_id)
            else:
                jobs.mark_interrupted(session.run_id)
        finally:
            runs.discard(session)


def create_app(storage_root: str | None = None) -> FastAPI:
    resolved_storage_root = Path(storage_root).expanduser() if storage_root else None
    workflow: MarketMindGraph | None = None
    jobs: JobStore | None = None
    runs = RunRegistry()
    initialization_lock = threading.Lock()

    def get_workflow() -> MarketMindGraph:
        nonlocal workflow
        with initialization_lock:
            if workflow is None:
                workflow = MarketMindGraph(storage_root=resolved_storage_root)
            return workflow

    def get_jobs() -> JobStore:
        nonlocal jobs
        root = get_workflow().paths.root
        with initialization_lock:
            if jobs is None:
                jobs = JobStore(root)
            return jobs

    def launch(session: RunSession, request: AnalysisRequest, resolution: SymbolResolution):
        store = None
        try:
            store = get_jobs()
            queued = SnapshotBuilder(session.run_id, request, resolution).snapshot.model_dump(mode="json")
            queued["started_at"] = session.started_at
            queued["model_usage"] = session.control.usage_snapshot()
            queued["data_mode"] = "demo" if request.llm_provider == "offline" else "live"
            if request.snapshot_id:
                queued["data_snapshot"] = {"snapshot_id": request.snapshot_id}
            store.save(queued, request.api_key)
            session.publish("snapshot", queued)
            worker = AnalysisThread(target=_run_analysis_thread,
                                    args=(session, get_workflow(), request, resolution, store, runs), daemon=True)
            worker.start()
        except Exception:
            session.publish("error", {"message": "Unable to start research. Try again."})
            session.finish()
            try:
                if store is not None:
                    store.remove(session.run_id)
            finally:
                runs.discard(session)
            raise HTTPException(status_code=503, detail="Unable to start research. Try again.") from None

    app = FastAPI(title="MarketMind AI Web", version="0.2.0")
    app.state.runs = runs
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(symbols_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/providers/models")
    @app.get("/api/providers")
    def providers() -> JSONResponse:
        payload = [provider.model_dump(mode="json") for provider in build_provider_catalog()]
        return JSONResponse(payload)

    @app.post("/validate-key", response_model=ValidateKeyResponse)
    @app.post("/api/validate-key", response_model=ValidateKeyResponse)
    def validate_key(request: ValidateKeyRequest) -> ValidateKeyResponse:
        core = to_core_request(
            AnalysisRequest(
                ticker="NVDA",
                analysis_date="2026-06-12",
                llm_provider=request.llm_provider,
                api_key=request.api_key,
                quick_model=request.model,
                deep_model=request.model,
                analysts=["market"],
                output_language="English",
                base_url=request.base_url,
            )
        )
        ok, message = get_workflow().validate_provider(core)
        return ValidateKeyResponse(valid=ok, provider=request.llm_provider, model=request.model, message=message)

    @app.post("/runs", response_model=RunCreatedResponse)
    @app.post("/reports", response_model=RunCreatedResponse)
    @app.post("/api/runs", response_model=RunCreatedResponse)
    @app.post("/api/reports", response_model=RunCreatedResponse)
    def create_run(request: AnalysisRequest) -> RunCreatedResponse:
        current_workflow = get_workflow()
        try:
            resolved = resolve_request_symbol(request, current_workflow)
        except SnapshotIntegrityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        logger.info(
            "create_run_symbol_resolution %s",
            json.dumps(
                {
                    "original_input": request.ticker,
                    "analysis_date": request.analysis_date,
                    "status": resolved.status,
                    "resolved_symbol": resolved.resolved_symbol,
                    "confidence": resolved.confidence,
                },
                ensure_ascii=False,
            ),
        )
        if resolved.status != "RESOLVED":
            raise HTTPException(status_code=422, detail=_resolution_http_detail(resolved))
        session = runs.create(request.model_call_limit)
        launch(session, request, resolved)
        return RunCreatedResponse(
            run_id=session.run_id,
            stream_url=f"/runs/{session.run_id}/stream",
            result_url=f"/runs/{session.run_id}/result",
            report_url=f"/runs/{session.run_id}/report",
            ticker_resolution=resolved,
        )

    @app.get("/reviews")
    @app.get("/api/reviews")
    def list_reviews() -> JSONResponse:
        return JSONResponse(get_workflow().reviews.list_reviews())

    @app.post("/runs/{run_id}/review")
    @app.post("/api/runs/{run_id}/review")
    def review_run(run_id: str, request: ReviewRequest) -> JSONResponse:
        try:
            snapshot = get_workflow().reviews.decide(run_id, **request.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(snapshot)

    @app.post("/runs/{run_id}/revise", response_model=RunCreatedResponse)
    @app.post("/api/runs/{run_id}/revise", response_model=RunCreatedResponse)
    def revise_run(run_id: str, request: ReviseRequest) -> RunCreatedResponse:
        current_workflow = get_workflow()
        try:
            child_id, payload = current_workflow.reviews.reserve_revision(
                run_id, version=request.version, report_hash=request.report_hash)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        child_request = AnalysisRequest.model_validate({**payload, "api_key": request.api_key})
        try:
            resolved = resolve_request_symbol(child_request, current_workflow)
        except SnapshotIntegrityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if resolved.status != "RESOLVED":
            raise HTTPException(status_code=422, detail=_resolution_http_detail(resolved))
        def revision_can_start() -> bool:
            previous = current_workflow.archive.load(child_id)
            return previous is None or previous.get("status") == "error"

        session, claimed = runs.claim(child_id, can_start=revision_can_start, model_call_limit=child_request.model_call_limit)
        if claimed and session is not None:
            launch(session, child_request, resolved)
        return RunCreatedResponse(run_id=child_id, stream_url=f"/runs/{child_id}/stream",
                                  result_url=f"/runs/{child_id}/result", report_url=f"/runs/{child_id}/report",
                                  ticker_resolution=resolved)

    @app.get("/api/snapshots/{snapshot_id}/sources/{record_id}")
    def get_saved_source(snapshot_id: str, record_id: str) -> Response:
        store = SourceStore(get_workflow().paths.root / 'sources')
        try:
            saved = store.load(snapshot_id)
            record = next((record for record in saved.records if record.record_id == record_id), None)
            if record is None or record.raw_sha256 is None:
                raise HTTPException(status_code=404, detail="Saved source not found")
            body = store.read_blob(record.raw_sha256)
        except SnapshotIntegrityError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(body, media_type='text/plain', headers={
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; sandbox",
            'Content-Disposition': f'attachment; filename="source-{record.raw_sha256}.txt"',
        })

    @app.get("/api/jobs")
    def get_interrupted_jobs(status: Literal["interrupted"] = "interrupted") -> JSONResponse:
        current_workflow = get_workflow()
        store = get_jobs()
        interrupted = []
        for job in store.interrupted():
            resolved = _archived_or_interrupted(current_workflow, job["run_id"], job)
            if resolved and resolved.get("job_status") == "interrupted":
                interrupted.append(resolved)
        return JSONResponse(interrupted)

    @app.post("/runs/{run_id}/cancel", status_code=202)
    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> JSONResponse:
        session = runs.get(run_id)
        if session is None:
            if _resolve_snapshot(get_workflow(), run_id, runs, get_jobs()) is None:
                raise HTTPException(status_code=404, detail="Run not found")
            raise HTTPException(status_code=409, detail="This research run is no longer active.")
        if not session.control.cancel():
            raise HTTPException(status_code=409, detail="This research run has finished or is already stopping.")
        snapshot = session.view(session.latest_snapshot or get_jobs().get(run_id))
        return JSONResponse(snapshot or {"run_id": run_id, "job_status": "stopping"}, status_code=202)

    @app.get("/runs/{run_id}")
    @app.get("/api/runs/{run_id}")
    def get_run_snapshot(run_id: str) -> JSONResponse:
        latest = _resolve_snapshot(get_workflow(), run_id, runs, get_jobs())
        if latest is None:
            session = runs.get(run_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            return JSONResponse({"status": "queued", "run_id": run_id})
        return JSONResponse(latest)

    @app.get("/runs/{run_id}/result")
    @app.get("/api/runs/{run_id}/result")
    def get_run_result(run_id: str) -> JSONResponse:
        latest = _resolve_snapshot(get_workflow(), run_id, runs, get_jobs())
        if latest is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if latest.get("status") not in {"completed", "error"}:
            raise HTTPException(status_code=409, detail="Run is not finished yet")
        return JSONResponse(latest)

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    @app.get("/api/runs/{run_id}/report", response_class=HTMLResponse)
    def get_run_report(run_id: str, autoprint: bool = Query(default=False)) -> HTMLResponse:
        latest = _resolve_snapshot(get_workflow(), run_id, runs, get_jobs())
        if latest is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return HTMLResponse(render_report_html(latest, autoprint=autoprint))

    @app.get("/runs/{run_id}/stream")
    @app.get("/api/runs/{run_id}/stream")
    def stream_run_events(run_id: str) -> StreamingResponse:
        session = runs.get(run_id)
        durable = get_workflow().reviews.load(run_id)
        if session is None or durable is not None:
            persisted = durable or _resolve_snapshot(get_workflow(), run_id, runs, get_jobs())
            if persisted is None:
                raise HTTPException(status_code=404, detail="Run not found")

            def single_event_stream() -> Iterator[bytes]:
                yield _to_sse({"type": "snapshot", "payload": persisted})
                yield _to_sse({"type": "complete", "payload": persisted})

            return StreamingResponse(single_event_stream(), media_type="text/event-stream")
        return StreamingResponse((_to_sse(event) for event in session.stream_events()), media_type="text/event-stream")

    return app


def run(host: str = "127.0.0.1", port: int = 8000, storage_root: Path | None = None) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("uvicorn is required to serve the FastAPI web app.") from exc

    app_instance = create_app(str(storage_root) if storage_root else None)
    uvicorn.run(app_instance, host=host, port=port, log_level="info")


app = create_app()
