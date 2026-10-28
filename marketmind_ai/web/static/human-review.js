const reviewLabels = {
  pending: "Awaiting human review", approved: "Approved", rejected: "Rejected", changes_requested: "Changes requested",
};
let reviewQueueKey = "";
let reviewListGeneration = 0;

function reviewError(message) {
  $("reviewError").textContent = message || "";
  $("reviewError").hidden = !message;
}

function reviewErrorText(error) {
  if (typeof error?.detail === "string") return error.detail;
  if (Array.isArray(error?.detail)) return error.detail.map((item) => item.msg).join("; ");
  return error?.detail?.message || error?.message || "Unable to save the review. Reload the report and try again.";
}

function renderReviewQueue() {
  const query = $("reviewSearch").value.trim().toLowerCase();
  const status = $("reviewStatusFilter").value;
  const items = (state.recentReviews || []).filter((item) => {
    const text = [item.ticker, item.analysis_date, item.run_id, item.review?.version, reviewLabels[item.review?.status]].join(" ").toLowerCase();
    return (!status || item.review?.status === status) && (!query || text.includes(query));
  });
  const list = $("reviewQueue");
  list.replaceChildren();
  const disabled = !!state.reviewBusy || !!state.startingRun || ["queued", "running"].includes(state.snapshot?.status);
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "saved-report";
    button.disabled = disabled;
    button.setAttribute("aria-current", item.run_id === state.runId ? "true" : "false");
    button.innerHTML = `<span class="saved-report-title"><strong>${escapeHtml(item.ticker || "Unknown ticker")}</strong><span>${escapeHtml(item.analysis_date || "Date unavailable")}</span></span>
      <span class="saved-report-meta"><span>v${escapeHtml(item.review?.version || 1)}</span><span>${escapeHtml(reviewLabels[item.review?.status] || "Unreviewed")}</span></span>`;
    button.addEventListener("click", () => void openReviewedRun(item.run_id).catch((error) => reviewError(reviewErrorText(error))));
    list.append(button);
  }
  $("reviewQueueStatus").textContent = items.length ? `${items.length} saved report${items.length === 1 ? "" : "s"}`
    : state.recentReviews?.length ? "No reports match these filters." : "No saved reports yet. Complete a research run to create one.";
}

async function refreshReviews() {
  const generation = ++reviewListGeneration;
  $("reviewQueueStatus").textContent = "Loading saved reports…";
  try {
    const items = await getJson("/api/reviews");
    if (generation !== reviewListGeneration) return;
    state.recentReviews = items;
    renderReviewQueue();
  } catch (error) {
    if (generation === reviewListGeneration) $("reviewQueueStatus").textContent = `Unable to load saved reports. ${reviewErrorText(error)}`;
  }
}

async function openReviewedRun(id) {
  if (!id || state.reviewBusy) return;
  const generation = ++state.loadGeneration;
  closeEventSource();
  try {
    const snapshot = await getJson(`/api/runs/${encodeURIComponent(id)}`);
    if (generation !== state.loadGeneration) return;
    state.runId = id;
    state.reportUrl = `/runs/${id}/report`;
    $("revisionApiKey").value = "";
    $("reviewComment").value = "";
    reviewError("");
    renderSnapshot(snapshot);
    if (["queued", "running"].includes(snapshot.status)) connectRunStream(id);
  } catch (error) {
    if (generation === state.loadGeneration) throw error;
  }
}

function updateReviewControls() {
  const snapshot = state.snapshot;
  const review = snapshot?.review;
  const busy = !!state.reviewBusy;
  const pending = review?.status === "pending";
  const reviewer = $("reviewerName").value.trim();
  const comment = $("reviewComment").value.trim();
  const blocked = snapshot?.final_structured_decision?.decision_status === "Actionable"
    && snapshot?.report_verification?.blocks_actionable_recommendation;
  $("approveReportBtn").disabled = busy || !pending || !reviewer || blocked;
  $("requestChangesBtn").disabled = $("rejectReportBtn").disabled = busy || !pending || !reviewer || !comment;
  $("reviewForm").disabled = busy;
  const runActive = !!state.startingRun || ["queued", "running"].includes(snapshot?.status);
  $("startRunBtn").disabled = busy || runActive;
  $("offlineDemoBtn").disabled = busy || runActive;
  renderReviewQueue();
  document.querySelectorAll("#reviewLinks button").forEach((button) => { button.disabled = busy; });
  const needsKey = snapshot && !["offline", "ollama"].includes(snapshot.provider);
  $("reviseReportBtn").disabled = busy || (needsKey && !$("revisionApiKey").value.trim());
}

