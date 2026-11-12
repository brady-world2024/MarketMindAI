from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from marketmind_ai.dataflows import y_finance as module
from marketmind_ai.dataflows.results import InvalidSourceResponse


def payload(days, *, split=None, currency='USD', symbol='NVDA'):
    timestamps = [int(datetime.fromisoformat(day + 'T13:30:00+00:00').timestamp()) for day in days]
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': currency, 'exchangeTimezoneName': 'America/New_York'},
        'timestamp': timestamps, 'indicators': {'quote': [{'open': [120.] * len(days), 'high': [125.] * len(days),
        'low': [119.] * len(days), 'close': [121.] * len(days), 'volume': [1000] * len(days)}]},
        'events': {'splits': split or {}}}], 'error': None}}


def test_verified_later_split_restores_cutoff_price_units_and_volume(monkeypatch):
    future = payload(['2024-06-07', '2024-06-10', '2024-06-11'], split={
        '1718026200': {'date': 1718026200, 'numerator': 10, 'denominator': 1, 'splitRatio': '10:1'}})
    reader = Mock(side_effect=[payload(['2024-06-07']), future])
    monkeypatch.setattr(module, '_http_json', reader)
    monkeypatch.setattr(module, '_price_retrieval_now', lambda: datetime(2024, 6, 11, 21, tzinfo=timezone.utc))
    bars = module.get_price_history('NVDA', '2024-06-07', 50)
    assert bars[0].close == 1210 and bars[0].volume == 100
    assert bars.price_basis['verified'] is True
    assert bars.price_basis['post_cutoff_split_factor'] == 10
    first_query = parse_qs(urlsplit(reader.call_args_list[0].args[0]).query)
    assert int(first_query['period2'][0]) == int(datetime.fromisoformat('2024-06-08T00:00:00-04:00').timestamp())
    assert first_query['events'] == ['splits']


@pytest.mark.parametrize('damage', ['missing_session', 'identity', 'currency', 'bad_ratio', 'missing_metadata', 'fractional_volume'])
def test_unverifiable_adjustments_do_not_return_usable_prices(monkeypatch, damage):
    historical = payload(['2024-06-07'])
    future = payload(['2024-06-07', '2024-06-10', '2024-06-11'])
    result = future['chart']['result'][0]
    if damage == 'missing_session':
        future = payload(['2024-06-07', '2024-06-11'])
    elif damage == 'identity':
        result['meta']['symbol'] = 'OTHER'
    elif damage == 'currency':
        result['meta']['currency'] = 'EUR'
    elif damage == 'missing_metadata':
        del result['meta']['exchangeTimezoneName']
    else:
        result['events']['splits'] = {'1718026200': {'date': 1718026200, 'numerator': 0 if damage == 'bad_ratio' else 3,
            'denominator': 1, 'splitRatio': '3:1'}}
    monkeypatch.setattr(module, '_http_json', Mock(side_effect=[historical, future]))
    monkeypatch.setattr(module, '_price_retrieval_now', lambda: datetime(2024, 6, 11, 21, tzinfo=timezone.utc))
    with pytest.raises(InvalidSourceResponse):
        module.get_price_history('NVDA', '2024-06-07', 50)


def test_already_effective_split_does_not_change_cutoff_units(monkeypatch):
    future = payload(['2024-06-10', '2024-06-11'], split={'1718026200': {
        'date':1718026200,'numerator':10,'denominator':1,'splitRatio':'10:1'}})
    monkeypatch.setattr(module, '_http_json', Mock(side_effect=[payload(['2024-06-10']), future]))
    monkeypatch.setattr(module, '_price_retrieval_now', lambda: datetime(2024, 6, 11, 21, tzinfo=timezone.utc))
    bars = module.get_price_history('NVDA', '2024-06-10', 50)
    assert bars[0].close == 121
    assert bars.price_basis['post_cutoff_split_factor'] == 1


def test_price_and_action_queries_must_agree_on_the_shared_session(monkeypatch):
    historical = payload(['2024-06-07'])
    verification = payload(['2024-06-07', '2024-06-10', '2024-06-11'])
    verification['chart']['result'][0]['indicators']['quote'][0]['close'][0] = 122
    monkeypatch.setattr(module, '_http_json', Mock(side_effect=[historical, verification]))
    monkeypatch.setattr(module, '_price_retrieval_now', lambda: datetime(2024, 6, 11, 21, tzinfo=timezone.utc))
    with pytest.raises(InvalidSourceResponse):
        module.get_price_history('NVDA', '2024-06-07', 50)
