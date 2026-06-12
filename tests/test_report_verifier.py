import unittest

from marketmind_ai.verification import ReportVerifier


VALID_DECISION = """**Decision Status**: Actionable

**Rating**: Buy

**Confidence**: 74/100

**Confidence Rationale**: Multiple desks aligned while residual volatility remains manageable.

**Executive Summary**: Add exposure on confirmation.

**Investment Thesis**: Evidence across tape, catalysts, and business quality supports a constructive bias.

**Primary Evidence Pack**:
1. [High][Fact] Claim: Momentum remains constructive. | Source: Market Analyst | Date: 2026-06-12 | Excerpt: RSI stabilized above 50. | Interpretation: Trend support remains intact.
2. [Medium][Judgment] Claim: Catalyst tone improved. | Source: News Analyst | Date: 2026-06-11 | Excerpt: A major customer reaffirmed demand. | Interpretation: Follow-through risk improved.

**Key Risks**:
- Valuation is still demanding.

**Evidence Gap**: The next earnings update could still challenge the current demand narrative."""


class ReportVerifierTests(unittest.TestCase):
    def test_future_dated_evidence_is_rejected(self):
        verifier = ReportVerifier()
        result = verifier.verify(
            final_state={
                "final_trade_decision": VALID_DECISION.replace("2026-06-12", "2026-06-20", 1),
                "investment_plan": "**Recommendation Status**: Actionable",
                "trader_investment_plan": "**Action Status**: Actionable",
                "trade_date": "2026-06-12",
                "company_of_interest": "NVDA",
            },
            resolved_ticker={"resolved_symbol": "NVDA"},
        )
        self.assertTrue(result.blocks_actionable_recommendation)

    def test_no_recommendation_with_rating_is_rejected(self):
        verifier = ReportVerifier()
        result = verifier.verify(
            final_state={
                "final_trade_decision": VALID_DECISION.replace("**Decision Status**: Actionable", "**Decision Status**: No Recommendation", 1),
                "investment_plan": "**Recommendation Status**: No Recommendation",
                "trader_investment_plan": "**Action Status**: No Recommendation",
                "trade_date": "2026-06-12",
                "company_of_interest": "NVDA",
            },
            resolved_ticker={"resolved_symbol": "NVDA"},
        )
        self.assertTrue(result.blocks_actionable_recommendation)


if __name__ == "__main__":
    unittest.main()
