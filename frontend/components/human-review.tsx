"use client";

import { useEffect, useState } from "react";
import type { ReviewDecision, ReviewSummary, RunCreatedResponse, RunSnapshot } from "../lib/api-types";

const STATUS_LABELS = {
  pending: "Awaiting human review",
  approved: "Approved",
  rejected: "Rejected",
  changes_requested: "Changes requested",
};

async function readResponse<T>(response: Response): Promise<T> {
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg).join("; ")
      : detail?.message ?? "Unable to save the review. Refresh the report and try again.";
    throw new Error(message);
  }
  return body as T;
}

type Props = {
  snapshot: RunSnapshot | null;
  apiBaseUrl: string;
  running: boolean;
  onOpenRun: (runId: string) => Promise<void>;
  onSnapshot: (snapshot: RunSnapshot) => void;
  onRevision: (run: RunCreatedResponse) => void;
};

export function HumanReviewPanel({ snapshot, apiBaseUrl, running, onOpenRun, onSnapshot, onRevision }: Props) {
  const [queue, setQueue] = useState<ReviewSummary[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [revisionKey, setRevisionKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const review = snapshot?.review;

  async function refreshQueue() {
    setLoadingQueue(true);
    try {
      setQueue(await readResponse<ReviewSummary[]>(await fetch(`${apiBaseUrl}/reviews`)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load review history.");
    } finally {
      setLoadingQueue(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void fetch(`${apiBaseUrl}/reviews`).then(readResponse<ReviewSummary[]>).then((items) => {
      if (!cancelled) setQueue(items);
    }).catch((cause) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : "Unable to load review history.");
    });
    return () => { cancelled = true; };
  }, [apiBaseUrl, snapshot?.run_id, review?.status]);

  useEffect(() => {
    setComment("");
    setRevisionKey("");
    setError(null);
  }, [snapshot?.run_id]);

  async function decide(decision: ReviewDecision) {
    if (!snapshot || !review || busy) return;
    if (!reviewer.trim()) { setError("Enter your reviewer name."); return; }
    if (decision !== "approve" && !comment.trim()) {
      setError("Explain what needs to change or why you are rejecting this report."); return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await readResponse<RunSnapshot>(await fetch(`${apiBaseUrl}/runs/${snapshot.run_id}/review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, version: review.version, report_hash: review.report_hash,
          reviewer: reviewer.trim(), comment: comment.trim() }),
      }));
      onSnapshot(next);
      await refreshQueue();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Review could not be saved.");
    } finally { setBusy(false); }
  }

  async function revise() {
    if (!snapshot || !review || busy) return;
    setBusy(true);
    setError(null);
    try {
      const run = await readResponse<RunCreatedResponse>(await fetch(`${apiBaseUrl}/runs/${snapshot.run_id}/revise`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: review.version, report_hash: review.report_hash, api_key: revisionKey.trim() || null }),
      }));
      setRevisionKey("");
      onRevision(run);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The revised run could not be started.");
    } finally { setBusy(false); }
  }

  async function openRun(id: string) {
    setBusy(true);
    setError(null);
    try { await onOpenRun(id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to open this report."); }
    finally { setBusy(false); }
  }

  const actionableBlocked = snapshot?.final_structured_decision?.decision_status === "Actionable"
    && snapshot?.report_verification?.blocks_actionable_recommendation;
  const pending = review?.status === "pending";
  const decision = snapshot?.final_structured_decision;
  const issues = [...(snapshot?.report_verification?.issues ?? []), ...(snapshot?.report_quality?.issues ?? [])];
  const needsRevisionKey = snapshot && !["offline", "ollama"].includes(snapshot.provider);

  return (
    <section className="panel reviewPanel" aria-labelledby="review-title">
      <div className="sectionHeader compact">
        <div><p className="sectionKicker">Human review</p><h2 id="review-title">Review the research</h2></div>
        {review && <span className={`reviewBadge ${review.status}`}>{STATUS_LABELS[review.status]}</span>}
      </div>
      <div className="reviewQueue">
        <label className="field"><span>Recent reports</span>
          <select aria-label="Recent reports" value={queue.some((item) => item.run_id === snapshot?.run_id) ? snapshot?.run_id : ""}
            disabled={busy || running} onChange={(event) => { if (event.target.value) void openRun(event.target.value); }}>
            <option value="">Choose a report to review</option>
            {queue.map((item) => <option key={item.run_id} value={item.run_id}>
              {item.ticker} · {item.analysis_date} · v{item.review.version} · {STATUS_LABELS[item.review.status]} · {item.run_id}
            </option>)}
          </select>
        </label>
        <button type="button" className="secondaryButton" disabled={loadingQueue || busy} onClick={() => void refreshQueue()}>
          {loadingQueue ? "Loading…" : "Refresh reports"}
        </button>
      </div>

      {!review ? <p className="emptyState">{snapshot?.status === "running" ? "Review becomes available when analysis and validation finish."
        : snapshot?.final_decision ? "No human review is recorded for this legacy report."
        : "Complete a research run or choose a saved report. Drafts stay available after you close the page."}</p> : <>
        <div className="reviewReceipt">
          <strong>Version {review.version}</strong><span>Analysis {snapshot?.status}</span>
          <code title={review.report_hash}>{review.report_hash.slice(0, 16)}</code>
        </div>
        <p className="summaryLine">{review.status === "approved" ? "This version was accepted by a reviewer and is available to decision memory."
          : "This report has not been accepted into decision memory. You can inspect and export it with its review status."}</p>
        {review.parent_run_id && <button type="button" className="reviewTextButton" disabled={busy || running}
          onClick={() => void openRun(review.parent_run_id!)}>View previous version</button>}
        {review.feedback && <div className="reviewFeedback"><strong>Feedback for this version</strong><p>{review.feedback}</p>
          {snapshot?.provider === "offline" && <small>Offline mode uses deterministic fixtures. The feedback is recorded for review; no live model rewrites the analysis.</small>}</div>}

        <details className="reviewDetails" open>
          <summary>Validation and evidence</summary>
          <p className="summaryLine">Automated checks: {snapshot?.report_verification?.status ?? "Not available"}
            {snapshot?.report_quality && ` · Quality: ${snapshot.report_quality.grade ?? "Unscored"} (${snapshot.report_quality.score ?? "—"}/100)`}</p>
          {snapshot?.report_quality?.summary && <p>{snapshot.report_quality.summary}</p>}
          {issues.length > 0 && <ul>{issues.map((issue, i) => <li key={`${issue.code}-${i}`}>{issue.message ?? issue.code}</li>)}</ul>}
          {decision?.evidence_gap && <p><strong>Evidence gap:</strong> {decision.evidence_gap}</p>}
          {(decision?.key_risks ?? []).length > 0 && <><strong>Key risks</strong><ul>{decision?.key_risks?.map((risk, i) => <li key={i}>{risk}</li>)}</ul></>}
          {decision?.counterargument && <p><strong>Counterargument:</strong> {decision.counterargument}</p>}
          {decision?.counterargument_response && <p><strong>Response:</strong> {decision.counterargument_response}</p>}
          <div className="reviewTableWrap"><table className="reviewTable"><caption>Evidence available for this report version</caption>
            <thead><tr><th>Evidence</th><th>Source</th><th>Excerpt</th></tr></thead>
            <tbody>{(snapshot?.evidence_ledger ?? []).map((item, i) => <tr key={`${item.evidence_id}-${i}`}>
              <td><strong>{item.evidence_id}</strong><p>{item.claim}</p></td>
              <td>{item.source}<br />{item.source_date}<br />{item.freshness}<br />
                {item.url && (/^https?:\/\//i.test(item.url) ? <a href={item.url} target="_blank" rel="noreferrer">Open source</a> : <small>{item.url}</small>)}</td>
              <td>{item.excerpt}<p>{item.interpretation}</p></td>
            </tr>)}</tbody>
          </table></div>
          {(snapshot?.evidence_ledger ?? []).length === 0 && <p className="emptyState">No evidence ledger was captured.</p>}
        </details>

        {pending && <fieldset className="reviewForm" disabled={busy || running}>
          <legend>Review this version</legend>
          <label className="field"><span>Reviewer name</span><input value={reviewer} maxLength={120}
            onChange={(event) => setReviewer(event.target.value)} autoComplete="name" />
            <small>Self-reported name for this local review record.</small></label>
          <label className="field"><span>Review comments</span><textarea rows={3} maxLength={4000} value={comment}
            onChange={(event) => setComment(event.target.value)} placeholder="Explain concerns, missing evidence, or requested changes." />
            <small>Required when rejecting a report or requesting changes.</small></label>
          <p className="summaryLine">Approval accepts this report version. It preserves automated validation limits and does not place a trade. Human approval does not guarantee factual correctness.</p>
          <div className="reviewActions">
            <button type="button" className="primaryButton" disabled={!!actionableBlocked || !reviewer.trim()}
              onClick={() => void decide("approve")}>Approve report</button>
            <button type="button" className="secondaryButton" disabled={!reviewer.trim() || !comment.trim()}
              onClick={() => void decide("request_changes")}>Request changes</button>
            <button type="button" className="secondaryButton reviewReject" disabled={!reviewer.trim() || !comment.trim()}
              onClick={() => void decide("reject")}>Reject report</button>
          </div>
        </fieldset>}

        {review.status === "changes_requested" && <div className="reviewForm">
            {review.revision_run_id && <button type="button" className="secondaryButton" disabled={busy || running}
              onClick={() => void openRun(review.revision_run_id!)}>Open revised run</button>}
            <p>{review.revision_run_id ? "If the revised run was interrupted or failed, resume or retry it here. The same revised run is reused."
              : "A new analysis will use the original settings and the reviewer’s feedback. It will need a new review."}</p>
            {needsRevisionKey && <label className="field"><span>API key for {snapshot?.provider}</span>
              <input type="password" autoComplete="off" value={revisionKey} onChange={(event) => setRevisionKey(event.target.value)} />
              <small>Enter the original provider’s key again for this revision.</small></label>}
            <button type="button" className="primaryButton" disabled={busy || running || (!!needsRevisionKey && !revisionKey.trim())}
              onClick={() => void revise()}>{review.revision_run_id ? "Resume or retry revised report" : "Generate revised report"}</button>
          </div>}

        {review.history.length > 0 && <details className="reviewDetails" open><summary>Review history</summary>
          {review.history.map((item, i) => <article key={`${item.reviewed_at}-${i}`} className="reviewAudit">
            <strong>{item.decision.replaceAll("_", " ")} · {item.reviewer}</strong>
            <small>{item.reviewed_at} · Version {item.version}</small><p>{item.comment || "No additional comments."}</p>
          </article>)}
        </details>}
      </>}
      {busy && <p className="summaryLine" role="status">Saving or loading report…</p>}
      {error && <p className="statusBad" role="alert">{error} <button type="button" className="reviewTextButton" disabled={busy || !snapshot}
        onClick={() => snapshot && void openRun(snapshot.run_id)}>Reload report</button></p>}
    </section>
  );
}
