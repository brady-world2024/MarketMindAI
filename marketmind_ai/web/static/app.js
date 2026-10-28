const state = {
  providers: [],
  runId: null,
  reportUrl: null,
  eventSource: null,
  snapshot: null,
  selectedCandidate: null,
  searchTimer: null,
  loadGeneration: 0,
  providerValidationGeneration: 0,
  elapsedTimer: null,
};

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function isoToday() {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function providerByValue(value) {
  return state.providers.find((provider) => provider.value === value) || state.providers[0] || null;
}

function selectedAnalysts() {
  return Array.from(document.querySelectorAll(".analyst-group input:checked")).map((box) => box.value);
}

async function getJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw payload;
  }
  return payload;
}

function resolvedModelValue(kind) {
  const select = kind === "quick" ? $("quickModelSelect") : $("deepModelSelect");
  const customInput = kind === "quick" ? $("quickModelCustomInput") : $("deepModelCustomInput");
  if (select.value !== "custom") {
    return select.value;
  }
  return customInput.value.trim();
}

function currentPayload() {
  return {
    ticker: $("tickerInput").value.trim(),
    analysis_date: $("analysisDateInput").value,
    llm_provider: $("providerSelect").value,
    api_key: $("apiKeyInput").value.trim(),
    base_url: $("baseUrlInput").value.trim(),
    quick_model: resolvedModelValue("quick"),
    deep_model: resolvedModelValue("deep"),
    output_language: $("languageSelect").value,
    research_depth: Number($("depthInput").value),
    checkpoint_enabled: $("checkpointInput").checked,
    google_thinking_level: $("googleThinkingLevelSelect").value,
    openai_reasoning_effort: $("openaiReasoningEffortSelect").value,
    anthropic_effort: $("anthropicEffortSelect").value,
    analysts: selectedAnalysts(),
  };
}

function fillModelSelect(element, models, provider) {
  const options = [...models];
  if (provider.supports_custom_models && !options.some((option) => option.value === "custom")) {
    options.push({ label: "Custom model ID", value: "custom" });
  }
  element.innerHTML = "";
  options.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.value;
    option.textContent = model.label;
    element.appendChild(option);
  });
}

function syncProviderReasoningControls(providerValue) {
  $("googleThinkingLabel").hidden = providerValue !== "google";
  $("anthropicEffortLabel").hidden = providerValue !== "anthropic";
  $("openaiReasoningLabel").hidden = ![
    "openai",
    "openrouter",
    "ollama",
    "xai",
    "deepseek",
    "qwen",
    "glm",
    "azure",
  ].includes(providerValue);
}

function syncCustomModelField(kind, provider) {
  const select = kind === "quick" ? $("quickModelSelect") : $("deepModelSelect");
  const wrapper = kind === "quick" ? $("quickModelCustomLabel") : $("deepModelCustomLabel");
  const input = kind === "quick" ? $("quickModelCustomInput") : $("deepModelCustomInput");
  const isCustom = select.value === "custom";
  wrapper.hidden = !isCustom;
  input.required = isCustom;
  input.placeholder = provider?.custom_model_placeholder || `Enter a custom ${kind} model ID`;
  if (!isCustom) {
    input.value = "";
  }
}

function syncProviderModels() {
  const provider = providerByValue($("providerSelect").value);
  if (!provider) {
    return;
  }
  $("dataSourceBadge").textContent = provider.label;
  $("baseUrlInput").placeholder = provider.base_url || "Optional custom chat-completions endpoint";
  fillModelSelect($("quickModelSelect"), provider.quick_models, provider);
  fillModelSelect($("deepModelSelect"), provider.deep_models, provider);
  $("apiKeyInput").disabled = provider.value === "offline";
  $("apiKeyInput").placeholder = provider.requires_api_key ? "Enter your provider API key" : "Optional for this provider";
  $("apiKeyHelpText").textContent = provider.value === "offline"
    ? "Offline demo uses deterministic fixtures. No API key or live model connection is needed."
    : provider.requires_api_key
      ? "Your key is sent to this local server for validation and research. It is not saved in browser storage."
      : "This provider can run without an API key. Add one only if your local gateway expects it.";
  syncProviderReasoningControls(provider.value);
  syncCustomModelField("quick", provider);
  syncCustomModelField("deep", provider);
}

