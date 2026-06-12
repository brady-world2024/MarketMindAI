from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List

from ..config import DEFAULT_ANALYSTS, SUPPORTED_ANALYSTS, normalize_analyst_key


@dataclass
class AnalysisRequest:
    ticker: str
    analysis_date: str
    llm_provider: str = "openai"
    api_key: str = ""
    quick_model: str = "gpt-5.4-mini"
    deep_model: str = "gpt-5.4"
    analysts: List[str] = field(default_factory=lambda: list(DEFAULT_ANALYSTS))
    output_language: str = "English"
    research_depth: int = 1
    base_url: str = ""
    google_thinking_level: str = ""
    openai_reasoning_effort: str = ""
    anthropic_effort: str = ""
    storage_root: str = ""
    checkpoint_enabled: bool = False

    @classmethod
    def from_mapping(cls, payload: Dict[str, Any]) -> "AnalysisRequest":
        ticker = " ".join(str(payload.get("ticker", "")).split())
        if not ticker:
            raise ValueError("ticker cannot be empty")
        if len(ticker) > 128:
            raise ValueError("ticker is too long")
        analysis_date = str(payload.get("analysis_date", "")).strip()
        try:
            parsed = datetime.strptime(analysis_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("analysis_date must be YYYY-MM-DD") from exc
        if parsed > date.today():
            raise ValueError("analysis_date cannot be in the future")
        llm_provider = str(payload.get("llm_provider", "openai")).strip() or "openai"
        quick_model = str(payload.get("quick_model", "gpt-5.4-mini")).strip() or "gpt-5.4-mini"
        deep_model = str(payload.get("deep_model", "gpt-5.4")).strip() or "gpt-5.4"
        output_language = str(payload.get("output_language", "English")).strip() or "English"
        research_depth = int(payload.get("research_depth", 1))
        if research_depth < 1 or research_depth > 5:
            raise ValueError("research_depth must be between 1 and 5")
        raw_analysts = payload.get("analysts", list(DEFAULT_ANALYSTS))
        if not isinstance(raw_analysts, list):
            raise ValueError("analysts must be a list")
        analysts: List[str] = []
        for item in raw_analysts:
            key = normalize_analyst_key(str(item))
            if key not in SUPPORTED_ANALYSTS:
                raise ValueError(f"unsupported analyst role: {item}")
            if key not in analysts:
                analysts.append(key)
        if not analysts:
            raise ValueError("at least one analyst must be selected")
        return cls(
            ticker=ticker,
            analysis_date=parsed.isoformat(),
            llm_provider=llm_provider,
            api_key=str(payload.get("api_key", "")).strip(),
            quick_model=quick_model,
            deep_model=deep_model,
            analysts=analysts,
            output_language=output_language,
            research_depth=research_depth,
            base_url=str(payload.get("base_url", "")).strip(),
            google_thinking_level=str(payload.get("google_thinking_level", "")).strip(),
            openai_reasoning_effort=str(payload.get("openai_reasoning_effort", "")).strip(),
            anthropic_effort=str(payload.get("anthropic_effort", "")).strip(),
            storage_root=str(payload.get("storage_root", "")).strip(),
            checkpoint_enabled=bool(payload.get("checkpoint_enabled", False)),
        )
