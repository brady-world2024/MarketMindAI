from __future__ import annotations

from typing import Any, Mapping


class ClaimEvidenceAuditor:
    """Deterministically checks whether final claims are tied to real evidence ids."""

    def audit(self, decision: Mapping[str, Any] | Any, evidence_ledger: list[Mapping[str, Any]]) -> dict[str, Any]:
        payload = _as_mapping(decision)
        valid_ids = {_text(item.get("evidence_id")).upper() for item in evidence_ledger if _text(item.get("evidence_id"))}
        core_claims = [_as_mapping(item) for item in payload.get("core_claims") or []]
        actionable = _text(payload.get("decision_status")) == "Actionable"

        supported_claims: list[dict[str, Any]] = []
        weakly_supported_claims: list[dict[str, Any]] = []
        unsupported_claims: list[dict[str, Any]] = []
        rewrite_suggestions: list[dict[str, str]] = []
        issues: list[dict[str, str]] = []

        if not core_claims:
            claim_text = _text(payload.get("investment_thesis") or payload.get("executive_summary"))
            if claim_text:
                unsupported_claims.append({"claim": claim_text, "evidence_ids": [], "invalid_evidence_ids": []})
                rewrite_suggestions.append(_rewrite_suggestion(claim_text))
            if actionable:
                issues.append(
                    {
                        "code": "unsupported_core_claim",
                        "message": "Actionable reports need explicit core claims tied to evidence ids.",
                    }
                )

        for item in core_claims:
            claim = _text(item.get("claim"))
            evidence_ids = [_text(value).upper() for value in item.get("evidence_ids") or [] if _text(value)]
            invalid_ids = [value for value in evidence_ids if value not in valid_ids]
            support_level = _text(item.get("support_level")).lower()
            row = {"claim": claim, "evidence_ids": evidence_ids, "invalid_evidence_ids": invalid_ids}
            if not claim or not evidence_ids or support_level == "unsupported" or len(invalid_ids) == len(evidence_ids):
                unsupported_claims.append(row)
                rewrite_suggestions.append(_rewrite_suggestion(claim))
                issues.append(
                    {
                        "code": "unsupported_core_claim",
                        "message": f"Core claim lacks valid evidence support: {claim}",
                    }
                )
            elif invalid_ids or support_level == "weak":
                weakly_supported_claims.append(row)
                issues.append(
                    {
                        "code": "weak_claim_support",
                        "message": f"Core claim has weak or partially invalid evidence support: {claim}",
                    }
                )
            else:
                supported_claims.append(row)

        counterargument = _text(payload.get("counterargument"))
        counterargument_response = _text(payload.get("counterargument_response"))
        counterargument_ids = [
            _text(value).upper() for value in payload.get("counterargument_evidence_ids") or [] if _text(value)
        ]
        invalid_counter_ids = [value for value in counterargument_ids if value not in valid_ids]
        missing_counterargument = actionable and not counterargument
        missing_response = actionable and not counterargument_response
        if missing_counterargument:
            issues.append(
                {
                    "code": "missing_counterargument",
                    "message": "Actionable reports should include the strongest counterargument.",
                }
            )
        if missing_response:
            issues.append(
                {
                    "code": "missing_counterargument_response",
                    "message": (
                        "Actionable reports should explain why the counterargument does or does not change "
                        "the recommendation."
                    ),
                }
            )
        if invalid_counter_ids:
            issues.append(
                {
                    "code": "weak_claim_support",
                    "message": f"Counterargument references invalid evidence ids: {', '.join(invalid_counter_ids)}.",
                }
            )

        claim_support_score = _claim_support_score(
            len(supported_claims),
            len(weakly_supported_claims),
            len(unsupported_claims),
        )
        counterargument_score = _counterargument_score(
            actionable,
            counterargument,
            counterargument_response,
            invalid_counter_ids,
        )
        severity = _severity(
            actionable=actionable,
            unsupported_count=len(unsupported_claims),
            weak_count=len(weakly_supported_claims),
            missing_counterargument=missing_counterargument,
            missing_response=missing_response,
        )

        return {
            "severity": severity,
            "claim_support_score": claim_support_score,
            "counterargument_score": counterargument_score,
            "supported_claims": supported_claims,
            "weakly_supported_claims": weakly_supported_claims,
            "unsupported_claims": unsupported_claims,
            "missing_counterarguments": [
                code
                for code, missing in (
                    ("missing_counterargument", missing_counterargument),
                    ("missing_counterargument_response", missing_response),
                )
                if missing
            ],
            "rewrite_suggestions": rewrite_suggestions,
            "issues": issues,
        }


def _claim_support_score(supported: int, weak: int, unsupported: int) -> int:
    total = supported + weak + unsupported
    if total == 0:
        return 45
    return round(((supported * 100) + (weak * 55)) / total)


def _counterargument_score(actionable: bool, counterargument: str, response: str, invalid_ids: list[str]) -> int:
    if not actionable:
        return 100
    score = 100
    if not counterargument:
        score -= 45
    if not response:
        score -= 45
    if invalid_ids:
        score -= 15
    return max(0, score)


def _severity(
    *,
    actionable: bool,
    unsupported_count: int,
    weak_count: int,
    missing_counterargument: bool,
    missing_response: bool,
) -> str:
    if actionable and unsupported_count:
        return "severe"
    if actionable and weak_count and (missing_counterargument or missing_response):
        return "severe"
    if unsupported_count or (actionable and (missing_counterargument or missing_response)):
        return "major"
    if weak_count:
        return "minor"
    return "none"


def _rewrite_suggestion(claim: str) -> dict[str, str]:
    claim_text = claim or "This claim"
    return {
        "claim": claim_text,
        "suggested_text": (
            f"Evidence does not yet prove that {claim_text.lower()}; "
            "frame this as a hypothesis needing confirmation."
        ),
    }


def _as_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return value.__dict__
    return {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value).strip()