function renderSelectedSymbol(candidate) {
  const card = $("selectedSymbolCard");
  if (!candidate) {
    card.hidden = true;
    $("selectedSymbolText").textContent = "No symbol selected.";
    return;
  }
  const parts = [
    candidate.symbol || candidate.resolved_symbol || "",
    candidate.name || candidate.company_name || "",
    candidate.exchange || "",
  ].filter(Boolean);
  $("selectedSymbolText").textContent = parts.join(" — ");
  card.hidden = false;
}

function clearSearchResults(message = "Start typing to search.") {
  $("searchResultsCard").hidden = true;
  $("searchResults").innerHTML = "";
  $("searchResultsMeta").textContent = message;
}

function renderSearchResults(query, candidates) {
  const card = $("searchResultsCard");
  const container = $("searchResults");
  card.hidden = false;
  $("searchResultsMeta").textContent = candidates.length
    ? `${candidates.length} result${candidates.length === 1 ? "" : "s"} for “${query}”`
    : `No matches for “${query}”`;
  container.innerHTML = "";
  if (!candidates.length) {
    const empty = document.createElement("div");
    empty.className = "search-result-empty";
    empty.textContent = "No matching tickers were found.";
    container.appendChild(empty);
    return;
  }
  candidates.slice(0, 8).forEach((candidate) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result-item";
    const providerText = candidate.provider ? `<span>${escapeHtml(candidate.provider)}</span>` : "";
    const typeText = candidate.type ? `<span>${escapeHtml(candidate.type)}</span>` : "";
    button.innerHTML = `
      <strong>${escapeHtml(candidate.symbol)}</strong>
      <span>${escapeHtml(candidate.name)}</span>
      <div class="search-result-meta">
        <span>${escapeHtml(candidate.exchange || "Unknown exchange")}</span>
        ${providerText}
        ${typeText}
      </div>
    `;
    button.addEventListener("click", () => {
      state.selectedCandidate = candidate;
      $("tickerInput").value = candidate.symbol;
      renderSelectedSymbol(candidate);
      clearSearchResults(`Selected ${candidate.symbol}.`);
      void validateSymbol();
    });
    container.appendChild(button);
  });
}

async function searchSymbols() {
  const query = $("tickerInput").value.trim();
  if (query.length < 2) {
    clearSearchResults("Enter at least two characters to search.");
    return;
  }
  $("searchResultsCard").hidden = false;
  $("searchResultsMeta").textContent = `Searching matches for “${query}”…`;
  $("searchResults").innerHTML = '<div class="search-result-empty">Searching…</div>';
  try {
    const payload = await getJson(`/api/symbols/search?query=${encodeURIComponent(query)}`);
    renderSearchResults(payload.query, payload.candidates || []);
  } catch (_error) {
    $("searchResults").innerHTML = '<div class="search-result-empty">Symbol search failed.</div>';
    $("searchResultsMeta").textContent = "Search error";
  }
}

function queueSymbolSearch() {
  if (state.searchTimer) {
    window.clearTimeout(state.searchTimer);
  }
  state.searchTimer = window.setTimeout(() => {
    void searchSymbols();
  }, 280);
}

function resolutionSummary(resolution) {
  if (!resolution) {
    return null;
  }
  return {
    symbol: resolution.resolved_symbol || resolution.original_input || "",
    name: resolution.company_name || "",
    exchange: resolution.exchange || "",
  };
}

function renderResolution(payload, isError = false) {
  const resolution = payload.resolution || payload.detail?.resolution || payload;
  const status = resolution?.status || payload.status || "UNKNOWN";
  const message = payload.message || payload.detail?.message || resolution?.reason || "No message";
  let text = `Status: ${status}\n${message}`;
  if (resolution?.candidates?.length) {
    text += "\n\nCandidates:";
    resolution.candidates.slice(0, 5).forEach((item) => {
      text += `\n- ${item.symbol} — ${item.name}${item.exchange ? ` — ${item.exchange}` : ""}`;
    });
  }
  $("resolutionText").textContent = text;
  $("resolutionCard").dataset.state = isError ? "error" : "ok";
  if (!isError && resolution?.status === "RESOLVED") {
    state.selectedCandidate = resolutionSummary(resolution);
    renderSelectedSymbol(state.selectedCandidate);
  }
}

