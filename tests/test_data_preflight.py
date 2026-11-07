from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from marketmind_ai.agents.utils.research_types import PriceBar
from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.dataflows.instrument_metadata import InstrumentEligibility
from marketmind_ai.dataflows.preflight import run_preflight, validate_daily_bars
from marketmind_ai.graph.runtime_support import build_offline_data_vendor_config


def bars(count):
    return [PriceBar((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 10, 12, 9, 11, 0) for i in range(count)]


@pytest.mark.parametrize('count,eligible', [(49, False), (50, True)])
def test_exact_valid_price_minimum(monkeypatch, count, eligible):
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'offline', lambda *a: bars(count))
    with dataflow_context({'data_mode': 'demo', 'data_vendors': build_offline_data_vendor_config()}):
        result = run_preflight('AAPL', '2026-06-12')
    assert result.can_recommend is eligible
    assert result.requirements['price_history']['valid_count'] == count


def test_invalid_and_future_rows_do_not_count_and_conflicts_block():
    valid = bars(50)
    invalid = [PriceBar('2026-01-02', 10, 9, 8, 11, 5), PriceBar('2027-01-01', 10, 12, 9, 11, 1),
               PriceBar('2026-03-01', float('nan'), 12, 9, 11, 1)]
    clean, reasons = validate_daily_bars(valid + invalid, '2026-06-12')
    assert len(clean) == 50
    assert reasons
    conflict = PriceBar(valid[0].date, 10, 13, 9, 11, 2)
    clean, reasons = validate_daily_bars(valid + [conflict], '2026-06-12')
    assert 'conflicting_price_dates' in reasons
    assert len(clean) == 49


def test_news_is_optional_but_each_statement_is_required(monkeypatch):
    monkeypatch.setitem(VENDOR_METHODS['get_news'], 'offline', lambda *a: [])
    config = {'data_mode': 'demo', 'data_vendors': build_offline_data_vendor_config()}
    with dataflow_context(config):
        result = run_preflight('AAPL', '2026-06-12')
        assert result.can_recommend
        assert not result.requirements['news']['available']
    monkeypatch.setitem(VENDOR_METHODS['get_cashflow'], 'offline', lambda *a: None)
    with dataflow_context(config):
        result = run_preflight('AAPL', '2026-06-12')
        assert not result.can_recommend
        assert 'cashflow' in result.missing
        assert result.to_dict()['data_mode'] == 'demo'


def test_unverified_instrument_stops_before_price_research(monkeypatch):
    monkeypatch.setitem(VENDOR_METHODS['get_instrument_metadata'], 'offline', lambda *a: InstrumentEligibility('AAPL'))
    price = Mock()
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'offline', price)
    with dataflow_context({'data_mode': 'demo', 'data_vendors': build_offline_data_vendor_config()}):
        assert not run_preflight('AAPL', '2026-06-12').can_recommend
    price.assert_not_called()
