from __future__ import annotations

from typing import Any, Callable, Dict, List

from .alpha_vantage_fundamentals import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_income_statement as get_alpha_vantage_income_statement,
)
from .alpha_vantage_indicator import get_indicators as get_alpha_vantage_indicators
from .alpha_vantage_news import (
    get_global_news as get_alpha_vantage_global_news,
    get_global_news_documents as get_alpha_vantage_global_news_documents,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_news_documents as get_alpha_vantage_news_documents,
)
from .alpha_vantage_stock import get_price_history as get_alpha_vantage_price_history
from .alpha_vantage_symbol import (
    search_symbols as search_symbols_alpha_vantage,
    validate_fundamental_data as validate_fundamental_data_alpha_vantage,
    validate_price_data as validate_price_data_alpha_vantage,
)
from .alpha_vantage_transcripts import get_fundamental_documents as get_alpha_vantage_fundamental_documents
from .config import get_config
from .offline import (
    get_balance_sheet as get_offline_balance_sheet,
    get_cashflow as get_offline_cashflow,
    get_fundamental_documents as get_offline_fundamental_documents,
    get_fundamentals as get_offline_fundamentals,
    get_global_news as get_offline_global_news,
    get_income_statement as get_offline_income_statement,
    get_indicators as get_offline_indicators,
    get_insider_transactions as get_offline_insider_transactions,
    get_news as get_offline_news,
    get_price_history as get_offline_price_history,
    search_symbols as search_symbols_offline,
    validate_fundamental_data as validate_fundamental_data_offline,
    validate_price_data as validate_price_data_offline,
)
from .sec_filings import get_fundamental_documents as get_sec_fundamental_documents
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_fundamentals as get_yfinance_fundamentals,
    get_income_statement as get_yfinance_income_statement,
    get_indicators as get_yfinance_indicators,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_price_history as get_yfinance_price_history,
    search_symbols as search_symbols_yfinance,
    validate_fundamental_data as validate_fundamental_data_yfinance,
    validate_price_data as validate_price_data_yfinance,
)
from .yfinance_news import (
    get_global_news_documents_yfinance,
    get_global_news_yfinance,
    get_news_documents_yfinance,
    get_news_yfinance,
)


def _offline_news_documents(ticker: str, start_date: str, end_date: str) -> list[dict]:
    return [
        {
            "title": item.title,
            "summary": item.summary,
            "source": item.source,
            "link": item.url,
            "published_at": item.published_at,
            "provider": "offline-fixtures",
            "scope": "company",
            "sentiment_label": "",
            "sentiment_score": item.sentiment_score,
        }
        for item in get_offline_news(ticker, end_date, 8)
    ]


def _offline_global_news_documents(curr_date: str, look_back_days: int = 7, limit: int = 25) -> list[dict]:
    return [
        {
            "title": item.title,
            "summary": item.summary,
            "source": item.source,
            "link": item.url,
            "published_at": item.published_at,
            "provider": "offline-fixtures",
            "scope": "macro",
            "sentiment_label": "",
            "sentiment_score": item.sentiment_score,
        }
        for item in get_offline_global_news(curr_date, "macro", min(limit, 8))
    ]


