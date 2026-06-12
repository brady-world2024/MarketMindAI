from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EvidenceItem:
    kind: str
    strength: str
    claim: str
    source: str
    source_date: str
    detail: str


@dataclass
class VerificationIssue:
    severity: str
    code: str
    message: str


@dataclass
class VerificationResult:
    status: str
    evidence_sufficient: bool
    blocks_actionable_recommendation: bool
    summary: str
    issues: List[VerificationIssue] = field(default_factory=list)


@dataclass
class FinalDecision:
    ticker: str
    action: str
    confidence: float
    thesis: str
    time_horizon: str
    entry_plan: str
    risk_controls: str
    evidence_gap: str
    evidence_items: List[EvidenceItem]
    rationale: str
    verifier: Optional[VerificationResult] = None
