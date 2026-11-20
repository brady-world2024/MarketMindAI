from copy import deepcopy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from marketmind_ai.cli.main import app
from marketmind_ai.evaluation.reliability import evaluate_reliability


def live_report(run_id="live-ready"):
    snapshot = json.loads(Path(__file__).with_name("reliability-report-fixture.json").read_text())
    snapshot["run_id"] = run_id
    return snapshot


def blocked_report(run_id="live-missing-data"):
    report = live_report(run_id)
    report["data_availability"].update(can_recommend=False, ai_analysis_performed=False, missing=["cashflow"])
    report["data_availability"]["requirements"]["cashflow"]["available"] = False
    report.update(final_signal="No Recommendation", final_structured_decision={"decision_status": "No Recommendation"},
                  model_usage={"calls_started": 0, "reported_total_tokens": None})
    report.pop("report_verification")
    report.pop("report_quality")
    return report


def test_fixed_reports_distinguish_completion_coverage_and_measured_usage():
    ready = live_report()
    same_day = live_report("same-company-and-date")
    demo = live_report("demo-run")
    demo.update(data_mode="demo")
    demo["source_records"][0].update(data_mode="demo", provider="offline")
    unknown = {"run_id": "legacy", "status": "completed"}
    interrupted = {"run_id": "failed", "status": "error", "job_status": "interrupted", "data_mode": "live",
                   "model_usage": {"calls_started": 2, "reported_total_tokens": None, "possibly_incomplete": True}}
    sample = [ready, blocked_report(), same_day, demo, unknown, interrupted]
    before = deepcopy(sample)
    summary = evaluate_reliability(sample)
    assert sample == before
    assert evaluate_reliability(sample) == summary
    live = summary["by_data_mode"]["live"]
    assert live["runs"] == 4
    assert live["outcomes"] == {"completed_actionable": 2, "completed_no_recommendation": 1, "interrupted": 1}
    assert live["completion"] == {"completed": 3, "terminal_runs": 4, "rate": 0.75}
    assert live["required_data"] == {"available": 14, "unavailable": 1, "not_recorded": 5, "coverage": 14 / 15}
    assert live["core_claims"] == {"traceable": 2, "untraceable": 0, "not_assessed": 0, "traceability": 1.0}
    assert live["unsupported_claims"] == {"count": 0, "runs_with_audit": 2}
    assert live["model_usage"]["calls_started"] == {"total": 8, "runs_reporting": 4}
    assert live["model_usage"]["reported_total_tokens"] == {"total": 600, "runs_reporting": 2}
    assert live["partial_usage_runs"] == 1
    assert live["execution_time_ms"] == {"total": 9000, "runs_reporting": 3}
    assert summary["by_data_mode"]["demo"]["runs"] == 1
    assert summary["by_data_mode"]["unknown"]["required_data"]["coverage"] is None
    assert summary["by_data_mode"]["unknown"]["model_usage"]["calls_started"] == {"total": None, "runs_reporting": 0}
    assert summary["violation_count"] == 0
    assert "Private report claim" not in json.dumps(summary)
    assert "Saved material private" not in json.dumps(summary)


def test_report_with_future_demo_and_missing_required_material_exposes_gate_violations():
    failed = blocked_report("incomplete")
    failed["data_availability"]["ai_analysis_performed"] = True
    failed["final_signal"] = "Buy"  # A conflicting actionable field still counts.
    failed["report_verification"] = {"blocks_actionable_recommendation": True}
    failed["source_records"][0].update(data_mode="demo", provider="offline")
    failed["source_records"][1]["admissibility"] = "included"
    summary = evaluate_reliability([failed])
    assert summary["violation_count"] == 5
    assert summary["runs"][0]["run_id"] == "incomplete"
    assert {entry["code"] for entry in summary["runs"][0]["violations"]} == {
        "demo_source_in_live_run", "source_after_cutoff", "analysis_without_required_data",
        "recommendation_without_required_data", "recommendation_blocked_by_verification",
    }


def test_bad_evidence_link_is_distinct_from_unknown_metadata_and_recorded_contradiction():
    report = live_report()
    report["final_structured_decision"]["core_claims"].append({"claim":"Invalid", "evidence_ids":["E99"]})
    report["report_verification"]["qualitative_claims"].append({"status": "contradicted"})
    report["report_quality"]["claim_audit"]["unsupported_claims"] = [{"claim":"Invalid"}]
    unverifiable = live_report("unverifiable")
    unverifiable.pop("research_cutoff")
    summary = evaluate_reliability([report, unverifiable])
    live = summary["by_data_mode"]["live"]
    assert live["core_claims"] == {"traceable": 1, "untraceable": 1, "not_assessed": 1, "traceability": 0.5}
    assert live["qualitative_checks"] == {"supported": 2, "contradicted": 1}
    assert live["unsupported_claims"] == {"count": 1, "runs_with_audit": 2}
    assert "missing_cutoff" in summary["runs"][1]["unverified"]


