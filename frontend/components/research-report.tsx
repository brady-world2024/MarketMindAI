import type { RunSnapshot } from "../lib/api-types";
import { ReportText, revealEvidence } from "./report-text";
import { WorkbenchIcon } from "./workbench-icon";
import { DataSourcesPanel } from "./data-sources-panel";

type Props = { snapshot: RunSnapshot; onOpenReport: () => void; onExport: () => void;
  apiBaseUrl?: string; onReplay?: () => void; replayBusy?: boolean };
const REVIEW_LABELS = { pending: "Awaiting review", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested" };

export function ResearchReport({ snapshot, onOpenReport, onExport, apiBaseUrl, onReplay, replayBusy }: Props) {
  const decision = snapshot.final_structured_decision;
  const evidenceIds = (snapshot.evidence_ledger ?? []).map((item) => item.evidence_id).filter((id): id is string => !!id);
  const reasons = decision?.core_claims?.length ? decision.core_claims : (snapshot.evidence_ledger ?? []).slice(0, 3)
    .filter((item) => item.claim).map((item) => ({ claim: item.claim!, evidence_ids: item.evidence_id ? [item.evidence_id] : [] }));
  const status = snapshot.review?.status;
  const noRecommendation = decision?.decision_status === "No Recommendation" || /no.recommendation/i.test(snapshot.final_signal ?? "");
  const signalTone = noRecommendation ? "abstain" : /sell|underweight/i.test(snapshot.final_signal ?? "") ? "negative" : /hold/i.test(snapshot.final_signal ?? "") ? "neutral" : "";
  return <section className="panel resultPanel" aria-labelledby="result-title">
    <div className="sectionHeader compact">
      <div><p className="sectionKicker">Research report</p><h2 id="result-title">{snapshot.ticker}<span className="reportTitleSuffix"> / Research brief</span></h2>
        <p className="summaryLine subtle">{snapshot.company_name ?? snapshot.original_input} · {snapshot.analysis_date}</p></div>
      <div className="reportActions"><button type="button" className="secondaryButton" onClick={onOpenReport}><WorkbenchIcon name="document" size={14} />Open report</button>
        <button type="button" className="secondaryButton" onClick={onExport}>Export PDF<WorkbenchIcon name="arrow" size={14} /></button></div>
    </div>
    <div className="resultHeadline">
      <div className="verdict"><span className="sectionKicker">Research view</span><span className={`resultSignal ${signalTone}`}>{snapshot.final_signal ?? "Research complete"}</span></div>
      <span className={`reviewBadge ${status ?? "pending"}`}>{status ? REVIEW_LABELS[status] : "No review recorded"}</span>
      {snapshot.review && <span className="resultVersion">Version {snapshot.review.version}</span>}
    </div>
    <dl className="reportFacts"><div><dt>Analysis date</dt><dd>{snapshot.analysis_date ?? "—"}</dd></div>
      <div><dt>AI provider</dt><dd>{snapshot.data_availability?.ai_analysis_performed === false ? "Not called" : snapshot.provider === "offline" ? "Offline demo" : snapshot.provider ?? "—"}</dd></div>
      <div><dt>Evidence items</dt><dd>{snapshot.evidence_ledger?.length ?? 0}</dd></div>
      <div><dt>Language</dt><dd>{snapshot.output_language ?? "—"}</dd></div></dl>
    <DataSourcesPanel snapshot={snapshot} apiBaseUrl={apiBaseUrl} onReplay={onReplay} replayBusy={replayBusy} />
    {decision?.executive_summary || decision?.investment_thesis
      ? <p className="resultSummary">{decision.executive_summary || decision.investment_thesis}</p>
      : <ReportText text={snapshot.final_decision ?? "No final summary is available."} evidenceIds={evidenceIds} evidencePrefix={snapshot.run_id} />}
    {decision?.investment_thesis && decision.investment_thesis !== decision.executive_summary
      && <p className="summaryLine">{decision.investment_thesis}</p>}
    {reasons.length > 0 && <div className="supportingReasons"><h3><WorkbenchIcon name="evidence" size={16} />Supporting reasons</h3><ul>
      {reasons.map((item, i) => <li key={i}>{item.claim} <span className="evidenceRefs">
        {(item.evidence_ids ?? []).filter((id) => evidenceIds.includes(id)).map((id) =>
          <a key={id} className="evidenceRef" href={`#${snapshot.run_id}-evidence-${id}`} onClick={() => revealEvidence(`${snapshot.run_id}-evidence-${id}`)}>{id}</a>)}
      </span></li>)}
    </ul></div>}
    <div className="resultConsiderations">
      <div className="riskConsideration"><h3>Key risks</h3>{decision?.key_risks?.length ? <ul>{decision.key_risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul>
        : <p className="summaryLine">No structured risks were captured. Check the full report.</p>}</div>
      <div><h3>What remains uncertain</h3><p>{decision?.evidence_gap ?? "Check the full report for evidence gaps."}</p>
        {decision?.counterargument && <details><summary>Strongest counterargument</summary><p>{decision.counterargument}</p>
          {decision.counterargument_response && <p>{decision.counterargument_response}</p>}</details>}</div>
    </div>
    {decision?.confidence != null && <details className="reportExtra"><summary>Confidence rationale</summary>
      <p>Model-reported confidence: {decision.confidence}/100. This score is not a calibrated probability.</p>
      <p>{decision.confidence_rationale ?? "No confidence rationale was captured."}</p></details>}
    <details className="reportExtra"><summary>View original decision text</summary><pre className="rawOutput">{snapshot.final_decision}</pre></details>
  </section>;
}
