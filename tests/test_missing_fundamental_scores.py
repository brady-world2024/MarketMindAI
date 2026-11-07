from marketmind_ai.agents.utils.agent_utils import compute_market_snapshot, score_bundle
from marketmind_ai.agents.utils.research_types import FundamentalSnapshot, ResearchBundle
from test_data_preflight import bars


def test_missing_ratios_do_not_receive_zero_debt_bonus_or_zero_margin_penalty():
    bundle = ResearchBundle(None, compute_market_snapshot(bars(50)), FundamentalSnapshot('ABC'), [], [], 0, 'test')
    assert score_bundle(bundle)['fundamentals'] == 0
    bundle.fundamentals.debt_to_equity = 0
    assert score_bundle(bundle)['fundamentals'] == 8
    bundle.fundamentals.operating_margin = 0
    assert score_bundle(bundle)['fundamentals'] == 2


def test_missing_news_and_overview_do_not_become_fact_evidence():
    from marketmind_ai.graph.runtime_support import AutonomousRuntime
    from marketmind_ai.graph.request import AnalysisRequest
    bundle = ResearchBundle(None, compute_market_snapshot(bars(50)), FundamentalSnapshot('ABC'), [], [], 0, 'yfinance')
    runtime = AutonomousRuntime(AnalysisRequest('ABC', '2026-06-12'), {'resolved_symbol': 'ABC'}, None, None, None)
    runtime.bundle = lambda: bundle
    evidence = runtime.evidence_pack()
    assert [item.source_type for item in evidence] == ['price']


def test_absent_ratios_render_as_missing_in_both_languages():
    from marketmind_ai.graph.offline_reports import fundamentals_report, bull_bear_lists
    bundle = ResearchBundle(None, compute_market_snapshot(bars(50)), FundamentalSnapshot('ABC'), [], [], 0, 'test')
    for language in ('English', 'Chinese'):
        report = fundamentals_report(bundle, 0, language)
        assert 'n/a / n/a' in report
        assert '0.00 / 0.00' not in report
    assert 'n/a' in bull_bear_lists({'market': 0}, bundle, 'English')[1][0]
    bundle.fundamentals.trailing_pe = 0
    assert '0.0 / n/a' in fundamentals_report(bundle, 0, 'English')
