from __future__ import annotations

from pathlib import Path
import re
from typing import Any, List

from ...pathing import safe_ticker_component
from .rating import NO_RECOMMENDATION, parse_rating


class MarketMindMemoryLog:
    _SEPARATOR = "\n\n<!-- MARKETMIND_ENTRY_END -->\n\n"
    _TAG_RE = re.compile(r"^\[(?P<body>.+?)\]$")

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        raw_path = cfg.get("memory_log_path")
        self._log_path = Path(raw_path).expanduser() if raw_path else None
        self._max_entries = int(cfg.get("memory_log_max_entries", 0) or 0)
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path | None:
        return self._log_path

    def store_decision(self, ticker: str, trade_date: str, final_trade_decision: str) -> None:
        if self._log_path is None:
            return
        rating = parse_rating(final_trade_decision)
        tag = f"[{trade_date} | {safe_ticker_component(ticker)} | {rating} | pending]"
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            if tag in raw:
                return
        entry = f"{tag}\n\nDECISION:\n{final_trade_decision.strip()}{self._SEPARATOR}"
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)

    def load_entries(self) -> List[dict[str, Any]]:
        if self._log_path is None or not self._log_path.exists():
            return []
        raw = self._log_path.read_text(encoding="utf-8")
        blocks = [block.strip() for block in raw.split(self._SEPARATOR) if block.strip()]
        entries: List[dict[str, Any]] = []
        for block in blocks:
            parsed = self._parse_entry(block)
            if parsed is not None:
                entries.append(parsed)
        return entries

    def get_pending_entries(self) -> List[dict[str, Any]]:
        return [entry for entry in self.load_entries() if entry.get("pending")]

    def get_past_context(self, ticker: str, n_same: int = 5, n_cross: int = 3) -> str:
        resolved = [entry for entry in self.load_entries() if not entry.get("pending")]
        if not resolved:
            return ""
        safe_ticker = safe_ticker_component(ticker)
        same = [entry for entry in reversed(resolved) if entry["ticker"] == safe_ticker][:n_same]
        cross = [entry for entry in reversed(resolved) if entry["ticker"] != safe_ticker][:n_cross]
        parts = []
        if same:
            parts.append(f"Past analyses of {safe_ticker} (most recent first):")
            for entry in same:
                parts.append(
                    f"- {entry['date']} | {entry['rating']} | raw={entry.get('raw') or 'n/a'} | alpha={entry.get('alpha') or 'n/a'} | "
                    f"Decision: {self._condense(entry.get('decision', ''))}"
                )
                reflection = self._condense(entry.get("reflection", ""))
                if reflection:
                    parts.append(f"  Reflection: {reflection}")
        if cross:
            parts.append("Recent cross-ticker lessons:")
            for entry in cross:
                reflection = self._condense(entry.get("reflection", "") or entry.get("decision", ""))
                parts.append(f"- {entry['ticker']} {entry['date']}: {reflection}")
        return "\n".join(parts).strip()

    def update_with_outcome(
        self,
        ticker: str,
        trade_date: str,
        raw_return: float,
        alpha_return: float,
        holding_days: int,
        reflection: str,
    ) -> None:
        self.batch_update_with_outcomes(
            [
                {
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "raw_return": raw_return,
                    "alpha_return": alpha_return,
                    "holding_days": holding_days,
                    "reflection": reflection,
                }
            ]
        )

    def batch_update_with_outcomes(self, updates: List[dict[str, Any]]) -> None:
        if self._log_path is None or not self._log_path.exists() or not updates:
            return
        raw = self._log_path.read_text(encoding="utf-8")
        blocks = raw.split(self._SEPARATOR)
        update_map = {
            (str(item["trade_date"]), safe_ticker_component(item["ticker"])): item
            for item in updates
        }
        changed = False
        new_blocks: list[str] = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue
            lines = stripped.splitlines()
            tag_line = lines[0].strip()
            parsed_tag = self._parse_tag_line(tag_line)
            if parsed_tag is None:
                new_blocks.append(block)
                continue
            key = (parsed_tag["date"], parsed_tag["ticker"])
            update = update_map.get(key)
            if not update or not parsed_tag["pending"]:
                new_blocks.append(block)
                continue

            rest = "\n".join(lines[1:]).lstrip()
            new_tag = (
                f"[{parsed_tag['date']} | {parsed_tag['ticker']} | {parsed_tag['rating']} | "
                f"{update['raw_return']:+.1%} | {update['alpha_return']:+.1%} | {int(update['holding_days'])}d]"
            )
            reflection = str(update.get("reflection", "")).strip()
            resolved_block = f"{new_tag}\n\n{rest}"
            if reflection:
                resolved_block += f"\n\nREFLECTION:\n{reflection}"
            new_blocks.append(resolved_block)
            changed = True

        if not changed:
            return
        payload = self._SEPARATOR.join(self._apply_rotation(new_blocks))
        tmp_path = self._log_path.with_suffix(".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self._log_path)

    def _apply_rotation(self, blocks: list[str]) -> list[str]:
        if self._max_entries <= 0:
            return blocks
        resolved = []
        for index, block in enumerate(blocks):
            stripped = block.strip()
            if not stripped:
                continue
            tag_line = stripped.splitlines()[0].strip()
            tag = self._parse_tag_line(tag_line)
            if tag and not tag["pending"]:
                resolved.append(index)
        if len(resolved) <= self._max_entries:
            return blocks
        drop = set(resolved[: len(resolved) - self._max_entries])
        return [block for index, block in enumerate(blocks) if index not in drop]

    def _parse_entry(self, raw: str) -> dict[str, Any] | None:
        lines = raw.splitlines()
        if not lines:
            return None
        tag = self._parse_tag_line(lines[0].strip())
        if tag is None:
            return None
        body = "\n".join(lines[1:]).strip()
        decision = self._extract_section(body, "DECISION")
        reflection = self._extract_section(body, "REFLECTION")
        return {
            "date": tag["date"],
            "ticker": tag["ticker"],
            "rating": tag["rating"],
            "pending": tag["pending"],
            "raw": tag["raw"],
            "alpha": tag["alpha"],
            "holding_days": tag["holding_days"],
            "decision": decision,
            "reflection": reflection,
        }

    def _parse_tag_line(self, line: str) -> dict[str, Any] | None:
        match = self._TAG_RE.match(line)
        if not match:
            return None
        parts = [part.strip() for part in match.group("body").split("|")]
        if len(parts) < 4:
            return None
        date_value, ticker, rating = parts[0], safe_ticker_component(parts[1]), parts[2]
        tail = parts[3:]
        pending = len(tail) == 1 and tail[0].lower() == "pending"
        raw = alpha = None
        holding_days = None
        if not pending and len(tail) >= 3:
            raw = tail[0]
            alpha = tail[1]
            holding_days = tail[2]
        return {
            "date": date_value,
            "ticker": ticker,
            "rating": rating or NO_RECOMMENDATION,
            "pending": pending,
            "raw": raw,
            "alpha": alpha,
            "holding_days": holding_days,
        }

    @staticmethod
    def _extract_section(body: str, name: str) -> str:
        section_re = re.compile(
            rf"{re.escape(name)}:\n(?P<content>.*?)(?=\n[A-Z_ ]+:\n|\Z)",
            re.DOTALL,
        )
        match = section_re.search(body)
        if not match:
            return ""
        return match.group("content").strip()

    @staticmethod
    def _condense(text: str, limit: int = 220) -> str:
        cleaned = " ".join(str(text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."
