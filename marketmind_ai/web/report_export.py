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


def render_report_html(snapshot: dict[str, Any], autoprint: bool = False) -> str:
    ticker = snapshot.get("ticker") or snapshot.get("original_input") or "Unknown"
    company_name = snapshot.get("company_name") or ""
    analysis_date = snapshot.get("analysis_date") or "Unknown date"
    report_title = f"{ticker} Research Report"
    page_title = report_title if not company_name else f"{ticker} · {company_name} Research Report"
    analyst_text = ", ".join(snapshot.get("selected_analysts") or []) or "None"
    final_signal = snapshot.get("final_signal") or "Pending"
    final_decision = snapshot.get("final_decision") or "No final decision has been produced yet."
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
        --ink: #1f1916;
        --muted: #64584e;
        --line: rgba(62, 42, 28, 0.14);
        --accent: #205d57;
        --accent-soft: rgba(32, 93, 87, 0.08);
        --panel: #fffaf3;
        --panel-strong: #fffdf8;
        --shadow: 0 20px 44px rgba(39, 25, 15, 0.09);
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(225, 197, 164, 0.34), transparent 26%),
          linear-gradient(180deg, #f7f1e7 0%, #efe3d4 100%);
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
        letter-spacing: 0.18em;
        font-size: 0.75rem;
        color: var(--muted);
      }}

      h1,
      h2 {{
        margin: 0;
        font-family: "Iowan Old Style", Georgia, serif;
      }}

      h1 {{
        font-size: clamp(2rem, 4vw, 3.4rem);
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
        letter-spacing: 0.12em;
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
        letter-spacing: 0.12em;
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

      @media (max-width: 900px) {{
        .hero-grid,
        .meta-grid {{
          grid-template-columns: 1fr;
        }}

        .page {{
          width: min(100%, calc(100% - 24px));
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
        {report_sections}
        {appendix_sections}
      </section>
    </main>
    {auto_print_script}
  </body>
</html>
"""
