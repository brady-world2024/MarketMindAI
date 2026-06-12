import unittest

from marketmind_ai.symbols import SymbolResolution, ValidationFlags
from marketmind_ai.web.catalog import build_provider_catalog, supported_provider_values
from marketmind_ai.web.models import AnalysisRequest, ResolveSymbolRequest
from marketmind_ai.web.runner import SnapshotBuilder, build_graph_config


class WebModelTests(unittest.TestCase):
    def test_supported_provider_values_include_expected_targets(self):
        providers = supported_provider_values()
        for provider in ("openai", "anthropic", "google", "ollama", "openrouter"):
            self.assertIn(provider, providers)

    def test_analysis_request_normalizes_fields(self):
        request = AnalysisRequest(
            ticker=" nvda ",
            analysis_date="2026-05-01",
            llm_provider="openai",
            api_key=" key ",
            quick_model="gpt-5.4-mini",
            deep_model="gpt-5.4",
            analysts=["news", "market", "news"],
            output_language="Chinese",
        )
        self.assertEqual(request.ticker, "nvda")
        self.assertEqual(request.api_key, "key")
        self.assertEqual(request.analysts, ["news", "market"])

    def test_analysis_request_normalizes_sentiment_alias_to_social(self):
        request = AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-05-01",
            llm_provider="openai",
            quick_model="gpt-5.4-mini",
            deep_model="gpt-5.4",
            analysts=["sentiment", "market"],
            output_language="English",
        )
        self.assertEqual(request.analysts, ["social", "market"])

    def test_build_graph_config_carries_web_fields(self):
        request = AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-05-01",
            llm_provider="openai",
            api_key="web-key",
            quick_model="gpt-5.4-mini",
            deep_model="gpt-5.4",
            analysts=["market", "news"],
            output_language="Chinese",
            research_depth=3,
        )
        config = build_graph_config(request)
        self.assertEqual(config["llm_provider"], "openai")
        self.assertEqual(config["api_key"], "web-key")
        self.assertEqual(config["quick_think_llm"], "gpt-5.4-mini")
        self.assertEqual(config["deep_think_llm"], "gpt-5.4")
        self.assertEqual(config["output_language"], "Chinese")
        self.assertEqual(config["max_debate_rounds"], 3)
        self.assertEqual(config["max_risk_discuss_rounds"], 3)

    def test_resolve_symbol_request_accepts_company_queries(self):
        request = ResolveSymbolRequest(query=" Apple Inc ", analysis_date="2026-05-01")
        self.assertEqual(request.query, "Apple Inc")
        self.assertEqual(request.analysis_date, "2026-05-01")

    def test_snapshot_builder_records_resolution_metadata(self):
        request = AnalysisRequest(
            ticker="APPLE",
            analysis_date="2026-05-01",
            llm_provider="openai",
            quick_model="gpt-5.4-mini",
            deep_model="gpt-5.4",
            analysts=["market", "news"],
            output_language="English",
        )
        resolution = SymbolResolution(
            status="RESOLVED",
            original_input="APPLE",
            normalized_query="APPLE",
            resolved_symbol="AAPL",
            company_name="Apple Inc",
            exchange="NASDAQ",
            region="United States",
            currency="USD",
            confidence=94.2,
            validation=ValidationFlags(price_data=True, fundamental_data=True),
        )
        snapshot = SnapshotBuilder("run-1", request, resolution).snapshot
        self.assertEqual(snapshot.original_input, "APPLE")
        self.assertEqual(snapshot.ticker, "AAPL")
        self.assertEqual(snapshot.resolved_from, "APPLE")
        self.assertEqual(snapshot.company_name, "Apple Inc")


if __name__ == "__main__":
    unittest.main()
