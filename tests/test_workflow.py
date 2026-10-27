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
            final_payload = final_snapshot.to_dict()
            self.assertGreaterEqual(final_payload["report_quality"]["score"], 60)
            self.assertIn("confidence_calibration", final_payload["report_quality"]["dimensions"])
            self.assertIn("claim_support", final_payload["report_quality"]["dimensions"])
            self.assertIn("counterargument_coverage", final_payload["report_quality"]["dimensions"])
            self.assertIn("claim_audit", final_payload["report_quality"])
            self.assertTrue(final_payload["final_structured_decision"]["core_claims"])
            self.assertEqual(final_payload["report_quality"]["claim_audit"]["unsupported_claims"], [])
            self.assertTrue(final_payload["evidence_ledger"])
            for evidence in final_payload["evidence_ledger"]:
                self.assertTrue(evidence["provider"])
                self.assertTrue(evidence["url"])
                self.assertTrue(evidence["source_type"])
                self.assertTrue(evidence["retrieved_at"])
                self.assertTrue(evidence["raw_source_id"])
            self.assertTrue(final_snapshot.tool_calls)
            self.assertTrue(any(report.key == "final_trade_decision" and report.content for report in final_snapshot.reports))
            self.assertIsNotNone(workflow.archive.load("testrun123"))
            self.assertEqual(workflow.journal.recall("NVDA"), [])
            self.assertEqual(final_payload["review"]["status"], "pending")
            workflow.reviews.decide("testrun123", decision="approve", reviewer="Test reviewer", comment="",
                                    version=final_payload["review"]["version"], report_hash=final_payload["review"]["report_hash"])
            self.assertTrue(workflow.journal.recall("NVDA"))


if __name__ == "__main__":
    unittest.main()
