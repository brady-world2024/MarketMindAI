import type { ReviewSummary, RunSnapshot } from "./api-types";

export const RESEARCH_PHASES = ["Prepare run", "Collect evidence", "Build analysis", "Check risks", "Human review"];

export function researchPhase(snapshot: Partial<RunSnapshot> | null) {
  let index = 0;
  const agent = snapshot?.current_agent ?? "";
  if (/Market Analyst|Social Analyst|Sentiment Analyst|News Analyst|Fundamentals Analyst/.test(agent)) index = 1;
  if (/Bull Researcher|Bear Researcher|Research Manager|Trader/.test(agent)) index = 2;
  if (/Aggressive|Conservative|Neutral|Portfolio Manager/.test(agent)) index = 3;
  if (snapshot?.status === "completed") index = 4;
  let label = snapshot ? RESEARCH_PHASES[index] : "Ready to research";
  if (snapshot?.status === "error") label = "Analysis failed";
  if (snapshot?.status === "completed") label = ({ pending: "Awaiting review", approved: "Approved",
    rejected: "Rejected", changes_requested: "Changes requested" })[snapshot.review?.status ?? "pending"];
  return { index, label, failed: snapshot?.status === "error" };
}

export function elapsedTime(snapshot: RunSnapshot | null, now: number): string {
  if (!snapshot?.started_at) return "—";
  const start = Date.parse(snapshot.started_at);
  const finish = snapshot.finished_at ? Date.parse(snapshot.finished_at) : now;
  if (!Number.isFinite(start) || !Number.isFinite(finish)) return "—";
  const seconds = Math.max(0, Math.floor((finish - start) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function filterReviews(items: ReviewSummary[], status: string, query: string): ReviewSummary[] {
  const search = query.trim().toLowerCase();
  return items.filter((item) => (status === "all" || item.review.status === status)
    && (!search || `${item.ticker} ${item.analysis_date} ${item.run_id} v${item.review.version}`.toLowerCase().includes(search)));
}
