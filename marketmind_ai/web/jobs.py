"""Durable recovery metadata for a single local research server."""
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from ..dataflows.results import safe_json


_FIELDS = (
    "run_id", "status", "ticker", "original_input", "analysis_date", "provider", "quick_model",
    "deep_model", "output_language", "selected_analysts", "data_mode", "started_at",
    "current_agent", "research_cutoff", "data_snapshot", "model_usage",
)


class JobStore:
    def __init__(self, root: Path):
        self.path = root / "jobs.sqlite3"
        self.owner = uuid4().hex
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS active_jobs (
                    run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def save(self, snapshot: dict, secret: str | None = None):
        payload = {key: snapshot[key] for key in _FIELDS if key in snapshot}

        def redact(value):
            if isinstance(value, str):
                return value.replace(secret, "[redacted]") if secret else value
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value

        for key in ("original_input", "quick_model", "deep_model", "output_language"):
            if key in payload:
                payload[key] = redact(safe_json(payload[key]))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO active_jobs (run_id, owner, payload, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET owner=excluded.owner, payload=excluded.payload, updated_at=excluded.updated_at
            """, (snapshot["run_id"], self.owner, json.dumps(payload), datetime.now(timezone.utc).isoformat()))

    def remove(self, run_id: str):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DELETE FROM active_jobs WHERE run_id=? AND owner=?", (run_id, self.owner))

    def mark_interrupted(self, run_id: str):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE active_jobs SET owner='' WHERE run_id=? AND owner=?", (run_id, self.owner))

    def get(self, run_id: str) -> dict | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT owner, payload FROM active_jobs WHERE run_id=?", (run_id,)).fetchone()
        return self._snapshot(*row) if row else None

    def interrupted(self) -> list[dict]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("""
                SELECT owner, payload FROM active_jobs WHERE owner != ? ORDER BY updated_at DESC
            """, (self.owner,)).fetchall()
        return [self._snapshot(*row) for row in rows]

    def _snapshot(self, owner: str, payload: str) -> dict:
        result = json.loads(payload)
        result.update(agents=[], messages=[], reports=[], tool_calls=[])
        if owner != self.owner:
            result["job_status"] = "interrupted"
            if result.get("model_usage") is not None:
                result["model_usage"]["possibly_incomplete"] = True
            result["last_job_status"] = result["status"]
            result["status"] = "error"
            result["error"] = "The research server stopped before this run finished."
            result["latest_update"] = ("Use the saved data to run this research again."
                                       if result.get("data_snapshot") else "No saved data was available. Start a new research run.")
        return result
