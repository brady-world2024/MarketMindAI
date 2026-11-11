"""Conservative security classification from registered cover facts and listing flags."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from . import sec_filings as sec
from .results import Serializable, utc_now
from .market_identity import normalize_exchange
from .config import get_audit
from .source_policy import aware_time
from .sec_statements import get_sec_filing_identity

DIRECTORY_BASE = 'https://www.nasdaqtrader.com/dynamic/SymDir/'


@dataclass
class InstrumentEligibility(Serializable):
    symbol: str
    status: str = 'unverified'
    exchange: str | None = None
    security_type: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    source_urls: list[str] = field(default_factory=list)
    retrieved_at: Any = field(default_factory=utc_now)


class _CoverParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = {}
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        name = attrs.get('name', tag).lower().split(':')[-1]
        context = attrs.get('contextref')
        key = (context, name) if context and name in {'tradingsymbol', 'security12btitle', 'securityexchangename'} else None
        self.stack.append([tag, key, []])

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_data(self, data):
        for _, key, parts in self.stack:
            if key:
                parts.append(data)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _, key, parts in self.stack[i:]:
                    if key:
                        text = ' '.join(''.join(parts).split())
                        self.facts.setdefault(key, set()).add(text)
                del self.stack[i:]
                return


def parse_cover_securities(html: str) -> list[dict]:
    parser = _CoverParser()
    parser.feed(html)
    rows = []
    for context in {key[0] for key in parser.facts}:
        fields = {name: parser.facts.get((context, name), set()) for name in
                  ('tradingsymbol', 'security12btitle', 'securityexchangename')}
        if not all(len(values) == 1 for values in fields.values()):
            continue
        rows.append({'context': context, 'symbol': next(iter(fields['tradingsymbol'])),
                     'title': next(iter(fields['security12btitle'])),
                     'exchange': next(iter(fields['securityexchangename']))})
    return rows


def _exchange(value: str) -> str:
    return normalize_exchange(value)


def classify_instrument(symbol: str, securities: list[dict], directory: dict) -> InstrumentEligibility:
    result = InstrumentEligibility(symbol=symbol.upper(), metadata={'securities': securities, 'directory': directory})
    matches = [row for row in securities if str(row.get('symbol', '')).upper() == symbol.upper()]
    signatures = {(row.get('title'), row.get('exchange')) for row in matches}
    if len(signatures) != 1:
        result.reason_codes = ['security_context_unverified']
        return result
    row = matches[0]
    result.exchange = _exchange(row['exchange'])
    title = row['title'].lower()
    if re.search(r'depositary|depository|\badr\b|\bads\b', title):
        result.security_type = 'ADR'
    elif re.search(r'preferred|preference|warrant|\bunits?\b|\brights?\b|\bnotes?\b|bonds?|debentures?', title):
        result.security_type = 'other'
    elif re.search(r'common\s+(stock|shares)|ordinary\s+shares', title):
        result.security_type = 'common_stock'
    if result.exchange not in {'NYSE', 'NASDAQ'}:
        result.status, result.reason_codes = 'unsupported', ['unsupported_exchange']
    elif result.security_type in {'ADR', 'other'}:
        result.status, result.reason_codes = 'unsupported', ['unsupported_security_type']
    elif result.security_type is None:
        result.reason_codes = ['security_type_unverified']
    elif str(directory.get('symbol', '')).upper() != symbol.upper():
        result.reason_codes = ['listing_flags_unverified']
    elif directory.get('ETF') == 'Y' or directory.get('Test Issue') == 'Y':
        result.status, result.reason_codes = 'unsupported', ['etf_or_test_issue']
    elif directory.get('ETF') != 'N' or directory.get('Test Issue') != 'N':
        result.reason_codes = ['listing_flags_unverified']
    elif directory.get('Exchange') and directory['Exchange'] != 'N':
        result.status, result.reason_codes = 'unsupported', ['unsupported_exchange']
    else:
        result.status = 'supported'
    return result


def get_instrument_metadata(symbol: str, analysis_date: str) -> InstrumentEligibility:
    cik = sec._lookup_cik(symbol)
    if cik is None:
        return InstrumentEligibility(symbol=symbol, reason_codes=['sec_security_not_found'], provider='sec')
    url = sec.SEC_SUBMISSIONS_URL.format(cik=cik)
    recent = (sec._sec_get_json(url).get('filings') or {}).get('recent') or {}
    filings = sorted((dict(zip(('form', 'date', 'accession', 'document'), values), published_at=(
        recent.get('acceptanceDateTime', [])[index] if index < len(recent.get('acceptanceDateTime', [])) else None))
        for index, values in enumerate(zip(
        recent.get('form', []), recent.get('filingDate', []), recent.get('accessionNumber', []),
        recent.get('primaryDocument', []))) if values[0] in {'10-K', '10-Q', '20-F', '40-F'} and values[1] <= analysis_date),
        key=lambda item: item['date'], reverse=True)
    audit = get_audit()
    cutoff = aware_time(audit.cutoff_at) if audit and audit.cutoff_at else None
    if cutoff:
        filings = [filing for filing in filings if aware_time(filing['published_at']) is not None and aware_time(filing['published_at']) <= cutoff]
        filings.sort(key=lambda filing: aware_time(filing['published_at']), reverse=True)
    historical = None
    if not filings and cutoff:
        historical = get_sec_filing_identity(symbol, cutoff)
        if not historical.reason_codes and historical.primary_document_url:
            filings = [{'form': historical.form, 'date': historical.published_at[:10],
                        'accession': historical.accession, 'document': historical.primary_document_url.rsplit('/', 1)[-1],
                        'published_at': historical.published_at}]
            cik = historical.cik
    if not filings:
        return InstrumentEligibility(symbol=symbol, reason_codes=['registered_cover_unavailable'], provider='sec', source_urls=[url])
    filing = filings[0]
    cover_url = sec.SEC_ARCHIVE_URL.format(cik_int=int(cik), accession=filing['accession'].replace('-', ''), document=filing['document'])
    rows = parse_cover_securities(sec._sec_get_text(cover_url))
    target = [row for row in rows if row['symbol'].upper() == symbol.upper()]
    directory = {}
    urls = [url, cover_url]
    if target and _exchange(target[0]['exchange']) in {'NASDAQ', 'NYSE'}:
        filename = 'nasdaqlisted.txt' if _exchange(target[0]['exchange']) == 'NASDAQ' else 'otherlisted.txt'
        directory_url = DIRECTORY_BASE + filename
        urls.append(directory_url)
        for row in csv.DictReader(io.StringIO(sec._sec_get_text(directory_url)), delimiter='|'):
            # Other-listed uses ACT Symbol; aliases are not guessed across share classes.
            identifier = row.get('Symbol') or row.get('ACT Symbol')
            if identifier and identifier.upper() == symbol.upper():
                directory = dict(row, symbol=identifier)
                break
    result = classify_instrument(symbol, rows, directory)
    result.metadata['cik'] = cik
    accepted = aware_time(filing.get('published_at'))
    result.metadata['published_at'] = accepted.isoformat() if accepted else None
    result.metadata['directory_public_time_verified'] = False
    result.metadata['directory_role'] = 'current_listing_veto_only'
    result.provider, result.source_urls = 'sec', urls
    return result


def get_demo_instrument_metadata(symbol: str, analysis_date: str) -> InstrumentEligibility:
    from .offline import _FIXTURES
    if symbol.upper() not in _FIXTURES:
        return InstrumentEligibility(symbol=symbol, reason_codes=['demo_security_not_defined'], provider='offline')
    return InstrumentEligibility(symbol=symbol.upper(), status='supported', exchange='NASDAQ',
                                 security_type='common_stock', provider='offline', metadata={'fixture': True})
