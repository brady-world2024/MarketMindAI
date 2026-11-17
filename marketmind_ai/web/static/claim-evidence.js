function claimCheckId(snapshot, kind, index) {
  return `${snapshot.run_id}-${kind}-${index + 1}`;
}

function claimCheckLinks(snapshot, index) {
  const claim = snapshot.final_structured_decision?.core_claims?.[index];
  if (!claim?.claim) return [];
  const links = [];
  (snapshot.report_verification?.qualitative_claims || []).forEach((check, checkIndex) => {
    if (check.claim_number === index + 1 && check.claim === claim.claim) {
      links.push({id: claimCheckId(snapshot, "claim-check", checkIndex), label: "Source check"});
    }
  });
  const evidenceIds = new Set((snapshot.evidence_ledger || []).map(item => item.evidence_id));
  (snapshot.report_verification?.financial_claims || []).forEach((check, checkIndex) => {
    if (check.evidence_id && evidenceIds.has(check.evidence_id) && claim.evidence_ids?.includes(check.evidence_id)) {
      links.push({id: claimCheckId(snapshot, "calculation", checkIndex), label: `Calculation ${check.evidence_id}`});
    }
  });
  return links;
}

function renderClaimChecks(snapshot) {
  const verdicts = {supported: "Supported", contradicted: "Contradicted", insufficient: "Insufficient evidence"};
  const metrics = {revenue_yoy: "Revenue year over year", operating_margin: "Operating margin"};
  const verdict = check => Object.prototype.hasOwnProperty.call(verdicts, check.status) ? verdicts[check.status] : "Unverified";
  const sourceLink = (recordId, label) => {
    const snapshotId = snapshot.data_snapshot?.snapshot_id;
    return snapshotId && recordId
      ? `<a href="/api/snapshots/${encodeURIComponent(snapshotId)}/sources/${encodeURIComponent(recordId)}" download>${label}</a>`
      : "";
  };
  const qualitative = (snapshot.report_verification?.qualitative_claims || []).map((check, index) => `
    <details class="claim-check" id="${escapeHtml(claimCheckId(snapshot, "claim-check", index))}" tabindex="-1">
      <summary>${escapeHtml(check.claim)} · ${verdict(check)}</summary>
      <p>${escapeHtml(check.reason)}</p>
      ${(check.citations || []).map(citation => `
        <h4>Quoted evidence</h4><blockquote>${escapeHtml(citation.quote)}</blockquote>
        <p>${escapeHtml(citation.provider)} · ${escapeHtml(citation.published_at)}</p>
        ${citation.context && citation.context !== citation.quote
          ? `<details><summary>Nearby context</summary><p>${escapeHtml(citation.context)}</p></details>` : ""}
        ${sourceLink(citation.record_id, "Download saved source")}`).join("")}
    </details>`).join("");
  const financial = (snapshot.report_verification?.financial_claims || []).map((check, index) => `
    <details class="claim-check" id="${escapeHtml(claimCheckId(snapshot, "calculation", index))}" tabindex="-1">
      <summary>${Object.prototype.hasOwnProperty.call(metrics, check.metric) ? metrics[check.metric] : "Financial calculation"} · ${verdict(check)}</summary>
      ${check.claim ? `<p>${escapeHtml(check.claim)}</p>` : ""}
      <p>${escapeHtml(check.reason)}</p>
      ${check.formula ? `<p class="calculation-formula">${escapeHtml(check.formula)}</p>` : ""}
      ${check.declared_percentage != null ? `<p>Reported percentage ${escapeHtml(check.declared_percentage)}%</p>` : ""}
      ${check.rounded_percentage != null ? `<p>Calculated percentage ${escapeHtml(check.rounded_percentage)}%</p>` : ""}
      ${check.display_scale != null ? `<p>Display scale ${escapeHtml(check.display_scale)}</p>` : ""}
      <ul>${(check.inputs || []).map(input => `<li>${escapeHtml(input.label)} · ${escapeHtml(input.period_end)}
        · Original ${escapeHtml(input.raw_value)} · Normalized ${escapeHtml(input.value)} ${escapeHtml(check.currency ?? "")}
        · Row ${escapeHtml(input.line)}, column ${escapeHtml(input.column)}</li>`).join("")}</ul>
      ${check.accession ? `<p>SEC filing ${escapeHtml(check.accession)}</p>` : ""}
      ${sourceLink(check.record_id, "Download saved SEC source")}
    </details>`).join("");
  return qualitative + financial;
}
