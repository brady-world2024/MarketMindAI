import type { RunSnapshot } from "../lib/api-types";

export function DataSourcesPanel({ snapshot }: { snapshot: RunSnapshot }) {
  const data = snapshot.data_availability;
  const mode = snapshot.data_mode ?? "unknown";
  return <div className="sourcePanel">
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
