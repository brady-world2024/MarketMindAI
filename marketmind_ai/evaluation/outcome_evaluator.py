"""Outcome evaluation and lightweight backtesting over resolved memory-log entries."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..agents.utils.rating import NO_RECOMMENDATION, RATINGS_5_TIER, parse_confidence, parse_rating


logger = logging.getLogger(__name__)


class OutcomeEvaluator:
    _CONFIDENCE_BUCKETS = (
        (0, 39, "0-39"),
        (40, 59, "40-59"),
        (60, 79, "60-79"),
        (80, 100, "80-100"),
    )

    def __init__(self, config: dict[str, Any] | None, memory_log: Any):
        self.config = config or {}
        self.memory_log = memory_log
        path = self.config.get("evaluation_summary_path")
        self.summary_path = Path(path).expanduser() if path else None
        self.hold_band = float(self.config.get("evaluation_hold_band", 0.02))
        self.last_write_error: Optional[str] = None

    def build_summary(self) -> dict[str, Any]:
        entries = list(self.memory_log.load_entries())
        pending_entries = sum(1 for entry in entries if entry.get("pending"))

        resolved_records = []
        for entry in entries:
            if entry.get("pending"):
                continue

            raw_return = self._parse_percent(entry.get("raw"))
            alpha_return = self._parse_percent(entry.get("alpha"))
            if raw_return is None or alpha_return is None:
                continue

            decision_text = entry.get("decision", "")
            signal = parse_rating(decision_text)
            confidence = parse_confidence(decision_text)
            correct = self._is_correct(signal, alpha_return)
            resolved_records.append(
                {
                    "date": entry.get("date"),
                    "ticker": entry.get("ticker"),
                    "signal": signal,
                    "confidence": confidence,
                    "raw_return": raw_return,
                    "alpha_return": alpha_return,
                    "correct": correct,
                }
            )

        actionable_records = [record for record in resolved_records if record["correct"] is not None]
        no_recommendation_count = sum(1 for record in resolved_records if record["signal"] == NO_RECOMMENDATION)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_entries": len(entries),
            "pending_entries": pending_entries,
            "resolved_entries": len(resolved_records),
            "actionable_entries": len(actionable_records),
            "no_recommendation_entries": no_recommendation_count,
            "avg_raw_return": self._average(record["raw_return"] for record in resolved_records),
            "avg_alpha_return": self._average(record["alpha_return"] for record in resolved_records),
            "actionable_hit_rate": self._average(1.0 if record["correct"] else 0.0 for record in actionable_records),
            "average_confidence": self._average(
                record["confidence"] for record in resolved_records if record["confidence"] is not None
            ),
            "signal_breakdown": self._build_signal_breakdown(resolved_records),
            "confidence_buckets": self._build_confidence_buckets(resolved_records),
        }

    def write_summary(self) -> dict[str, Any]:
        summary = self.build_summary()
        if self.summary_path is None:
            return summary

        try:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            self.last_write_error = None
        except OSError as exc:
            self.last_write_error = str(exc)
            summary["write_error"] = self.last_write_error
            logger.warning("Could not write evaluation summary to %s: %s", self.summary_path, exc)
        return summary

    def _build_signal_breakdown(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        breakdown = []
        for signal in (*RATINGS_5_TIER, NO_RECOMMENDATION):
            group = [record for record in records if record["signal"] == signal]
            if not group:
                continue
            actionable_group = [record for record in group if record["correct"] is not None]
            breakdown.append(
                {
                    "signal": signal,
                    "count": len(group),
                    "hit_rate": self._average(1.0 if record["correct"] else 0.0 for record in actionable_group),
                    "avg_alpha_return": self._average(record["alpha_return"] for record in group),
                }
            )
        return breakdown

    def _build_confidence_buckets(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets = []
        for lower, upper, label in self._CONFIDENCE_BUCKETS:
            group = [
                record
                for record in records
                if record["confidence"] is not None and lower <= record["confidence"] <= upper
            ]
            actionable_group = [record for record in group if record["correct"] is not None]
            buckets.append(
                {
                    "label": label,
                    "count": len(group),
                    "hit_rate": self._average(1.0 if record["correct"] else 0.0 for record in actionable_group),
                    "avg_alpha_return": self._average(record["alpha_return"] for record in group),
                }
            )
        return buckets

    def _is_correct(self, signal: str, alpha_return: float) -> Optional[bool]:
        if signal in {"Buy", "Overweight"}:
            return alpha_return > 0
        if signal in {"Sell", "Underweight"}:
            return alpha_return < 0
        if signal == "Hold":
            return abs(alpha_return) <= self.hold_band
        if signal == NO_RECOMMENDATION:
            return None
        return None

    @staticmethod
    def _parse_percent(value: Any) -> Optional[float]:
        if value in (None, "", "n/a"):
            return None
        text = str(value).strip().replace("%", "")
        try:
            return float(text) / 100.0
        except ValueError:
            return None

    @staticmethod
    def _average(values) -> Optional[float]:
        values = [value for value in values if value is not None]
        if not values:
            return None
        return sum(values) / len(values)
