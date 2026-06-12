import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from marketmind_ai.graph.marketmind_graph import MarketMindGraph, build_offline_data_vendor_config
from marketmind_ai.symbols import SymbolResolution, ValidationFlags
from marketmind_ai.web.app import create_app


def _resolved(symbol="AAPL", original_input="APPLE"):
    return SymbolResolution(
        status="RESOLVED",
        original_input=original_input,
        normalized_query=original_input,
        resolved_symbol=symbol,
        company_name="Apple Inc",
        exchange="NASDAQ",
        region="United States",
        currency="USD",
        confidence=94.2,
        validation=ValidationFlags(price_data=True, fundamental_data=True),
    )


def _not_found(original_input="APPLE"):
    return SymbolResolution(
        status="NOT_FOUND",
        original_input=original_input,
        normalized_query=original_input,
        reason="No matching symbols were returned.",
        validation=ValidationFlags(price_data=False, fundamental_data=False),
    )


class SymbolResolutionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(self._temp_dir.name))

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_report_generation_is_blocked_when_ticker_is_not_resolved(self):
        with patch("marketmind_ai.web.app.resolve_request_symbol", lambda request, workflow=None: _not_found()):
            with patch("marketmind_ai.web.app.AnalysisThread") as mock_thread:
                response = self.client.post(
                    "/api/runs",
                    json={
                        "ticker": "APPLE",
                        "analysis_date": "2026-05-01",
                        "llm_provider": "openai",
                        "quick_model": "gpt-5.4-mini",
                        "deep_model": "gpt-5.4",
                        "analysts": ["market"],
                        "output_language": "English",
                    },
                )

        self.assertEqual(response.status_code, 422)
        body = response.json()["detail"]
        self.assertEqual(body["status"], "NOT_FOUND")
        mock_thread.assert_not_called()

    def test_resolve_endpoint_returns_resolution(self):
        with patch("marketmind_ai.web.symbols_router.SymbolResolver.resolve", lambda self, query, analysis_date: _resolved(original_input=query)):
            response = self.client.post(
                "/api/symbols/resolve",
                json={"query": "APPLE", "analysis_date": "2026-05-01"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "RESOLVED")
        self.assertEqual(body["resolved_symbol"], "AAPL")

    def test_resolve_endpoint_is_registered_in_openapi(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/api/symbols/resolve", paths)
        self.assertIn("post", paths["/api/symbols/resolve"])

    def test_resolve_endpoint_returns_validation_payload_for_invalid_symbol(self):
        with patch("marketmind_ai.web.symbols_router.SymbolResolver.resolve", lambda self, query, analysis_date: _not_found(original_input=query)):
            response = self.client.post(
                "/api/symbols/resolve",
                json={"query": "UNKNOWN", "analysis_date": "2026-05-01"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "NOT_FOUND")
        self.assertEqual(body["original_input"], "UNKNOWN")

    def test_graph_blocks_report_generation_when_resolution_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = MarketMindGraph(
                storage_root=Path(temp_dir),
                config={"data_vendors": build_offline_data_vendor_config()},
            )
            with patch.object(workflow.resolver, "resolve", lambda query, trade_date: _not_found(original_input=query)):
                with self.assertRaises(ValueError):
                    list(
                        workflow.stream(
                            workflow_request(),
                            run_id="blocked",
                        )
                    )


def workflow_request():
    from marketmind_ai.graph.request import AnalysisRequest

    return AnalysisRequest.from_mapping(
        {
            "ticker": "APPLE",
            "analysis_date": "2026-05-01",
            "llm_provider": "offline",
            "quick_model": "heuristic-fast",
            "deep_model": "heuristic-deep",
            "analysts": ["market"],
            "output_language": "English",
        }
    )


if __name__ == "__main__":
    unittest.main()
