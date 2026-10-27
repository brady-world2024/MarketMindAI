"""Durable, optimistic human review with approved-only learning."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from marketmind_ai.graph.marketmind_graph import MarketMindGraph
from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.web.app import RUNS, create_app


def request(**overrides):
    return AnalysisRequest.from_mapping({
        "ticker": "NVDA", "analysis_date": "2026-06-12", "llm_provider": "offline",
        "quick_model": "heuristic-fast", "deep_model": "heuristic-deep",
        "analysts": ["market", "news", "fundamentals"], **overrides,
    })


@pytest.fixture
def draft(tmp_path):
    graph = MarketMindGraph(storage_root=tmp_path)
    snapshot = list(graph.stream(request(api_key="secret-do-not-save"), run_id="review-test"))[-1].to_dict()
    return graph, snapshot, TestClient(create_app(str(tmp_path)))


def review_payload(snapshot, decision="approve", **overrides):
    return {"decision": decision, "version": snapshot["review"]["version"],
            "report_hash": snapshot["review"]["report_hash"], "reviewer": "Alex",
            "comment": "Investigate the counterargument" if decision != "approve" else "", **overrides}


def test_draft_is_durable_and_excluded_from_both_memory_paths(draft):
    graph, snapshot, client = draft
    assert snapshot.get("review", {}).get("status") == "pending"
    assert snapshot["status"] == "completed"
    assert graph.journal.recall("NVDA") == []
    assert graph.memory_log.load_entries() == []
    assert all(not text for text in graph.memory_retriever.build_contexts("NVDA", "2026-07-01").values())
    restored = client.get("/runs/review-test/result").json()
    assert restored == snapshot
    assert client.get("/api/reviews").json()[0]["review"] == snapshot["review"]
    for path in graph.paths.root.rglob("*"):
        if path.is_file():
            assert b"secret-do-not-save" not in path.read_bytes()


def test_approval_is_durable_idempotent_and_publishes_memory_atomically(draft):
    graph, snapshot, client = draft
    body = review_payload(snapshot)
    accepted = client.post("/runs/review-test/review", json=body)
    assert accepted.status_code == 200
    assert accepted.json()["review"]["status"] == "approved"
    assert len(accepted.json()["review"]["history"]) == 1
    assert client.post("/api/runs/review-test/review", json=body).json() == accepted.json()
    assert len(graph.journal.recall("NVDA")) == 1
    assert len(graph.memory_log.load_entries()) == 1
    assert any(graph.memory_retriever.build_contexts("NVDA", "2026-07-01").values())
    restart = TestClient(create_app(str(graph.paths.root)))
    assert restart.get("/runs/review-test/result").json() == accepted.json()
    graph.memory_log.update_with_outcome("NVDA", "2026-06-12", .05, .03, 5, "Evidence held.", run_id="review-test")
    assert graph.memory_log.load_entries()[0]["reflection"] == "Evidence held."
    assert not graph.memory_log.load_entries()[0]["pending"]
    assert not graph.paths.memory_file.exists()


@pytest.mark.parametrize("change", [{"version": 99}, {"report_hash": "stale"}])
def test_stale_review_rejected_without_memory(draft, change):
    graph, snapshot, client = draft
    assert client.post("/runs/review-test/review", json=review_payload(snapshot, **change)).status_code == 409
    assert graph.memory_log.load_entries() == []


@pytest.mark.parametrize("decision,reviewer,comment", [("reject", "Alex", ""), ("request_changes", "Alex", "  "), ("approve", " ", ""), ("invalid", "Alex", "text")])
def test_review_validation(draft, decision, reviewer, comment):
    _, snapshot, client = draft
    response = client.post("/runs/review-test/review", json=review_payload(snapshot, decision, reviewer=reviewer, comment=comment))
    assert response.status_code == 422


def test_competing_reviewers_only_one_wins(draft):
    graph, snapshot, client = draft
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda decision: client.post("/runs/review-test/review", json=review_payload(snapshot, decision)), ["approve", "reject"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = client.get("/runs/review-test/result").json()
    assert len(final["review"]["history"]) == 1
    assert len(graph.memory_log.load_entries()) == (1 if final["review"]["status"] == "approved" else 0)


def test_revision_links_feedback_fresh_checks_and_survives_restart(draft):
    graph, snapshot, client = draft
    assert client.post("/runs/review-test/revise", json=review_payload(snapshot)).status_code == 409
    changed = client.post("/runs/review-test/review", json=review_payload(snapshot, "request_changes")).json()
    revision_body = {"version": changed["review"]["version"], "report_hash": changed["review"]["report_hash"]}
    with patch("marketmind_ai.web.app.AnalysisThread") as worker:
        child = client.post("/runs/review-test/revise", json=revision_body)
        assert child.status_code == 200
        duplicate = client.post("/api/runs/review-test/revise", json=revision_body)
        assert duplicate.json()["run_id"] == child.json()["run_id"]
        worker.return_value.start.assert_called_once()
    child_id = child.json()["run_id"]
    assert client.get("/runs/review-test/result").json()["review"]["revision_run_id"] == child_id
    # Simulate restart: reserved child recovers from SQLite, without a credential or checkpoint.
    with RUNS._lock:
        RUNS._sessions.pop(child_id, None)
    restart = TestClient(create_app(str(graph.paths.root)))
    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    with patch("marketmind_ai.web.app.AnalysisThread", InlineThread):
        resumed = restart.post("/runs/review-test/revise", json=revision_body)
    assert resumed.json()["run_id"] == child_id
    fresh = restart.get(f"/runs/{child_id}/result").json()
    assert fresh["review"]["status"] == "pending"
    assert fresh["review"]["version"] == 2
    assert fresh["review"]["parent_run_id"] == "review-test"
    assert fresh["review"]["history"] == []
    assert "Investigate the counterargument" in json.dumps(fresh)
    assert "not synthesized" in json.dumps(fresh).lower()
    assert graph.journal.recall("NVDA") == []


def test_durable_snapshot_wins_over_cached_session(draft):
    _, snapshot, client = draft
    session = RUNS.create()
    session.run_id = "review-test"
    with RUNS._lock:
        RUNS._sessions["review-test"] = session
    session.publish("snapshot", snapshot)
    accepted = client.post("/runs/review-test/review", json=review_payload(snapshot)).json()
    assert client.get("/runs/review-test").json() == accepted


def test_conflicting_resubmission_and_rejection_never_publish_memory(draft):
    graph, snapshot, client = draft
    rejected = client.post("/runs/review-test/review", json=review_payload(snapshot, "reject"))
    assert rejected.status_code == 200
    assert rejected.json()["review"]["status"] == "rejected"
    assert client.post("/runs/review-test/review", json=review_payload(snapshot)).status_code == 409
    assert graph.memory_log.load_entries() == []
    assert all(not text for text in graph.memory_retriever.build_contexts("NVDA", "2026-07-01").values())


def test_gate_failure_cannot_be_approved_but_no_recommendation_can(draft):
    graph, snapshot, client = draft
    failed = {**snapshot, "run_id": "failed-gate", "final_signal": "Buy",
              "final_structured_decision": {"decision_status": "Actionable"},
              "report_verification": {"status": "fail", "blocks_actionable_recommendation": True}}
    failed = graph.reviews.save_draft(failed, request(), {})
    assert client.post("/runs/failed-gate/review", json=review_payload(failed)).status_code == 409
    abstain = graph.reviews.save_draft({**failed, "run_id": "abstain", "final_signal": "No Recommendation",
                                      "final_structured_decision": {"decision_status": "No Recommendation"},
                                      "final_decision": "**Decision Status**: No Recommendation\n\n**Evidence Gap**: Need evidence."}, request(), {})
    accepted = client.post("/runs/abstain/review", json=review_payload(abstain))
    assert accepted.status_code == 200
    assert accepted.json()["final_signal"] == "No Recommendation"
    assert accepted.json()["final_structured_decision"]["decision_status"] == "No Recommendation"


def test_approval_and_learning_roll_back_together_on_storage_failure(draft):
    graph, snapshot, _ = draft
    import sqlite3
    with graph.reviews.connect() as db:
        db.execute("CREATE TRIGGER reject_memory BEFORE INSERT ON approved_memories BEGIN SELECT RAISE(ABORT, 'storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="storage failure"):
        graph.reviews.decide("review-test", **review_payload(snapshot))
    assert graph.reviews.load("review-test")["review"]["status"] == "pending"
    assert graph.memory_log.load_entries() == []


def test_hash_binds_all_reviewed_report_content(draft):
    from copy import deepcopy
    from marketmind_ai.graph.review import report_hash
    _, snapshot, _ = draft
    original_hash = report_hash(snapshot)
    for field in ("final_decision", "final_signal", "final_structured_decision", "report_verification", "report_quality", "evidence_ledger", "reports"):
        changed = deepcopy(snapshot)
        changed[field] = "modified"
        assert report_hash(changed) != original_hash
    changed = deepcopy(snapshot)
    changed["review"]["status"] = "approved"
    assert report_hash(changed) == original_hash


def test_concurrent_revisions_reserve_one_child(draft):
    graph, snapshot, client = draft
    client.post("/runs/review-test/review", json=review_payload(snapshot, "request_changes"))
    with patch("marketmind_ai.web.app.AnalysisThread") as worker:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post("/runs/review-test/revise", json={
                "version": snapshot["review"]["version"], "report_hash": snapshot["review"]["report_hash"]}), range(2)))
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json()["run_id"] == responses[1].json()["run_id"]
        worker.return_value.start.assert_called_once()
    assert graph.memory_log.load_entries() == []


def test_completed_session_sse_replay_uses_current_review(draft):
    _, snapshot, client = draft
    session, _ = RUNS.claim("review-test")
    session.publish("snapshot", snapshot)
    session.publish("complete", snapshot)
    session.finish()
    client.post("/runs/review-test/review", json=review_payload(snapshot))
    response = client.get("/runs/review-test/stream")
    payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert all(payload.get("review", {}).get("status") == "approved" for payload in payloads)


def test_optional_revision_credentials_do_not_become_literal_none():
    from marketmind_ai.web.models import AnalysisRequest as WebRequest
    from marketmind_ai.web.runner import to_core_request
    web_request = WebRequest(ticker="NVDA", analysis_date="2026-06-12", llm_provider="openai",
                             quick_model="quick", deep_model="deep", api_key=None)
    assert to_core_request(web_request).api_key == ""


@pytest.mark.parametrize("status", ["failed", "unknown", None])
def test_actionable_approval_fails_closed_on_verification_status(draft, status):
    graph, snapshot, client = draft
    altered = {**snapshot, "run_id": "bad-status", "final_signal": "Buy",
               "final_structured_decision": {"decision_status": "Actionable"},
               "report_verification": {"status": status, "blocks_actionable_recommendation": False}}
    altered = graph.reviews.save_draft(altered, request(), {})
    assert client.post("/runs/bad-status/review", json=review_payload(altered)).status_code == 409


def test_contradictory_abstention_cannot_bypass_gate(draft):
    graph, snapshot, client = draft
    altered = graph.reviews.save_draft({**snapshot, "run_id": "contradictory", "final_signal": "No Recommendation",
                                      "final_structured_decision": {"decision_status": "Actionable"},
                                      "report_verification": {"status": "failed"}}, request(), {})
    assert client.post("/runs/contradictory/review", json=review_payload(altered)).status_code == 409


def test_immutable_run_id_cannot_be_reused_for_a_different_report(draft):
    from marketmind_ai.graph.review import ReviewConflict
    graph, snapshot, _ = draft
    with pytest.raises(ReviewConflict, match="immutable"):
        graph.reviews.save_draft({**snapshot, "final_decision": "Different report"}, request(), {})
    assert graph.reviews.load("review-test") == snapshot


def test_revision_rejects_unresolved_symbol_without_starting_worker(draft):
    from marketmind_ai.symbols import SymbolResolution
    _, snapshot, client = draft
    client.post("/runs/review-test/review", json=review_payload(snapshot, "request_changes"))
    unresolved = SymbolResolution(status="NOT_FOUND", original_input="NVDA", normalized_query="NVDA", reason="No symbol")
    with patch("marketmind_ai.web.app.resolve_request_symbol", return_value=unresolved), patch("marketmind_ai.web.app.AnalysisThread") as worker:
        response = client.post("/runs/review-test/revise", json={"version": 1, "report_hash": snapshot["review"]["report_hash"]})
    assert response.status_code == 422
    worker.assert_not_called()


def test_failed_revision_can_retry_same_child(draft):
    graph, snapshot, client = draft
    client.post("/runs/review-test/review", json=review_payload(snapshot, "request_changes"))
    body = {"version": 1, "report_hash": snapshot["review"]["report_hash"]}
    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    with patch("marketmind_ai.web.app.AnalysisThread", InlineThread), patch("marketmind_ai.graph.marketmind_graph.MarketMindGraph.stream", side_effect=RuntimeError("Temporary provider failure")):
        failed = client.post("/runs/review-test/revise", json=body)
    child_id = failed.json()["run_id"]
    assert client.get(f"/runs/{child_id}/result").json()["status"] == "error"
    with patch("marketmind_ai.web.app.AnalysisThread", InlineThread):
        retried = client.post("/runs/review-test/revise", json=body)
    assert retried.json()["run_id"] == child_id
    assert client.get(f"/runs/{child_id}/result").json()["status"] == "completed"
    assert graph.reviews.load(child_id)["review"]["status"] == "pending"


def test_same_day_approved_runs_keep_their_own_outcome_reflections(draft):
    graph, snapshot, _ = draft
    second = graph.reviews.save_draft({**snapshot, "run_id": "same-day-other",
                                      "final_decision": snapshot["final_decision"] + "\nIndependent second thesis."}, request(), {})
    for run in (snapshot, second):
        graph.reviews.decide(run["run_id"], **review_payload(run))
    with patch.object(graph.pending_outcomes, "_fetch_returns", return_value=(.05, .03, 5)), patch(
        "marketmind_ai.graph.pending_outcomes.Reflector.reflect_on_final_decision",
        side_effect=lambda decision, *_: "Second thesis lesson" if decision.endswith("Independent second thesis.") else "First thesis lesson",
    ):
        graph.pending_outcomes.resolve_for_ticker("NVDA", "2026-07-01", None)
    entries = graph.memory_log.load_entries()
    by_run = {entry.get("run_id"): entry for entry in entries}
    assert set(by_run) == {"review-test", "same-day-other"}
    assert by_run["review-test"]["reflection"] == "First thesis lesson"
    assert by_run["same-day-other"]["reflection"] == "Second thesis lesson"
    assert all(not entry["pending"] for entry in entries)


def test_date_ticker_outcome_fallback_applies_only_to_legacy_memory(draft):
    graph, snapshot, _ = draft
    graph.reviews.decide("review-test", **review_payload(snapshot))
    graph.memory_log.store_decision("NVDA", "2026-06-12", "**Rating**: Hold\nLegacy decision.")
    graph.memory_log.update_with_outcome("NVDA", "2026-06-12", .01, .02, 5, "Legacy reflection")
    entries = graph.memory_log.load_entries()
    legacy = next(entry for entry in entries if entry["decision"].endswith("Legacy decision."))
    approved = next(entry for entry in entries if entry["decision"] == snapshot["final_decision"])
    assert legacy["reflection"] == "Legacy reflection"
    assert approved["pending"]
    assert approved["reflection"] == ""


def test_run_outcome_never_updates_same_day_legacy_entry_and_recovers_old_sqlite_identity(draft):
    graph, snapshot, _ = draft
    graph.reviews.decide("review-test", **review_payload(snapshot))
    graph.memory_log.store_decision("NVDA", "2026-06-12", "**Rating**: Hold\nLegacy decision.")
    # Compatibility with SQLite memory written before run_id was included in its JSON.
    with graph.reviews.connect() as db:
        entry = json.loads(db.execute("SELECT entry FROM approved_memories WHERE run_id='review-test'").fetchone()[0])
        entry.pop("run_id", None)
        db.execute("UPDATE approved_memories SET entry=? WHERE run_id='review-test'", (json.dumps(entry),))
    assert graph.memory_log.get_pending_entries()[-1]["run_id"] == "review-test"
    graph.memory_log.update_with_outcome("NVDA", "2026-06-12", .03, .01, 5, "Reviewed lesson", run_id="review-test")
    entries = graph.memory_log.load_entries()
    legacy = next(entry for entry in entries if not entry.get("run_id"))
    approved = next(entry for entry in entries if entry.get("run_id") == "review-test")
    assert legacy["pending"]
    assert legacy["reflection"] == ""
    assert approved["reflection"] == "Reviewed lesson"
