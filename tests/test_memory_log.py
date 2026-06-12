import tempfile
import unittest
from pathlib import Path

from marketmind_ai.agents.utils.memory import MarketMindMemoryLog


DECISION_BUY = """**Decision Status**: Actionable

**Rating**: Buy

**Confidence**: 82/100

**Executive Summary**: Enter on strength.

**Investment Thesis**: Evidence is aligned.

**Evidence Gap**: Need confirmation from the next catalyst."""


class MarketMindMemoryLogTests(unittest.TestCase):
    def make_log(self, root: Path) -> MarketMindMemoryLog:
        return MarketMindMemoryLog({"memory_log_path": str(root / "memory.md")})

    def test_store_is_idempotent_for_same_ticker_and_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = self.make_log(Path(temp_dir))
            log.store_decision("NVDA", "2026-01-05", DECISION_BUY)
            log.store_decision("NVDA", "2026-01-05", DECISION_BUY)
            self.assertEqual(len(log.load_entries()), 1)
            self.assertTrue(log.load_entries()[0]["pending"])

    def test_update_with_outcome_resolves_entry_and_adds_reflection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log = self.make_log(Path(temp_dir))
            log.store_decision("NVDA", "2026-01-05", DECISION_BUY)
            log.update_with_outcome("NVDA", "2026-01-05", 0.05, 0.03, 5, "Catalyst followed through.")
            entries = log.load_entries()
            self.assertEqual(len(entries), 1)
            self.assertFalse(entries[0]["pending"])
            self.assertEqual(entries[0]["raw"], "+5.0%")
            self.assertEqual(entries[0]["alpha"], "+3.0%")
            self.assertEqual(entries[0]["reflection"], "Catalyst followed through.")


if __name__ == "__main__":
    unittest.main()
