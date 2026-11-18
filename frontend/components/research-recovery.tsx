import type { RunSnapshot } from "../lib/api-types";
import { DATA_REQUIREMENTS, canRefreshSavedResearch, isNoRecommendation, recoveryMessage } from "../lib/research-recovery";

type RefreshProps = {snapshot: RunSnapshot; onRefresh?: () => void; busy?: boolean};

export function RefreshResearchAction({ snapshot, onRefresh, busy }: RefreshProps) {
  const date = snapshot.research_cutoff?.requested_date ?? snapshot.analysis_date;
  if (!onRefresh || !canRefreshSavedResearch(snapshot)) return null;
  return <div className="refreshResearchAction">
    <button type="button" className="secondaryButton" disabled={busy} onClick={onRefresh}>Refresh data and rerun</button>
    <p className="summaryLine">Fetch sources again for {snapshot.ticker}, requested {date}. This creates a new report and data snapshot.
      {snapshot.data_mode === "demo" ? " Demo refresh uses offline models." : " Uses your current live AI settings and this run’s budget."}</p>
  </div>;
}

export function ResearchRecovery({ snapshot, onRefresh, busy }: RefreshProps) {
  if (!isNoRecommendation(snapshot)) return null;
  return <section className="researchRecovery" aria-labelledby="recovery-title">
    <h3 id="recovery-title">Why no recommendation</h3>
    <p>{recoveryMessage(snapshot)}</p>
    {!!snapshot.data_availability?.missing?.length && <ul>{snapshot.data_availability.missing.map(key =>
      <li key={key}>{DATA_REQUIREMENTS[key] ?? key.replaceAll("_", " ")}</li>)}</ul>}
    <a href="#research-data-sources">Review saved sources</a>
    {!canRefreshSavedResearch(snapshot) && <p>Start a new research run from setup to choose the company and date.</p>}
    <RefreshResearchAction snapshot={snapshot} onRefresh={onRefresh} busy={busy} />
  </section>;
}
