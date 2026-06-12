import unittest

from marketmind_ai.graph.decision import EvidenceItem, FinalDecision
from marketmind_ai.verification import DecisionVerifier


class DecisionVerifierTests(unittest.TestCase):
    def test_directional_decision_requires_multiple_evidence_items(self):
        verifier = DecisionVerifier()
        decision = FinalDecision(
            ticker="NVDA",
            action="BUY",
            confidence=62.0,
            thesis="Constructive setup",
            time_horizon="1-4 weeks",
            entry_plan="Buy strength",
            risk_controls="No stop yet",
            evidence_gap="the thesis still needs monitoring",
            evidence_items=[
                EvidenceItem(
                    kind="market",
                    strength="high",
                    claim="trend is positive",
                    source="test",
                    source_date="2026-06-12",
                    detail="details",
                )
            ],
            rationale="test",
        )
        result = verifier.verify(
            ticker="NVDA",
            decision=decision,
            provisional_action="BUY",
            trader_plan="Action: BUY, risk controls still TBD",
        )
        self.assertTrue(result.blocks_actionable_recommendation)
        self.assertEqual(result.status, "failed")
        self.assertGreaterEqual(len(result.issues), 2)


if __name__ == "__main__":
    unittest.main()
