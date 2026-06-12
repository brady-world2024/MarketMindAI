from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ..agents.state import MarketMindState


class GraphSetup:
    def __init__(self, conditional_logic: Any):
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        *,
        selected_analysts: list[str],
        analyst_nodes: Dict[str, Any],
        delete_nodes: Dict[str, Any],
        tool_nodes: Dict[str, ToolNode],
        shared_nodes: Dict[str, Any],
    ):
        if not selected_analysts:
            raise ValueError("At least one analyst must be selected.")

        workflow = StateGraph(MarketMindState)

        for analyst_type, node in analyst_nodes.items():
            label = analyst_type.capitalize() if analyst_type != "sentiment" else "Sentiment"
            workflow.add_node(f"{label} Analyst", node)
            workflow.add_node(f"Msg Clear {label}", delete_nodes[analyst_type])
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        for label, node in shared_nodes.items():
            workflow.add_node(label, node)

        first_analyst = selected_analysts[0]
        first_label = first_analyst.capitalize() if first_analyst != "sentiment" else "Sentiment"
        workflow.add_edge(START, f"{first_label} Analyst")

        for index, analyst_type in enumerate(selected_analysts):
            label = analyst_type.capitalize() if analyst_type != "sentiment" else "Sentiment"
            current_analyst = f"{label} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {label}"
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)
            if index < len(selected_analysts) - 1:
                next_type = selected_analysts[index + 1]
                next_label = next_type.capitalize() if next_type != "sentiment" else "Sentiment"
                workflow.add_edge(current_clear, f"{next_label} Analyst")
            else:
                workflow.add_edge(current_clear, "Bull Researcher")

        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {"Bear Researcher": "Bear Researcher", "Research Manager": "Research Manager"},
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {"Bull Researcher": "Bull Researcher", "Research Manager": "Research Manager"},
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {"Conservative Analyst": "Conservative Analyst", "Portfolio Manager": "Portfolio Manager"},
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {"Neutral Analyst": "Neutral Analyst", "Portfolio Manager": "Portfolio Manager"},
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {"Aggressive Analyst": "Aggressive Analyst", "Portfolio Manager": "Portfolio Manager"},
        )
        workflow.add_edge("Portfolio Manager", END)
        return workflow
