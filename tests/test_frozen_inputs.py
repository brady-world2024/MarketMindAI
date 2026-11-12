from copy import deepcopy

from marketmind_ai.dataflows.frozen_inputs import FrozenInputs
from marketmind_ai.dataflows.source_records import ResearchDataSnapshot


def frozen():
    bars = [{'date': '2026-06-12', 'open': 10, 'high': 12, 'low': 9, 'close': 11, 'volume': 0}]
    snapshot = ResearchDataSnapshot(origin_run_id='original', original_input='ABC', symbol='ABC', data_mode='live',
        cutoff={'requested_date': '2026-06-13', 'effective_session_date': '2026-06-12', 'cutoff_at': '2026-06-12T20:00:00+00:00'},
        resolution={'resolved_symbol': 'ABC'}, availability={}, inputs={
            'get_price_history': {'available': True, 'provider': 'yfinance', 'value': bars},
            'get_news': {'available': True, 'provider': 'yfinance', 'value': [
                {'title': str(i), 'source': 'publisher', 'published_at': '2026-06-12T12:00:00Z'} for i in range(8)]},
            'get_income_statement': {'available': True, 'provider': 'sec', 'value': 'Fiscal period 2026-03-31\nRevenue: 0'},
        })
    return FrozenInputs(snapshot)


def test_frozen_values_rebuild_known_types_and_return_independent_copies():
    inputs = frozen()
    result = inputs.read('get_price_history', 'ABC', '2026-06-13', 180)
    assert result.available and result.value[0].close == 11
    result.value[0].close = 999
    assert inputs.read('get_price_history', 'ABC', '2026-06-12', 180).value[0].close == 11
    assert len(inputs.read('get_news', 'ABC', '2026-06-12', 3).value) == 3
    assert inputs.read('get_income_statement', 'ABC').provider == 'sec'


def test_frozen_lookup_cannot_escape_symbol_date_method_or_indicator_price_basis():
    inputs = frozen()
    for method, args in [('get_price_history', ('OTHER', '2026-06-12', 180)),
                         ('get_news', ('ABC', '2026-06-14', 8)),
                         ('unrecognized_method', ('ABC',))]:
        assert not inputs.read(method, *args).available
    indicator = inputs.read('get_indicators', 'ABC', '2026-06-12', ['close_1_sma', 'close_50_sma'])
    assert indicator.available
    assert '999' not in indicator.value
    assert 'close_50_sma: None' in indicator.value


def test_unavailable_optional_material_is_not_represented_as_success():
    assert not frozen().read('get_insider_transactions', 'ABC', '2026-06-12').available


def test_routing_and_direct_invocation_cannot_fetch_after_freeze(monkeypatch):
    from unittest.mock import Mock
    from marketmind_ai.dataflows.config import dataflow_context
    from marketmind_ai.dataflows.interface import VENDOR_METHODS, fetch_from_vendors, invoke_vendor_method
    source = Mock(side_effect=AssertionError('A frozen input cannot fetch'))
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'yfinance', source)
    with dataflow_context({'data_mode': 'live', 'data_vendors': {'core_stock_apis': 'yfinance'}}) as audit:
        audit.frozen_inputs = frozen()
        assert fetch_from_vendors('get_price_history', 'ABC', '2026-06-12', 180).available
        assert invoke_vendor_method('get_price_history', 'yfinance', 'ABC', '2026-06-12', 180)[0].close == 11
    source.assert_not_called()


def test_frozen_manifest_is_isolated_and_fingerprint_is_not_recomputed(monkeypatch):
    from unittest.mock import Mock
    from marketmind_ai.dataflows import source_store
    original = frozen().snapshot
    fingerprint = Mock(wraps=source_store.snapshot_fingerprint)
    monkeypatch.setattr(source_store, 'snapshot_fingerprint', fingerprint)
    inputs = FrozenInputs(original)
    original.inputs['get_price_history']['value'][0]['close'] = 999
    assert inputs.read('get_price_history', 'ABC', '2026-06-12', 180).value[0].close == 11
    assert inputs.manifest_sha256 == inputs.manifest_sha256
    assert fingerprint.call_count == 1


def test_news_window_cannot_claim_data_before_its_saved_collection_scope():
    base = frozen().snapshot
    documents = [{'title': 'Saved', 'published_at': '2026-06-12T12:00:00Z'}]
    entries = {**base.inputs, 'get_global_news_documents': {'available': True, 'provider': 'yfinance',
        'value': documents, 'window_days': 8}, 'get_news_documents': {'available': True,
        'provider': 'yfinance', 'value': documents, 'window_start': '2026-05-27'}}
    inputs = FrozenInputs(base.model_copy(update={'inputs': entries}))
    assert inputs.read('get_global_news_documents', '2026-06-12', 7, 25).available
    assert not inputs.read('get_global_news_documents', '2026-06-12', 16, 25).available
    assert not inputs.read('get_global_news_documents', '2026-06-12', True, 25).available
    assert not inputs.read('get_news_documents', 'ABC', '2026-05-01', '2026-06-12').available
    assert not inputs.read('get_news_documents', 'ABC', '2026-06-13', '2026-06-12').available
