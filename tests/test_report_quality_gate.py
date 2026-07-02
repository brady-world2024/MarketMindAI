from marketmind_ai.agents.schemas import (
    DecisionStatus,
    EvidenceItem,
    EvidenceKind,
    EvidenceStrength,
    PortfolioDecision,
    PortfolioRating,
)
from marketmind_ai.graph.runtime_support import GraphResearchEngine
from marketmind_ai.verification import DecisionVerifier


def _stale_evidence(source: str) -> EvidenceItem:
    return EvidenceItem(
        claim=f"{source} supports the thesis, but the evidence is stale.",
        evidence_type=EvidenceKind.FACT,
        source=source,
        source_date="2025-01-01",
        excerpt="Old metric still looked constructive.",
        interpretation="The item is too old to carry an actionable call.",
        strength=EvidenceStrength.MEDIUM,
    )


def test_quality_gate_downgrades_actionable_decisions_with_stale_evidence():
    engine = GraphResearchEngine.__new__(GraphResearchEngine)
    engine.verifier = DecisionVerifier()
    engine.resolution = {"resolved_symbol": "NVDA"}
    state = {
        "investment_plan": "**Recommendation Status**: Actionable",
        "trader_investment_plan": "**Action Status**: Actionable\n\nStop if the breakout fails.",
        "trade_date": "2026-06-12",
    }
    decision = PortfolioDecision(
        decision_status=DecisionStatus.ACTIONABLE,
        rating=PortfolioRating.OVERWEIGHT,
        confidence=72,
        confidence_rationale="The stale evidence still appears aligned.",
        executive_summary="Scale in on confirmation.",
        investment_thesis="The setup is constructive.",
        primary_evidence=[_stale_evidence("Market Analyst"), _stale_evidence("News Analyst")],
        key_risks=["Valuation remains demanding."],
        evidence_gap="Fresh confirmation is still needed.",
        price_target=1179.46,
        time_horizon="1-4 weeks",
    )

    final_decision, payload = engine._verify_and_payload(state, decision)

    assert final_decision.decision_status == DecisionStatus.NO_RECOMMENDATION
    assert final_decision.rating is None
    assert final_decision.confidence <= 49
    assert final_decision.price_target is None
    assert final_decision.time_horizon is None
    assert "quality gate" in final_decision.evidence_gap
    assert "stale_evidence" in {issue["code"] for issue in payload["report_quality"]["issues"]}
