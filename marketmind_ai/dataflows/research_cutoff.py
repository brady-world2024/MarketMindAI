"""Resolve a research date to a completed US cash-equity session."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version
from zoneinfo import ZoneInfo

import exchange_calendars as calendars
import pandas as pd

from .results import Serializable

NEW_YORK = ZoneInfo('America/New_York')


class CutoffUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchCutoff(Serializable):
    requested_date: str
    effective_session_date: str
    cutoff_at: str
    cutoff_at_local: str
    computed_at: str
    market_timezone: str = 'America/New_York'
    calendar_id: str = 'XNYS'
    calendar_version: str = ''


def resolve_research_cutoff(requested_date: str, *, now: datetime | None = None) -> ResearchCutoff:
    try:
        requested = date.fromisoformat(requested_date)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError('An aware clock is required.')
        current = current.astimezone(timezone.utc)
        upper = min(requested, current.astimezone(NEW_YORK).date())
        calendar = calendars.get_calendar('XNYS', start=upper - timedelta(days=366), end=upper + timedelta(days=1))
        schedule = calendar.schedule
        eligible = schedule[(schedule.index.date <= upper) & (schedule['close'] <= pd.Timestamp(current))]
        if eligible.empty:
            raise ValueError('No completed session is verifiable.')
        session = eligible.index[-1].date().isoformat()
        close = eligible.iloc[-1]['close'].to_pydatetime().astimezone(timezone.utc)
        return ResearchCutoff(requested.isoformat(), session, close.isoformat(), close.astimezone(NEW_YORK).isoformat(),
                              current.isoformat(), calendar_version=version('exchange_calendars'))
    except Exception:
        raise CutoffUnavailableError('The requested market-close cutoff could not be verified.') from None
