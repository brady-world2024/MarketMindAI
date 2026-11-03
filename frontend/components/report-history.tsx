"use client";

import { useEffect, useRef, useState } from "react";
import type { ReviewSummary } from "../lib/api-types";
import { filterReviews } from "../lib/research-view";
import { WorkbenchIcon } from "./workbench-icon";

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
    <div className="sectionHeader compact"><h2 id="history-title"><WorkbenchIcon name="library" size={16} />Saved reports</h2>
      <button type="button" className="iconButton" disabled={loading} aria-label="Refresh saved reports" title="Refresh saved reports"
        onClick={() => void loadReports()}><WorkbenchIcon name="refresh" size={15} /></button></div>
    <label className="field"><span className="visuallyHidden">Search saved reports</span>
      <input type="search" placeholder="Search ticker or date" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    <label className="historyFilter"><span className="visuallyHidden">Filter reports by review status</span>
      <select value={status} onChange={(event) => setStatus(event.target.value)}>{FILTERS.map(([value, label]) =>
        <option key={value} value={value}>{label}</option>)}</select></label>
    <p className="historyCount" aria-live="polite">{loading ? "Loading saved reports…" : `${filtered.length} of ${items.length} reports`}</p>
    {filtered.length ? <ul className="historyList">{filtered.map((item) => <li key={item.run_id}>
      <button className={`historyItem ${item.run_id === currentRunId ? "selected" : ""}`} type="button"
        disabled={running || opening !== null} aria-current={item.run_id === currentRunId ? "true" : undefined}
        title={`Run ${item.run_id}`} onClick={() => void openReport(item.run_id)}>
        <div><div className="historyItemHeading"><strong>{item.ticker}</strong><small>v{item.review.version}</small></div><span>{item.analysis_date}</span>
          {item.review.parent_run_id && <small>Revised report</small>}</div>
        <span className={`reviewBadge ${item.review.status}`}>{opening === item.run_id ? "Opening…" : LABELS[item.review.status]}</span>
      </button>
    </li>)}</ul> : !loading && !error && <div className="historyEmpty"><WorkbenchIcon name="document" size={24} /><strong>{items.length ? "No matching reports" : "A fresh start"}</strong>
      <p>{items.length ? "Try another ticker, date or review status." : "Completed research will appear here. Reopen it anytime to read and review."}</p></div>}
    {running && <p className="summaryLine subtle">Finish the current run before opening another report.</p>}
    {error && <p className="statusBad" role="alert">{error}</p>}
  </section>;
}
