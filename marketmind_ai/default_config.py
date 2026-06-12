"""Default runtime configuration for MarketMind AI."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from typing import Any


def _getenv(name: str, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    return default


def default_storage_root() -> Path:
    configured = os.getenv("MARKETMIND_AI_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".marketmind"


def build_default_config(storage_root: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(storage_root).expanduser() if storage_root else default_storage_root()
    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "project_dir": str(Path(__file__).resolve().parent),
            "root_dir": str(root),
            "results_dir": str(root / "logs"),
            "runs_dir": str(root / "runs"),
            "web_runs_dir": str(root / "runs" / "web"),
            "data_cache_dir": str(root / "cache"),
            "memory_dir": str(root / "memory"),
            "memory_file": str(root / "memory" / "decisions.jsonl"),
            "memory_log_path": str(root / "memory" / "marketmind_memory.md"),
            "evaluation_dir": str(root / "evaluation"),
            "evaluation_summary_path": str(root / "evaluation" / "decision_evaluation.json"),
            "checkpoints_dir": str(root / "checkpoints"),
        }
    )
    if overrides:
        _merge_dict(config, overrides)
    return config


def _merge_dict(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = value


DEFAULT_CONFIG: dict[str, Any] = {
    "project_dir": str(Path(__file__).resolve().parent),
    "root_dir": str(default_storage_root()),
    "results_dir": _getenv("MARKETMIND_RESULTS_DIR", str(default_storage_root() / "logs")),
    "runs_dir": _getenv("MARKETMIND_RUNS_DIR", str(default_storage_root() / "runs")),
    "web_runs_dir": _getenv("MARKETMIND_WEB_RUNS_DIR", str(default_storage_root() / "runs" / "web")),
    "data_cache_dir": _getenv("MARKETMIND_CACHE_DIR", str(default_storage_root() / "cache")),
    "memory_dir": _getenv("MARKETMIND_MEMORY_DIR", str(default_storage_root() / "memory")),
    "memory_file": _getenv("MARKETMIND_MEMORY_FILE", str(default_storage_root() / "memory" / "decisions.jsonl")),
    "memory_log_path": _getenv(
        "MARKETMIND_MEMORY_LOG_PATH",
        str(default_storage_root() / "memory" / "marketmind_memory.md"),
    ),
    "evaluation_dir": _getenv("MARKETMIND_EVALUATION_DIR", str(default_storage_root() / "evaluation")),
    "evaluation_summary_path": _getenv(
        "MARKETMIND_EVALUATION_SUMMARY_PATH",
        str(default_storage_root() / "evaluation" / "decision_evaluation.json"),
    ),
    "checkpoints_dir": _getenv("MARKETMIND_CHECKPOINTS_DIR", str(default_storage_root() / "checkpoints")),
    "memory_log_max_entries": None,
    "memory_retrieval_enabled": True,
    "memory_retrieval_same_limit": 3,
    "memory_retrieval_cross_limit": 2,
    "memory_retrieval_report_limit": 3,
    "memory_retrieval_report_chars": 700,
    "report_verifier_enabled": True,
    "evaluation_holding_days": 5,
    "evaluation_hold_band": 0.02,
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "api_key": None,
    "backend_url": None,
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "checkpoint_enabled": False,
    "output_language": "English",
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "fundamental_document_data": "sec,alpha_vantage",
        "news_data": "yfinance",
        "news_document_data": "yfinance,alpha_vantage",
        "symbol_resolution": "yfinance",
    },
    "tool_vendors": {},
    "fundamentals_rag_enabled": True,
    "fundamentals_rag_max_chunks": 6,
    "fundamentals_rag_chunk_chars": 1400,
    "news_rag_enabled": True,
    "news_rag_company_limit": 6,
    "news_rag_macro_limit": 4,
    "sec_user_agent": _getenv(
        "MARKETMIND_SEC_USER_AGENT",
        "MarketMindAI/1.0 (research tooling; contact: marketmindai@example.com)",
    ),
}
