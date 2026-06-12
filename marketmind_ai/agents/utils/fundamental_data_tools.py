from __future__ import annotations

from langchain_core.tools import tool

from ...dataflows.fundamentals_rag import build_fundamental_document_context
from ...dataflows.interface import route_to_vendor


def build_fundamental_data_tools(context):
    @tool
    def get_fundamentals(symbol: str) -> str:
        """Return a compact business and valuation snapshot."""
        bundle = context.load_bundle(symbol)
        f = bundle.fundamentals
        return (
            f"company={f.company_name}\nsector={f.sector}\nindustry={f.industry}\n"
            f"market_cap={f.market_cap}\ntrailing_pe={f.trailing_pe}\nforward_pe={f.forward_pe}\n"
            f"revenue_growth={f.revenue_growth}\ngross_margin={f.gross_margin}\n"
            f"operating_margin={f.operating_margin}\ndebt_to_equity={f.debt_to_equity}\n"
            f"current_ratio={f.current_ratio}\nfree_cashflow={f.free_cashflow}\n"
            f"description={f.description}"
        )

    @tool
    def get_balance_sheet(symbol: str) -> str:
        """Return balance-sheet style indicators."""
        return route_to_vendor("get_balance_sheet", symbol)

    @tool
    def get_cashflow(symbol: str) -> str:
        """Return cash-flow style indicators."""
        return route_to_vendor("get_cashflow", symbol)

    @tool
    def get_income_statement(symbol: str) -> str:
        """Return income-statement style indicators."""
        return route_to_vendor("get_income_statement", symbol)

    @tool
    def get_fundamental_document_context(symbol: str, analysis_date: str = "") -> str:
        """Return long-form filing or business-summary context for the fundamentals analyst."""
        return build_fundamental_document_context(symbol, analysis_date or context.analysis_date)

    return [
        get_fundamentals,
        get_balance_sheet,
        get_cashflow,
        get_income_statement,
        get_fundamental_document_context,
    ]
