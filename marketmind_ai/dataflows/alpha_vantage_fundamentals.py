from __future__ import annotations

import re

from ..agents.utils.research_types import FundamentalSnapshot
from .alpha_vantage_common import _coerce_float, _gross_margin_from_overview, _make_api_request, _raise_for_alpha_vantage_errors
from .results import InvalidSourceResponse, finite_number, valid_fiscal_period


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


def _statement_report(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise InvalidSourceResponse("Financial statement payload is invalid.")
    _raise_for_alpha_vantage_errors(payload)
    for collection in ("quarterlyReports", "annualReports"):
        reports = payload.get(collection)
        if not isinstance(reports, list):
            continue
        for report in reports:
            if (isinstance(report, dict) and valid_fiscal_period(report.get("fiscalDateEnding"))
                    and any(finite_number(value) for key, value in report.items()
                            if key not in ("fiscalDateEnding", "reportedCurrency"))):
                return report
    raise InvalidSourceResponse("Financial statement contains no valid fiscal report.")


def _render_statement(report: dict) -> str:
    # Preserve every numeric source field accepted by _statement_report. A
    # summary subset can omit the only populated field and lose its evidence.
    lines = [f"Fiscal Date: {report['fiscalDateEnding']}"]
    for key, value in report.items():
        if key in ("fiscalDateEnding", "reportedCurrency") or not finite_number(value):
            continue
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", key).title()
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def get_balance_sheet(symbol: str) -> str:
    payload = _make_api_request("BALANCE_SHEET", {"symbol": symbol})
    return _render_statement(_statement_report(payload))


def get_cashflow(symbol: str) -> str:
    payload = _make_api_request("CASH_FLOW", {"symbol": symbol})
    return _render_statement(_statement_report(payload))


def get_income_statement(symbol: str) -> str:
    payload = _make_api_request("INCOME_STATEMENT", {"symbol": symbol})
    return _render_statement(_statement_report(payload))
