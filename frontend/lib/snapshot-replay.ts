import type { RunSnapshot } from "./api-types";
import type { ProviderSettings } from "./provider-settings";

export function buildReplayRequest(saved: RunSnapshot, settings: ProviderSettings) {
  if (!saved.data_snapshot?.snapshot_id || !["demo", "live"].includes(saved.data_mode ?? "")) {
    throw new Error("Saved snapshot provenance is unverified; this report cannot replay saved data.");
  }
  const demo = saved.data_mode === "demo";
  if (!demo && (!settings.provider || settings.provider === "offline" || !settings.validationResult?.valid)) {
    throw new Error("Live saved-data replay requires a verified live AI connection. Connect a provider first.");
  }
  return {
    snapshot_id: saved.data_snapshot.snapshot_id,
    ticker: saved.ticker,
    analysis_date: saved.research_cutoff?.requested_date ?? saved.analysis_date,
    llm_provider: demo ? "offline" : settings.provider,
    api_key: demo ? null : settings.apiKey.trim() || null,
    base_url: demo ? null : settings.baseUrl.trim() || null,
    quick_model: demo ? "heuristic-fast" : settings.quickModel === "custom" ? settings.quickCustom.trim() : settings.quickModel,
    deep_model: demo ? "heuristic-deep" : settings.deepModel === "custom" ? settings.deepCustom.trim() : settings.deepModel,
    analysts: saved.selected_analysts,
    output_language: saved.output_language,
    checkpoint_enabled: false,
  };
}
