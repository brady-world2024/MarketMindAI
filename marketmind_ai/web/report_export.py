from __future__ import annotations

from html import escape
from typing import Any


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


def render_report_html(snapshot: dict[str, Any], autoprint: bool = False) -> str:
    ticker = snapshot.get("ticker") or snapshot.get("original_input") or "Unknown"
    company_name = snapshot.get("company_name") or ""
    analysis_date = snapshot.get("analysis_date") or "Unknown date"
    report_title = f"{ticker} Research Report"
    page_title = report_title if not company_name else f"{ticker} · {company_name} Research Report"
    analyst_text = ", ".join(snapshot.get("selected_analysts") or []) or "None"
    final_signal = snapshot.get("final_signal") or "Pending"
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
        {structured_sections}
        {report_sections}
        {appendix_sections}
      </section>
    </main>
    {auto_print_script}
  </body>
</html>
"""
