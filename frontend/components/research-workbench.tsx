"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  ProviderOption,
  ResolvedTicker,
  ResolutionErrorResponse,
  RunCreatedResponse,
  RunSnapshot,
  SymbolCandidate,
  ValidateKeyResponse,
} from "../lib/api-types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const ANALYST_OPTIONS = [
  { value: "market", label: "Market Analyst" },
  { value: "social", label: "Social Analyst" },
  { value: "news", label: "News Analyst" },
  { value: "fundamentals", label: "Fundamentals Analyst" },
] as const;

const LANGUAGE_OPTIONS = [
  "English",
  "Chinese",
  "Japanese",
  "Korean",
  "Hindi",
  "Spanish",
  "Portuguese",
  "French",
  "German",
  "Arabic",
  "Russian",
] as const;

function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function withQuery(path: string, query: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}${query}`;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function prettyStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function normalizeQuery(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function formatCandidateLabel(candidate: SymbolCandidate): string {
  return `${candidate.symbol} — ${candidate.name}`;
}

function formatCandidateMeta(candidate: SymbolCandidate): string {
  const parts = [candidate.exchange, candidate.region].filter(Boolean);
  return parts.join(" — ");
}

function resolutionMatchesInput(resolution: ResolvedTicker | null, input: string): boolean {
  if (!resolution) {
    return false;
  }

  const normalized = normalizeQuery(input).toUpperCase();
  if (!normalized) {
    return false;
  }

  return (
    normalizeQuery(resolution.original_input).toUpperCase() === normalized ||
    (resolution.resolved_symbol ?? "").toUpperCase() === normalized
  );
}

function resolutionStatusMessage(resolution: ResolvedTicker): string {
  if (resolution.status === "RESOLVED") {
    const label = resolution.company_name
      ? `${resolution.resolved_symbol} — ${resolution.company_name}`
      : resolution.resolved_symbol ?? resolution.original_input;

    if (
      resolution.resolved_symbol &&
      normalizeQuery(resolution.original_input).toUpperCase() !== resolution.resolved_symbol.toUpperCase()
    ) {
      return `Resolved to ${label}`;
    }

    return `Validated ${label}`;
  }

  return resolution.reason?.trim() || "Unable to resolve the requested symbol.";
}

function resolutionFailureMessage(resolution: ResolvedTicker): string {
  if (resolution.status === "NOT_FOUND") {
    return `No verified symbol found for "${resolution.original_input}".`;
  }
  if (resolution.status === "AMBIGUOUS") {
    return "Multiple close matches were found. Choose one to continue.";
  }
  if (resolution.status === "INSUFFICIENT_DATA") {
    return resolution.reason?.trim() || "This symbol does not have enough market data.";
  }
  return resolution.reason?.trim() || "Unable to resolve the requested symbol.";
}

function formatResolutionError(payload: ResolutionErrorResponse): string {
  const detail = payload.detail;
  if (!detail) {
    return "Unable to resolve the requested symbol.";
  }

  const parts = [detail.message];
  const candidates = detail.resolution?.candidates ?? [];
  if (candidates.length > 0) {
    parts.push("");
    parts.push("Suggestions:");
    for (const candidate of candidates.slice(0, 5)) {
      parts.push(
        `- ${candidate.symbol} — ${candidate.name}${candidate.exchange ? ` — ${candidate.exchange}` : ""}${candidate.region ? ` — ${candidate.region}` : ""}`,
      );
    }
  }
  return parts.join("\n");
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildPrintableReport(snapshot: RunSnapshot): string {
  const reportSections = snapshot.reports.filter(
    (report) => report.content && report.key !== "final_trade_decision",
  );
  const renderedSections = reportSections
    .map(
      (report) => `
        <section class="report-section">
          <h2>${escapeHtml(report.label)}</h2>
          <pre>${escapeHtml(report.content ?? "")}</pre>
        </section>
      `,
    )
    .join("");

  const finalDecision = snapshot.final_decision
    ? `
      <section class="final-section">
        <div class="meta-row">
          <span class="label">Final Signal</span>
          <span class="signal">${escapeHtml(snapshot.final_signal ?? "Pending")}</span>
        </div>
        <pre>${escapeHtml(snapshot.final_decision)}</pre>
      </section>
    `
    : "";

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapeHtml(snapshot.ticker)} Research Report</title>
    <style>
      :root {
        color-scheme: light;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        color: #1c1713;
        background: #f7f1e8;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
      }
      .page {
        width: min(980px, calc(100% - 48px));
        margin: 24px auto 40px;
        padding: 28px;
        background: #fffaf3;
        border: 1px solid #e8dccb;
      }
      h1,
      h2 {
        margin: 0;
        font-family: "Iowan Old Style", Georgia, serif;
      }
      h1 {
        font-size: 2rem;
        margin-bottom: 8px;
      }
      h2 {
        font-size: 1.15rem;
        margin-bottom: 12px;
      }
      .meta-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px 18px;
        margin: 20px 0 24px;
      }
      .meta-row {
        display: grid;
        gap: 4px;
      }
      .label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #9a5d2d;
        font-weight: 700;
      }
      .value,
      .signal {
        font-weight: 700;
      }
      .signal {
        color: #2f6b54;
      }
      .final-section,
      .report-section {
        margin-top: 24px;
        padding-top: 20px;
        border-top: 1px solid #eadfce;
      }
      pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        line-height: 1.58;
        font-family: "SFMono-Regular", "JetBrains Mono", monospace;
        font-size: 0.92rem;
      }
      @page {
        size: A4;
        margin: 14mm;
      }
      @media print {
        body {
          background: #ffffff;
        }
        .page {
          width: 100%;
          margin: 0;
          padding: 0;
          border: 0;
        }
      }
    </style>
  </head>
  <body>
    <main class="page">
      <h1>${escapeHtml(snapshot.ticker)} Research Report</h1>
      <div class="meta-grid">
        ${
          snapshot.resolved_from
            ? `
        <div class="meta-row">
          <span class="label">Resolved Input</span>
          <span class="value">${escapeHtml(snapshot.resolved_from)} -> ${escapeHtml(snapshot.ticker)}${snapshot.company_name ? ` — ${escapeHtml(snapshot.company_name)}` : ""}</span>
        </div>
        `
            : ""
        }
        <div class="meta-row">
          <span class="label">Analysis Date</span>
          <span class="value">${escapeHtml(snapshot.analysis_date)}</span>
        </div>
        <div class="meta-row">
          <span class="label">Generated</span>
          <span class="value">${escapeHtml(snapshot.finished_at ?? snapshot.started_at)}</span>
        </div>
        <div class="meta-row">
          <span class="label">Provider</span>
          <span class="value">${escapeHtml(snapshot.provider)}</span>
        </div>
        <div class="meta-row">
          <span class="label">Language</span>
          <span class="value">${escapeHtml(snapshot.output_language)}</span>
        </div>
        <div class="meta-row">
          <span class="label">Quick Model</span>
          <span class="value">${escapeHtml(snapshot.quick_model)}</span>
        </div>
        <div class="meta-row">
          <span class="label">Deep Model</span>
          <span class="value">${escapeHtml(snapshot.deep_model)}</span>
        </div>
      </div>
      ${finalDecision}
      ${renderedSections}
    </main>
  </body>
</html>`;
}

