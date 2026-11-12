"""Collect and qualify one immutable set of inputs before constructing a model."""
from datetime import date, timedelta
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import exchange_calendars as calendars

from ..agents.utils.research_types import FundamentalSnapshot
from .config import get_audit, get_config
from .frozen_inputs import FrozenInputs
from .interface import fetch_from_vendors
from .preflight import DataAvailability, validate_daily_bars
from .results import SourceAttempt, SourceMaterial, safe_json, utc_now
from .sec_statements import SECStatement, SECStatementBundle, get_sec_statement_bundle
from .source_policy import DEFAULT_SOURCE_POLICY, aware_time, classify_public_time
from .source_records import ResearchDataSnapshot, SourceRecord
from .source_store import SourceStore
from .source_store import SnapshotIntegrityError

KINDS = ('income_statement', 'balance_sheet', 'cashflow')


def _demo_statements(symbol, cutoff):
    bundle = SECStatementBundle(symbol, form='DEMO', period_end=cutoff.effective_session_date,
        published_at=cutoff.cutoff_at, source_url=f'demo://{symbol}/statements', available=True)
    for kind in KINDS:
        value = fetch_from_vendors(f'get_{kind}', symbol)
        if value.available:
            text = value.value
            bundle.statements[kind] = SECStatement(kind, f'Demo {kind}', f'demo://{symbol}/{kind}', text,
                [line.split(':', 1) for line in text.splitlines()], 'USD', ['Synthetic fixture values'],
                cutoff.effective_session_date, 1)
        else:
            bundle.available = False
            bundle.reason_codes.append(f'missing_{kind}')
    return bundle


def _canonical_article(item):
    if item.url:
        parts = urlsplit(item.url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith('utm_')]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ''))
    return (item.source, item.title, item.published_at)


def bind_frozen_snapshot(snapshot, audit):
    audit.frozen_inputs = FrozenInputs(snapshot)
    audit.cutoff_at = snapshot.cutoff['cutoff_at']
    # AI provenance only references admitted values. Inspection views use the
    # manifest's separate retained materials, including exclusions.
    audit.materials = [SourceMaterial(method=r.method, provider=r.provider, data_mode=r.data_mode,
        retrieved_at=aware_time(r.retrieved_at), content=r.content, source_url=r.source_url)
        for r in snapshot.records if r.admissibility == 'included' and r.content is not None]


