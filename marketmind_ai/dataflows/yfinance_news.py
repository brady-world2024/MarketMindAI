"""yfinance-based news data fetching functions."""

from __future__ import annotations

from datetime import datetime, timedelta

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional import failure path
    yf = None

from ..agents.utils.research_types import NewsItem


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format."""
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pub_date = None
        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    return {
        "title": article.get("title", "No title"),
        "summary": article.get("summary", ""),
        "publisher": article.get("publisher", "Unknown"),
        "link": article.get("link", ""),
        "pub_date": None,
    }


def _article_to_document(article: dict, scope: str) -> dict:
    data = _extract_article_data(article)
    pub_date = data.get("pub_date")
    published_at = pub_date.strftime("%Y-%m-%d") if pub_date else ""
    return {
        "title": data["title"],
        "summary": data["summary"],
        "source": data["publisher"],
        "link": data["link"],
        "published_at": published_at,
        "provider": "yfinance",
        "scope": scope,
        "sentiment_label": "",
        "sentiment_score": None,
    }


def _document_to_news_item(document: dict) -> NewsItem:
    return NewsItem(
        title=str(document.get("title") or ""),
        source=str(document.get("source") or "Yahoo Finance"),
        published_at=str(document.get("published_at") or ""),
        url=str(document.get("link") or ""),
        summary=str(document.get("summary") or ""),
        sentiment_score=float(document.get("sentiment_score") or 0.0),
    )


def get_news_yfinance(ticker: str, analysis_date: str, limit: int = 8) -> list[NewsItem]:
    start_date = (datetime.strptime(analysis_date, "%Y-%m-%d") - timedelta(days=max(limit, 7) * 2)).strftime("%Y-%m-%d")
    documents = get_news_documents_yfinance(ticker, start_date, analysis_date)
    return [_document_to_news_item(item) for item in documents[:limit] if item.get("title")]


def get_global_news_yfinance(analysis_date: str, theme: str = "macro", limit: int = 8) -> list[NewsItem]:
    documents = get_global_news_documents_yfinance(analysis_date, look_back_days=max(limit, 7), limit=limit)
    items = []
    for item in documents[:limit]:
        article = _document_to_news_item(item)
        if theme and theme.lower() not in {"macro", "market"}:
            article.title = f"{theme.title()}: {article.title}"
        items.append(article)
    return items


def get_news_documents_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Retrieve structured company-news documents for RAG and event timelines."""
    if yf is None:
        return []
    try:
        stock = yf.Ticker(ticker)
        news = stock.get_news(count=30)
        if not news:
            return []

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        documents = []
        for article in news:
            data = _extract_article_data(article)
            if data["pub_date"]:
                pub_date_naive = data["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_date_naive <= end_dt + timedelta(days=1)):
                    continue
            documents.append(_article_to_document(article, "company"))
        return documents
    except Exception:
        return []


def get_global_news_documents_yfinance(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> list[dict]:
    """Retrieve structured macro-news documents for RAG and event timelines."""
    if yf is None:
        return []
    search_queries = [
        "stock market economy",
        "Federal Reserve interest rates",
        "inflation economic outlook",
        "global markets trading",
    ]

    all_news = []
    seen_titles = set()
    try:
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)

        for query in search_queries:
            search = yf.Search(
                query=query,
                news_count=limit,
                enable_fuzzy_query=True,
            )

            if not search.news:
                continue

            for article in search.news:
                data = _extract_article_data(article)
                title = data["title"]
                if not title or title in seen_titles:
                    continue
                pub_date = data.get("pub_date")
                if pub_date:
                    pub_naive = pub_date.replace(tzinfo=None)
                    if pub_naive < start_dt or pub_naive > curr_dt + timedelta(days=1):
                        continue
                seen_titles.add(title)
                all_news.append(_article_to_document(article, "macro"))

            if len(all_news) >= limit:
                break

        return all_news[:limit]
    except Exception:
        return []
