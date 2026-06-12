import tempfile
import unittest
from pathlib import Path

from marketmind_ai.graph.marketmind_graph import MarketMindGraph, build_offline_data_vendor_config
from marketmind_ai.graph.request import AnalysisRequest


class MarketMindGraphTests(unittest.TestCase):
    def test_offline_workflow_produces_persisted_final_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = MarketMindGraph(
                storage_root=Path(temp_dir),
                config={"data_vendors": build_offline_data_vendor_config()},
            )
            request = AnalysisRequest.from_mapping(
                {
                    "ticker": "NVDA",
                    "analysis_date": "2026-06-12",
                    "llm_provider": "offline",
                    "quick_model": "heuristic-fast",
                    "deep_model": "heuristic-deep",
                    "analysts": ["market", "social", "news", "fundamentals"],
                    "output_language": "English",
                    "research_depth": 2,
                }
            )
            snapshots = list(workflow.stream(request, run_id="testrun123"))
            final_snapshot = snapshots[-1]

            self.assertEqual(final_snapshot.run_id, "testrun123")
            self.assertEqual(final_snapshot.status, "completed")
            self.assertIsNotNone(final_snapshot.final_signal)
            self.assertIsNotNone(final_snapshot.final_decision)
            self.assertTrue(final_snapshot.tool_calls)
            self.assertTrue(any(report.key == "final_trade_decision" and report.content for report in final_snapshot.reports))
            self.assertIsNotNone(workflow.archive.load("testrun123"))
            self.assertTrue(workflow.journal.recall("NVDA"))


if __name__ == "__main__":
    unittest.main()
