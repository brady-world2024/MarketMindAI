"""Measure citation admission and semantic verdicts on labeled research claims."""

from collections import Counter
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..dataflows.source_policy import aware_time
from ..dataflows.source_records import SourceRecord
from ..reporting.qualitative_verification import ClaimStatus, inspect_core_claims

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_STATUSES = get_args(ClaimStatus)


class BenchmarkSource(SourceRecord):
    record_id: Text = Field(...)


class BenchmarkEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_source_id: Text
    excerpt: Text


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: Text
    claim: Text
    evidence: list[BenchmarkEvidence] = Field(min_length=1)
    expected_model: bool = Field(strict=True)
    expected_status: ClaimStatus
    label_rationale: Text


class ClaimBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    benchmark_id: Text
    symbol: Text
    cutoff_at: Text
    source_records: list[BenchmarkSource] = Field(min_length=1)
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self):
        if aware_time(self.cutoff_at) is None:
            raise ValueError("The cutoff must include a valid date, time and UTC offset.")
        source_ids = {record.record_id for record in self.source_records}
        if len(source_ids) != len(self.source_records):
            raise ValueError("Source record IDs must be unique.")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique.")
        for case in self.cases:
            if any(item.raw_source_id not in source_ids for item in case.evidence):
                raise ValueError("Every evidence item must refer to a known source record.")
            if not case.expected_model and case.expected_status != "insufficient":
                raise ValueError("Cases blocked before the model must expect insufficient evidence.")
        return self


def read_benchmark(path: Path | None = None) -> bytes:
    if path is not None:
        return path.read_bytes()
    return files(__package__).joinpath("fixtures", "qualitative_claims_v1.json").read_bytes()


def _case_result(case, sources, benchmark, judge):
    evidence = [item.model_dump() for item in case.evidence]
    records = [sources[source_id] for source_id in dict.fromkeys(item.raw_source_id for item in case.evidence)]
    decision = {
        "core_claims": [{"claim": case.claim, "evidence_ids": [f"E{i}" for i in range(1, len(evidence) + 1)]}],
        "primary_evidence": evidence,
    }
    checks, accepted = inspect_core_claims(decision, records, benchmark.symbol, benchmark.cutoff_at,
                                          judge if case.expected_model else None)
    check, = checks
    admitted = bool(check["citations"])
    if not case.expected_model:
        state = "not_applicable"
    elif not admitted:
        state = "blocked"
    elif judge is None:
        state = "not_run"
    else:
        state = "judged" if accepted else "unavailable"
    return {
        "case_id": case.case_id, "expected_admitted": case.expected_model, "admitted": admitted,
        "expected_status": case.expected_status, "model_state": state,
        "model_status": check["status"] if accepted else None,
    }


def _rate(count, eligible):
    return {"count": count, "eligible": eligible, "rate": count / eligible if eligible else None}


def _semantic_summary(rows):
    matrix = {expected: dict.fromkeys(_STATUSES, 0) for expected in _STATUSES}
    states = Counter(row["model_state"] for row in rows if row["expected_admitted"])
    for row in rows:
        if row["model_state"] == "judged":
            matrix[row["expected_status"]][row["model_status"]] += 1
    supported = matrix["supported"]
    supported_count = sum(supported.values())
    false_accepts = matrix["contradicted"]["supported"] + matrix["insufficient"]["supported"]
    return {
        "expected": sum(states.values()),
        "judged": states["judged"],
        "unavailable": states["unavailable"],
        "not_run": states["not_run"],
        "blocked": states["blocked"],
        "confusion_matrix": matrix,
        "false_accept": _rate(false_accepts, states["judged"] - supported_count),
        "false_reject": _rate(supported_count - supported["supported"], supported_count),
    }


def evaluate_claims(benchmark: ClaimBenchmark, judge=None) -> dict:
    """Apply production citation rules and score valid verdicts against the reference labels."""
    sources = {source.record_id: source.model_dump() for source in benchmark.source_records}
    rows = [_case_result(case, sources, benchmark, judge) for case in benchmark.cases]
    return {
        "schema_version": 1,
        "benchmark_id": benchmark.benchmark_id,
        "mode": "admission_only" if judge is None else "model",
        "admission": {
            "expected_admitted": sum(row["expected_admitted"] for row in rows),
            "admitted": sum(row["admitted"] for row in rows),
            "mismatches": sum(row["expected_admitted"] != row["admitted"] for row in rows),
        },
        "semantic": _semantic_summary(rows),
        "cases": rows,
    }
