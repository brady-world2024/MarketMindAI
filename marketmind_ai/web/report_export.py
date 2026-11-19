from __future__ import annotations

from html import escape
import json
import re
from typing import Any
from urllib.parse import quote

from ..graph.research_scope import HORIZON_LABELS, OBJECTIVE_LABELS


def _meta_row(label: str, value: Any) -> str:
    text = escape(str(value or "—"))
    return (
        '<div class="meta-row">'
        f'<span class="meta-label">{escape(label)}</span>'
        f'<strong class="meta-value">{text}</strong>'
        "</div>"
    )


def _pre_section(title: str, content: str, tone: str = "") -> str:
    class_name = "report-section"
    if tone:
        class_name += f" {tone}"
    return (
        f'<section class="{class_name}">'
        f"<h2>{escape(title)}</h2>"
        f"<pre>{escape(content)}</pre>"
        "</section>"
    )


def _structured_decision_section(decision: dict[str, Any]) -> str:
    if not decision:
        return ""
    rating = decision.get("rating") or "No Recommendation"
    status = decision.get("decision_status") or "Unknown"
    confidence = decision.get("confidence")
    confidence_text = f"{confidence}/100" if confidence is not None else "—"
    price_target = decision.get("price_target")
    time_horizon = decision.get("time_horizon") or "—"
    risks = [str(item) for item in decision.get("key_risks") or [] if str(item).strip()]
    risk_items = "".join(f"<li>{escape(item)}</li>" for item in risks) or "<li>No key risks were captured.</li>"
    thesis = decision.get("investment_thesis") or "No investment thesis was captured."
    summary = decision.get("executive_summary") or "No executive summary was captured."
    gap = decision.get("evidence_gap") or "No evidence gap was captured."
    target_text = "—" if price_target is None else str(price_target)
    return (
        '<section class="report-section decision-brief">'
        "<h2>Decision Brief</h2>"
        '<div class="decision-metrics">'
        f'<div><span>Status</span><strong>{escape(str(status))}</strong></div>'
        f'<div><span>Rating</span><strong>{escape(str(rating))}</strong></div>'
        f'<div><span>Confidence</span><strong>{escape(confidence_text)}</strong></div>'
        f'<div><span>Price Target</span><strong>{escape(target_text)}</strong></div>'
        f'<div><span>Time Horizon</span><strong>{escape(str(time_horizon))}</strong></div>'
        "</div>"
        '<div class="brief-grid">'
        f'<div><h3>Executive Summary</h3><p>{escape(str(summary))}</p></div>'
        f'<div><h3>Investment Thesis</h3><p>{escape(str(thesis))}</p></div>'
        f'<div><h3>Evidence Gap</h3><p>{escape(str(gap))}</p></div>'
        f"<div><h3>Key Risks</h3><ul>{risk_items}</ul></div>"
        "</div>"
        "</section>"
    )


def _quality_section(report_quality: dict[str, Any]) -> str:
    if not report_quality:
        return ""
    dimensions = report_quality.get("dimensions") or {}
    dimension_rows = "".join(
        '<div class="quality-dimension">'
        f'<span>{escape(str(item.get("label") or key))}</span>'
        f'<strong>{escape(str(item.get("score", "—")))}</strong>'
        f'<p>{escape(str(item.get("detail") or ""))}</p>'
        "</div>"
        for key, item in dimensions.items()
        if isinstance(item, dict)
    )
    issues = report_quality.get("issues") or []
    issue_items = "".join(
        f'<li><strong>{escape(str(issue.get("code", "issue")))}</strong>: {escape(str(issue.get("message", "")))}</li>'
        for issue in issues
        if isinstance(issue, dict)
    )
    if not issue_items:
        issue_items = "<li>No quality issues were detected.</li>"
    return (
        '<section class="report-section quality-panel">'
        "<h2>Quality Score</h2>"
        '<div class="quality-header">'
        f'<strong>{escape(str(report_quality.get("score", "—")))}</strong>'
        f'<span>{escape(str(report_quality.get("grade", "Unscored")))}</span>'
        "</div>"
        f'<p class="quality-summary">{escape(str(report_quality.get("summary") or ""))}</p>'
        f'<div class="quality-grid">{dimension_rows}</div>'
        f'<h3>Quality Issues</h3><ul>{issue_items}</ul>'
        "</section>"
    )


