import type { RunSnapshot } from "../lib/api-types";
import { ReportText, revealEvidence } from "./report-text";

type Props = { snapshot: RunSnapshot; onOpenReport: () => void; onExport: () => void };
const REVIEW_LABELS = { pending: "Awaiting review", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested" };

export function ResearchReport({ snapshot, onOpenReport, onExport }: Props) {
  const decision = snapshot.final_structured_decision;
  const evidenceIds = (snapshot.evidence_ledger ?? []).map((item) => item.evidence_id).filter((id): id is string => !!id);
  const reasons = decision?.core_claims?.length ? decision.core_claims : (snapshot.evidence_ledger ?? []).slice(0, 3)
    .filter((item) => item.claim).map((item) => ({ claim: item.claim!, evidence_ids: item.evidence_id ? [item.evidence_id] : [] }));
  const status = snapshot.review?.status;
  const noRecommendation = decision?.decision_status === "No Recommendation" || /no.recommendation/i.test(snapshot.final_signal ?? "");
  return <section className="panel resultPanel" aria-labelledby="result-title">
    <div className="sectionHeader compact">
      <div><p className="sectionKicker">Research report</p><h2 id="result-title">{snapshot.ticker} research</h2>
        <p className="summaryLine subtle">{snapshot.company_name ?? snapshot.original_input} · {snapshot.analysis_date}</p></div>
      <div className="reportActions"><button type="button" className="secondaryButton" onClick={onOpenReport}>Open report</button>
        <button type="button" className="secondaryButton" onClick={onExport}>Export PDF</button></div>
    </div>
    <div className="resultHeadline">
      <span className={`resultSignal ${noRecommendation ? "abstain" : ""}`}>{snapshot.final_signal ?? "Research complete"}</span>
      <span className={`reviewBadge ${status ?? "pending"}`}>{status ? REVIEW_LABELS[status] : "No review recorded"}</span>
      {snapshot.review && <span className="resultVersion">Version {snapshot.review.version}</span>}
    </div>
    {decision?.executive_summary || decision?.investment_thesis
      ? <p className="resultSummary">{decision.executive_summary || decision.investment_thesis}</p>
      : <ReportText text={snapshot.final_decision ?? "No final summary is available."} evidenceIds={evidenceIds} evidencePrefix={snapshot.run_id} />}
    {decision?.investment_thesis && decision.investment_thesis !== decision.executive_summary
      && <p className="summaryLine">{decision.investment_thesis}</p>}
    {reasons.length > 0 && <div className="supportingReasons"><h3>Supporting reasons</h3><ul>
      {reasons.map((item, i) => <li key={i}>{item.claim} <span className="evidenceRefs">
        {(item.evidence_ids ?? []).filter((id) => evidenceIds.includes(id)).map((id) =>
          <a key={id} className="evidenceRef" href={`#${snapshot.run_id}-evidence-${id}`} onClick={() => revealEvidence(`${snapshot.run_id}-evidence-${id}`)}>{id}</a>)}
      </span></li>)}
    </ul></div>}
    <div className="resultConsiderations">
      <div><h3>Key risks</h3>{decision?.key_risks?.length ? <ul>{decision.key_risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul>
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
