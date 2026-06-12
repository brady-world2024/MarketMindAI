from __future__ import annotations

from typing import Annotated, Optional

from langgraph.graph import MessagesState
from typing_extensions import TypedDict


class InvestDebateState(TypedDict):
    bull_history: Annotated[str, "Bullish debate transcript"]
    bear_history: Annotated[str, "Bearish debate transcript"]
    history: Annotated[str, "Combined debate transcript"]
    current_response: Annotated[str, "Most recent debate utterance"]
    judge_decision: Annotated[str, "Research manager decision"]
    count: Annotated[int, "Debate turn count"]


class RiskDebateState(TypedDict):
    aggressive_history: Annotated[str, "Aggressive risk transcript"]
    conservative_history: Annotated[str, "Conservative risk transcript"]
    neutral_history: Annotated[str, "Neutral risk transcript"]
    history: Annotated[str, "Combined risk transcript"]
    latest_speaker: Annotated[str, "Latest risk speaker"]
    current_aggressive_response: Annotated[str, "Latest aggressive view"]
    current_conservative_response: Annotated[str, "Latest conservative view"]
    current_neutral_response: Annotated[str, "Latest neutral view"]
    judge_decision: Annotated[str, "Final portfolio manager decision"]
    count: Annotated[int, "Risk debate turn count"]


class MarketMindState(MessagesState):
    company_of_interest: Annotated[str, "Resolved ticker to analyze"]
    original_query: Annotated[str, "Original user query"]
    company_name: Annotated[str, "Resolved company name"]
    trade_date: Annotated[str, "Analysis date"]
    output_language: Annotated[str, "User-facing output language"]
    selected_analysts: Annotated[list[str], "Enabled analyst desks"]
    sender: Annotated[str, "Most recent agent sender"]
    market_report: Annotated[str, "Market analyst report"]
    sentiment_report: Annotated[str, "Sentiment analyst report"]
    news_report: Annotated[str, "News analyst report"]
    fundamentals_report: Annotated[str, "Fundamentals analyst report"]
    investment_debate_state: Annotated[InvestDebateState, "Bull/Bear debate state"]
    investment_plan: Annotated[str, "Research manager decision text"]
    trader_investment_plan: Annotated[str, "Trader execution proposal"]
    research_memory_context: Annotated[str, "Research-manager memory context"]
    trader_memory_context: Annotated[str, "Trader memory context"]
    portfolio_memory_context: Annotated[str, "Portfolio-manager memory context"]
    risk_debate_state: Annotated[RiskDebateState, "Risk debate state"]
    pre_verifier_final_trade_decision: Annotated[str, "Portfolio manager raw decision"]
    final_trade_decision: Annotated[str, "Verifier-adjusted final decision"]
    report_verification: Annotated[dict, "Deterministic verification payload"]
    symbol_resolution: Annotated[dict, "Ticker resolution payload"]
    final_structured_decision: Annotated[dict, "Structured PM decision for UI/state persistence"]
    last_error: Annotated[Optional[str], "Latest runtime error"]

