"""Summarize recorded research reliability without rerunning data or models."""

from collections import Counter
from collections.abc import Iterable
import re

from ..agents.utils.rating import ACTIONABLE, NO_RECOMMENDATION, RATINGS_5_TIER
from ..dataflows.source_policy import DEFAULT_SOURCE_POLICY, aware_time

_REQUIRED_DATA = ("instrument", *DEFAULT_SOURCE_POLICY.required)
_DATA_MODES = ("live", "demo", "unknown")
_RUN_STATES = {"queued", "running", "completed", "error"}
_STOPPED = {"interrupted", "cancelled", "timed_out", "budget_exhausted"}
_RATINGS = {rating.lower() for rating in RATINGS_5_TIER}
_VERDICTS = {"supported", "contradicted", "insufficient"}
_USAGE_FIELDS = ("calls_started", "calls_failed", "calls_retried", "reported_input_tokens",
                 "reported_output_tokens", "reported_total_tokens", "model_elapsed_ms")


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _unique_index(rows, field, normalize=_text):
    keys = [normalize(row.get(field)) for row in rows]
    counts = Counter(keys)
    return {key: row for key, row in zip(keys, rows) if key and counts[key] == 1}


def _evidence_id(value):
    return _text(value).upper()


def _is_demo_source(record):
    return (record.get("data_mode") == "demo"
            or record.get("provider") == "offline"
            or record.get("raw_content_kind") == "demo")


def _source_traceability(record, ticker, mode, cutoff):
    published = aware_time(record.get("published_at"))
    digest = _text(record.get("raw_sha256"))
    if (record.get("admissibility") != "included"
            or record.get("data_mode") != mode
            or (mode == "live" and _is_demo_source(record))
            or record.get("symbol") != ticker
            or (published is not None and published > cutoff)
            or (digest and re.fullmatch(r"[a-f0-9]{64}", digest) is None)):
        return "untraceable"
    return "not_assessed" if published is None or not digest else "traceable"


def _claim_traceability(report, decision, records, cutoff, mode):
    counts = dict.fromkeys(("traceable", "untraceable", "not_assessed"), 0)
    claims = decision.get("core_claims")
    if not isinstance(claims, list):
        return counts
    if (mode == "unknown" or cutoff is None or not _text(report.get("ticker"))
            or not _text(_mapping(report.get("data_snapshot")).get("snapshot_id"))
            or not isinstance(report.get("source_records"), list)
            or not isinstance(report.get("evidence_ledger"), list)):
        counts["not_assessed"] = len(claims)
        return counts
    source_index = _unique_index(records, "record_id")
    evidence = _unique_index(_rows(report.get("evidence_ledger")), "evidence_id", _evidence_id)
    links = {key: _source_traceability(source_index.get(_text(row.get("raw_source_id")), {}),
                                       report["ticker"], mode, cutoff)
             for key, row in evidence.items()}
    for claim in claims:
        ids = _mapping(claim).get("evidence_ids")
        outcomes = {links.get(_evidence_id(item), "untraceable") for item in ids} if isinstance(ids, list) else set()
        if not outcomes or "untraceable" in outcomes:
            counts["untraceable"] += 1
        elif "not_assessed" in outcomes:
            counts["not_assessed"] += 1
        else:
            counts["traceable"] += 1
    return counts


