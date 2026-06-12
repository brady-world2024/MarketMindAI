from __future__ import annotations

from ._tool_agent import create_tool_analyst_node


def create_sentiment_analyst(llm, tools, offline_runtime):
    message = (
        "You are the Sentiment Analyst. Use the available headline and participation signals to infer crowd temperature, consensus fragility, "
        "and whether the narrative is early, crowded, or deteriorating. Separate genuine demand from hype, and identify where sentiment may be "
        "confirming price versus merely following it."
    )
    return create_tool_analyst_node(
        role="sentiment",
        label="Sentiment Analyst",
        report_field="sentiment_report",
        llm=llm,
        tools=tools,
        offline_runtime=offline_runtime,
        system_message=message,
    )
