from __future__ import annotations

from ..schemas import PortfolioDecision, render_portfolio_decision
from ..utils.common import build_instrument_context, get_language_instruction
from ..utils.structured import bind_structured


def create_portfolio_manager(llm, offline_runtime, verifier_callback):
    structured = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def node(state):
        if offline_runtime.models.offline:
            research_plan = offline_runtime.offline_research_plan(state["selected_analysts"])
            trader_plan = offline_runtime.offline_trader_proposal(research_plan)
            decision = offline_runtime.offline_portfolio_decision(research_plan, trader_plan)
        else:
            prompt = (
                "You are the Portfolio Manager. Make the final portfolio call only if the evidence is current, dated, and internally consistent.\n\n"
                f"{build_instrument_context(state['company_of_interest'])}\n\n"
                "Decision rules:\n"
                "- Every actionable rating needs at least two concrete evidence items from the current run.\n"
                "- At least one evidence item must be a Fact.\n"
                "- Do not lightly override upstream No Recommendation conclusions.\n"
                "- Buy / Overweight / Underweight / Sell below 50 confidence are not allowed.\n"
                "- If support is still too weak, set Decision Status to No Recommendation and state what evidence is still needed.\n\n"
                f"Research Plan:\n{state['investment_plan']}\n\n"
                f"Trader Plan:\n{state['trader_investment_plan']}\n\n"
                f"Risk Debate:\n{state['risk_debate_state'].get('history', '')}\n\n"
                f"Portfolio Memory:\n{state.get('portfolio_memory_context', '')}\n"
                f"{get_language_instruction(state['output_language'])}"
            )
            if structured is not None:
                decision = structured.invoke(prompt)
            else:
                research_plan = offline_runtime.offline_research_plan(state["selected_analysts"])
                trader_plan = offline_runtime.offline_trader_proposal(research_plan)
                decision = offline_runtime.offline_portfolio_decision(research_plan, trader_plan)

        raw_text = render_portfolio_decision(decision)
        final_decision, verification = verifier_callback(state, decision)
        final_text = render_portfolio_decision(final_decision)
        risk = state["risk_debate_state"]
        return {
            "risk_debate_state": {
                "history": risk.get("history", ""),
                "aggressive_history": risk.get("aggressive_history", ""),
                "conservative_history": risk.get("conservative_history", ""),
                "neutral_history": risk.get("neutral_history", ""),
                "latest_speaker": "Portfolio Manager",
                "current_aggressive_response": risk.get("current_aggressive_response", ""),
                "current_conservative_response": risk.get("current_conservative_response", ""),
                "current_neutral_response": risk.get("current_neutral_response", ""),
                "judge_decision": final_text,
                "count": risk["count"],
            },
            "pre_verifier_final_trade_decision": raw_text,
            "final_trade_decision": final_text,
            "report_verification": verification,
            "final_structured_decision": final_decision.model_dump(mode="json"),
            "sender": "Portfolio Manager",
        }

    return node
