from __future__ import annotations

from typing import Any, Mapping

from ..agents.utils.rating import NO_RECOMMENDATION, parse_rating


class SignalProcessor:
    def __init__(self, quick_thinking_llm: Any = None):
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str, verification: Mapping[str, Any] | None = None) -> str:
        if verification:
            if bool(verification.get("blocks_actionable_recommendation")):
                return NO_RECOMMENDATION
            if str(verification.get("status", "")).lower() in {"fail", "failed"}:
                return NO_RECOMMENDATION
        return parse_rating(full_signal)
