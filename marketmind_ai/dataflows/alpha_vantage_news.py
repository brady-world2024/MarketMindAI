from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..agents.utils.research_types import NewsItem
from .alpha_vantage_common import _coerce_float, _make_api_request, format_datetime_for_api


def get_news_documents(ticker: str, start_date: str, end_date: str) -> list[dict]:
    """Retrieve structured company-news documents for RAG and event timelines."""
    payload = _make_api_request(
        "NEWS_SENTIMENT",
        {
            "tickers": ticker,
            "time_from": format_datetime_for_api(start_date),
            "time_to": format_datetime_for_api(end_date),
        },
    )
    return _extract_feed_items(payload, scope="company", end_date=end_date)


def get_global_news_documents(curr_date: str, look_back_days: int = 7, limit: int = 25) -> list[dict]:
    """Retrieve structured macro-news documents for RAG and event timelines."""
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    payload = _make_api_request(
        "NEWS_SENTIMENT",
        {
            "topics": "financial_markets,economy_macro,economy_monetary",
            "time_from": format_datetime_for_api(start_date),
            "time_to": format_datetime_for_api(curr_date),
            "limit": str(limit),
        },
    )
    return _extract_feed_items(payload, scope="macro", end_date=curr_date)


def get_news(ticker: str, analysis_date: str, limit: int = 8) -> list[NewsItem]:
    start_date = (datetime.strptime(analysis_date, "%Y-%m-%d") - timedelta(days=max(limit, 7) * 2)).strftime("%Y-%m-%d")
    documents = get_news_documents(ticker, start_date, analysis_date)
    return [_document_to_news_item(item) for item in documents[:limit]]


def get_global_news(curr_date: str, theme: str = "macro", limit: int = 8) -> list[NewsItem]:
    documents = get_global_news_documents(curr_date, look_back_days=max(limit, 7), limit=limit)
    items = []
    for item in documents[:limit]:
        article = _document_to_news_item(item)
        if theme and theme.lower() not in {"macro", "market"}:
            article.title = f"{theme.title()}: {article.title}"
        items.append(article)
    return items


def get_insider_transactions(symbol: str, analysis_date: str = "") -> str:
    payload = _make_api_request("INSIDER_TRANSACTIONS", {"symbol": symbol})
    items = _extract_insider_items(payload, analysis_date=analysis_date)
    if not items:
        return "No recent insider transaction entries were returned by Alpha Vantage."

    lines = []
    for item in items[:5]:
        parts = [
            item.get("transaction_date") or "Unknown date",
            item.get("insider_name") or "Unknown insider",
            item.get("transaction_type") or "Unknown action",
        ]
        shares = item.get("shares")
        price = item.get("share_price")
        if shares is not None:
            parts.append(f"shares={shares:g}")
        if price is not None:
            parts.append(f"price={price:g}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _extract_feed_items(
    payload: dict | str,
    *,
    scope: str,
    end_date: str,
) -> list[dict]:
    data = _load_payload(payload)
    feed = data.get("feed", []) if isinstance(data, dict) else []
    items = []
    for article in feed:
        published_at = _normalize_published_at(article.get("time_published", ""))
        if published_at and published_at > end_date:
            continue
        items.append(
            {
                "title": article.get("title", "No title"),
                "summary": article.get("summary", ""),
                "source": article.get("source", "Alpha Vantage"),
                "link": article.get("url", ""),
                "published_at": published_at,
                "provider": "alpha_vantage",
                "scope": scope,
                "sentiment_label": article.get("overall_sentiment_label", ""),
                "sentiment_score": _coerce_float(article.get("overall_sentiment_score")),
            }
        )
    return items


def _document_to_news_item(item: dict) -> NewsItem:
    return NewsItem(
        title=str(item.get("title") or ""),
        source=str(item.get("source") or "Alpha Vantage"),
        published_at=str(item.get("published_at") or ""),
        url=str(item.get("link") or ""),
        summary=str(item.get("summary") or ""),
        sentiment_score=float(item.get("sentiment_score") or 0.0),
    )


def _load_payload(payload: dict | str) -> dict:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def _normalize_published_at(value: str) -> str:
    if not value:
        return ""
    for fmt in ("%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value[:10] if len(value) >= 10 else ""


def _extract_insider_items(payload: dict | str, analysis_date: str = "") -> list[dict]:
    data = _load_payload(payload)
    records = []
    for raw in data.get("data", []) if isinstance(data, dict) else []:
        trade_date = str(
            raw.get("transaction_date")
            or raw.get("filing_date")
            or raw.get("transactionDate")
            or ""
        )
        normalized_date = _normalize_published_at(trade_date) if trade_date else ""
        if analysis_date and normalized_date and normalized_date > analysis_date:
            continue
        records.append(
            {
                "transaction_date": normalized_date or trade_date or "",
                "insider_name": str(
                    raw.get("insider_name")
                    or raw.get("name")
                    or raw.get("executive")
                    or ""
                ),
                "transaction_type": str(
                    raw.get("transaction_type")
                    or raw.get("acquisition_or_disposal")
                    or raw.get("transactionType")
                    or ""
                ),
                "shares": _coerce_float(
                    raw.get("shares")
                    or raw.get("share_count")
                    or raw.get("shares_traded")
                ),
                "share_price": _coerce_float(
                    raw.get("share_price")
                    or raw.get("price")
                    or raw.get("transaction_price")
                ),
            }
        )
    records.sort(key=lambda item: item.get("transaction_date") or "", reverse=True)
    return records
