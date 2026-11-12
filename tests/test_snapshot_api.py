from unittest.mock import Mock

from fastapi.testclient import TestClient

from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.dataflows.source_store import SourceStore
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.web.app import create_app


def test_api_replays_without_symbol_network_and_serves_only_safe_verified_sources(tmp_path, monkeypatch):
    graph = MarketMindGraph(storage_root=tmp_path)
    first = list(graph.stream(AnalysisRequest('NVDA', '2026-06-13', llm_provider='offline'), run_id='saved'))[-1].to_dict()
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

    monkeypatch.setattr('marketmind_ai.web.app.AnalysisThread', ImmediateThread)
    client = TestClient(create_app(str(tmp_path)))
    payload = {'ticker': 'NVDA', 'analysis_date': '2026-06-13', 'llm_provider': 'offline',
               'quick_model': 'offline-draft', 'deep_model': 'offline-reasoner', 'snapshot_id': identifier}
    response = client.post('/api/runs', json=payload)
    assert response.status_code == 200, response.text
    result = client.get(response.json()['result_url']).json()
    assert result['data_snapshot'] == first['data_snapshot']
    assert result['status'] == 'completed'
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