VENDOR_METHODS: Dict[str, Dict[str, Callable[..., Any]]] = {
    "search_symbols": {
        "offline": search_symbols_offline,
        "yfinance": search_symbols_yfinance,
        "alpha_vantage": search_symbols_alpha_vantage,
    },
    "validate_price_data": {
        "offline": validate_price_data_offline,
        "yfinance": validate_price_data_yfinance,
        "alpha_vantage": validate_price_data_alpha_vantage,
    },
    "validate_fundamental_data": {
        "offline": validate_fundamental_data_offline,
        "yfinance": validate_fundamental_data_yfinance,
        "alpha_vantage": validate_fundamental_data_alpha_vantage,
    },
    "get_price_history": {
        "offline": get_offline_price_history,
        "yfinance": get_yfinance_price_history,
        "alpha_vantage": get_alpha_vantage_price_history,
    },
    "get_indicators": {
        "offline": get_offline_indicators,
        "yfinance": get_yfinance_indicators,
        "alpha_vantage": get_alpha_vantage_indicators,
    },
    "get_fundamentals": {
        "offline": get_offline_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
    },
    "get_balance_sheet": {
        "offline": get_offline_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
    },
    "get_cashflow": {
        "offline": get_offline_cashflow,
        "yfinance": get_yfinance_cashflow,
        "alpha_vantage": get_alpha_vantage_cashflow,
    },
    "get_income_statement": {
        "offline": get_offline_income_statement,
        "yfinance": get_yfinance_income_statement,
        "alpha_vantage": get_alpha_vantage_income_statement,
    },
    "get_fundamental_documents": {
        "offline": get_offline_fundamental_documents,
        "sec": get_sec_fundamental_documents,
        "alpha_vantage": get_alpha_vantage_fundamental_documents,
    },
    "get_news": {
        "offline": get_offline_news,
        "yfinance": get_news_yfinance,
        "alpha_vantage": get_alpha_vantage_news,
    },
    "get_global_news": {
        "offline": get_offline_global_news,
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "offline": get_offline_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "alpha_vantage": get_alpha_vantage_insider_transactions,
    },
    "get_news_documents": {
        "offline": _offline_news_documents,
        "alpha_vantage": get_alpha_vantage_news_documents,
        "yfinance": get_news_documents_yfinance,
    },
    "get_global_news_documents": {
        "offline": _offline_global_news_documents,
        "alpha_vantage": get_alpha_vantage_global_news_documents,
        "yfinance": get_global_news_documents_yfinance,
    },
}


TOOLS_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": ["get_price_history"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"],
    },
    "fundamental_document_data": {
        "description": "Fundamental long-form documents such as filings and earnings transcripts",
        "tools": ["get_fundamental_documents"],
    },
    "news_data": {
        "description": "News and insider data",
        "tools": ["get_news", "get_global_news", "get_insider_transactions"],
    },
    "news_document_data": {
        "description": "Structured news events for timeline retrieval and RAG",
        "tools": ["get_news_documents", "get_global_news_documents"],
    },
    "symbol_resolution": {
        "description": "Ticker lookup and validation",
        "tools": ["search_symbols", "validate_price_data", "validate_fundamental_data"],
    },
}


def get_category_for_method(method: str) -> str:
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str | None = None) -> str:
    config = get_config()
    if method:
        override = config.get("tool_vendors", {}).get(method)
        if override:
            return str(override)
    if category == "symbol_resolution":
        return str(
            config.get("data_vendors", {}).get(
                category,
                config.get("data_vendors", {}).get("core_stock_apis", "yfinance"),
            )
        )
    return str(config.get("data_vendors", {}).get(category, ""))


def get_fallback_vendors(method: str) -> List[str]:
    category = get_category_for_method(method)
    ordered = [value.strip() for value in get_vendor(category, method).split(",") if value.strip()]
    supported = set(VENDOR_METHODS.get(method, {}))
    vendors: List[str] = []
    for vendor in ordered:
        if vendor in supported and vendor not in vendors:
            vendors.append(vendor)
    for vendor in VENDOR_METHODS.get(method, {}):
        if vendor not in vendors:
            vendors.append(vendor)
    return vendors


def invoke_vendor_method(method: str, vendor: str, *args, **kwargs):
    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")
    if vendor not in VENDOR_METHODS[method]:
        raise ValueError(f"Vendor '{vendor}' not supported for method '{method}'")
    return VENDOR_METHODS[method][vendor](*args, **kwargs)


def collect_from_vendors(method: str, *args, **kwargs) -> list[Any]:
    results: list[Any] = []
    for vendor in get_fallback_vendors(method):
        try:
            result = invoke_vendor_method(method, vendor, *args, **kwargs)
        except Exception:
            continue
        if result is None:
            continue
        if isinstance(result, list):
            results.extend(result)
        else:
            results.append(result)
    return results


def route_to_vendor(method: str, *args, **kwargs):
    for vendor in get_fallback_vendors(method):
        try:
            return invoke_vendor_method(method, vendor, *args, **kwargs)
        except Exception:
            continue
    raise RuntimeError(f"No available vendor for '{method}'")
