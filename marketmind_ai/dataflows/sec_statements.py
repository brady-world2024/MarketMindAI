"""Capture formal SEC statement reports without crossing a publication cutoff.

Amounts remain as reported. Headers and row-level unit wording are retained;
this adapter does not infer a universal scale from a report's heading.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any

from .results import Serializable, valid_fiscal_period
from .sec_filings import SEC_ARCHIVE_URL, SEC_SUBMISSIONS_URL, SEC_TICKER_URL, _sec_get_text

_FORMS = {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A", "40-F/A"}
_KINDS = ("income_statement", "balance_sheet", "cashflow")
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
_FILENAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:htm|html)\Z", re.I)
_NUMBER = re.compile(r"[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?\Z")


@dataclass
class SECCapture(Serializable):
    source_url: str
    content_type: str
    body: str
    retrieved_at: str


@dataclass
class SECStatement(Serializable):
    kind: str
    title: str
    source_url: str
    text: str
    rows: list[list[str]]
    currency: str | None
    unit_context: list[str]
    period_end: str
    numeric_cell_count: int


@dataclass
class SECStatementBundle(Serializable):
    symbol: str
    cik: str | None = None
    form: str | None = None
    accession: str | None = None
    period_end: str | None = None
    published_at: str | None = None
    source_url: str | None = None
    statements: dict[str, SECStatement] = field(default_factory=dict)
    captures: list[SECCapture] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    available: bool = False
    excluded_filings: list[dict[str, Any]] = field(default_factory=list)
    primary_document_url: str | None = None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _capture(bundle: SECStatementBundle, url: str, content_type: str) -> str:
    # Fetch text first so the captured JSON is the actual provider body, rather
    # than a reconstruction that can conceal missing source reads.
    body = _sec_get_text(url)
    if not isinstance(body, str):
        raise ValueError("invalid source body")
    bundle.captures.append(SECCapture(url, content_type, body, datetime.now(timezone.utc).isoformat()))
    return body


def _json_source(bundle: SECStatementBundle, url: str) -> dict:
    payload = json.loads(_capture(bundle, url, "application/json"))
    if not isinstance(payload, dict):
        raise ValueError("invalid source object")
    return payload


def _filings(payload: dict) -> list[dict[str, Any]]:
    keys = ("form", "accessionNumber", "reportDate", "acceptanceDateTime", "filingDate", "primaryDocument")
    if not isinstance(payload.get("form"), list):
        raise ValueError("invalid submissions columns")
    result = []
    for i in range(len(payload["form"])):
        result.append({key: payload[key][i] if isinstance(payload.get(key), list) and i < len(payload[key]) else None for key in keys})
    return result


def _eligible(bundle: SECStatementBundle, filings: list[dict], cutoff: datetime) -> tuple[list[dict], list[dict]]:
    eligible, uncertain = [], []
    for filing in filings:
        if filing.get("form") not in _FORMS:
            continue
        accepted = _timestamp(filing.get("acceptanceDateTime"))
        period = filing.get("reportDate")
        reason = None
        if accepted is not None and accepted > cutoff:
            reason = "accepted_after_cutoff"
        elif not valid_fiscal_period(period):
            reason = "invalid_report_period"
        elif not isinstance(filing.get("accessionNumber"), str) or not _ACCESSION.fullmatch(filing["accessionNumber"]):
            reason = "invalid_accession"
        elif accepted is None:
            reason = "acceptance_time_unknown"
            # A known later filing date can exclude a record, but it cannot
            # establish any particular publication clock time.
            filed = filing.get("filingDate")
            if not valid_fiscal_period(filed) or filed <= cutoff.date().isoformat():
                uncertain.append(filing)
        elif period > accepted.date().isoformat():
            reason = "report_period_after_acceptance"
        else:
            eligible.append(filing)
        if reason:
            bundle.excluded_filings.append({**filing, "reason_code": reason})
    return eligible, uncertain


def _key(filing: dict) -> tuple[str, datetime]:
    return filing["reportDate"], _timestamp(filing["acceptanceDateTime"])


def get_sec_statement_bundle(symbol: str, cutoff_at: str | datetime) -> SECStatementBundle:
    """Return the latest applicable three-statement SEC filing at ``cutoff_at``.

    The fiscal period orders filings first, then SEC acceptance time orders
    versions. Failure of that selected filing never selects an older version.
    All successfully read responses remain captured even when unavailable.
    """
    return _get_sec_bundle(symbol, cutoff_at, headers_only=False)


def get_sec_filing_identity(symbol: str, cutoff_at: str | datetime) -> SECStatementBundle:
    """Select the same cutoff-safe formal filing using SEC JSON sources only.

    An identity is valid when accession, publication time, fiscal period and
    primary-document URL are present with no reason codes. ``available`` stays
    false because this entry point does not establish three-statement coverage.
    """
    return _get_sec_bundle(symbol, cutoff_at, headers_only=True)


def _get_sec_bundle(symbol: str, cutoff_at: str | datetime, *, headers_only: bool) -> SECStatementBundle:
    bundle = SECStatementBundle(symbol=str(symbol).strip().upper())
    cutoff = _timestamp(cutoff_at)
    if cutoff is None:
        bundle.reason_codes.append("invalid_cutoff")
        return bundle
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", bundle.symbol):
        bundle.reason_codes.append("invalid_symbol")
        return bundle
    try:
        mapping = _json_source(bundle, SEC_TICKER_URL)
        matches = [item for item in mapping.values() if isinstance(item, dict) and str(item.get("ticker", "")).upper() == bundle.symbol]
        if len(matches) != 1:
            bundle.reason_codes.append("cik_not_found" if not matches else "ambiguous_cik")
            return bundle
        raw_cik = str(matches[0].get("cik_str", ""))
        if not re.fullmatch(r"\d{1,10}", raw_cik) or int(raw_cik) <= 0:
            bundle.reason_codes.append("invalid_cik")
            return bundle
        bundle.cik = raw_cik.zfill(10)
    except Exception:
        bundle.reason_codes.append("ticker_mapping_unavailable")
        return bundle
    try:
        submissions = _json_source(bundle, SEC_SUBMISSIONS_URL.format(cik=bundle.cik))
        filing_data = submissions.get("filings")
        if not isinstance(filing_data, dict):
            raise ValueError("missing filings")
        recent = _filings(filing_data.get("recent") or {})
        candidates, uncertain = _eligible(bundle, recent, cutoff)
        best_period = max((f["reportDate"] for f in candidates), default=None)
        descriptors = filing_data.get("files", [])
        if not isinstance(descriptors, list):
            raise ValueError("invalid history index")
    except Exception:
        bundle.reason_codes.append("submissions_unavailable")
        return bundle
    for descriptor in descriptors:
        # An archive ending before the already verified fiscal period cannot
        # contain a later period or a newer version of it.
        if not isinstance(descriptor, dict):
            bundle.reason_codes.append("invalid_submissions_history")
            return bundle
        start, end = descriptor.get("filingFrom"), descriptor.get("filingTo")
        if not valid_fiscal_period(start) or not valid_fiscal_period(end) or start > end:
            bundle.reason_codes.append("invalid_submissions_history")
            return bundle
        if start > cutoff.date().isoformat() or (best_period is not None and end < best_period):
            continue
        name = descriptor.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"CIK" + bundle.cik + r"-submissions-\d+\.json", name):
            bundle.reason_codes.append("invalid_submissions_history_path")
            return bundle
        try:
            history = _json_source(bundle, "https://data.sec.gov/submissions/" + name)
            extra, unknown = _eligible(bundle, _filings(history), cutoff)
            candidates.extend(extra)
            uncertain.extend(unknown)
        except Exception:
            bundle.reason_codes.append("submissions_history_unavailable")
            return bundle
    if not candidates:
        invalid_period = any(f["reason_code"] in {"invalid_report_period", "report_period_after_acceptance"} for f in bundle.excluded_filings)
        bundle.reason_codes.append("latest_report_period_unknown" if invalid_period else "latest_acceptance_time_unknown" if uncertain else "no_eligible_filing")
        return bundle
    selected = max(candidates, key=_key)
    latest_key = _key(selected)
    equivalent = {f["accessionNumber"] for f in candidates if _key(f) == latest_key}
    if len(equivalent) > 1:
        bundle.reason_codes.append("ambiguous_latest_filing")
        return bundle
    bundle.form = selected["form"]
    bundle.accession = selected["accessionNumber"]
    bundle.period_end = selected["reportDate"]
    bundle.published_at = _timestamp(selected["acceptanceDateTime"]).isoformat()
    archive = SEC_ARCHIVE_URL.format(cik_int=int(bundle.cik), accession=bundle.accession.replace("-", ""), document="")
    primary_document = selected.get("primaryDocument")
    if not isinstance(primary_document, str) or not _FILENAME.fullmatch(primary_document) or ".." in primary_document:
        bundle.reason_codes.append("invalid_primary_document_path")
    else:
        bundle.primary_document_url = archive + primary_document
    bundle.source_url = archive + "FilingSummary.xml"
    blocked = any(f["reportDate"] >= bundle.period_end for f in uncertain)
    if blocked:
        bundle.reason_codes.append("latest_acceptance_time_unknown")
    for excluded in bundle.excluded_filings:
        reason = excluded["reason_code"]
        if reason not in {"invalid_report_period", "report_period_after_acceptance", "invalid_accession"}:
            continue
        accepted = _timestamp(excluded.get("acceptanceDateTime"))
        filed = excluded.get("filingDate")
        potentially_later = (accepted is not None and accepted >= latest_key[1]) or (
            accepted is None and (not valid_fiscal_period(filed) or filed <= cutoff.date().isoformat()))
        period = excluded.get("reportDate")
        if reason in {"invalid_report_period", "report_period_after_acceptance"}:
            # Acceptance chronology alone says nothing about fiscal-period
            # ordering: an unknown period can precede an amendment to an older
            # period and still be the newest applicable financial period.
            potentially_later = accepted is not None or not valid_fiscal_period(filed) or filed <= cutoff.date().isoformat()
        if reason == "invalid_accession":
            potentially_later = valid_fiscal_period(period) and (period > bundle.period_end or (period == bundle.period_end and potentially_later))
        if potentially_later:
            code = "latest_filing_identifier_invalid" if reason == "invalid_accession" else "latest_report_period_unknown"
            if code not in bundle.reason_codes:
                bundle.reason_codes.append(code)
    if headers_only:
        bundle.source_url = bundle.primary_document_url
        return bundle
    if "invalid_primary_document_path" in bundle.reason_codes:
        return bundle
    try:
        body = _capture(bundle, bundle.source_url, "application/xml")
        # ElementTree has no network resolver; disallow DTD/entity declarations
        # as they are not needed by SEC FilingSummary reports.
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
            raise ValueError("unsupported summary declarations")
        root = ET.fromstring(body)
        reports = _classify_reports(root)
    except Exception:
        bundle.reason_codes.append("filing_summary_unavailable")
        return bundle
    paths = {}
    for kind in _KINDS:
        matches = reports[kind]
        if len(matches) != 1:
            bundle.reason_codes.append(f"ambiguous_{kind}" if matches else f"missing_{kind}")
            continue
        title, filename = matches[0]
        if not filename:
            bundle.reason_codes.append(f"{kind}_unsupported_format")
        elif not _FILENAME.fullmatch(filename) or ".." in filename:
            bundle.reason_codes.append("invalid_statement_path")
        else:
            paths[kind] = (title, archive + filename)
    # Validate all paths before fetching any report.
    if "invalid_statement_path" in bundle.reason_codes:
        return bundle
    for kind, (title, url) in paths.items():
        try:
            html = _capture(bundle, url, "text/html")
            statement = _parse_statement(html, kind, title, url, bundle.period_end)
            if statement.numeric_cell_count == 0:
                bundle.reason_codes.append(f"{kind}_no_numeric_data")
            elif kind == "income_statement" and _combined_income_name(title) and not any(
                row and re.search(r"\b(?:revenue|sales|net\s+(?:income|loss|earnings)|operating\s+(?:income|loss)|income\s+before)\b", row[0], re.I)
                and any(_numeric(cell) for cell in row[1:]) for row in statement.rows
            ):
                bundle.reason_codes.append("income_statement_no_income_data")
            else:
                bundle.statements[kind] = statement
        except _InvalidReport:
            bundle.reason_codes.append(f"{kind}_invalid_report")
        except Exception:
            bundle.reason_codes.append(f"{kind}_unavailable")
    bundle.available = not bundle.reason_codes and set(bundle.statements) == set(_KINDS)
    return bundle


def _combined_income_name(name: str) -> bool:
    return bool(re.search(r"statements?\s+of\s+(?:income|operations|earnings|loss)(?:\s*\(loss\))?\s+(?:and|&)\s+comprehensive\s+(?:income|loss)(?:\s*\(loss\))?", name, re.I))


def _classify_reports(root: ET.Element) -> dict[str, list[tuple[str, str | None]]]:
    reports = {kind: [] for kind in _KINDS}
    for report in root.iter():
        if report.tag.rsplit("}", 1)[-1] != "Report":
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in report}
        if fields.get("MenuCategory", "").lower() != "statements":
            continue
        title = fields.get("ShortName") or fields.get("LongName", "")
        names = " ".join([fields.get("ShortName", ""), fields.get("LongName", "")]).lower()
        if any(term in names for term in ("parenthetical", "equity", "stockholders", "shareholders", "notes to", "footnote")):
            continue
        combined = next((name for name in (fields.get("ShortName", ""), fields.get("LongName", "")) if _combined_income_name(name)), None)
        if "comprehensive" in names and not combined:
            continue
        if combined:
            title = combined
        kind = None
        if re.search(r"balance\s*sheets?|financial\s+position", names):
            kind = "balance_sheet"
        elif re.search(r"cash\s*flows?", names):
            kind = "cashflow"
        elif re.search(r"statements?\s+of\s+(?:income|operations|earnings|loss)|income\s+statements?|statements?\s+of\s+profit", names):
            kind = "income_statement"
        if kind:
            reports[kind].append((title, fields.get("HtmlFileName") or None))
    return reports


def _numeric(value: str) -> bool:
    value = re.sub(r"[$€£¥\s]", "", value)
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    return bool(_NUMBER.fullmatch(value))


class _ReportParser(HTMLParser):
    """Read visible report tables only, ignoring hidden XBRL references."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.table_depth = 0
        self.report_depth = 0
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.cell_numeric = False
        self.count = 0
        self.header_cells: list[str] = []
        self.report_tables = 0
        self.closed_report_tables = 0
        self.malformed = False
        self.visible_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent_hidden = self.stack[-1][1] if self.stack else False
        style = re.sub(r"\s+", "", attrs.get("style", "").lower())
        hidden = parent_hidden or tag in {"script", "style"} or "hidden" in attrs or "display:none" in style or "visibility:hidden" in style or "authRefData" in attrs.get("class", "")
        if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr"}:
            self.stack.append((tag, hidden))
        if hidden:
            return
        if tag == "table":
            self.table_depth += 1
            if "report" in attrs.get("class", "").split() and not self.report_depth:
                self.report_depth = self.table_depth
                self.report_tables += 1
        if not self.report_depth:
            return
        if tag == "tr" and self.table_depth == self.report_depth:
            if self.row is not None:
                self.malformed = True
            self.row = []
        elif tag in {"td", "th"} and self.row is not None and self.table_depth == self.report_depth:
            if self.cell is not None:
                self.malformed = True
            self.cell = []
            classes = attrs.get("class", "").split()
            self.cell_numeric = tag == "td" and any(re.fullmatch(r"num[a-z]*", c) for c in classes)
        elif tag in {"ix:nonfraction", "ix:nondecimal"} and self.cell is not None:
            self.cell_numeric = True
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        hidden = self.stack[-1][1] if self.stack else False
        if not hidden:
            if tag in {"td", "th"} and self.cell is not None:
                value = re.sub(r"\s+", " ", "".join(self.cell)).strip()
                if self.row is not None:
                    self.row.append(value)
                if tag == "th":
                    self.header_cells.append(value)
                if self.cell_numeric and _numeric(value):
                    self.count += 1
                self.cell = None
            elif tag == "tr" and self.row is not None and self.table_depth == self.report_depth:
                if self.cell is not None:
                    self.malformed = True
                self.rows.append(self.row)
                self.row = None
            elif tag == "table":
                if self.table_depth == self.report_depth:
                    if self.row is not None or self.cell is not None:
                        self.malformed = True
                    self.closed_report_tables += 1
                    self.report_depth = 0
                self.table_depth = max(0, self.table_depth - 1)
        # Real SEC HTML is HTML rather than XML. Close to the matching open
        # element without allowing an unmatched end tag to reveal hidden data.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]):
            self.visible_parts.append(data)
            if self.cell is not None:
                self.cell.append(data)


