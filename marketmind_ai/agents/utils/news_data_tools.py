from __future__ import annotations

from langchain_core.tools import tool

from ...dataflows.interface import fetch_from_vendors
from ...dataflows.news_rag import build_news_event_timeline


def build_news_data_tools(context, roles: tuple[str, ...] = ("news", "sentiment")):
    tools = []

    @tool
    def get_news(symbol: str, analysis_date: str = "", limit: int = 8) -> str:
        """Return recent company-specific headlines."""
        effective = analysis_date or context.analysis_date
        result = fetch_from_vendors("get_news", symbol, effective, limit)
        if not result.available:
            return "No time-verified company headlines are available for this request."
        items = result.value
        lines = [f"{item.published_at} | {item.source} | sentiment={item.sentiment_score} | {item.title}" for item in items[:limit]]
        return "\n".join(lines) or "No recent company headlines found."

    tools.append(get_news)

    if "news" in roles:
        @tool
        def get_news_event_timeline(symbol: str, analysis_date: str = "", limit: int = 8) -> str:
            """Return a chronological company event timeline."""
            effective = analysis_date or context.analysis_date
            return build_news_event_timeline(symbol, effective, look_back_days=max(limit, 7))

        @tool
        def get_global_news(analysis_date: str = "", theme: str = "macro") -> str:
            """Return broad macro context relevant to the trading date."""
            effective = analysis_date or context.analysis_date
            result = fetch_from_vendors("get_global_news", effective, theme, 6)
            if not result.available:
                return "No time-verified macro headlines are available for this request."
            items = result.value
            lines = [
                f"{item.published_at} | {item.source} | sentiment={item.sentiment_score} | {item.title}"
                for item in items
            ]
            return "\n".join(lines) or f"{effective}: No broad macro headlines were returned."

        @tool
        def get_insider_transactions(symbol: str, analysis_date: str = "") -> str:
            """Return recent insider-activity context for a ticker."""
            result = fetch_from_vendors("get_insider_transactions", symbol, analysis_date or context.analysis_date)
            return result.value if result.available else "No time-verified insider activity is available for this request."

        tools.extend([get_news_event_timeline, get_global_news, get_insider_transactions])

    return tools
