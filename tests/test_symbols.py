import tempfile
import unittest
from pathlib import Path

from marketmind_ai.graph.marketmind_graph import MarketMindGraph, build_offline_data_vendor_config


class SymbolResolverTests(unittest.TestCase):
    def test_company_name_resolves_to_fixture_symbol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = MarketMindGraph(
                storage_root=Path(temp_dir),
                config={"data_vendors": build_offline_data_vendor_config()},
            )
            resolution = workflow.resolve_symbol("NVIDIA", "2026-06-12")
            self.assertEqual(resolution.status, "RESOLVED")
            self.assertEqual(resolution.resolved_symbol, "NVDA")
            self.assertTrue(resolution.validation.price_data)
            self.assertTrue(resolution.validation.fundamental_data)


if __name__ == "__main__":
    unittest.main()
