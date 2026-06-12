from __future__ import annotations

from .alpha_vantage_stock import get_price_history
from .stockstats_utils import render_indicator_report


def get_indicators(symbol: str, analysis_date: str, indicators: list[str] | None = None) -> str:
    bars = get_price_history(symbol, analysis_date, lookback_days=260)
    return render_indicator_report(bars, indicators)
