import json
import tempfile
import unittest
from pathlib import Path

from marketmind_ai.agents.utils.memory import MarketMindMemoryLog
from marketmind_ai.agents.utils.memory_retrieval import MarketMindMemoryRetriever


class MemoryRetrievalTests(unittest.TestCase):
    def test_build_contexts_include_report_and_reflection_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log = MarketMindMemoryLog({"memory_log_path": str(root / "memory.md")})
            log.store_decision(
                "NVDA",
                "2026-01-05",
                "**Decision Status**: Actionable\n\n**Rating**: Buy\n\n**Confidence**: 75/100\n\n**Evidence Gap**: Need follow-through.",
            )
            log.update_with_outcome("NVDA", "2026-01-05", 0.05, 0.02, 5, "The catalyst held and margins mattered.")
            report_dir = root / "results" / "NVDA" / "MarketMindStrategy_logs"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "full_states_log_2026-01-05.json").write_text(
                json.dumps(
                    {
                        "trade_date": "2026-01-05",
                        "fundamentals_report": "Gross margin expanded materially after the product cycle improved.",
                        "news_report": "A hyperscaler contract supported revenue visibility.",
                        "final_trade_decision": "**Decision Status**: Actionable\n\n**Rating**: Buy",
                    }
                ),
                encoding="utf-8",
            )
            retriever = MarketMindMemoryRetriever(
                {
                    "memory_log_path": str(root / "memory.md"),
                    "results_dir": str(root / "results"),
                    "memory_retrieval_enabled": True,
                },
                log,
            )
            contexts = retriever.build_contexts("NVDA", "2026-02-01")
            self.assertIn("Historical retrieval for Research Manager on NVDA", contexts["research_memory_context"])
            self.assertIn("Gross margin expanded", contexts["research_memory_context"])
            self.assertIn("Prior outcome lessons for NVDA", contexts["portfolio_memory_context"])


if __name__ == "__main__":
    unittest.main()
