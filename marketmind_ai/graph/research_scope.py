"""Optional research presets and the instructions they add to analysis."""

from typing import Literal

ResearchObjective = Literal["company_overview", "earnings", "risk_counterevidence"]
ResearchHorizon = Literal["1_to_4_weeks", "1_to_3_months", "6_to_12_months"]

OBJECTIVE_LABELS: dict[ResearchObjective, str] = {
    "company_overview": "Company overview",
    "earnings": "Earnings and financial results",
    "risk_counterevidence": "Risks and counterevidence",
}
HORIZON_LABELS: dict[ResearchHorizon, str] = {
    "1_to_4_weeks": "1–4 weeks",
    "1_to_3_months": "1–3 months",
    "6_to_12_months": "6–12 months",
}

_OBJECTIVE_GUIDANCE: dict[ResearchObjective, str] = {
    "company_overview": "Synthesize the business, financial results, market context, and principal risks.",
    "earnings": "Prioritize reported earnings, revenue and margin changes, cash flow, and the evidence for their drivers.",
    "risk_counterevidence": "Prioritize downside risks and counterevidence. Identify what would invalidate the thesis.",
}


def scope_guidance(objective: ResearchObjective | None, horizon: ResearchHorizon | None) -> str:
    guidance = []
    if objective is not None:
        guidance.append(f"Research objective: {OBJECTIVE_LABELS[objective]}. {_OBJECTIVE_GUIDANCE[objective]}")
    if horizon is not None:
        guidance.append(
            f"Requested research horizon: {HORIZON_LABELS[horizon]} after the research cutoff. "
            "Evaluate the thesis, risks, and any substantiated catalysts on that horizon. "
            "Explain when the available evidence cannot support that time frame."
        )
    if not guidance:
        return ""
    guidance.append("Use only permitted evidence. The research scope does not relax decision or verification rules.")
    return "\n".join(guidance) + "\n\n"