def _inspect(report):
    mode = _text(report.get("data_mode"))
    mode = mode if mode in _DATA_MODES else "unknown"
    state = _text(report["status"])
    stop = _text(report.get("job_status"))
    decision = _mapping(report.get("final_structured_decision"))
    signal = _text(report.get("final_signal")).lower()
    declared = _text(decision.get("decision_status")).lower().replace("_", " ")
    actionable = declared == ACTIONABLE.lower() or signal in _RATINGS
    declined = NO_RECOMMENDATION.lower() in (declared, signal)
    if state in {"queued", "running"}:
        outcome = "in_progress"
    elif stop in _STOPPED:
        outcome = stop
    elif state == "error":
        outcome = "failed"
    elif actionable:
        outcome = "completed_actionable"
    else:
        outcome = "completed_no_recommendation" if declined else "completed_other"

    availability = _mapping(report.get("data_availability"))
    required = _mapping(availability.get("requirements"))
    missing = availability.get("missing")
    missing = missing if isinstance(missing, list) else []
    coverage = dict.fromkeys(("available", "unavailable", "not_recorded"), 0)
    for name in _REQUIRED_DATA:
        available = _mapping(required.get(name)).get("available")
        if available is False or name in missing:
            coverage["unavailable"] += 1
        elif available is True:
            coverage["available"] += 1
        else:
            coverage["not_recorded"] += 1

    records = _rows(report.get("source_records"))
    cutoff = aware_time(_mapping(report.get("research_cutoff")).get("cutoff_at"))
    verification = _mapping(report.get("report_verification"))
    audit = _mapping(_mapping(report.get("report_quality")).get("claim_audit"))
    unsupported = audit.get("unsupported_claims")
    violations, unverified = [], set()
    if mode == "unknown":
        unverified.add("unknown_data_mode")
    if cutoff is None:
        unverified.add("missing_cutoff")
    if not records:
        unverified.add("missing_source_records")
    if coverage["not_recorded"]:
        unverified.add("missing_required_data_records")
    if mode == "live":
        for record in records:
            if record.get("admissibility") != "included":
                continue
            source_id = _text(record.get("record_id")) or None
            if _is_demo_source(record):
                violations.append({"code": "demo_source_in_live_run", "record_id": source_id})
            if not _text(record.get("raw_sha256")):
                unverified.add("missing_source_digest")
            published = aware_time(record.get("published_at"))
            if published is None:
                unverified.add("unverified_source_publication_time")
            elif cutoff is not None and published > cutoff:
                violations.append({"code": "source_after_cutoff", "record_id": source_id})
    blocked_for_data = availability.get("can_recommend") is False or coverage["unavailable"] > 0
    if blocked_for_data and availability.get("ai_analysis_performed") is True:
        violations.append({"code": "analysis_without_required_data"})
    if blocked_for_data and actionable:
        violations.append({"code": "recommendation_without_required_data"})
    if verification.get("blocks_actionable_recommendation") is True and actionable:
        violations.append({"code": "recommendation_blocked_by_verification"})
    if stop in _STOPPED and (state == "completed" or actionable):
        violations.append({"code": "terminal_state_conflict"})

    started, finished = (aware_time(report.get(field)) for field in ("started_at", "finished_at"))
    elapsed = round((finished - started).total_seconds() * 1000) if started and finished and finished >= started else None
    usage = _mapping(report.get("model_usage"))
    return {
        "run_id": report["run_id"], "data_mode": mode, "outcome": outcome,
        "recovery_of_run_id": _text(report.get("recovery_of_run_id")) or None,
        "required_data": coverage, "core_claims": _claim_traceability(report, decision, records, cutoff, mode),
        "unsupported_claims": len(unsupported) if isinstance(unsupported, list) else None,
        "financial_checks": _verdict_counts(verification.get("financial_claims")),
        "qualitative_checks": _verdict_counts(verification.get("qualitative_claims")),
        "elapsed_ms": elapsed, "model_usage": {field: usage[field] for field in _USAGE_FIELDS
                                              if type(usage.get(field)) is int and usage[field] >= 0},
        "usage_possibly_incomplete": usage.get("possibly_incomplete") is True,
        "violations": violations, "unverified": sorted(unverified),
    }


def _verdict_counts(rows):
    statuses = (_text(row.get("status")) for row in _rows(rows))
    return dict(Counter(status for status in statuses if status in _VERDICTS))


def _measurement(values):
    observed = [value for value in values if value is not None]
    return {"total": sum(observed) if observed else None, "runs_reporting": len(observed)}


def _fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def _completion(outcomes):
    completed = sum(count for outcome, count in outcomes.items() if outcome.startswith("completed_"))
    terminal = sum(outcomes.values()) - outcomes.get("in_progress", 0)
    return {"completed": completed, "terminal_runs": terminal, "rate": _fraction(completed, terminal)}


def _group_summary(runs):
    outcomes = Counter(run["outcome"] for run in runs)
    recoveries = Counter(run["outcome"] for run in runs if run["recovery_of_run_id"] is not None)
    data = Counter(available=0, unavailable=0, not_recorded=0)
    claims = Counter(traceable=0, untraceable=0, not_assessed=0)
    financial, qualitative = Counter(), Counter()
    for run in runs:
        data.update(run["required_data"])
        claims.update(run["core_claims"])
        financial.update(run["financial_checks"])
        qualitative.update(run["qualitative_checks"])
    unsupported = _measurement(run["unsupported_claims"] for run in runs)
    return {
        "runs": len(runs), "outcomes": dict(outcomes),
        "completion": _completion(outcomes),
        "recovery": {"attempts": sum(recoveries.values()), "outcomes": dict(recoveries),
                     "completion": _completion(recoveries)},
        "required_data": {**data, "coverage": _fraction(data["available"], data["available"] + data["unavailable"])},
        "core_claims": {**claims, "traceability": _fraction(claims["traceable"], claims["traceable"] + claims["untraceable"])},
        "unsupported_claims": {"count": unsupported["total"], "runs_with_audit": unsupported["runs_reporting"]},
        "financial_checks": dict(financial),
        "qualitative_checks": dict(qualitative),
        "execution_time_ms": _measurement(run["elapsed_ms"] for run in runs),
        "model_usage": {field: _measurement(run["model_usage"].get(field) for run in runs) for field in _USAGE_FIELDS},
        "partial_usage_runs": sum(run["usage_possibly_incomplete"] for run in runs),
    }


def evaluate_reliability(reports: Iterable[dict]) -> dict:
    """Return measured counts and observed violations for a set of unique runs."""
    groups: dict[str, list[dict]] = {}
    seen, runs = set(), []
    for report in reports:
        if not isinstance(report, dict) or not _text(report.get("run_id")) or _text(report.get("status")) not in _RUN_STATES:
            raise ValueError("Each snapshot must have a run ID and a valid status.")
        run_id = _text(report["run_id"])
        if run_id in seen:
            raise ValueError("Duplicate run ID. Provide one snapshot per run.")
        seen.add(run_id)
        run = _inspect(report)
        runs.append(run)
        groups.setdefault(run["data_mode"], []).append(run)
    if not runs:
        raise ValueError("Provide at least one saved run snapshot.")
    return {
        "schema_version": 1,
        "by_data_mode": {mode: _group_summary(groups[mode]) for mode in _DATA_MODES if mode in groups},
        "violation_count": sum(len(run["violations"]) for run in runs),
        "runs": runs,
    }
