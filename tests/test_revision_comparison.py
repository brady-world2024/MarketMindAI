from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.graph.review import ReviewStore, report_hash
from marketmind_ai.reporting.revision_comparison import compare_revision
from marketmind_ai.web.app import create_app


def reports():
    original = json.loads((Path(__file__).parent / "claim-evidence-fixture.json").read_text())
    original["run_id"] = "parent-run"
    original["data_snapshot"]["manifest_sha256"] = "b" * 64
    revised = deepcopy(original)
    revised["run_id"] = "child-run"
    revised["final_structured_decision"]["executive_summary"] = "The revised summary. <script>text</script>"
    revised["final_structured_decision"]["key_risks"] = ["A different recorded risk."]
    original["review"] = {"version": 1, "report_hash": report_hash(original), "revision_run_id": "child-run"}
    revised["review"] = {"version": 2, "report_hash": report_hash(revised), "parent_run_id": "parent-run"}
    return original, revised


def test_comparison_records_fields_without_changing_reports():
    original, revised = reports()
    before = deepcopy((original, revised))
    result = compare_revision(revised, original)
    assert result["status"] == "available"
    assert result["previous"]["run_id"] == "parent-run"
    assert result["current"]["report_hash"] == revised["review"]["report_hash"]
    assert {row["field"] for row in result["changed_fields"]} == {"executive_summary", "key_risks"}
    assert result["data_snapshot"] == "same"
    assert result["added_evidence"] == result["removed_evidence"] == []
    assert (original, revised) == before


def test_evidence_renumbering_is_not_a_content_change_and_duplicates_count():
    original, revised = reports()
    revised["evidence_ledger"] = list(reversed(revised["evidence_ledger"]))
    renumbered = {}
    for index, row in enumerate(revised["evidence_ledger"], 1):
        renumbered[row["evidence_id"]] = f"E{index}"
        row.update(evidence_id=f"E{index}", retrieved_at="2026-07-01T10:00:00Z")
    for claim in revised["final_structured_decision"]["core_claims"]:
        claim["evidence_ids"] = [renumbered.get(item, item) for item in claim["evidence_ids"]]
    revised["review"]["report_hash"] = report_hash(revised)
    result = compare_revision(revised, original)
    assert result["added_evidence"] == result["removed_evidence"] == []
    revised["evidence_ledger"].append(deepcopy(revised["evidence_ledger"][0]))
    revised["review"]["report_hash"] = report_hash(revised)
    result = compare_revision(revised, original)
    assert len(result["added_evidence"]) == 1 and result["removed_evidence"] == []


def test_changing_a_claim_to_another_existing_source_is_visible():
    original, revised = reports()
    revised["final_structured_decision"]["core_claims"][0]["evidence_ids"] = ["E2"]
    revised["review"]["report_hash"] = report_hash(revised)
    result = compare_revision(revised, original)
    assert result["added_evidence"] == result["removed_evidence"] == []
    change = next(row for row in result["changed_fields"] if row["field"] == "claim_citations")
    assert "Revenue 110" in change["before"]
    assert change["before"] != change["after"]


def test_changed_quote_retains_old_and_new_evidence():
    original, revised = reports()
    revised["evidence_ledger"][0]["excerpt"] = "Revenue 120"
    revised["review"]["report_hash"] = report_hash(revised)
    result = compare_revision(revised, original)
    assert result["added_evidence"][0]["excerpt"] == "Revenue 120"
    assert result["removed_evidence"][0]["excerpt"] == "Revenue 110"


def test_legacy_decision_text_changes_are_visible():
    original, revised = reports()
    for report in (original, revised):
        report.pop("final_structured_decision")
    revised["final_decision"] = "A different legacy conclusion."
    for report in (original, revised):
        report["review"]["report_hash"] = report_hash(report)
    changes = compare_revision(revised, original)["changed_fields"]
    assert any(row["field"] == "decision_text" and row["after"] == revised["final_decision"] for row in changes)