function renderAgents(snapshot) {
  const board = $("agentBoard");
  board.innerHTML = "";
  (snapshot.agents || []).forEach((agent) => {
    const card = document.createElement("div");
    card.className = "agent-card";
    card.dataset.status = agent.status;
    card.innerHTML = `<span>${escapeHtml(agent.label)}</span><strong>${escapeHtml(agent.status.replaceAll("_", " "))}</strong>`;
    board.appendChild(card);
  });
}

function renderFeed(snapshot) {
  const feed = $("feed");
  feed.innerHTML = "";
  (snapshot.messages || []).slice(-20).forEach((message) => {
    const item = document.createElement("article");
    item.className = "feed-item";
    item.innerHTML = `<div class="feed-meta">${escapeHtml(message.timestamp)} · ${escapeHtml(message.kind)}</div><p>${escapeHtml(message.content)}</p>`;
    feed.appendChild(item);
  });
}

function evidenceAnchorId(value) {
  const id = String(value || "").trim().toUpperCase();
  return /^E\d+$/.test(id) ? `evidence-${id}` : null;
}

function evidenceIdSet(ids) {
  return new Set(ids.filter((id) => evidenceAnchorId(id)).map((id) => String(id).trim().toUpperCase()));
}

function evidenceLink(id) {
  const anchor = evidenceAnchorId(id);
  if (!anchor) return escapeHtml(id);
  const label = String(id).trim().toUpperCase();
  return `<a class="evidence-link" href="#${anchor}" data-evidence-id="${label}">${label}</a>`;
}

function linkEvidenceText(escapedText, ids) {
  return escapedText.replace(/\bE\d+\b/gi, (id) => ids.has(id.toUpperCase()) ? evidenceLink(id) : id);
}

function openEvidenceLink(event) {
  const link = event.target.closest?.("a[data-evidence-id]");
  const anchor = evidenceAnchorId(link?.dataset.evidenceId);
  if (!anchor) return;
  const target = document.getElementById(anchor);
  if (!target) return;
  event.preventDefault();
  let details = target.closest("details");
  while (details) {
    details.open = true;
    details = details.parentElement?.closest("details");
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.focus({ preventScroll: true });
}

// Escape first, then add only a small, fixed set of presentation tags.
// Raw HTML, links and embedded media in model output remain literal text.
function renderReportText(value, evidenceIds = []) {
  const ids = evidenceIdSet(evidenceIds);
  const lines = escapeHtml(value || "").replaceAll("\r", "").split("\n");
  const output = [];
  let list = null;
  let paragraph = [];
  const inline = (text) => linkEvidenceText(text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>"), ids);
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => { if (list) output.push(`</${list}>`); list = null; };
  for (const line of lines) {
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList(); output.push(`<h4>${inline(heading[1])}</h4>`);
    } else if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? "ul" : "ol";
      if (list !== kind) { closeList(); list = kind; output.push(`<${kind}>`); }
      output.push(`<li>${inline((bullet || numbered)[1])}</li>`);
    } else if (!line.trim()) {
      flushParagraph(); closeList();
    } else {
      closeList(); paragraph.push(line);
    }
  }
  flushParagraph(); closeList();
  return output.join("");
}

function renderReports(snapshot) {
  const container = $("reports");
  const evidenceIds = (snapshot.evidence_ledger || []).map((item) => item.evidence_id);
  const openKeys = new Set(Array.from(container.querySelectorAll?.("details[data-report-key][open]") || []).map((item) => item.dataset.reportKey));
  container.innerHTML = "";
  (snapshot.reports || []).forEach((report) => {
    if (!report.content) return;
    const section = document.createElement("details");
    section.className = "report-card";
    section.dataset.reportKey = report.key || report.label;
    section.open = openKeys.has(section.dataset.reportKey);
    section.innerHTML = `<summary>${escapeHtml(report.label)}</summary><div class="report-prose">${renderReportText(report.content, evidenceIds)}</div>
      <details class="raw-report"><summary>Raw report text</summary><pre>${escapeHtml(report.content)}</pre></details>`;
    container.appendChild(section);
  });
}

