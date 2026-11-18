"use client";

import { useEffect, useRef, useState } from "react";
import type { RevisionComparison, RunSnapshot } from "../lib/api-types";

const dataLabels = {
  same: "Same saved data snapshot",
  different: "Different saved data snapshots",
  unverified: "Data snapshot identity unverified",
};

export function ComparisonResult({ comparison }: { comparison: RevisionComparison }) {
  if (comparison.status !== "available") return <p className="summaryLine">
    {comparison.reason ?? "Comparison unavailable."}
  </p>;
  return <div className="comparisonResult">
    <h3>Changes from previous version</h3>
    <p>Version {comparison.previous.version ?? "?"} → {comparison.current.version ?? "?"}
      {" · "}{dataLabels[comparison.data_snapshot]}</p>
    <div className="comparisonFields">{comparison.changed_fields.map(item => <article key={item.field}>
      <h4>{item.label}</h4>
      <div className="comparisonPair">
        <div><small>Previous version</small><p>{item.before ?? "Not recorded"}</p></div>
        <div><small>Current version</small><p>{item.after ?? "Not recorded"}</p></div>
      </div>
    </article>)}</div>
    {([
      ["Added to this report", comparison.added_evidence],
      ["Removed from previous report", comparison.removed_evidence],
    ] as const).map(([label, rows]) => <div key={label}>
      <h4>{label} ({rows.length})</h4>
      {rows.map((row, index) => <article className="comparisonEvidence" key={index}>
        <strong>{row.evidence_id}</strong><p>{row.claim}</p>
        <p>{[row.source, row.source_date].filter(Boolean).join(" · ")}</p>
        {row.excerpt && <blockquote>{row.excerpt}</blockquote>}
        {row.interpretation && <p>{row.interpretation}</p>}
      </article>)}
    </div>)}
    {!comparison.changed_fields.length && !comparison.added_evidence.length && !comparison.removed_evidence.length &&
      <p>No changes in the compared conclusion fields or cited evidence.</p>}
    <p>Retained evidence items {comparison.unchanged_evidence_count}</p>
    <details className="reportExtra"><summary>Compared report versions</summary>
      <p>Previous run {comparison.previous.run_id} · {comparison.previous.report_hash}</p>
      <p>Current run {comparison.current.run_id} · {comparison.current.report_hash}</p>
    </details>
  </div>;
}

export function RevisionComparisonPanel({ snapshot, apiBaseUrl }: { snapshot: RunSnapshot | null; apiBaseUrl: string }) {
  const identity = `${snapshot?.run_id}:${snapshot?.review?.report_hash}:${snapshot?.review?.parent_run_id}`;
  const activeIdentity = useRef(identity);
  activeIdentity.current = identity;
  const controller = useRef<AbortController | null>(null);
  const [result, setResult] = useState<{
    identity: string; loading: boolean; comparison?: RevisionComparison; error?: string;
  } | null>(null);
  useEffect(() => () => controller.current?.abort(), [identity]);
  if (!snapshot?.review?.parent_run_id) return null;
  const view = result?.identity === identity ? result : null;

  async function load() {
    if (!snapshot?.review?.parent_run_id) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const isCurrent = () => !request.signal.aborted && activeIdentity.current === identity;
    setResult({ identity, loading: true });
    try {
      const response = await fetch(`${apiBaseUrl}/api/runs/${encodeURIComponent(snapshot.run_id)}/comparison`,
        { signal: request.signal });
      if (!response.ok) throw new Error("The comparison could not be loaded. Try again.");
      const comparison = await response.json() as RevisionComparison;
      if (!isCurrent()) return;
      if (comparison.status === "available" && (comparison.current.run_id !== snapshot.run_id
          || comparison.current.report_hash !== snapshot.review.report_hash
          || comparison.previous.run_id !== snapshot.review.parent_run_id)) {
        throw new Error("The comparison does not match this report version. Reload the report.");
      }
      setResult({ identity, loading: false, comparison });
    } catch (cause) {
      if (isCurrent()) setResult({ identity, loading: false,
        error: cause instanceof Error ? cause.message : "Comparison unavailable. Try again." });
    }
  }

  return <section className="revisionComparison" aria-label="Revision comparison">
    <button type="button" className="secondaryButton" onClick={() => void load()} disabled={view?.loading}>
      {view?.loading ? "Comparing versions…" : view?.error ? "Retry comparison" : "Compare with previous version"}
    </button>
    {view?.error && <p className="statusBad" role="alert">{view.error}</p>}
    {view?.comparison && <ComparisonResult comparison={view.comparison} />}
  </section>;
}