function renderHumanReview(snapshot) {
  const review = snapshot.review;
  const label = review ? reviewLabels[review.status] : "No human review recorded";
  $("reviewBadge").textContent = label;
  $("reviewBadge").dataset.status = review?.status || "unreviewed";
  $("decisionLabel").textContent = review?.status === "approved" ? "Reviewed decision" : "Decision draft";
  $("reviewDescription").textContent = review?.status === "approved"
    ? "This version was accepted by a reviewer and is available to decision memory."
    : review ? "This report has not been accepted into decision memory. Exports include its review status."
    : snapshot.status === "completed" ? "No human review is recorded for this legacy report."
    : "Review becomes available when analysis and validation finish.";
  $("reviewVersion").textContent = review ? `Version ${review.version} · ${review.report_hash}` : "";
  $("reviewForm").hidden = review?.status !== "pending";
  $("reviewEvidence").hidden = !review && !snapshot.report_verification && !snapshot.evidence_ledger?.length;
  $("reviewHistory").hidden = !review?.history?.length;
  $("revisionForm").hidden = review?.status !== "changes_requested";
  $("revisionDescription").textContent = review?.revision_run_id
    ? "If the revised run was interrupted or failed, resume or retry it here. The same revised run is reused."
    : "A new analysis will use the original settings and feedback, and will need a new review.";
  $("reviseReportBtn").textContent = review?.revision_run_id ? "Resume or retry revised report" : "Generate revised report";
  $("revisionKeyLabel").hidden = ["offline", "ollama"].includes(snapshot.provider);
  $("revisionKeyTitle").textContent = `API key for ${snapshot.provider}`;
  $("revisionFeedback").hidden = !review?.feedback;
  $("revisionFeedback").textContent = review?.feedback ? `Feedback for this version: ${review.feedback}${snapshot.provider === "offline"
    ? " — Offline mode records this feedback and uses deterministic fixtures; no live model rewrites the analysis." : ""}` : "";
  $("reviewLinks").replaceChildren();
  for (const [id, title] of [[review?.parent_run_id, "View previous version"], [review?.revision_run_id, "Open revised run"]]) {
    if (!id) continue;
    const button = document.createElement("button");
    button.type = "button"; button.className = "ghost"; button.textContent = title;
    button.disabled = !!state.reviewBusy;
    button.addEventListener("click", () => void openReviewedRun(id).catch((error) => reviewError(reviewErrorText(error))));
    $("reviewLinks").append(button);
  }
  if (review || snapshot.report_verification || snapshot.evidence_ledger?.length) {
    const decision = snapshot.final_structured_decision || {};
    const quality = snapshot.report_quality || {};
    const issues = [...(snapshot.report_verification?.issues || []), ...(quality.issues || [])];
    const evidence = (snapshot.evidence_ledger || []).map((item) => `<tr${evidenceAnchorId(item.evidence_id) ? ` id="${evidenceAnchorId(item.evidence_id)}" tabindex="-1"` : ""}><td><strong>${escapeHtml(item.evidence_id || "")}</strong><p>${escapeHtml(item.claim || "")}</p></td>
      <td>${escapeHtml(item.source || "")}<br>${escapeHtml(item.source_date || "")}<br>${escapeHtml(item.freshness || "")}<br>${escapeHtml(item.url || "")}</td>
      <td>${escapeHtml(item.excerpt || "")}<p>${escapeHtml(item.interpretation || "")}</p></td></tr>`).join("");
    $("reviewEvidenceBody").innerHTML = `<p>Automated checks: ${escapeHtml(snapshot.report_verification?.status || "Not available")} · Quality: ${escapeHtml(quality.grade || "Unscored")} (${escapeHtml(quality.score ?? "—")}/100)</p>
      <p>${escapeHtml(quality.summary || "")}</p>
      <ul>${issues.map((item) => `<li>${escapeHtml(item.message || item.code || "")}</li>`).join("")}</ul>
      <p><strong>Evidence gap:</strong> ${escapeHtml(decision.evidence_gap || "Not captured")}</p>
      <ul>${(decision.key_risks || []).map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")}</ul>
      <p><strong>Counterargument:</strong> ${escapeHtml(decision.counterargument || "Not captured")}</p>
      <p>${escapeHtml(decision.counterargument_response || "")}</p>
      <div class="review-table-wrap"><table><caption>Evidence available for this report version</caption><thead><tr><th>Evidence</th><th>Source</th><th>Excerpt</th></tr></thead><tbody>${evidence}</tbody></table></div>`;
    $("reviewHistoryBody").innerHTML = (review?.history || []).map((item) => `<article class="review-audit">
      <strong>${escapeHtml(item.decision.replaceAll("_", " "))} · ${escapeHtml(item.reviewer)}</strong>
      <small>${escapeHtml(item.reviewed_at)} · Version ${escapeHtml(item.version)}</small><p>${escapeHtml(item.comment || "No additional comments.")}</p></article>`).join("");
  }
  updateReviewControls();
  const key = `${snapshot.run_id}:${review?.status || snapshot.status}`;
  if (key !== reviewQueueKey) { reviewQueueKey = key; void refreshReviews(); }
}

