from __future__ import annotations

from typing import Any, Callable, Dict, List
from collections.abc import Mapping
from hashlib import sha256
import pickle
import math
from uuid import uuid4

from .results import (
    DataConfigurationError, DataMode, DataUnavailableError, InvalidSourceResponse,
    SourceAttempt, SourceMaterial, UnconfiguredSourceError, VendorResult, utc_now,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

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
from .config import get_audit, get_config
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
from .instrument_metadata import get_instrument_metadata, get_demo_instrument_metadata
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
    "get_instrument_metadata": {"sec": get_instrument_metadata, "offline": get_demo_instrument_metadata},
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
    "instrument_metadata": {"description": "Registered security type and listing flags", "tools": ["get_instrument_metadata"]},
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


def get_vendor(category: str, method: str | None = None):
    config = get_config()
    tool_vendors = config.get("tool_vendors", {})
    data_vendors = config.get("data_vendors", {})
    if not isinstance(tool_vendors, Mapping) or not isinstance(data_vendors, Mapping):
        raise DataConfigurationError("Provider configuration sections must be mappings.")
    if method and method in tool_vendors:
        return tool_vendors[method]
    if category == "symbol_resolution":
        return data_vendors.get(category, data_vendors.get("core_stock_apis", ""))
    return data_vendors.get(category, "")


def get_fallback_vendors(method: str) -> List[str]:
    """Return exactly the configured sequence, rejecting ambiguous configurations."""
    try:
        category = get_category_for_method(method)
    except ValueError:
        raise DataConfigurationError("Requested data method is not configured.") from None
    selected = get_vendor(category, method)
    if isinstance(selected, str):
        ordered = [value.strip() for value in selected.split(",")]
    elif isinstance(selected, (tuple, list)) and all(isinstance(value, str) for value in selected):
        ordered = [value.strip() for value in selected]
    else:
        raise DataConfigurationError("Provider configuration must be a provider list.")
    supported = VENDOR_METHODS.get(method, {})
    if not ordered or any(not value or value not in supported for value in ordered):
        raise DataConfigurationError("Provider configuration contains an unsupported or missing provider.")
    modes = {"demo" if vendor == "offline" else "live" for vendor in ordered}
    explicit_mode = get_config().get("data_mode")
    if len(modes) != 1 or (explicit_mode is not None and (explicit_mode not in ("live", "demo") or explicit_mode not in modes)):
        raise DataConfigurationError("Provider configuration conflicts with the requested data mode.")
    return list(dict.fromkeys(ordered))


def invoke_vendor_method(method: str, vendor: str, *args, **kwargs):
    audit = get_audit()
    if audit is not None and audit.frozen_inputs is not None:
        result = audit.frozen_inputs.read(method, *args, **kwargs)
        if not result.available or result.provider != vendor:
            raise DataUnavailableError(result)
        return result.value
    if method not in VENDOR_METHODS or vendor not in VENDOR_METHODS[method]:
        raise DataConfigurationError("Requested provider does not support this method.")
    if vendor not in get_fallback_vendors(method):
        raise DataConfigurationError("Requested provider is not explicitly configured for this request.")
    audit = get_audit()
    if audit is not None:
        with audit.lock:
            result = _fetch_from_vendors(method, args, kwargs, False, audit, selected_vendors=[vendor])
    else:
        result = _fetch_from_vendors(method, args, kwargs, False, None, selected_vendors=[vendor])
    if not result.available:
        raise DataUnavailableError(result)
    return result.value


def _response_status(value: Any) -> str:
    if value is None or value is False:
        return "empty"
    if isinstance(value, (str, list, tuple, dict, set)) and not value:
        return "empty"
    if isinstance(value, float) and not math.isfinite(value):
        return "invalid_response"
    if isinstance(value, dict) and any(key in value for key in ("Error Message", "Information", "Note", "error")):
        return "invalid_response"
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return "empty"
        if (text.startswith(("error", "no ", "failed", "unable", "insufficient"))
                or "could not be retrieved" in text or "is not available" in text
                or "api key is not configured" in text or "api rate limit" in text):
            return "invalid_response"
    return "success"


def _failure_details(exc: Exception) -> tuple[str, str, str]:
    # Exception text may contain credential-bearing URLs. Use it only to classify;
    # persist a fixed message and code, never the text or traceback.
    if isinstance(exc, DataConfigurationError):
        return "unconfigured", "configuration_error", "Provider configuration is invalid for this request."
    if isinstance(exc, UnconfiguredSourceError):
        return "unconfigured", "provider_unconfigured", "The provider client or credential is not configured."
    if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return "timeout", "provider_timeout", "The provider request timed out."
    if isinstance(exc, AlphaVantageRateLimitError) or getattr(exc, "code", None) == 429:
        return "rate_limited", "provider_rate_limited", "The provider request was rate limited."
    if isinstance(exc, InvalidSourceResponse):
        return "invalid_response", "invalid_response", "The provider response contained no valid source data."
    message = str(exc).lower()
    if "api key" in message and ("not configured" in message or "missing" in message):
        return "unconfigured", "provider_unconfigured", "The provider credential is not configured."
    return "error", "provider_error", "The provider request failed."


def _cache_key(method: str, vendors: list[str], args: tuple, kwargs: dict, aggregate: bool):
    try:
        # Hash raw arguments, not redacted material: different secret arguments
        # must never collide. No argument contents are stored in the audit key.
        return sha256(pickle.dumps((method, vendors, args, sorted(kwargs.items()), aggregate))).hexdigest()
    except (TypeError, ValueError, pickle.PicklingError):
        return None


def fetch_from_vendors(method: str, *args, aggregate: bool = False, **kwargs) -> VendorResult:
    """Fetch from explicitly configured providers with per-attempt provenance."""
    audit = get_audit()
    if audit is not None and audit.frozen_inputs is not None:
        return audit.frozen_inputs.read(method, *args, aggregate=aggregate, **kwargs)
    if audit is not None:
        # A copied thread context shares this collector. Serializing cache access
        # also prevents duplicate requests when tools race with the same args.
        with audit.lock:
            return _fetch_from_vendors(method, args, kwargs, aggregate, audit)
    return _fetch_from_vendors(method, args, kwargs, aggregate, None)


def _fetch_from_vendors(method, args, kwargs, aggregate, audit, *, selected_vendors=None) -> VendorResult:
    attempts = []
    materials = []
    try:
        vendors = get_fallback_vendors(method)
        if selected_vendors is not None:
            if any(provider not in vendors for provider in selected_vendors):
                raise DataConfigurationError("Requested provider is not explicitly configured for this request.")
            vendors = selected_vendors
    except DataConfigurationError as exc:
        started = utc_now()
        status, code, message = _failure_details(exc)
        attempt = SourceAttempt(attempt_id=str(uuid4()), run_id=audit.run_id if audit else None,
                                method=method, provider="configuration", data_mode=DataMode.UNKNOWN,
                                status=status, started_at=started, finished_at=utc_now(),
                                error_code=code, message=message)
        if audit:
            audit.attempts.append(attempt)
        return VendorResult(status=status, attempts=[attempt])
    key = _cache_key(method, vendors, args, kwargs, aggregate)
    if audit and key is not None and key in audit.cache:
        return audit.cache[key]
    mode = DataMode.DEMO if vendors[0] == "offline" else DataMode.LIVE
    collected = []
    successful_provider = None
    value = None
    for provider in vendors:
        started = utc_now()
        attempt_id = str(uuid4())
        previous_capture = audit.capture_context if audit else None
        if audit:
            audit.capture_context = (method, provider, attempt_id)
        try:
            # The sequence has been validated before any adapter is called.
            response = VENDOR_METHODS[method][provider](*args, **kwargs)
            status = _response_status(response)
            code = None if status == "success" else status
            message = None if status == "success" else "The provider returned no usable source data."
        except Exception as exc:
            status, code, message = _failure_details(exc)
            response = None
        finally:
            if audit:
                audit.capture_context = previous_capture
        finished = utc_now()
        count = len(response) if status == "success" and isinstance(response, (list, tuple, dict, set)) else (1 if status == "success" else None)
        attempt = SourceAttempt(attempt_id=attempt_id, run_id=audit.run_id if audit else None,
                                method=method, provider=provider, data_mode=mode, status=status,
                                started_at=started, finished_at=finished, error_code=code, message=message, item_count=count)
        attempts.append(attempt)
        if status == "success":
            material = SourceMaterial(method=method, provider=provider, data_mode=mode,
                                      retrieved_at=finished, content=response, attempt_id=attempt_id)
            materials.append(material)
            successful_provider = successful_provider or provider
            if aggregate:
                collected.extend(response if isinstance(response, list) else [response])
            else:
                value = response
                break
    result = VendorResult(value=collected if aggregate and materials else value,
                          provider=successful_provider, data_mode=mode,
                          status="success" if materials else attempts[-1].status,
                          attempts=attempts, materials=materials)
    if audit:
        audit.attempts.extend(attempts)
        audit.materials.extend(materials)
        if result.available and key is not None and (not aggregate or all(item.status == "success" for item in attempts)):
            audit.cache[key] = result
    return result


def collect_from_vendors(method: str, *args, **kwargs) -> list[Any]:
    result = fetch_from_vendors(method, *args, aggregate=True, **kwargs)
    if not result.available:
        raise DataUnavailableError(result)
    return result.value


def route_to_vendor(method: str, *args, **kwargs):
    result = fetch_from_vendors(method, *args, **kwargs)
    if not result.available:
        raise DataUnavailableError(result)
    return result.value
