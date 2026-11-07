import pytest
from marketmind_ai.symbols import SymbolResolver


class Provider:
    def __init__(self, exchanges, regions=None):
        self.exchanges = exchanges
        self.regions = regions or ['United States'] * len(exchanges)
    def search_symbols(self, query, limit=8):
        return [{'symbol': 'NVDA', 'name': 'NVIDIA Corporation', 'exchange': exchange,
                 'region': region, 'type': 'EQUITY'} for exchange, region in zip(self.exchanges, self.regions)]


@pytest.mark.parametrize('exchanges', [('NMS', 'NASDAQ'), ('NMS', 'United States')])
def test_same_us_ticker_is_not_ambiguous_due_to_provider_venue_aliases(exchanges):
    assert SymbolResolver(Provider(exchanges)).resolve_identity('NVDA', '2026-06-12').status == 'RESOLVED'


def test_different_known_listing_venues_still_need_confirmation():
    assert SymbolResolver(Provider(('NASDAQ', 'TSX'))).resolve_identity('NVDA', '2026-06-12').status == 'AMBIGUOUS'


def test_yahoo_exchange_display_in_region_does_not_conflict_with_us_country():
    provider = Provider(('NMS', 'United States'), ('NASDAQ', 'United States'))
    assert SymbolResolver(provider).resolve_identity('NVDA', '2026-06-12').status == 'RESOLVED'


def test_failed_identity_sources_return_sanitized_failure_details(monkeypatch):
    from marketmind_ai.dataflows.results import DataUnavailableError, VendorResult, SourceAttempt, utc_now
    failure = VendorResult(status='timeout', attempts=[SourceAttempt('attempt', 'search_symbols', 'yfinance',
        'live', 'timeout', utc_now(), utc_now(), message='The provider request timed out.')])
    def unavailable(*args, **kwargs):
        raise DataUnavailableError(failure)
    resolver = SymbolResolver()
    monkeypatch.setattr(resolver, 'search_symbols', unavailable)
    result = resolver.resolve_identity('NVDA', '2026-06-12')
    assert result.status == 'INSUFFICIENT_DATA'
    assert 'yfinance: timeout' in result.reason
    assert result.source_attempts[0]['status'] == 'timeout'
