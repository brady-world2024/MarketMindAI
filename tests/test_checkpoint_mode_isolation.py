from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import Mock

import pytest
from langgraph.graph import END, StateGraph

from marketmind_ai.dataflows.config import get_config, get_audit
from marketmind_ai.dataflows.source_records import ResearchDataSnapshot
from marketmind_ai.dataflows.research_snapshot import bind_frozen_snapshot
from marketmind_ai.dataflows.preflight import DataAvailability
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.symbols import SymbolResolution


def test_interrupted_demo_checkpoint_cannot_enter_live_run(tmp_path, monkeypatch):
    class State(TypedDict):
        market_report: str
        sender: str

    starts = []
    should_fail = [True]

    class Engine:
        def __init__(self, request, **kwargs):
            self.request = request
            self.models = SimpleNamespace(quick=Mock())
        def initial_state(self):
            return {}
        def build_graph(self):
            def analyst(state):
                starts.append(self.request.llm_provider)
                return {'market_report': f'{self.request.llm_provider} market report', 'sender': 'Market Analyst'}
            def finish(state):
                if should_fail[0]:
                    raise RuntimeError('Interrupted demo')
                return {}
            graph = StateGraph(State)
            graph.add_node('analyst', analyst)
            graph.add_node('finish', finish)
            graph.set_entry_point('analyst')
            graph.add_edge('analyst', 'finish')
            graph.add_edge('finish', END)
            return graph

    graph = MarketMindGraph(storage_root=tmp_path)
    monkeypatch.setattr(graph.resolver, 'resolve_identity', lambda *a: SymbolResolution(
        status='RESOLVED', original_input='ABC', normalized_query='ABC', resolved_symbol='ABC'))
    saved = []
    def prepare(resolution, cutoff, store, *, run_id, **kwargs):
        data = ResearchDataSnapshot(origin_run_id=run_id, original_input='ABC', symbol='ABC',
            data_mode=get_config()['data_mode'], cutoff=cutoff.to_dict(), resolution=resolution.to_dict(),
            availability=DataAvailability(get_config()['data_mode'], can_recommend=True).to_dict())
        store.save(data)
        bind_frozen_snapshot(data, get_audit())
        saved.append(data)
        return data
    monkeypatch.setattr('marketmind_ai.graph.marketmind_graph.prepare_research_snapshot', prepare)
    monkeypatch.setattr('marketmind_ai.graph.marketmind_graph.GraphResearchEngine', Engine)
    with pytest.raises(RuntimeError, match='Interrupted demo'):
        list(graph.stream(AnalysisRequest('ABC', '2026-06-12', llm_provider='offline', checkpoint_enabled=True), run_id='demo-run'))
    should_fail[0] = False
    final = list(graph.stream(AnalysisRequest('ABC', '2026-06-12', checkpoint_enabled=True), run_id='live-run'))[-1]
    assert final.data_mode == 'live'
    assert next(report.content for report in final.reports if report.key == 'market_report') == 'openai market report'
    assert starts == ['offline', 'openai']
    # Explicitly replaying the same inputs preserves the interrupted run checkpoint.
    list(graph.stream(AnalysisRequest('ABC', '2026-06-12', llm_provider='offline', checkpoint_enabled=True,
        snapshot_id=saved[0].snapshot_id), run_id='demo-run'))
    assert starts == ['offline', 'openai']