def prepare_research_snapshot(resolution, cutoff, store: SourceStore, *, run_id: str,
                              memory_contexts=None, memory_entries=None, calibration_summary=None) -> ResearchDataSnapshot:
    audit = get_audit()
    if audit is None or audit.frozen_inputs is not None:
        raise ValueError('Source preparation requires a new run context.')
    audit.cutoff_at = cutoff.cutoff_at
    symbol = resolution.resolved_symbol
    mode = get_config().get('data_mode')
    if mode not in {'live', 'demo'}:
        raise ValueError('Research requires an explicit source mode.')
    availability = DataAvailability(data_mode=mode)
    records, inputs = [], {}

    def record(method, provider, content, *, reason=None, source_url=None, published_at=None,
               public_time_basis=None, raw=None, raw_kind='vendor_object', content_type='application/json', **metadata):
        body = content if raw is None else raw
        digest = store.write_blob(body)
        output = SourceRecord(method=method, provider=provider or 'unknown', symbol=symbol, data_mode=mode,
            publisher=metadata.pop('publisher', provider), source_url=source_url,
            published_at=published_at, time_precision='instant' if aware_time(published_at) else 'unknown',
            public_time_basis=public_time_basis, admissibility='included' if not reason else
            ('unverified' if 'unverified' in reason else 'excluded'), reason_codes=[reason] if reason else [],
            content=safe_json(content), raw_sha256=digest, raw_content_kind='demo' if mode == 'demo' else raw_kind,
            content_type=content_type, **metadata)
        records.append(output)
        return output

    def requirement(name, available, reasons, **extra):
        availability.requirements[name] = {'required': True, 'available': available,
                                          'reason_codes': list(dict.fromkeys(reasons)), **extra}
        if not available:
            availability.missing.append(name)
            availability.reason_codes.extend(reasons)

    metadata = fetch_from_vendors('get_instrument_metadata', symbol, cutoff.effective_session_date)
    instrument = metadata.value if metadata.available else None
    availability.instrument = instrument
    instrument_public = cutoff.cutoff_at if mode == 'demo' else (instrument.metadata.get('published_at') if instrument else None)
    instrument_reason = None
    if not instrument or instrument.status != 'supported':
        instrument_reason = (instrument.reason_codes[0] if instrument and instrument.reason_codes else 'instrument_unverified')
    elif mode == 'live' and (not instrument.metadata.get('cik') or classify_public_time(instrument_public, cutoff.cutoff_at)):
        instrument_reason = 'instrument_public_time_unverified'
    record('get_instrument_metadata', metadata.provider, instrument.to_dict() if instrument else None,
           reason=instrument_reason or 'eligibility_metadata_not_ai_input', published_at=instrument_public,
           public_time_basis='synthetic_fixture' if mode == 'demo' else 'SEC cover acceptance only; current listing flags not time-verified',
           source_url=next(iter(instrument.source_urls), None) if instrument else None)
    requirement('instrument', instrument_reason is None, [instrument_reason] if instrument_reason else [])

    if instrument_reason is None:
        fetched = fetch_from_vendors('get_price_history', symbol, cutoff.effective_session_date, 260)
        price_basis = getattr(fetched.value, 'price_basis', None)
        basis_ok = mode == 'demo' or (isinstance(price_basis, dict) and price_basis.get('verified') is True
            and price_basis.get('basis') == 'cutoff_split_units_no_dividend_adjustment'
            and aware_time(price_basis.get('cutoff_at')) == aware_time(cutoff.cutoff_at))
        bars, reasons = validate_daily_bars(fetched.value, cutoff.effective_session_date)
        if not basis_ok:
            reasons.append('price_adjustment_basis_unverified')
        try:
            if bars:
                calendar = calendars.get_calendar('XNYS', start=bars[0].date, end=cutoff.effective_session_date)
                sessions = {day.date().isoformat() for day in calendar.sessions}
                filtered = [bar for bar in bars if bar.date in sessions]
                if len(filtered) != len(bars):
                    reasons.append('non_trading_price_rows')
                bars = filtered
        except Exception:
            bars = []
            reasons.append('price_calendar_unverified')
        if len(bars) < DEFAULT_SOURCE_POLICY.minimum_price_bars:
            reasons.append('fewer_than_50_valid_daily_bars')
        if not bars or bars[-1].date != cutoff.effective_session_date:
            reasons.append('required_session_close_missing')
        price_ok = fetched.available and basis_ok and len(bars) >= 50 and bars[-1].date == cutoff.effective_session_date and 'conflicting_price_dates' not in reasons
        if not fetched.available:
            reasons.extend(attempt.error_code or attempt.status for attempt in fetched.attempts)
        price = record('get_price_history', fetched.provider, safe_json(bars),
            reason=None if price_ok else (reasons[0] if reasons else 'price_history_unavailable'),
            published_at=cutoff.cutoff_at, public_time_basis='completed_market_session; provider OHLCV',
            raw=safe_json(fetched.value), currency=resolution.currency, price_basis=price_basis)
        inputs['get_price_history'] = {'available': price_ok, 'provider': fetched.provider, 'value': safe_json(bars), 'record_ids': [price.record_id]}
        requirement('price_history', price_ok, reasons, valid_count=len(bars), minimum_count=50, provider=fetched.provider)

        started = utc_now()
        previous = audit.capture_context
        audit.capture_context = ('get_sec_statement_bundle', 'sec' if mode == 'live' else 'offline', uuid4().hex)
        try:
            bundle = get_sec_statement_bundle(symbol, cutoff.cutoff_at) if mode == 'live' else _demo_statements(symbol, cutoff)
        except Exception:
            bundle = SECStatementBundle(symbol, reason_codes=['statement_source_failed'])
        finally:
            audit.capture_context = previous
        audit.attempts.append(SourceAttempt(uuid4().hex, 'get_sec_statement_bundle', 'sec' if mode == 'live' else 'offline', mode,
            'success' if bundle.available else 'invalid_response', started, utc_now(), run_id=run_id,
            error_code=None if bundle.available else 'sec_statement_unavailable',
            message=None if bundle.available else 'The required filing-bound statements are unavailable.'))
        captures = {}
        for capture in bundle.captures:
            captures[capture.source_url] = capture
            record('sec_capture', 'sec', None, reason='transport_capture_not_ai_input', source_url=capture.source_url,
                   raw=capture.body, raw_kind='http_body', content_type=capture.content_type, retrieved_at=capture.retrieved_at)
        identity_ok = mode == 'demo' or (bundle.symbol.upper() == symbol.upper() and
                        bundle.cik == instrument.metadata.get('cik') and bundle.accession is not None)
        for kind in KINDS:
            statement = bundle.statements.get(kind)
            reasons = list(bundle.reason_codes)
            time_reason = None if mode == 'demo' else classify_public_time(bundle.published_at, cutoff.cutoff_at)
            if time_reason:
                reasons.append(time_reason)
            if not identity_ok:
                reasons.append('statement_identity_unverified')
            if statement is None or statement.numeric_cell_count <= 0:
                reasons.append(f'missing_{kind}')
            ok = bundle.available and statement is not None and statement.numeric_cell_count > 0 and identity_ok and not time_reason
            normalized = statement.text if statement else None
            captured = captures.get(statement.source_url) if statement else None
            item = record(f'get_{kind}', 'sec' if mode == 'live' else 'offline', normalized,
                reason=None if ok else (reasons[0] if reasons else f'missing_{kind}'),
                source_url=statement.source_url if statement else bundle.source_url, published_at=bundle.published_at,
                public_time_basis='SEC acceptanceDateTime' if mode == 'live' else 'synthetic_fixture',
                raw=captured.body if captured else normalized, raw_kind='http_body' if captured else 'vendor_object',
                content_type=captured.content_type if captured else 'text/plain', cik=bundle.cik, accession=bundle.accession,
                filing_form=bundle.form, period_end=bundle.period_end, currency=statement.currency if statement else None,
                unit_context='\n'.join(statement.unit_context) if statement else None)
            inputs[f'get_{kind}'] = {'available': ok, 'provider': item.provider, 'value': normalized if ok else None, 'record_ids': [item.record_id]}
            requirement(kind, ok, reasons, provider=item.provider, period_end=bundle.period_end, published_at=bundle.published_at)
        for excluded in bundle.excluded_filings:
            record('sec_filing_selection', 'sec', excluded, reason=excluded.get('reason_code') or 'filing_excluded',
                   source_url=bundle.source_url, published_at=excluded.get('acceptanceDateTime'))

    availability.can_recommend = not availability.missing
    if availability.can_recommend:
        overview = fetch_from_vendors('get_fundamentals', symbol)
        overview_reason = None if mode == 'demo' and overview.available else 'current_snapshot_not_time_verified'
        item = record('get_fundamentals', overview.provider, safe_json(overview.value), reason=overview_reason,
                      published_at=cutoff.cutoff_at if mode == 'demo' else None,
                      public_time_basis='synthetic_fixture' if mode == 'demo' else None)
        inputs['get_fundamentals'] = {'available': overview_reason is None, 'provider': item.provider,
            'value': safe_json(overview.value) if overview_reason is None else None, 'record_ids': [item.record_id]}
        availability.requirements['fundamentals'] = {'required': False, 'available': overview_reason is None,
                                                     'reason_codes': [overview_reason] if overview_reason else []}
        for method, args, scope in [('get_news', (symbol, cutoff.effective_session_date, 8), 'company'),
                                    ('get_global_news', (cutoff.effective_session_date, 'macro', 8), 'macro')]:
            fetched = fetch_from_vendors(method, *args)
            admitted, item_ids, seen = [], [], set()
            for news in fetched.value or []:
                reason = None if mode == 'demo' else classify_public_time(news.published_at, cutoff.cutoff_at)
                identity = _canonical_article(news)
                if identity in seen and reason is None:
                    reason = 'duplicate_article'
                seen.add(identity)
                item = record(method, fetched.provider, safe_json(news), reason=reason,
                    source_url=news.url or None, published_at=news.published_at, publisher=news.source,
                    public_time_basis='synthetic_fixture' if mode == 'demo' else 'provider publication timestamp')
                if reason is None:
                    admitted.append(safe_json(news))
                    item_ids.append(item.record_id)
            inputs[method] = {'available': bool(admitted), 'provider': fetched.provider, 'value': admitted, 'record_ids': item_ids}
            documents = [dict(title=n['title'], summary=n['summary'], source=n['source'], link=n['url'],
                             published_at=n['published_at'], provider=fetched.provider, scope=scope,
                             sentiment_score=n['sentiment_score']) for n in admitted]
            document_method = 'get_news_documents' if scope == 'company' else 'get_global_news_documents'
            inputs[document_method] = {'available': bool(documents), 'provider': fetched.provider, 'value': documents,
                'record_ids': item_ids, 'window_start': (date.fromisoformat(cutoff.effective_session_date) - timedelta(days=16)).isoformat(),
                'window_days': 8 if scope == 'macro' else 16}
            availability.requirements['news' if scope == 'company' else 'global_news'] = {
                'required': False, 'available': bool(admitted), 'reason_codes': [] if admitted else ['no_time_verified_news']}
        docs, ids = [], []
        for item in records:
            if item.method in {f'get_{kind}' for kind in KINDS} and item.admissibility == 'included':
                docs.append({'source': item.source_url, 'doc_type': item.filing_form, 'filing_date': item.published_at[:10],
                    'published_at': item.published_at, 'title': item.method, 'text': item.content, 'provider': item.provider})
                ids.append(item.record_id)
        inputs['get_fundamental_documents'] = {'available': bool(docs), 'provider': 'sec' if mode == 'live' else 'offline', 'value': docs, 'record_ids': ids}
        insider = fetch_from_vendors('get_insider_transactions', symbol, cutoff.effective_session_date)
        reason = None if mode == 'demo' and insider.available else 'public_time_unverified'
        item = record('get_insider_transactions', insider.provider, safe_json(insider.value), reason=reason,
                      published_at=cutoff.cutoff_at if mode == 'demo' else None)
        inputs['get_insider_transactions'] = {'available': reason is None, 'provider': item.provider,
            'value': insider.value if reason is None else None, 'record_ids': [item.record_id]}

    # HTTP bodies can contain records beyond the cutoff. They remain inspectable
    # transport evidence and are never part of a tool's normalized input.
    for capture in audit.raw_captures:
        record(capture['method'], capture['provider'], None, reason='transport_capture_not_ai_input',
               source_url=capture['source_url'], raw=capture['body'], raw_kind='http_body',
               content_type=capture['content_type'], retrieved_at=capture['retrieved_at'])
    materials = [dict(method=r.method, provider=r.provider, data_mode=r.data_mode, retrieved_at=r.retrieved_at,
        source_url=r.source_url, content=r.content, record_id=r.record_id, admissibility=r.admissibility,
        reason_codes=r.reason_codes, published_at=r.published_at) for r in records if r.content is not None]
    snapshot = ResearchDataSnapshot(origin_run_id=run_id, original_input=resolution.original_input, symbol=symbol,
        data_mode=mode, cutoff=cutoff.to_dict(), resolution=resolution.to_dict(), availability=availability.to_dict(),
        records=records, inputs=inputs, attempts=[attempt.to_dict() for attempt in audit.attempts], materials=materials,
        memory_contexts=memory_contexts or {}, memory_entries=memory_entries or [], calibration_summary=calibration_summary or {})
    store.save(snapshot)
    bind_frozen_snapshot(snapshot, audit)
    return snapshot


def load_research_snapshot(store, snapshot_id, query, requested_date, mode):
    snapshot = store.load(snapshot_id)
    aliases = {snapshot.symbol.casefold(), ' '.join(snapshot.original_input.split()).casefold()}
    if (' '.join(query.split()).casefold() not in aliases or requested_date != snapshot.cutoff.get('requested_date')
            or snapshot.data_mode != mode):
        raise SnapshotIntegrityError('Saved data does not match this security, requested date, or source mode.')
    return snapshot


def snapshot_availability(snapshot):
    from .instrument_metadata import InstrumentEligibility
    payload = dict(snapshot.availability)
    if payload.get('instrument'):
        payload['instrument'] = InstrumentEligibility(**payload['instrument'])
    payload['ai_analysis_performed'] = False
    return DataAvailability(**payload)
