const state = {
  providers: [],
  runId: null,
  reportUrl: null,
  eventSource: null,
  snapshot: null,
  selectedCandidate: null,
  searchTimer: null,
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
  $("apiKeyHelpText").textContent = provider.requires_api_key
    ? "API keys stay in the browser for this session and are only sent when you validate or start a run."
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

function renderReports(snapshot) {
  const container = $("reports");
  container.innerHTML = "";
  (snapshot.reports || []).forEach((report) => {
    if (!report.content) return;
    const section = document.createElement("section");
    section.className = "report-card";
    section.innerHTML = `<h3>${escapeHtml(report.label)}</h3><pre>${escapeHtml(report.content)}</pre>`;
    container.appendChild(section);
  });
}

function finalSummaryText(snapshot) {
  if (!snapshot.final_decision) {
    return snapshot.latest_update || "Waiting for research output.";
  }
  return snapshot.final_decision.split("\n").find((line) => line.trim()) || snapshot.final_decision;
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  if (!state.reportUrl && snapshot?.run_id) {
    state.reportUrl = `/runs/${snapshot.run_id}/report`;
  }
  $("runPill").textContent = snapshot.status;
  $("appStatus").textContent = snapshot.latest_update || snapshot.status;
  $("dataSourceBadge").textContent = snapshot.provider;
  $("finalSignal").textContent = snapshot.final_signal || "Pending";
  $("finalSummary").textContent = finalSummaryText(snapshot);
  $("exportPdfBtn").disabled = snapshot.status !== "completed";
  renderAgents(snapshot);
  renderFeed(snapshot);
  renderReports(snapshot);
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

async function validateProvider() {
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
    alert(payload.message);
  } catch (payload) {
    alert(payload.error || payload.message || "Validation failed.");
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
  source.addEventListener("snapshot", (event) => {
    renderSnapshot(JSON.parse(event.data));
  });
  source.addEventListener("complete", (event) => {
    renderSnapshot(JSON.parse(event.data));
    source.close();
  });
  const onError = (event) => {
    try {
      const payload = JSON.parse(event.data);
      alert(payload.message || "Run failed.");
    } catch (_ignored) {
      alert("Run failed.");
    }
    source.close();
  };
  source.addEventListener("run_error", onError);
  source.addEventListener("error", onError);
}

async function startRun() {
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
    state.runId = response.run_id;
    state.reportUrl = response.report_url || `/runs/${response.run_id}/report`;
    $("exportPdfBtn").disabled = true;
    renderResolution({
      resolution: response.ticker_resolution,
      status: "RESOLVED",
      message: "Symbol validated and run created.",
    });
    connectRunStream(response.run_id);
  } catch (payload) {
    const message = payload?.message || payload?.detail?.message || payload?.error || payload?.detail || "Unable to start run.";
    if (payload?.detail || payload?.resolution || payload?.status) {
      renderResolution(payload, true);
    }
    alert(message);
  }
}

async function refreshRun() {
  if (!state.runId) return;
  try {
    const snapshot = await getJson(`/api/runs/${state.runId}`);
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
  $("providerSelect").addEventListener("change", syncProviderModels);
  $("quickModelSelect").addEventListener("change", () => {
    syncCustomModelField("quick", providerByValue($("providerSelect").value));
  });
  $("deepModelSelect").addEventListener("change", () => {
    syncCustomModelField("deep", providerByValue($("providerSelect").value));
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
  await loadProviders();
}

bootstrap();
