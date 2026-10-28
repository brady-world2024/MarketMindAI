"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import type {
  ProviderOption,
  ResolvedTicker,
  RunCreatedResponse,
  RunSnapshot,
  SymbolCandidate,
  ValidateKeyResponse,
} from "../lib/api-types";
import { HumanReviewPanel } from "./human-review";
import { initialProviderSettings, providerSettingsReducer, type SettingsField } from "../lib/provider-settings";
import { ResearchReport } from "./research-report";
import { ResearchProgress, type StreamState } from "./research-progress";
import { ReportText } from "./report-text";
import { ReportHistory } from "./report-history";

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
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
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
      <p>Human review: ${escapeHtml(snapshot.review?.status.replaceAll("_", " ") ?? "No human review recorded")}
        ${snapshot.review ? ` · Version ${snapshot.review.version} · ${escapeHtml(snapshot.review.report_hash)}` : ""}</p>
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
  const [settings, dispatchSettings] = useReducer(providerSettingsReducer, initialProviderSettings);
  const { provider, apiKey, baseUrl, quickModel, quickCustom, deepModel, deepCustom, isValidatingKey, validationResult } = settings;
  const [analysts, setAnalysts] = useState<string[]>(
    ANALYST_OPTIONS.map((option) => option.value),
  );
  const [ticker, setTicker] = useState("NVDA");
  const [analysisDate, setAnalysisDate] = useState(todayIso());
  const [tickerResolution, setTickerResolution] = useState<ResolvedTicker | null>(null);
  const [tickerCandidates, setTickerCandidates] = useState<SymbolCandidate[]>([]);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [outputLanguage, setOutputLanguage] = useState("English");
  const [customLanguage, setCustomLanguage] = useState("");
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [checkpointEnabled, setCheckpointEnabled] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [isLoadingProviders, setIsLoadingProviders] = useState(true);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [researchDepth, setResearchDepth] = useState(1);
  const [showApiKey, setShowApiKey] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const loadGeneration = useRef(0);
  const connectionController = useRef<AbortController | null>(null);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const deferredSnapshot = useDeferredValue(snapshot);
  const activeRunRef = useRef(runId);
  activeRunRef.current = runId;

  const selectedProvider = useMemo(
    () => providers.find((item) => item.value === provider) ?? null,
    [providers, provider],
  );

  const quickNeedsCustom = quickModel === "custom";
  const deepNeedsCustom = deepModel === "custom";
  const languageNeedsCustom = outputLanguage === "custom";

  function editSetting(field: SettingsField, value: string) {
    connectionController.current?.abort();
    dispatchSettings({ type: "edit", field, value });
  }

  function chooseProvider(value: string) {
    const option = providers.find((item) => item.value === value);
    if (!option) return;
    connectionController.current?.abort();
    setShowApiKey(false);
    dispatchSettings({ type: "select", provider: option });
  }

  useEffect(() => {
    let cancelled = false;
    async function loadProviders() {
      try {
        setIsLoadingProviders(true);
        const response = await fetch(apiUrl("/providers/models"));
        if (!response.ok) {
          throw new Error("Failed to load providers.");
        }
        const data = (await response.json()) as ProviderOption[];
        if (cancelled) return;
        setProviders(data);
        if (data.length > 0) {
          dispatchSettings({ type: "select", provider: data[0] });
        }
      } catch (loadError) {
        if (cancelled) return;
        const nextMessage =
          loadError instanceof Error ? loadError.message : "Unable to load providers.";
        setError(nextMessage);
      } finally {
        if (!cancelled) setIsLoadingProviders(false);
      }
    }

    void loadProviders();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    return () => {
      loadGeneration.current += 1;
      eventSourceRef.current?.close();
      connectionController.current?.abort();
    };
  }, []);

  useEffect(() => {
    let savedRun: string | null = null;
    try { savedRun = window.localStorage.getItem("marketmind-active-run"); } catch { /* Storage may be unavailable. */ }
    if (savedRun && /^[a-zA-Z0-9_-]+$/.test(savedRun)) {
      void openSavedRun(savedRun).catch((cause) => setError(cause instanceof Error ? cause.message : "Unable to restore the saved run."));
    }
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
      dispatchSettings({ type: "validation-finished", revision: settings.revision, result: {
        valid: false,
        provider,
        model: "",
        message: "Select a model first.",
      } });
      return;
    }

    const revision = settings.revision;
    connectionController.current?.abort();
    const controller = new AbortController();
    connectionController.current = controller;
    dispatchSettings({ type: "validation-started", revision });

    try {
      const response = await fetch(apiUrl("/validate-key"), {
        method: "POST",
        signal: controller.signal,
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

      const payload = await response.json();
      const data: ValidateKeyResponse = response.ok ? payload : {
        valid: false, provider, model: modelToValidate,
        message: typeof payload.detail === "string" ? payload.detail : "Connection check failed. Check the provider, model and API key.",
      };
      dispatchSettings({ type: "validation-finished", revision, result: data });
    } catch (validateError) {
      if (controller.signal.aborted || settingsRef.current.revision !== revision) return;
      const nextMessage =
        validateError instanceof Error ? validateError.message : "Unable to validate the API key.";
      dispatchSettings({ type: "validation-finished", revision, result: {
        valid: false,
        provider,
        model: modelToValidate,
        message: nextMessage,
      } });
    }
  }

  function connectToStream(run: RunCreatedResponse) {
    eventSourceRef.current?.close();
    const source = new EventSource(apiUrl(run.stream_url));
    eventSourceRef.current = source;
    const generation = loadGeneration.current;
    let finished = false;
    const isCurrent = () => !finished && eventSourceRef.current === source && generation === loadGeneration.current;
    const finish = (next: RunSnapshot) => {
      finished = true;
      setSnapshot(next);
      setRunId(next.run_id);
      setReportUrl(run.report_url);
      setIsRunning(false);
      setStreamState("finished");
      if (next.status === "error") setError(next.error ?? "The analysis failed.");
      source.close();
    };
    setStreamState("connecting");
    source.onopen = () => { if (isCurrent()) setStreamState("live"); };

    source.addEventListener("snapshot", (event) => {
      if (!isCurrent()) return;
      const next = JSON.parse(event.data) as RunSnapshot;
      if (next.status === "error" || next.status === "completed") { finish(next); return; }
      startTransition(() => {
        setSnapshot(next);
        setRunId(next.run_id);
        setReportUrl(run.report_url);
      });
    });

    source.addEventListener("complete", (event) => {
      if (!isCurrent()) return;
      finish(JSON.parse(event.data) as RunSnapshot);
    });

    source.onerror = (event) => {
      if (!isCurrent()) return;
      // The server sends an error message for a failed run. Transport errors have no data.
      if (event instanceof MessageEvent && event.data) {
        const payload = JSON.parse(event.data) as { message?: string };
        finished = true;
        setError(payload.message ?? "The analysis failed.");
        setSnapshot((current) => current?.run_id === run.run_id
          ? { ...current, status: "error", error: payload.message ?? "The analysis failed." } : current);
        setIsRunning(false);
        setStreamState("finished");
        source.close();
        return;
      }
      setStreamState(source.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    };
  }

  function rememberRun(id: string) {
    try { window.localStorage.setItem("marketmind-active-run", id); } catch { /* The review queue still provides recovery. */ }
  }

  async function openSavedRun(id: string) {
    const generation = ++loadGeneration.current;
    eventSourceRef.current?.close();
    const response = await fetch(apiUrl(`/runs/${encodeURIComponent(id)}`));
    if (generation !== loadGeneration.current) return;
    if (!response.ok) throw new Error("Unable to load the saved run. Refresh recent reports and choose another report.");
    const next = (await response.json()) as RunSnapshot;
    if (generation !== loadGeneration.current) return;
    setSnapshot(next);
    setRunId(id);
    setReportUrl(`/runs/${id}/report`);
    setError(null);
    rememberRun(id);
    const running = next.status === "queued" || next.status === "running";
    setIsRunning(running);
    setStreamState(running ? "connecting" : "finished");
    if (running) connectToStream({ run_id: id, stream_url: `/runs/${id}/stream`, result_url: `/runs/${id}/result`, report_url: `/runs/${id}/report` });
  }

  function startRevision(run: RunCreatedResponse) {
    loadGeneration.current += 1;
    setSnapshot(null);
    setRunId(run.run_id);
    setReportUrl(run.report_url);
    setError(null);
    setIsRunning(true);
    rememberRun(run.run_id);
    connectToStream(run);
  }

  async function startRun() {
    if (!selectedProvider || isRunning || reviewBusy) {
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
    if (!normalizeQuery(ticker)) {
      setTickerError("Enter a company name or ticker to research.");
      return;
    }

    loadGeneration.current += 1;
    const generation = loadGeneration.current;
    eventSourceRef.current?.close();
    setError(null);
    setSnapshot(null);
    setRunId(null);
    setReportUrl(null);
    setIsRunning(true);
    setStreamState("connecting");
    setTickerError(null);
    setTickerCandidates([]);

    try {
      const response = await fetch(apiUrl("/runs"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ticker: resolvedTicker?.resolved_symbol ?? normalizeQuery(ticker),
          analysis_date: analysisDate,
          llm_provider: provider,
          api_key: apiKey.trim() || null,
          quick_model: resolvedQuickModel,
          deep_model: resolvedDeepModel,
          analysts,
          output_language: resolvedLanguage,
          base_url: baseUrl.trim() || null,
          checkpoint_enabled: checkpointEnabled,
          research_depth: researchDepth,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        if (generation !== loadGeneration.current) return;
        let message = text || "Failed to create the run.";
        try {
          const payload = JSON.parse(text);
          const detail = payload.detail;
          if (typeof detail === "string") message = detail;
          else if (Array.isArray(detail)) message = detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ");
          else if (detail?.message) {
            message = detail.message;
            setTickerCandidates(detail.resolution?.candidates ?? []);
          }
        } catch { /* A plain response body is already a useful error. */ }
        throw new Error(message);
      }

      const run = (await response.json()) as RunCreatedResponse;
      if (generation !== loadGeneration.current) return;
      if (run.ticker_resolution) setTickerResolution(run.ticker_resolution);
      setRunId(run.run_id);
      setReportUrl(run.report_url);
      rememberRun(run.run_id);
      connectToStream(run);
    } catch (runError) {
      if (generation !== loadGeneration.current) return;
      const nextMessage = runError instanceof Error ? runError.message : "Failed to start the run.";
      setError(nextMessage);
      setIsRunning(false);
      setStreamState("idle");
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

  const reportSnapshot = deferredSnapshot?.run_id === snapshot?.run_id ? deferredSnapshot : snapshot;
  const evidenceIds = (reportSnapshot?.evidence_ledger ?? []).flatMap((item) => item.evidence_id ? [item.evidence_id] : []);
  const hasResult = !!reportSnapshot?.final_decision;
  const offline = provider === "offline";

  return (
    <main className="shell">
      <header className="workbenchHeader"><div><p className="eyebrow">MarketMind AI</p>
        <h1>Research with a clearer view.</h1></div><p>Follow the evidence. Review the decision.</p></header>
      <div className="layout workbenchLayout">
        <aside className="setupColumn">
          <section className="panel setupPanel" aria-labelledby="setup-title">
            <div className="sectionHeader"><div><p className="sectionKicker">New research</p><h2 id="setup-title">What are you researching?</h2></div></div>
            <form className="formGrid" onSubmit={(event) => { event.preventDefault(); void startRun(); }}>
              <label className="field"><span>Company or ticker</span><input value={ticker} required
                placeholder="AAPL or Apple" autoComplete="off" spellCheck={false} onChange={(event) => {
                  setTicker(event.target.value); setTickerResolution(null); setTickerCandidates([]); setTickerError(null);
                }} /><small>Company names are resolved before research begins.</small></label>
              {tickerResolution?.status === "RESOLVED" && <p className="statusGood tickerStatus">{resolutionStatusMessage(tickerResolution)}</p>}
              {tickerError && <p className="statusBad" role="alert">{tickerError}</p>}
              {tickerCandidates.length > 0 && <div className="tickerPrompt"><p className="summaryLine">Choose the company you meant, then start research again:</p>
                {tickerCandidates.map((candidate) => <button type="button" className="tickerPromptButton"
                  key={`${candidate.symbol}-${candidate.exchange}`} onClick={() => {
                    setTicker(candidate.symbol); setTickerResolution(null); setTickerCandidates([]); setTickerError(null); setError(null);
                  }}><strong>{formatCandidateLabel(candidate)}</strong><small>{formatCandidateMeta(candidate)}</small></button>)}</div>}
              <div className="setupPair"><label className="field"><span>Analysis date</span><input type="date" required
                value={analysisDate} max={todayIso()} onChange={(event) => { setAnalysisDate(event.target.value); setTickerResolution(null); }} /></label>
                <label className="field"><span>Report language</span><select value={outputLanguage} onChange={(event) => setOutputLanguage(event.target.value)}>
                  {LANGUAGE_OPTIONS.map((item) => <option key={item}>{item}</option>)}<option value="custom">Custom</option></select></label></div>
              {languageNeedsCustom && <label className="field"><span>Custom language</span><input value={customLanguage} required
                placeholder="For example: Turkish" onChange={(event) => setCustomLanguage(event.target.value)} /></label>}
              <div className="providerSection"><label className="field"><span>AI provider</span><select value={provider}
                onChange={(event) => chooseProvider(event.target.value)} disabled={isLoadingProviders}>
                {isLoadingProviders && <option value="">Loading providers…</option>}
                {providers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                {!offline ? <><label className="field"><span>API key{!selectedProvider?.requires_api_key && " (optional)"}</span>
                  <div className="keyInput"><input type={showApiKey ? "text" : "password"} value={apiKey} autoComplete="off"
                    required={selectedProvider?.requires_api_key} placeholder="Enter this provider’s key"
                    onChange={(event) => editSetting("apiKey", event.target.value)} />
                    <button type="button" className="keyVisibility" aria-label={showApiKey ? "Hide API key" : "Show API key"}
                      aria-pressed={showApiKey} onClick={() => setShowApiKey(!showApiKey)}>{showApiKey ? "Hide" : "Show"}</button></div>
                  <small>Used for this run. Not saved with the report.</small></label>
                  <button type="button" className="secondaryButton connectionCheck" disabled={isValidatingKey || !provider}
                    onClick={() => void validateKey()}>{isValidatingKey ? "Checking connection…" : "Check connection"}</button></>
                  : <p className="offlineNotice">Offline demo uses sample data and local rules. No API key or paid model calls.</p>}
                {validationResult && <p role="status" className={validationResult.valid ? "statusGood" : "statusBad"}>{validationResult.message}</p>}
                {!offline && providers.some((item) => item.value === "offline") && <button type="button" className="reviewTextButton demoButton"
                  onClick={() => chooseProvider("offline")}>Try the offline demo · no key needed</button>}
              </div>
              <details className="advancedSettings"><summary>Advanced settings <small>Models, data and workflow</small></summary><div className="formGrid advancedBody">
                <label className="field"><span>Quick model</span><select value={quickModel} onChange={(event) => editSetting("quickModel", event.target.value)} disabled={!selectedProvider}>
                  {selectedProvider?.quick_models.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  {selectedProvider?.supports_custom_models && !selectedProvider.quick_models.some((item) => item.value === "custom") && <option value="custom">Custom model</option>}</select></label>
                {quickNeedsCustom && <label className="field"><span>Quick model ID</span><input value={quickCustom} required placeholder={selectedProvider?.custom_model_placeholder ?? "Custom model ID"}
                  onChange={(event) => editSetting("quickCustom", event.target.value)} /></label>}
                <label className="field"><span>Deep model</span><select value={deepModel} onChange={(event) => editSetting("deepModel", event.target.value)} disabled={!selectedProvider}>
                  {selectedProvider?.deep_models.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  {selectedProvider?.supports_custom_models && !selectedProvider.deep_models.some((item) => item.value === "custom") && <option value="custom">Custom model</option>}</select></label>
                {deepNeedsCustom && <label className="field"><span>Deep model ID</span><input value={deepCustom} required placeholder={selectedProvider?.custom_model_placeholder ?? "Custom model ID"}
                  onChange={(event) => editSetting("deepCustom", event.target.value)} /></label>}
                {!offline && <label className="field"><span>Provider base URL</span><input value={baseUrl} autoComplete="off"
                  placeholder={selectedProvider?.base_url ?? "Optional custom endpoint"} onChange={(event) => editSetting("baseUrl", event.target.value)} /></label>}
                <fieldset className="analystField"><legend>Analysts</legend><div className="chipGrid">{ANALYST_OPTIONS.map((option) => <button key={option.value}
                  type="button" aria-pressed={analysts.includes(option.value)} className={`chipButton ${analysts.includes(option.value) ? "active" : ""}`}
                  onClick={() => toggleAnalyst(option.value)}>{option.label}</button>)}</div></fieldset>
                <label className="field"><span>Research depth</span><select value={researchDepth} onChange={(event) => setResearchDepth(Number(event.target.value))}>
                  {[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value}{value === 1 ? " · Quickest" : value === 5 ? " · Most thorough" : ""}</option>)}</select>
                  <small>More depth may increase time and model usage.</small></label>
                <label className="toggleField"><input type="checkbox" checked={checkpointEnabled} onChange={(event) => setCheckpointEnabled(event.target.checked)} />
                  <span><strong>Resume with checkpoints</strong><small>Save workflow progress for interrupted runs.</small></span></label>
              </div></details>
              <button type="submit" className="primaryButton startResearch" disabled={isRunning || reviewBusy || isLoadingProviders || !provider}>
                {isRunning ? "Research in progress…" : offline ? "Start offline demo" : "Start research"}</button>
              {error && <p className="statusBad" role="alert">{error}</p>}
            </form>
          </section>
          <ReportHistory apiBaseUrl={API_BASE_URL} currentRunId={runId} reviewStatus={snapshot?.review?.status}
            running={isRunning || reviewBusy} onOpenRun={openSavedRun} />
        </aside>
        <section className="workspace" aria-label="Research workspace">
          <ResearchProgress snapshot={snapshot} running={isRunning} streamState={streamState}
            onReconnect={() => { if (runId) void openSavedRun(runId).catch((cause) => setError(cause instanceof Error ? cause.message : "Unable to reconnect.")); }} />
          {hasResult && reportSnapshot && <ResearchReport snapshot={reportSnapshot} onOpenReport={openHtmlReport} onExport={exportPdfReport} />}
          {hasResult && <HumanReviewPanel key={snapshot?.run_id} snapshot={snapshot} apiBaseUrl={API_BASE_URL} running={isRunning}
            onOpenRun={openSavedRun} onBusyChange={setReviewBusy} onSnapshot={(next) => setSnapshot((current) => current?.run_id === next.run_id ? next : current)} onRevision={(run) => { if (activeRunRef.current === snapshot?.run_id) startRevision(run); }} />}
          {!snapshot && !isRunning && <section className="panel welcomePanel"><p className="sectionKicker">Your research workspace</p><h2>From a question to a reviewed report.</h2>
            <p>Start with a company. MarketMind gathers evidence, builds an analysis and checks its reasoning. You review the result before accepting a decision.</p>
            <ol><li><strong>Set the question</strong><span>Choose a company, date and language.</span></li><li><strong>Read the evidence</strong><span>See the conclusion, risks and gaps together.</span></li>
              <li><strong>Make the call</strong><span>Approve, request changes or reject this version.</span></li></ol></section>}
          {(reportSnapshot?.reports ?? []).some((report) => report.content) && <details className="panel stagePanel"><summary>Stage reports <span>Read the research behind the summary</span></summary>
            <div className="stageReports">{reportSnapshot?.reports.filter((report) => report.content).map((report) => <details className="stageReport" key={report.key}>
              <summary>{report.label}</summary><ReportText text={report.content!} evidenceIds={evidenceIds} evidencePrefix={reportSnapshot.run_id} />
              <details className="reportExtra"><summary>View raw text</summary><pre className="rawOutput">{report.content}</pre></details></details>)}</div></details>}
          {snapshot && <details className="panel executionPanel"><summary>Execution details <span>Agents, tool calls and messages</span></summary>
            <div className="agentGrid">{snapshot.agents.map((agent) => <article key={agent.key} className="agentCard"><h4>{agent.label}</h4>
              <span className={`chip ${agent.status}`}>{prettyStatus(agent.status)}</span></article>)}</div>
            <details className="reportExtra"><summary>Tool calls ({snapshot.tool_calls.length})</summary><div className="feedList">{snapshot.tool_calls.slice().reverse().map((tool, i) =>
              <article className="feedCard" key={tool.id ?? i}><div className="feedMeta"><span>{tool.timestamp}</span><strong>{tool.name}</strong></div><pre>{tool.args}</pre></article>)}</div></details>
            <details className="reportExtra"><summary>Messages ({snapshot.messages.length})</summary><div className="feedList">{snapshot.messages.slice().reverse().map((message, i) =>
              <article className="feedCard" key={message.id ?? i}><div className="feedMeta"><span>{message.timestamp}</span><strong>{message.kind}</strong></div><pre>{message.content}</pre></article>)}</div></details>
            <p className="summaryLine subtle">Run {snapshot.run_id} · {snapshot.provider} · {snapshot.quick_model} / {snapshot.deep_model}</p>
          </details>}
        </section>
      </div>
    </main>
  );
}
