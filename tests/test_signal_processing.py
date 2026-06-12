import unittest
from unittest.mock import MagicMock

from marketmind_ai.agents.utils.rating import (
    ACTIONABLE,
    NO_RECOMMENDATION,
    RATINGS_5_TIER,
    parse_confidence,
    parse_decision_status,
    parse_rating,
)
from marketmind_ai.graph.signal_processing import SignalProcessor


class TestParseRating(unittest.TestCase):
    def test_explicit_label_buy(self):
        self.assertEqual(parse_rating("Rating: Buy\nReasoning here."), "Buy")

    def test_explicit_label_overweight(self):
        self.assertEqual(parse_rating("Rating: Overweight\nDetails."), "Overweight")

    def test_explicit_label_with_markdown_bold_value(self):
        self.assertEqual(parse_rating("Rating: **Sell**\nExit immediately."), "Sell")

    def test_explicit_label_with_markdown_bold_label(self):
        self.assertEqual(parse_rating("**Rating**: Underweight\nTrim exposure."), "Underweight")

    def test_recommendation_label_parses(self):
        self.assertEqual(parse_rating("**Recommendation**: Buy\nDetails."), "Buy")

    def test_rendered_pm_markdown_shape(self):
        text = (
            "**Decision Status**: Actionable\n\n"
            "**Rating**: Buy\n\n"
            "**Confidence**: 82/100\n\n"
            "**Executive Summary**: Enter at $189-192, 6% portfolio cap.\n\n"
            "**Investment Thesis**: AI capex cycle intact; institutional flows constructive."
        )
        self.assertEqual(parse_rating(text), "Buy")
        self.assertEqual(parse_decision_status(text), ACTIONABLE)
        self.assertEqual(parse_confidence(text), 82)

    def test_explicit_label_wins_over_prose_with_markdown(self):
        text = (
            "The buy thesis is weakened by guidance.\n"
            "Rating: **Sell**\n"
            "Exit before earnings."
        )
        self.assertEqual(parse_rating(text), "Sell")

    def test_no_recommendation_status_overrides_rating(self):
        text = (
            "**Decision Status**: No Recommendation\n\n"
            "**Confidence**: 29/100\n\n"
            "**Evidence Gap**: Need clearer guidance."
        )
        self.assertEqual(parse_rating(text), NO_RECOMMENDATION)
        self.assertEqual(parse_decision_status(text), NO_RECOMMENDATION)
        self.assertEqual(parse_confidence(text), 29)

    def test_no_rating_returns_default(self):
        self.assertEqual(parse_rating("No clear directional signal at this time."), "Hold")

    def test_no_rating_custom_default(self):
        self.assertEqual(parse_rating("Plain prose.", default="Underweight"), "Underweight")

    def test_all_five_tiers_recognised(self):
        for rating in RATINGS_5_TIER:
            with self.subTest(rating=rating):
                self.assertEqual(parse_rating(f"Rating: {rating}"), rating)


class TestSignalProcessor(unittest.TestCase):
    def test_returns_rating_from_pm_markdown(self):
        sp = SignalProcessor()
        md = (
            "**Decision Status**: Actionable\n\n"
            "**Rating**: Overweight\n\n"
            "**Executive Summary**: Build gradually."
        )
        self.assertEqual(sp.process_signal(md), "Overweight")

    def test_returns_no_recommendation_when_explicit(self):
        sp = SignalProcessor()
        md = "**Decision Status**: No Recommendation\n\n**Evidence Gap**: Need earnings confirmation."
        self.assertEqual(sp.process_signal(md), NO_RECOMMENDATION)

    def test_verification_fail_forces_no_recommendation(self):
        sp = SignalProcessor()
        md = (
            "**Decision Status**: Actionable\n\n"
            "**Rating**: Buy\n\n"
            "**Confidence**: 81/100"
        )
        verification = {
            "status": "fail",
            "blocks_actionable_recommendation": True,
        }
        self.assertEqual(sp.process_signal(md, verification=verification), NO_RECOMMENDATION)

    def test_makes_no_llm_calls(self):
        llm = MagicMock()
        sp = SignalProcessor(llm)
        sp.process_signal("Rating: Buy\nDetails.")
        llm.invoke.assert_not_called()
        llm.with_structured_output.assert_not_called()

    def test_default_when_no_rating_present(self):
        sp = SignalProcessor()
        self.assertEqual(sp.process_signal("Plain prose without a recommendation."), "Hold")


if __name__ == "__main__":
    unittest.main()
