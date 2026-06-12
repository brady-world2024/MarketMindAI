import os
import unittest
from unittest.mock import patch

from marketmind_ai.dataflows.config import _configured_sec_user_agent


class DataflowConfigTests(unittest.TestCase):
    def test_sec_user_agent_prefers_unified_env_var(self):
        with patch.dict(
            os.environ,
            {
                "MARKETMIND_SEC_USER_AGENT": "MarketMindAI-Test/1.0 (contact@example.com)",
                "MARKETMIND_AI_SEC_USER_AGENT": "legacy-value",
            },
            clear=False,
        ):
            self.assertEqual(
                _configured_sec_user_agent(),
                "MarketMindAI-Test/1.0 (contact@example.com)",
            )

    def test_sec_user_agent_keeps_legacy_env_var_as_fallback(self):
        with patch.dict(
            os.environ,
            {"MARKETMIND_AI_SEC_USER_AGENT": "Legacy-Agent/0.9"},
            clear=True,
        ):
            self.assertEqual(_configured_sec_user_agent(), "Legacy-Agent/0.9")


if __name__ == "__main__":
    unittest.main()
