from __future__ import annotations

from math import sqrt
from typing import Iterable, Sequence

import pandas as pd
from stockstats import wrap

from ..agents.utils.research_types import PriceBar


_STOCKSTATS_INDICATORS = {
    "close_50_sma": "close_50_sma",
    "close_200_sma": "close_200_sma",
    "close_10_ema": "close_10_ema",
    "macd": "macd",
    "macds": "macds",
    "macdh": "macdh",
    "rsi": "rsi_14",
    "boll": "boll",
    "boll_ub": "boll_ub",
    "boll_lb": "boll_lb",
    "atr": "atr_14",
}


def _average(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value * alpha) + (current * (1 - alpha))
    return current


def _ema_series(values: Sequence[float], period: int) -> list[float | None]:
    series: list[float | None] = [None] * len(values)
    if len(values) < period:
        return series
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    series[period - 1] = current
    for index in range(period, len(values)):
        current = (values[index] * alpha) + (current * (1 - alpha))
        series[index] = current
    return series


def _rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for prev, current in zip(values[:-1], values[1:]):
        delta = current - prev
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = _average(gains[:period])
    avg_loss = _average(losses[:period])
    if avg_gain is None or avg_loss is None:
        return None
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    ranges = []
    for index in range(1, len(closes)):
        true_range = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        ranges.append(true_range)
    if len(ranges) < period:
        return None
    current = sum(ranges[:period]) / period
    for value in ranges[period:]:
        current = ((current * (period - 1)) + value) / period
    return current


def _vwma(closes: Sequence[float], volumes: Sequence[int], period: int = 20) -> float | None:
    if len(closes) < period or len(volumes) < period:
        return None
    close_slice = closes[-period:]
    volume_slice = volumes[-period:]
    denominator = sum(volume_slice)
    if denominator == 0:
        return None
    return sum(close * volume for close, volume in zip(close_slice, volume_slice)) / denominator


def _volatility(values: Sequence[float], period: int = 20) -> float | None:
    if len(values) <= period:
        return None
    closes = values[-period:]
    returns = []
    for prev, current in zip(closes[:-1], closes[1:]):
        if prev == 0:
            continue
        returns.append((current - prev) / prev)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return sqrt(variance)


def _stddev(values: Sequence[float], period: int = 20) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    return sqrt(variance)


def _macd_components(closes: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    ema_12_series = _ema_series(closes, 12)
    ema_26_series = _ema_series(closes, 26)
    macd_series = [
        (fast - slow) if fast is not None and slow is not None else None
        for fast, slow in zip(ema_12_series, ema_26_series)
    ]
    macd_values = [value for value in macd_series if value is not None]
    macd_value = macd_values[-1] if macd_values else None
    signal_value = _ema(macd_values, 9) if len(macd_values) >= 9 else None
    histogram = None
    if macd_value is not None and signal_value is not None:
        histogram = macd_value - signal_value
    return macd_value, signal_value, histogram


def bars_to_dataframe(bars: Iterable[PriceBar]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
    )
    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    numeric_columns = ["open", "high", "low", "close", "volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame[numeric_columns] = frame[numeric_columns].ffill().bfill()
    return frame.reset_index(drop=True)


def _stockstats_value(frame: pd.DataFrame, indicator: str):
    column = _STOCKSTATS_INDICATORS.get(indicator)
    if not column or frame.empty:
        return None
    try:
        stock_frame = wrap(frame.copy())
        stock_frame[column]
        value = stock_frame.iloc[-1].get(column)
    except Exception:
        return None
    if pd.isna(value):
        return None
    return float(value)


def _manual_indicator_mapping(bar_list: list[PriceBar]) -> dict[str, float | None]:
    closes = [bar.close for bar in bar_list]
    highs = [bar.high for bar in bar_list]
    lows = [bar.low for bar in bar_list]
    volumes = [bar.volume for bar in bar_list]
    sma_20 = _sma(closes, 20)
    boll_std = _stddev(closes, 20)
    macd, signal, histogram = _macd_components(closes)
    return {
        "close_50_sma": _sma(closes, 50),
        "close_200_sma": _sma(closes, 200),
        "close_10_ema": _ema(closes, 10),
        "macd": macd,
        "macds": signal,
        "macdh": histogram,
        "rsi": _rsi(closes, 14),
        "boll": sma_20,
        "boll_ub": (sma_20 + (2 * boll_std)) if sma_20 is not None and boll_std is not None else None,
        "boll_lb": (sma_20 - (2 * boll_std)) if sma_20 is not None and boll_std is not None else None,
        "atr": _atr(highs, lows, closes, 14),
        "vwma": _vwma(closes, volumes, 20),
        "volatility_20": _volatility(closes, 20),
    }


def render_indicator_report(bars: Iterable[PriceBar], indicators: list[str] | None = None) -> str:
    bar_list = list(bars)
    manual = _manual_indicator_mapping(bar_list)
    frame = bars_to_dataframe(bar_list)
    requested = indicators or list(manual.keys())
    rendered = []
    for name in requested:
        value = _stockstats_value(frame, name)
        if value is None:
            value = manual.get(name)
        rendered.append(f"{name}: {value}")
    return "\n".join(rendered)
