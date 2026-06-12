import tempfile
import unittest
from pathlib import Path

from marketmind_ai.evaluation import OutcomeEvaluator
from marketmind_ai.agents.utils.memory import MarketMindMemoryLog


DECISION_BUY = """**Decision Status**: Actionable

**Rating**: Buy

**Confidence**: 82/100

**Executive Summary**: Enter on strength.

**Investment Thesis**: Evidence is aligned.

**Evidence Gap**: Need confirmation."""

DECISION_NO_REC = """**Decision Status**: No Recommendation

**Confidence**: 31/100

**Executive Summary**: Wait for confirmation.

**Evidence Gap**: Need clearer guidance."""


class OutcomeEvaluatorTests(unittest.TestCase):
    def make_log(self, root: Path) -> MarketMindMemoryLog:
        return MarketMindMemoryLog({"memory_log_path": str(root / "memory.md")})

    def test_summary_tracks_actionable_vs_no_recommendation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log = self.make_log(root)
            log.store_decision("NVDA", "2026-01-05", DECISION_BUY)
            log.update_with_outcome("NVDA", "2026-01-05", 0.05, 0.03, 5, "Correct.")
            log.store_decision("AAPL", "2026-01-07", DECISION_NO_REC)
            log.update_with_outcome("AAPL", "2026-01-07", 0.02, 0.01, 5, "Correct to wait.")
            evaluator = OutcomeEvaluator({"evaluation_summary_path": str(root / "summary.json")}, log)
            summary = evaluator.build_summary()
            self.assertEqual(summary["resolved_entries"], 2)
            self.assertEqual(summary["actionable_entries"], 1)
            self.assertEqual(summary["no_recommendation_entries"], 1)


if __name__ == "__main__":
    unittest.main()
