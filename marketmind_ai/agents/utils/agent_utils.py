from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import TYPE_CHECKING, Dict, List, Optional

from langchain_core.messages import HumanMessage, RemoveMessage

from ...dataflows.interface import get_vendor, route_to_vendor
from ...symbols import SymbolResolution, ValidationFlags
from .core_stock_tools import build_core_stock_tools
from .fundamental_data_tools import build_fundamental_data_tools
from .news_data_tools import build_news_data_tools
from .research_types import IndicatorSet, MarketSnapshot, ResearchBundle
from .technical_indicators_tools import build_technical_indicator_tools

if TYPE_CHECKING:
    from ...graph.storage import DecisionJournal


def build_instrument_context(ticker: str) -> str:
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


def get_language_instruction(language: str = "English") -> str:
    cleaned = str(language or "").strip()
    if not cleaned or cleaned.lower() == "english":
        return ""
    return f" Write your entire response in {cleaned}."


def create_msg_delete():
    def delete_messages(state):
        removals = [RemoveMessage(id=message.id) for message in state["messages"]]
        return {"messages": removals + [HumanMessage(content="Continue")]}

    return delete_messages


def _average(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value * alpha) + (current * (1 - alpha))
    return current


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
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


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
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


def _volatility(values: List[float], period: int = 20) -> Optional[float]:
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


def _change_pct(closes: List[float], days: int) -> float:
    if len(closes) <= days or closes[-days - 1] == 0:
        return 0.0
    return round(((closes[-1] - closes[-days - 1]) / closes[-days - 1]) * 100, 2)


def compute_market_snapshot(bars) -> MarketSnapshot:
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    indicators = IndicatorSet(
        sma_20=_sma(closes, 20),
        sma_50=_sma(closes, 50),
        ema_12=_ema(closes, 12),
        ema_26=_ema(closes, 26),
        rsi_14=_rsi(closes, 14),
        atr_14=_atr(highs, lows, closes, 14),
        volatility_20=_volatility(closes, 20),
        momentum_20_pct=((closes[-1] - closes[-21]) / closes[-21]) if len(closes) > 21 and closes[-21] else None,
    )
    return MarketSnapshot(
        latest_close=closes[-1],
        latest_volume=bars[-1].volume,
        change_1d_pct=_change_pct(closes, 1),
        change_5d_pct=_change_pct(closes, 5),
        change_20d_pct=_change_pct(closes, 20),
        indicators=indicators,
        bars=bars,
    )


def sentiment_from_headlines(items) -> float:
    if not items:
        return 0.0
    score = 0.0
    for item in items:
        if item.sentiment_score:
            score += item.sentiment_score
            continue
        tokens = {token.strip(".,:;!?").lower() for token in item.title.split()}
        positive = {"growth", "record", "strong", "beat", "backlog", "demand", "resilient", "approved", "surge"}
        negative = {"miss", "cut", "pressure", "probe", "slowdown", "lawsuit", "risk", "delay", "weak"}
        score += 0.22 * len(tokens & positive)
        score -= 0.22 * len(tokens & negative)
    return round(max(-1.0, min(1.0, score / len(items))), 2)


def score_bundle(bundle: ResearchBundle) -> Dict[str, float]:
    market = 0.0
    indicators = bundle.market.indicators
    if indicators.sma_20 and indicators.sma_50:
        if bundle.market.latest_close > indicators.sma_20 > indicators.sma_50:
            market += 22
        elif bundle.market.latest_close < indicators.sma_20 < indicators.sma_50:
            market -= 22
    market += bundle.market.change_20d_pct * 0.55
    market += bundle.market.change_5d_pct * 0.25
    if indicators.rsi_14 is not None:
        if indicators.rsi_14 > 72:
            market -= 8
        elif indicators.rsi_14 < 28:
            market += 6
    if indicators.volatility_20 and indicators.volatility_20 > 0.04:
        market -= 7

    fundamentals = 0.0
    f = bundle.fundamentals
    if (f.revenue_growth or 0.0) > 0.12:
        fundamentals += 16
    elif (f.revenue_growth or 0.0) < 0:
        fundamentals -= 10
    if (f.operating_margin or 0.0) > 0.18:
        fundamentals += 10
    elif (f.operating_margin or 0.0) < 0.08:
        fundamentals -= 6
    if (f.debt_to_equity or 0.0) < 0.8:
        fundamentals += 8
    elif (f.debt_to_equity or 0.0) > 1.8:
        fundamentals -= 10
    if (f.trailing_pe or 0.0) > 45:
        fundamentals -= 7
    elif 0 < (f.trailing_pe or 0.0) < 20:
        fundamentals += 4

    return {
        "market": round(market, 2),
        "sentiment": round(bundle.sentiment_score * 32.0, 2),
        "news": round(sum(item.sentiment_score for item in bundle.news[:5]) * 9.0, 2),
        "fundamentals": round(fundamentals, 2),
    }


@dataclass
class AnalysisContext:
    journal: DecisionJournal
    analysis_date: str
    bundle_cache: Dict[str, ResearchBundle] = field(default_factory=dict)

    def load_bundle(self, symbol: str, resolution: Optional[dict] = None) -> ResearchBundle:
        upper = symbol.upper()
        if upper in self.bundle_cache:
            return self.bundle_cache[upper]
        bars = route_to_vendor("get_price_history", upper, self.analysis_date, 180)
        market = compute_market_snapshot(bars)
        fundamentals = route_to_vendor("get_fundamentals", upper)
        news = route_to_vendor("get_news", upper, self.analysis_date, 8)
        sentiment = sentiment_from_headlines(news)
        memory = self.journal.recall(upper, 5)
        resolution_payload = resolution or {
            "resolved_symbol": upper,
            "company_name": fundamentals.company_name,
            "exchange": "",
            "region": "",
            "currency": "",
        }
        bundle = ResearchBundle(
            resolution=SymbolResolution(
                status="RESOLVED",
                original_input=upper,
                normalized_query=upper,
                resolved_symbol=upper,
                company_name=resolution_payload.get("company_name") or fundamentals.company_name,
                exchange=resolution_payload.get("exchange", ""),
                region=resolution_payload.get("region", ""),
                currency=resolution_payload.get("currency", ""),
                reason="Runtime bundle loaded.",
                validation=ValidationFlags(price_data=True, fundamental_data=True),
            ),
            market=market,
            fundamentals=fundamentals,
            news=news,
            memory=memory,
            sentiment_score=sentiment,
            data_source=get_vendor("core_stock_apis").split(",")[0].strip() or "unknown",
        )
        self.bundle_cache[upper] = bundle
        return bundle


def build_toolsets(context: AnalysisContext):
    return {
        "market": build_core_stock_tools(context) + build_technical_indicator_tools(context),
        "sentiment": build_news_data_tools(context, roles=("sentiment",)),
        "news": build_news_data_tools(context, roles=("news",)),
        "fundamentals": build_fundamental_data_tools(context),
    }