function finalSummaryText(snapshot) {
  return snapshot.final_structured_decision?.executive_summary
    || snapshot.final_structured_decision?.investment_thesis
    || snapshot.latest_update || "Waiting for research output.";
}

function renderDecisionSummary(snapshot) {
  const decision = snapshot.final_structured_decision || {};
  $("finalSignal").textContent = decision.rating || snapshot.final_signal || decision.decision_status || "Pending";
  $("finalSummary").textContent = finalSummaryText(snapshot);
  const evidenceIds = (snapshot.evidence_ledger || []).map((item) => item.evidence_id);
  const ids = evidenceIdSet(evidenceIds);
  const reasons = (decision.core_claims || []).flatMap((item) => {
    const claim = typeof item === "string" ? item : item.claim || item.statement;
    if (!claim) return [];
    const references = (typeof item === "string" ? [] : item.evidence_ids || []).filter((id) => ids.has(String(id).trim().toUpperCase()));
    return [`<li>${linkEvidenceText(escapeHtml(claim), ids)}${references.length ? `<span class="evidence-citations"> ${references.map(evidenceLink).join(" ")}</span>` : ""}</li>`];
  });
  if (!reasons.length && decision.investment_thesis) reasons.push(`<li>${linkEvidenceText(escapeHtml(decision.investment_thesis), ids)}</li>`);
  const list = (items) => `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  const hasDecision = !!snapshot.final_structured_decision;
  $("decisionDetails").innerHTML = hasDecision ? `
    <p class="decision-meta">${escapeHtml(decision.decision_status || "Decision status unavailable")} · Confidence: ${escapeHtml(decision.confidence ?? "—")}/100</p>
    <h3>Why this decision</h3>${reasons.length ? `<ul>${reasons.join("")}</ul>` : "<p>No structured reasons were captured.</p>"}
    <h3>Key risks</h3>${decision.key_risks?.length ? list(decision.key_risks) : "<p>No structured risks were captured.</p>"}
    <h3>Evidence gap</h3><p>${escapeHtml(decision.evidence_gap || "Not captured")}</p>
    ${decision.counterargument ? `<h3>Strongest counterargument</h3><p>${escapeHtml(decision.counterargument)}</p><p>${escapeHtml(decision.counterargument_response || "")}</p>` : ""}`
    : snapshot.final_decision ? `<div class="report-prose">${renderReportText(snapshot.final_decision, evidenceIds)}</div>` : "";
}

function renderElapsed(snapshot) {
  const start = Date.parse(snapshot.started_at);
  const finish = snapshot.finished_at ? Date.parse(snapshot.finished_at) : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(finish)) { $("elapsedTime").textContent = "Elapsed —"; return; }
  const seconds = Math.max(0, Math.floor((finish - start) / 1000));
  $("elapsedTime").textContent = `Elapsed ${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function renderRunProgress(snapshot) {
  const agents = snapshot.agents || [];
  const active = agents.find((agent) => agent.status === "in_progress");
  const lastAgent = agents.find((agent) => agent.label === snapshot.current_agent || agent.key === snapshot.current_agent);
  let phase = snapshot.status === "queued" ? "Queued · preparing research" : "Research in progress";
  if (snapshot.status === "completed") phase = snapshot.review?.status === "approved" ? "Complete · human review approved"
    : snapshot.review?.status === "changes_requested" ? "Human review · changes requested"
    : snapshot.review?.status === "rejected" ? "Human review · report rejected" : "Awaiting human review";
  else if (snapshot.status === "error") phase = `Run failed · ${snapshot.error || snapshot.latest_update || "See activity for details"}`;
  else if (active) phase = `In progress · ${active.label}`;
  else if (snapshot.current_agent) phase = `${snapshot.current_agent}${lastAgent?.status === "completed" ? " · step completed" : " · latest stage"}`;
  $("runPhase").textContent = phase;
  const completed = agents.filter((agent) => agent.status === "completed").length;
  $("phaseDetail").textContent = agents.length ? `${completed} of ${agents.length} agent stages complete${snapshot.report_verification ? ` · Validation: ${snapshot.report_verification.status || "recorded"}` : ""}` : "Stages appear as the run reports progress.";
  renderElapsed(snapshot);
  const groups = [
    ["Research", ["market", "social", "news", "fundamentals"]],
    ["Debate & thesis", ["bull", "bear", "research_manager"]],
    ["Trade proposal", ["trader"]],
    ["Risk review", ["aggressive", "conservative", "neutral"]],
    ["Final decision", ["portfolio_manager"]],
  ];
  const reviewComplete = snapshot.review?.status === "approved";
  const reviewPhase = reviewComplete ? "Complete" : snapshot.status === "completed" ? "In progress" : "Waiting";
  const reviewStatus = reviewComplete ? "Approved" : snapshot.review?.status === "changes_requested" ? "Changes requested"
    : snapshot.review?.status === "rejected" ? "Rejected" : snapshot.status === "completed" ? "Awaiting review" : "Waiting";
  $("phaseSteps").innerHTML = groups.map(([label, keys]) => {
    const members = agents.filter((agent) => keys.includes(agent.key));
    const status = members.length && members.every((agent) => agent.status === "completed") ? "Complete"
      : members.some((agent) => agent.status === "error") ? "Failed"
      : members.some((agent) => agent.status === "in_progress" || agent.status === "completed") ? "In progress" : "Waiting";
    return `<li data-phase-status="${status}"><span>${label}</span><small>${status}</small></li>`;
  }).join("") + `<li data-phase-status="${snapshot.report_verification?.status === "failed" ? "Failed" : snapshot.report_verification ? "Complete" : "Waiting"}"><span>Validation</span><small>${escapeHtml(snapshot.report_verification?.status || "Waiting")}</small></li>` + `<li data-phase-status="${reviewPhase}"><span>Human review</span><small>${reviewStatus}</small></li>`;
  if (["completed", "error"].includes(snapshot.status)) {
    $("streamStatus").textContent = snapshot.status === "error" ? "Run failed" : "Run complete";
  }
}

function renderToolCalls(snapshot) {
  $("toolLog").innerHTML = (snapshot.tool_calls || []).slice(-20).map((tool) => `<article class="feed-item"><strong>${escapeHtml(tool.name)}</strong><small>${escapeHtml(tool.timestamp)}</small><pre>${escapeHtml(tool.args || "")}</pre></article>`).join("") || "<p>No tool calls recorded yet.</p>";
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  state.runId = snapshot.run_id;
  try { localStorage.setItem("marketmind-active-run", snapshot.run_id); } catch (_ignored) {}
  if (!state.reportUrl && snapshot?.run_id) {
    state.reportUrl = `/runs/${snapshot.run_id}/report`;
  }
  $("runPill").textContent = snapshot.status;
  $("appStatus").textContent = snapshot.latest_update || snapshot.status;
  $("dataSourceBadge").textContent = snapshot.provider;
  renderDecisionSummary(snapshot);
  renderRunProgress(snapshot);
  renderToolCalls(snapshot);
  $("exportPdfBtn").disabled = snapshot.status !== "completed";
  renderAgents(snapshot);
  renderFeed(snapshot);
  renderReports(snapshot);
  if (typeof renderHumanReview === "function") renderHumanReview(snapshot);
}

async function loadProviders() {
  state.providers = await getJson("/api/providers");
  const select = $("providerSelect");
  select.innerHTML = "";
  state.providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.value;
    option.textContent = provider.label;
    select.appendChild(option);
  });
  syncProviderModels();
}

