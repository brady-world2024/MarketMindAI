"""Deterministic checks for final portfolio reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Any, Mapping, Optional

from ..agents.utils.rating import (
    ACTIONABLE,
    NO_RECOMMENDATION,
    parse_confidence,
    parse_decision_status,
    parse_rating,
)


_RATING_LABEL_RE = re.compile(r"^\s*\*{0,2}Rating\*{0,2}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_EVIDENCE_GAP_RE = re.compile(r"^\s*\*{0,2}Evidence Gap\*{0,2}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DATE_EXACT_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_EVIDENCE_LINE_RE = re.compile(
    r"^\s*\d+\.\s+\[(?P<strength>[^\]]+)\]\[(?P<kind>[^\]]+)\]\s+"
    r"Claim:\s*(?P<claim>.*?)\s+\|\s+Source:\s*(?P<source>.*?)\s+\|\s+"
    r"Date:\s*(?P<source_date>.*?)\s+\|\s+Excerpt:\s*(?P<excerpt>.*?)\s+\|\s+"
    r"Interpretation:\s*(?P<interpretation>.*?)\s*$",
    re.MULTILINE,
)


@dataclass(slots=True)
class ReportVerificationIssue:
    severity: str
    code: str
    message: str


@dataclass(slots=True)
class ReportVerificationResult:
    status: str
    evidence_sufficient: bool
    blocks_actionable_recommendation: bool
    summary: str
    issues: list[ReportVerificationIssue] = field(default_factory=list)
    checked_fields: list[str] = field(
        default_factory=lambda: [
            "ticker",
            "decision_status",
            "rating",
            "confidence",
            "evidence_pack",
            "evidence_gap",
            "evidence_dates",
            "upstream_alignment",
        ]
    )
    original_rating: Optional[str] = None
    original_decision_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


class ReportVerifier:
    def verify(
        self,
        *,
        final_state: Mapping[str, Any],
        resolved_ticker: Any | None = None,
    ) -> ReportVerificationResult:
        text = str(final_state.get("final_trade_decision") or "")
        if not text.strip():
            text = str(final_state.get("pre_verifier_final_trade_decision") or "")
        trade_date = str(final_state.get("trade_date") or "")
        company = str(final_state.get("company_of_interest") or "")
        resolved_symbol = self._resolved_symbol(resolved_ticker) or company

        issues: list[ReportVerificationIssue] = []
        if not text.strip():
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="missing_final_decision",
                    message="The final portfolio report is empty.",
                )
            )
            return self._build_result(issues=issues, evidence_sufficient=False, decision_status=None, rating=None)

        decision_status = parse_decision_status(text)
        rating = parse_rating(text)
        confidence = parse_confidence(text)
        has_rating_label = self._extract_rating_label(text) is not None
        evidence_gap = self._extract_evidence_gap(text)
        evidence_items = self._parse_evidence_items(text)

        if resolved_symbol and company and resolved_symbol != company:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="ticker_mismatch",
                    message=f"Resolved symbol {resolved_symbol} does not match report state ticker {company}.",
                )
            )

        if decision_status == ACTIONABLE and not has_rating_label:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="missing_rating",
                    message="Actionable final decisions must include an explicit rating.",
                )
            )

        if decision_status == NO_RECOMMENDATION and has_rating_label:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="no_recommendation_with_rating",
                    message="No Recommendation outputs must not include a directional rating.",
                )
            )

        if confidence is None:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="missing_confidence",
                    message="The final report is missing an explicit confidence score.",
                )
            )

        if not evidence_gap:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="missing_evidence_gap",
                    message="The final report must explain what evidence is still missing or conflicted.",
                )
            )

        if not evidence_items:
            issues.append(
                ReportVerificationIssue(
                    severity="fail",
                    code="missing_evidence_pack",
                    message="The final report does not contain a parseable primary evidence pack.",
                )
            )

        fact_evidence_count = sum(1 for item in evidence_items if item["kind"].lower() == "fact")

        if decision_status == ACTIONABLE:
            if len(evidence_items) < 2:
                issues.append(
                    ReportVerificationIssue(
                        severity="fail",
                        code="insufficient_evidence_items",
                        message="Actionable final decisions require at least two evidence items.",
                    )
                )
            if fact_evidence_count < 1:
                issues.append(
                    ReportVerificationIssue(
                        severity="fail",
                        code="missing_fact_evidence",
                        message="Actionable final decisions require at least one fact-based evidence item.",
                    )
                )
            if confidence is not None and rating not in {None, "Hold", NO_RECOMMENDATION} and confidence < 50:
                issues.append(
                    ReportVerificationIssue(
                        severity="fail",
                        code="low_confidence_directional_call",
                        message="Directional final decisions below 50 confidence must be downgraded.",
                    )
                )

        upstream_plan = str(final_state.get("investment_plan") or "")
        upstream_trader = str(final_state.get("trader_investment_plan") or "")
        if decision_status == ACTIONABLE:
            if parse_decision_status(upstream_plan) == NO_RECOMMENDATION:
                issues.append(
                    ReportVerificationIssue(
                        severity="fail",
                        code="research_manager_no_recommendation",
                        message="The Research Manager marked the setup as No Recommendation, so the final decision cannot become actionable yet.",
                    )
                )
            if parse_decision_status(upstream_trader) == NO_RECOMMENDATION:
                issues.append(
                    ReportVerificationIssue(
                        severity="fail",
                        code="trader_no_recommendation",
                        message="The Trader marked the setup as No Recommendation, so the final decision cannot become actionable yet.",
                    )
                )

        parsed_trade_date = self._parse_exact_date(trade_date)
        if parsed_trade_date is not None:
            for item in evidence_items:
                item_date = self._parse_exact_date(item["source_date"])
                if item_date and item_date > parsed_trade_date:
                    issues.append(
                        ReportVerificationIssue(
                            severity="fail",
                            code="future_dated_evidence",
                            message=f"Evidence dated {item['source_date']} is after the analysis date {trade_date}.",
                        )
                    )

        if decision_status == ACTIONABLE and evidence_gap:
            if any(keyword in evidence_gap.lower() for keyword in ("cannot verify", "missing critical", "insufficient", "not enough evidence")):
                issues.append(
                    ReportVerificationIssue(
                        severity="warn",
                        code="actionable_with_severe_gap_language",
                        message="The report is still actionable, but the evidence-gap text sounds materially unresolved.",
                    )
                )

        evidence_sufficient = not any(issue.severity == "fail" for issue in issues)
        return self._build_result(
            issues=issues,
            evidence_sufficient=evidence_sufficient,
            decision_status=decision_status,
            rating=rating,
        )

    @staticmethod
    def _resolved_symbol(resolved_ticker: Any | None) -> str | None:
        if resolved_ticker is None:
            return None
        if isinstance(resolved_ticker, dict):
            return str(resolved_ticker.get("resolved_symbol") or "") or None
        return getattr(resolved_ticker, "resolved_symbol", None)

    @staticmethod
    def _parse_evidence_items(text: str) -> list[dict[str, str]]:
        rows = []
        for match in _EVIDENCE_LINE_RE.finditer(text or ""):
            rows.append(
                {
                    "strength": match.group("strength").strip(),
                    "kind": match.group("kind").strip(),
                    "claim": match.group("claim").strip(),
                    "source": match.group("source").strip(),
                    "source_date": match.group("source_date").strip(),
                    "excerpt": match.group("excerpt").strip(),
                    "interpretation": match.group("interpretation").strip(),
                }
            )
        return rows

    @staticmethod
    def _extract_rating_label(text: str) -> Optional[str]:
        match = _RATING_LABEL_RE.search(text or "")
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_evidence_gap(text: str) -> str:
        match = _EVIDENCE_GAP_RE.search(text or "")
        return match.group(1).strip() if match else ""

    @staticmethod
    def _parse_exact_date(text: str):
        match = _DATE_EXACT_RE.search(text or "")
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _build_result(
        *,
        issues: list[ReportVerificationIssue],
        evidence_sufficient: bool,
        decision_status: Optional[str],
        rating: Optional[str],
    ) -> ReportVerificationResult:
        failed = any(issue.severity == "fail" for issue in issues)
        return ReportVerificationResult(
            status="failed" if failed else "passed",
            evidence_sufficient=evidence_sufficient,
            blocks_actionable_recommendation=failed,
            summary="Decision blocked by verifier." if failed else "Decision passed deterministic checks.",
            issues=issues,
            original_rating=rating,
            original_decision_status=decision_status,
        )
