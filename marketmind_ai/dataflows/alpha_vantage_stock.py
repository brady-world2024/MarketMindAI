from __future__ import annotations

from datetime import datetime

from ..agents.utils.research_types import PriceBar
from .alpha_vantage_common import _make_api_request


def get_price_history(symbol: str, analysis_date: str, lookback_days: int = 180) -> list[PriceBar]:
    payload = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", {"symbol": symbol, "outputsize": "full"})
    series = payload.get("Time Series (Daily)", {})
    end_date = datetime.strptime(analysis_date, "%Y-%m-%d").date()
    bars = []
    for day_text, row in series.items():
        day = datetime.strptime(day_text, "%Y-%m-%d").date()
        if day > end_date:
            continue
        bars.append(
            PriceBar(
                date=day.isoformat(),
                open=round(float(row.get("1. open", 0.0)), 2),
                high=round(float(row.get("2. high", 0.0)), 2),
                low=round(float(row.get("3. low", 0.0)), 2),
                close=round(float(row.get("4. close", 0.0)), 2),
                volume=int(float(row.get("6. volume", 0.0))),
            )
        )
    bars.sort(key=lambda item: item.date)
    return bars[-lookback_days:]
