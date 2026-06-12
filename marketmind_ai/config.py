from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .default_config import build_default_config, default_storage_root
from .pathing import safe_ticker_component


APP_NAME = "MarketMind AI Rebuild"
DEFAULT_ANALYSTS = ("market", "social", "news", "fundamentals")
SUPPORTED_ANALYSTS = set(DEFAULT_ANALYSTS) | {"sentiment"}


def normalize_analyst_key(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned == "sentiment":
        return "social"
    return cleaned


def to_runtime_analyst_key(value: str) -> str:
    normalized = normalize_analyst_key(value)
    if normalized == "social":
        return "sentiment"
    return normalized


def from_runtime_analyst_key(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned == "sentiment":
        return "social"
    return cleaned

def runtime_defaults(
    storage_root: str | Path | None = None,
    overrides: dict | None = None,
) -> dict:
    return build_default_config(storage_root=storage_root, overrides=overrides)


@dataclass(frozen=True)
class ProviderOption:
    value: str
    label: str
    requires_api_key: bool
    supports_custom_models: bool
    quick_models: List[str]
    deep_models: List[str]
    custom_model_placeholder: str = ""
    base_url: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "label": self.label,
            "requires_api_key": self.requires_api_key,
            "supports_custom_models": self.supports_custom_models,
            "custom_model_placeholder": self.custom_model_placeholder or None,
            "base_url": self.base_url or None,
            "quick_models": [{"label": model, "value": model} for model in self.quick_models],
            "deep_models": [{"label": model, "value": model} for model in self.deep_models],
        }


def provider_catalog() -> List[ProviderOption]:
    return [
        ProviderOption(
            value="openai",
            label="OpenAI",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["gpt-4o-mini", "gpt-5.4-mini"],
            deep_models=["gpt-4o", "gpt-5.4"],
            custom_model_placeholder="Enter a chat-completions model",
            base_url="https://api.openai.com/v1",
        ),
        ProviderOption(
            value="anthropic",
            label="Anthropic",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
            deep_models=["claude-3-7-sonnet-latest", "claude-opus-4-1"],
            custom_model_placeholder="Enter a Claude model id",
        ),
        ProviderOption(
            value="google",
            label="Google Gemini",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["gemini-2.0-flash", "gemini-2.5-flash"],
            deep_models=["gemini-2.5-pro"],
            custom_model_placeholder="Enter a Gemini model id",
        ),
        ProviderOption(
            value="xai",
            label="xAI-Compatible API",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["grok-2-mini"],
            deep_models=["grok-2"],
            custom_model_placeholder="Enter a Grok model id",
            base_url="https://api.x.ai/v1",
        ),
        ProviderOption(
            value="deepseek",
            label="DeepSeek-Compatible API",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["deepseek-chat"],
            deep_models=["deepseek-reasoner"],
            custom_model_placeholder="Enter a DeepSeek model id",
            base_url="https://api.deepseek.com/v1",
        ),
        ProviderOption(
            value="qwen",
            label="Qwen-Compatible API",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["qwen-turbo"],
            deep_models=["qwen-max"],
            custom_model_placeholder="Enter a Qwen model id",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        ProviderOption(
            value="glm",
            label="GLM-Compatible API",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["glm-4-flash"],
            deep_models=["glm-4-plus"],
            custom_model_placeholder="Enter a GLM model id",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        ),
        ProviderOption(
            value="openrouter",
            label="OpenRouter",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["openai/gpt-4o-mini", "anthropic/claude-3.5-haiku"],
            deep_models=["openai/gpt-4o", "anthropic/claude-3.7-sonnet"],
            custom_model_placeholder="Enter an OpenRouter model id",
            base_url="https://openrouter.ai/api/v1",
        ),
        ProviderOption(
            value="azure",
            label="Azure OpenAI",
            requires_api_key=True,
            supports_custom_models=True,
            quick_models=["gpt-4o-mini"],
            deep_models=["gpt-4o", "gpt-5.4"],
            custom_model_placeholder="Enter an Azure deployment name",
        ),
        ProviderOption(
            value="ollama",
            label="Ollama Local Server",
            requires_api_key=False,
            supports_custom_models=True,
            quick_models=["qwen2.5:7b", "llama3.1:8b"],
            deep_models=["qwen2.5:14b", "llama3.1:70b"],
            custom_model_placeholder="Enter a local Ollama model name",
            base_url="http://127.0.0.1:11434/v1",
        ),
        ProviderOption(
            value="offline",
            label="Offline Research Engine",
            requires_api_key=False,
            supports_custom_models=False,
            quick_models=["heuristic-fast"],
            deep_models=["heuristic-deep"],
        ),
    ]


def provider_defaults(value: str) -> ProviderOption:
    for option in provider_catalog():
        if option.value == value:
            return option
    return provider_catalog()[0]


@dataclass
class AppPaths:
    root: Path = field(default_factory=default_storage_root)

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def web_runs_dir(self) -> Path:
        return self.runs_dir / "web"

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def memory_file(self) -> Path:
        return self.memory_dir / "decisions.jsonl"

    @property
    def memory_log_path(self) -> Path:
        return self.memory_dir / "marketmind_memory.md"

    @property
    def evaluations_dir(self) -> Path:
        return self.root / "evaluation"

    @property
    def evaluation_summary_path(self) -> Path:
        return self.evaluations_dir / "decision_evaluation.json"

    @property
    def results_dir(self) -> Path:
        return self.root / "logs"

    @property
    def checkpoints_dir(self) -> Path:
        return self.root / "checkpoints"

    def strategy_logs_dir(self, ticker: str) -> Path:
        return self.results_dir / safe_ticker_component(ticker) / "MarketMindStrategy_logs"

    def state_log_path(self, ticker: str, analysis_date: str) -> Path:
        return self.strategy_logs_dir(ticker) / f"full_states_log_{analysis_date}.json"

    def runtime_config(self, overrides: dict | None = None) -> dict:
        return build_default_config(self.root, overrides=overrides)

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.web_runs_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
