import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from marketmind_ai.symbols import SymbolResolution, ValidationFlags
from marketmind_ai.web.app import create_app


class WebAppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(str(Path(self._temp_dir.name))))

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_health_and_provider_routes(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"ok": True})

        providers = self.client.get("/api/providers")
        self.assertEqual(providers.status_code, 200)
        self.assertGreaterEqual(len(providers.json()), 5)
        self.assertIn("base_url", providers.json()[0])
        alias = self.client.get("/providers/models")
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(alias.json(), providers.json())

    def test_index_references_static_assets(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/styles.css', response.text)
        self.assertIn('/static/app.js', response.text)

    def test_resolve_route_accepts_company_query(self):
        with patch(
            "marketmind_ai.web.symbols_router.SymbolResolver.resolve",
            lambda self, query, analysis_date: SymbolResolution(
                status="RESOLVED",
                original_input=query,
                normalized_query=query,
                resolved_symbol="NVDA",
                company_name="NVIDIA Corporation",
                exchange="NASDAQ",
                region="US",
                currency="USD",
                confidence=98.0,
                validation=ValidationFlags(price_data=True, fundamental_data=True),
            ),
        ):
            response = self.client.post("/api/symbols/resolve", json={"query": "NVIDIA", "analysis_date": "2026-06-12"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "RESOLVED")
        self.assertEqual(payload["resolved_symbol"], "NVDA")

    def test_canonical_routes_and_reference_aliases_are_exposed(self):
        openapi = self.client.get("/openapi.json")
        self.assertEqual(openapi.status_code, 200)
        paths = openapi.json()["paths"]
        self.assertIn("/providers/models", paths)
        self.assertIn("/api/providers", paths)
        self.assertIn("/validate-key", paths)
        self.assertIn("/api/validate-key", paths)
        self.assertIn("/runs", paths)
        self.assertIn("/reports", paths)
        self.assertIn("/api/runs", paths)
        self.assertIn("/api/reports", paths)
        self.assertIn("/runs/{run_id}", paths)
        self.assertIn("/api/runs/{run_id}", paths)
        self.assertIn("/runs/{run_id}/result", paths)
        self.assertIn("/api/runs/{run_id}/result", paths)
        self.assertIn("/runs/{run_id}/report", paths)
        self.assertIn("/api/runs/{run_id}/report", paths)
        self.assertIn("/runs/{run_id}/stream", paths)
        self.assertIn("/api/runs/{run_id}/stream", paths)
        self.assertNotIn("/api/resolve", paths)

    def test_create_run_returns_reference_compatible_urls(self):
        with patch("marketmind_ai.web.app.AnalysisThread") as mock_thread:
            response = self.client.post(
                "/runs",
                json={
                    "ticker": "NVDA",
                    "analysis_date": "2026-06-12",
                    "llm_provider": "offline",
                    "quick_model": "heuristic-fast",
                    "deep_model": "heuristic-deep",
                    "analysts": ["market"],
                    "output_language": "English",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertRegex(payload["stream_url"], r"^/runs/.+/stream$")
        self.assertRegex(payload["result_url"], r"^/runs/.+/result$")
        self.assertRegex(payload["report_url"], r"^/runs/.+/report$")
        mock_thread.return_value.start.assert_called_once()

    def test_report_route_renders_printable_html(self):
        snapshot = {
            "run_id": "run-123",
            "status": "completed",
            "original_input": "NVDA",
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "analysis_date": "2026-06-12",
            "provider": "openai",
            "quick_model": "gpt-5.4-mini",
            "deep_model": "gpt-5.4",
            "output_language": "English",
            "selected_analysts": ["market", "news"],
            "started_at": "2026-06-12T10:00:00Z",
            "finished_at": "2026-06-12T10:10:00Z",
            "current_agent": None,
            "latest_update": "Completed",
            "agents": [],
            "messages": [],
            "tool_calls": [],
            "reports": [{"key": "final_trade_decision", "label": "Final Trade Decision", "content": "Buy NVDA"}],
            "final_signal": "Overweight",
            "final_decision": "Actionable decision text",
        }
        with patch("marketmind_ai.web.app._resolve_snapshot", return_value=snapshot):
            response = self.client.get("/runs/run-123/report?autoprint=true")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("NVDA Research Report", response.text)
        self.assertIn("window.print()", response.text)


if __name__ == "__main__":
    unittest.main()
