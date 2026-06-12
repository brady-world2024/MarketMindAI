from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from ..config import DEFAULT_ANALYSTS, normalize_analyst_key, provider_catalog
from ..symbols import SymbolCandidate, SymbolResolution


ANALYST_KEYS = tuple(DEFAULT_ANALYSTS)


class ModelOption(BaseModel):
    label: str
    value: str


class ProviderOption(BaseModel):
    value: str
    label: str
    requires_api_key: bool = True
    supports_custom_models: bool = False
    custom_model_placeholder: Optional[str] = None
    quick_models: list[ModelOption]
    deep_models: list[ModelOption]
    base_url: Optional[str] = None


class AnalysisRequest(BaseModel):
    ticker: str
    analysis_date: str
    llm_provider: str
    api_key: Optional[str] = None
    quick_model: str
    deep_model: str
    analysts: list[str] = Field(default_factory=lambda: list(ANALYST_KEYS))
    output_language: str = "English"
    research_depth: int = Field(default=1, ge=1, le=5)
    base_url: Optional[str] = None
    google_thinking_level: Optional[str] = None
    openai_reasoning_effort: Optional[str] = None
    anthropic_effort: Optional[str] = None
    checkpoint_enabled: bool = False

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("ticker cannot be empty")
        if len(cleaned) > 128:
            raise ValueError("ticker is too long")
        if any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t")):
            raise ValueError("ticker contains unsupported control characters")
        return cleaned

    @field_validator("analysis_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("analysis_date must be in YYYY-MM-DD format") from exc
        if parsed > date.today():
            raise ValueError("analysis_date cannot be in the future")
        return parsed.isoformat()

    @field_validator("llm_provider", "quick_model", "deep_model", "output_language")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field cannot be empty")
        return cleaned

    @field_validator("api_key", "base_url", "google_thinking_level", "openai_reasoning_effort", "anthropic_effort")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("analysts")
    @classmethod
    def validate_analysts(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("Select at least one analyst")
        normalized = []
        for item in values:
            key = normalize_analyst_key(item)
            if key not in ANALYST_KEYS:
                raise ValueError(f"Unsupported analyst role: {item}")
            if key not in normalized:
                normalized.append(key)
        return normalized


class RunCreatedResponse(BaseModel):
    run_id: str
    stream_url: str
    result_url: str
    report_url: str
    ticker_resolution: Optional[SymbolResolution] = None


class ResolveSymbolRequest(BaseModel):
    query: str
    analysis_date: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("query cannot be empty")
        if len(cleaned) > 128:
            raise ValueError("query is too long")
        if any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t")):
            raise ValueError("query contains unsupported control characters")
        return cleaned

    @field_validator("analysis_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("analysis_date must be in YYYY-MM-DD format") from exc
        if parsed > date.today():
            raise ValueError("analysis_date cannot be in the future")
        return parsed.isoformat()


class ValidateKeyRequest(BaseModel):
    llm_provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    @field_validator("llm_provider", "model")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field cannot be empty")
        return cleaned

    @field_validator("api_key", "base_url")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ValidateKeyResponse(BaseModel):
    valid: bool
    provider: str
    model: str
    message: str


class SymbolSearchResponse(BaseModel):
    query: str
    candidates: list[SymbolCandidate]


class AgentStatusView(BaseModel):
    key: str
    label: str
    status: Literal["pending", "in_progress", "completed", "error"]


class MessageView(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: str
    kind: str
    content: str


class ToolCallView(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: str
    name: str
    args: str


class ReportSectionView(BaseModel):
    key: str
    label: str
    content: Optional[str] = None


class RunSnapshot(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed", "error"]
    original_input: str
    ticker: str
    resolved_from: Optional[str] = None
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    ticker_resolution: Optional[SymbolResolution] = None
    analysis_date: str
    provider: str
    quick_model: str
    deep_model: str
    output_language: str
    selected_analysts: list[str]
    started_at: str
    finished_at: Optional[str] = None
    current_agent: Optional[str] = None
    latest_update: Optional[str] = None
    agents: list[AgentStatusView]
    messages: list[MessageView]
    tool_calls: list[ToolCallView]
    reports: list[ReportSectionView]
    final_signal: Optional[str] = None
    final_decision: Optional[str] = None
    error: Optional[str] = None


def provider_values() -> set[str]:
    return {option.value for option in provider_catalog()}
