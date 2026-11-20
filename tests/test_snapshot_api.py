from unittest.mock import Mock

from fastapi.testclient import TestClient

from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.dataflows.source_store import SourceStore
from marketmind_ai.evaluation.reliability import evaluate_reliability
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.web.app import create_app


def test_api_replays_without_symbol_network_and_serves_only_safe_verified_sources(tmp_path, monkeypatch):
    graph = MarketMindGraph(storage_root=tmp_path)
    first = list(graph.stream(AnalysisRequest('NVDA', '2026-06-13', llm_provider='offline',
        research_objective='earnings', research_horizon='1_to_3_months'), run_id='saved'))[-1].to_dict()
    identifier = first['data_snapshot']['snapshot_id']
    spies = []
    for adapters in VENDOR_METHODS.values():
        for provider in adapters:
            spy = Mock(side_effect=AssertionError('Replay cannot call sources'))
            monkeypatch.setitem(adapters, provider, spy)
            spies.append(spy)

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)

    class QueuedThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    payload = {'ticker': 'NVDA', 'analysis_date': '2026-06-13', 'llm_provider': 'offline',
               'research_objective': first['research_objective'], 'research_horizon': first['research_horizon'],
               'quick_model': 'offline-draft', 'deep_model': 'offline-reasoner', 'snapshot_id': identifier}
    monkeypatch.setattr('marketmind_ai.web.app.AnalysisThread', QueuedThread)
    original_client = TestClient(create_app(str(tmp_path)))
    queued = original_client.post('/api/runs', json=payload)
    assert queued.status_code == 200
    monkeypatch.setattr('marketmind_ai.web.app.AnalysisThread', ImmediateThread)
    client = TestClient(create_app(str(tmp_path)))
    recovered = client.get(queued.json()['result_url']).json()
    assert recovered['job_status'] == 'interrupted'
    assert recovered['research_objective'] == 'earnings'
    assert recovered['research_horizon'] == '1_to_3_months'
    parent_id = recovered['run_id']
    recovery = {**payload, 'recovery_of_run_id': parent_id}
    assert original_client.post('/api/runs', json=recovery).status_code == 409
    assert client.post('/api/runs', json={**recovery, 'recovery_of_run_id': '0' * 12}).status_code == 404
    assert client.post('/api/runs', json={**recovery, 'snapshot_id': None}).status_code == 409
    assert client.post('/api/runs', json={**recovery, 'snapshot_id': 'a' * 32}).status_code == 409
    assert client.post('/api/runs', json={**recovery, 'llm_provider': 'openai'}).status_code == 422
    response = client.post('/api/runs', json=recovery)
    assert response.status_code == 200, response.text
    assert response.json()['run_id'] != queued.json()['run_id']
    result = client.get(response.json()['result_url']).json()
    assert result['recovery_of_run_id'] == parent_id
    assert graph.archive.load(result['run_id'])['recovery_of_run_id'] == parent_id
    assert client.get(queued.json()['result_url']).json() == recovered
    assert client.post('/api/runs', json={**recovery, 'recovery_of_run_id': result['run_id']}).status_code == 409
    assert result['data_snapshot'] == first['data_snapshot']
    assert result['status'] == 'completed'
    assert result['research_objective'] == 'earnings'
    assert result['research_horizon'] == '1_to_3_months'
    assert 'Earnings and financial results' in client.get(response.json()['report_url']).text
    metrics = evaluate_reliability([result])['by_data_mode']['demo']['recovery']
    assert metrics['attempts'] == 1
    assert metrics['completion'] == {'completed': 1, 'terminal_runs': 1, 'rate': 1.0}
    review = result['review']
    graph.reviews.decide(result['run_id'], decision='request_changes', version=review['version'],
                         report_hash=review['report_hash'], reviewer='Tester', comment='Review again')
    _, revision = graph.reviews.reserve_revision(result['run_id'], version=review['version'],
                                                  report_hash=review['report_hash'])
    assert 'recovery_of_run_id' not in revision
    assert sum(spy.call_count for spy in spies) == 0
    record = first['source_records'][0]
    raw = client.get(f'/api/snapshots/{identifier}/sources/{record["record_id"]}')
    assert raw.status_code == 200
    assert raw.headers['content-type'].startswith('text/plain')
    assert raw.headers['x-content-type-options'] == 'nosniff'
    assert 'attachment' in raw.headers['content-disposition']
    expected = SourceStore(tmp_path / 'sources').read_blob(record['raw_sha256'])
    assert raw.text == expected
    assert client.get(f'/api/snapshots/{identifier}/sources/missing').status_code == 404
    assert client.post('/api/runs', json={**payload, 'ticker': 'AAPL'}).status_code == 422
    assert client.post('/api/runs', json={**payload, 'snapshot_id': 'a' * 32}).status_code == 422
    path = tmp_path / 'sources' / 'blobs' / record['raw_sha256']
    path.write_bytes(b'<script>tampered</script>')
    assert client.get(f'/api/snapshots/{identifier}/sources/{record["record_id"]}').status_code == 422


def test_queued_recovery_retains_original_run_id_after_another_restart(tmp_path, monkeypatch):
    from marketmind_ai.dataflows.source_records import ResearchDataSnapshot

    class QueuedThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr('marketmind_ai.web.app.AnalysisThread', QueuedThread)
    payload = {'ticker': 'NVDA', 'analysis_date': '2026-06-13', 'llm_provider': 'offline',
               'quick_model': 'heuristic-fast', 'deep_model': 'heuristic-deep'}
    first = TestClient(create_app(str(tmp_path)))
    created = first.post('/api/runs', json=payload).json()
    saved = ResearchDataSnapshot(origin_run_id=created['run_id'], original_input='NVDA',
        symbol='NVDA', data_mode='demo', cutoff={'requested_date': payload['analysis_date']},
        resolution={'status': 'RESOLVED', 'original_input': 'NVDA', 'normalized_query': 'NVDA',
                    'resolved_symbol': 'NVDA'}, availability={})
    SourceStore(tmp_path / 'sources').save(saved)
    restarted = TestClient(create_app(str(tmp_path)))
    response = restarted.post('/api/runs', json={**payload, 'snapshot_id': saved.snapshot_id,
        'recovery_of_run_id': created['run_id']})
    assert response.status_code == 200, response.text
    new_run = response.json()['run_id']
    assert restarted.get(f'/api/runs/{new_run}').json()['recovery_of_run_id'] == created['run_id']
    after_crash = TestClient(create_app(str(tmp_path))).get(f'/api/runs/{new_run}/result').json()
    assert after_crash['job_status'] == 'interrupted'
    assert after_crash['recovery_of_run_id'] == created['run_id']
    assert after_crash['data_snapshot']['snapshot_id'] == saved.snapshot_id
