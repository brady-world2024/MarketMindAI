"use client";

import { useEffect, useState } from "react";
import type { RunSnapshot } from "../lib/api-types";
import { elapsedTime, RESEARCH_PHASES, researchPhase } from "../lib/research-view";
import { DataPreflightCard } from "./data-preflight-card";
import { WorkbenchIcon } from "./workbench-icon";

export type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "disconnected" | "finished";

export function ResearchProgress({ snapshot, running, streamState, onReconnect, onCancel, cancelling }: {
  snapshot: RunSnapshot | null; running: boolean; streamState: StreamState; onReconnect: () => void;
  onCancel?: () => void; cancelling?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const phase = researchPhase(snapshot);
  const reviewComplete = snapshot?.review?.status === "approved";
  const connectionInterrupted = streamState === "reconnecting" || streamState === "disconnected";
  const noAnalysis = snapshot?.data_availability?.ai_analysis_performed === false
    && snapshot?.data_availability?.can_recommend === false;
  return <section className="panel progressPanel" aria-labelledby="progress-title">
    <div className="sectionHeader compact"><div><p className="sectionKicker">Research progress</p>
      <h2 id="progress-title">{running && !snapshot ? "Preparing your research" : phase.label}</h2></div>
      <span className="elapsedTime"><WorkbenchIcon name="clock" size={14} />{elapsedTime(snapshot, now)}</span></div>
    {noAnalysis ? <p className="offlineNotice">Preflight stopped · AI research stages skipped. 未进行 AI 分析。</p> : <ol className="phaseSteps" aria-label="Research stages">{RESEARCH_PHASES.map((label, index) => <li key={label}
      className={`${index < phase.index || reviewComplete && index === 4 ? "done" : ""} ${index === phase.index && !reviewComplete ? "current" : ""} ${phase.failed && index === phase.index ? "failed" : ""}`}
      aria-current={index === phase.index && !reviewComplete ? "step" : undefined}><span aria-hidden="true">{index < phase.index || reviewComplete && index === 4 ? "✓" : index + 1}</span>{label}</li>)}</ol>}
    <p className="summaryLine" role="status">{snapshot?.latest_update ?? (running ? "Checking input and starting the workflow…" : "Choose a company and start a research run.")}</p>
    <DataPreflightCard snapshot={snapshot} running={running} />
    {snapshot?.provider === "offline" && <p className="offlineNotice">Offline demo · Uses sample data and local rules. No paid model calls.</p>}
    {snapshot?.model_usage && <div className="summaryLine" aria-label="Model usage">
      <p>Model calls {snapshot.model_usage.calls_started}{snapshot.model_usage.model_call_limit !== null
        ? ` / ${snapshot.model_usage.model_call_limit}` : " · no limit"}
        {snapshot.model_usage.calls_failed > 0 && ` · ${snapshot.model_usage.calls_failed} failed`}</p>
      <p>Provider-reported tokens {snapshot.model_usage.reported_total_tokens ?? "Not reported"}
        {snapshot.model_usage.reported_total_tokens !== null &&
          ` · ${snapshot.model_usage.calls_with_reported_total_tokens} of ${snapshot.model_usage.calls_started} calls reported a total`}</p>
      {(snapshot.model_usage.reported_input_tokens != null || snapshot.model_usage.reported_output_tokens != null) &&
        <p>Reported input {snapshot.model_usage.reported_input_tokens ?? "—"} · Reported output {snapshot.model_usage.reported_output_tokens ?? "—"}</p>}
      {snapshot.model_usage.possibly_incomplete && <p>Last recorded usage before interruption. Some calls may be missing.</p>}
      <p>Combined model call time {(snapshot.model_usage.model_elapsed_ms / 1000).toFixed(1)}s</p>
    </div>}
    {running && onCancel && (
      <div className="connectionNotice">
        <button className="secondaryButton" type="button" onClick={onCancel}
          disabled={cancelling || snapshot?.job_status === "stopping"}>
          {cancelling || snapshot?.job_status === "stopping" ? "Stopping…" : "Cancel research"}
        </button>
        <small>Requests already sent may finish and incur charges.</small>
      </div>
    )}
    {connectionInterrupted && <div className="connectionNotice" role="status"><div><strong>{streamState === "reconnecting" ? "Reconnecting to progress updates" : "Progress connection closed"}</strong>
      <p>The analysis may still be running. Reopen the saved run to check its latest status.</p></div>
      <button className="secondaryButton" type="button" onClick={onReconnect}>Reconnect</button></div>}
    {snapshot?.error && <p className="statusBad" role="alert">{snapshot.error}</p>}
  </section>;
}
