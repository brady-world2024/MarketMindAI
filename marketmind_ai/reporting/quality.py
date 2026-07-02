from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from .claim_audit import ClaimEvidenceAuditor


_CONFIDENCE_BUCKETS = (
    (0, 39, "0-39"),
    (40, 59, "40-59"),
    (60, 79, "60-79"),
    (80, 100, "80-100"),
)


def build_evidence_ledger(
    structured_decision: Mapping[str, Any] | Any,
    *,
    analysis_date: str,
) -> list[dict[str, Any]]:
    """Render final decision evidence into a stable, auditable ledger."""
    decision = _as_mapping(structured_decision)
    evidence = _evidence_items(decision)
    supports = "rating" if decision.get("rating") else "no_recommendation"
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(evidence, start=1):
        source_date = _text(item.get("source_date"))
        rows.append(
            {
                "evidence_id": f"E{index}",
                "claim": _text(item.get("claim")),
                "kind": _text(item.get("evidence_type") or item.get("kind")),
                "source": _text(item.get("source")),
                "source_date": source_date,
                "excerpt": _text(item.get("excerpt") or item.get("detail")),
                "interpretation": _text(item.get("interpretation")),
                "strength": _text(item.get("strength")),
                "freshness": _freshness(source_date, analysis_date),
                "supports": supports,
                "provider": _text(item.get("provider")),
                "url": _text(item.get("url") or item.get("link")),
                "source_type": _text(item.get("source_type")),
                "retrieved_at": _text(item.get("retrieved_at")),
                "raw_source_id": _text(item.get("raw_source_id")),
            }
        )
    return rows


