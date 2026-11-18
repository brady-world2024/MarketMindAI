let revisionComparisonIdentity = "";
let revisionComparisonGeneration = 0;

function comparisonIdentity(snapshot) {
  return `${snapshot?.run_id}:${snapshot?.review?.report_hash}:${snapshot?.review?.parent_run_id}`;
}

function renderRevisionComparison(snapshot) {
  const identity = comparisonIdentity(snapshot);
  $("revisionComparison").hidden = !snapshot.review?.parent_run_id;
  if (identity === revisionComparisonIdentity) return;
  revisionComparisonIdentity = identity;
  revisionComparisonGeneration += 1;
  $("revisionComparisonBody").innerHTML = "";
  $("revisionComparisonStatus").textContent = "";
  $("compareRevisionBtn").disabled = false;
  $("compareRevisionBtn").textContent = "Compare with previous version";
}

function comparisonResultHtml(comparison) {
  if (comparison.status !== "available") return `<p>${escapeHtml(comparison.reason || "Comparison unavailable.")}</p>`;
  const dataLabels = {same: "Same saved data snapshot", different: "Different saved data snapshots",
    unverified: "Data snapshot identity unverified"};
  const fields = comparison.changed_fields.map(item => `<article><h4>${escapeHtml(item.label)}</h4>
    <div class="comparison-pair"><div><small>Previous version</small><p>${escapeHtml(item.before ?? "Not recorded")}</p></div>
      <div><small>Current version</small><p>${escapeHtml(item.after ?? "Not recorded")}</p></div></div></article>`).join("");
  const evidence = [["Added to this report", comparison.added_evidence],
    ["Removed from previous report", comparison.removed_evidence]].map(([label, rows]) =>
    `<h4>${label} (${rows.length})</h4>${rows.map(row => `<article class="comparison-evidence">
      <strong>${escapeHtml(row.evidence_id || "")}</strong><p>${escapeHtml(row.claim || "")}</p>
      <p>${escapeHtml([row.source, row.source_date].filter(Boolean).join(" · "))}</p>
      ${row.excerpt ? `<blockquote>${escapeHtml(row.excerpt)}</blockquote>` : ""}
      ${row.interpretation ? `<p>${escapeHtml(row.interpretation)}</p>` : ""}</article>`).join("")}`).join("");
  const same = !comparison.changed_fields.length && !comparison.added_evidence.length && !comparison.removed_evidence.length;
  return `<div class="comparison-result"><h3>Changes from previous version</h3>
    <p>Version ${escapeHtml(comparison.previous.version ?? "?")} → ${escapeHtml(comparison.current.version ?? "?")}
      · ${Object.prototype.hasOwnProperty.call(dataLabels, comparison.data_snapshot) ? dataLabels[comparison.data_snapshot] : dataLabels.unverified}</p>
    ${fields}${evidence}${same ? "<p>No changes in the compared conclusion fields or cited evidence.</p>" : ""}
    <p>Retained evidence items ${escapeHtml(comparison.unchanged_evidence_count)}</p>
    <details><summary>Compared report versions</summary>
      <p>Previous run ${escapeHtml(comparison.previous.run_id)} · ${escapeHtml(comparison.previous.report_hash)}</p>
      <p>Current run ${escapeHtml(comparison.current.run_id)} · ${escapeHtml(comparison.current.report_hash)}</p>
    </details></div>`;
}

async function loadRevisionComparison() {
  const snapshot = state.snapshot;
  if (!snapshot?.review?.parent_run_id) return;
  const identity = comparisonIdentity(snapshot);
  const generation = ++revisionComparisonGeneration;
  const isCurrent = () => generation === revisionComparisonGeneration && identity === revisionComparisonIdentity;
  $("compareRevisionBtn").disabled = true;
  $("revisionComparisonBody").innerHTML = "";
  $("revisionComparisonStatus").textContent = "Comparing versions…";
  try {
    const comparison = await getJson(`/api/runs/${encodeURIComponent(snapshot.run_id)}/comparison`);
    if (!isCurrent()) return;
    if (comparison.status === "available" && (comparison.current.run_id !== snapshot.run_id
        || comparison.current.report_hash !== snapshot.review.report_hash
        || comparison.previous.run_id !== snapshot.review.parent_run_id)) {
      throw new Error("The comparison does not match this report version. Reload the report.");
    }
    $("revisionComparisonBody").innerHTML = comparisonResultHtml(comparison);
    $("revisionComparisonStatus").textContent = "";
    $("compareRevisionBtn").textContent = "Compare with previous version";
  } catch (error) {
    if (isCurrent()) {
      $("revisionComparisonStatus").textContent = error?.message || "Comparison unavailable. Try again.";
      $("compareRevisionBtn").textContent = "Retry comparison";
    }
  } finally {
    if (isCurrent()) $("compareRevisionBtn").disabled = false;
  }
}
