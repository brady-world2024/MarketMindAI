from __future__ import annotations

from ..utils.common import get_language_instruction


def create_bull_researcher(llm, offline_runtime):
    def node(state):
        if offline_runtime.models.offline:
            bundle = offline_runtime.bundle()
            scores = offline_runtime.scores()
            bulls, _ = offline_runtime.bull_bear_lists(scores, bundle, offline_runtime.request.output_language)
            content = offline_runtime.bull_case(bundle, bulls, offline_runtime.request.output_language)
        else:
            prompt = (
                "You are the Bull Researcher. Make the strongest evidence-based long case possible using only what the current run actually supports. "
                "Directly respond to the bearish objections already raised. Do not ignore valuation, timing, or evidence gaps. "
                "Your goal is not optimism; it is the strongest defensible bull argument.\n\n"
                f"Market Report:\n{state['market_report']}\n\n"
                f"Sentiment Report:\n{state['sentiment_report']}\n\n"
                f"News Report:\n{state['news_report']}\n\n"
                f"Fundamentals Report:\n{state['fundamentals_report']}\n\n"
                f"Debate so far:\n{state['investment_debate_state'].get('history', '')}\n"
                f"{get_language_instruction(state['output_language'])}"
            )
            content = str(llm.invoke(prompt).content)
        argument = f"Bull Analyst: {content}"
        debate = state["investment_debate_state"]
        return {
            "investment_debate_state": {
                "history": debate.get("history", "") + ("\n" if debate.get("history") else "") + argument,
                "bull_history": debate.get("bull_history", "") + ("\n" if debate.get("bull_history") else "") + argument,
                "bear_history": debate.get("bear_history", ""),
                "current_response": argument,
                "judge_decision": debate.get("judge_decision", ""),
                "count": debate["count"] + 1,
            },
            "sender": "Bull Researcher",
        }

    return node
