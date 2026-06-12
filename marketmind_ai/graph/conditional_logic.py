from __future__ import annotations

from ..agents.state import MarketMindState


class ConditionalLogic:
    def __init__(self, max_debate_rounds: int = 2, max_risk_rounds: int = 2):
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_rounds = max_risk_rounds

    def should_continue_market(self, state: MarketMindState) -> str:
        return self._should_continue_analyst(state, "tools_market", "Msg Clear Market")

    def should_continue_sentiment(self, state: MarketMindState) -> str:
        return self._should_continue_analyst(state, "tools_sentiment", "Msg Clear Sentiment")

    def should_continue_news(self, state: MarketMindState) -> str:
        return self._should_continue_analyst(state, "tools_news", "Msg Clear News")

    def should_continue_fundamentals(self, state: MarketMindState) -> str:
        return self._should_continue_analyst(state, "tools_fundamentals", "Msg Clear Fundamentals")

    @staticmethod
    def _should_continue_analyst(state: MarketMindState, tool_node: str, clear_node: str) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return tool_node
        return clear_node

    def should_continue_debate(self, state: MarketMindState) -> str:
        if state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds:
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: MarketMindState) -> str:
        if state["risk_debate_state"]["count"] >= 3 * self.max_risk_rounds:
            return "Portfolio Manager"
        speaker = state["risk_debate_state"]["latest_speaker"]
        if speaker.startswith("Aggressive"):
            return "Conservative Analyst"
        if speaker.startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
