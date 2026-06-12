from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ..utils.common import build_instrument_context, get_language_instruction


def create_tool_analyst_node(
    *,
    role: str,
    label: str,
    report_field: str,
    llm: Any,
    tools: list[Any],
    offline_runtime: Any,
    system_message: str,
) -> Callable[[dict], dict]:
    def node(state):
        instrument_context = build_instrument_context(state["company_of_interest"])
        full_system_message = system_message + get_language_instruction(state["output_language"])
        if getattr(offline_runtime, "models", None) is not None and offline_runtime.models.offline:
            has_tool_output = any(isinstance(message, ToolMessage) for message in state["messages"])
            if not has_tool_output:
                result = offline_runtime.offline_tool_call_message(role, state)
                return {"messages": [result], "sender": label}
            report = offline_runtime.offline_analyst_report(role)
            return {"messages": [AIMessage(content=report)], report_field: report, "sender": label}

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are collaborating inside an autonomous multi-agent market research system. "
                    "Use your tools before drafting conclusions whenever tools are available. "
                    "Cite concrete metrics, dates, and contradictions. "
                    "If evidence is incomplete, say so clearly rather than smoothing it over. "
                    "You have access to the following tools: {tool_names}. "
                    "{system_message} The current analysis date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        ).partial(
            tool_names=", ".join(tool.name for tool in tools),
            system_message=full_system_message,
            current_date=state["trade_date"],
            instrument_context=instrument_context,
        )
        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        report = result.content if not result.tool_calls else ""
        return {"messages": [result], report_field: report, "sender": label}

    return node
