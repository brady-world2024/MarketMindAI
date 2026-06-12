import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from marketmind_ai.agents.managers.research_manager import create_research_manager
from marketmind_ai.agents.schemas import (
    DecisionStatus,
    EvidenceItem,
    EvidenceKind,
    EvidenceStrength,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    render_research_plan,
    render_trader_proposal,
)
from marketmind_ai.agents.trader.trader import create_trader


def _evidence_item(
    source: str,
    claim: str = "Demand remains strong.",
    kind: EvidenceKind = EvidenceKind.FACT,
    source_date: str = "2026-05-01",
) -> EvidenceItem:
    return EvidenceItem(
        claim=claim,
        evidence_type=kind,
        source=source,
        source_date=source_date,
        excerpt="Revenue growth and guidance both improved.",
        interpretation="Supports continued upside in the current setup.",
        strength=EvidenceStrength.HIGH,
    )


class DummyOfflineRuntime:
    def __init__(self, offline: bool = False):
        self.models = SimpleNamespace(offline=offline)

    def offline_research_plan(self, _selected_analysts):
        return ResearchPlan(
            recommendation_status=DecisionStatus.ACTIONABLE,
            recommendation=PortfolioRating.HOLD,
            confidence=55,
            confidence_rationale="Baseline offline fallback confidence.",
            rationale="Balanced setup.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
            key_risks=["Need another catalyst."],
            evidence_gap="Need a cleaner catalyst path.",
            strategic_actions="Stay patient.",
        )

    def offline_trader_proposal(self, _research_plan):
        return TraderProposal(
            action_status=DecisionStatus.ACTIONABLE,
            action=TraderAction.HOLD,
            confidence=55,
            confidence_rationale="Baseline offline fallback confidence.",
            reasoning="Balanced setup.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
            risk_controls=["Keep sizing small until confirmation."],
            evidence_gap="Need stronger confirmation.",
        )


def _make_trader_state():
    return {
        "company_of_interest": "NVDA",
        "selected_analysts": ["market", "news"],
        "investment_plan": (
            "**Recommendation**: Buy\n\n"
            "**Confidence Rationale**: Multiple fresh facts align.\n\n"
            "**Strategic Actions**: Build gradually."
        ),
        "trader_memory_context": "",
        "output_language": "English",
    }


def _structured_trader_llm(captured: dict, proposal: TraderProposal | None = None):
    if proposal is None:
        proposal = TraderProposal(
            action_status=DecisionStatus.ACTIONABLE,
            action=TraderAction.BUY,
            confidence=74,
            confidence_rationale="The setup is confirmed by multiple fresh evidence items.",
            reasoning="Strong setup.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("Fundamentals Analyst")],
            risk_controls=["Size normally only if volume confirms."],
            evidence_gap="Residual uncertainty remains around macro volatility.",
        )
    structured = MagicMock()
    def _invoke(prompt):
        captured["prompt"] = prompt
        return proposal

    structured.invoke.side_effect = _invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "selected_analysts": ["market", "news", "fundamentals"],
        "research_memory_context": "",
        "output_language": "English",
        "investment_debate_state": {
            "history": "Bull and bear arguments here.",
            "bull_history": "Bull says...",
            "bear_history": "Bear says...",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }


def _structured_rm_llm(captured: dict, plan: ResearchPlan | None = None):
    if plan is None:
        plan = ResearchPlan(
            recommendation_status=DecisionStatus.ACTIONABLE,
            recommendation=PortfolioRating.HOLD,
            confidence=52,
            confidence_rationale="The arguments are balanced and the evidence is mixed.",
            rationale="Balanced view across both sides.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
            key_risks=["The next catalyst may break the tie."],
            evidence_gap="Residual uncertainty remains because the next catalyst could break the balance.",
            strategic_actions="Hold current position; reassess after earnings.",
        )
    structured = MagicMock()
    def _invoke(prompt):
        captured["prompt"] = prompt
        return plan

    structured.invoke.side_effect = _invoke
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