async function validateSymbol() {
  try {
    const payload = await getJson("/api/symbols/resolve", {
      method: "POST",
      body: JSON.stringify({
        query: $("tickerInput").value.trim(),
        analysis_date: $("analysisDateInput").value,
      }),
    });
    renderResolution(payload);
  } catch (errorPayload) {
    renderResolution(errorPayload, true);
  }
}

function providerFingerprint() {
  return JSON.stringify([$("providerSelect").value, $("apiKeyInput").value.trim(), $("baseUrlInput").value.trim(), resolvedModelValue("quick"), resolvedModelValue("deep")]);
}

function invalidateProviderValidation() {
  ++state.providerValidationGeneration;
  $("providerStatus").textContent = $("providerSelect").value === "offline" ? "Offline demo · no connection needed" : "Connection not checked for these settings.";
  $("providerStatus").dataset.state = "idle";
  $("validateProviderBtn").disabled = false;
}

function changeProvider() {
  $("apiKeyInput").value = "";
  $("baseUrlInput").value = "";
  syncProviderModels();
  invalidateProviderValidation();
}

async function validateProvider() {
  const generation = ++state.providerValidationGeneration;
  const fingerprint = providerFingerprint();
  $("providerStatus").textContent = "Checking connection…";
  $("providerStatus").dataset.state = "checking";
  $("validateProviderBtn").disabled = true;
  try {
    const payload = await getJson("/api/validate-key", {
      method: "POST",
      body: JSON.stringify({
        llm_provider: $("providerSelect").value,
        api_key: $("apiKeyInput").value.trim(),
        model: resolvedModelValue("quick"),
        base_url: $("baseUrlInput").value.trim(),
      }),
    });
    if (generation !== state.providerValidationGeneration || fingerprint !== providerFingerprint()) return;
    $("providerStatus").textContent = payload.message || (payload.valid === false ? "Connection check failed." : "Connection verified.");
    $("providerStatus").dataset.state = payload.valid === false ? "error" : "ok";
  } catch (payload) {
    if (generation !== state.providerValidationGeneration || fingerprint !== providerFingerprint()) return;
    $("providerStatus").textContent = payload.error || payload.message || payload.detail || "Connection check failed.";
    $("providerStatus").dataset.state = "error";
  } finally {
    if (generation === state.providerValidationGeneration) $("validateProviderBtn").disabled = false;
  }
}

