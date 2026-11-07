"""Research entry requirements, evaluated before any model is constructed."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .config import get_config
from .interface import fetch_from_vendors
from .instrument_metadata import InstrumentEligibility
from .results import DataMode, Serializable, finite_number
from ..agents.utils.research_types import PriceBar

REQUIRED_METHODS = {'price_history': 'get_price_history', 'income_statement': 'get_income_statement',
                    'balance_sheet': 'get_balance_sheet', 'cashflow': 'get_cashflow'}


@dataclass
class DataAvailability(Serializable):
    data_mode: DataMode | str
    can_recommend: bool = False
    ai_analysis_performed: bool = False
    requirements: dict[str, dict] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    instrument: InstrumentEligibility | None = None
    # Runtime values are separate from this serializable availability contract.


def validate_daily_bars(rows: Any, analysis_date: str) -> tuple[list[PriceBar], list[str]]:
    clean, conflicts, reasons = {}, set(), set()
    cutoff = date.fromisoformat(analysis_date)
    for row in rows if isinstance(rows, (list, tuple)) else []:
        try:
            values = row if isinstance(row, dict) else vars(row)
            day = date.fromisoformat(values['date'])
            prices = [values[key] for key in ('open', 'high', 'low', 'close')]
            volume = values['volume']
            if (day > cutoff or not all(finite_number(v) and float(v) > 0 for v in prices)
                    or not finite_number(volume) or float(volume) < 0):
                raise ValueError
            opening, high, low, close = map(float, prices)
            if not (low <= min(opening, close) <= max(opening, close) <= high):
                raise ValueError
            bar = PriceBar(day.isoformat(), opening, high, low, close, float(volume))
            if bar.date in clean and clean[bar.date] != bar:
                conflicts.add(bar.date)
            else:
                clean[bar.date] = bar
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            reasons.add('invalid_price_rows')
    for day in conflicts:
        clean.pop(day, None)
    if conflicts:
        reasons.add('conflicting_price_dates')
    return [clean[day] for day in sorted(clean)], sorted(reasons)


def run_preflight(symbol: str, analysis_date: str) -> DataAvailability:
    mode = get_config().get('data_mode', DataMode.UNKNOWN)
    outcome = DataAvailability(data_mode=mode)
    metadata = fetch_from_vendors('get_instrument_metadata', symbol, analysis_date)
    outcome.instrument = metadata.value if metadata.available and isinstance(metadata.value, InstrumentEligibility) else InstrumentEligibility(
        symbol=symbol, reason_codes=['instrument_metadata_unavailable'])
    supported = outcome.instrument.status == 'supported'
    outcome.requirements['instrument'] = {'required': True, 'available': supported,
                                          'reason_codes': outcome.instrument.reason_codes}
    if not supported:
        outcome.missing = ['instrument']
        outcome.reason_codes = outcome.instrument.reason_codes or ['instrument_unverified']
        return outcome
    for name, method in REQUIRED_METHODS.items():
        args = (symbol, analysis_date, 180) if name == 'price_history' else (symbol,)
        fetched = fetch_from_vendors(method, *args)
        entry = {'required': True, 'available': fetched.available, 'provider': fetched.provider,
                 'reason_codes': [] if fetched.available else [attempt.error_code or attempt.status for attempt in fetched.attempts]}
        if name == 'price_history':
            clean, reasons = validate_daily_bars(fetched.value, analysis_date)
            entry.update(valid_count=len(clean), minimum_count=50,
                         available=fetched.available and len(clean) >= 50 and 'conflicting_price_dates' not in reasons,
                         reason_codes=entry['reason_codes'] + reasons)
            if len(clean) < 50:
                entry['reason_codes'].append('fewer_than_50_valid_daily_bars')
        outcome.requirements[name] = entry
        if not entry['available']:
            outcome.missing.append(name)
            outcome.reason_codes.extend(entry['reason_codes'])
    # Company overview and news are useful retained materials, but not core gates.
    for name, method, args in [('fundamentals', 'get_fundamentals', (symbol,)),
                                ('news', 'get_news', (symbol, analysis_date, 8))]:
        fetched = fetch_from_vendors(method, *args)
        outcome.requirements[name] = {'required': False, 'available': fetched.available,
                                      'provider': fetched.provider, 'reason_codes': [] if fetched.available else ['optional_data_unavailable']}
    outcome.can_recommend = not outcome.missing
    return outcome
