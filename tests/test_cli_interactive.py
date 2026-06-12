import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from marketmind_ai.cli.main import app
from marketmind_ai.cli.models import AnalyzeOptions
from marketmind_ai.cli.utils import build_interactive_analyze_options


class CliInteractiveTests(unittest.TestCase):
    @patch("marketmind_ai.cli.utils.prompt_confirm", side_effect=[True, False])
    @patch("marketmind_ai.cli.utils.prompt_checkbox", return_value=["market", "news"])
    @patch("marketmind_ai.cli.utils.prompt_select", side_effect=["offline", "heuristic-fast", "heuristic-deep", 3])
    @patch("marketmind_ai.cli.utils.prompt_text", side_effect=["nvda", "2026-06-12", "Chinese"])
    def test_build_interactive_analyze_options_for_offline_provider(
        self,
        _prompt_text,
        _prompt_select,
        _prompt_checkbox,
        _prompt_confirm,
    ):
        options = build_interactive_analyze_options(storage_root="/tmp/marketmind-interactive")

        self.assertEqual(options.ticker, "NVDA")
        self.assertEqual(options.analysis_date, "2026-06-12")
        self.assertEqual(options.llm_provider, "offline")
        self.assertEqual(options.quick_model, "heuristic-fast")
        self.assertEqual(options.deep_model, "heuristic-deep")
        self.assertEqual(options.analysts, ["market", "news"])
        self.assertEqual(options.research_depth, 3)
        self.assertEqual(options.output_language, "Chinese")
        self.assertTrue(options.checkpoint_enabled)
        self.assertFalse(options.emit_json)
        self.assertEqual(options.storage_root, "/tmp/marketmind-interactive")

    @patch("marketmind_ai.cli.main.run_analyze", return_value=0)
    @patch(
        "marketmind_ai.cli.main.build_interactive_analyze_options",
        return_value=AnalyzeOptions(
            ticker="NVDA",
            analysis_date="2026-06-12",
            llm_provider="offline",
            api_key="",
            quick_model="heuristic-fast",
            deep_model="heuristic-deep",
            output_language="English",
            base_url="",
            google_thinking_level="",
            openai_reasoning_effort="",
            anthropic_effort="",
            analysts=["market", "news"],
            research_depth=3,
            checkpoint_enabled=False,
            storage_root="/tmp/interactive-run",
            emit_json=False,
        ),
    )
    def test_interactive_command_dispatches_built_options(self, mock_builder, mock_run_analyze):
        runner = CliRunner()
        result = runner.invoke(app, ["interactive", "--storage-root", "/tmp/interactive-run"])

        self.assertEqual(result.exit_code, 0)
        mock_builder.assert_called_once_with(storage_root="/tmp/interactive-run")
        mock_run_analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()
