from __future__ import annotations

from ..dataflows.interface import route_to_vendor
from .reflection import Reflector


class PendingOutcomeResolver:
    def __init__(self, memory_log) -> None:
        self.memory_log = memory_log

    def resolve_for_ticker(self, ticker: str, analysis_date: str, quick_llm) -> None:
        pending = [
            entry
            for entry in self.memory_log.get_pending_entries()
            if entry.get("ticker", "").upper() == ticker.upper()
        ]
        if not pending:
            return
        reflector = Reflector(quick_llm)
        updates = []
        for entry in pending:
            fetched = self._fetch_returns(ticker, analysis_date, entry.get("date", ""))
            if fetched is None:
                continue
            raw_return, alpha_return, holding_days = fetched
            reflection = reflector.reflect_on_final_decision(
                entry.get("decision", ""),
                raw_return,
                alpha_return,
            )
            updates.append(
                {
                    "ticker": ticker,
                    "trade_date": entry.get("date", ""),
                    "raw_return": raw_return,
                    "alpha_return": alpha_return,
                    "holding_days": holding_days,
                    "reflection": reflection,
                }
            )
        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    @staticmethod
    def _fetch_returns(ticker: str, analysis_date: str, trade_date: str, holding_days: int = 5):
        if not trade_date or trade_date >= analysis_date:
            return None
        try:
            bars = route_to_vendor("get_price_history", ticker, analysis_date, 420)
            benchmark = route_to_vendor("get_price_history", "SPY", analysis_date, 420)
        except Exception:
            return None
        if len(bars) < 2 or len(benchmark) < 2:
            return None
        try:
            start_index = next(index for index, bar in enumerate(bars) if bar.date >= trade_date)
            bench_index = next(index for index, bar in enumerate(benchmark) if bar.date >= trade_date)
        except StopIteration:
            return None
        end_index = min(start_index + holding_days, len(bars) - 1)
        bench_end_index = min(bench_index + holding_days, len(benchmark) - 1)
        if end_index <= start_index or bench_end_index <= bench_index:
            return None
        start_price = bars[start_index].close
        end_price = bars[end_index].close
        bench_start = benchmark[bench_index].close
        bench_end = benchmark[bench_end_index].close
        if start_price <= 0 or bench_start <= 0:
            return None
        raw_return = (end_price - start_price) / start_price
        alpha_return = raw_return - ((bench_end - bench_start) / bench_start)
        actual_holding_days = min(end_index - start_index, bench_end_index - bench_index)
        return raw_return, alpha_return, actual_holding_days
