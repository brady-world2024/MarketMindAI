from __future__ import annotations

from ._tool_agent import create_tool_analyst_node


def create_fundamentals_analyst(llm, tools, offline_runtime):
    message = (
        "You are the Fundamentals Analyst. Start with `get_fundamental_document_context` so your first pass uses the latest filings and earnings call "
        "transcript evidence before drilling into statement tools. Use financial statements and long-form context to evaluate business quality, "
        "balance-sheet resilience, margin structure, growth durability, and valuation discipline. Explain which parts of the thesis are hard facts, "
        "which are interpretation, and what would need to change before the company deserves a materially different rating."
    )
    return create_tool_analyst_node(
        role="fundamentals",
        label="Fundamentals Analyst",
        report_field="fundamentals_report",
        llm=llm,
        tools=tools,
        offline_runtime=offline_runtime,
        system_message=message,
    )
