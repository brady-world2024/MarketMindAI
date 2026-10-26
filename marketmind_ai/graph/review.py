"""Transactional human review, immutable reports, and approved learning records."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .snapshot import utc_now
from ..agents.utils.rating import parse_rating, parse_decision_status
from ..pathing import safe_ticker_component


class ReviewConflict(ValueError):
    pass


def report_hash(snapshot: dict) -> str:
    # Review metadata and stream progress are mutable; report content is not.
    keys = ("ticker", "analysis_date", "provider", "quick_model", "deep_model", "output_language",
            "selected_analysts", "final_signal", "final_decision", "final_structured_decision",
            "report_verification", "report_quality", "evidence_ledger", "reports")
    payload = {key: snapshot.get(key) for key in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class ReviewStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS review_runs (
                    run_id TEXT PRIMARY KEY, snapshot TEXT, request TEXT NOT NULL,
                    state TEXT, version INTEGER NOT NULL, parent_run_id TEXT,
                    revision_run_id TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approved_memories (
                    run_id TEXT PRIMARY KEY REFERENCES review_runs(run_id),
                    entry TEXT NOT NULL, state TEXT NOT NULL
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _safe_request(request) -> dict:
        payload = asdict(request) if not isinstance(request, dict) else dict(request)
        payload.pop("api_key", None)
        return payload

    def save_draft(self, snapshot: dict, request, state: dict) -> dict:
        snapshot = deepcopy(snapshot)
        payload = self._safe_request(request)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM review_runs WHERE run_id=?", (snapshot["run_id"],)).fetchone()
            if old and old["snapshot"]:
                # Retries cannot overwrite a previously reviewed immutable report.
                canonical = json.loads(old["snapshot"])
                if report_hash(canonical) != report_hash(snapshot):
                    raise ReviewConflict("A run id identifies an immutable report; use a new run id for new research.")
                return canonical
            version = old["version"] if old else 1
            parent = old["parent_run_id"] if old else None
            feedback = payload.get("human_feedback", "")
            snapshot["review"] = {"status": "pending", "version": version,
                                  "report_hash": report_hash(snapshot), "requested_at": utc_now(),
                                  "history": [], "parent_run_id": parent, "revision_run_id": None,
                                  "feedback": feedback}
            db.execute("""INSERT INTO review_runs(run_id,snapshot,request,state,version,parent_run_id,created_at)
                          VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
                          snapshot=excluded.snapshot,request=excluded.request,state=excluded.state""",
                       (snapshot["run_id"], json.dumps(snapshot), json.dumps(payload), json.dumps(state), version, parent, utc_now()))
        return snapshot

    def load(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT snapshot FROM review_runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row["snapshot"]) if row and row["snapshot"] else None

    def list_reviews(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT snapshot FROM review_runs WHERE snapshot IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            snapshot = json.loads(row["snapshot"])
            result.append({key: snapshot[key] for key in ("run_id", "ticker", "analysis_date", "review")})
        return result

    @staticmethod
    def _check(row, version: int, digest: str) -> dict:
        if not row or not row["snapshot"]:
            raise KeyError("Reviewable run not found")
        snapshot = json.loads(row["snapshot"])
        review = snapshot["review"]
        if review["version"] != version or review["report_hash"] != digest or report_hash(snapshot) != digest:
            raise ReviewConflict("The report version or hash changed. Reload the report before reviewing.")
        return snapshot

    def decide(self, run_id: str, *, decision: str, version: int, report_hash: str, reviewer: str, comment: str = "") -> dict:
        reviewer, comment = reviewer.strip(), comment.strip()
        if decision not in {"approve", "reject", "request_changes"} or not reviewer or (decision != "approve" and not comment):
            raise ValueError("A reviewer and valid decision are required; rejection and changes require a comment.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM review_runs WHERE run_id=?", (run_id,)).fetchone()
            snapshot = self._check(row, version, report_hash)
            review = snapshot["review"]
            if review["status"] != "pending":
                latest = review["history"][-1]
                if all(latest[key] == value for key, value in (("decision", decision), ("reviewer", reviewer), ("comment", comment))):
                    return snapshot
                raise ReviewConflict("This report already has a human decision. Reload the current review.")
            if decision == "approve" and self._approval_blocked(snapshot):
                raise ReviewConflict("Automated validation blocks this actionable report. Request changes before approving.")
            review["status"] = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[decision]
            review["history"].append({"decision": decision, "reviewer": reviewer, "comment": comment,
                                      "reviewed_at": utc_now(), "version": version, "report_hash": report_hash})
            db.execute("UPDATE review_runs SET snapshot=? WHERE run_id=?", (json.dumps(snapshot), run_id))
            if decision == "approve":
                entry = {"run_id": run_id, "date": snapshot["analysis_date"], "ticker": safe_ticker_component(snapshot["ticker"]),
                         "rating": parse_rating(snapshot.get("final_decision") or ""), "pending": True,
                         "raw": None, "alpha": None, "holding_days": None,
                         "decision": snapshot.get("final_decision") or "", "reflection": ""}
                db.execute("INSERT INTO approved_memories(run_id,entry,state) VALUES(?,?,?)",
                           (run_id, json.dumps(entry), row["state"] or "{}"))
        return snapshot

    @staticmethod
    def _approval_blocked(snapshot: dict) -> bool:
        structured = snapshot.get("final_structured_decision") or {}
        status = str(structured.get("decision_status") or "").lower().replace("_", " ")
        signal = str(snapshot.get("final_signal") or "").lower().replace("_", " ")
        text_status = parse_decision_status(snapshot.get("final_decision") or "").lower()
        if "no recommendation" in {status, signal, text_status}:
            return not (status == signal == text_status == "no recommendation")
        verification = snapshot.get("report_verification") or {}
        from .runtime_support import GraphResearchEngine
        quality = snapshot.get("report_quality") or {}
        return (status != "actionable" or verification.get("status") != "passed"
                or verification.get("blocks_actionable_recommendation", False)
                or not quality or GraphResearchEngine._quality_blocks_actionable(quality))

    def reserve_revision(self, run_id: str, *, version: int, report_hash: str) -> tuple[str, dict]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM review_runs WHERE run_id=?", (run_id,)).fetchone()
            snapshot = self._check(row, version, report_hash)
            review = snapshot["review"]
            if review["status"] != "changes_requested":
                raise ReviewConflict("A revision requires a human request for changes.")
            child_id = row["revision_run_id"]
            if child_id:
                child = db.execute("SELECT request FROM review_runs WHERE run_id=?", (child_id,)).fetchone()
                return child_id, json.loads(child["request"])
            child_id = uuid4().hex[:12]
            payload = json.loads(row["request"])
            payload["human_feedback"] = "\n\n".join(filter(None, [payload.get("human_feedback"), review["history"][-1]["comment"]]))
            payload["checkpoint_enabled"] = False
            review["revision_run_id"] = child_id
            db.execute("UPDATE review_runs SET snapshot=?,revision_run_id=? WHERE run_id=?", (json.dumps(snapshot), child_id, run_id))
            db.execute("INSERT INTO review_runs(run_id,request,version,parent_run_id,created_at) VALUES(?,?,?,?,?)",
                       (child_id, json.dumps(payload), version + 1, run_id, utc_now()))
            return child_id, payload
