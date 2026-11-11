from datetime import datetime, timezone

import pytest

from marketmind_ai.dataflows.research_cutoff import CutoffUnavailableError, resolve_research_cutoff


@pytest.mark.parametrize('requested,expected,close', [
    ('2026-06-12', '2026-06-12', '2026-06-12T20:00:00+00:00'),
    ('2026-06-13', '2026-06-12', '2026-06-12T20:00:00+00:00'),
    ('2026-11-26', '2026-11-25', '2026-11-25T21:00:00+00:00'),
    ('2026-11-28', '2026-11-27', '2026-11-27T18:00:00+00:00'),
    ('2026-03-06', '2026-03-06', '2026-03-06T21:00:00+00:00'),
    ('2026-03-09', '2026-03-09', '2026-03-09T20:00:00+00:00'),
])
def test_real_market_sessions_and_close(requested, expected, close):
    result = resolve_research_cutoff(requested, now=datetime(2026, 12, 30, 23, tzinfo=timezone.utc))
    assert result.effective_session_date == expected
    assert result.cutoff_at == close
    assert result.requested_date == requested
    assert result.market_timezone == 'America/New_York'
    assert result.calendar_version


def test_unfinished_session_is_not_eligible():
    result = resolve_research_cutoff('2026-06-12', now=datetime(2026, 6, 12, 17, tzinfo=timezone.utc))
    assert result.effective_session_date == '2026-06-11'
    assert resolve_research_cutoff('2026-06-12', now=datetime(2026, 6, 12, 20, tzinfo=timezone.utc)).effective_session_date == '2026-06-12'


def test_cutoff_requires_aware_now_and_valid_calendar_date():
    with pytest.raises(CutoffUnavailableError):
        resolve_research_cutoff('2026-06-12', now=datetime(2026, 6, 12))
    with pytest.raises(CutoffUnavailableError):
        resolve_research_cutoff('not-a-date')
    with pytest.raises(CutoffUnavailableError):
        resolve_research_cutoff('1600-01-01')
