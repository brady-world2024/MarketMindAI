from __future__ import annotations

from ..utils.common import get_language_instruction


def create_bear_researcher(llm, offline_runtime):
    def node(state):
        if offline_runtime.models.offline:
            bundle = offline_runtime.bundle()
            scores = offline_runtime.scores()
            _, bears = offline_runtime.bull_bear_lists(scores, bundle, offline_runtime.request.output_language)
            content = offline_runtime.bear_case(bundle, bears, offline_runtime.request.output_language)
        else:
            prompt = (
                "You are the Bear Researcher. Build the strongest evidence-based cautionary or short case possible using only the current run. "
                "Challenge the bullish claims directly on valuation, timing, fragility of demand, macro exposure, and missing evidence. "
                "Do not turn generic risk language into a thesis; stay specific.\n\n"
                f"Market Report:\n{state['market_report']}\n\n"
                f"Sentiment Report:\n{state['sentiment_report']}\n\n"
                f"News Report:\n{state['news_report']}\n\n"
                f"Fundamentals Report:\n{state['fundamentals_report']}\n\n"
                f"Debate so far:\n{state['investment_debate_state'].get('history', '')}\n"
                f"{get_language_instruction(state['output_language'])}"
            )
            content = str(llm.invoke(prompt).content)
        argument = f"Bear Analyst: {content}"
        debate = state["investment_debate_state"]
        return {
            "investment_debate_state": {
                "history": debate.get("history", "") + ("\n" if debate.get("history") else "") + argument,
                "bull_history": debate.get("bull_history", ""),
                "bear_history": debate.get("bear_history", "") + ("\n" if debate.get("bear_history") else "") + argument,
                "current_response": argument,
                "judge_decision": debate.get("judge_decision", ""),
                "count": debate["count"] + 1,
            },
            "sender": "Bear Researcher",
        }

    return node
