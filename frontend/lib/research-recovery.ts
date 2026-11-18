import type { RunSnapshot } from "./api-types";

export const DATA_REQUIREMENTS: Record<string, string> = {
  instrument: "Security eligibility",
  price_history: "Daily price history",
  income_statement: "Income statement",
  balance_sheet: "Balance sheet",
  cashflow: "Cash flow statement",
  news: "Company news",
  global_news: "Market news",
  fundamentals: "Company overview",
};

export function isNoRecommendation(snapshot: RunSnapshot) {
  return snapshot.final_structured_decision?.decision_status === "No Recommendation"
    || /no.recommendation/i.test(snapshot.final_signal ?? "");
}

export function canRefreshSavedResearch(snapshot: RunSnapshot) {
  const date = snapshot.research_cutoff?.requested_date ?? snapshot.analysis_date;
  return ["completed", "error"].includes(snapshot.status) && ["demo", "live"].includes(snapshot.data_mode ?? "")
    && !!snapshot.ticker?.trim() && typeof date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(date);
}

export function recoveryMessage(snapshot: RunSnapshot) {
  if (snapshot.data_availability?.can_recommend === false) {
    return "Required research data was unavailable or unverified. Review the recorded source failures before fetching data again.";
  }
  if (snapshot.report_verification?.blocks_actionable_recommendation) {
    return "Recorded validation prevents an actionable recommendation. Review the claim checks and evidence gap before rerunning.";
  }
  return "The saved report contains no recommendation. Review its evidence gap and risks before starting another analysis.";
}
