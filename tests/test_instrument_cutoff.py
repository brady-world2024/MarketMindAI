from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.dataflows.instrument_metadata import get_instrument_metadata


def test_security_cover_cannot_come_from_an_after_close_filing(monkeypatch):
    from marketmind_ai.dataflows import instrument_metadata as module
    monkeypatch.setattr(module.sec, '_lookup_cik', lambda *a: '0000000001')
    monkeypatch.setattr(module.sec, '_sec_get_json', lambda *a: {'filings': {'recent': {
        'form': ['10-Q', '10-Q'], 'filingDate': ['2026-06-12', '2026-06-12'],
        'accessionNumber': ['0000000001-26-000002', '0000000001-26-000001'],
        'primaryDocument': ['future.htm', 'known.htm'],
        'acceptanceDateTime': ['2026-06-12T20:01:00Z', '2026-06-12T19:59:00Z']}}})
    requested = []
    def text(url):
        requested.append(url)
        if url.endswith('nasdaqlisted.txt'):
            return 'Symbol|ETF|Test Issue\nABC|N|N\n'
        assert url.endswith('known.htm'), 'Future security cover must not be read'
        return ''.join(f'<ix:nonNumeric name="dei:{field}" contextRef="x">{value}</ix:nonNumeric>' for field, value in [
            ('TradingSymbol', 'ABC'), ('Security12bTitle', 'Common Stock'), ('SecurityExchangeName', 'NASDAQ')])
    monkeypatch.setattr(module.sec, '_sec_get_text', text)
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.cutoff_at = '2026-06-12T20:00:00Z'
        result = get_instrument_metadata('ABC', '2026-06-12')
    assert result.status == 'supported'
    assert result.metadata['cik'] == '0000000001'
    assert result.metadata['published_at'] == '2026-06-12T19:59:00+00:00'


def test_historical_cover_uses_verified_submission_identity_when_recent_is_too_new(monkeypatch):
    from marketmind_ai.dataflows import instrument_metadata as module
    from marketmind_ai.dataflows.sec_statements import SECStatementBundle
    monkeypatch.setattr(module.sec, '_lookup_cik', lambda *a: '0000000001')
    monkeypatch.setattr(module.sec, '_sec_get_json', lambda *a: {'filings': {'recent': {}}})
    header = SECStatementBundle('ABC', cik='0000000001', form='10-Q', accession='0000000001-26-000001',
        published_at='2026-05-01T19:00:00+00:00',
        primary_document_url='https://www.sec.gov/Archives/edgar/data/1/000000000126000001/known.htm')
    monkeypatch.setattr(module, 'get_sec_filing_identity', lambda *a: header)
    requested = []
    def text(url):
        requested.append(url)
        if url.endswith('nasdaqlisted.txt'):
            return 'Symbol|ETF|Test Issue\nABC|N|N\n'
        assert url == header.primary_document_url
        return ''.join(f'<ix:nonNumeric name="dei:{field}" contextRef="x">{value}</ix:nonNumeric>' for field, value in [
            ('TradingSymbol', 'ABC'), ('Security12bTitle', 'Common Stock'), ('SecurityExchangeName', 'NASDAQ')])
    monkeypatch.setattr(module.sec, '_sec_get_text', text)
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.cutoff_at = '2026-06-12T20:00:00Z'
        result = get_instrument_metadata('ABC', '2026-06-12')
    assert result.status == 'supported'
    assert result.metadata['published_at'] == header.published_at
    assert header.primary_document_url in requested
