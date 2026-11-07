from unittest.mock import Mock

import pytest

from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.dataflows.instrument_metadata import InstrumentEligibility
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.web.models import RunSnapshot
from marketmind_ai.web.report_export import render_report_html
from test_data_preflight import bars


@pytest.fixture
def unavailable_workflow(tmp_path, monkeypatch):
    monkeypatch.setitem(VENDOR_METHODS['search_symbols'], 'yfinance', lambda *a, **k: [
        {'symbol': 'ABC', 'name': 'ABC Incorporated', 'provider': 'yfinance', 'type': 'EQUITY'}])
    monkeypatch.setitem(VENDOR_METHODS['get_instrument_metadata'], 'sec', lambda *a: InstrumentEligibility(
        symbol='ABC', status='supported', exchange='NYSE', security_type='common_stock', provider='sec'))
    monkeypatch.setitem(VENDOR_METHODS['get_price_history'], 'yfinance', lambda *a: bars(50))
    for method in ('get_income_statement', 'get_balance_sheet', 'get_fundamentals', 'get_news'):
        monkeypatch.setitem(VENDOR_METHODS[method], 'yfinance', lambda *a: None)
    monkeypatch.setitem(VENDOR_METHODS['get_cashflow'], 'yfinance', lambda *a: 'Fiscal period 2025-12-31\nCashflow: 0')
    workflow = MarketMindGraph(storage_root=tmp_path)
    engine = Mock(side_effect=AssertionError('No model or graph engine may be constructed'))
    monkeypatch.setattr('marketmind_ai.graph.marketmind_graph.GraphResearchEngine', engine)
    return workflow, engine


def test_missing_required_data_without_api_key_saves_nonactionable_materials(unavailable_workflow):
    workflow, engine = unavailable_workflow
    request = AnalysisRequest(ticker='ABC', analysis_date='2026-06-12', api_key='', analysts=['news'])
    snapshots = list(workflow.stream(request, run_id='partial-example'))
    final = snapshots[-1].to_dict()
    engine.assert_not_called()
    assert final['status'] == 'completed'
    assert final['data_mode'] == 'live'
    assert final['data_availability']['can_recommend'] is False
    assert final['final_signal'] == 'No Recommendation'
    decision = final['final_structured_decision']
    assert decision['rating'] is None and decision['confidence'] is None and decision['price_target'] is None
    assert final['data_availability']['ai_analysis_performed'] is False
    assert final['source_attempts'] and final['source_materials']
    assert workflow.reviews.load('partial-example')['source_materials'] == final['source_materials']
    assert RunSnapshot.model_validate(final).model_dump()['data_mode'] == 'live'
    exported = render_report_html(final)
    assert 'income_statement' in exported and 'get_cashflow' in exported
    assert 'No AI analysis' in exported
    review = final['review']
    approved = workflow.reviews.decide('partial-example', decision='approve', version=review['version'],
                                     report_hash=review['report_hash'], reviewer='Tester')
    assert approved['final_signal'] == 'No Recommendation'


def test_review_cannot_approve_actionable_when_required_data_failed():
    assert MarketMindGraph.__name__
    from marketmind_ai.graph.review import ReviewStore
    assert ReviewStore._approval_blocked({'data_availability': {'can_recommend': False},
        'final_structured_decision': {'decision_status': 'actionable', 'rating': 'Buy'},
        'final_signal': 'Buy', 'final_decision': 'Final Rating: Buy', 'report_verification': {'status': 'passed'},
        'report_quality': {'score': 100}})


def test_interleaved_generators_reset_context_and_keep_audit_isolated(unavailable_workflow):
    from marketmind_ai.dataflows.config import get_audit, get_config
    workflow, _ = unavailable_workflow
    previous = get_config()
    live = workflow.stream(AnalysisRequest('ABC', '2026-06-12'), run_id='live-isolated')
    demo = workflow.stream(AnalysisRequest('UNKNOWN', '2026-06-12', llm_provider='offline'), run_id='demo-isolated')
    next(live)
    assert get_config() == previous and get_audit() is None
    next(demo)
    live_result = next(live).to_dict()
    demo_result = next(demo).to_dict()
    assert live_result['data_mode'] == 'live' and demo_result['data_mode'] == 'demo'
    assert all(item['run_id'] == 'live-isolated' and item['provider'] != 'offline' for item in live_result['source_attempts'])
    assert all(item['run_id'] == 'demo-isolated' and item['provider'] == 'offline' for item in demo_result['source_attempts'])
    assert get_config() == previous and get_audit() is None
    live.close()
    demo.close()


def test_api_retains_partial_result_and_exports_it_without_api_key(unavailable_workflow, monkeypatch):
    from fastapi.testclient import TestClient
    from marketmind_ai.web.app import create_app
    workflow, engine = unavailable_workflow

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)

    monkeypatch.setattr('marketmind_ai.web.app.AnalysisThread', ImmediateThread)
    client = TestClient(create_app(str(workflow.paths.root)))
    created = client.post('/api/runs', json={'ticker': 'ABC', 'analysis_date': '2026-06-12',
        'llm_provider': 'openai', 'quick_model': 'gpt-5.4-mini', 'deep_model': 'gpt-5.4', 'analysts': ['market'], 'api_key': None})
    assert created.status_code == 200, created.text
    result = client.get(created.json()['result_url'])
    assert result.status_code == 200
    assert result.json()['data_availability']['ai_analysis_performed'] is False
    assert 'No AI analysis' in client.get(created.json()['report_url']).text
    engine.assert_not_called()


def test_model_setup_failure_retains_completed_preflight_materials(unavailable_workflow, monkeypatch):
    workflow, engine = unavailable_workflow
    for method in ('get_income_statement', 'get_balance_sheet'):
        monkeypatch.setitem(VENDOR_METHODS[method], 'yfinance', lambda *a: 'Fiscal period 2025-12-31\nRevenue: 0')
    engine.side_effect = ValueError('Missing credentials')
    snapshots = []
    with pytest.raises(ValueError, match='AI connection could not be initialized'):
        for snapshot in workflow.stream(AnalysisRequest('ABC', '2026-06-12'), run_id='auth-failure'):
            snapshots.append(snapshot.to_dict())
    final = snapshots[-1]
    assert final['source_materials']
    assert final['data_availability']['can_recommend']
    assert final['data_availability']['ai_analysis_performed'] is False
    assert final['status'] == 'error'
    assert workflow.archive.load('auth-failure')['source_materials'] == final['source_materials']
