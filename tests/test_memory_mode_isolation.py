from unittest.mock import Mock

from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest


def approve(graph, snapshot):
    review = snapshot['review']
    return graph.reviews.decide(snapshot['run_id'], decision='approve', reviewer='Reviewer',
                               version=review['version'], report_hash=review['report_hash'])


def test_approved_demo_and_unknown_history_stays_out_of_live_research(tmp_path):
    import json
    graph = MarketMindGraph(storage_root=tmp_path)
    snapshot = list(graph.stream(AnalysisRequest('NVDA', '2026-06-12', llm_provider='offline'), run_id='demo-memory'))[-1].to_dict()
    approve(graph, snapshot)
    graph.memory_log.store_decision('NVDA', '2026-06-01', 'Final Rating: Buy\nLegacy unverified decision')
    reports = graph.paths.results_dir / 'NVDA' / 'MarketMindStrategy_logs'
    reports.mkdir(parents=True, exist_ok=True)
    (reports / 'full_states_log_2026-06-01.json').write_text(json.dumps({
        'trade_date': '2026-06-01', 'market_report': 'UNKNOWN MODE LEGACY REPORT'}))
    assert len(graph.journal.recall('NVDA')) == 2
    with dataflow_context({'data_mode': 'live'}):
        assert graph.journal.recall('NVDA') == []
        assert graph.memory_log.approved_states() == []
        assert all(not item for item in graph.memory_retriever.build_contexts('NVDA', '2026-07-01').values())
        assert graph.outcome_evaluator.build_summary()['total_entries'] == 0
        quick = Mock()
        graph.pending_outcomes.resolve_for_ticker('NVDA', '2026-07-01', quick)
        quick.invoke.assert_not_called()
    with dataflow_context({'data_mode': 'demo'}):
        assert len(graph.journal.recall('NVDA')) == 1
        assert graph.memory_log.approved_states()
    assert len(graph.memory_log.load_entries()) == 2


def test_approving_partial_report_does_not_break_later_report_retrieval(tmp_path):
    graph = MarketMindGraph(storage_root=tmp_path)
    partial = list(graph.stream(AnalysisRequest('UNKNOWN', '2026-06-12', llm_provider='offline'), run_id='partial-memory'))[-1].to_dict()
    approve(graph, partial)
    contexts = graph.memory_retriever.build_contexts('NVDA', '2026-07-01')
    assert all(not text for text in contexts.values())
    final = list(graph.stream(AnalysisRequest('NVDA', '2026-06-12', llm_provider='offline'), run_id='after-partial'))[-1]
    assert final.status == 'completed'
    assert final.data_availability['ai_analysis_performed']
