from __future__ import annotations

from ._tool_agent import create_tool_analyst_node


def create_market_analyst(llm, tools, offline_runtime):
    message = (
        "You are the Market Analyst. Study the recent tape first, then request only the indicators that actually help distinguish trend, "
        "momentum, volatility, and exhaustion. Avoid redundant indicators. Explain what the price structure says, what it does not say, "
        "where the setup could fail, and which levels or regime shifts would invalidate a naive read of the chart. End with a compact markdown table."
    )
    return create_tool_analyst_node(
        role="market",
        label="Market Analyst",
        report_field="market_report",
        llm=llm,
        tools=tools,
        offline_runtime=offline_runtime,
        system_message=message,
    )