@pytest.mark.parametrize("change", ["missing", "wrong_parent", "wrong_child", "tampered", "wrong_company", "malformed_review"])
def test_unavailable_parent_or_integrity_never_produces_a_diff(change):
    original, revised = reports()
    if change == "missing":
        original = None
    elif change == "wrong_parent":
        original["run_id"] = "unrelated-run"
    elif change == "wrong_child":
        original["review"]["revision_run_id"] = "another-child"
    elif change == "wrong_company":
        revised["ticker"] = "XYZ"
        revised["review"]["report_hash"] = report_hash(revised)
    elif change == "malformed_review":
        original["review"] = ["corrupt"]
    else:
        revised["final_signal"] = "Sell"
    result = compare_revision(revised, original)
    assert result["status"] == "unavailable" and result["reason"]
    assert not result.get("changed_fields")


def test_initial_report_and_unknown_data_version_are_explicit():
    original, revised = reports()
    assert compare_revision(original, None)["status"] == "not_applicable"
    del revised["data_snapshot"]["manifest_sha256"]
    revised["review"]["report_hash"] = report_hash(revised)
    assert compare_revision(revised, original)["data_snapshot"] == "unverified"
    revised["data_snapshot"].update(snapshot_id="c" * 32, manifest_sha256="d" * 64)
    revised["review"]["report_hash"] = report_hash(revised)
    assert compare_revision(revised, original)["data_snapshot"] == "different"


def test_api_and_export_share_durable_comparison_without_model_calls(tmp_path, monkeypatch):
    store = ReviewStore(tmp_path / "reviews.sqlite3")
    original, revised = reports()
    request = AnalysisRequest("ABC", "2026-06-12", llm_provider="offline")
    original = store.save_draft(original, request, {})
    review = original["review"]
    store.decide("parent-run", decision="request_changes", version=review["version"],
                 report_hash=review["report_hash"], reviewer="Tester", comment="Clarify the risk")
    child_id, payload = store.reserve_revision("parent-run", version=review["version"], report_hash=review["report_hash"])
    revised["run_id"] = child_id
    revised = store.save_draft(revised, payload, {})
    before = deepcopy((store.load("parent-run"), store.load(child_id)))
    stream = Mock(side_effect=AssertionError("Comparison must be read-only"))
    monkeypatch.setattr("marketmind_ai.graph.marketmind_graph.MarketMindGraph.stream", stream)
    client = TestClient(create_app(str(tmp_path)))
    response = client.get(f"/api/runs/{child_id}/comparison")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "available" and result["current"]["run_id"] == child_id
    html = client.get(f"/api/runs/{child_id}/report").text
    assert "Changes from previous version" in html and "A different recorded risk." in html
    assert revised["review"]["report_hash"] in html and review["report_hash"] in html
    assert "&lt;script&gt;text&lt;/script&gt;" in html and "<script>text</script>" not in html
    assert (store.load("parent-run"), store.load(child_id)) == before
    assert client.get("/api/runs/unknown/comparison").status_code == 404
    stream.assert_not_called()
    with store.connect() as db:
        db.execute("UPDATE review_runs SET snapshot=? WHERE run_id=?", ("broken JSON", "parent-run"))
    assert client.get(f"/api/runs/{child_id}/comparison").json()["status"] == "unavailable"
    exported = client.get(f"/api/runs/{child_id}/report")
    assert exported.status_code == 200 and "could not be verified" in exported.text
    original["review"] = ["corrupt"]
    with store.connect() as db:
        db.execute("UPDATE review_runs SET snapshot=? WHERE run_id=?", (json.dumps(original), "parent-run"))
    assert client.get(f"/api/runs/{child_id}/comparison").json()["status"] == "unavailable"
    assert client.get(f"/api/runs/{child_id}/report").status_code == 200
