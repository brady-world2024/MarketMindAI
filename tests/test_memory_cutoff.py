from marketmind_ai.agents.utils.memory import MarketMindMemoryLog
from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.dataflows.source_records import ResearchDataSnapshot
from marketmind_ai.dataflows.source_store import SourceStore, snapshot_fingerprint
from marketmind_ai.graph.review import ReviewStore


def save_prior(root, run_id, *, finished='2026-06-11T19:00:00Z', cutoff='2026-06-10T20:00:00Z', reviewed='2026-06-11T19:01:00Z'):
    source = ResearchDataSnapshot(origin_run_id=run_id, original_input='ABC', symbol='ABC', data_mode='live',
        created_at='2026-06-11T18:00:00Z', cutoff={'requested_date': '2026-06-10', 'cutoff_at': cutoff},
        resolution={'resolved_symbol': 'ABC'}, availability={'can_recommend': False})
    SourceStore(root / 'sources').save(source)
    report = {'run_id': run_id, 'ticker': 'ABC', 'analysis_date': '2026-06-10', 'data_mode': 'live',
        'finished_at': finished, 'research_cutoff': source.cutoff,
        'data_snapshot': {'snapshot_id': source.snapshot_id, 'manifest_sha256': snapshot_fingerprint(source),
                          'policy_version': source.policy_version, 'processing_version': source.processing_version},
        'final_signal': 'No Recommendation', 'final_decision': 'Final Decision Status: No Recommendation',
        'final_structured_decision': {'decision_status': 'No Recommendation'}}
    reviews = ReviewStore(root / 'reviews.sqlite3')
    saved = reviews.save_draft(report, {}, {'company_of_interest': 'ABC', 'trade_date': '2026-06-10', 'market_report': run_id})
    from unittest.mock import patch
    with patch('marketmind_ai.graph.review.utc_now', return_value=reviewed):
        reviews.decide(run_id, decision='approve', reviewer='Reviewer', version=1, report_hash=saved['review']['report_hash'])


def test_future_or_unverified_history_does_not_enter_an_earlier_cutoff(tmp_path):
    save_prior(tmp_path, 'known-before-cutoff')
    save_prior(tmp_path, 'generated-after-cutoff', finished='2026-06-13T12:00:00Z')
    save_prior(tmp_path, 'source-after-cutoff', cutoff='2026-06-13T20:00:00Z')
    log = MarketMindMemoryLog({'review_db_path': str(tmp_path / 'reviews.sqlite3')})
    assert len(log.load_entries()) == 3
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.cutoff_at = '2026-06-12T20:00:00Z'
        assert [row['run_id'] for row in log.load_entries()] == ['known-before-cutoff']
        assert [row['market_report'] for row in log.approved_states()] == ['known-before-cutoff']
    assert len(log.load_entries()) == 3


def test_approval_after_cutoff_cannot_select_historical_memories(tmp_path):
    save_prior(tmp_path, 'late-approved', reviewed='2026-06-13T12:00:00Z')
    log = MarketMindMemoryLog({'review_db_path': str(tmp_path / 'reviews.sqlite3')})
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.cutoff_at = '2026-06-12T20:00:00Z'
        assert log.load_entries() == []
        assert log.approved_states() == []
