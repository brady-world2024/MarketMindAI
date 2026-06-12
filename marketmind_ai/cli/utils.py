from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import questionary
from rich.console import Console

from ..config import provider_catalog, provider_defaults
from ..graph import MarketMindGraph
from ..graph.request import AnalysisRequest
from ..llm_clients.model_catalog import get_model_options
from .config import DEFAULT_ANALYSIS_DATE, DEFAULT_CLI_ANALYSTS
from .models import AnalyzeOptions, RunStatistics


console = Console()

QUESTIONARY_STYLE = questionary.Style(
    [
        ("text", "fg:green"),
        ("selected", "fg:cyan noinherit"),
        ("highlighted", "fg:cyan noinherit"),
        ("pointer", "fg:cyan noinherit"),
        ("checkbox-selected", "fg:cyan"),
    ]
)

ANALYST_LABELS = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}


class PromptAborted(RuntimeError):
    """Raised when the interactive CLI is cancelled."""


def _abort(message: str = "Interactive session cancelled.") -> PromptAborted:
    return PromptAborted(message)


def normalize_ticker_symbol(value: str) -> str:
    cleaned = "".join(str(value or "").strip().upper().split())
    if not cleaned:
        raise ValueError("ticker cannot be empty")
    return cleaned


def resolve_storage_root(storage_root: str) -> Path | None:
    return Path(storage_root).expanduser() if storage_root else None


def workflow_from_storage_root(storage_root: str) -> MarketMindGraph:
    return MarketMindGraph(storage_root=resolve_storage_root(storage_root))


def build_analysis_request(options: AnalyzeOptions) -> AnalysisRequest:
    payload = {
        "ticker": options.ticker,
        "analysis_date": options.analysis_date,
        "llm_provider": options.llm_provider,
        "api_key": options.api_key,
        "quick_model": options.quick_model,
        "deep_model": options.deep_model,
        "output_language": options.output_language,
        "base_url": options.base_url,
        "google_thinking_level": options.google_thinking_level,
        "openai_reasoning_effort": options.openai_reasoning_effort,
        "anthropic_effort": options.anthropic_effort,
        "research_depth": options.research_depth,
        "storage_root": options.storage_root,
        "checkpoint_enabled": options.checkpoint_enabled,
        "analysts": options.analysts or list(DEFAULT_CLI_ANALYSTS),
    }
    return AnalysisRequest.from_mapping(payload)


def dump_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_run_statistics(stats: RunStatistics) -> str:
    return (
        f"stats: snapshots={stats.snapshots_seen}, agent_updates={stats.agent_updates}, "
        f"tools={stats.tool_calls}, messages={stats.message_count}, "
        f"tokens_in={stats.tokens_in}, tokens_out={stats.tokens_out}, elapsed={stats.elapsed_seconds:.2f}s"
    )


def _non_empty(value: str) -> bool | str:
    if str(value or "").strip():
        return True
    return "Please enter a value."


def _valid_date(value: str) -> bool | str:
    try:
        datetime.strptime(str(value or "").strip(), "%Y-%m-%d")
    except ValueError:
        return "Please enter a valid date in YYYY-MM-DD format."
    return True


def prompt_text(
    message: str,
    *,
    default: str = "",
    validate: Callable[[str], bool | str] | None = None,
) -> str:
    answer = questionary.text(
        message,
        default=default,
        validate=validate,
        style=QUESTIONARY_STYLE,
    ).ask()
    if answer is None:
        raise _abort()
    return str(answer).strip()


def prompt_password(message: str) -> str:
    answer = questionary.password(message, style=QUESTIONARY_STYLE).ask()
    if answer is None:
        raise _abort()
    return str(answer).strip()


def prompt_select(message: str, choices: Iterable, *, instruction: str = ""):
    answer = questionary.select(
        message,
        choices=list(choices),
        instruction=instruction,
        style=QUESTIONARY_STYLE,
    ).ask()
    if answer is None:
        raise _abort()
    return answer


def prompt_checkbox(message: str, choices: Iterable, *, minimum: int = 1) -> list[str]:
    answer = questionary.checkbox(
        message,
        choices=list(choices),
        validate=lambda items: len(items) >= minimum or f"Select at least {minimum} option(s).",
        instruction="\n- Press Space to toggle\n- Press Enter when done",
        style=QUESTIONARY_STYLE,
    ).ask()
    if answer is None:
        raise _abort()
    return list(answer)


def prompt_confirm(message: str, *, default: bool = False) -> bool:
    answer = questionary.confirm(message, default=default, style=QUESTIONARY_STYLE).ask()
    if answer is None:
        raise _abort()
    return bool(answer)


