from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class DecisionStatus(str, Enum):
    ACTIONABLE = "Actionable"
    NO_RECOMMENDATION = "No Recommendation"


class EvidenceStrength(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class EvidenceKind(str, Enum):
    FACT = "Fact"
    JUDGMENT = "Judgment"


class EvidenceItem(BaseModel):
    claim: str = Field(description="What this evidence supports.")
    evidence_type: EvidenceKind = Field(description="Whether the item is a Fact or a Judgment.")
    source: str = Field(description="Origin of the evidence.")
    source_date: str = Field(description="Date or period tied to the source.")
    excerpt: str = Field(description="A short cited excerpt or metric.")
    interpretation: str = Field(description="Why the excerpt matters.")
    strength: EvidenceStrength = Field(description="How strongly the item supports the claim.")

    @model_validator(mode="after")
    def validate_non_empty_fields(self) -> "EvidenceItem":
        for field_name in ("claim", "source", "source_date", "excerpt", "interpretation"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        return self


class ResearchPlan(BaseModel):
    recommendation_status: DecisionStatus
    recommendation: Optional[PortfolioRating] = None
    confidence: int = Field(ge=0, le=100)
    confidence_rationale: str
    rationale: str
    primary_evidence: list[EvidenceItem] = Field(min_length=1, max_length=5)
    key_risks: list[str] = Field(min_length=1, max_length=4)
    evidence_gap: str
    strategic_actions: str

    @model_validator(mode="after")
    def validate_status_fields(self) -> "ResearchPlan":
        if not self.confidence_rationale.strip():
            raise ValueError("confidence_rationale is required")
        if not self.evidence_gap.strip():
            raise ValueError("evidence_gap is required")
        if self.recommendation_status == DecisionStatus.ACTIONABLE:
            if self.recommendation is None:
                raise ValueError("recommendation is required for Actionable status")
            if len(self.primary_evidence) < 2:
                raise ValueError("actionable research plans require at least two evidence items")
            if not any(item.evidence_type == EvidenceKind.FACT for item in self.primary_evidence):
                raise ValueError("actionable research plans require at least one fact-based evidence item")
            if self.recommendation != PortfolioRating.HOLD and self.confidence < 50:
                raise ValueError("directional actionable research plans require confidence of at least 50")
        else:
            if self.recommendation is not None:
                raise ValueError("recommendation must be null when recommendation_status is No Recommendation")
        return self


class TraderProposal(BaseModel):
    action_status: DecisionStatus
    action: Optional[TraderAction] = None
    confidence: int = Field(ge=0, le=100)
    confidence_rationale: str
    reasoning: str
    primary_evidence: list[EvidenceItem] = Field(min_length=1, max_length=5)
    risk_controls: list[str] = Field(min_length=1, max_length=4)
    evidence_gap: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    position_sizing: Optional[str] = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "TraderProposal":
        if not self.confidence_rationale.strip():
            raise ValueError("confidence_rationale is required")
        if not self.evidence_gap.strip():
            raise ValueError("evidence_gap is required")
        if self.action_status == DecisionStatus.ACTIONABLE:
            if self.action is None:
                raise ValueError("action is required for Actionable status")
            if len(self.primary_evidence) < 2:
                raise ValueError("actionable trader proposals require at least two evidence items")
            if not any(item.evidence_type == EvidenceKind.FACT for item in self.primary_evidence):
                raise ValueError("actionable trader proposals require at least one fact-based evidence item")
            if self.action != TraderAction.HOLD and self.confidence < 50:
                raise ValueError("directional actionable trader proposals require confidence of at least 50")
        else:
            if self.action is not None:
                raise ValueError("action must be null when action_status is No Recommendation")
            if any(value is not None for value in (self.entry_price, self.stop_loss, self.position_sizing)):
                raise ValueError("pricing and sizing fields must be null when action_status is No Recommendation")
        return self


class PortfolioDecision(BaseModel):
    decision_status: DecisionStatus
    rating: Optional[PortfolioRating] = None
    confidence: int = Field(ge=0, le=100)
    confidence_rationale: str
    executive_summary: str
    investment_thesis: str
    primary_evidence: list[EvidenceItem] = Field(min_length=1, max_length=5)
    key_risks: list[str] = Field(min_length=1, max_length=4)
    evidence_gap: str
    price_target: Optional[float] = None
    time_horizon: Optional[str] = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "PortfolioDecision":
        if not self.confidence_rationale.strip():
            raise ValueError("confidence_rationale is required")
        if not self.evidence_gap.strip():
            raise ValueError("evidence_gap is required")
        if self.decision_status == DecisionStatus.ACTIONABLE:
            if self.rating is None:
                raise ValueError("rating is required for Actionable status")
            if len(self.primary_evidence) < 2:
                raise ValueError("actionable portfolio decisions require at least two evidence items")
            if not any(item.evidence_type == EvidenceKind.FACT for item in self.primary_evidence):
                raise ValueError("actionable portfolio decisions require at least one fact-based evidence item")
            if self.rating != PortfolioRating.HOLD and self.confidence < 50:
                raise ValueError("directional actionable portfolio decisions require confidence of at least 50")
        else:
            if self.rating is not None:
                raise ValueError("rating must be null when decision_status is No Recommendation")
            if self.price_target is not None or self.time_horizon is not None:
                raise ValueError("price_target and time_horizon must be null when decision_status is No Recommendation")
        return self


def render_research_plan(plan: ResearchPlan) -> str:
    parts = [f"**Recommendation Status**: {plan.recommendation_status.value}", ""]
    if plan.recommendation is not None:
        parts.extend([f"**Recommendation**: {plan.recommendation.value}", ""])
    parts.extend(
        [
            f"**Confidence**: {plan.confidence}/100",
            "",
            f"**Confidence Rationale**: {plan.confidence_rationale}",
            "",
            f"**Rationale**: {plan.rationale}",
            "",
            "**Primary Evidence Pack**:",
        ]
    )
    parts.extend(_render_evidence_list(plan.primary_evidence))
    parts.extend(["", "**Key Risks**:"])
    parts.extend(f"- {risk}" for risk in plan.key_risks)
    parts.extend(["", f"**Evidence Gap**: {plan.evidence_gap}"])
    parts.extend(["", f"**Strategic Actions**: {plan.strategic_actions}"])
    return "\n".join(parts)


def render_trader_proposal(proposal: TraderProposal) -> str:
    parts = [f"**Action Status**: {proposal.action_status.value}", ""]
    if proposal.action is not None:
        parts.extend([f"**Action**: {proposal.action.value}", ""])
    parts.extend(
        [
            f"**Confidence**: {proposal.confidence}/100",
            "",
            f"**Confidence Rationale**: {proposal.confidence_rationale}",
            "",
            f"**Reasoning**: {proposal.reasoning}",
            "",
            "**Primary Evidence Pack**:",
        ]
    )
    parts.extend(_render_evidence_list(proposal.primary_evidence))
    parts.extend(["", "**Risk Controls**:"])
    parts.extend(f"- {risk}" for risk in proposal.risk_controls)
    parts.extend(["", f"**Evidence Gap**: {proposal.evidence_gap}"])
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    tail = proposal.action.value.upper() if proposal.action is not None else DecisionStatus.NO_RECOMMENDATION.value.upper()
    parts.extend(["", f"FINAL TRANSACTION PROPOSAL: **{tail}**"])
    return "\n".join(parts)


def render_portfolio_decision(decision: PortfolioDecision) -> str:
    parts = [f"**Decision Status**: {decision.decision_status.value}", ""]
    if decision.rating is not None:
        parts.extend([f"**Rating**: {decision.rating.value}", ""])
    parts.extend(
        [
            f"**Confidence**: {decision.confidence}/100",
            "",
            f"**Confidence Rationale**: {decision.confidence_rationale}",
            "",
            f"**Executive Summary**: {decision.executive_summary}",
            "",
            f"**Investment Thesis**: {decision.investment_thesis}",
            "",
            "**Primary Evidence Pack**:",
        ]
    )
    parts.extend(_render_evidence_list(decision.primary_evidence))
    parts.extend(["", "**Key Risks**:"])
    parts.extend(f"- {risk}" for risk in decision.key_risks)
    parts.extend(["", f"**Evidence Gap**: {decision.evidence_gap}"])
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


def _render_evidence_list(items: list[EvidenceItem]) -> list[str]:
    rendered = []
    for index, item in enumerate(items, start=1):
        rendered.append(
            f"{index}. [{item.strength.value}][{item.evidence_type.value}] Claim: {item.claim} | "
            f"Source: {item.source} | Date: {item.source_date} | Excerpt: {item.excerpt} | "
            f"Interpretation: {item.interpretation}"
        )
    return rendered
