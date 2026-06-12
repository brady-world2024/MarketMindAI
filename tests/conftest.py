from __future__ import annotations

import os


os.environ.setdefault("MARKETMIND_WEB_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
os.environ.setdefault("MARKETMIND_AI_HOME", "/tmp/marketmind-pytest-home")
