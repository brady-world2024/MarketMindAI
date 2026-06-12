from __future__ import annotations

from ..schemas import ResearchPlan, render_research_plan
from ..utils.common import build_instrument_context, get_language_instruction
from ..utils.structured import bind_structured, invoke_structured_or_freetext


def create_research_manager(llm, offline_runtime):
    structured = bind_structured(llm, ResearchPlan, "Research Manager")

    def node(state):
        if offline_runtime.models.offline:
            plan = offline_runtime.offline_research_plan(state["selected_analysts"])
        else:
            prompt = (
                "You are the Research Manager. Synthesize the analyst stack and the bull/bear debate into a disciplined investment plan.\n\n"
                f"{build_instrument_context(state['company_of_interest'])}\n\n"
                "Recommendation scale:\n"
                "- **Buy**\n"
                "- **Overweight**\n"
                "- **Hold**\n"
                "- **Underweight**\n"
                "- **Sell**\n"
                "- **No Recommendation**\n\n"
                "Rules:\n"
                "- Only make an actionable recommendation when at least two concrete evidence items support it.\n"
                "- At least one evidence item must be a hard fact with a date or period.\n"
                "- Each evidence item must include a source, source date or period, and a short excerpt.\n"
                "- If the evidence is incomplete, internally inconsistent, or mostly judgment, default to No Recommendation.\n"
                "- Include an explicit Confidence Rationale that explains both what is known and what remains unresolved.\n"
                "- Always preserve an explicit evidence gap.\n\n"
                f"Debate history:\n{state['investment_debate_state'].get('history', '')}\n\n"
                f"Historical memory:\n{state.get('research_memory_context', '')}\n"
                f"{get_language_instruction(state['output_language'])}"
            )
            if structured is None:
                rendered = invoke_structured_or_freetext(
                    structured,
                    llm,
                    prompt,
                    render_research_plan,
                    "Research Manager",
                )
                return {
                    "investment_debate_state": {
                        "history": state["investment_debate_state"].get("history", ""),
                        "bull_history": state["investment_debate_state"].get("bull_history", ""),
                        "bear_history": state["investment_debate_state"].get("bear_history", ""),
                        "current_response": rendered,
                        "judge_decision": rendered,
                        "count": state["investment_debate_state"]["count"],
                    },
                    "investment_plan": rendered,
                    "sender": "Research Manager",
                }
            plan = structured.invoke(prompt)
        rendered = render_research_plan(plan)
        debate = state["investment_debate_state"]
        return {
            "investment_debate_state": {
                "history": debate.get("history", ""),
                "bull_history": debate.get("bull_history", ""),
                "bear_history": debate.get("bear_history", ""),
                "current_response": rendered,
                "judge_decision": rendered,
                "count": debate["count"],
            },
            "investment_plan": rendered,
            "sender": "Research Manager",
        }

    return node
