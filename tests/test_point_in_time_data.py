from datetime import datetime, timezone
from unittest.mock import Mock

import exchange_calendars as xcals
import pytest

from marketmind_ai.agents.utils.research_types import FundamentalSnapshot, NewsItem, PriceBar
from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.dataflows.instrument_metadata import InstrumentEligibility
from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.dataflows.research_cutoff import resolve_research_cutoff
from marketmind_ai.dataflows.research_snapshot import prepare_research_snapshot
from marketmind_ai.dataflows.sec_statements import SECCapture, SECStatement, SECStatementBundle
from marketmind_ai.dataflows.source_store import SourceStore
from marketmind_ai.dataflows.price_units import PriceHistory
from marketmind_ai.default_config import build_default_config
from marketmind_ai.symbols import SymbolResolution


def valid_bars():
    sessions = xcals.get_calendar('XNYS').sessions_in_range('2026-02-01', '2026-06-12')[-60:]
    return PriceHistory([PriceBar(day.date().isoformat(), 10, 12, 9, 11, 0) for day in sessions], {
        'verified': True, 'basis': 'cutoff_split_units_no_dividend_adjustment', 'cutoff_at': '2026-06-12T20:00:00+00:00'})


def sec_bundle():
    bundle = SECStatementBundle('ABC', cik='0000000001', form='10-Q', accession='0000000001-26-000001',
        period_end='2026-03-31', published_at='2026-05-01T15:00:00+00:00', source_url='https://www.sec.gov/filing', available=True)
    for kind in ('income_statement', 'balance_sheet', 'cashflow'):
        url = f'https://www.sec.gov/filing/{kind}.htm'
        text = f'{kind}\nFiscal period 2026-03-31\nRevenue: 0'
        bundle.statements[kind] = SECStatement(kind, kind, url, text, [['Revenue', '0']], 'USD', ['$ in millions'], '2026-03-31', 1)
        bundle.captures.append(SECCapture(url, 'text/html', '<table>Revenue: 0</table>', '2026-06-13T10:00:00Z'))
    return bundle


@pytest.fixture
def sources(tmp_path, monkeypatch):
    config = build_default_config(tmp_path, {'data_mode': 'live'})
    monkeypatch.setitem(VENDOR_METHODS['get_instrument_metadata'], 'sec', lambda *a: InstrumentEligibility(
        'ABC', 'supported', 'NYSE', 'common_stock', metadata={'cik': '0000000001', 'published_at': '2026-05-01T15:00:00Z'}, provider='sec'))
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'yfinance', lambda *a: valid_bars())
    monkeypatch.setitem(VENDOR_METHODS['get_fundamentals'], 'yfinance', lambda *a: FundamentalSnapshot('ABC', trailing_pe=999))
    monkeypatch.setitem(VENDOR_METHODS['get_news'], 'yfinance', lambda *a: [
        NewsItem('Before close', 'Publisher', '2026-06-12T19:59:00Z', 'https://news.test/a'),
        NewsItem('After close', 'Publisher', '2026-06-12T20:01:00Z', 'https://news.test/b'),
        NewsItem('Unknown time', 'Publisher', '2026-06-12', 'https://news.test/c')])
    monkeypatch.setitem(VENDOR_METHODS['get_global_news'], 'yfinance', lambda *a: [])
    monkeypatch.setitem(VENDOR_METHODS['get_insider_transactions'], 'yfinance', lambda *a: 'Current insider summary')
    bundle = sec_bundle()
    reader = Mock(return_value=bundle)
    monkeypatch.setattr('marketmind_ai.dataflows.research_snapshot.get_sec_statement_bundle', reader)
    cutoff = resolve_research_cutoff('2026-06-13', now=datetime(2026, 6, 13, 12, tzinfo=timezone.utc))
    resolution = SymbolResolution(status='RESOLVED', original_input='ABC', normalized_query='ABC', resolved_symbol='ABC', company_name='ABC')
    return config, cutoff, resolution, bundle, reader


def test_preparation_keeps_excluded_material_but_only_freezes_verified_inputs(tmp_path, sources):
    config, cutoff, resolution, bundle, reader = sources
    store = SourceStore(tmp_path / 'sources')
    with dataflow_context(config, run_id='new-run') as audit:
        snapshot = prepare_research_snapshot(resolution, cutoff, store, run_id='new-run')
    assert snapshot.availability['can_recommend'] is True
    assert snapshot.inputs['get_news']['value'][0]['title'] == 'Before close'
    assert len(snapshot.inputs['get_news']['value']) == 1
    assert snapshot.inputs['get_fundamentals']['available'] is False
    assert any(r.reason_codes == ['published_after_cutoff'] for r in snapshot.records)
    assert any(r.reason_codes == ['public_time_unverified'] for r in snapshot.records)
    assert any(r.content and '999' in str(r.content) and r.admissibility != 'included' for r in snapshot.records)
    assert store.load(snapshot.snapshot_id).inputs == snapshot.inputs
    assert audit.frozen_inputs is not None
    assert reader.call_args.args[1] == cutoff.cutoff_at


@pytest.mark.parametrize('failure', ['latest_statement_missing', 'statement_after_close', 'stale_prices'])
def test_required_freshness_or_time_failure_cannot_become_recommendation(tmp_path, sources, monkeypatch, failure):
    config, cutoff, resolution, bundle, _ = sources
    if failure == 'latest_statement_missing':
        bundle.available = False
        bundle.reason_codes = ['missing_cashflow']
        del bundle.statements['cashflow']
    elif failure == 'statement_after_close':
        bundle.published_at = '2026-06-12T20:01:00Z'
    else:
        monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'yfinance', lambda *a: valid_bars()[:-1])
    with dataflow_context(config):
        snapshot = prepare_research_snapshot(resolution, cutoff, SourceStore(tmp_path / 'sources'), run_id='failed')
    assert snapshot.availability['can_recommend'] is False
    assert snapshot.availability['ai_analysis_performed'] is False
    assert snapshot.records


def test_unverified_price_adjustment_basis_blocks_required_history(tmp_path, sources, monkeypatch):
    config, cutoff, resolution, *_ = sources
    # Structurally valid prices alone cannot establish their historical units.
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'yfinance', lambda *a: list(valid_bars()))
    with dataflow_context(config):
        snapshot = prepare_research_snapshot(resolution, cutoff, SourceStore(tmp_path / 'sources'), run_id='unknown-units')
    assert not snapshot.availability['can_recommend']
    assert 'price_adjustment_basis_unverified' in snapshot.availability['reason_codes']
