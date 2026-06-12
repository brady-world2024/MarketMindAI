from __future__ import annotations

from typing import Any, Mapping

from ..graph.decision import FinalDecision
from .report_verifier import ReportVerificationIssue, ReportVerificationResult, ReportVerifier


class DecisionVerifier:
    def __init__(self) -> None:
        self.report_verifier = ReportVerifier()

    def verify(
        self,
        *,
        ticker: str,
        decision: FinalDecision,
        provisional_action: str,
        trader_plan: str,
    ) -> ReportVerificationResult:
        issues: list[ReportVerificationIssue] = []
        action = decision.action.upper()
        if decision.ticker.upper() != ticker.upper():
            issues.append(ReportVerificationIssue("fail", "ticker_mismatch", "Final decision ticker does not match the resolved symbol."))
        if action not in {"BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL", "NO_RECOMMENDATION"}:
            issues.append(ReportVerificationIssue("fail", "invalid_action", "Final decision action is outside the supported set."))
        if not (0 <= float(decision.confidence) <= 100):
            issues.append(ReportVerificationIssue("fail", "invalid_confidence", "Confidence must be between 0 and 100."))
        if not decision.evidence_gap.strip():
            issues.append(ReportVerificationIssue("fail", "missing_evidence_gap", "Every final decision must state what remains uncertain."))
        if action != "NO_RECOMMENDATION" and len(decision.evidence_items) < 2:
            issues.append(ReportVerificationIssue("fail", "insufficient_evidence", "Actionable decisions require at least two evidence items."))
        if action in {"BUY", "OVERWEIGHT", "UNDERWEIGHT", "SELL"} and all(token not in trader_plan.lower() for token in ("stop", "invalidation")):
            issues.append(ReportVerificationIssue("fail", "missing_risk_control", "Directional trade plans must include a stop or invalidation level."))
        if provisional_action == "NO_RECOMMENDATION" and action != "NO_RECOMMENDATION":
            issues.append(ReportVerificationIssue("fail", "upstream_block", "Upstream nodes declined to issue an actionable setup."))
        lowered_gap = decision.evidence_gap.lower()
        if action != "NO_RECOMMENDATION" and any(
            phrase in lowered_gap for phrase in ("cannot verify", "insufficient", "contradictory", "missing critical")
        ):
            issues.append(ReportVerificationIssue("warn", "severe_gap_language", "The evidence-gap language still sounds materially unresolved."))
        failed = any(issue.severity == "fail" for issue in issues)
        return ReportVerificationResult(
            status="failed" if failed else "passed",
            evidence_sufficient=not failed,
            blocks_actionable_recommendation=failed,
            summary="Decision blocked by verifier." if failed else "Decision passed deterministic checks.",
            issues=issues,
        )

    def verify_final_state(self, final_state: Mapping[str, Any], resolved_ticker: Any | None = None) -> ReportVerificationResult:
        return self.report_verifier.verify(final_state=final_state, resolved_ticker=resolved_ticker)