function closeEventSource() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function connectRunStream(runId) {
  closeEventSource();
  const source = new EventSource(`/api/runs/${runId}/stream`);
  state.eventSource = source;
  $("streamStatus").textContent = "Connecting to live updates…";
  const isCurrent = () => state.runId === runId && state.eventSource === source;
  source.addEventListener("open", () => {
    if (isCurrent()) $("streamStatus").textContent = "Live updates connected";
  });
  source.addEventListener("snapshot", (event) => {
    if (!isCurrent()) return;
    $("streamStatus").textContent = "Live updates connected";
    const snapshot = JSON.parse(event.data);
    renderSnapshot(snapshot);
    if (["completed", "error"].includes(snapshot.status)) { source.close(); state.eventSource = null; }
  });
  source.addEventListener("complete", (event) => {
    if (!isCurrent()) return;
    renderSnapshot(JSON.parse(event.data));
    source.close();
    state.eventSource = null;
  });
  const failRun = (message) => {
    renderSnapshot({ ...state.snapshot, run_id: runId, status: "error", error: message, finished_at: new Date().toISOString() });
    $("streamStatus").textContent = message;
    source.close();
    state.eventSource = null;
    void refreshRun();
  };
  source.addEventListener("run_error", (event) => {
    if (!isCurrent()) return;
    let message = "Run failed. Refresh the snapshot for details.";
    try { message = JSON.parse(event.data).message || message; } catch (_ignored) {}
    failRun(message);
  });
  source.addEventListener("error", (event) => {
    if (!isCurrent()) return;
    if (event.data) {
      try { failRun(JSON.parse(event.data).message || "Run failed."); return; } catch (_ignored) {}
    }
    $("streamStatus").textContent = "Live updates interrupted · reconnecting. The run may still be active.";
  });
}