export function ResearchWorkbench() {
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [quickModel, setQuickModel] = useState("");
  const [quickCustom, setQuickCustom] = useState("");
  const [deepModel, setDeepModel] = useState("");
  const [deepCustom, setDeepCustom] = useState("");
  const [analysts, setAnalysts] = useState<string[]>(
    ANALYST_OPTIONS.map((option) => option.value),
  );
  const [ticker, setTicker] = useState("NVDA");
  const [analysisDate, setAnalysisDate] = useState(todayIso());
  const [tickerResolution, setTickerResolution] = useState<ResolvedTicker | null>(null);
  const [tickerCandidates, setTickerCandidates] = useState<SymbolCandidate[]>([]);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [isCheckingTicker, setIsCheckingTicker] = useState(false);
  const [outputLanguage, setOutputLanguage] = useState("English");
  const [customLanguage, setCustomLanguage] = useState("");
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [checkpointEnabled, setCheckpointEnabled] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoadingProviders, setIsLoadingProviders] = useState(true);
  const [isValidatingKey, setIsValidatingKey] = useState(false);
  const [validationResult, setValidationResult] = useState<ValidateKeyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const deferredSnapshot = useDeferredValue(snapshot);

  const selectedProvider = useMemo(
    () => providers.find((item) => item.value === provider) ?? null,
    [providers, provider],
  );

  const quickNeedsCustom = quickModel === "custom";
  const deepNeedsCustom = deepModel === "custom";
  const languageNeedsCustom = outputLanguage === "custom";

  useEffect(() => {
    async function loadProviders() {
      try {
        setIsLoadingProviders(true);
        const response = await fetch(apiUrl("/providers/models"));
        if (!response.ok) {
          throw new Error("Failed to load providers.");
        }
        const data = (await response.json()) as ProviderOption[];
        setProviders(data);
        if (data.length > 0) {
          setProvider(data[0].value);
        }
      } catch (loadError) {
        const nextMessage =
          loadError instanceof Error ? loadError.message : "Unable to load providers.";
        setError(nextMessage);
      } finally {
        setIsLoadingProviders(false);
      }
    }

    void loadProviders();
  }, []);

  useEffect(() => {
    if (!selectedProvider) {
      return;
    }

    if (
      selectedProvider.quick_models.length > 0 &&
      !selectedProvider.quick_models.some((item) => item.value === quickModel)
    ) {
      setQuickModel(selectedProvider.quick_models[0].value);
      setQuickCustom("");
    }

    if (
      selectedProvider.deep_models.length > 0 &&
      !selectedProvider.deep_models.some((item) => item.value === deepModel)
    ) {
      setDeepModel(selectedProvider.deep_models[0].value);
      setDeepCustom("");
    }

    setValidationResult(null);
    setBaseUrl(selectedProvider.base_url ?? "");
  }, [selectedProvider, quickModel, deepModel]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!tickerResolution || resolutionMatchesInput(tickerResolution, ticker)) {
      return;
    }
    setTickerResolution(null);
    setTickerCandidates([]);
    setTickerError(null);
  }, [ticker, tickerResolution]);

  function toggleAnalyst(value: string) {
    setAnalysts((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  }

  async function validateKey() {
    if (!selectedProvider) {
      return;
    }

    const modelToValidate =
      (quickNeedsCustom ? quickCustom.trim() : quickModel) ||
      (deepNeedsCustom ? deepCustom.trim() : deepModel);

    if (!modelToValidate) {
      setValidationResult({
        valid: false,
        provider,
        model: "",
        message: "Select a model first.",
      });
      return;
    }

    setIsValidatingKey(true);
    setValidationResult(null);
    setError(null);

    try {
      const response = await fetch(apiUrl("/validate-key"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          llm_provider: provider,
          model: modelToValidate,
          api_key: apiKey.trim() || null,
          base_url: baseUrl.trim() || null,
        }),
      });

      const data = (await response.json()) as ValidateKeyResponse;
      setValidationResult(data);
      if (!data.valid) {
        setError(data.message);
      }
    } catch (validateError) {
      const nextMessage =
        validateError instanceof Error ? validateError.message : "Unable to validate the API key.";
      setValidationResult({
        valid: false,
        provider,
        model: modelToValidate,
        message: nextMessage,
      });
      setError(nextMessage);
    } finally {
      setIsValidatingKey(false);
    }
  }

  async function fetchFinalResult(resultUrl: string) {
    const response = await fetch(apiUrl(resultUrl));
    if (!response.ok) {
      return;
    }
    const data = (await response.json()) as RunSnapshot;
    startTransition(() => {
      setSnapshot(data);
    });
  }

  function connectToStream(run: RunCreatedResponse) {
    eventSourceRef.current?.close();
    const source = new EventSource(apiUrl(run.stream_url));
    eventSourceRef.current = source;

    source.addEventListener("snapshot", (event) => {
      const nextSnapshot = JSON.parse(event.data) as RunSnapshot;
      startTransition(() => {
        setSnapshot(nextSnapshot);
        setRunId(nextSnapshot.run_id);
        setReportUrl((current) => current ?? `/runs/${nextSnapshot.run_id}/report`);
      });

      if (nextSnapshot.status === "error") {
        setError(nextSnapshot.error ?? "The run failed.");
        setIsRunning(false);
        source.close();
      }
    });

    source.addEventListener("complete", async () => {
      setIsRunning(false);
      source.close();
      await fetchFinalResult(run.result_url);
    });

    source.onerror = () => {
      setIsRunning(false);
    };
  }

  async function checkTicker(query: string): Promise<ResolvedTicker | null> {
    const normalized = normalizeQuery(query);
    if (!normalized) {
      setTickerResolution(null);
      setTickerCandidates([]);
      setTickerError("Enter a symbol or company name.");
      return null;
    }

    try {
      setIsCheckingTicker(true);
      setTickerError(null);
      setTickerCandidates([]);
      const response = await fetch(apiUrl("/api/symbols/resolve"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: normalized,
          analysis_date: analysisDate,
        }),
      });

      if (!response.ok) {
        const message = (await response.text()) || "Unable to resolve the requested symbol.";
        throw new Error(message);
      }

      const resolved = (await response.json()) as ResolvedTicker;
      setTickerResolution(resolved);

      if (resolved.status === "RESOLVED") {
        if (resolved.resolved_symbol) {
          setTicker(resolved.resolved_symbol);
        }
        return resolved;
      }

      setTickerCandidates((resolved.candidates ?? []).slice(0, 5));
      setTickerError(resolutionFailureMessage(resolved));
      return resolved;
    } catch (resolveError) {
      const message =
        resolveError instanceof Error
          ? resolveError.message
          : "Unable to resolve the requested symbol.";
      setTickerCandidates([]);
      setTickerError(message);
      return null;
    } finally {
      setIsCheckingTicker(false);
    }
  }

  async function handleTickerSelection(candidate: SymbolCandidate) {
    setTicker(candidate.symbol);
    setTickerError(null);
    await checkTicker(candidate.symbol);
  }

  async function startRun() {
    if (!selectedProvider) {
      return;
    }
    if (analysts.length === 0) {
      setError("Select at least one analyst.");
      return;
    }

    const resolvedQuickModel = quickNeedsCustom ? quickCustom.trim() : quickModel;
    const resolvedDeepModel = deepNeedsCustom ? deepCustom.trim() : deepModel;
    const resolvedLanguage = languageNeedsCustom ? customLanguage.trim() : outputLanguage;

    if (!resolvedQuickModel || !resolvedDeepModel || !resolvedLanguage) {
      setError("Complete the model and output fields.");
      return;
    }

    const resolvedTicker =
      tickerResolution?.status === "RESOLVED" && resolutionMatchesInput(tickerResolution, ticker)
        ? tickerResolution
        : null;
    if (!resolvedTicker) {
      setTickerError("Check the symbol before starting.");
      return;
    }

    setError(null);
    setSnapshot(null);
    setRunId(null);
    setReportUrl(null);
    setIsRunning(true);

    try {
      const response = await fetch(apiUrl("/runs"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ticker: resolvedTicker.resolved_symbol ?? ticker,
          analysis_date: analysisDate,
          llm_provider: provider,
          api_key: apiKey.trim() || null,
          quick_model: resolvedQuickModel,
          deep_model: resolvedDeepModel,
          analysts,
          output_language: resolvedLanguage,
          base_url: baseUrl.trim() || null,
          checkpoint_enabled: checkpointEnabled,
        }),
      });

      if (!response.ok) {
        let message = "Failed to create the run.";
        try {
          const payload = (await response.json()) as ResolutionErrorResponse;
          message = formatResolutionError(payload);
        } catch {
          message = (await response.text()) || message;
        }
        throw new Error(message);
      }

      const run = (await response.json()) as RunCreatedResponse;
      setRunId(run.run_id);
      setReportUrl(run.report_url);
      connectToStream(run);
    } catch (runError) {
      const nextMessage = runError instanceof Error ? runError.message : "Failed to start the run.";
      setError(nextMessage);
      setIsRunning(false);
    }
  }

  function exportPdfReport() {
    if (reportUrl) {
      window.open(apiUrl(withQuery(reportUrl, "autoprint=1")), "_blank", "noopener,noreferrer");
      return;
    }

    if (!deferredSnapshot) {
      return;
    }

    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      setError("Unable to open the print window.");
      return;
    }

    const reportHtml = buildPrintableReport(deferredSnapshot);
    printWindow.document.open();
    printWindow.document.write(reportHtml);
    printWindow.document.close();
    printWindow.focus();

    window.setTimeout(() => {
      printWindow.print();
    }, 250);
  }

  function openHtmlReport() {
    if (!reportUrl && !deferredSnapshot?.run_id) {
      return;
    }
    window.open(apiUrl(reportUrl ?? `/runs/${deferredSnapshot?.run_id}/report`), "_blank", "noopener,noreferrer");
  }

  return (
    <main className="shell">
      <section className="layout">
        <aside className="panel controlPanel">
          <div className="sectionHeader">
            <h2>MarketMind AI</h2>
          </div>

          <div className="formGrid">
            <label className="field">
              <span>LLM Provider</span>
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                disabled={isLoadingProviders}
              >
                {providers.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="field">
              <span>API Key</span>
              <div className="inlineField">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={
                    selectedProvider?.requires_api_key
                      ? "Enter the provider API key"
                      : "Optional for local Ollama"
                  }
                />
                <button
                  type="button"
                  className="secondaryButton"
                  onClick={() => {
                    void validateKey();
                  }}
                  disabled={isValidatingKey || !provider}
                >
                  {isValidatingKey ? "Checking..." : "Check Key"}
                </button>
              </div>
              {validationResult ? (
                <p className={validationResult.valid ? "statusGood" : "statusBad"}>
                  {validationResult.valid ? "Connected: " : "Failed: "}
                  {validationResult.message}
                </p>
              ) : null}
            </div>

            <label className="field">
              <span>Provider Base URL</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={selectedProvider?.base_url ?? "Optional custom chat-completions endpoint"}
              />
            </label>

            <div className="dualField">
              <label className="field">
                <span>Quick Model</span>
                <select
                  value={quickModel}
                  onChange={(event) => setQuickModel(event.target.value)}
                  disabled={!selectedProvider}
                >
                  {selectedProvider?.quick_models.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              {quickNeedsCustom ? (
                <label className="field">
                  <span>Quick Model ID</span>
                  <input
                    value={quickCustom}
                    onChange={(event) => setQuickCustom(event.target.value)}
                    placeholder="Enter a custom quick model ID"
                  />
                </label>
              ) : null}
            </div>

            <div className="dualField">
              <label className="field">
                <span>Deep Model</span>
                <select
                  value={deepModel}
                  onChange={(event) => setDeepModel(event.target.value)}
                  disabled={!selectedProvider}
                >
                  {selectedProvider?.deep_models.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              {deepNeedsCustom ? (
                <label className="field">
                  <span>Deep Model ID</span>
                  <input
                    value={deepCustom}
                    onChange={(event) => setDeepCustom(event.target.value)}
                    placeholder="Enter a custom deep model ID"
                  />
                </label>
              ) : null}
            </div>

            <div className="field">
              <span>Analysts</span>
              <div className="chipGrid">
                {ANALYST_OPTIONS.map((option) => {
                  const active = analysts.includes(option.value);
                  return (
                    <button
                      key={option.value}
                      type="button"
                      className={active ? "chipButton active" : "chipButton"}
                      onClick={() => toggleAnalyst(option.value)}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="tripleField">
              <label className="field">
                <span>Ticker</span>
                <div className="inlineField">
                  <input
                    value={ticker}
                    placeholder="AAPL or Apple"
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => {
                      setTicker(event.target.value);
                      setTickerResolution(null);
                      setTickerCandidates([]);
                      setTickerError(null);
                    }}
                  />
                  <button
                    type="button"
                    className="secondaryButton"
                    onClick={() => {
                      void checkTicker(ticker);
                    }}
                    disabled={isCheckingTicker}
                  >
                    {isCheckingTicker ? "Checking..." : "Check Symbol"}
                  </button>
                </div>
                {tickerResolution?.status === "RESOLVED" ? (
                  <p className="statusGood tickerStatus">{resolutionStatusMessage(tickerResolution)}</p>
                ) : null}
                {tickerError ? <p className="statusBad tickerStatus">{tickerError}</p> : null}
                {tickerCandidates.length > 0 ? (
                  <div className="tickerPrompt">
                    <p className="summaryLine tickerPromptTitle">Did you mean:</p>
                    <div className="tickerPromptActions">
                      {tickerCandidates.map((candidate) => (
                        <button
                          key={`${candidate.symbol}-${candidate.exchange ?? "na"}-${candidate.region ?? "na"}`}
                          type="button"
                          className="tickerPromptButton"
                          onClick={() => {
                            void handleTickerSelection(candidate);
                          }}
                        >
                          <span>{formatCandidateLabel(candidate)}</span>
                          {formatCandidateMeta(candidate) ? (
                            <span className="tickerPromptMeta">{formatCandidateMeta(candidate)}</span>
                          ) : null}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </label>
              <label className="field">
                <span>Analysis Date</span>
                <input
                  type="date"
                  value={analysisDate}
                  max={todayIso()}
                  onChange={(event) => {
                    setAnalysisDate(event.target.value);
                    setTickerResolution(null);
                    setTickerCandidates([]);
                    setTickerError(null);
                  }}
                />
              </label>
              <label className="field">
                <span>Output Language</span>
                <select
                  value={outputLanguage}
                  onChange={(event) => setOutputLanguage(event.target.value)}
                >
                  {LANGUAGE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                  <option value="custom">Custom</option>
                </select>
              </label>
            </div>

            {languageNeedsCustom ? (
              <label className="field">
                <span>Custom Language</span>
                <input
                  value={customLanguage}
                  onChange={(event) => setCustomLanguage(event.target.value)}
                  placeholder="For example: Turkish or Vietnamese"
                />
              </label>
            ) : null}

            <label className="toggleField">
              <input
                type="checkbox"
                checked={checkpointEnabled}
                onChange={(event) => setCheckpointEnabled(event.target.checked)}
              />
              <span>
                <strong>Resume with checkpoints</strong>
                <small>Save graph progress so interrupted runs can resume.</small>
              </span>
            </label>

            <button type="button" className="primaryButton" onClick={() => void startRun()} disabled={isRunning}>
              {isRunning ? "Running..." : "Start Research"}
            </button>

            {error ? <p className="statusBad">{error}</p> : null}
          </div>
        </aside>

        <section className="workspace">
          <div className="panel statusPanel">
            <div className="sectionHeader compact">
              <div>
                <p className="sectionKicker">Run Status</p>
                <h2>{deferredSnapshot ? `${deferredSnapshot.ticker} · ${deferredSnapshot.analysis_date}` : "Ready"}</h2>
              </div>
              <div className="statusCluster">
                <span className={`pill ${deferredSnapshot?.status ?? "queued"}`}>
                  {prettyStatus(deferredSnapshot?.status ?? "queued")}
                </span>
                <span className="ghostPill">{runId ?? "No run yet"}</span>
              </div>
            </div>
            <p className="summaryLine">{deferredSnapshot?.latest_update ?? "--"}</p>
            {deferredSnapshot?.resolved_from ? (
              <p className="summaryLine subtle">
                Resolved: {deferredSnapshot.resolved_from} -&gt; {deferredSnapshot.ticker}
                {deferredSnapshot.company_name ? ` — ${deferredSnapshot.company_name}` : ""}
              </p>
            ) : null}
            <p className="summaryLine subtle">
              Current Agent: {deferredSnapshot?.current_agent ?? "--"}
            </p>
          </div>

          <div className="dashboardGrid">
            <section className="panel spanTwo">
              <div className="sectionHeader compact">
                <p className="sectionKicker">Agent Board</p>
                <h3>Agent Progress</h3>
              </div>
              <div className="agentGrid">
                {(deferredSnapshot?.agents ?? []).map((agent) => (
                  <article key={agent.key} className="agentCard">
                    <h4>{agent.label}</h4>
                    <span className={`chip ${agent.status}`}>{prettyStatus(agent.status)}</span>
                  </article>
                ))}
                {(deferredSnapshot?.agents ?? []).length === 0 ? (
                  <p className="emptyState">No agents</p>
                ) : null}
              </div>
            </section>

            <section className="panel">
              <div className="sectionHeader compact">
                <div>
                  <p className="sectionKicker">Final Call</p>
                  <h3>Final Decision</h3>
                </div>
                {deferredSnapshot?.final_decision ? (
                  <div className="reportActions">
                    <button
                      type="button"
                      className="secondaryButton exportButton"
                      onClick={openHtmlReport}
                    >
                      Open Report
                    </button>
                    <button
                      type="button"
                      className="secondaryButton exportButton"
                      onClick={exportPdfReport}
                    >
                      Export PDF
                    </button>
                  </div>
                ) : null}
              </div>
              {deferredSnapshot?.final_decision ? (
                <div className="finalCall">
                  <span className="signalBanner">
                    {deferredSnapshot.final_signal ?? "Pending"}
                  </span>
                  <pre>{deferredSnapshot.final_decision}</pre>
                </div>
              ) : (
                <p className="emptyState">Pending</p>
              )}
            </section>

            <section className="panel">
              <div className="sectionHeader compact">
                <p className="sectionKicker">Tool Feed</p>
                <h3>Tool Calls</h3>
              </div>
              <div className="feedList">
                {(deferredSnapshot?.tool_calls ?? []).length === 0 ? (
                  <p className="emptyState">No tools</p>
                ) : (
                  deferredSnapshot?.tool_calls
                    .slice()
                    .reverse()
                    .map((tool, index) => (
                      <article
                        key={
                          tool.id ??
                          `${tool.timestamp}-${tool.name}-${tool.args.slice(0, 24)}-${index}`
                        }
                        className="feedCard"
                      >
                        <div className="feedMeta">
                          <span>{tool.timestamp}</span>
                          <span>{tool.name}</span>
                        </div>
                        <pre>{tool.args}</pre>
                      </article>
                    ))
                )}
              </div>
            </section>

            <section className="panel">
              <div className="sectionHeader compact">
                <p className="sectionKicker">Agent Feed</p>
                <h3>Messages</h3>
              </div>
              <div className="feedList">
                {(deferredSnapshot?.messages ?? []).length === 0 ? (
                  <p className="emptyState">No messages</p>
                ) : (
                  deferredSnapshot?.messages
                    .slice()
                    .reverse()
                    .map((message, index) => (
                      <article
                        key={
                          message.id ??
                          `${message.timestamp}-${message.kind}-${message.content.slice(0, 24)}-${index}`
                        }
                        className="feedCard"
                      >
                        <div className="feedMeta">
                          <span>{message.timestamp}</span>
                          <span>{message.kind}</span>
                        </div>
                        <pre>{message.content}</pre>
                      </article>
                    ))
                )}
              </div>
            </section>

            <section className="panel spanTwo">
              <div className="sectionHeader compact">
                <p className="sectionKicker">Research Dossier</p>
                <h3>Stage Reports</h3>
              </div>
              <div className="reportGrid">
                {(deferredSnapshot?.reports ?? []).filter((report) => report.content).length === 0 ? (
                  <p className="emptyState">No reports</p>
                ) : (
                  deferredSnapshot?.reports
                    .filter((report) => report.content)
                    .map((report) => (
                      <article key={report.key} className="reportCard">
                        <header>{report.label}</header>
                        <pre>{report.content}</pre>
                      </article>
                    ))
                )}
              </div>
            </section>
          </div>
        </section>
      </section>
    </main>
  );
}