def _evidence_ledger_section(ledger: list[dict[str, Any]]) -> str:
    if not ledger:
        return ""
    rows = []
    for item in ledger:
        source = item.get("source") or "Unknown"
        source_date = item.get("source_date") or "Unknown date"
        provider = item.get("provider") or "Unknown provider"
        source_type = item.get("source_type") or "Unknown type"
        url = item.get("url") or ""
        provenance = f"{provider} · {source_type}"
        if url:
            provenance += f"\n{url}"
        rows.append(
            "<tr>"
            f'<td class="evidence-id">{escape(str(item.get("evidence_id") or ""))}</td>'
            f"<td>{escape(str(item.get('claim') or ''))}</td>"
            f"<td>{escape(str(item.get('kind') or ''))}</td>"
            f"<td>{escape(str(source))}<br /><span>{escape(str(source_date))}</span></td>"
            f"<td>{escape(provenance).replace(chr(10), '<br />')}</td>"
            f"<td>{escape(str(item.get('excerpt') or ''))}</td>"
            f"<td>{escape(str(item.get('freshness') or ''))}</td>"
            "</tr>"
        )
    return (
        '<section class="report-section evidence-ledger-section">'
        "<h2>Evidence Ledger</h2>"
        '<div class="table-wrap">'
        '<table class="evidence-table">'
        "<thead><tr>"
        "<th>ID</th><th>Claim</th><th>Kind</th><th>Source</th><th>Provenance</th><th>Excerpt</th><th>Freshness</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _review_section(snapshot: dict[str, Any]) -> str:
    review = snapshot.get("review") or {}
    labels = {
        "pending": "Awaiting human review",
        "approved": "Approved by human reviewer",
        "rejected": "Rejected by human reviewer",
        "changes_requested": "Changes requested — awaiting a revised report",
    }
    label = labels.get(review.get("status"), "No human review recorded")
    metadata = "".join(
        _meta_row(name, value)
        for name, value in (
            ("Review status", label),
            ("Report version", review.get("version")),
            ("Report fingerprint", review.get("report_hash")),
            ("Review requested", review.get("requested_at")),
            ("Previous run", review.get("parent_run_id")),
            ("Revised run", review.get("revision_run_id")),
        ) if value is not None
    )
    history = "".join(
        _pre_section(
            f"{item.get('decision', '').replace('_', ' ').title()} · {item.get('reviewer', '')}",
            f"{item.get('reviewed_at', '')} · Version {item.get('version', '')}\n{item.get('comment', '')}",
        )
        for item in review.get("history", [])
    )
    return (
        '<section class="report-section human-review-section">'
        f"<h2>{escape(label)}</h2>"
        f'<div class="meta-grid">{metadata}</div>'
        "<p>Reviewer names are self-reported in this local application. "
        "Approval records acceptance of this report version and does not change its automated validation result. "
        "Human approval does not guarantee factual correctness.</p>"
        f"{history}</section>"
    )


def _provenance_section(snapshot: dict[str, Any]) -> str:
    cutoff = snapshot.get('research_cutoff') or {}
    manifest = snapshot.get('data_snapshot') or {}
    rows = ''.join(_meta_row(label, data.get(key) or 'Unverified') for label, data, key in [
        ('Requested date', cutoff, 'requested_date'), ('Effective session date', cutoff, 'effective_session_date'),
        ('Cutoff (UTC)', cutoff, 'cutoff_at'), ('Cutoff (market local)', cutoff, 'cutoff_at_local'),
        ('Market timezone', cutoff, 'market_timezone'), ('Snapshot ID', manifest, 'snapshot_id'),
        ('Manifest SHA-256', manifest, 'manifest_sha256'), ('Policy version', manifest, 'policy_version'),
        ('Processing version', manifest, 'processing_version'),
    ])
    warning = '' if cutoff and manifest.get('snapshot_id') else '<p>Snapshot provenance: Unverified · 未核验</p>'
    result = f'<section class="report-section"><h2>Research Cutoff &amp; Saved Data</h2>{warning}{rows}</section>'
    for status in ('included', 'excluded', 'unverified'):
        records = [record for record in snapshot.get('source_records') or [] if (record.get('admissibility') or 'unverified') == status]
        result += f'<section class="report-section"><h2>{status.title()} Sources ({len(records)})</h2>'
        for record in records:
            metadata = {key: record.get(key) for key in ('record_id', 'method', 'provider', 'publisher', 'admissibility', 'reason_codes', 'published_at', 'time_precision', 'public_time_basis', 'retrieved_at', 'period_end', 'accession', 'source_url', 'raw_content_kind', 'raw_sha256', 'price_basis')}
            result += f'<pre>{escape(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre>'
            if manifest.get('snapshot_id') and record.get('record_id') and record.get('raw_sha256'):
                url = '/api/snapshots/' + quote(str(manifest['snapshot_id']), safe='') + '/sources/' + quote(str(record['record_id']), safe='')
                result += f'<a href="{escape(url, quote=True)}" download>Download saved source</a>'
        result += '</section>'
    return result


def _claim_check_id(snapshot, kind, index):
    return f'{snapshot.get("run_id", "report")}-{kind}-{index + 1}'


def _claim_navigation_section(snapshot: dict[str, Any]) -> str:
    claims = (snapshot.get("final_structured_decision") or {}).get("core_claims") or []
    if not claims:
        return ""
    checks = snapshot.get("report_verification") or {}
    evidence_ids = {item.get("evidence_id") for item in snapshot.get("evidence_ledger") or []}
    rows = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or not claim.get("claim"):
            text = claim.get("statement", "") if isinstance(claim, dict) else str(claim)
            rows.append(f"<li>{escape(str(text))}</li>")
            continue
        links = []
        for check_index, check in enumerate(checks.get("qualitative_claims") or []):
            if check.get("claim_number") == index + 1 and check.get("claim") == claim.get("claim"):
                target = _claim_check_id(snapshot, "claim-check", check_index)
                links.append(f'<a href="#{escape(target, quote=True)}">Source check</a>')
        for check_index, check in enumerate(checks.get("financial_claims") or []):
            evidence_id = check.get("evidence_id")
            if evidence_id and evidence_id in evidence_ids and evidence_id in (claim.get("evidence_ids") or []):
                target = _claim_check_id(snapshot, "calculation", check_index)
                links.append(f'<a href="#{escape(target, quote=True)}">Calculation {escape(evidence_id)}</a>')
        rows.append(f'<li>{escape(str(claim.get("claim") or ""))} {" · ".join(links)}</li>')
    return '<section class="report-section"><h2>Supporting reasons</h2><ul>' + "".join(rows) + "</ul></section>"


def _claim_check_sections(snapshot: dict[str, Any]) -> str:
    verification = snapshot.get("report_verification") or {}
    verdicts = {"supported": "Supported", "contradicted": "Contradicted", "insufficient": "Insufficient evidence"}
    result = ""

    def source_link(record_id, label):
        snapshot_id = (snapshot.get("data_snapshot") or {}).get("snapshot_id")
        if not snapshot_id or not record_id:
            return ""
        url = "/api/snapshots/" + quote(str(snapshot_id), safe="") + "/sources/" + quote(str(record_id), safe="")
        return f'<a href="{escape(url, quote=True)}" download>{label}</a>'

    for index, check in enumerate(verification.get("qualitative_claims") or []):
        target = _claim_check_id(snapshot, "claim-check", index)
        result += f'<section class="report-section" id="{escape(target, quote=True)}"><h2>Qualitative Claim Verification</h2>'
        result += f'<h3>{escape(str(check.get("claim") or ""))}</h3>'
        result += _meta_row("Verification", verdicts.get(check.get("status"), "Unverified"))
        result += f'<p>{escape(str(check.get("reason") or ""))}</p>'
        for citation in check.get("citations") or []:
            result += f'<h4>Quoted evidence</h4><blockquote>{escape(str(citation.get("quote") or ""))}</blockquote>'
            result += _meta_row("Provider", citation.get("provider")) + _meta_row("Published", citation.get("published_at"))
            if citation.get("context") and citation["context"] != citation.get("quote"):
                result += f'<h4>Nearby context</h4><p>{escape(str(citation["context"]))}</p>'
            result += source_link(citation.get("record_id"), "Download saved source")
        result += "</section>"
    for index, check in enumerate(verification.get("financial_claims") or []):
        target = _claim_check_id(snapshot, "calculation", index)
        result += f'<section class="report-section" id="{escape(target, quote=True)}"><h2>Financial Claim Verification</h2>'
        metric = {"revenue_yoy": "Revenue year over year", "operating_margin": "Operating margin"}.get(
            check.get("metric"), "Financial calculation")
        result += f"<h3>{metric}</h3>" + _meta_row("Verification", verdicts.get(check.get("status"), "Unverified"))
        result += f'<p>{escape(str(check.get("reason") or ""))}</p>'
        for label, key in (("Claim", "claim"), ("Formula", "formula"), ("Display scale", "display_scale"),
                           ("SEC filing", "accession"), ("Currency", "currency")):
            if check.get(key) is not None:
                result += _meta_row(label, str(check[key]))
        for label, key in (("Reported percentage", "declared_percentage"), ("Calculated percentage", "rounded_percentage")):
            if check.get(key) is not None:
                result += _meta_row(label, f"{check[key]}%")
        for item in check.get("inputs") or []:
            details = (f'{item.get("label", "")} · {item.get("period_end", "")} · Original {item.get("raw_value", "")}'
                       f' · Normalized {item.get("value", "")} {check.get("currency") or ""}'
                       f' · Row {item.get("line", "")}, column {item.get("column", "")}')
            result += f"<p>{escape(details)}</p>"
        result += source_link(check.get("record_id"), "Download saved SEC source") + "</section>"
    return result


def _source_sections(snapshot: dict[str, Any]) -> str:
    availability = snapshot.get('data_availability') or {}
    mode = snapshot.get('data_mode') or 'unknown'
    summary = f"Data mode: {mode}\n"
    if availability.get('ai_analysis_performed') is False:
        summary += 'No AI analysis was performed. 无法形成建议。\n'
    if mode == 'demo':
        summary += 'Synthetic demo materials. Do not use as live market research.\n'
    if mode == 'unknown':
        summary += 'Historical report: data mode and source isolation have not been verified.\n'
    summary += json.dumps(availability, ensure_ascii=False, indent=2)
    result = _provenance_section(snapshot) + _pre_section('Data Availability / 数据完整性', summary)
    result += _claim_check_sections(snapshot)
    for title, key in [('Source Attempts / 来源尝试', 'source_attempts'), ('Retained Source Materials / 已保留材料', 'source_materials')]:
        if snapshot.get(key):
            result += _pre_section(title, json.dumps(snapshot[key], ensure_ascii=False, indent=2))
    return result


def _recovery_section(snapshot: dict[str, Any]) -> str:
    recorded_decision = snapshot.get("final_structured_decision")
    decision = recorded_decision if isinstance(recorded_decision, dict) else {}
    statuses = (decision.get("decision_status"), snapshot.get("final_signal"))
    if not any(str(value or "").lower().replace("_", " ") == "no recommendation" for value in statuses):
        return ""
    availability = snapshot.get("data_availability") or {}
    verification = snapshot.get("report_verification") or {}
    message = "The saved report contains no recommendation. Review its evidence gap and risks before starting another analysis."
    if availability.get("can_recommend") is False:
        message = "Required research data was unavailable or unverified. Review the recorded source failures before fetching data again."
    elif verification.get("blocks_actionable_recommendation"):
        message = "Recorded validation prevents an actionable recommendation. Review the claim checks and evidence gap before rerunning."
    labels = {"instrument": "Security eligibility", "price_history": "Daily price history",
              "income_statement": "Income statement", "balance_sheet": "Balance sheet", "cashflow": "Cash flow statement"}
    missing = "".join(f'<li>{escape(labels.get(key, key.replace("_", " ")))}</li>' for key in availability.get("missing") or [])
    date = (snapshot.get("research_cutoff") or {}).get("requested_date") or snapshot.get("analysis_date")
    can_refresh = (snapshot.get("status") in {"completed", "error"} and snapshot.get("data_mode") in {"live", "demo"}
                   and isinstance(snapshot.get("ticker"), str) and bool(snapshot["ticker"].strip())
                   and isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date))
    action = ("To fetch sources again, reopen this report in the research workspace and select Refresh data and rerun."
              if can_refresh else "Start a new research run from setup to choose the company and date.")
    return ('<section class="report-section"><h2>Why no recommendation</h2>'
            f'<p>{message}</p><ul>{missing}</ul>'
            f'<p>{action}</p></section>')


