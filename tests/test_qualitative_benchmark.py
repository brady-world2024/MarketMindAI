import json
from importlib import import_module
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from marketmind_ai.evaluation.qualitative_benchmark import (
    ClaimBenchmark, evaluate_claims, read_benchmark,
)

cli_module = import_module("marketmind_ai.cli.main")


@pytest.fixture
def benchmark():
    return ClaimBenchmark.model_validate_json(read_benchmark())


def test_default_benchmark_checks_admission_without_measuring_model_accuracy(benchmark):
    result = evaluate_claims(benchmark)
    assert result == evaluate_claims(benchmark)
    assert result["admission"] == {"expected_admitted": 12, "admitted": 12, "mismatches": 0}
    assert {row["case_id"] for row in result["cases"] if not row["admitted"]} == {
        "after-close", "date-without-time", "different-issuer", "fabricated-excerpt",
    }
    assert result["semantic"]["judged"] == 0
    assert result["semantic"]["not_run"] == 12
    assert result["semantic"]["false_accept"] == {"count": 0, "eligible": 0, "rate": None}
    assert result["semantic"]["false_reject"] == {"count": 0, "eligible": 0, "rate": None}


def test_fixed_judgments_distinguish_errors_and_missing_predictions(benchmark):
    by_claim = {case.claim: case for case in benchmark.cases}

    def judge(claims):
        claim, = claims
        case = by_claim[claim["claim"]]
        assert case.expected_model
        assert set(claim) == {"claim", "claim_number", "citations"}
        assert "label_rationale" not in json.dumps(claim)
        if case.case_id == "logo-unrelated":
            raise RuntimeError("secret diagnostic")
        status = {"shipment-opposite": "supported", "plant-closure-zh": "insufficient"}.get(
            case.case_id, case.expected_status,
        )
        return [{"claim_number": 1, "status": status, "reason": "Fixture prediction."}]

    result = evaluate_claims(benchmark, judge=judge)
    semantic = result["semantic"]
    assert semantic["judged"] == 11 and semantic["unavailable"] == 1 and semantic["not_run"] == 0
    assert semantic["false_accept"] == {"count": 1, "eligible": 7, "rate": 1 / 7}
    assert semantic["false_reject"] == {"count": 1, "eligible": 4, "rate": 1 / 4}
    assert semantic["confusion_matrix"]["contradicted"]["supported"] == 1
    assert semantic["confusion_matrix"]["supported"]["insufficient"] == 1
    assert {row["case_id"] for row in result["cases"] if row["model_state"] == "unavailable"} == {"logo-unrelated"}
    assert "secret diagnostic" not in json.dumps(result)


@pytest.mark.parametrize("failure", [[], [{"claim_number": 2, "status": "supported", "reason": "Wrong claim"}],
                                     [{"claim_number": 1, "status": "supported", "reason": " "}]],
                         ids=["omitted", "wrong_claim", "blank_reason"])
def test_invalid_verdicts_do_not_become_semantic_predictions(benchmark, failure):
    result = evaluate_claims(benchmark, judge=lambda _: failure)
    assert result["semantic"]["judged"] == 0
    assert result["semantic"]["unavailable"] == 12
    assert result["semantic"]["false_reject"]["rate"] is None


@pytest.mark.parametrize("corruption", [
    "duplicate_case", "duplicate_source", "unknown_source", "invalid_version",
    "label_blank", "no_cases", "naive_cutoff",
])
def test_invalid_benchmark_is_rejected_before_model_initialization(tmp_path, monkeypatch, corruption):
    benchmark = json.loads(read_benchmark())
    if corruption == "duplicate_case":
        benchmark["cases"].append(benchmark["cases"][0])
    elif corruption == "duplicate_source":
        benchmark["source_records"].append(benchmark["source_records"][0])
    elif corruption == "unknown_source":
        benchmark["cases"][0]["evidence"][0]["raw_source_id"] = "unknown"
    elif corruption == "invalid_version":
        benchmark["schema_version"] = 2
    elif corruption == "label_blank":
        benchmark["cases"][0]["label_rationale"] = " "
    elif corruption == "no_cases":
        benchmark["cases"] = []
    else:
        benchmark["cutoff_at"] = "2026-06-12"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(benchmark), encoding="utf-8")
    factory = Mock(side_effect=AssertionError("No model should be constructed"))
    monkeypatch.setattr(cli_module, "build_research_model", factory)
    result = CliRunner().invoke(cli_module.app, [
        "evaluate-claims", str(source), "--provider", "openai", "--model", "fixture",
    ])
    assert result.exit_code == 2
    assert "Invalid benchmark" in result.stderr
    factory.assert_not_called()


def test_cli_offline_and_explicit_model_modes_use_the_same_admission(monkeypatch):
    class FixtureModel:
        def with_structured_output(self, schema):
            assert schema.__name__ == "ClaimVerdicts"
            return self

        def invoke(self, messages):
            system, user = messages
            assert "Only the supplied citations may support a claim" in system.content
            payload = json.loads(user.content)
            assert set(payload) == {"symbol", "claims"} and payload["symbol"] == "EXAMPLE"
            claim, = payload["claims"]
            assert set(claim) == {"claim_number", "claim", "citations"}
            return {"verdicts": [{"claim_number": 1, "status": "insufficient", "reason": "Fixture response"}]}

    factory = Mock(return_value=FixtureModel())
    monkeypatch.setattr(cli_module, "build_research_model", factory)
    runner = CliRunner()
    offline = runner.invoke(cli_module.app, ["evaluate-claims"])
    assert offline.exit_code == 0, offline.output
    assert runner.invoke(cli_module.app, ["evaluate-claims"]).stdout == offline.stdout
    factory.assert_not_called()
    assert runner.invoke(cli_module.app, ["evaluate-claims", "--provider", "openai"]).exit_code == 2
    live = runner.invoke(cli_module.app, ["evaluate-claims", "--provider", "openai", "--model", "fixture"])
    assert live.exit_code == 0, live.output
    factory.assert_called_once()
    live_result, offline_result = json.loads(live.stdout), json.loads(offline.stdout)
    assert live_result["benchmark_sha256"] == offline_result["benchmark_sha256"]
    assert live_result["admission"] == offline_result["admission"]
    assert live_result["semantic"]["judged"] == 12
    assert live_result["semantic"]["false_reject"]["rate"] == 1
    assert live_result["model_usage"]["calls_started"] == 12


def test_cli_surfaces_admission_regressions_and_partial_model_runs(benchmark, tmp_path, monkeypatch):
    modified = json.loads(read_benchmark())
    future = next(source for source in modified["source_records"] if source["record_id"] == "future")
    future["published_at"] = "2026-06-12T19:59:59Z"
    source = tmp_path / "changed.json"
    source.write_text(json.dumps(modified), encoding="utf-8")
    runner = CliRunner()
    regression = runner.invoke(cli_module.app, ["evaluate-claims", str(source)])
    assert regression.exit_code == 1
    assert json.loads(regression.stdout)["admission"]["mismatches"] == 1

    model = Mock()
    model.with_structured_output.return_value = model
    model.invoke.side_effect = RuntimeError("secret connection failure")
    monkeypatch.setattr(cli_module, "build_research_model", lambda *_: model)
    partial = runner.invoke(cli_module.app, ["evaluate-claims", "--provider", "openai", "--model", "fixture"])
    assert partial.exit_code == 1
    assert json.loads(partial.stdout)["semantic"]["unavailable"] == 12
    assert "secret" not in partial.output
