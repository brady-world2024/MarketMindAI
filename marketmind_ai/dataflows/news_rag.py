"""News-focused retrieval and lightweight event-timeline helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
from typing import Iterable

from .config import get_config
from .interface import collect_from_vendors


@dataclass
class NewsEventSnippet:
    source: str
    title: str
    summary: str
    published_at: str
    provider: str
    scope: str
    link: str = ""
    sentiment_label: str = ""
    sentiment_score: float | None = None


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DEFAULT_COMPANY_QUERY = (
    "earnings guidance product launch demand supply regulation lawsuit "
    "partnership AI chips margins revenue customers competition"
)
_DEFAULT_MACRO_QUERY = (
    "interest rates inflation macro economy tariffs regulation semiconductors "
    "supply chain risk geopolitics market demand"
)


def build_news_event_timeline(
    ticker: str,
    curr_date: str,
    look_back_days: int = 7,
    query: str | None = None,
    *,
    provider=None,
) -> str:
    """Collect, rank, and render company + macro news into an event timeline."""
    config = get_config()
    if not config.get("news_rag_enabled", True):
        return "News event RAG is disabled in the current configuration."

    current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (current_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    company_events = collect_from_vendors(
        "get_news_documents",
        ticker,
        start_date,
        curr_date,
    )
    macro_events = collect_from_vendors(
        "get_global_news_documents",
        curr_date,
        look_back_days,
        max(int(config.get("news_rag_macro_limit", 4)) * 3, 12),
    )

    unique_company = _dedupe_events(_coerce_events(company_events))
    unique_macro = _dedupe_events(_coerce_events(macro_events))
    if not unique_company and not unique_macro:
        return (
            f"No company-specific or macro news events were available for `{ticker}` "
            f"between {start_date} and {curr_date}."
        )

    company_selected = rank_news_event_snippets(
        unique_company,
        query=query or _DEFAULT_COMPANY_QUERY,
        curr_date=curr_date,
        limit=int(config.get("news_rag_company_limit", 6)),
    )
    macro_selected = rank_news_event_snippets(
        unique_macro,
        query=query or _DEFAULT_MACRO_QUERY,
        curr_date=curr_date,
        limit=int(config.get("news_rag_macro_limit", 4)),
    )

    lines = [
        f"# News and event timeline for {ticker}",
        f"# Window: {start_date} to {curr_date}.",
        (
            "# Use this timeline to identify confirmed catalysts, unresolved follow-ups, "
            "and macro context before reading raw article dumps."
        ),
        "",
        f"## Company-specific catalysts ({len(company_selected)} shown)",
    ]
    lines.extend(_render_timeline(company_selected, empty_message="No company-specific events were retrieved."))
    lines.extend(["", f"## Macro / market context ({len(macro_selected)} shown)"])
    lines.extend(_render_timeline(macro_selected, empty_message="No macro events were retrieved."))
    return "\n".join(lines).strip()


def rank_news_event_snippets(
    snippets: Iterable[NewsEventSnippet],
    query: str,
    curr_date: str,
    limit: int = 6,
) -> list[NewsEventSnippet]:
    """Rank news events using title/query overlap, recency, and article quality."""
    query_tokens = set(_TOKEN_RE.findall(query.lower())) or set(_TOKEN_RE.findall(_DEFAULT_COMPANY_QUERY))
    ranked = []
    for snippet in snippets:
        text = f"{snippet.title} {snippet.summary}".lower()
        text_tokens = set(_TOKEN_RE.findall(text))
        overlap = len(query_tokens & text_tokens)
        if overlap == 0 and len(text_tokens) < 8:
            continue
        score = float(overlap)
        score += _title_overlap_bonus(snippet.title, query_tokens)
        score += _recency_weight(snippet.published_at, curr_date)
        score += 0.35 if snippet.summary else 0.0
        score += 0.25 if snippet.link else 0.0
        score += 0.2 if snippet.scope == "company" else 0.0
        score += _sentiment_bonus(snippet.sentiment_score)
        ranked.append((score, snippet))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].published_at,
            item[1].title,
        ),
        reverse=True,
    )
    return [snippet for _, snippet in ranked[:limit]]


def _render_timeline(snippets: list[NewsEventSnippet], *, empty_message: str) -> list[str]:
    if not snippets:
        return [empty_message]

    lines = []
    for index, snippet in enumerate(snippets, start=1):
        lines.extend(
            [
                f"### {index}. {snippet.published_at or 'Unknown date'} — {snippet.title}",
                f"- Source: {snippet.source}",
                f"- Provider: {snippet.provider}",
                f"- Scope: {snippet.scope}",
                *(
                    [f"- Sentiment: {snippet.sentiment_label} ({snippet.sentiment_score:+.2f})"]
                    if snippet.sentiment_score is not None
                    else ([f"- Sentiment: {snippet.sentiment_label}"] if snippet.sentiment_label else [])
                ),
                *([f"- Link: {snippet.link}"] if snippet.link else []),
                snippet.summary.strip() or "No summary was provided by the data source.",
                "",
            ]
        )
    return lines


def _coerce_events(items: Iterable[NewsEventSnippet | dict]) -> list[NewsEventSnippet]:
    events = []
    for item in items:
        if isinstance(item, NewsEventSnippet):
            events.append(item)
            continue
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        events.append(
            NewsEventSnippet(
                source=str(item.get("source", "Unknown")),
                title=title,
                summary=str(item.get("summary", "")),
                published_at=str(item.get("published_at", "")),
                provider=str(item.get("provider", "unknown")),
                scope=str(item.get("scope", "company")),
                link=str(item.get("link", "")),
                sentiment_label=str(item.get("sentiment_label", "")),
                sentiment_score=_coerce_float(item.get("sentiment_score")),
            )
        )
    return events


def _dedupe_events(snippets: Iterable[NewsEventSnippet]) -> list[NewsEventSnippet]:
    seen = set()
    unique = []
    for snippet in snippets:
        key = (
            snippet.title.lower(),
            snippet.published_at,
            snippet.source.lower(),
            snippet.link,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(snippet)
    return unique


def _title_overlap_bonus(title: str, query_tokens: set[str]) -> float:
    title_tokens = set(_TOKEN_RE.findall(title.lower()))
    overlap = len(query_tokens & title_tokens)
    return overlap * 0.6


def _recency_weight(published_at: str, curr_date: str) -> float:
    try:
        published_dt = datetime.strptime(published_at, "%Y-%m-%d")
        current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError:
        return 0.0

    delta_days = max((current_dt - published_dt).days, 0)
    return 1.0 / (1.0 + math.log1p(delta_days))


def _sentiment_bonus(sentiment_score: float | None) -> float:
    if sentiment_score is None:
        return 0.0
    return min(abs(sentiment_score), 1.0) * 0.2


def _coerce_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
