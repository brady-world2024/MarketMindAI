from marketmind_ai.dataflows.source_policy import DEFAULT_SOURCE_POLICY, classify_public_time


def test_approved_policy_keeps_core_and_optional_requirements():
    assert DEFAULT_SOURCE_POLICY.minimum_price_bars == 50
    assert DEFAULT_SOURCE_POLICY.required == ('price_history', 'income_statement', 'balance_sheet', 'cashflow')
    assert DEFAULT_SOURCE_POLICY.statement_provider == 'sec'
    assert 'news' not in DEFAULT_SOURCE_POLICY.required


def test_unknown_future_and_date_only_are_not_ai_inputs():
    cutoff = '2026-06-12T20:00:00+00:00'
    assert classify_public_time(None, cutoff) == 'public_time_unverified'
    assert classify_public_time('2026-06-12', cutoff) == 'public_time_unverified'
    assert classify_public_time('2026-06-12T19:00:00', cutoff) == 'public_time_unverified'
    assert classify_public_time('2026-06-12T20:01:00Z', cutoff) == 'published_after_cutoff'
    assert classify_public_time('2026-06-12T15:59:00-04:00', cutoff) is None
    assert classify_public_time(cutoff, cutoff) is None
