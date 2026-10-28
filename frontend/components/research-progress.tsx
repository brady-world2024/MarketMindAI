"use client";

import { useEffect, useState } from "react";
import type { RunSnapshot } from "../lib/api-types";
import { elapsedTime, RESEARCH_PHASES, researchPhase } from "../lib/research-view";

export type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "disconnected" | "finished";

export function ResearchProgress({ snapshot, running, streamState, onReconnect }: {
  snapshot: RunSnapshot | null; running: boolean; streamState: StreamState; onReconnect: () => void;
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
  return <section className="panel progressPanel" aria-labelledby="progress-title">
    <div className="sectionHeader compact"><div><p className="sectionKicker">Research progress</p>
      <h2 id="progress-title">{running && !snapshot ? "Preparing your research" : phase.label}</h2></div>
      <span className="elapsedTime">{elapsedTime(snapshot, now)}</span></div>
    <ol className="phaseSteps" aria-label="Research stages">{RESEARCH_PHASES.map((label, index) => <li key={label}
      className={`${index < phase.index || reviewComplete && index === 4 ? "done" : ""} ${index === phase.index && !reviewComplete ? "current" : ""} ${phase.failed && index === phase.index ? "failed" : ""}`}
      aria-current={index === phase.index && !reviewComplete ? "step" : undefined}><span aria-hidden="true">{index < phase.index || reviewComplete && index === 4 ? "✓" : index + 1}</span>{label}</li>)}</ol>
    <p className="summaryLine" role="status">{snapshot?.latest_update ?? (running ? "Checking input and starting the workflow…" : "Choose a company and start a research run.")}</p>
    {snapshot?.provider === "offline" && <p className="offlineNotice">Offline demo · Uses sample data and local rules. No paid model calls.</p>}
    {connectionInterrupted && <div className="connectionNotice" role="status"><div><strong>{streamState === "reconnecting" ? "Reconnecting to progress updates" : "Progress connection closed"}</strong>
      <p>The analysis may still be running. Reopen the saved run to check its latest status.</p></div>
      <button className="secondaryButton" type="button" onClick={onReconnect}>Reconnect</button></div>}
    {snapshot?.error && <p className="statusBad" role="alert">{snapshot.error}</p>}
  </section>;
}
