from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional import failure path
    yf = None

from ..agents.utils.research_types import FundamentalSnapshot, PriceBar
from ..symbols import SymbolCandidate
from .stockstats_utils import render_indicator_report
from .results import InvalidSourceResponse, UnconfiguredSourceError, finite_number, valid_fiscal_period
from .source_capture import capture_source_response


def _http_json(url: str, timeout: int = 15) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MarketMindAIRebuild/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    capture_source_response(url, body, 'application/json')
    return json.loads(body)


def _coerce_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("raw")
        if raw is not None:
            return float(raw)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def search_symbols(query: str, limit: int = 8) -> list[SymbolCandidate]:
    encoded = urllib.parse.quote(query)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount={limit}&newsCount=0"
    payload = _http_json(url)
    candidates: list[SymbolCandidate] = []
    for item in payload.get("quotes", []):
        symbol = str(item.get("symbol", "")).strip()
        name = str(item.get("shortname") or item.get("longname") or "").strip()
        if not symbol or not name:
            continue
        candidates.append(
            SymbolCandidate(
                symbol=symbol,
                name=name,
                exchange=str(item.get("exchange", "")).strip(),
                region=str(item.get("exchangeDisp") or item.get("region", "")).strip(),
                currency=str(item.get("currency", "")).strip(),
                instrument_type=str(item.get("quoteType", "")).strip(),
                provider="yahoo-finance",
                match_score=float(item.get("score", 0.0) or 0.0),
            )
        )
    return candidates[:limit]


def _price_retrieval_now():
    return datetime.now(timezone.utc)


def get_price_history(symbol: str, analysis_date: str, lookback_days: int = 180) -> list[PriceBar]:
    from .price_units import restore_cutoff_units
    from .research_cutoff import resolve_research_cutoff
    now = _price_retrieval_now()
    cutoff = resolve_research_cutoff(analysis_date, now=now)
    market_zone = ZoneInfo('America/New_York')
    end_date = datetime.strptime(cutoff.effective_session_date, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=lookback_days * 2)
    def query(start, end):
        params = urllib.parse.urlencode({
            "period1": int(datetime.combine(start, datetime.min.time(), market_zone).timestamp()),
            "period2": int(datetime.combine(end, datetime.min.time(), market_zone).timestamp()),
            "interval": "1d", "events": "splits"})
        return _http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{params}")
    historical = query(start_date, end_date + timedelta(days=1))
    verification = query(end_date, now.astimezone(market_zone).date() + timedelta(days=1))
    bars = restore_cutoff_units(historical, verification, symbol, analysis_date, now)
    return type(bars)(bars[-lookback_days:], bars.price_basis)


def get_fundamentals(symbol: str) -> FundamentalSnapshot:
    if yf is not None:
        try:
            ticker = yf.Ticker(symbol.upper())
            info = getattr(ticker, "info", {}) or {}
            if info:
                return FundamentalSnapshot(
                    company_name=str(info.get("longName") or info.get("shortName") or symbol),
                    sector=str(info.get("sector") or ""),
                    industry=str(info.get("industry") or ""),
                    description=str(info.get("longBusinessSummary") or ""),
                    market_cap=_coerce_float(info.get("marketCap")),
                    trailing_pe=_coerce_float(info.get("trailingPE")),
                    forward_pe=_coerce_float(info.get("forwardPE")),
                    price_to_book=_coerce_float(info.get("priceToBook")),
                    revenue_growth=_coerce_float(info.get("revenueGrowth")),
                    gross_margin=_coerce_float(info.get("grossMargins")),
                    operating_margin=_coerce_float(info.get("operatingMargins")),
                    debt_to_equity=_coerce_float(info.get("debtToEquity")),
                    current_ratio=_coerce_float(info.get("currentRatio")),
                    free_cashflow=_coerce_float(info.get("freeCashflow")),
                )
        except Exception:
            pass

    modules = ",".join(
        [
            "price",
            "summaryDetail",
            "financialData",
            "defaultKeyStatistics",
            "assetProfile",
        ]
    )
    url = (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        f"{urllib.parse.quote(symbol)}?modules={modules}"
    )
    payload = _http_json(url)
    result = payload["quoteSummary"]["result"][0]
    price = result.get("price", {})
    detail = result.get("summaryDetail", {})
    financial = result.get("financialData", {})
    stats = result.get("defaultKeyStatistics", {})
    profile = result.get("assetProfile", {})
    return FundamentalSnapshot(
        company_name=str(price.get("longName") or price.get("shortName") or symbol),
        sector=str(profile.get("sector") or ""),
        industry=str(profile.get("industry") or ""),
        description=str(profile.get("longBusinessSummary") or ""),
        market_cap=_coerce_float(price.get("marketCap")),
        trailing_pe=_coerce_float(detail.get("trailingPE")),
        forward_pe=_coerce_float(detail.get("forwardPE")),
        price_to_book=_coerce_float(stats.get("priceToBook")),
        revenue_growth=_coerce_float(financial.get("revenueGrowth")),
        gross_margin=_coerce_float(financial.get("grossMargins")),
        operating_margin=_coerce_float(financial.get("operatingMargins")),
        debt_to_equity=_coerce_float(financial.get("debtToEquity")),
        current_ratio=_coerce_float(financial.get("currentRatio")),
        free_cashflow=_coerce_float(financial.get("freeCashflow")),
    )


