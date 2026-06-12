from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"


class CommandName(str, Enum):
    ANALYZE = "analyze"
    INTERACTIVE = "interactive"
    RESOLVE = "resolve"
    VALIDATE_PROVIDER = "validate-provider"
    SERVE = "serve"


@dataclass(frozen=True)
class AnalyzeOptions:
    ticker: str
    analysis_date: str
    llm_provider: str
    api_key: str
    quick_model: str
    deep_model: str
    output_language: str
    base_url: str
    google_thinking_level: str
    openai_reasoning_effort: str
    anthropic_effort: str
    analysts: list[str] = field(default_factory=list)
    research_depth: int = 1
    checkpoint_enabled: bool = False
    storage_root: str = ""
    emit_json: bool = False


@dataclass(frozen=True)
class ResolveOptions:
    query: str
    analysis_date: str
    storage_root: str = ""


@dataclass(frozen=True)
class ValidateProviderOptions:
    llm_provider: str
    api_key: str
    quick_model: str
    deep_model: str
    base_url: str
    google_thinking_level: str
    openai_reasoning_effort: str
    anthropic_effort: str
    storage_root: str = ""


@dataclass(frozen=True)
class ServeOptions:
    host: str
    port: int
    storage_root: str = ""


@dataclass(frozen=True)
class AnnouncementPayload:
    announcements: list[str] = field(default_factory=list)
    require_attention: bool = False


@dataclass(frozen=True)
class RunStatistics:
    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    agent_updates: int = 0
    snapshots_seen: int = 0
    message_count: int = 0
    elapsed_seconds: float = 0.0
