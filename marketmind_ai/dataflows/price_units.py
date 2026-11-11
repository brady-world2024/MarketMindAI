"""Verify and reverse Yahoo's post-cutoff split adjustments, without dividends."""
from datetime import datetime, timezone
from fractions import Fraction
import math
from zoneinfo import ZoneInfo

import exchange_calendars as calendars

from ..agents.utils.research_types import PriceBar
from .research_cutoff import resolve_research_cutoff
from .results import InvalidSourceResponse

NEW_YORK = ZoneInfo('America/New_York')


class PriceHistory(list):
    def __init__(self, bars, price_basis):
        super().__init__(bars)
        self.price_basis = price_basis


def chart_result(payload, symbol):
    try:
        chart = payload['chart']
        if chart.get('error') or len(chart['result']) != 1:
            raise ValueError
        result = chart['result'][0]
        meta = result['meta']
        if (meta['symbol'].upper() != symbol.upper() or meta['exchangeTimezoneName'] != 'America/New_York'
                or not isinstance(meta['currency'], str) or len(meta['currency']) != 3):
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError, AttributeError):
        raise InvalidSourceResponse('Price identity and timezone could not be verified.') from None


def chart_bars(result):
    try:
        stamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        if any(len(quote[key]) != len(stamps) for key in ('open', 'high', 'low', 'close', 'volume')):
            raise ValueError
        bars = []
        for index, stamp in enumerate(stamps):
            values = [quote[key][index] for key in ('open', 'high', 'low', 'close', 'volume')]
            if any(value is None for value in values):
                continue
            if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
                raise ValueError
            opening, high, low, close, volume = map(float, values)
            if min(opening, high, low, close) <= 0 or not low <= min(opening, close) <= max(opening, close) <= high or volume < 0 or not volume.is_integer():
                raise ValueError
            day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(NEW_YORK).date().isoformat()
            bars.append(PriceBar(day, opening, high, low, close, int(volume)))
        return bars
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise InvalidSourceResponse('The price series could not be verified.') from None


def restore_cutoff_units(historical, verification, symbol, requested_date, now):
    original = chart_result(historical, symbol)
    checked = chart_result(verification, symbol)
    if original['meta']['currency'] != checked['meta']['currency']:
        raise InvalidSourceResponse('Price currency changed across adjustment verification.')
    cutoff = resolve_research_cutoff(requested_date, now=now)
    current = resolve_research_cutoff(now.astimezone(NEW_YORK).date().isoformat(), now=now)
    original_bars, verification_bars = chart_bars(original), chart_bars(checked)
    # Successful HTTP alone cannot prove a complete action window. Every
    # completed market session must be represented in the queried price series.
    calendar = calendars.get_calendar('XNYS', start=cutoff.effective_session_date, end=current.effective_session_date)
    expected = {day.date().isoformat() for day in calendar.sessions_in_range(cutoff.effective_session_date, current.effective_session_date)}
    actual = [bar.date for bar in verification_bars if bar.date in expected]
    if set(actual) != expected or len(actual) != len(set(actual)):
        raise InvalidSourceResponse('The split verification window is incomplete.')
    original_close = [bar for bar in original_bars if bar.date == cutoff.effective_session_date]
    verified_close = [bar for bar in verification_bars if bar.date == cutoff.effective_session_date]
    if len(original_close) != 1 or len(verified_close) != 1 or original_close[0] != verified_close[0]:
        raise InvalidSourceResponse('The price and split queries disagree on the cutoff session.')
    factor, actions = Fraction(1), []
    try:
        events = checked.get('events', {})
        if not isinstance(events, dict) or not isinstance(events.get('splits', {}), dict):
            raise ValueError
        for key, event in events.get('splits', {}).items():
            if isinstance(event['date'], bool) or int(key) != event['date']:
                raise ValueError
            effective = datetime.fromtimestamp(event['date'], timezone.utc)
            numerator, denominator = Fraction(str(event['numerator'])), Fraction(str(event['denominator']))
            ratio_parts = event['splitRatio'].split(':')
            ratio = numerator / denominator
            if numerator <= 0 or denominator <= 0 or len(ratio_parts) != 2 or ratio != Fraction(ratio_parts[0]) / Fraction(ratio_parts[1]):
                raise ValueError
            if effective > now:
                raise ValueError
            if effective > datetime.fromisoformat(cutoff.cutoff_at):
                factor *= ratio
                actions.append({'effective_at': effective.isoformat(), 'numerator': str(numerator), 'denominator': str(denominator)})
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        raise InvalidSourceResponse('Split adjustment factors could not be verified.') from None
    bars = []
    for bar in original_bars:
        if bar.date > cutoff.effective_session_date:
            continue
        volume = Fraction(bar.volume) / factor
        if volume.denominator != 1:
            raise InvalidSourceResponse('The original volume cannot be restored exactly.')
        values = [float(Fraction(str(getattr(bar, key))) * factor) for key in ('open', 'high', 'low', 'close')]
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise InvalidSourceResponse('Restored price units are invalid.')
        bars.append(PriceBar(bar.date, *values, int(volume)))
    basis = {'verified': True, 'basis': 'cutoff_split_units_no_dividend_adjustment',
        'currency': original['meta']['currency'], 'cutoff_at': cutoff.cutoff_at,
        'verification_through': current.effective_session_date, 'verified_at': now.isoformat(),
        'post_cutoff_split_factor': float(factor), 'post_cutoff_actions': actions}
    return PriceHistory(bars, basis)
