import type { RunSnapshot } from "../lib/api-types";
import { DATA_REQUIREMENTS as requirements } from "../lib/research-recovery";
const requiredKeys = ["instrument", "price_history", "income_statement", "balance_sheet", "cashflow"];

const reasons: Record<string, string> = {
  instrument_unverified: "Common stock or exchange could not be verified",
  instrument_public_time_unverified: "Security listing could not be verified at the cutoff",
  unsupported_exchange: "This exchange is outside the supported NYSE and Nasdaq listings",
  unsupported_security_type: "This security type is outside the supported common stocks",
  fewer_than_50_valid_daily_bars: "Fewer than 50 valid daily bars",
  required_session_close_missing: "The effective session’s closing price is missing",
  price_adjustment_basis_unverified: "Price units at the cutoff could not be verified",
  missing_income_statement: "Income statement is missing",
  missing_balance_sheet: "Balance sheet is missing",
  missing_cashflow: "Cash flow statement is missing",
  public_time_unverified: "Publication time could not be verified",
  published_after_cutoff: "Published after the cutoff",
  statement_identity_unverified: "SEC filing identity could not be verified",
  no_time_verified_news: "No news with a verified publication time",
  current_snapshot_not_time_verified: "Company overview could not be verified at the cutoff",
};

export function DataPreflightCard({ snapshot, running }: { snapshot: RunSnapshot | null; running: boolean }) {
  const data = snapshot?.data_availability;
  const cutoff = snapshot?.research_cutoff;
  const checking = running && !snapshot?.job_status;
  const state = data?.can_recommend === true ? "passed" : data?.can_recommend === false ? "blocked" :
    checking ? "checking" : "unknown";
  const label = {
    passed: "Data preflight passed",
    blocked: "Required data incomplete",
    checking: "Checking required data…",
    unknown: "Preflight result unavailable",
  }[state];
  const mode = snapshot?.data_mode === "demo" ? "Demo data" : snapshot?.data_mode === "live" ? "Live data" : null;
  const entries = Object.entries(requirements).filter(([key]) =>
    requiredKeys.includes(key) || data?.requirements?.[key] || data?.missing?.includes(key));
  const close = cutoff?.cutoff_at_local
    ? `${cutoff.cutoff_at_local.slice(11, 16)} ${cutoff.market_timezone ?? ""}`.trim()
    : cutoff?.cutoff_at ? `${cutoff.cutoff_at.slice(11, 16)} UTC` : null;
  return <section className="preflightCard" data-state={state} aria-labelledby="preflight-title">
    <div className="preflightHeader">
      <h3 id="preflight-title">Data preflight</h3>
      <strong role="status">{label}</strong>
    </div>
    {(mode || cutoff?.effective_session_date || cutoff?.requested_date) && <p className="preflightCutoff">
      {[
        mode,
        cutoff?.requested_date && `Requested ${cutoff.requested_date}`,
        cutoff?.effective_session_date && `Session ${cutoff.effective_session_date}`,
        close && `Close ${close}`,
      ].filter(Boolean).join(" · ")}
    </p>}
    {data && <dl className="preflightRows">{entries.map(([key, title]) => {
      const entry = data.requirements?.[key];
      const missing = data.missing?.includes(key);
      const status = entry?.available === true ? "Available" :
        entry?.available === false || missing ? "Unavailable" : "Not checked";
      const provider = entry?.provider ?? (key === "instrument" ? snapshot?.instrument_eligibility?.provider : null);
      const source = provider === "sec" ? "SEC" : provider === "offline" ? null : provider;
      const details = [
        entry?.valid_count != null && entry.minimum_count != null &&
          `${entry.valid_count} / ${entry.minimum_count} valid daily bars`,
        entry?.period_end && `Period ended ${entry.period_end}`,
        source,
      ].filter(Boolean);
      return <div key={key} className="preflightRow">
        <dt>{title}{entry?.required === false && <small>Optional</small>}</dt>
        <dd>
          <span className="preflightRowStatus">{status}</span>
          {details.length > 0 && <span>{details.join(" · ")}</span>}
          {!!entry?.reason_codes?.length && <span>{entry.reason_codes.map((code) =>
            Object.hasOwn(reasons, code) ? reasons[code] : code.replaceAll("_", " ")).join(" · ")}</span>}
        </dd>
      </div>;
    })}</dl>}
    {state === "blocked" && <p className="preflightNext">
      No recommendation. {data?.ai_analysis_performed === false && "AI analysis skipped. "}
      <a href="#research-data-sources">View data sources</a>
    </p>}
  </section>;
}
