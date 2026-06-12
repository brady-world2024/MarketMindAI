from __future__ import annotations

from ..agents.utils.research_types import FundamentalSnapshot
from .alpha_vantage_common import _coerce_float, _gross_margin_from_overview, _make_api_request


def get_fundamentals(symbol: str) -> FundamentalSnapshot:
    payload = _make_api_request("OVERVIEW", {"symbol": symbol})
    if not payload or "Symbol" not in payload:
        raise RuntimeError(f"No Alpha Vantage overview for {symbol}")
    return FundamentalSnapshot(
        company_name=str(payload.get("Name") or symbol),
        sector=str(payload.get("Sector") or ""),
        industry=str(payload.get("Industry") or ""),
        description=str(payload.get("Description") or ""),
        market_cap=_coerce_float(payload.get("MarketCapitalization")),
        trailing_pe=_coerce_float(payload.get("PERatio")),
        forward_pe=_coerce_float(payload.get("ForwardPE")),
        price_to_book=_coerce_float(payload.get("PriceToBookRatio")),
        revenue_growth=_coerce_float(payload.get("QuarterlyRevenueGrowthYOY")),
        gross_margin=_gross_margin_from_overview(payload),
        operating_margin=_coerce_float(payload.get("OperatingMarginTTM")),
        debt_to_equity=_coerce_float(payload.get("DebtToEquityRatio")),
        current_ratio=_coerce_float(payload.get("CurrentRatio")),
        free_cashflow=_coerce_float(payload.get("FreeCashFlowTTM")),
    )


def get_balance_sheet(symbol: str) -> str:
    payload = _make_api_request("BALANCE_SHEET", {"symbol": symbol})
    reports = payload.get("quarterlyReports") or payload.get("annualReports") or []
    if not reports:
        return "No Alpha Vantage balance-sheet report was returned."
    report = reports[0]
    return (
        f"Fiscal Date: {report.get('fiscalDateEnding', '')}\n"
        f"Total Assets: {report.get('totalAssets', '')}\n"
        f"Total Liabilities: {report.get('totalLiabilities', '')}\n"
        f"Cash And Short Term Investments: {report.get('cashAndShortTermInvestments', '')}\n"
        f"Current Debt: {report.get('currentDebt', '')}\n"
        f"Long Term Debt: {report.get('longTermDebt', '')}"
    )


def get_cashflow(symbol: str) -> str:
    payload = _make_api_request("CASH_FLOW", {"symbol": symbol})
    reports = payload.get("quarterlyReports") or payload.get("annualReports") or []
    if not reports:
        return "No Alpha Vantage cash-flow report was returned."
    report = reports[0]
    return (
        f"Fiscal Date: {report.get('fiscalDateEnding', '')}\n"
        f"Operating Cashflow: {report.get('operatingCashflow', '')}\n"
        f"Capital Expenditures: {report.get('capitalExpenditures', '')}\n"
        f"Cashflow From Investment: {report.get('cashflowFromInvestment', '')}\n"
        f"Cashflow From Financing: {report.get('cashflowFromFinancing', '')}"
    )


def get_income_statement(symbol: str) -> str:
    payload = _make_api_request("INCOME_STATEMENT", {"symbol": symbol})
    reports = payload.get("quarterlyReports") or payload.get("annualReports") or []
    if not reports:
        return "No Alpha Vantage income-statement report was returned."
    report = reports[0]
    return (
        f"Fiscal Date: {report.get('fiscalDateEnding', '')}\n"
        f"Total Revenue: {report.get('totalRevenue', '')}\n"
        f"Gross Profit: {report.get('grossProfit', '')}\n"
        f"Operating Income: {report.get('operatingIncome', '')}\n"
        f"Net Income: {report.get('netIncome', '')}"
    )
