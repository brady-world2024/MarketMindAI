from __future__ import annotations

from langchain_core.tools import tool


def build_core_stock_tools(context):
    @tool
    def get_stock_data(symbol: str, analysis_date: str = "") -> str:
        """Return recent OHLCV data for a ticker in CSV-like form."""
        bundle = context.load_bundle(symbol)
        rows = ["date,open,high,low,close,volume"]
        for bar in bundle.market.bars[-30:]:
            rows.append(f"{bar.date},{bar.open},{bar.high},{bar.low},{bar.close},{bar.volume}")
        return "\n".join(rows)

    return [get_stock_data]