def validate_price_data(symbol: str, analysis_date: str) -> bool:
    try:
        return len(get_price_history(symbol, analysis_date, 90)) >= 20
    except Exception:
        return False


def validate_fundamental_data(symbol: str, analysis_date: str) -> bool:
    try:
        snapshot = get_fundamentals(symbol)
        return bool(snapshot.company_name)
    except Exception:
        return False


def get_indicators(symbol: str, analysis_date: str, indicators: list[str] | None = None) -> str:
    bars = get_price_history(symbol, analysis_date, lookback_days=260)
    return render_indicator_report(bars, indicators)


def _format_frame(title: str, frame) -> str:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise InvalidSourceResponse("Financial statement contains no usable data.")
    valid_columns = [column for column in frame.columns if valid_fiscal_period(column)]
    if not valid_columns:
        raise InvalidSourceResponse("Financial statement has no fiscal period.")
    numeric_columns = [column for column in valid_columns if any(finite_number(cell) for cell in frame[column])]
    if not numeric_columns:
        raise InvalidSourceResponse("Financial statement has no finite numeric cells.")
    usable = frame.loc[:, numeric_columns]
    rendered = usable.iloc[:, :3].to_string(max_rows=None, max_cols=None)
    return f"{title}\n{rendered}"


def _get_statement(symbol: str, title: str, attribute: str) -> str:
    if yf is None:
        raise UnconfiguredSourceError("The yfinance client is not available.")
    # Preserve structural failure information for the routing boundary.
    ticker = yf.Ticker(symbol.upper())
    return _format_frame(title, getattr(ticker, attribute))


def get_balance_sheet(symbol: str) -> str:
    return _get_statement(symbol, "Quarterly Balance Sheet", "quarterly_balance_sheet")


def get_cashflow(symbol: str) -> str:
    return _get_statement(symbol, "Quarterly Cash Flow", "quarterly_cashflow")


def get_income_statement(symbol: str) -> str:
    return _get_statement(symbol, "Quarterly Income Statement", "quarterly_income_stmt")


def get_insider_transactions(symbol: str, analysis_date: str) -> str:
    if yf is None:
        return "yfinance is not available."
    modules = "insiderTransactions,defaultKeyStatistics,price"
    url = (
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
        f"{urllib.parse.quote(symbol)}?modules={modules}"
    )
    try:
        payload = _http_json(url)
        result = payload["quoteSummary"]["result"][0]
        transactions = result.get("insiderTransactions", {}).get("transactions", [])
        if not transactions:
            return "No recent insider transaction entries were returned by Yahoo Finance."
        lines = []
        for item in transactions[:5]:
            lines.append(
                f"{item.get('filerName', 'insider')} | {item.get('transactionText', '')} | "
                f"shares={item.get('shares', '')} | value={item.get('value', '')}"
            )
        return "\n".join(lines)
    except Exception:
        return "Insider transaction data could not be retrieved from Yahoo Finance."
