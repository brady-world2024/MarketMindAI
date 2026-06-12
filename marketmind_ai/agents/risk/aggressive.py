from __future__ import annotations

from ..utils.common import get_language_instruction


def create_aggressive_debator(llm, offline_runtime):
    return _create_risk_node("Aggressive", llm, offline_runtime)


def _create_risk_node(stance: str, llm, offline_runtime):
    stance_lower = stance.lower()

    def node(state):
        if offline_runtime.models.offline:
            mapping = {
                "aggressive": "Lean into the trade only while momentum and catalyst follow-through remain intact; conviction can be expressed, but only with a clear invalidation.",
                "conservative": "Volatility, valuation, and evidence gaps argue for smaller sizing and tighter stops than the upside narrative alone would suggest.",
                "neutral": "Keep the base case tied to what is actually evidenced in this run today, not to an aspirational version of the story.",
            }
            content = mapping[stance_lower]
        else:
            prompt = (
                f"You are the {stance} Risk Analyst. Debate sizing, downside asymmetry, invalidation, and portfolio-fit based on the current research plan and trader proposal.\n\n"
                f"Research Plan:\n{state['investment_plan']}\n\n"
                f"Trader Plan:\n{state['trader_investment_plan']}\n\n"
                f"Risk Debate So Far:\n{state['risk_debate_state'].get('history', '')}\n"
                f"{get_language_instruction(state['output_language'])}"
            )
            content = str(llm.invoke(prompt).content)
        line = f"{stance} Analyst: {content}"
        risk = state["risk_debate_state"]
        updated = {
            "history": risk.get("history", "") + ("\n" if risk.get("history") else "") + line,
            "aggressive_history": risk.get("aggressive_history", ""),
            "conservative_history": risk.get("conservative_history", ""),
            "neutral_history": risk.get("neutral_history", ""),
            "latest_speaker": f"{stance} Analyst",
            "current_aggressive_response": risk.get("current_aggressive_response", ""),
            "current_conservative_response": risk.get("current_conservative_response", ""),
            "current_neutral_response": risk.get("current_neutral_response", ""),
            "judge_decision": risk.get("judge_decision", ""),
            "count": risk["count"] + 1,
        }
        key = f"{stance_lower}_history"
        current_key = f"current_{stance_lower}_response"
        updated[key] = risk.get(key, "") + ("\n" if risk.get(key) else "") + line
        updated[current_key] = line
        return {"risk_debate_state": updated, "sender": f"{stance} Analyst"}

    return node
