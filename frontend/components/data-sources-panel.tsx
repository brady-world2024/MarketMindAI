import type { RunSnapshot } from "../lib/api-types";

export function SnapshotProvenance({ snapshot, apiBaseUrl = "" }: { snapshot: RunSnapshot; apiBaseUrl?: string }) {
  const cutoff = snapshot.research_cutoff;
  const manifest = snapshot.data_snapshot;
  const fields = [
    ["Requested date", cutoff?.requested_date], ["Effective session date", cutoff?.effective_session_date],
    ["Cutoff (UTC)", cutoff?.cutoff_at], ["Cutoff (market local)", cutoff?.cutoff_at_local], ["Market timezone", cutoff?.market_timezone],
    ["Snapshot ID", manifest?.snapshot_id], ["Manifest SHA-256", manifest?.manifest_sha256],
    ["Policy version", manifest?.policy_version], ["Processing version", manifest?.processing_version],
  ];
  return <div className="snapshotProvenance">
    <h3>Research cutoff &amp; saved data</h3>
    {(!cutoff || !manifest?.snapshot_id) && <p className="summaryLine">Snapshot provenance: Unverified · 未核验. This historical report has no verified cutoff or saved data manifest.</p>}
    <dl className="reportFacts">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "Unverified"}</dd></div>)}</dl>
    {snapshot.data_mode === "demo" && <p className="summaryLine">Synthetic snapshot and publication times · 演示材料</p>}
    {(["included", "excluded", "unverified"] as const).map((status) => {
      const records = (snapshot.source_records ?? []).filter((item) => (item.admissibility ?? "unverified") === status);
      return <details className="reportExtra" key={status}><summary>{status[0].toUpperCase() + status.slice(1)} sources ({records.length})</summary>
        {records.map((item) => <article className="reportExtra" key={item.record_id}>
          <h4>{item.method ?? item.record_id}</h4>
          <p className="summaryLine">Provider: {item.provider ?? "Unverified"} · Publisher: {item.publisher ?? "Unverified"}</p>
          <p className="summaryLine">Published: {item.published_at ?? "Unverified"} · Precision: {item.time_precision ?? "unknown"}{item.public_time_basis && ` · ${item.public_time_basis}`}</p>
          <p className="summaryLine">Period end: {item.period_end ?? "Unverified"} · SEC accession: {item.accession ?? "Unverified"}</p>
          {item.price_basis && <p className="summaryLine">Price units: {item.price_basis.verified ? "Verified at cutoff" : "Unverified"} · {item.price_basis.basis} · Adjustment window through {item.price_basis.verification_through} · Post-cutoff split factor: {item.price_basis.post_cutoff_split_factor}</p>}
          <p className="summaryLine">Reasons: {item.reason_codes?.join(", ") || (status === "included" ? "Admitted by saved source policy" : "Unverified")}</p>
          {item.source_url && <p className="summaryLine">Source URL: {item.source_url}</p>}
          <p className="summaryLine">Record: {item.record_id} · Raw kind: {item.raw_content_kind ?? "Unverified"} · SHA-256: {item.raw_sha256 ?? "Unverified"}</p>
          {manifest?.snapshot_id && item.raw_sha256 && <a href={`${apiBaseUrl.replace(/\/$/, "")}/api/snapshots/${encodeURIComponent(manifest.snapshot_id)}/sources/${encodeURIComponent(item.record_id)}`} download>Download saved source</a>}
        </article>)}
      </details>;
    })}
  </div>;
}

export function DataSourcesPanel({ snapshot, apiBaseUrl, onReplay, replayBusy }: {
  snapshot: RunSnapshot; apiBaseUrl?: string; onReplay?: () => void; replayBusy?: boolean;
}) {
  const data = snapshot.data_availability;
  const mode = snapshot.data_mode ?? "unknown";
  return <div className="sourcePanel">
    <SnapshotProvenance snapshot={snapshot} apiBaseUrl={apiBaseUrl} />
    {snapshot.data_snapshot?.snapshot_id && onReplay && <div className="reportExtra">
      <button type="button" className="secondaryButton" disabled={replayBusy} onClick={onReplay}>Replay saved data</button>
      <p className="summaryLine">Run research again with the same saved evidence inputs. Model output may differ.
        {mode === "demo" ? " Demo replay uses offline models." : " Live replay uses your verified AI connection."}</p>
    </div>}
    <h3>Data availability / 数据完整性</h3>
    <p className="summaryLine">Data mode: <strong>{mode === "unknown" ? "Unknown · 未核验" : mode}</strong>
      {mode === "demo" && " · Synthetic sample data / 演示材料"}</p>
    {mode === "unknown" && <p className="summaryLine">Historical data mode and source isolation have not been verified.</p>}
    {data?.ai_analysis_performed === false && <p className="offlineNotice">No AI analysis · 未进行 AI 分析</p>}
    {data?.can_recommend === false && <p className="statusBad">无法形成建议 · Missing: {data.missing.join(", ")}</p>}
    {data && <dl className="reportFacts">{Object.entries(data.requirements).map(([name, entry]) => <div key={name}>
      <dt>{name}{entry.required ? " · Required" : " · Optional"}</dt>
      <dd>{entry.available ? "Available" : "Unavailable"}{entry.valid_count != null && ` · ${entry.valid_count}/${entry.minimum_count} valid daily bars`}</dd>
      {!!entry.reason_codes?.length && <p className="summaryLine">{entry.reason_codes.join(", ")}</p>}
    </div>)}</dl>}
    {!!snapshot.source_attempts?.length && <details className="reportExtra"><summary>Source attempts / 来源尝试 ({snapshot.source_attempts.length})</summary>
      {snapshot.source_attempts.map((item, i) => <p key={i} className="summaryLine">{item.method} · {item.provider} · {item.status}
        {item.finished_at && ` · ${item.finished_at}`}{item.message && ` · ${item.message}`}</p>)}</details>}
    {!!snapshot.source_materials?.length && <details className="reportExtra"><summary>Retained source materials / 已保留材料 ({snapshot.source_materials.length})</summary>
      {snapshot.source_materials.map((item, i) => <details className="reportExtra" key={i}><summary>{item.method} · {item.provider}</summary>
        <p className="summaryLine">{item.retrieved_at}{item.source_url && ` · ${item.source_url}`}</p>
        <pre className="rawOutput">{typeof item.content === "string" ? item.content : JSON.stringify(item.content, null, 2)}</pre></details>)}</details>}
  </div>;
}
