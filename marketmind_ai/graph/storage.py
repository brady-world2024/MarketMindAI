from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from ..agents.utils.memory import MarketMindMemoryLog
from ..agents.utils.research_types import MemoryEntry
from ..agents.utils.rating import NO_RECOMMENDATION
from ..config import AppPaths
from ..pathing import safe_ticker_component
from .decision import FinalDecision
from .snapshot import RunSnapshot


class RunArchive:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def save(self, snapshot: RunSnapshot) -> Path:
        path = self.paths.runs_dir / f"{snapshot.run_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_web_snapshot(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.paths.web_runs_dir / f"{run_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_state_log(self, ticker: str, analysis_date: str, state: dict[str, Any]) -> Path:
        path = self.paths.state_log_path(ticker, analysis_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> Optional[dict]:
        for directory in (self.paths.runs_dir, self.paths.web_runs_dir):
            path = directory / f"{run_id}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return None


class DecisionJournal:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.memory_log = MarketMindMemoryLog({"memory_log_path": str(paths.memory_log_path)})

    def remember(self, symbol: str, analysis_date: str, decision: FinalDecision) -> None:
        self.memory_log.store_decision(symbol, analysis_date, self._to_markdown(decision))
        payload = {
            "symbol": safe_ticker_component(symbol),
            "analysis_date": analysis_date,
            "action": decision.action,
            "confidence": decision.confidence,
            "thesis": decision.thesis,
            "outcome": "",
        }
        with self.paths.memory_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def recall(self, symbol: str, limit: int = 5) -> List[MemoryEntry]:
        symbol = safe_ticker_component(symbol)
        rows: List[MemoryEntry] = []
        for entry in self.memory_log.load_entries():
            if entry["ticker"] != symbol:
                continue
            confidence = 0.0
            decision_text = entry.get("decision", "")
            confidence_match = re.search(r"Confidence[^0-9]*(\d{1,3})", decision_text, re.IGNORECASE)
            if confidence_match:
                confidence = float(confidence_match.group(1))
            rows.append(
                MemoryEntry(
                    symbol=symbol,
                    analysis_date=str(entry["date"]),
                    action=str(entry["rating"]).upper().replace(" ", "_"),
                    confidence=confidence,
                    thesis=MarketMindMemoryLog._condense(entry.get("decision", ""), 280),
                    outcome=entry.get("reflection", "") or "",
                )
            )
        return rows[-limit:]

    @staticmethod
    def _to_markdown(decision: FinalDecision) -> str:
        rating = decision.action.replace("_", " ").title()
        parts = [
            "**Decision Status**: Actionable" if rating != NO_RECOMMENDATION else f"**Decision Status**: {NO_RECOMMENDATION}",
            "",
        ]
        if rating != NO_RECOMMENDATION:
            parts.extend([f"**Rating**: {rating}", ""])
        parts.extend(
            [
                f"**Confidence**: {int(round(decision.confidence))}/100",
                "",
                f"**Executive Summary**: {decision.entry_plan}",
                "",
                f"**Investment Thesis**: {decision.thesis}",
                "",
                f"**Evidence Gap**: {decision.evidence_gap}",
            ]
        )
        return "\n".join(parts)
