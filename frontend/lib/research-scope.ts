export const RESEARCH_OBJECTIVES = {
  company_overview: "Company overview",
  earnings: "Earnings and financial results",
  risk_counterevidence: "Risks and counterevidence",
} as const;

export const RESEARCH_HORIZONS = {
  "1_to_4_weeks": "1–4 weeks",
  "1_to_3_months": "1–3 months",
  "6_to_12_months": "6–12 months",
} as const;

export type ResearchObjective = keyof typeof RESEARCH_OBJECTIVES;
export type ResearchHorizon = keyof typeof RESEARCH_HORIZONS;

export function researchScopeFacts({
  research_objective, research_horizon,
}: { research_objective?: ResearchObjective | null; research_horizon?: ResearchHorizon | null }) {
  const objective = research_objective && RESEARCH_OBJECTIVES[research_objective];
  const horizon = research_horizon && RESEARCH_HORIZONS[research_horizon];
  return [
    ...(objective ? [{ label: "Research objective", value: objective }] : []),
    ...(horizon ? [{ label: "Requested horizon", value: horizon }] : []),
  ];
}
