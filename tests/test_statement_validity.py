from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from marketmind_ai.dataflows import alpha_vantage_fundamentals as av
from marketmind_ai.dataflows import y_finance as yahoo
from marketmind_ai.dataflows.results import InvalidSourceResponse


@pytest.mark.parametrize("method,attribute", [("get_income_statement", "quarterly_income_stmt"), ("get_balance_sheet", "quarterly_balance_sheet"), ("get_cashflow", "quarterly_cashflow")])
@pytest.mark.parametrize("frame", [pd.DataFrame(), pd.DataFrame({"2026-06-30": [None]}), pd.DataFrame({"not a period": [12]}), pd.DataFrame({"2026-06-30": [float("inf")]}), "Error 429 occurred at 2026-06-30"])
def test_yahoo_statement_requires_period_and_finite_numeric_cells(monkeypatch, method, attribute, frame):
    ticker = SimpleNamespace(**{attribute: frame})
    monkeypatch.setattr(yahoo, "yf", SimpleNamespace(Ticker=lambda symbol: ticker))
    with pytest.raises(InvalidSourceResponse):
        getattr(yahoo, method)("NVDA")


@pytest.mark.parametrize("frame", [pd.DataFrame({pd.Timestamp("2026-06-30"): [0]}), pd.DataFrame({"2026-06-30": [0]})])
def test_yahoo_zero_is_a_valid_statement_value(monkeypatch, frame):
    monkeypatch.setattr(yahoo, "yf", SimpleNamespace(Ticker=lambda symbol: SimpleNamespace(quarterly_income_stmt=frame)))
    assert "2026-06-30" in yahoo.get_income_statement("NVDA")


@pytest.mark.parametrize("report", [{}, {"fiscalDateEnding": "2026-06-30"}, {"fiscalDateEnding": "not a date", "totalRevenue": "12"}, {"fiscalDateEnding": "2026-06-30", "totalRevenue": "None"}, {"fiscalDateEnding": "2026-06-30", "totalRevenue": "inf"}, {"fiscalDateEnding": "2026-06-30", "totalRevenue": "Error 429"}])
@pytest.mark.parametrize("method", ["get_income_statement", "get_balance_sheet", "get_cashflow"])
def test_av_statement_requires_period_and_finite_numeric_cells(monkeypatch, method, report):
    monkeypatch.setattr(av, "_make_api_request", lambda *a: {"quarterlyReports": [report]})
    with pytest.raises(InvalidSourceResponse):
        getattr(av, method)("NVDA")


def test_av_accepts_zero_and_skips_invalid_latest_report(monkeypatch):
    monkeypatch.setattr(av, "_make_api_request", lambda *a: {"quarterlyReports": [{"fiscalDateEnding": "2026-09-30", "totalRevenue": "None"}, {"fiscalDateEnding": "2026-06-30", "totalRevenue": "0"}]})
    rendered = av.get_income_statement("NVDA")
    assert "2026-06-30" in rendered and "Total Revenue: 0" in rendered


def test_yahoo_nat_is_not_a_fiscal_period(monkeypatch):
    frame = pd.DataFrame({pd.NaT: [1]})
    monkeypatch.setattr(yahoo, "yf", SimpleNamespace(Ticker=lambda symbol: SimpleNamespace(quarterly_income_stmt=frame)))
    with pytest.raises(InvalidSourceResponse):
        yahoo.get_income_statement("NVDA")


def test_yahoo_render_keeps_the_valid_numeric_period(monkeypatch):
    frame = pd.DataFrame({"2026-09-30": [None], "2026-06-30": [None], "2026-03-31": [None], "2025-12-31": [123456]})
    monkeypatch.setattr(yahoo, "yf", SimpleNamespace(Ticker=lambda symbol: SimpleNamespace(quarterly_income_stmt=frame)))
    assert "123456" in yahoo.get_income_statement("NVDA")


@pytest.mark.parametrize("value", [100, 0, "0"])
@pytest.mark.parametrize("method", ["get_income_statement", "get_balance_sheet", "get_cashflow"])
def test_av_render_retains_valid_numeric_fields_outside_summary_subset(monkeypatch, method, value):
    report = {
        "fiscalDateEnding": "2026-06-30",
        "reportedCurrency": "USD",
        "unlistedMetric": value,
        "otherMetric": "42",
        "operatingCashflow": "None",
        "capitalExpenditures": None,
        "cashflowFromInvestment": "None",
        "cashflowFromFinancing": None,
    }
    monkeypatch.setattr(av, "_make_api_request", lambda *a: {"quarterlyReports": [report]})
    rendered = getattr(av, method)("NVDA")
    assert f"Unlisted Metric: {value}" in rendered
    assert "Other Metric: 42" in rendered
    assert "None" not in rendered


def test_av_cashflow_renders_valid_net_income_when_summary_fields_missing(monkeypatch):
    report = {"fiscalDateEnding": "2026-06-30", "netIncome": "100", "operatingCashflow": "None", "capitalExpenditures": "None", "cashflowFromInvestment": "None", "cashflowFromFinancing": "None"}
    monkeypatch.setattr(av, "_make_api_request", lambda *a: {"quarterlyReports": [report]})
    assert "Net Income: 100" in av.get_cashflow("NVDA")


def test_yahoo_render_does_not_truncate_numeric_evidence_in_middle_rows(monkeypatch):
    values = [None] * 80
    values[40] = 123456
    frame = pd.DataFrame({"2026-06-30": values}, dtype=object)
    monkeypatch.setattr(yahoo, "yf", SimpleNamespace(Ticker=lambda symbol: SimpleNamespace(quarterly_income_stmt=frame)))
    with pd.option_context("display.max_rows", 60):
        rendered = yahoo.get_income_statement("NVDA")
    assert "123456" in rendered
    assert "..." not in rendered
