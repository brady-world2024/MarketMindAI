from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ...symbols import SymbolResolution


@dataclass
class PriceBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class IndicatorSet:
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None
    volatility_20: Optional[float] = None
    momentum_20_pct: Optional[float] = None


@dataclass
class MarketSnapshot:
    latest_close: float
    latest_volume: int
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    indicators: IndicatorSet
    bars: List[PriceBar] = field(default_factory=list)


@dataclass
class NewsItem:
    title: str
    source: str
    published_at: str
    url: str = ""
    summary: str = ""
    sentiment_score: float = 0.0


@dataclass
class FundamentalSnapshot:
    company_name: str
    sector: str = ""
    industry: str = ""
    description: str = ""
    market_cap: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    free_cashflow: Optional[float] = None


@dataclass
class MemoryEntry:
    symbol: str
    analysis_date: str
    action: str
    confidence: float
    thesis: str
    outcome: str = ""


@dataclass
class ResearchBundle:
    resolution: SymbolResolution
    market: MarketSnapshot
    fundamentals: FundamentalSnapshot
    news: List[NewsItem]
    memory: List[MemoryEntry]
    sentiment_score: float
    data_source: str
