from __future__ import annotations

"""Reference-style aggregate exports for Alpha Vantage dataflows."""

from .alpha_vantage_fundamentals import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from .alpha_vantage_indicator import get_indicators
from .alpha_vantage_news import (
    get_global_news,
    get_global_news_documents,
    get_insider_transactions,
    get_news,
    get_news_documents,
)
from .alpha_vantage_stock import get_price_history
from .alpha_vantage_symbol import search_symbols, validate_fundamental_data, validate_price_data


def get_stock(symbol: str, analysis_date: str, lookback_days: int = 180):
    return get_price_history(symbol, analysis_date, lookback_days=lookback_days)


def get_indicator(symbol: str, analysis_date: str, indicators: list[str] | None = None):
    return get_indicators(symbol, analysis_date, indicators=indicators)


__all__ = [
    "get_stock",
    "get_indicator",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_global_news",
    "get_insider_transactions",
    "get_news_documents",
    "get_global_news_documents",
    "search_symbols",
    "validate_price_data",
    "validate_fundamental_data",
]
