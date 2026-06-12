from __future__ import annotations

from langchain_core.tools import tool

from ...dataflows.interface import route_to_vendor


def build_technical_indicator_tools(context):
    @tool
    def get_indicators(symbol: str, analysis_date: str = "", indicators: list[str] | None = None) -> str:
        """Return selected technical indicators for a ticker."""
        effective = analysis_date or context.analysis_date
        return route_to_vendor("get_indicators", symbol, effective, indicators)

    return [get_indicators]
