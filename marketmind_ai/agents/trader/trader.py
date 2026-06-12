from __future__ import annotations

from langchain_core.messages import AIMessage

from ..schemas import TraderProposal, render_trader_proposal
from ..utils.common import build_instrument_context, get_language_instruction
from ..utils.structured import bind_structured, invoke_structured_or_freetext


def create_trader(llm, offline_runtime):
    structured = bind_structured(llm, TraderProposal, "Trader")

    def node(state):
        if offline_runtime.models.offline:
            research_plan = offline_runtime.offline_research_plan(state["selected_analysts"])
            proposal = offline_runtime.offline_trader_proposal(research_plan)
        else:
            prompt = [
                (
                    "system",
                    "You are the Trader. Convert the research plan into a concrete transaction proposal without inventing unsupported precision. "
                    "Actionable plans need explicit risk controls, entry logic, and at least two concrete evidence items. "
                    "Every concrete evidence item must cite a source date or period. "
                    "Include a Confidence Rationale and be explicit about unresolved evidence gaps."
                    + get_language_instruction(state["output_language"]),
                ),
                (
                    "human",
                    f"{build_instrument_context(state['company_of_interest'])}\n\n"
                    f"Proposed Investment Plan:\n{state['investment_plan']}\n\n"
                    f"Trader Memory:\n{state.get('trader_memory_context', '')}",
                ),
            ]
            if structured is None:
                rendered = invoke_structured_or_freetext(
                    structured,
                    llm,
                    prompt,
                    render_trader_proposal,
                    "Trader",
                )
                return {
                    "messages": [AIMessage(content=rendered)],
                    "trader_investment_plan": rendered,
                    "sender": "Trader",
                }
            proposal = structured.invoke(prompt)
        rendered = render_trader_proposal(proposal)
        return {
            "messages": [AIMessage(content=rendered)],
            "trader_investment_plan": rendered,
            "sender": "Trader",
        }

    return node
