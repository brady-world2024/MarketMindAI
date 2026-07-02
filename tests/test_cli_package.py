import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from marketmind_ai.cli.announcements import fetch_announcements
from marketmind_ai.cli.main import app, main
from marketmind_ai.cli.stats_handler import StatsCallbackHandler


class CliPackageTests(unittest.TestCase):
    def test_cli_supports_expected_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("analyze", result.stdout)
        self.assertIn("interactive", result.stdout)
        self.assertIn("resolve", result.stdout)
        self.assertIn("validate-provider", result.stdout)
        self.assertIn("serve", result.stdout)

    @patch("marketmind_ai.cli.main.app")
    def test_main_without_explicit_argv_allows_typer_to_read_process_args(self, mock_app):
        result = main()

        self.assertEqual(result, 0)
        self.assertIsNone(mock_app.call_args.kwargs["args"])

    def test_fetch_announcements_without_config_returns_empty_payload(self):
        payload = fetch_announcements(url="")
        self.assertEqual(payload.announcements, [])
        self.assertFalse(payload.require_attention)

    def test_stats_handler_observes_snapshot_counts(self):
        handler = StatsCallbackHandler()
        handler.observe_snapshot(
            {
                "current_agent": "Market Analyst",
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "tool_calls": [{"id": "t1"}, {"id": "t2"}],
            }
        )
        stats = handler.get_stats()
        self.assertEqual(stats.snapshots_seen, 1)
        self.assertEqual(stats.agent_updates, 1)
        self.assertEqual(stats.message_count, 2)
        self.assertEqual(stats.tool_calls, 2)


if __name__ == "__main__":
    unittest.main()
