from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
import hashlib
import json

from ..agents.utils.memory_retrieval import MarketMindMemoryRetriever
from ..config import AppPaths, DEFAULT_ANALYSTS
from ..dataflows.config import DataflowAudit, dataflow_context, get_audit
from ..dataflows.preflight import run_preflight
from ..evaluation import OutcomeEvaluator
from ..llm_clients import build_model_bundle
from ..symbols import SymbolResolver
from ..verification import DecisionVerifier
from .checkpointer import clear_checkpoint, get_checkpointer, has_checkpoint, thread_id
from .pending_outcomes import PendingOutcomeResolver
from .request import AnalysisRequest
from .runtime_support import GraphResearchEngine, build_offline_data_vendor_config
from .signal_processing import SignalProcessor
from .snapshot_support import SnapshotProjector, extract_text
from .storage import DecisionJournal, RunArchive
from .review import ReviewStore


class MarketMindGraph:
    def __init__(
        self,
        selected_analysts: Optional[list[str]] = None,
        debug: bool = False,
        config: dict[str, Any] | None = None,
        storage_root: Optional[Path] = None,
    ) -> None:
        self.debug = debug
        self.selected_analysts = selected_analysts or list(DEFAULT_ANALYSTS)
        self.paths = AppPaths(storage_root) if storage_root else AppPaths()
        self.config = self.paths.runtime_config(overrides=config)
        self.archive = RunArchive(self.paths)
        self.reviews = ReviewStore(self.paths.root / "reviews.sqlite3")
        self.journal = DecisionJournal(self.paths)
        self.memory_log = self.journal.memory_log
        self.resolver = SymbolResolver()
        self.verifier = DecisionVerifier()
        self.memory_retriever = MarketMindMemoryRetriever(self.config, self.memory_log)
        self.outcome_evaluator = OutcomeEvaluator(self.config, self.memory_log)
        self.projector = SnapshotProjector(SignalProcessor())
        self.pending_outcomes = PendingOutcomeResolver(self.memory_log)

    def resolve_symbol(self, query: str, analysis_date: str):
        with dataflow_context(self.config):
            return self.resolver.resolve(query, analysis_date)

    def resolve_for_research(self, query: str, analysis_date: str):
        with dataflow_context(self.config):
            return self.resolver.resolve_identity(query, analysis_date)

    def validate_provider(self, request: AnalysisRequest) -> tuple[bool, str]:
        if request.llm_provider.lower() == "offline":
            return True, "Offline LangGraph runtime is always available."
        try:
            bundle = build_model_bundle(request)
            response = bundle.quick.invoke("Reply with the single word OK.")
            content = extract_text(getattr(response, "content", response))
            return ("OK" in content.upper(), content or "Provider responded.")
        except Exception as exc:
            return False, str(exc)

    def stream(self, request: AnalysisRequest, run_id: Optional[str] = None):
        runtime_config = self._runtime_config_for_request(request)
        identifier = run_id or uuid4().hex
        audit = DataflowAudit(run_id=identifier)
        iterator = self._stream_scoped(request, identifier, runtime_config)
        # Reset ContextVars before every yield: interleaved generators must not
        # expose another run's config or leave a context active in the caller.
        try:
            while True:
                with dataflow_context(runtime_config, audit=audit):
                    try:
                        snapshot = next(iterator)
                    except StopIteration:
                        return
                yield snapshot
        finally:
            with dataflow_context(runtime_config, audit=audit):
                iterator.close()

    @staticmethod
    def _attach_sources(snapshot, availability):
        audit = get_audit()
        snapshot.data_mode = availability.data_mode
        snapshot.data_availability = availability.to_dict()
        snapshot.instrument_eligibility = availability.instrument.to_dict() if availability.instrument else None
        snapshot.source_attempts = [item.to_dict() for item in audit.attempts] if audit else []
        snapshot.source_materials = [item.to_dict() for item in audit.materials] if audit else []

    def _stream_scoped(self, request, run_id, runtime_config):
        resolution = self.resolver.resolve_identity(request.ticker, request.analysis_date)
        if resolution.status != "RESOLVED":
            raise ValueError(resolution.reason or "Symbol resolution failed.")

        ticker = resolution.resolved_symbol or request.ticker
        snapshot = self.projector.create_snapshot(run_id=run_id, request=request, resolution=resolution)
        snapshot.status = "running"
        snapshot.data_mode = runtime_config['data_mode']
        snapshot.latest_update = "Checking security eligibility and required data. No AI analysis yet."
        yield snapshot.clone()
        availability = run_preflight(ticker, request.analysis_date)
        self._attach_sources(snapshot, availability)
        if not availability.can_recommend:
            missing = ', '.join(availability.missing)
            reason = f"Required data unavailable: {missing}. Reasons: {', '.join(availability.reason_codes)}"
            snapshot.status = 'completed'
            snapshot.finished_at = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            snapshot.latest_update = 'Data incomplete. No AI analysis. 无法形成建议。'
            snapshot.final_signal = 'No Recommendation'
            snapshot.final_decision = f'Final Decision Status: No Recommendation\n无法形成建议。No AI analysis was performed.\n{reason}'
            snapshot.final_structured_decision = {'decision_status': 'No Recommendation', 'rating': None,
                'confidence': None, 'price_target': None, 'time_horizon': None, 'investment_thesis': None,
                'executive_summary': 'No AI analysis was performed. 无法形成建议。', 'evidence_gap': reason,
                'key_risks': [], 'primary_evidence': []}
            snapshot.report_verification = {'status': 'blocked', 'blocks_actionable_recommendation': True,
                                             'summary': reason, 'issues': [{'code': code, 'message': code.replace('_', ' ')}
                                                                        for code in availability.reason_codes]}
            for agent in snapshot.agents:
                agent.status = 'skipped'
            draft = self.reviews.save_draft(snapshot.to_dict(), request, {})
            snapshot.review = draft['review']
            self.archive.save(snapshot)
            yield snapshot.clone()
            return

        snapshot.latest_update = 'Required data passed preflight. Preparing AI analysis.'
        yield snapshot.clone()
        try:
            engine = GraphResearchEngine(
                request=request,
                resolution=resolution.to_dict(),
                journal=self.journal,
                verifier=self.verifier,
                max_recur_limit=int(runtime_config.get("max_recur_limit", 100) or 100),
            )
        except Exception as exc:
            snapshot.status = 'error'
            snapshot.error = 'AI connection could not be initialized. Check provider credentials and settings.'
            snapshot.latest_update = snapshot.error
            snapshot.finished_at = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            self.archive.save(snapshot)
            yield snapshot.clone()
            # The original provider exception may contain connection secrets.
            raise ValueError(snapshot.error) from None
        availability.ai_analysis_performed = True
        self.pending_outcomes.resolve_for_ticker(ticker, request.analysis_date, engine.models.quick)
        calibration_summary = self.outcome_evaluator.build_summary()
        memory_contexts = self.memory_retriever.build_contexts(ticker, request.analysis_date)
        self._attach_sources(snapshot, availability)
        snapshot.latest_update = resolution.reason or "Resolved symbol. Preparing LangGraph analysis."
        yield snapshot.clone()

        workflow = engine.build_graph()
        initial_state = engine.initial_state()
        initial_state["past_context"] = self.memory_log.get_past_context(ticker)
        initial_state["calibration_summary"] = calibration_summary
        initial_state.update(memory_contexts)
        current_state = None

        try:
            if request.checkpoint_enabled:
                # Legacy ticker/date checkpoints have unknown provenance. New
                # checkpoints belong to one run and one explicit source config.
                source_identity = json.dumps({key: runtime_config.get(key) for key in
                    ('data_mode', 'data_vendors', 'tool_vendors')}, sort_keys=True)
                checkpoint_namespace = f"{run_id}:{hashlib.sha256(source_identity.encode()).hexdigest()}"
                with get_checkpointer(self.paths.root, ticker) as saver:
                    graph = workflow.compile(checkpointer=saver)
                    config = {
                        "configurable": {"thread_id": thread_id(ticker, request.analysis_date, namespace=checkpoint_namespace)},
                        "recursion_limit": int(runtime_config.get("max_recur_limit", 100) or 100),
                    }
                    start_input = None if has_checkpoint(self.paths.root, ticker, request.analysis_date, namespace=checkpoint_namespace) else initial_state
                    for state in graph.stream(start_input, config=config, stream_mode="values"):
                        current_state = state
                        self.projector.apply_state(snapshot, state)
                        self._attach_sources(snapshot, availability)
                        yield snapshot.clone()
                clear_checkpoint(self.paths.root, ticker, request.analysis_date, namespace=checkpoint_namespace)
            else:
                graph = workflow.compile()
                config = {"recursion_limit": int(runtime_config.get("max_recur_limit", 100) or 100)}
                for state in graph.stream(initial_state, config=config, stream_mode="values"):
                    current_state = state
                    self.projector.apply_state(snapshot, state)
                    self._attach_sources(snapshot, availability)
                    yield snapshot.clone()
        except Exception as exc:
            snapshot.status = "error"
            snapshot.error = str(exc)
            snapshot.latest_update = "LangGraph run failed."
            yield snapshot.clone()
            raise

        if current_state is None:
            raise RuntimeError("LangGraph run produced no state output")

        snapshot.status = "completed"
        snapshot.finished_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        snapshot.current_agent = None
        snapshot.latest_update = "Research complete."
        self._attach_sources(snapshot, availability)
        draft = self.reviews.save_draft(snapshot.to_dict(), request, self.projector.state_log_payload(current_state))
        snapshot.review = draft["review"]
        self.archive.save(snapshot)
        self.outcome_evaluator.write_summary()
        yield snapshot.clone()

    def _runtime_config_for_request(self, request: AnalysisRequest) -> dict[str, Any]:
        config = deepcopy(self.config)
        config.update(
            {
                "llm_provider": request.llm_provider,
                "data_mode": "demo" if request.llm_provider.lower() == "offline" else "live",
                "deep_think_llm": request.deep_model,
                "quick_think_llm": request.quick_model,
                "api_key": request.api_key or None,
                "backend_url": request.base_url or None,
                "google_thinking_level": request.google_thinking_level or None,
                "openai_reasoning_effort": request.openai_reasoning_effort or None,
                "anthropic_effort": request.anthropic_effort or None,
                "checkpoint_enabled": request.checkpoint_enabled,
                "output_language": request.output_language,
                "max_debate_rounds": request.research_depth,
                "max_risk_discuss_rounds": request.research_depth,
            }
        )
        if request.llm_provider.lower() == "offline":
            config["data_vendors"] = build_offline_data_vendor_config()
        return config


__all__ = ["MarketMindGraph", "build_offline_data_vendor_config"]
