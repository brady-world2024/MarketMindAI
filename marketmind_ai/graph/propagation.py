from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from ..agents.state import InvestDebateState, RiskDebateState


class Propagator:
    def __init__(self, max_recur_limit: int = 150):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        *,
        ticker: str,
        original_query: str,
        company_name: str,
        trade_date: str,
        output_language: str,
        selected_analysts: list[str],
        symbol_resolution: dict,
        past_context: str = "",
        research_memory_context: str = "",
        trader_memory_context: str = "",
        portfolio_memory_context: str = "",
    ) -> Dict[str, Any]:
        return {
            "messages": [HumanMessage(content=ticker)],
            "company_of_interest": ticker,
            "original_query": original_query,
            "company_name": company_name,
            "trade_date": str(trade_date),
            "output_language": output_language,
            "selected_analysts": list(selected_analysts),
            "past_context": past_context,
            "research_memory_context": research_memory_context,
            "trader_memory_context": trader_memory_context,
            "portfolio_memory_context": portfolio_memory_context,
            "sender": "",
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": InvestDebateState(
                bull_history="",
                bear_history="",
                history="",
                current_response="",
                judge_decision="",
                count=0,
            ),
            "investment_plan": "",
            "trader_investment_plan": "",
            "risk_debate_state": RiskDebateState(
                aggressive_history="",
                conservative_history="",
                neutral_history="",
                history="",
                latest_speaker="",
                current_aggressive_response="",
                current_conservative_response="",
                current_neutral_response="",
                judge_decision="",
                count=0,
            ),
            "pre_verifier_final_trade_decision": "",
            "final_trade_decision": "",
            "report_verification": {},
            "symbol_resolution": symbol_resolution,
            "final_structured_decision": {},
            "last_error": None,
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {"stream_mode": "values", "config": config}