def _revision_comparison_section(comparison) -> str:
    if not comparison or comparison.get("status") == "not_applicable":
        return ""
    result = '<section class="report-section"><h2>Changes from previous version</h2>'
    if comparison.get("status") != "available":
        return result + f'<p>{escape(comparison.get("reason") or "Comparison unavailable.")}</p></section>'
    result += _meta_row("Previous version", comparison["previous"].get("version"))
    result += _meta_row("Previous run", comparison["previous"]["run_id"])
    result += _meta_row("Previous report fingerprint", comparison["previous"]["report_hash"])
    result += _meta_row("Current version", comparison["current"].get("version"))
    result += _meta_row("Current run", comparison["current"]["run_id"])
    result += _meta_row("Current report fingerprint", comparison["current"]["report_hash"])
    data_labels = {"same": "Same saved data snapshot", "different": "Different saved data snapshots",
                   "unverified": "Data snapshot identity unverified"}
    result += f'<p>{data_labels[comparison["data_snapshot"]]}</p>'
    changes = comparison["changed_fields"]
    if changes:
        result += '<div class="table-wrap"><table><thead><tr><th>Field</th><th>Previous version</th><th>Current version</th></tr></thead><tbody>'
        for item in changes:
            before = item["before"] if item["before"] is not None else "Not recorded"
            after = item["after"] if item["after"] is not None else "Not recorded"
            result += f'<tr><th>{escape(item["label"])}</th><td><pre>{escape(before)}</pre></td><td><pre>{escape(after)}</pre></td></tr>'
        result += "</tbody></table></div>"
    for label, key in (("Added to this report", "added_evidence"), ("Removed from previous report", "removed_evidence")):
        rows = comparison[key]
        result += f"<h3>{label} ({len(rows)})</h3>"
        for row in rows:
            result += _pre_section(str(row.get("evidence_id") or "Evidence"),
                                   "\n".join(str(row.get(key) or "") for key in
                                             ("claim", "source", "source_date", "excerpt", "interpretation")))
    if not changes and not comparison["added_evidence"] and not comparison["removed_evidence"]:
        result += "<p>No changes in the compared conclusion fields or cited evidence.</p>"
    result += f'<p>Retained evidence items {comparison["unchanged_evidence_count"]}</p></section>'
    return result