def test_mislabeled_demo_and_conflicting_record_ids_are_not_traceable_live_sources():
    wrong_mode = live_report("demo-as-live")
    wrong_mode["source_records"][0]["provider"] = "offline"
    duplicate = live_report("ambiguous-source")
    duplicate["source_records"].append(deepcopy(duplicate["source_records"][0]))
    summary = evaluate_reliability([wrong_mode, duplicate])
    assert summary["violation_count"] == 1
    assert summary["by_data_mode"]["live"]["core_claims"]["untraceable"] == 2


@pytest.mark.parametrize(("field", "flag"), [
    ("published_at", "unverified_source_publication_time"),
    ("raw_sha256", "missing_source_digest"),
])
def test_missing_source_metadata_does_not_count_as_a_broken_link(field, flag):
    report = live_report()
    report["source_records"][0].pop(field)
    report["final_structured_decision"]["core_claims"].append({"evidence_ids": ["E1", "E99"]})
    summary = evaluate_reliability([report])
    assert summary["by_data_mode"]["live"]["core_claims"] == {
        "traceable": 0, "untraceable": 1, "not_assessed": 1, "traceability": 0.0,
    }
    assert flag in summary["runs"][0]["unverified"]


def test_financial_conflict_is_counted_in_a_correctly_downgraded_report():
    report = live_report("financial-conflict")
    report["status"] = "completed "
    report["final_signal"] = "No Recommendation"
    report["final_structured_decision"]["decision_status"] = "No Recommendation"
    report["report_verification"] = {
        "status": "blocked", "blocks_actionable_recommendation": True,
        "financial_claims": [{"status": "contradicted"}, {"status": "supported"}],
    }
    summary = evaluate_reliability([report])
    live = summary["by_data_mode"]["live"]
    assert live["outcomes"] == {"completed_no_recommendation": 1}
    assert live["financial_checks"] == {"contradicted": 1, "supported": 1}
    assert live["qualitative_checks"] == {}
    assert summary["violation_count"] == 0


def test_progress_snapshot_does_not_distort_terminal_rate_or_missing_token_measures():
    report = live_report()
    report["model_usage"]["reported_total_tokens"] = 0
    active = {"run_id": "queued", "status": "queued", "data_mode": "live",
              "started_at": "", "model_usage": {"reported_total_tokens": False}}
    live = evaluate_reliability([report, active])["by_data_mode"]["live"]
    assert live["completion"] == {"completed": 1, "terminal_runs": 1, "rate": 1.0}
    assert live["model_usage"]["reported_total_tokens"] == {"total": 0, "runs_reporting": 1}


def test_recovery_attempts_have_a_separate_completion_rate():
    success = live_report("recover-done")
    partial = blocked_report("recover-declined")
    inflight = {"run_id": "recover-running", "data_mode": "live", "status": "running"}
    stops = [
        {"run_id": f"recover-{cause}", "data_mode": "live", "status": "error", "job_status": cause}
        for cause in ("cancelled", "timed_out", "budget_exhausted", "interrupted", "failed")
    ]
    attempts = [success, partial, inflight, *stops]
    for report in attempts:
        report["recovery_of_run_id"] = "123456abcdef"
    summary = evaluate_reliability([*attempts, live_report(), {
        "run_id": "old-demo", "data_mode": "demo", "status": "completed",
    }])
    live = summary["by_data_mode"]["live"]
    assert live["recovery"] == {
        "attempts": 8,
        "outcomes": {"completed_actionable": 1, "completed_no_recommendation": 1,
                     "cancelled": 1, "timed_out": 1, "budget_exhausted": 1,
                     "interrupted": 1, "failed": 1, "in_progress": 1},
        "completion": {"completed": 2, "terminal_runs": 7, "rate": 2 / 7},
    }
    assert summary["runs"][0]["recovery_of_run_id"] == "123456abcdef"
    assert summary["runs"][len(attempts)]["recovery_of_run_id"] is None
    assert summary["by_data_mode"]["demo"]["recovery"]["completion"]["rate"] is None


def test_cli_reads_snapshot_arrays_and_signals_bad_runs_without_modifying_files(tmp_path):
    snapshots = tmp_path / "reports.json"
    failed = blocked_report()
    failed["final_signal"] = "Buy"
    document = json.dumps([live_report(), failed])
    snapshots.write_text(document)
    result = CliRunner().invoke(app, ["evaluate-reliability", str(snapshots)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["violation_count"] == 1
    assert snapshots.read_text() == document

    snapshots.write_text(json.dumps([live_report()]))
    clean = CliRunner().invoke(app, ["evaluate-reliability", str(snapshots)])
    assert clean.exit_code == 0
    assert json.loads(clean.stdout)["schema_version"] == 1
    duplicate = CliRunner().invoke(app, ["evaluate-reliability", str(snapshots), str(snapshots)])
    assert duplicate.exit_code == 2 and "Duplicate run ID" in duplicate.stderr
    snapshots.write_text("broken JSON")
    invalid = CliRunner().invoke(app, ["evaluate-reliability", str(snapshots)])
    assert invalid.exit_code == 2
    assert "broken JSON" not in invalid.output


@pytest.mark.parametrize("reports", [[], [1], [{"status": "error"}], [{"run_id": "unknown", "status": "invalid"}]])
def test_invalid_top_level_run_inputs_are_rejected(reports):
    with pytest.raises(ValueError):
        evaluate_reliability(reports)
