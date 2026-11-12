"""Point-in-time SEC statements; all source reads are isolated fixtures."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from marketmind_ai.dataflows import sec_statements as sec

CIK = "0001045810"
ACCESSION = "0001045810-26-000052"
BASE = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000052/"
CUTOFF = "2026-05-22T20:00:00+00:00"


def filing(accession=ACCESSION, period="2026-04-26", accepted="2026-05-21T20:30:00Z", form="10-Q"):
    return dict(accessionNumber=accession, reportDate=period, acceptanceDateTime=accepted,
                form=form, filingDate=(accepted or "2026-05-21")[:10], primaryDocument="report.htm")


def columns(*filings):
    return {key: [f.get(key) for f in filings] for key in filing()}


def summary(extra="", income="Consolidated Statements of Income"):
    names = [(income, "R2.htm"), ("Consolidated Balance Sheets", "R4.htm"),
             ("Consolidated Statements of Cash Flows", "R7.htm")]
    return "<FilingSummary><MyReports>" + "".join(
        f"<Report><ShortName>{name}</ShortName><LongName>{name}</LongName>"
        f"<MenuCategory>Statements</MenuCategory><HtmlFileName>{file}</HtmlFileName></Report>"
        for name, file in names) + extra + "</MyReports></FilingSummary>"


def report(value="$ 0", title="Statement - USD ($), $ in Millions"):
    return f'''<html><body><table class="report"><tr><th>{title}</th><th>Apr. 26, 2026</th></tr>
    <tr><td>Revenue</td><td class="nump">{value}</td></tr>
    <tr><td>Interest</td><td class="num">(102)</td></tr>
    <tr><td>Basic (in dollars per share)</td><td class="nump">2.40</td></tr>
    <tr><td>Disclosure without value</td><td class="text">—</td></tr></table>
    <div style="display: none"><table class="authRefData"><tr><td>SECRET_DEFINITION 12345</td></tr></table></div>
    <script>SECRET_SCRIPT 12345</script></body></html>'''


def source(monkeypatch, filings=None, summary_body=None, reports=None, history=None):
    bodies = {sec.SEC_TICKER_URL: json.dumps({"0": {"ticker": "NVDA", "cik_str": 1045810}}),
              sec.SEC_SUBMISSIONS_URL.format(cik=CIK): json.dumps({"filings": {
                  "recent": columns(*(filings if filings is not None else [filing()])),
                  "files": history or []}}),
              BASE + "FilingSummary.xml": summary_body or summary()}
    for name in ("R2.htm", "R4.htm", "R7.htm"):
        bodies[BASE + name] = report()
    bodies.update(reports or {})
    calls = []
    def get(url):
        calls.append(url)
        body = bodies[url]
        if isinstance(body, Exception):
            raise body
        return body
    monkeypatch.setattr(sec, "_sec_get_text", get)
    return bodies, calls


def test_returns_three_statements_and_captures_actual_raw_sources(monkeypatch):
    _, calls = source(monkeypatch)
    result = sec.get_sec_statement_bundle("nvda", CUTOFF)
    assert result.available
    assert set(result.statements) == {"income_statement", "balance_sheet", "cashflow"}
    assert result.published_at == "2026-05-21T20:30:00+00:00"
    assert result.period_end == "2026-04-26"
    assert {c.source_url for c in result.captures} == set(calls)
    assert json.loads(result.captures[0].body)["0"]["ticker"] == "NVDA"
    assert result.to_dict()["statements"]["income_statement"]["numeric_cell_count"] == 3


def test_exact_acceptance_cutoff_excludes_after_close_and_uses_period_before_version(monkeypatch):
    old_amendment = filing("0001045810-26-000053", "2025-12-31", "2026-05-22T19:00:00Z", "10-K/A")
    later = filing("0001045810-26-000054", "2026-04-26", "2026-05-22T20:00:01Z")
    source(monkeypatch, [later, old_amendment, filing()])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available and result.accession == ACCESSION
    assert any(f["reason_code"] == "accepted_after_cutoff" for f in result.excluded_filings)


def test_same_period_restatement_wins_and_failed_latest_never_falls_back(monkeypatch):
    amendment = filing("0001045810-26-000053", accepted="2026-05-22T19:00:00Z", form="10-Q/A")
    _, calls = source(monkeypatch, [amendment, filing()])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available
    assert result.accession == amendment["accessionNumber"]
    assert "filing_summary_unavailable" in result.reason_codes
    assert BASE + "FilingSummary.xml" not in calls


def test_unknown_acceptance_is_never_inferred_from_filing_date(monkeypatch):
    source(monkeypatch, [filing(accepted=None)])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available
    assert result.published_at is None
    assert result.excluded_filings[0]["reason_code"] == "acceptance_time_unknown"
    assert len(result.captures) == 2


def test_historical_submission_range_is_loaded_when_recent_is_after_cutoff(monkeypatch):
    desc = {"name": "CIK0001045810-submissions-001.json", "filingFrom": "2024-01-01", "filingTo": "2026-05-21"}
    bodies, _ = source(monkeypatch, [filing(accepted="2026-05-23T10:00:00Z")], history=[desc])
    url = "https://data.sec.gov/submissions/" + desc["name"]
    bodies[url] = json.dumps(columns(filing()))
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available
    assert url in [c.source_url for c in result.captures]


def test_missing_necessary_history_fails_closed(monkeypatch):
    desc = {"name": "CIK0001045810-submissions-001.json", "filingFrom": "2024-01-01", "filingTo": "2026-05-21"}
    source(monkeypatch, [filing(accepted="2026-05-23T10:00:00Z")], history=[desc])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "submissions_history_unavailable" in result.reason_codes


def test_comprehensive_equity_parenthetical_notes_do_not_replace_primary(monkeypatch):
    extra = "".join(f"<Report><ShortName>{name}</ShortName><MenuCategory>{category}</MenuCategory>"
                    f"<HtmlFileName>ignored.htm</HtmlFileName></Report>" for name, category in [
                        ("Statements of Comprehensive Income", "Statements"),
                        ("Statements of Equity", "Statements"),
                        ("Statements of Income (Parenthetical)", "Statements"),
                        ("Statements of Income", "Notes")])
    _, calls = source(monkeypatch, summary_body=summary(extra))
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available and BASE + "ignored.htm" not in calls


def test_ambiguous_primary_reports_fail_instead_of_first_wins(monkeypatch):
    extra = "<Report><ShortName>Statements of Operations</ShortName><MenuCategory>Statements</MenuCategory><HtmlFileName>R8.htm</HtmlFileName></Report>"
    source(monkeypatch, summary_body=summary(extra))
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "ambiguous_income_statement" in result.reason_codes


def test_visible_rows_zero_negative_and_per_share_units_are_preserved(monkeypatch):
    source(monkeypatch)
    statement = sec.get_sec_statement_bundle("NVDA", CUTOFF).statements["income_statement"]
    assert len(statement.rows) == 5
    assert statement.rows[1] == ["Revenue", "$ 0"]
    assert statement.rows[2][1] == "(102)"
    assert "dollars per share" in statement.text
    assert "$ in Millions" in " ".join(statement.unit_context)
    assert "SECRET" not in statement.text
    assert statement.currency == "USD"


@pytest.mark.parametrize("body", [report("—").replace('(102)', '—').replace('2.40', '—'),
                                  '<html><h1>Statements of Income 2026</h1><p>Error 403</p></html>',
                                  '<table class="report"><tr><th>Statements of Income 2026</th></tr></table>'])
def test_null_title_only_and_error_digits_are_not_numeric_coverage(monkeypatch, body):
    source(monkeypatch, reports={BASE + "R2.htm": body})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_no_numeric_data" in result.reason_codes
    assert BASE + "R2.htm" in [c.source_url for c in result.captures]


@pytest.mark.parametrize("filename", ["../R2.htm", "https://evil.test/R2.htm", "%2e%2e/R2.htm", "R2.htm?key=x", "/R2.htm"])
def test_summary_cannot_escape_sec_archive(monkeypatch, filename):
    _, calls = source(monkeypatch, summary_body=summary().replace("R2.htm", filename))
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "invalid_statement_path" in result.reason_codes
    assert len(calls) == 3


def test_exception_messages_are_not_exposed(monkeypatch):
    source(monkeypatch, reports={BASE + "R2.htm": RuntimeError("token=secret-account-value")})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_unavailable" in result.reason_codes
    assert "secret-account-value" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("cutoff", ["2026-05-22", "2026-05-22T20:00:00", datetime(2026, 5, 22)])
def test_cutoff_must_have_known_time_zone(monkeypatch, cutoff):
    _, calls = source(monkeypatch)
    result = sec.get_sec_statement_bundle("NVDA", cutoff)
    assert not result.available and "invalid_cutoff" in result.reason_codes
    assert calls == []


def test_unknown_time_newer_period_blocks_older_verified_filing(monkeypatch):
    unknown = filing("0001045810-26-000053", "2026-05-01", accepted=None)
    source(monkeypatch, [unknown, filing()])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "latest_acceptance_time_unknown" in result.reason_codes


def test_unknown_old_period_and_known_future_filing_date_do_not_block(monkeypatch):
    unknown = filing("0001045810-25-000053", "2025-05-01", accepted=None)
    future = filing("0001045810-26-000054", "2026-05-01", accepted=None)
    future["filingDate"] = "2026-05-23"
    source(monkeypatch, [unknown, future, filing()])
    assert sec.get_sec_statement_bundle("NVDA", CUTOFF).available


def test_unsupported_statement_format_is_explicit(monkeypatch):
    source(monkeypatch, summary_body=summary().replace("<HtmlFileName>R2.htm</HtmlFileName>", "<XmlFileName>R2.xml</XmlFileName>"))
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_unsupported_format" in result.reason_codes


def test_conflicting_same_period_acceptance_is_ambiguous(monkeypatch):
    source(monkeypatch, [filing(), filing("0001045810-26-000053")])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "ambiguous_latest_filing" in result.reason_codes


def test_all_zero_statement_is_valid_and_unknown_currency_is_not_guessed(monkeypatch):
    html = report("0", title="Amounts in thousands").replace("(102)", "0").replace("2.40", "0")
    source(monkeypatch, reports={BASE + "R2.htm": html})
    result = sec.get_sec_statement_bundle("NVDA", datetime(2026, 5, 22, 20, tzinfo=timezone.utc))
    assert result.available
    assert result.statements["income_statement"].numeric_cell_count == 3
    assert result.statements["income_statement"].currency is None


def test_read_error_page_is_captured_but_is_not_statement(monkeypatch):
    error = "<html><body>SEC request rate threshold exceeded 403 2026</body></html>"
    source(monkeypatch, reports={BASE + "R2.htm": error})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available
    assert "income_statement" not in result.statements
    assert next(c.body for c in result.captures if c.source_url == BASE + "R2.htm") == error


def test_statement_names_support_financial_position_and_earnings(monkeypatch):
    xml = summary(income="Condensed Consolidated Statements of Earnings").replace("Consolidated Balance Sheets", "Statements of Financial Position")
    source(monkeypatch, summary_body=xml)
    assert sec.get_sec_statement_bundle("NVDA", CUTOFF).available


@pytest.mark.parametrize("cik", ["../1045810", "1045810/evil", "0", "10000000000", "https://evil.test", True, -1])
def test_cik_values_cannot_construct_unsafe_archive_or_submissions_urls(monkeypatch, cik):
    bodies, calls = source(monkeypatch)
    bodies[sec.SEC_TICKER_URL] = json.dumps({"0": {"ticker": "NVDA", "cik_str": cik}})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "invalid_cik" in result.reason_codes
    assert calls == [sec.SEC_TICKER_URL]


def test_history_names_are_bound_to_the_issuer_without_traversal(monkeypatch):
    desc = {"name": "../CIK0001045810-submissions-001.json", "filingFrom": "2024-01-01", "filingTo": "2026-05-21"}
    _, calls = source(monkeypatch, [filing(accepted="2026-05-23T10:00:00Z")], history=[desc])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "invalid_submissions_history_path" in result.reason_codes
    assert len(calls) == 2


def test_old_history_range_does_not_require_irrelevant_reads(monkeypatch):
    desc = {"name": "CIK0001045810-submissions-001.json", "filingFrom": "2020-01-01", "filingTo": "2024-12-31"}
    _, calls = source(monkeypatch, history=[desc])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available
    assert not any("submissions-001" in url for url in calls)


def test_exact_cutoff_is_eligible(monkeypatch):
    source(monkeypatch, [filing(accepted="2026-05-22T16:00:00-04:00")])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available and result.published_at == CUTOFF


def test_invalid_latest_report_period_blocks_older_verified_period(monkeypatch):
    latest = filing("0001045810-26-000053", period="", accepted="2026-05-22T19:00:00Z")
    source(monkeypatch, [latest, filing()])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "latest_report_period_unknown" in result.reason_codes


def test_combined_income_and_comprehensive_statement_is_primary_with_income_rows(monkeypatch):
    source(monkeypatch, summary_body=summary(income="Statements of Income and Comprehensive Income"))
    assert sec.get_sec_statement_bundle("NVDA", CUTOFF).available


def test_combined_title_without_numeric_income_rows_is_not_income_coverage(monkeypatch):
    html = '<table class="report"><tr><th>Combined Statement - USD ($)</th><th>Apr. 26, 2026</th></tr><tr><td>Foreign currency translation adjustment</td><td class="nump">123</td></tr></table>'
    source(monkeypatch, summary_body=summary(income="Statements of Operations and Comprehensive Income"), reports={BASE + "R2.htm": html})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_no_income_data" in result.reason_codes


def test_latest_invalid_accession_cannot_fall_back(monkeypatch):
    source(monkeypatch, [filing("../evil", accepted="2026-05-22T19:00:00Z"), filing()])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "latest_filing_identifier_invalid" in result.reason_codes


def test_unknown_report_period_cannot_be_hidden_by_later_old_period_amendment(monkeypatch):
    unknown = filing("0001045810-26-000053", period="", accepted="2026-05-21T19:00:00Z")
    old_amendment = filing(period="2025-12-31", accepted="2026-05-22T19:00:00Z", form="10-K/A")
    source(monkeypatch, [unknown, old_amendment])
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "latest_report_period_unknown" in result.reason_codes


@pytest.mark.parametrize("html", [
    report().split('</table>', 1)[0] + '<tr><td>unclosed row',
    '<table class="report"><tr><td>Revenue</td><td class="nump">123</td></tr><tr><td>unclosed row',
    '<table class="report"><tr><td>Access denied. Error code</td><td class="nump">403</td></tr></table>',
    '<table class="report"><tr><th>Statement - USD ($)</th></tr><tr><td>Revenue</td><td class="nump">123</td></tr></table>',
    report().replace('Apr. 26, 2026', 'Apr. 25, 2026'),
    report().replace('Revenue', 'Access denied. Error code'),
])
def test_truncated_transport_errors_and_missing_period_context_do_not_qualify(monkeypatch, html):
    source(monkeypatch, reports={BASE + "R2.htm": html})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_invalid_report" in result.reason_codes
    assert "income_statement" not in result.statements
    assert next(c.body for c in result.captures if c.source_url == BASE + "R2.htm") == html


def test_financial_error_word_is_not_treated_as_transport_failure(monkeypatch):
    html = report().replace('Revenue', 'Correction of prior period error')
    source(monkeypatch, reports={BASE + "R2.htm": html})
    assert sec.get_sec_statement_bundle("NVDA", CUTOFF).available


def test_combined_income_loss_title_with_numeric_income_rows_qualifies(monkeypatch):
    source(monkeypatch, summary_body=summary(income="Consolidated Statements of Income (Loss) and Comprehensive Income (Loss)"))
    assert sec.get_sec_statement_bundle("NVDA", CUTOFF).available


def test_transport_failure_outside_table_rejects_otherwise_dated_numeric_report(monkeypatch):
    html = '<h1>Access denied</h1>' + report()
    source(monkeypatch, reports={BASE + "R2.htm": html})
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert not result.available and "income_statement_invalid_report" in result.reason_codes


def test_filing_identity_loads_old_partition_without_statement_downloads(monkeypatch):
    desc = {"name": "CIK0001045810-submissions-001.json", "filingFrom": "2023-01-01", "filingTo": "2024-12-31"}
    bodies, calls = source(monkeypatch, history=[desc])
    historical = filing("0001045810-24-000052", period="2023-12-31", accepted="2024-02-20T20:30:00Z", form="10-K")
    history_url = "https://data.sec.gov/submissions/" + desc["name"]
    bodies[history_url] = json.dumps(columns(historical))
    result = sec.get_sec_filing_identity("NVDA", "2024-03-01T21:00:00Z")
    assert result.reason_codes == []
    assert result.accession == historical["accessionNumber"]
    assert result.period_end == "2023-12-31"
    assert result.published_at == "2024-02-20T20:30:00+00:00"
    assert result.primary_document_url == "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000052/report.htm"
    assert result.source_url == result.primary_document_url
    assert calls == [sec.SEC_TICKER_URL, sec.SEC_SUBMISSIONS_URL.format(cik=CIK), history_url]
    assert [capture.source_url for capture in result.captures] == calls
    assert result.statements == {} and not result.available
    assert result.to_dict()["primary_document_url"] == result.primary_document_url


@pytest.mark.parametrize("document", ["../report.htm", "https://evil.test/report.htm", "%2e%2e/report.htm", "report.htm?key=x", "/report.htm", None])
def test_filing_identity_rejects_unsafe_or_missing_primary_document(monkeypatch, document):
    selected = filing()
    selected["primaryDocument"] = document
    _, calls = source(monkeypatch, [selected])
    result = sec.get_sec_filing_identity("NVDA", CUTOFF)
    assert result.reason_codes
    assert result.primary_document_url is None
    assert not result.available and not result.statements
    assert len(calls) == 2


def test_filing_identity_keeps_unknown_latest_acceptance_blocker_without_report_reads(monkeypatch):
    unknown = filing("0001045810-26-000053", period="2026-05-01", accepted=None)
    _, calls = source(monkeypatch, [unknown, filing()])
    result = sec.get_sec_filing_identity("NVDA", CUTOFF)
    assert "latest_acceptance_time_unknown" in result.reason_codes
    assert not result.available
    assert len(calls) == 2


def test_statement_bundle_exposes_validated_primary_document_url(monkeypatch):
    source(monkeypatch)
    result = sec.get_sec_statement_bundle("NVDA", CUTOFF)
    assert result.available
    assert result.primary_document_url == BASE + "report.htm"
    assert result.source_url == BASE + "FilingSummary.xml"
