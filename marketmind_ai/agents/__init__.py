"""Lazy factory exports for MarketMind AI roles."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "create_aggressive_debator": "marketmind_ai.agents.risk.aggressive",
    "create_bear_researcher": "marketmind_ai.agents.researchers.bear",
    "create_bull_researcher": "marketmind_ai.agents.researchers.bull",
    "create_conservative_debator": "marketmind_ai.agents.risk.conservative",
    "create_fundamentals_analyst": "marketmind_ai.agents.analysts.fundamentals",
    "create_market_analyst": "marketmind_ai.agents.analysts.market",
    "create_neutral_debator": "marketmind_ai.agents.risk.neutral",
    "create_news_analyst": "marketmind_ai.agents.analysts.news",
    "create_portfolio_manager": "marketmind_ai.agents.managers.portfolio_manager",
    "create_research_manager": "marketmind_ai.agents.managers.research_manager",
    "create_sentiment_analyst": "marketmind_ai.agents.analysts.sentiment",
    "create_trader": "marketmind_ai.agents.trader.trader",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
