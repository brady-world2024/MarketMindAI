from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Iterable

from ...pathing import safe_ticker_component


@dataclass
class MemorySnippet:
    ticker: str
    trade_date: str
    title: str
    text: str
    kind: str
    section: str
    same_ticker: bool
    source: str


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ROLE_QUERIES = {
    "research": "bull bear thesis catalyst valuation growth guidance demand margins competition macro risk evidence",
    "trader": "entry timing confirmation breakout momentum risk reward stop loss execution sizing catalyst",
    "portfolio": "portfolio sizing downside drawdown confidence outcome lesson risk exposure no recommendation",
}
_SECTION_WEIGHTS = {
    "market_report": 1.0,
    "sentiment_report": 0.85,
    "news_report": 1.05,
    "fundamentals_report": 1.1,
    "investment_plan": 1.1,
    "trader_investment_plan": 1.15,
    "final_trade_decision": 1.2,
    "decision": 1.0,
    "reflection": 1.15,
}


class MarketMindMemoryRetriever:
    def __init__(self, config: dict, memory_log):
        self.config = config or {}
        self.memory_log = memory_log
        self.results_dir = Path(self.config.get("results_dir", ".")).expanduser()

    def build_contexts(self, ticker: str, trade_date: str) -> dict[str, str]:
        if not self.config.get("memory_retrieval_enabled", True):
            fallback = self.memory_log.get_past_context(ticker)
            return {
                "research_memory_context": fallback,
                "trader_memory_context": fallback,
                "portfolio_memory_context": fallback,
            }
        snippets = self._collect_snippets(safe_ticker_component(ticker), trade_date)
        return {
            "research_memory_context": self._build_context_for_role("research", ticker, trade_date, snippets),
            "trader_memory_context": self._build_context_for_role("trader", ticker, trade_date, snippets),
            "portfolio_memory_context": self._build_context_for_role("portfolio", ticker, trade_date, snippets),
        }

    def _build_context_for_role(
        self,
        role: str,
        ticker: str,
        trade_date: str,
        snippets: list[MemorySnippet],
    ) -> str:
        same_limit = int(self.config.get("memory_retrieval_same_limit", 3))
        cross_limit = int(self.config.get("memory_retrieval_cross_limit", 2))
        report_limit = int(self.config.get("memory_retrieval_report_limit", 3))
        query = _ROLE_QUERIES[role]
        same_history = self._rank_snippets(
            [item for item in snippets if item.same_ticker and item.kind in {"decision", "reflection"}],
            query,
            trade_date,
            same_limit,
        )
        report_history = self._rank_snippets(
            [item for item in snippets if item.same_ticker and item.kind == "report"],
            query,
            trade_date,
            report_limit,
        )
        cross_history = self._rank_snippets(
            [item for item in snippets if not item.same_ticker and item.kind == "reflection"],
            query,
            trade_date,
            cross_limit,
        )
        if not same_history and not report_history and not cross_history:
            return ""
        title = {
            "research": f"Historical retrieval for Research Manager on {ticker}",
            "trader": f"Historical retrieval for Trader on {ticker}",
            "portfolio": f"Historical retrieval for Portfolio Manager on {ticker}",
        }[role]
        lines = [title, ""]
        if report_history:
            lines.append(f"Recent report excerpts for {ticker}:")
            lines.extend(self._render_snippet(item) for item in report_history)
        if same_history:
            lines.append(f"Prior outcome lessons for {ticker}:")
            lines.extend(self._render_snippet(item) for item in same_history)
        if cross_history:
            lines.append("Cross-ticker lessons worth remembering:")
            lines.extend(self._render_snippet(item) for item in cross_history)
        return "\n".join(lines).strip()

    def _collect_snippets(self, ticker: str, trade_date: str) -> list[MemorySnippet]:
        snippets = []
        snippets.extend(self._collect_entry_snippets(ticker, trade_date))
        snippets.extend(self._collect_report_snippets(ticker, trade_date))
        return snippets

    def _collect_entry_snippets(self, ticker: str, trade_date: str) -> list[MemorySnippet]:
        snippets: list[MemorySnippet] = []
        for entry in self.memory_log.load_entries():
            if entry.get("pending"):
                continue
            if not self._is_before(entry.get("date", ""), trade_date):
                continue
            same_ticker = entry["ticker"] == ticker
            decision = str(entry.get("decision", "")).strip()
            if decision and same_ticker:
                snippets.append(
                    MemorySnippet(
                        ticker=entry["ticker"],
                        trade_date=entry["date"],
                        title=f"Prior final decision - {entry['ticker']} - {entry['date']}",
                        text=decision,
                        kind="decision",
                        section="decision",
                        same_ticker=True,
                        source="memory_log",
                    )
                )
            reflection = str(entry.get("reflection", "")).strip() or self._decision_fallback(decision)
            if reflection:
                snippets.append(
                    MemorySnippet(
                        ticker=entry["ticker"],
                        trade_date=entry["date"],
                        title=f"Outcome reflection - {entry['ticker']} - {entry['date']}",
                        text=reflection,
                        kind="reflection",
                        section="reflection",
                        same_ticker=same_ticker,
                        source="memory_log",
                    )
                )
        return snippets

    def _collect_report_snippets(self, ticker: str, trade_date: str) -> list[MemorySnippet]:
        report_dir = self.results_dir / safe_ticker_component(ticker) / "MarketMindStrategy_logs"
        if not report_dir.exists():
            return []
        snippets: list[MemorySnippet] = []
        for path in sorted(report_dir.glob("full_states_log_*.json"), reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            report_date = str(payload.get("trade_date", "") or payload.get("analysis_date", ""))
            if not self._is_before(report_date, trade_date):
                continue
            for section in (
                "market_report",
                "sentiment_report",
                "news_report",
                "fundamentals_report",
                "investment_plan",
                "trader_investment_plan",
                "final_trade_decision",
            ):
                text = str(payload.get(section, "")).strip()
                if not text:
                    continue
                snippets.append(
                    MemorySnippet(
                        ticker=ticker,
                        trade_date=report_date,
                        title=f"{section.replace('_', ' ').title()} - {report_date}",
                        text=self._extract_relevant_excerpt(text, _ROLE_QUERIES["research"]),
                        kind="report",
                        section=section,
                        same_ticker=True,
                        source=str(path),
                    )
                )
        return snippets

    def _rank_snippets(
        self,
        snippets: Iterable[MemorySnippet],
        query: str,
        trade_date: str,
        limit: int,
    ) -> list[MemorySnippet]:
        query_tokens = set(_TOKEN_RE.findall(query.lower()))
        ranked = []
        for snippet in snippets:
            text = f"{snippet.title} {snippet.text}".lower()
            tokens = set(_TOKEN_RE.findall(text))
            overlap = len(query_tokens & tokens)
            if overlap == 0 and len(tokens) < 10:
                continue
            score = float(overlap)
            score += _SECTION_WEIGHTS.get(snippet.section, 0.9)
            score += 0.3 if snippet.same_ticker else 0.0
            score += self._recency_weight(snippet.trade_date, trade_date)
            ranked.append((score, snippet))
        ranked.sort(key=lambda item: (item[0], item[1].trade_date, item[1].title), reverse=True)
        return [snippet for _, snippet in ranked[:limit]]

    def _render_snippet(self, snippet: MemorySnippet) -> str:
        return f"- {snippet.title}: {self._clip(snippet.text, int(self.config.get('memory_retrieval_report_chars', 280)))}"

    @staticmethod
    def _decision_fallback(decision_text: str) -> str:
        sentence = " ".join(decision_text.split())
        if len(sentence) <= 220:
            return sentence
        return sentence[:217].rstrip() + "..."

    @staticmethod
    def _extract_relevant_excerpt(text: str, query: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= 280:
            return compact
        sentences = re.split(r"(?<=[.!?])\s+", compact)
        query_tokens = set(_TOKEN_RE.findall(query.lower()))
        best_sentence = max(
            sentences,
            key=lambda sentence: len(query_tokens & set(_TOKEN_RE.findall(sentence.lower()))),
        )
        if len(best_sentence) <= 280:
            return best_sentence
        return best_sentence[:277].rstrip() + "..."

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    @staticmethod
    def _is_before(candidate: str, trade_date: str) -> bool:
        try:
            candidate_date = datetime.strptime(candidate, "%Y-%m-%d").date()
            anchor = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except ValueError:
            return False
        return candidate_date < anchor

    @staticmethod
    def _recency_weight(snippet_date: str, trade_date: str) -> float:
        try:
            snippet_dt = datetime.strptime(snippet_date, "%Y-%m-%d")
            trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            return 0.0
        delta = max((trade_dt - snippet_dt).days, 0)
        return 1.0 / (1.0 + math.log1p(delta))