def _model_choices(provider: str, mode: str) -> list[questionary.Choice]:
    option = provider_defaults(provider)
    try:
        raw_choices = list(get_model_options(provider, mode))
    except KeyError:
        models = option.quick_models if mode == "quick" else option.deep_models
        raw_choices = [(model, model) for model in models]

    values = {value for _, value in raw_choices}
    if option.supports_custom_models and "custom" not in values:
        raw_choices.append(("Custom model ID", "custom"))
    return [questionary.Choice(title, value=value) for title, value in raw_choices]


def _select_model(provider: str, mode: str) -> str:
    option = provider_defaults(provider)
    choice = prompt_select(
        f"Select the {mode} model:",
        _model_choices(provider, mode),
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
    )
    if choice != "custom":
        return str(choice)
    return prompt_text(
        option.custom_model_placeholder or "Enter a custom model ID:",
        validate=_non_empty,
    )


def _provider_specific_settings(provider: str) -> tuple[str, str, str]:
    google_thinking_level = ""
    openai_reasoning_effort = ""
    anthropic_effort = ""

    if provider == "google":
        google_thinking_level = str(
            prompt_select(
                "Google thinking level:",
                [
                    questionary.Choice("Default", value=""),
                    questionary.Choice("Minimal", value="minimal"),
                    questionary.Choice("Low", value="low"),
                    questionary.Choice("Medium", value="medium"),
                    questionary.Choice("High", value="high"),
                ],
            )
        )
    elif provider == "openai":
        openai_reasoning_effort = str(
            prompt_select(
                "OpenAI reasoning effort:",
                [
                    questionary.Choice("Default", value=""),
                    questionary.Choice("Minimal", value="minimal"),
                    questionary.Choice("Low", value="low"),
                    questionary.Choice("Medium", value="medium"),
                    questionary.Choice("High", value="high"),
                ],
            )
        )
    elif provider == "anthropic":
        anthropic_effort = str(
            prompt_select(
                "Anthropic effort:",
                [
                    questionary.Choice("Default", value=""),
                    questionary.Choice("Low", value="low"),
                    questionary.Choice("Medium", value="medium"),
                    questionary.Choice("High", value="high"),
                ],
            )
        )

    return google_thinking_level, openai_reasoning_effort, anthropic_effort


def build_interactive_analyze_options(storage_root: str = "") -> AnalyzeOptions:
    ticker = normalize_ticker_symbol(
        prompt_text(
            "Ticker symbol or company query:",
            validate=_non_empty,
        )
    )
    analysis_date = prompt_text(
        "Analysis date (YYYY-MM-DD):",
        default=DEFAULT_ANALYSIS_DATE,
        validate=_valid_date,
    )

    providers = provider_catalog()
    provider = str(
        prompt_select(
            "LLM provider:",
            [questionary.Choice(option.label, value=option.value) for option in providers],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        )
    )
    provider_option = provider_defaults(provider)

    quick_model = _select_model(provider, "quick")
    deep_model = _select_model(provider, "deep")

    api_key = ""
    if provider_option.requires_api_key:
        api_key = prompt_password("API key (leave blank to use environment variables if configured):")

    base_url = ""
    if provider != "offline":
        base_url = prompt_text(
            "Base URL override (press Enter to keep the suggested endpoint):",
            default=provider_option.base_url,
        )

    google_thinking_level, openai_reasoning_effort, anthropic_effort = _provider_specific_settings(provider)

    analysts = prompt_checkbox(
        "Select your analyst team:",
        [
            questionary.Choice(
                ANALYST_LABELS.get(name, name.title()),
                value=name,
                checked=name in DEFAULT_CLI_ANALYSTS,
            )
            for name in DEFAULT_CLI_ANALYSTS
        ],
    )
    research_depth = int(
        prompt_select(
            "Research depth:",
            [
                questionary.Choice("1 - Quick pass", value=1),
                questionary.Choice("2 - Light debate", value=2),
                questionary.Choice("3 - Standard committee flow", value=3),
                questionary.Choice("4 - Extended debate", value=4),
                questionary.Choice("5 - Full-depth run", value=5),
            ],
        )
    )
    output_language = prompt_text("Output language:", default="English", validate=_non_empty)
    checkpoint_enabled = prompt_confirm("Enable checkpoints for this run?", default=False)
    emit_json = prompt_confirm("Print the final snapshot as JSON after completion?", default=False)

    return AnalyzeOptions(
        ticker=ticker,
        analysis_date=analysis_date,
        llm_provider=provider,
        api_key=api_key,
        quick_model=quick_model,
        deep_model=deep_model,
        output_language=output_language,
        base_url=base_url,
        google_thinking_level=google_thinking_level,
        openai_reasoning_effort=openai_reasoning_effort,
        anthropic_effort=anthropic_effort,
        analysts=analysts,
        research_depth=research_depth,
        checkpoint_enabled=checkpoint_enabled,
        storage_root=storage_root,
        emit_json=emit_json,
    )
