import type { RunSnapshot } from "./api-types";
import type { ProviderSettings } from "./provider-settings";

function savedResearchRequest(saved: RunSnapshot, settings: ProviderSettings) {
  if (!["demo", "live"].includes(saved.data_mode ?? "")) throw new Error("The saved source mode is unverified. Start a new research run from setup.");
  const date = saved.research_cutoff?.requested_date ?? saved.analysis_date;
  if (!saved.ticker?.trim() || typeof date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error("The saved company or requested date is unavailable. Start a new research run from setup.");
  }
  const demo = saved.data_mode === "demo";
  if (!demo && (!settings.provider || settings.provider === "offline")) {
    throw new Error("Choose a live AI provider for this saved live research.");
  }
  const quick = demo ? "heuristic-fast" : settings.quickModel === "custom" ? settings.quickCustom.trim() : settings.quickModel;
  const deep = demo ? "heuristic-deep" : settings.deepModel === "custom" ? settings.deepCustom.trim() : settings.deepModel;
  if (!quick || !deep) throw new Error("Complete the current model settings before starting research.");
  return {
    ticker: saved.ticker,
    analysis_date: date,
    llm_provider: demo ? "offline" : settings.provider,
    api_key: demo ? null : settings.apiKey.trim() || null,
    base_url: demo ? null : settings.baseUrl.trim() || null,
    quick_model: quick,
    deep_model: deep,
    analysts: saved.selected_analysts,
    output_language: saved.output_language,
    research_objective: saved.research_objective ?? null,
    research_horizon: saved.research_horizon ?? null,
    checkpoint_enabled: false,
  };
}

export function buildReplayRequest(saved: RunSnapshot, settings: ProviderSettings) {
  if (!saved.data_snapshot?.snapshot_id || !["demo", "live"].includes(saved.data_mode ?? "")) {
    throw new Error("Saved snapshot provenance is unverified; this report cannot replay saved data.");
  }
  if (saved.data_mode === "live" && (!settings.provider || settings.provider === "offline" || !settings.validationResult?.valid)) {
    throw new Error("Live saved-data replay requires a verified live AI connection. Connect a provider first.");
  }
  return { ...savedResearchRequest(saved, settings), snapshot_id: saved.data_snapshot.snapshot_id };
}

export function buildRefreshRequest(saved: RunSnapshot, settings: ProviderSettings) {
  return savedResearchRequest(saved, settings);
}
