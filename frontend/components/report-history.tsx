"use client";

import { useEffect, useRef, useState } from "react";
import type { ReviewSummary } from "../lib/api-types";
import { filterReviews } from "../lib/research-view";

const FILTERS = [
  ["all", "All reports"], ["pending", "Awaiting review"], ["approved", "Approved"],
  ["changes_requested", "Changes requested"], ["rejected", "Rejected"],
] as const;
const LABELS = Object.fromEntries(FILTERS);

export function ReportHistory({ apiBaseUrl, currentRunId, reviewStatus, running, onOpenRun }: {
  apiBaseUrl: string; currentRunId?: string | null; reviewStatus?: string; running: boolean; onOpenRun: (id: string) => Promise<void>;
}) {
  const [items, setItems] = useState<ReviewSummary[]>([]);
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestGeneration = useRef(0);

  async function loadReports() {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/reviews`);
      if (!response.ok) throw new Error("Saved reports could not be loaded. Try refreshing the list.");
      const result = await response.json() as ReviewSummary[];
      if (generation === requestGeneration.current) setItems(result);
    } catch (cause) {
      if (generation === requestGeneration.current) setError(cause instanceof Error ? cause.message : "Unable to load saved reports.");
    } finally { if (generation === requestGeneration.current) setLoading(false); }
  }

  useEffect(() => {
    void loadReports();
    return () => { requestGeneration.current += 1; };
  }, [apiBaseUrl, currentRunId, reviewStatus]);

  async function openReport(id: string) {
    setOpening(id);
    setError(null);
    try { await onOpenRun(id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "This report could not be opened."); }
    finally { setOpening(null); }
  }

  const filtered = filterReviews(items, status, query);
  return <section className="panel historyPanel" aria-labelledby="history-title">
    <div className="sectionHeader compact"><div><p className="sectionKicker">Your research</p><h2 id="history-title">Saved reports</h2></div>
      <button type="button" className="secondaryButton compactButton" disabled={loading} onClick={() => void loadReports()}>{loading ? "Loading…" : "Refresh"}</button></div>
    <label className="field"><span className="visuallyHidden">Search saved reports</span>
      <input type="search" placeholder="Search company, ticker or date" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    <div className="historyFilters" role="group" aria-label="Filter reports by review status">{FILTERS.map(([value, label]) =>
      <button key={value} type="button" aria-pressed={status === value} className={status === value ? "active" : ""}
        onClick={() => setStatus(value)}>{label}</button>)}</div>
    <p className="historyCount" aria-live="polite">{loading ? "Loading saved reports…" : `${filtered.length} of ${items.length} reports`}</p>
    {filtered.length ? <ul className="historyList">{filtered.map((item) => <li key={item.run_id}>
      <button className={`historyItem ${item.run_id === currentRunId ? "selected" : ""}`} type="button"
        disabled={running || opening !== null} aria-current={item.run_id === currentRunId ? "true" : undefined}
        title={`Run ${item.run_id}`} onClick={() => void openReport(item.run_id)}>
        <div><strong>{item.ticker}</strong><span>{item.analysis_date} · Version {item.review.version}</span>
          <small>{item.review.parent_run_id ? "Revised report · " : ""}{new Date(item.review.requested_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small></div>
        <span className={`reviewBadge ${item.review.status}`}>{opening === item.run_id ? "Opening…" : LABELS[item.review.status]}</span>
      </button>
    </li>)}</ul> : !loading && <p className="emptyState">{items.length ? "No reports match these filters. Try another search or review status." : "Your completed research will appear here, ready to reopen and review."}</p>}
    {running && <p className="summaryLine subtle">Finish the current run before opening another report.</p>}
    {error && <p className="statusBad" role="alert">{error}</p>}
  </section>;
}
