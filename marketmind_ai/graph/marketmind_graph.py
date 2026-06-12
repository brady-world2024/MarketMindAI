from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..agents.utils.memory_retrieval import MarketMindMemoryRetriever
from ..config import AppPaths, DEFAULT_ANALYSTS
from ..dataflows.config import set_config
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
        set_config(self.config)
        self.archive = RunArchive(self.paths)
        self.journal = DecisionJournal(self.paths)
        self.memory_log = self.journal.memory_log
        self.resolver = SymbolResolver()
        self.verifier = DecisionVerifier()
        self.memory_retriever = MarketMindMemoryRetriever(self.config, self.memory_log)
        self.outcome_evaluator = OutcomeEvaluator(self.config, self.memory_log)
        self.projector = SnapshotProjector(SignalProcessor())
        self.pending_outcomes = PendingOutcomeResolver(self.memory_log)

    def resolve_symbol(self, query: str, analysis_date: str):
        return self.resolver.resolve(query, analysis_date)

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
        set_config(runtime_config)
        resolution = self.resolve_symbol(request.ticker, request.analysis_date)
        if resolution.status != "RESOLVED":
            raise ValueError(resolution.reason or "Symbol resolution failed.")

        engine = GraphResearchEngine(
            request=request,
            resolution=resolution.to_dict(),
            journal=self.journal,
            verifier=self.verifier,
            max_recur_limit=int(runtime_config.get("max_recur_limit", 100) or 100),
        )
        ticker = resolution.resolved_symbol or request.ticker
        self.pending_outcomes.resolve_for_ticker(ticker, request.analysis_date, engine.models.quick)
        memory_contexts = self.memory_retriever.build_contexts(ticker, request.analysis_date)
        snapshot = self.projector.create_snapshot(
            run_id=run_id or datetime.utcnow().strftime("%Y%m%d%H%M%S"),
            request=request,
            resolution=resolution,
        )
        snapshot.status = "running"
        snapshot.latest_update = resolution.reason or "Resolved symbol. Preparing LangGraph analysis."
        yield snapshot.clone()

        workflow = engine.build_graph()
        initial_state = engine.initial_state()
        initial_state["past_context"] = self.memory_log.get_past_context(ticker)
        initial_state.update(memory_contexts)
        current_state = None

        try:
            if request.checkpoint_enabled:
                with get_checkpointer(self.paths.root, ticker) as saver:
                    graph = workflow.compile(checkpointer=saver)
                    config = {
                        "configurable": {"thread_id": thread_id(ticker, request.analysis_date)},
                        "recursion_limit": int(runtime_config.get("max_recur_limit", 100) or 100),
                    }
                    start_input = None if has_checkpoint(self.paths.root, ticker, request.analysis_date) else initial_state
                    for state in graph.stream(start_input, config=config, stream_mode="values"):
                        current_state = state
                        self.projector.apply_state(snapshot, state)
                        yield snapshot.clone()
                clear_checkpoint(self.paths.root, ticker, request.analysis_date)
            else:
                graph = workflow.compile()
                config = {"recursion_limit": int(runtime_config.get("max_recur_limit", 100) or 100)}
                for state in graph.stream(initial_state, config=config, stream_mode="values"):
                    current_state = state
                    self.projector.apply_state(snapshot, state)
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
        self.archive.save(snapshot)
        self.archive.save_state_log(ticker, request.analysis_date, self.projector.state_log_payload(current_state))
        decision = self.projector.decision_from_state(current_state, ticker)
        if decision is not None:
            self.journal.remember(ticker, request.analysis_date, decision)
        self.outcome_evaluator.write_summary()
        yield snapshot.clone()

    def _runtime_config_for_request(self, request: AnalysisRequest) -> dict[str, Any]:
        config = deepcopy(self.config)
        config.update(
            {
                "llm_provider": request.llm_provider,
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
