from __future__ import annotations

import os

from ..config import DEFAULT_ANALYSTS


CLI_PROG = "marketmind-ai"
CLI_DESCRIPTION = "Evidence-backed market research workbench."
DEFAULT_ANALYSIS_DATE = "2026-06-12"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CLI_ANALYSTS = list(DEFAULT_ANALYSTS)

CLI_CONFIG = {
    "announcements_url": os.getenv("MARKETMIND_AI_ANNOUNCEMENTS_URL", ""),
    "announcements_timeout": 1.0,
    "announcements_fallback": "Check the repository changelog for the latest MarketMind AI updates.",
}
