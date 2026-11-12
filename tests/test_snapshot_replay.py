from unittest.mock import Mock

import pytest

from marketmind_ai.dataflows.interface import VENDOR_METHODS
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest


def request(**kwargs):
    return AnalysisRequest('NVDA', '2026-06-13', llm_provider='offline', **kwargs)


def test_completed_run_and_replay_share_immutable_inputs_without_any_source_call(tmp_path, monkeypatch):
    graph = MarketMindGraph(storage_root=tmp_path)
    first = list(graph.stream(request(), run_id='original'))[-1].to_dict()
    assert first['research_cutoff']['effective_session_date'] == '2026-06-12'
    assert first['data_availability']['can_recommend']
    saved = first['data_snapshot']
    blocked = []
    for methods in VENDOR_METHODS.values():
        for provider in methods:
            spy = Mock(side_effect=AssertionError('Saved replay must not fetch sources'))
            monkeypatch.setitem(methods, provider, spy)
            blocked.append(spy)
    repeated = list(graph.stream(request(snapshot_id=saved['snapshot_id']), run_id='replayed'))[-1].to_dict()
    assert repeated['data_snapshot']['snapshot_id'] == saved['snapshot_id']
    assert repeated['data_snapshot']['manifest_sha256'] == saved['manifest_sha256']
    assert repeated['source_records'] == first['source_records']
    assert repeated['run_id'] != first['run_id']
    assert repeated['status'] == 'completed'
    assert sum(spy.call_count for spy in blocked) == 0


def test_replay_rejects_different_identity_date_or_mode(tmp_path):
    graph = MarketMindGraph(storage_root=tmp_path)
    first = list(graph.stream(request(), run_id='origin'))[-1].to_dict()
    identifier = first['data_snapshot']['snapshot_id']
    for payload in [AnalysisRequest('AAPL', '2026-06-13', llm_provider='offline', snapshot_id=identifier),
                    AnalysisRequest('NVDA', '2026-06-12', llm_provider='offline', snapshot_id=identifier),
                    AnalysisRequest('NVDA', '2026-06-13', llm_provider='openai', snapshot_id=identifier)]:
        with pytest.raises(ValueError):
            list(graph.stream(payload))


def test_review_revision_defaults_to_the_reviewed_data_snapshot(tmp_path):
    graph = MarketMindGraph(storage_root=tmp_path)
    first = list(graph.stream(request(), run_id='review-origin'))[-1].to_dict()
    review = first['review']
    graph.reviews.decide('review-origin', decision='request_changes', version=review['version'],
        report_hash=review['report_hash'], reviewer='Reviewer', comment='Explain evidence gaps')
    _, payload = graph.reviews.reserve_revision('review-origin', version=review['version'], report_hash=review['report_hash'])
    assert payload['snapshot_id'] == first['data_snapshot']['snapshot_id']