class TestRenderTraderProposal(unittest.TestCase):
    def test_minimal_required_fields(self):
        proposal = TraderProposal(
            action_status=DecisionStatus.ACTIONABLE,
            action=TraderAction.HOLD,
            confidence=55,
            confidence_rationale="The evidence is real, but the setup lacks a clean edge.",
            reasoning="Balanced setup; no edge.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
            risk_controls=["Keep sizing small until a catalyst appears."],
            evidence_gap="Need stronger confirmation from price action and a cleaner catalyst path.",
        )
        md = render_trader_proposal(proposal)
        self.assertIn("**Action Status**: Actionable", md)
        self.assertIn("**Action**: Hold", md)
        self.assertIn("**Confidence**: 55/100", md)
        self.assertIn("Source: Market Analyst", md)
        self.assertIn("Date: 2026-05-01", md)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **HOLD**", md)

    def test_optional_fields_included_when_present(self):
        proposal = TraderProposal(
            action_status=DecisionStatus.ACTIONABLE,
            action=TraderAction.BUY,
            confidence=78,
            confidence_rationale="Multiple fresh facts align across technicals and fundamentals.",
            reasoning="Strong technicals + fundamentals.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("Fundamentals Analyst")],
            risk_controls=["Stop if the breakout fails."],
            evidence_gap="Residual uncertainty remains around near-term macro volatility.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
        )
        md = render_trader_proposal(proposal)
        self.assertIn("**Entry Price**: 189.5", md)
        self.assertIn("**Stop Loss**: 178.0", md)
        self.assertIn("**Position Sizing**: 6% of portfolio", md)

    def test_no_recommendation_renders_without_action(self):
        proposal = TraderProposal(
            action_status=DecisionStatus.NO_RECOMMENDATION,
            action=None,
            confidence=31,
            confidence_rationale="Only one weak confirmation exists and the setup is still conflicted.",
            reasoning="The setup is conflicted and lacks confirmation.",
            primary_evidence=[_evidence_item("Market Analyst", claim="Momentum is mixed.")],
            risk_controls=["Wait for earnings and a clean breakout."],
            evidence_gap="Need clearer confirmation from earnings and volume.",
        )
        md = render_trader_proposal(proposal)
        self.assertIn("**Action Status**: No Recommendation", md)
        self.assertNotIn("**Action**:", md)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **NO RECOMMENDATION**", md)

    def test_directional_actionable_trade_requires_minimum_confidence(self):
        with self.assertRaises(ValueError):
            TraderProposal(
                action_status=DecisionStatus.ACTIONABLE,
                action=TraderAction.BUY,
                confidence=42,
                confidence_rationale="The trade is speculative and lightly supported.",
                reasoning="A weak breakout could still work.",
                primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
                risk_controls=["Use a stop."],
                evidence_gap="Need stronger confirmation from volume and earnings.",
            )


class TestRenderResearchPlan(unittest.TestCase):
    def test_required_fields(self):
        plan = ResearchPlan(
            recommendation_status=DecisionStatus.ACTIONABLE,
            recommendation=PortfolioRating.OVERWEIGHT,
            confidence=72,
            confidence_rationale="Fresh evidence from both market and fundamentals supports a constructive stance.",
            rationale="Bull case carried; tailwinds intact.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("Fundamentals Analyst")],
            key_risks=["Valuation remains demanding."],
            evidence_gap="Residual uncertainty remains around valuation sensitivity if growth slows.",
            strategic_actions="Build position over two weeks; cap at 5%.",
        )
        md = render_research_plan(plan)
        self.assertIn("**Recommendation Status**: Actionable", md)
        self.assertIn("**Recommendation**: Overweight", md)
        self.assertIn("Source: Fundamentals Analyst", md)
        self.assertIn("Excerpt: Revenue growth and guidance both improved.", md)

    def test_all_5_tier_ratings_render(self):
        for rating in PortfolioRating:
            plan = ResearchPlan(
                recommendation_status=DecisionStatus.ACTIONABLE,
                recommendation=rating,
                confidence=60 if rating == PortfolioRating.HOLD else 61,
                confidence_rationale="The evidence is sufficient for the selected rating.",
                rationale="r",
                primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("News Analyst")],
                key_risks=["risk"],
                evidence_gap="Residual uncertainty remains limited but worth monitoring.",
                strategic_actions="s",
            )
            md = render_research_plan(plan)
            self.assertIn(f"**Recommendation**: {rating.value}", md)

    def test_no_recommendation_requires_gap(self):
        plan = ResearchPlan(
            recommendation_status=DecisionStatus.NO_RECOMMENDATION,
            recommendation=None,
            confidence=28,
            confidence_rationale="The analyst signals conflict and the missing facts are material.",
            rationale="Conflicting evidence across analysts.",
            primary_evidence=[_evidence_item("News Analyst", claim="The catalyst is unresolved.")],
            key_risks=["The next earnings print could change the thesis."],
            evidence_gap="Need a clearer read on guidance and post-earnings price action.",
            strategic_actions="Wait for fresh guidance before acting.",
        )
        md = render_research_plan(plan)
        self.assertIn("**Recommendation Status**: No Recommendation", md)
        self.assertNotIn("**Recommendation**:", md)
        self.assertIn("**Evidence Gap**: Need a clearer read", md)

    def test_actionable_plan_requires_fact_evidence(self):
        with self.assertRaises(ValueError):
            ResearchPlan(
                recommendation_status=DecisionStatus.ACTIONABLE,
                recommendation=PortfolioRating.BUY,
                confidence=70,
                confidence_rationale="The confidence is high but the support is only interpretive.",
                rationale="Bull case looks strong.",
                primary_evidence=[
                    _evidence_item("Market Analyst", kind=EvidenceKind.JUDGMENT),
                    _evidence_item("News Analyst", kind=EvidenceKind.JUDGMENT),
                ],
                key_risks=["The underlying facts are not pinned down clearly enough."],
                evidence_gap="Need direct factual confirmation from filings or price confirmation.",
                strategic_actions="Wait for direct factual confirmation.",
            )


