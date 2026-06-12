from __future__ import annotations

from ._tool_agent import create_tool_analyst_node


def create_news_analyst(llm, tools, offline_runtime):
    message = (
        "You are the News Analyst. Start with `get_news_event_timeline` to build an event chronology, not a bag of headlines. Distinguish fresh "
        "information from stale echo, connect company-specific items to the macro backdrop, and explain which events are likely to matter for the next "
        "1-4 weeks. Use raw `get_news` or `get_global_news` only when the timeline leaves evidence gaps. Call out missing dates, uncertain sourcing, "
        "and contradictory narratives."
    )
    return create_tool_analyst_node(
        role="news",
        label="News Analyst",
        report_field="news_report",
        llm=llm,
        tools=tools,
        offline_runtime=offline_runtime,
        system_message=message,
    )
