import pytest

from marketmind_ai.dataflows.instrument_metadata import classify_instrument, parse_cover_securities


def cover(*rows):
    return '<html>' + ''.join(
        f'<ix:nonNumeric name="dei:{field}" contextRef="{context}">{value}</ix:nonNumeric>'
        for context, field, value in rows
    ) + '</html>'


def test_cover_facts_match_same_security_context():
    html = cover(('common', 'TradingSymbol', 'ABC'), ('common', 'Security12bTitle', 'Common Stock'),
                 ('common', 'SecurityExchangeName', 'NASDAQ'),
                 ('preferred', 'TradingSymbol', 'ABC-P'), ('preferred', 'Security12bTitle', 'Preferred Stock'),
                 ('preferred', 'SecurityExchangeName', 'NYSE'))
    rows = parse_cover_securities(html)
    assert classify_instrument('ABC', rows, {'symbol': 'ABC', 'ETF': 'N', 'Test Issue': 'N'}).status == 'supported'
    assert classify_instrument('ABC-P', rows, {'symbol': 'ABC-P', 'ETF': 'N', 'Test Issue': 'N'}).status == 'unsupported'
    assert classify_instrument('MISSING', rows, {}).status == 'unverified'


@pytest.mark.parametrize('title,exchange,flag,status', [
    ('Common Stock', 'NYSE', 'N', 'supported'),
    ('Class A Ordinary Shares', 'The Nasdaq Stock Market LLC', 'N', 'supported'),
    # Exact registered exchange text returned by NVDA's SEC cover, live smoke.
    ('Common Stock, $0.001 par value per share', 'The Nasdaq Global Select Market', 'N', 'supported'),
    ('American Depositary Shares', 'NASDAQ', 'N', 'unsupported'),
    ('Common Stock', 'NYSE American', 'N', 'unsupported'),
    ('Common Stock', 'NASDAQ', 'Y', 'unsupported'),
    ('EQUITY', 'NASDAQ', 'N', 'unverified'),
    ('Common Stock', 'NASDAQ', '', 'unverified'),
])
def test_explicit_security_and_exchange_boundaries(title, exchange, flag, status):
    rows = [{'symbol': 'ABC', 'title': title, 'exchange': exchange, 'context': 'x'}]
    assert classify_instrument('ABC', rows, {'symbol': 'ABC', 'ETF': flag, 'Test Issue': 'N'}).status == status


def test_common_stock_of_other_share_class_cannot_verify_target():
    html = cover(('a', 'TradingSymbol', 'ABC'), ('b', 'Security12bTitle', 'Common Stock'),
                 ('b', 'SecurityExchangeName', 'NASDAQ'))
    assert classify_instrument('ABC', parse_cover_securities(html), {}).status == 'unverified'


def test_conflicting_cover_facts_are_not_selected_arbitrarily():
    html = cover(('x', 'TradingSymbol', 'ABC'), ('x', 'Security12bTitle', 'Common Stock'),
                 ('x', 'Security12bTitle', 'Preferred Stock'), ('x', 'SecurityExchangeName', 'NASDAQ'))
    assert classify_instrument('ABC', parse_cover_securities(html), {}).status == 'unverified'
