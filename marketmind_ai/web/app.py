from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..graph import MarketMindGraph
from ..symbols import SymbolResolution
from .catalog import build_provider_catalog
from .models import AnalysisRequest, RunCreatedResponse, ValidateKeyRequest, ValidateKeyResponse
from .report_export import render_report_html
from .runner import resolve_request_symbol, to_core_request
from .symbols_router import router as symbols_router


STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    configured = os.getenv("MARKETMIND_WEB_ALLOWED_ORIGINS", "")
    if configured.strip():
        return [item.strip() for item in configured.split(",") if item.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


class RunSession:
    def __init__(self, run_id: str):
        self.run_id = run_id
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

    def stream_events(self) -> Iterator[dict[str, Any]]:
        index = 0
        while True:
            with self._condition:
                while index >= len(self._history) and not self._done:
                    self._condition.wait(timeout=0.5)
                batch = self._history[index:]
                done = self._done
            for event in batch:
                yield event
                index += 1
            if done and index >= len(self._history):
                break


class RunRegistry:
    def __init__(self):
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()

    def create(self) -> RunSession:
        run_id = uuid.uuid4().hex[:12]
        session = RunSession(run_id)
        with self._lock:
            self._sessions[run_id] = session
        return session

    def get(self, run_id: str) -> RunSession | None:
        with self._lock:
            return self._sessions.get(run_id)


RUNS = RunRegistry()
AnalysisThread = threading.Thread


def _to_sse(event: dict[str, Any]) -> bytes:
    payload = json.dumps(event["payload"], ensure_ascii=False)
    return f"event: {event['type']}\ndata: {payload}\n\n".encode("utf-8")


def _persist_snapshot(workflow: MarketMindGraph, run_id: str, snapshot: dict[str, Any]) -> None:
    workflow.archive.save_web_snapshot(run_id, snapshot)


def _load_persisted_snapshot(workflow: MarketMindGraph, run_id: str) -> dict[str, Any] | None:
    return workflow.archive.load(run_id)


def _resolve_snapshot(workflow: MarketMindGraph, run_id: str) -> dict[str, Any] | None:
    session = RUNS.get(run_id)
    if session is not None and session.latest_snapshot is not None:
        return session.latest_snapshot
    return _load_persisted_snapshot(workflow, run_id)


def _resolution_http_detail(resolved: SymbolResolution) -> dict[str, Any]:
    return {
        "status": resolved.status,
        "message": resolved.reason,
        "resolution": resolved.to_dict(),
    }


def _run_analysis_thread(session: RunSession, workflow: MarketMindGraph, request: AnalysisRequest, resolution: SymbolResolution) -> None:
    try:
        core_request = to_core_request(request)
        for snapshot in workflow.stream(core_request, run_id=session.run_id):
            payload = snapshot.to_dict()
            session.publish("snapshot", payload)
        final_snapshot = session.latest_snapshot
        if final_snapshot is not None:
            _persist_snapshot(workflow, session.run_id, final_snapshot)
            session.publish("complete", final_snapshot)
    except Exception as exc:
        latest = session.latest_snapshot or {
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
            "error": str(exc),
        }
        latest["status"] = "error"
        latest["error"] = str(exc)
        latest["latest_update"] = "Analysis failed."
        _persist_snapshot(workflow, session.run_id, latest)
        session.publish("snapshot", latest)
        session.publish("error", {"message": str(exc)})
    finally:
        session.finish()


def create_app(storage_root: str | None = None) -> FastAPI:
    resolved_storage_root = Path(storage_root).expanduser() if storage_root else None
    workflow: MarketMindGraph | None = None

    def get_workflow() -> MarketMindGraph:
        nonlocal workflow
        if workflow is None:
            workflow = MarketMindGraph(storage_root=resolved_storage_root)
        return workflow

    app = FastAPI(title="MarketMind AI Web", version="0.2.0")
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
        resolved = resolve_request_symbol(request, current_workflow)
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
        session = RUNS.create()
        worker = AnalysisThread(
            target=_run_analysis_thread,
            args=(session, current_workflow, request, resolved),
            daemon=True,
        )
        worker.start()
        return RunCreatedResponse(
            run_id=session.run_id,
            stream_url=f"/runs/{session.run_id}/stream",
            result_url=f"/runs/{session.run_id}/result",
            report_url=f"/runs/{session.run_id}/report",
            ticker_resolution=resolved,
        )

    @app.get("/runs/{run_id}")
    @app.get("/api/runs/{run_id}")
    def get_run_snapshot(run_id: str) -> JSONResponse:
        latest = _resolve_snapshot(get_workflow(), run_id)
        if latest is None:
            session = RUNS.get(run_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            return JSONResponse({"status": "queued", "run_id": run_id})
        return JSONResponse(latest)

    @app.get("/runs/{run_id}/result")
    @app.get("/api/runs/{run_id}/result")
    def get_run_result(run_id: str) -> JSONResponse:
        latest = _resolve_snapshot(get_workflow(), run_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if latest.get("status") not in {"completed", "error"}:
            raise HTTPException(status_code=409, detail="Run is not finished yet")
        return JSONResponse(latest)

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    @app.get("/api/runs/{run_id}/report", response_class=HTMLResponse)
    def get_run_report(run_id: str, autoprint: bool = Query(default=False)) -> HTMLResponse:
        latest = _resolve_snapshot(get_workflow(), run_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return HTMLResponse(render_report_html(latest, autoprint=autoprint))

    @app.get("/runs/{run_id}/stream")
    @app.get("/api/runs/{run_id}/stream")
    def stream_run_events(run_id: str) -> StreamingResponse:
        session = RUNS.get(run_id)
        if session is None:
            persisted = _load_persisted_snapshot(get_workflow(), run_id)
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