async function submitHumanReview(decision) {
  const snapshot = state.snapshot;
  const review = snapshot?.review;
  if (!review || state.reviewBusy) return;
  state.reviewBusy = true;
  updateReviewControls();
  reviewError("");
  try {
    const next = await getJson(`/api/runs/${snapshot.run_id}/review`, {
      method: "POST", body: JSON.stringify({ decision, version: review.version, report_hash: review.report_hash,
        reviewer: $("reviewerName").value.trim(), comment: $("reviewComment").value.trim() }),
    });
    if (state.runId === next.run_id) renderSnapshot(next);
    await refreshReviews();
  } catch (error) { reviewError(reviewErrorText(error)); }
  finally { state.reviewBusy = false; updateReviewControls(); }
}

async function generateRevision() {
  const snapshot = state.snapshot;
  const review = snapshot?.review;
  if (!review || state.reviewBusy) return;
  const generation = ++state.loadGeneration;
  state.reviewBusy = true;
  updateReviewControls();
  reviewError("");
  try {
    const run = await getJson(`/api/runs/${snapshot.run_id}/revise`, {
      method: "POST", body: JSON.stringify({ version: review.version, report_hash: review.report_hash,
        api_key: $("revisionApiKey").value.trim() || null }),
    });
    if (generation !== state.loadGeneration) return;
    $("revisionApiKey").value = "";
    state.runId = run.run_id;
    state.reportUrl = run.report_url;
    try { localStorage.setItem("marketmind-active-run", run.run_id); } catch (_ignored) {}
    renderSnapshot({ ...snapshot, run_id: run.run_id, status: "queued", review: null,
      final_decision: null, final_signal: null, final_structured_decision: null, evidence_ledger: [],
      report_verification: null, report_quality: null, error: null, finished_at: null, started_at: new Date().toISOString(),
      reports: [], agents: [], messages: [], tool_calls: [],
      latest_update: "Preparing revised analysis." });
    connectRunStream(run.run_id);
  } catch (error) { reviewError(reviewErrorText(error)); }
  finally { state.reviewBusy = false; updateReviewControls(); }
}

$("approveReportBtn").addEventListener("click", () => void submitHumanReview("approve"));
$("rejectReportBtn").addEventListener("click", () => void submitHumanReview("reject"));
$("requestChangesBtn").addEventListener("click", () => void submitHumanReview("request_changes"));
$("reviseReportBtn").addEventListener("click", () => void generateRevision());
$("refreshReviewsBtn").addEventListener("click", () => void refreshReviews());
$("reviewSearch").addEventListener("input", renderReviewQueue);
$("reviewStatusFilter").addEventListener("change", renderReviewQueue);
for (const id of ["reviewerName", "reviewComment", "revisionApiKey"]) $(id).addEventListener("input", updateReviewControls);
void refreshReviews();
try {
  const savedRun = localStorage.getItem("marketmind-active-run");
  if (savedRun && /^[a-zA-Z0-9_-]+$/.test(savedRun)) void openReviewedRun(savedRun).catch((error) => reviewError(reviewErrorText(error)));
} catch (_ignored) {}
