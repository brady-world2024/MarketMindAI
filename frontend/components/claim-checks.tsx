import type { RunSnapshot } from "../lib/api-types";
import { claimCheckId } from "../lib/claim-evidence";

const verdicts = { supported: "Supported", contradicted: "Contradicted", insufficient: "Insufficient evidence" };
const metrics = { revenue_yoy: "Revenue year over year", operating_margin: "Operating margin" };

export function ClaimChecks({ snapshot, apiBaseUrl }: { snapshot: RunSnapshot | null; apiBaseUrl: string }) {
  if (!snapshot) return null;
  function sourceLink(recordId: string | undefined) {
    const snapshotId = snapshot?.data_snapshot?.snapshot_id;
    return snapshotId && recordId
      ? `${apiBaseUrl.replace(/\/$/, "")}/api/snapshots/${encodeURIComponent(snapshotId)}/sources/${encodeURIComponent(recordId)}`
      : null;
  }
  return <>
    {(snapshot.report_verification?.qualitative_claims ?? []).map((check, index) => (
      <details className="reviewDetails claimCheck" id={claimCheckId(snapshot, "claim-check", index)} tabIndex={-1} key={index}>
        <summary>{check.claim} · {verdicts[check.status] ?? "Unverified"}</summary>
        <p>{check.reason}</p>
        {(check.citations ?? []).map((citation, citationIndex) => <div key={citationIndex}>
          <h4>Quoted evidence</h4>
          <blockquote>{citation.quote}</blockquote>
          <p>{citation.provider} · {citation.published_at}</p>
          {citation.context && citation.context !== citation.quote && <details>
            <summary>Nearby context</summary><p>{citation.context}</p>
          </details>}
          {sourceLink(citation.record_id) && <a href={sourceLink(citation.record_id)!} download>Download saved source</a>}
        </div>)}
      </details>
    ))}
    {(snapshot.report_verification?.financial_claims ?? []).map((check, index) => (
      <details className="reviewDetails claimCheck" id={claimCheckId(snapshot, "calculation", index)} tabIndex={-1} key={index}>
        <summary>{metrics[check.metric] ?? "Financial calculation"} · {verdicts[check.status] ?? "Unverified"}</summary>
        {check.claim && <p>{check.claim}</p>}
        <p>{check.reason}</p>
        {check.formula && <p className="calculationFormula">{check.formula}</p>}
        {check.declared_percentage != null && <p>Reported percentage {check.declared_percentage}%</p>}
        {check.rounded_percentage != null && <p>Calculated percentage {check.rounded_percentage}%</p>}
        {check.display_scale != null && <p>Display scale {check.display_scale}</p>}
        {check.inputs && <ul>{check.inputs.map((input, inputIndex) => <li key={inputIndex}>
          {input.label} · {input.period_end} · Original {input.raw_value} · Normalized {input.value} {check.currency}
          {" · "}Row {input.line}, column {input.column}
        </li>)}</ul>}
        {check.accession && <p>SEC filing {check.accession}</p>}
        {sourceLink(check.record_id) && <a href={sourceLink(check.record_id)!} download>Download saved SEC source</a>}
      </details>
    ))}
  </>;
}