class ReportQualityScorer:
    """Score whether a generated report is decision-grade and auditable."""

    def score(
        self,
        *,
        final_state: Mapping[str, Any],
        structured_decision: Mapping[str, Any] | Any,
        verification: Mapping[str, Any] | None = None,
        calibration_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = _as_mapping(structured_decision)
        analysis_date = _text(final_state.get("trade_date"))
        ledger = build_evidence_ledger(decision, analysis_date=analysis_date)
        claim_audit = ClaimEvidenceAuditor().audit(decision, ledger)
        dimensions = {
            "evidence_count": self._evidence_count(ledger),
            "fact_coverage": self._fact_coverage(ledger),
            "source_diversity": self._source_diversity(ledger),
            "provenance": self._provenance(ledger),
            "data_freshness": self._data_freshness(ledger),
            "risk_balance": self._risk_balance(decision),
            "verification": self._verification(verification or {}),
            "claim_support": self._claim_support(claim_audit),
            "counterargument_coverage": self._counterargument_coverage(claim_audit),
        }
        if calibration_summary is not None:
            dimensions["confidence_calibration"] = self._confidence_calibration(decision, calibration_summary)

        weights = self._weights(include_calibration=calibration_summary is not None)
        total = round(sum(dimensions[key]["score"] * weights[key] for key in dimensions))
        issues = self._issues(
            ledger,
            decision,
            verification or {},
            dimensions.get("confidence_calibration"),
            claim_audit,
        )
        grade = "Strong" if total >= 80 else "Adequate" if total >= 60 else "Weak"
        return {
            "score": int(total),
            "grade": grade,
            "summary": self._summary(grade, total),
            "dimensions": dimensions,
            "issues": issues,
            "claim_audit": claim_audit,
        }

    @staticmethod
    def _evidence_count(ledger: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(ledger)
        if count >= 3:
            score = 100
        elif count == 2:
            score = 75
        elif count == 1:
            score = 30
        else:
            score = 0
        return {"score": score, "label": "Evidence Count", "detail": f"{count} evidence items"}

    @staticmethod
    def _fact_coverage(ledger: list[dict[str, Any]]) -> dict[str, Any]:
        fact_count = sum(1 for item in ledger if item.get("kind") == "Fact")
        if not ledger:
            score = 0
        elif fact_count == len(ledger):
            score = 100
        elif fact_count > 0:
            score = 70
        else:
            score = 0
        return {"score": score, "label": "Fact Coverage", "detail": f"{fact_count} fact items"}

    @staticmethod
    def _source_diversity(ledger: list[dict[str, Any]]) -> dict[str, Any]:
        unique_sources = {item.get("source") for item in ledger if item.get("source")}
        count = len(unique_sources)
        if count >= 3:
            score = 100
        elif count == 2:
            score = 75
        elif count == 1:
            score = 35
        else:
            score = 0
        return {"score": score, "label": "Source Diversity", "detail": f"{count} unique sources"}

    @staticmethod
    def _provenance(ledger: list[dict[str, Any]]) -> dict[str, Any]:
        fields = ("provider", "url", "source_type", "retrieved_at", "raw_source_id")
        if not ledger:
            return {"score": 0, "label": "Source Provenance", "detail": "No evidence provenance"}
        total_fields = len(ledger) * len(fields)
        present_fields = sum(1 for item in ledger for field in fields if item.get(field))
        score = int(round((present_fields / total_fields) * 100)) if total_fields else 0
        return {
            "score": score,
            "label": "Source Provenance",
            "detail": f"{present_fields}/{total_fields} provenance fields present",
        }

    @staticmethod
    def _data_freshness(ledger: list[dict[str, Any]]) -> dict[str, Any]:
        if not ledger:
            return {"score": 0, "label": "Data Freshness", "detail": "No dated evidence"}
        freshness = [item.get("freshness") for item in ledger]
        if all(item == "current" for item in freshness):
            score = 100
            detail = "All dated evidence is current"
        elif any(item == "stale" for item in freshness):
            score = 35
            detail = "One or more evidence items are stale"
        elif any(item == "undated" for item in freshness):
            score = 45
            detail = "One or more evidence items are undated"
        else:
            score = 75
            detail = "Evidence is recent but not all current"
        return {"score": score, "label": "Data Freshness", "detail": detail}

    @staticmethod
    def _risk_balance(decision: Mapping[str, Any]) -> dict[str, Any]:
        risks = [item for item in decision.get("key_risks") or [] if _text(item)]
        gap = _text(decision.get("evidence_gap"))
        if risks and gap:
            score = 100
            detail = f"{len(risks)} risks and explicit evidence gap"
        elif risks or gap:
            score = 50
            detail = "Partial risk balance"
        else:
            score = 0
            detail = "No explicit risks or evidence gap"
        return {"score": score, "label": "Risk Balance", "detail": detail}

    @staticmethod
    def _verification(verification: Mapping[str, Any]) -> dict[str, Any]:
        issues = verification.get("issues") or []
        if verification.get("status") == "passed" and not issues:
            score = 100
            detail = "Deterministic verifier passed"
        elif verification.get("status") == "passed":
            score = 75
            detail = f"Verifier passed with {len(issues)} issues"
        else:
            score = 30
            detail = "Verifier did not pass cleanly"
        return {"score": score, "label": "Verification", "detail": detail}

    @staticmethod
    def _weights(*, include_calibration: bool) -> dict[str, float]:
        if include_calibration:
            return {
                "evidence_count": 0.13,
                "fact_coverage": 0.09,
                "source_diversity": 0.09,
                "provenance": 0.07,
                "data_freshness": 0.14,
                "risk_balance": 0.09,
                "verification": 0.09,
                "claim_support": 0.15,
                "counterargument_coverage": 0.07,
                "confidence_calibration": 0.08,
            }
        return {
            "evidence_count": 0.14,
            "fact_coverage": 0.10,
            "source_diversity": 0.10,
            "provenance": 0.07,
            "data_freshness": 0.15,
            "risk_balance": 0.10,
            "verification": 0.10,
            "claim_support": 0.16,
            "counterargument_coverage": 0.08,
        }

    @staticmethod
    def _claim_support(claim_audit: Mapping[str, Any]) -> dict[str, Any]:
        unsupported = len(claim_audit.get("unsupported_claims") or [])
        weak = len(claim_audit.get("weakly_supported_claims") or [])
        supported = len(claim_audit.get("supported_claims") or [])
        return {
            "score": int(claim_audit.get("claim_support_score", 0)),
            "label": "Claim Support",
            "detail": f"{supported} supported, {weak} weak, {unsupported} unsupported core claims",
        }

    @staticmethod
    def _counterargument_coverage(claim_audit: Mapping[str, Any]) -> dict[str, Any]:
        missing = claim_audit.get("missing_counterarguments") or []
        if missing:
            detail = f"Missing counterargument coverage: {', '.join(missing)}"
        else:
            detail = "Counterargument and response are present for actionable report."
        return {
            "score": int(claim_audit.get("counterargument_score", 0)),
            "label": "Counterargument Coverage",
            "detail": detail,
        }

    @staticmethod
    def _confidence_calibration(
        decision: Mapping[str, Any],
        calibration_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        confidence = _confidence_value(decision.get("confidence"))
        if confidence is None:
            return {
                "score": 45,
                "label": "Confidence Calibration",
                "detail": "No confidence score available for historical calibration.",
                "bucket": "",
                "confidence": None,
                "count": 0,
                "hit_rate": None,
                "avg_alpha_return": None,
            }

        bucket_label = _confidence_bucket_label(confidence)
        bucket = _matching_confidence_bucket(calibration_summary, bucket_label)
        count = _int_value(bucket.get("count") if bucket else None) or 0
        hit_rate = _float_value(bucket.get("hit_rate") if bucket else None)
        avg_alpha_return = _float_value(bucket.get("avg_alpha_return") if bucket else None)

        if count == 0:
            score = 55
            detail = f"Confidence {confidence} falls in bucket {bucket_label} with no resolved outcomes yet."
        else:
            hit_component = 50 if hit_rate is None else max(0, min(100, round(hit_rate * 100)))
            alpha_component = _alpha_score(avg_alpha_return)
            score = round((hit_component * 0.7) + (alpha_component * 0.3))
            if count < 3:
                score = min(score, 70)
            detail = (
                f"Confidence {confidence} falls in bucket {bucket_label} with {count} resolved outcomes, "
                f"{_format_percent(hit_rate)} hit rate, "
                f"{_format_percent(avg_alpha_return, signed=True)} average alpha."
            )

        return {
            "score": int(score),
            "label": "Confidence Calibration",
            "detail": detail,
            "bucket": bucket_label,
            "confidence": confidence,
            "count": count,
            "hit_rate": hit_rate,
            "avg_alpha_return": avg_alpha_return,
        }

    @staticmethod
    def _issues(
        ledger: list[dict[str, Any]],
        decision: Mapping[str, Any],
        verification: Mapping[str, Any],
        calibration: Mapping[str, Any] | None = None,
        claim_audit: Mapping[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        if len(ledger) < 2:
            issues.append(
                {
                    "code": "insufficient_evidence_count",
                    "message": "Decision-grade reports need at least two primary evidence items.",
                }
            )
        if any(item.get("freshness") == "stale" for item in ledger):
            issues.append(
                {
                    "code": "stale_evidence",
                    "message": "One or more evidence items are stale relative to the analysis date.",
                }
            )
        provenance_fields = ("provider", "url", "source_type", "retrieved_at", "raw_source_id")
        if any(any(not item.get(field) for field in provenance_fields) for item in ledger):
            issues.append(
                {
                    "code": "missing_source_provenance",
                    "message": "One or more evidence items are missing provider, URL, type, retrieval time, or raw source ID.",
                }
            )
        if not [item for item in decision.get("key_risks") or [] if _text(item)]:
            issues.append(
                {
                    "code": "missing_key_risks",
                    "message": "The report should state concrete risks against the thesis.",
                }
            )
        if not _text(decision.get("evidence_gap")):
            issues.append(
                {
                    "code": "missing_evidence_gap",
                    "message": "The report should state what evidence remains missing or conflicted.",
                }
            )
        if verification.get("status") and verification.get("status") != "passed":
            issues.append(
                {
                    "code": "verifier_failed",
                    "message": "The deterministic verifier did not pass cleanly.",
                }
            )
        if calibration:
            count = _int_value(calibration.get("count")) or 0
            if calibration.get("confidence") is None:
                issues.append(
                    {
                        "code": "missing_confidence_for_calibration",
                        "message": (
                            "The report needs a numeric confidence score before historical calibration can be assessed."
                        ),
                    }
                )
            elif count < 3:
                issues.append(
                    {
                        "code": "limited_confidence_history",
                        "message": "Fewer than three resolved outcomes exist for this confidence bucket.",
                    }
                )
            elif int(calibration.get("score", 0)) < 50:
                issues.append(
                    {
                        "code": "weak_confidence_calibration",
                        "message": "This confidence bucket has weak historical hit rate or alpha performance.",
                    }
                )
        if claim_audit:
            issues.extend(claim_audit.get("issues") or [])
        return issues

    @staticmethod
    def _summary(grade: str, score: int) -> str:
        if grade == "Strong":
            return f"Report quality is strong enough for decision review ({score}/100)."
        if grade == "Adequate":
            return f"Report quality is adequate but still has review gaps ({score}/100)."
        return f"Report quality is weak and should not be used without review ({score}/100)."


def _as_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return value.__dict__
    return {}


def _evidence_items(decision: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = decision.get("primary_evidence") or []
    return [_as_mapping(item) for item in items]


def _confidence_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, min(100, int(round(value))))
    text = _text(value)
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return max(0, min(100, int(round(float(match.group(0))))))
    except ValueError:
        return None


def _confidence_bucket_label(confidence: int) -> str:
    for lower, upper, label in _CONFIDENCE_BUCKETS:
        if lower <= confidence <= upper:
            return label
    return "80-100" if confidence > 100 else "0-39"


def _matching_confidence_bucket(calibration_summary: Mapping[str, Any], label: str) -> Mapping[str, Any] | None:
    buckets = calibration_summary.get("confidence_buckets") or []
    for bucket in buckets:
        if isinstance(bucket, Mapping) and _text(bucket.get("label")) == label:
            return bucket
    return None


def _float_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _alpha_score(value: float | None) -> int:
    if value is None:
        return 50
    if value >= 0.02:
        return 100
    if value > 0:
        return 75
    if value <= -0.02:
        return 20
    if value < 0:
        return 40
    return 60


def _format_percent(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    percent = value * 100
    prefix = "+" if signed and percent > 0 else ""
    return f"{prefix}{percent:.0f}%"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value).strip()


def _freshness(source_date: str, analysis_date: str) -> str:
    item_date = _parse_date(source_date)
    run_date = _parse_date(analysis_date)
    if item_date is None or run_date is None:
        return "undated"
    delta_days = (run_date - item_date).days
    if delta_days < 0:
        return "future"
    if delta_days <= 30:
        return "current"
    if delta_days <= 90:
        return "recent"
    return "stale"


def _parse_date(value: str):
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
