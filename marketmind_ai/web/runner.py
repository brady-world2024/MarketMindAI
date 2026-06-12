from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .catalog import supported_provider_values
from .models import AnalysisRequest, RunSnapshot
from ..graph import MarketMindGraph
from ..graph.request import AnalysisRequest as CoreAnalysisRequest


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_graph_config(request: AnalysisRequest) -> dict[str, Any]:
    if request.llm_provider not in supported_provider_values():
        raise ValueError(f"Unsupported provider for the web UI: {request.llm_provider}")
    return {
        "llm_provider": request.llm_provider,
        "api_key": request.api_key,
        "quick_think_llm": request.quick_model,
        "deep_think_llm": request.deep_model,
        "output_language": request.output_language,
        "max_debate_rounds": request.research_depth,
        "max_risk_discuss_rounds": request.research_depth,
        "checkpoint_enabled": request.checkpoint_enabled,
        "base_url": request.base_url,
        "google_thinking_level": request.google_thinking_level,
        "openai_reasoning_effort": request.openai_reasoning_effort,
        "anthropic_effort": request.anthropic_effort,
    }


def to_core_request(request: AnalysisRequest) -> CoreAnalysisRequest:
    return CoreAnalysisRequest.from_mapping(request.model_dump(mode="python"))


def resolve_request_symbol(request: AnalysisRequest, workflow: MarketMindGraph | None = None):
    if workflow is None:
        runtime = MarketMindGraph(config=build_graph_config(request))
    else:
        runtime = MarketMindGraph(storage_root=workflow.paths.root, config=build_graph_config(request))
    return runtime.resolve_symbol(request.ticker, request.analysis_date)


class SnapshotBuilder:
    def __init__(self, run_id: str, request: AnalysisRequest, resolution):
        self.snapshot = RunSnapshot(
            run_id=run_id,
            status="queued",
            original_input=request.ticker,
            ticker=resolution.resolved_symbol or request.ticker,
            resolved_from=request.ticker if (resolution.resolved_symbol or request.ticker).upper() != request.ticker.upper() else None,
            company_name=resolution.company_name,
            exchange=resolution.exchange,
            region=resolution.region,
            currency=resolution.currency,
            ticker_resolution=resolution,
            analysis_date=request.analysis_date,
            provider=request.llm_provider,
            quick_model=request.quick_model,
            deep_model=request.deep_model,
            output_language=request.output_language,
            selected_analysts=request.analysts,
            started_at=iso_now(),
            current_agent=None,
            latest_update=resolution.reason or "Ready to start analysis.",
            agents=[],
            messages=[],
            tool_calls=[],
            reports=[],
        )

    def sync_from_core_snapshot(self, snapshot: Any) -> RunSnapshot:
        self.snapshot = RunSnapshot.model_validate(snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot)
        return deepcopy(self.snapshot)