def render_report_html(snapshot: dict[str, Any], autoprint: bool = False, comparison: dict | None = None) -> str:
    ticker = snapshot.get("ticker") or snapshot.get("original_input") or "Unknown"
    company_name = snapshot.get("company_name") or ""
    analysis_date = snapshot.get("analysis_date") or "Unknown date"
    report_title = f"{ticker} Research Report"
    page_title = report_title if not company_name else f"{ticker} · {company_name} Research Report"
    analyst_text = ", ".join(snapshot.get("selected_analysts") or []) or "None"
    final_signal = snapshot.get("final_signal") or ("No final recommendation" if snapshot.get("status") == "error" else "Pending")
    final_decision = snapshot.get("final_decision") or "No final decision has been produced yet."
    structured_decision = snapshot.get("final_structured_decision") or {}
    report_quality = snapshot.get("report_quality") or {}
    evidence_ledger = snapshot.get("evidence_ledger") or []
    reports = [report for report in snapshot.get("reports") or [] if report.get("content")]
    tool_calls = snapshot.get("tool_calls") or []
    messages = snapshot.get("messages") or []

    metadata = "".join(
        [
            _meta_row("Ticker", ticker),
            _meta_row("Company", company_name),
            _meta_row("Analysis Date", analysis_date),
            _meta_row("Status", snapshot.get("status")),
            _meta_row("Provider", snapshot.get("provider")),
            _meta_row("Quick Model", snapshot.get("quick_model")),
            _meta_row("Deep Model", snapshot.get("deep_model")),
            _meta_row("Analysts", analyst_text),
            _meta_row("Run ID", snapshot.get("run_id")),
        ]
    )

    objective = OBJECTIVE_LABELS.get(snapshot.get("research_objective"))
    horizon = HORIZON_LABELS.get(snapshot.get("research_horizon"))
    if objective:
        metadata += _meta_row("Research objective", objective)
    if horizon:
        metadata += _meta_row("Requested horizon", horizon)

    model_usage = snapshot.get("model_usage")
    if model_usage:
        metadata += _meta_row("Model calls", f"{model_usage['calls_started']} / {model_usage['model_call_limit'] or 'No limit'}")
        if retries := model_usage.get("calls_retried"):
            metadata += _meta_row("Model retries", retries)
        metadata += _meta_row("Provider-reported tokens",
                              model_usage["reported_total_tokens"] if model_usage["reported_total_tokens"] is not None else "Not reported")
        metadata += _meta_row("Calls reporting total tokens", model_usage["calls_with_reported_total_tokens"])
        for kind in ("input", "output"):
            count = model_usage.get(f"reported_{kind}_tokens")
            if count is not None:
                metadata += _meta_row(f"Reported {kind} tokens", count)
        if model_usage.get("possibly_incomplete"):
            metadata += _meta_row("Usage completeness", "Last recorded usage before interruption")
        metadata += _meta_row("Combined model call time", f"{model_usage['model_elapsed_ms'] / 1000:.1f}s")

    report_sections = "".join(
        _pre_section(report.get("label") or report.get("key") or "Report", report.get("content") or "")
        for report in reports
    )
    if not report_sections:
        report_sections = (
            '<section class="report-section">'
            "<h2>Research Dossier</h2>"
            "<p>No stage reports have been captured for this run yet.</p>"
            "</section>"
        )
    structured_sections = "".join(
        [
            _structured_decision_section(structured_decision if isinstance(structured_decision, dict) else {}),
            _recovery_section(snapshot),
            _revision_comparison_section(comparison),
            _claim_navigation_section(snapshot),
            _source_sections(snapshot),
            _quality_section(report_quality if isinstance(report_quality, dict) else {}),
            _evidence_ledger_section(evidence_ledger if isinstance(evidence_ledger, list) else []),
        ]
    )

    appendix_sections = ""
    if tool_calls:
        appendix_sections += _pre_section(
            "Tool Call Appendix",
            "\n\n".join(
                f"{item.get('timestamp', '')} · {item.get('name', '')}\n{item.get('args', '')}"
                for item in tool_calls
            ),
        )
    if messages:
        appendix_sections += _pre_section(
            "Run Message Appendix",
            "\n\n".join(
                f"{item.get('timestamp', '')} · {item.get('kind', '')}\n{item.get('content', '')}"
                for item in messages
            ),
        )

    auto_print_script = ""
    if autoprint:
        auto_print_script = (
            "<script>"
            "window.addEventListener('load', () => {"
            "window.setTimeout(() => window.print(), 180);"
            "});"
            "</script>"
        )

    subtitle = escape(analysis_date)
    if company_name:
        subtitle = f"{escape(company_name)} · {subtitle}"

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(page_title)}</title>
    <style>
      :root {{
        --ink: #151922;
        --muted: #5d6470;
        --line: rgba(34, 43, 55, 0.16);
        --accent: #176b87;
        --accent-soft: rgba(23, 107, 135, 0.09);
        --panel: #ffffff;
        --panel-strong: #f6f8fa;
        --shadow: 0 18px 38px rgba(20, 29, 43, 0.08);
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        color: var(--ink);
        background: #eef2f4;
        font-family: "Avenir Next", "Segoe UI Variable", "IBM Plex Sans", sans-serif;
      }}

      .page {{
        width: min(1100px, calc(100% - 40px));
        margin: 28px auto 44px;
      }}

      .hero,
      .report-section {{
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
      }}

      .hero {{
        padding: 30px 32px;
      }}

      .eyebrow {{
        margin: 0 0 10px;
        text-transform: uppercase;
        letter-spacing: 0;
        font-size: 0.75rem;
        color: var(--muted);
      }}

      h1,
      h2 {{
        margin: 0;
        font-family: "Iowan Old Style", Georgia, serif;
      }}

      h1 {{
        font-size: 2.7rem;
      }}

      .subtitle {{
        margin: 14px 0 0;
        color: var(--muted);
        line-height: 1.6;
      }}

      .hero-grid {{
        display: grid;
        grid-template-columns: 1.3fr 0.9fr;
        gap: 20px;
        margin-top: 24px;
      }}

      .meta-card,
      .decision-card {{
        padding: 20px;
        border: 1px solid var(--line);
        background: var(--panel-strong);
      }}

      .meta-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px 18px;
      }}

      .meta-row {{
        display: grid;
        gap: 5px;
      }}

      .meta-label {{
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0;
        color: var(--muted);
      }}

      .signal {{
        display: inline-flex;
        align-items: center;
        padding: 8px 12px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 0.82rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0;
      }}

      .decision-copy {{
        margin: 16px 0 0;
        white-space: pre-wrap;
        line-height: 1.62;
        font-family: "SFMono-Regular", "JetBrains Mono", monospace;
        font-size: 0.92rem;
      }}

      .print-note {{
        margin: 18px 0 0;
        color: var(--muted);
        font-size: 0.84rem;
      }}

      .sections {{
        display: grid;
        gap: 18px;
        margin-top: 22px;
      }}

      .report-section {{
        padding: 22px 24px;
      }}

      .report-section h2 {{
        margin-bottom: 14px;
        font-size: 1.3rem;
      }}

      .report-section pre {{
        margin: 0;
        white-space: pre-wrap;
        line-height: 1.66;
        font-family: "SFMono-Regular", "JetBrains Mono", monospace;
        font-size: 0.92rem;
      }}

      .report-section p {{
        margin: 0;
        color: var(--muted);
        line-height: 1.6;
      }}

      .decision-metrics,
      .quality-grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
      }}

      .decision-metrics div,
      .quality-dimension {{
        border: 1px solid var(--line);
        background: var(--panel-strong);
        padding: 12px;
      }}

      .decision-metrics span,
      .quality-dimension span {{
        display: block;
        color: var(--muted);
        font-size: 0.72rem;
        letter-spacing: 0;
        text-transform: uppercase;
      }}

      .decision-metrics strong {{
        display: block;
        margin-top: 6px;
        font-size: 1rem;
      }}

      .brief-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 18px;
        margin-top: 20px;
      }}

      .brief-grid h3,
      .quality-panel h3 {{
        margin: 0 0 8px;
        font-size: 0.88rem;
        text-transform: uppercase;
        letter-spacing: 0;
        color: var(--muted);
      }}

      .brief-grid ul,
      .quality-panel ul {{
        margin: 0;
        padding-left: 18px;
        line-height: 1.6;
      }}

      .quality-header {{
        display: flex;
        align-items: baseline;
        gap: 14px;
        margin-bottom: 8px;
      }}

      .quality-header strong {{
        font-size: 3rem;
        line-height: 1;
        color: var(--accent);
      }}

      .quality-header span {{
        color: var(--muted);
        font-weight: 800;
        letter-spacing: 0;
        text-transform: uppercase;
      }}

      .quality-summary {{
        margin-bottom: 18px !important;
      }}

      .quality-dimension strong {{
        display: block;
        margin-top: 6px;
        font-size: 1.35rem;
      }}

      .quality-dimension p {{
        margin-top: 4px;
        font-size: 0.82rem;
      }}

      .table-wrap {{
        overflow-x: auto;
      }}

      .evidence-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.88rem;
      }}

      .evidence-table th,
      .evidence-table td {{
        border-bottom: 1px solid var(--line);
        padding: 10px 8px;
        text-align: left;
        vertical-align: top;
      }}

      .evidence-table th {{
        color: var(--muted);
        font-size: 0.72rem;
        letter-spacing: 0;
        text-transform: uppercase;
      }}

      .evidence-table span {{
        color: var(--muted);
        font-size: 0.78rem;
      }}

      .evidence-id {{
        font-weight: 800;
        color: var(--accent);
        white-space: nowrap;
      }}

      @media (max-width: 900px) {{
        .hero-grid,
        .meta-grid,
        .decision-metrics,
        .quality-grid,
        .brief-grid {{
          grid-template-columns: 1fr;
        }}

        .page {{
          width: min(100%, calc(100% - 24px));
        }}

        h1 {{
          font-size: 2.1rem;
        }}
      }}

      @media print {{
        @page {{
          size: A4;
          margin: 14mm;
        }}

        body {{
          background: #fff;
        }}

        .page {{
          width: 100%;
          margin: 0;
        }}

        .hero,
        .report-section,
        .meta-card,
        .decision-card {{
          box-shadow: none;
          break-inside: avoid;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <section class="hero">
        <p class="eyebrow">MarketMind AI PDF Export</p>
        <h1>{escape(report_title)}</h1>
        <p class="subtitle">{subtitle}</p>
        <div class="hero-grid">
          <section class="meta-card">
            <h2>Run Metadata</h2>
            <div class="meta-grid">{metadata}</div>
          </section>
          <section class="decision-card">
            <span class="signal">{escape(final_signal)}</span>
            <pre class="decision-copy">{escape(final_decision)}</pre>
            <p class="print-note">Use your browser’s print dialog and choose “Save as PDF” to export this report.</p>
          </section>
        </div>
      </section>
      <section class="sections">
        {_review_section(snapshot)}
        {structured_sections}
        {report_sections}
        {appendix_sections}
      </section>
    </main>
    {auto_print_script}
  </body>
</html>
"""
