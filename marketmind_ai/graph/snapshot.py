from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel

from ..config import DEFAULT_ANALYSTS
from ..symbols import SymbolResolution

if TYPE_CHECKING:
    from .request import AnalysisRequest


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class AgentStatusView:
    key: str
    label: str
    status: str


@dataclass
class MessageView:
    timestamp: str
    kind: str
    content: str
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class ToolCallView:
    timestamp: str
    name: str
    args: str
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class ReportSectionView:
    key: str
    label: str
    content: Optional[str] = None


@dataclass
class RunSnapshot:
    run_id: str
    status: str
    original_input: str
    ticker: str
    analysis_date: str
    provider: str
    quick_model: str
    deep_model: str
    output_language: str
    selected_analysts: List[str]
    started_at: str
    resolved_from: Optional[str] = None
    company_name: Optional[str] = None
    exchange: str = ""
    region: str = ""
    currency: str = ""
    ticker_resolution: Optional[SymbolResolution] = None
    finished_at: Optional[str] = None
    current_agent: Optional[str] = None
    latest_update: str = ""
    agents: List[AgentStatusView] = field(default_factory=list)
    messages: List[MessageView] = field(default_factory=list)
    tool_calls: List[ToolCallView] = field(default_factory=list)
    reports: List[ReportSectionView] = field(default_factory=list)
    final_signal: Optional[str] = None
    final_decision: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        request: "AnalysisRequest",
        resolution: SymbolResolution,
        labels: Dict[str, str],
        report_labels: Dict[str, str],
    ) -> "RunSnapshot":
        selected = [key for key in DEFAULT_ANALYSTS if key in request.analysts]
        agents = [AgentStatusView(key=key, label=labels[key], status="pending") for key in selected]
        for key in (
            "bull",
            "bear",
            "research_manager",
            "trader",
            "aggressive",
            "conservative",
            "neutral",
            "portfolio_manager",
        ):
            agents.append(AgentStatusView(key=key, label=labels[key], status="pending"))
        resolved_symbol = resolution.resolved_symbol or request.ticker
        resolved_from = request.ticker if request.ticker.upper() != resolved_symbol.upper() else None
        reports = [ReportSectionView(key=key, label=label) for key, label in report_labels.items()]
        return cls(
            run_id=run_id,
            status="queued",
            original_input=request.ticker,
            ticker=resolved_symbol,
            resolved_from=resolved_from,
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
            selected_analysts=selected,
            started_at=utc_now(),
            latest_update=resolution.reason or "Ready to begin.",
            agents=agents,
            reports=reports,
        )

    def clone(self) -> "RunSnapshot":
        return deepcopy(self)

    def to_dict(self) -> dict:
        return _json_safe(self)