class TestTraderAgent(unittest.TestCase):
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        proposal = TraderProposal(
            action_status=DecisionStatus.ACTIONABLE,
            action=TraderAction.BUY,
            confidence=82,
            confidence_rationale="Technical and fundamental evidence align cleanly and are recent.",
            reasoning="AI capex cycle intact; institutional flows constructive.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("Fundamentals Analyst")],
            risk_controls=["Cut if the breakout fails on heavy volume."],
            evidence_gap="Residual uncertainty remains around macro headlines disrupting the breakout.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
        )
        llm = _structured_trader_llm(captured, proposal)
        trader = create_trader(llm, DummyOfflineRuntime())
        result = trader(_make_trader_state())
        plan = result["trader_investment_plan"]
        self.assertIn("**Action**: Buy", plan)
        self.assertIn("**Entry Price**: 189.5", plan)
        self.assertIn("FINAL TRANSACTION PROPOSAL: **BUY**", plan)
        self.assertIn(plan, result["messages"][0].content)

    def test_prompt_includes_investment_plan(self):
        captured = {}
        llm = _structured_trader_llm(captured)
        trader = create_trader(llm, DummyOfflineRuntime())
        trader(_make_trader_state())
        prompt = captured["prompt"]
        contents = [content for _, content in prompt]
        self.assertTrue(any("Proposed Investment Plan" in content for content in contents))
        self.assertTrue(any("Confidence Rationale" in content for content in contents))
        self.assertTrue(any("source date or period" in content for content in contents))

    def test_prompt_includes_memory_context_when_available(self):
        captured = {}
        llm = _structured_trader_llm(captured)
        trader = create_trader(llm, DummyOfflineRuntime())
        state = _make_trader_state()
        state["trader_memory_context"] = (
            "Historical retrieval for Trader on NVDA\n"
            "A prior breakout failed on weak volume."
        )
        trader(state)
        prompt = captured["prompt"]
        contents = [content for _, content in prompt]
        self.assertTrue(any("Historical retrieval for Trader on NVDA" in content for content in contents))

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = (
            "**Action**: Sell\n\nGuidance cut hits margins.\n\n"
            "FINAL TRANSACTION PROPOSAL: **SELL**"
        )
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        trader = create_trader(llm, DummyOfflineRuntime())
        result = trader(_make_trader_state())
        self.assertEqual(result["trader_investment_plan"], plain_response)


class TestResearchManagerAgent(unittest.TestCase):
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        plan = ResearchPlan(
            recommendation_status=DecisionStatus.ACTIONABLE,
            recommendation=PortfolioRating.OVERWEIGHT,
            confidence=75,
            confidence_rationale="Multiple recent facts line up in favor of the bull case.",
            rationale="Bull case is stronger; AI tailwind intact.",
            primary_evidence=[_evidence_item("Market Analyst"), _evidence_item("Fundamentals Analyst")],
            key_risks=["Multiple expansion could reverse quickly."],
            evidence_gap="Residual uncertainty remains around valuation if sentiment cools.",
            strategic_actions="Build position gradually over two weeks.",
        )
        llm = _structured_rm_llm(captured, plan)
        rm = create_research_manager(llm, DummyOfflineRuntime())
        result = rm(_make_rm_state())
        ip = result["investment_plan"]
        self.assertIn("**Recommendation**: Overweight", ip)
        self.assertIn("**Rationale**: Bull case", ip)
        self.assertIn("**Strategic Actions**: Build position", ip)

    def test_prompt_uses_5_tier_rating_scale(self):
        captured = {}
        llm = _structured_rm_llm(captured)
        rm = create_research_manager(llm, DummyOfflineRuntime())
        rm(_make_rm_state())
        prompt = captured["prompt"]
        for tier in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            self.assertIn(f"**{tier}**", prompt)
        self.assertIn("No Recommendation", prompt)
        self.assertIn("Confidence Rationale", prompt)
        self.assertIn("short excerpt", prompt)

    def test_prompt_includes_memory_context_when_available(self):
        captured = {}
        llm = _structured_rm_llm(captured)
        rm = create_research_manager(llm, DummyOfflineRuntime())
        state = _make_rm_state()
        state["research_memory_context"] = (
            "Historical retrieval for Research Manager on NVDA\n"
            "Prior guidance beats mattered more than macro noise."
        )
        rm(state)
        self.assertIn("Historical retrieval for Research Manager on NVDA", captured["prompt"])

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = "**Recommendation**: Sell\n\n**Rationale**: ...\n\n**Strategic Actions**: ..."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        rm = create_research_manager(llm, DummyOfflineRuntime())
        result = rm(_make_rm_state())
        self.assertEqual(result["investment_plan"], plain_response)


if __name__ == "__main__":
    unittest.main()
