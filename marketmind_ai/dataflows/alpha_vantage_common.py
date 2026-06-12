from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime


class AlphaVantageRateLimitError(RuntimeError):
    """Raised when Alpha Vantage rate limits or plan gates a request."""


def get_api_key() -> str:
    """Retrieve the Alpha Vantage API key using reference-compatible env names."""
    api_key = (
        os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
        or os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("Alpha Vantage API key is not configured")
    return api_key


def format_datetime_for_api(date_input) -> str:
    """Convert dates to the YYYYMMDDTHHMM shape required by Alpha Vantage."""
    if isinstance(date_input, datetime):
        return date_input.strftime("%Y%m%dT%H%M")
    if isinstance(date_input, str):
        value = date_input.strip()
        if len(value) == 13 and "T" in value:
            return value
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y%m%dT%H%M")
            except ValueError:
                continue
    raise ValueError(f"Unsupported Alpha Vantage datetime input: {date_input!r}")


def _coerce_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _make_api_request(function: str, params: dict[str, str]) -> dict:
    api_key = get_api_key()
    query = {"function": function, "apikey": api_key, **params}
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MarketMindAIRebuild/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    payload = json.loads(body)
    _raise_for_alpha_vantage_errors(payload)
    return payload


def _raise_for_alpha_vantage_errors(payload: dict) -> None:
    message = ""
    if isinstance(payload, dict):
        message = str(
            payload.get("Information")
            or payload.get("Note")
            or payload.get("Error Message")
            or ""
        )
    if not message:
        return
    lowered = message.lower()
    if "rate limit" in lowered or "call frequency" in lowered or "premium" in lowered:
        raise AlphaVantageRateLimitError(message)
    raise RuntimeError(message)


def _gross_margin_from_overview(payload: dict):
    direct = _coerce_float(payload.get("GrossMarginTTM"))
    if direct is not None:
        return direct
    gross_profit = _coerce_float(payload.get("GrossProfitTTM"))
    revenue = _coerce_float(payload.get("RevenueTTM"))
    if gross_profit is not None and revenue not in (None, 0):
        return gross_profit / revenue
    return None
