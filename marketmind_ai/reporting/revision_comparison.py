"""Compare recorded revision content without changing either report."""

from collections import Counter
from copy import deepcopy
import json

from ..graph.review import report_hash
from ..graph.research_scope import HORIZON_LABELS, OBJECTIVE_LABELS


def _text(value):
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(
            str(item.get("claim") or item.get("statement") or "") if isinstance(item, dict) else str(item)
            for item in value
        )
    return str(value)


def _fields(snapshot):
    saved_decision = snapshot.get("final_structured_decision")
    decision = saved_decision if isinstance(saved_decision, dict) else {}
    verification = snapshot.get("report_verification") or {}
    values = {
        "decision_status": ("Decision status", decision.get("decision_status")),
        "recommendation": ("Recommendation", decision.get("rating") or snapshot.get("final_signal")),
        "executive_summary": ("Executive summary", decision.get("executive_summary")),
        "investment_thesis": ("Investment thesis", decision.get("investment_thesis")),
        "core_claims": ("Core claims", decision.get("core_claims")),
        "key_risks": ("Key risks", decision.get("key_risks")),
        "evidence_gap": ("Evidence gap", decision.get("evidence_gap")),
        "confidence": ("Model confidence", decision.get("confidence")),
        "price_target": ("Price target", decision.get("price_target")),
        "time_horizon": ("Recommendation horizon", decision.get("time_horizon")),
        "decision_text": ("Recorded decision text", snapshot.get("final_decision") if not decision else None),
        "counterargument": ("Strongest counterargument", decision.get("counterargument")),
        "counterargument_response": ("Counterargument response", decision.get("counterargument_response")),
        "data_mode": ("Data mode", snapshot.get("data_mode")),
        "verification": ("Automated checks", verification.get("status")),
        "research_objective": ("Research objective", OBJECTIVE_LABELS.get(snapshot.get("research_objective"))),
        "research_horizon": ("Requested horizon", HORIZON_LABELS.get(snapshot.get("research_horizon"))),
    }
    return {key: (label, _text(value)) for key, (label, value) in values.items()}


def _evidence_content(row):
    # IDs are local to each report. Retrieval time and the final rating's
    # supports tag do not change a quoted source or its interpretation.
    return json.dumps(
        {key: value for key, value in row.items() if key not in {"evidence_id", "retrieved_at", "supports"}},
        sort_keys=True, ensure_ascii=False,
    )


def _unmatched_evidence(rows, other):
    remaining = Counter(_evidence_content(row) for row in other)
    unmatched = []
    for row in rows:
        content = _evidence_content(row)
        if remaining[content]:
            remaining[content] -= 1
        else:
            unmatched.append(deepcopy(row))
    return unmatched


def _claim_citations(snapshot):
    decision = snapshot.get("final_structured_decision")
    if not isinstance(decision, dict):
        return [], ""
    claims = decision.get("core_claims") or []
    ledger = snapshot.get("evidence_ledger") or []
    normalized, display = [], []
    source_fields = ("source", "provider", "source_date", "url", "raw_source_id", "source_record_id", "excerpt")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        citations, lines = [], [str(claim.get("claim") or claim.get("statement") or "")]
        for identifier in dict.fromkeys(claim.get("evidence_ids") or []):
            matches = [row for row in ledger if row.get("evidence_id") == identifier]
            if not matches:
                citations.append(json.dumps({"unresolved_reference": identifier}, sort_keys=True))
                lines.append(f"Unresolved reference {identifier}")
            for row in matches:
                source = {key: row.get(key) or None for key in source_fields}
                citations.append(json.dumps(source, sort_keys=True, ensure_ascii=False))
                lines.append(str(identifier) + " · " + " · ".join(str(source[key]) for key in source_fields if source[key]))
        normalized.append(sorted(citations))
        display.append("\n".join(lines))
    return normalized, "\n\n".join(display)


def compare_revision(current, previous):
    unavailable = {"status": "unavailable", "reason": "The saved previous version could not be verified."}
    review = current.get("review") or {}
    if not isinstance(review, dict):
        return unavailable
    parent_id = review.get("parent_run_id")
    if not parent_id:
        return {"status": "not_applicable"}
    previous_review = previous.get("review") if isinstance(previous, dict) else None
    if (not isinstance(previous, dict) or previous.get("run_id") != parent_id
            or not isinstance(previous_review, dict)
            or previous_review.get("revision_run_id") != current.get("run_id")):
        return unavailable
    if any(not current.get(key) or current[key] != previous.get(key) for key in ("ticker", "analysis_date")):
        return unavailable
    for report in (current, previous):
        if (report.get("status") != "completed"
                or report_hash(report) != (report.get("review") or {}).get("report_hash")):
            return unavailable

    before, after = _fields(previous), _fields(current)
    changes = [
        {"field": key, "label": label, "before": before[key][1], "after": value}
        for key, (label, value) in after.items() if value != before[key][1]
    ]
    before_citations, before_text = _claim_citations(previous)
    after_citations, after_text = _claim_citations(current)
    if before_citations != after_citations:
        changes.append({"field": "claim_citations", "label": "Core claim citations",
                        "before": before_text, "after": after_text})
    current_evidence = current.get("evidence_ledger") or []
    previous_evidence = previous.get("evidence_ledger") or []
    added = _unmatched_evidence(current_evidence, previous_evidence)
    removed = _unmatched_evidence(previous_evidence, current_evidence)
    current_data, previous_data = current.get("data_snapshot") or {}, previous.get("data_snapshot") or {}
    identity = ("snapshot_id", "manifest_sha256")
    data_status = "unverified"
    if all(source.get(key) for source in (current_data, previous_data) for key in identity):
        data_status = "same" if all(current_data[key] == previous_data[key] for key in identity) else "different"

    def version(report):
        saved = report.get("review") or {}
        return {"run_id": report["run_id"], "version": saved.get("version"), "report_hash": saved["report_hash"]}

    return {
        "status": "available",
        "current": version(current),
        "previous": version(previous),
        "changed_fields": changes,
        "added_evidence": added,
        "removed_evidence": removed,
        "unchanged_evidence_count": len(current_evidence) - len(added),
        "data_snapshot": data_status,
    }
