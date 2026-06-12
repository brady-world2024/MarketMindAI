from __future__ import annotations

from ..symbols import SymbolCandidate
from .alpha_vantage_common import _make_api_request
from .alpha_vantage_fundamentals import get_fundamentals
from .alpha_vantage_stock import get_price_history


def search_symbols(query: str, limit: int = 8) -> list[SymbolCandidate]:
    payload = _make_api_request("SYMBOL_SEARCH", {"keywords": query})
    candidates = []
    for item in payload.get("bestMatches", [])[:limit]:
        symbol = str(item.get("1. symbol", "")).strip()
        name = str(item.get("2. name", "")).strip()
        if not symbol or not name:
            continue
        candidates.append(
            SymbolCandidate(
                symbol=symbol,
                name=name,
                exchange=str(item.get("4. region", "")).strip(),
                region=str(item.get("4. region", "")).strip(),
                currency=str(item.get("8. currency", "")).strip(),
                instrument_type=str(item.get("3. type", "")).strip(),
                provider="alpha-vantage",
                match_score=float(item.get("9. matchScore", 0.0) or 0.0),
            )
        )
    return candidates


def validate_price_data(symbol: str, analysis_date: str) -> bool:
    try:
        return len(get_price_history(symbol, analysis_date, 90)) >= 20
    except Exception:
        return False


def validate_fundamental_data(symbol: str, analysis_date: str) -> bool:
    try:
        return bool(get_fundamentals(symbol).company_name)
    except Exception:
        return False