async function startRun() {
  if (state.reviewBusy || state.startingRun || ["queued", "running"].includes(state.snapshot?.status)) return;
  state.startingRun = true;
  $("runError").hidden = true;
  $("startRunBtn").disabled = true;
  $("offlineDemoBtn").disabled = true;
  const generation = ++state.loadGeneration;
  closeEventSource();
  try {
    const payload = currentPayload();
    if (!payload.quick_model || !payload.deep_model) {
      throw new Error("Please provide both quick and deep model IDs.");
    }
    if (!payload.analysts.length) {
      throw new Error("Select at least one analyst desk.");
    }
    const response = await getJson("/api/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (generation !== state.loadGeneration) return;
    state.runId = response.run_id;
    try { localStorage.setItem("marketmind-active-run", response.run_id); } catch (_ignored) {}
    state.reportUrl = response.report_url || `/runs/${response.run_id}/report`;
    $("exportPdfBtn").disabled = true;
    renderResolution({
      resolution: response.ticker_resolution,
      status: "RESOLVED",
      message: "Symbol validated and run created.",
    });
    renderSnapshot({ run_id: response.run_id, ticker: payload.ticker, analysis_date: payload.analysis_date,
      status: "queued", provider: payload.llm_provider, started_at: new Date().toISOString(),
      latest_update: "Preparing research.", reports: [], agents: [], messages: [], tool_calls: [] });
    connectRunStream(response.run_id);
  } catch (payload) {
    if (generation !== state.loadGeneration) return;
    const message = payload?.message || payload?.detail?.message || payload?.error || payload?.detail || "Unable to start run.";
    if (payload?.detail || payload?.resolution || payload?.status) {
      renderResolution(payload, true);
    }
    $("runError").textContent = String(message);
    $("runError").hidden = false;
  } finally {
    state.startingRun = false;
    const running = ["queued", "running"].includes(state.snapshot?.status);
    $("startRunBtn").disabled = !!state.reviewBusy || running;
    $("offlineDemoBtn").disabled = !!state.reviewBusy || running;
  }
}

async function refreshRun() {
  if (!state.runId) return;
  const id = state.runId;
  const generation = state.loadGeneration;
  try {
    const snapshot = await getJson(`/api/runs/${id}`);
    if (id !== state.runId || generation !== state.loadGeneration) return;
    renderSnapshot(snapshot);
  } catch (_error) {}
}

function exportPdf() {
  if (!state.runId) {
    return;
  }
  const url = `${state.reportUrl || `/runs/${state.runId}/report`}?autoprint=1`;
  const popup = window.open(url, "_blank", "noopener,noreferrer");
  if (!popup) {
    window.location.href = url;
  }
}

function bindEvents() {
  $("reports").addEventListener("click", openEvidenceLink);
  $("decisionDetails").addEventListener("click", openEvidenceLink);
  $("providerSelect").addEventListener("change", changeProvider);
  for (const id of ["apiKeyInput", "baseUrlInput", "quickModelCustomInput", "deepModelCustomInput"]) $(id).addEventListener("input", invalidateProviderValidation);
  $("quickModelSelect").addEventListener("change", () => {
    syncCustomModelField("quick", providerByValue($("providerSelect").value));
    invalidateProviderValidation();
  });
  $("deepModelSelect").addEventListener("change", () => {
    syncCustomModelField("deep", providerByValue($("providerSelect").value));
    invalidateProviderValidation();
  });
  $("tickerInput").addEventListener("input", () => {
    state.selectedCandidate = null;
    renderSelectedSymbol(null);
    queueSymbolSearch();
  });
  $("searchSymbolsBtn").addEventListener("click", () => {
    void searchSymbols();
  });
  $("validateSymbolBtn").addEventListener("click", () => {
    void validateSymbol();
  });
  $("validateProviderBtn").addEventListener("click", () => {
    void validateProvider();
  });
  $("offlineDemoBtn").addEventListener("click", () => {
    if (state.reviewBusy || state.startingRun || ["queued", "running"].includes(state.snapshot?.status)) return;
    $("providerSelect").value = "offline";
    changeProvider();
    void startRun();
  });
  $("startRunBtn").addEventListener("click", () => {
    void startRun();
  });
  $("refreshResultBtn").addEventListener("click", () => {
    void refreshRun();
  });
  $("exportPdfBtn").addEventListener("click", exportPdf);
  $("depthInput").addEventListener("input", () => {
    $("depthLabel").textContent = $("depthInput").value;
  });
}

async function bootstrap() {
  $("analysisDateInput").value = isoToday();
  $("analysisDateInput").max = isoToday();
  $("depthLabel").textContent = $("depthInput").value;
  bindEvents();
  try {
    await loadProviders();
    invalidateProviderValidation();
  } catch (_error) {
    $("providerStatus").textContent = "Unable to load providers. Reload the page to try again.";
    $("providerStatus").dataset.state = "error";
  }
  state.elapsedTimer = window.setInterval(() => {
    if (state.snapshot && ["queued", "running"].includes(state.snapshot.status)) renderElapsed(state.snapshot);
  }, 1000);
}

bootstrap();