class _InvalidReport(ValueError):
    """A captured response cannot establish a complete dated SEC report."""


def _header_periods(headers: list[str]) -> set[str]:
    periods: set[str] = set()
    months = {name: index for index, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
    for header in headers:
        for candidate in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", header):
            if valid_fiscal_period(candidate):
                periods.add(candidate)
        for month, day, year in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b", header):
            month_number = months.get(month[:3].lower())
            if month_number:
                try:
                    periods.add(date(int(year), month_number, int(day)).isoformat())
                except ValueError:
                    pass
    return periods


def _parse_statement(html: str, kind: str, title: str, url: str, period: str) -> SECStatement:
    parser = _ReportParser()
    parser.feed(html)
    parser.close()
    text = "\n".join("\t".join(row) for row in parser.rows)
    # A number is evidence only inside a complete, dated report table. A
    # partly downloaded report can otherwise retain its first numeric rows.
    if parser.count and (
        parser.malformed or parser.report_depth or parser.row is not None or parser.cell is not None
        or parser.report_tables != parser.closed_report_tables
        or period not in _header_periods(parser.header_cells)
        or re.search(r"\baccess\s+denied\b|\brequest\s+rate\s+threshold\s+exceeded\b|\berror\s+code\s*[:/]?\s*(?:403|404|429|500|502|503)\b|\b(?:bad\s+gateway|service\s+unavailable)\b", " ".join(parser.visible_parts), re.I)
    ):
        raise _InvalidReport()
    unit_context = list(dict.fromkeys(cell for row in parser.rows for cell in row if re.search(r"millions?|thousands?|billions?|per\s+share|in\s+shares|\b(?:USD|EUR|GBP|JPY|CAD|AUD)\b", cell, re.I)))
    currencies = set(re.findall(r"\b(?:USD|EUR|GBP|JPY|CAD|AUD|CNY|CHF|HKD)\b", text))
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return SECStatement(kind, title, url, text, parser.rows, currency, unit_context, period, parser.count)
