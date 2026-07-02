from __future__ import annotations

from datetime import datetime
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .decision import EvidenceItem, FinalDecision
from .request import AnalysisRequest
from .snapshot import MessageView, RunSnapshot, ToolCallView


SNAPSHOT_AGENT_LABELS = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
    "bull": "Bull Researcher",
    "bear": "Bear Researcher",
    "research_manager": "Research Manager",
    "trader": "Trader",
    "aggressive": "Aggressive Analyst",
    "conservative": "Conservative Analyst",
    "neutral": "Neutral Analyst",
    "portfolio_manager": "Portfolio Manager",
}


SNAPSHOT_REPORT_LABELS = {
    "market_report": "Market Analysis",
    "sentiment_report": "Social Sentiment",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "bull_history": "Bull Researcher Debate",
    "bear_history": "Bear Researcher Debate",
    "investment_plan": "Research Manager Decision",
    "trader_investment_plan": "Trader Proposal",
    "aggressive_history": "Aggressive Risk View",
    "conservative_history": "Conservative Risk View",
    "neutral_history": "Neutral Risk View",
    "final_trade_decision": "Portfolio Manager Decision",
}


def extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")).strip())
            else:
                parts.append(str(item).strip())
        return " ".join(part for part in parts if part)
    return str(content).strip()


class SnapshotProjector:
    def __init__(self, signal_processor) -> None:
        self.signal_processor = signal_processor

    def create_snapshot(self, *, run_id: str, request: AnalysisRequest, resolution) -> RunSnapshot:
        return RunSnapshot.create(
            run_id=run_id,
            request=request,
            resolution=resolution,
            labels=SNAPSHOT_AGENT_LABELS,
            report_labels=SNAPSHOT_REPORT_LABELS,
        )

    def apply_state(self, snapshot: RunSnapshot, state: dict) -> None:
        snapshot.current_agent = state.get("sender") or None
        snapshot.latest_update = f"{state.get('sender') or 'LangGraph'} completed a step."
        self._ingest_messages(snapshot, state.get("messages", []))

        mappings = {
            "market_report": ("market_report", "market"),
            "sentiment_report": ("sentiment_report", "social"),
            "news_report": ("news_report", "news"),
            "fundamentals_report": ("fundamentals_report", "fundamentals"),
        }
        for state_key, (report_key, agent_key) in mappings.items():
            value = state.get(state_key) or ""
            if value:
                self._set_report(snapshot, report_key, value)
                self._set_agent(snapshot, agent_key, "completed")

        debate = state.get("investment_debate_state") or {}
        if debate.get("bull_history"):
            self._set_report(snapshot, "bull_history", debate["bull_history"])
            self._set_agent(snapshot, "bull", "completed")
        if debate.get("bear_history"):
            self._set_report(snapshot, "bear_history", debate["bear_history"])
            self._set_agent(snapshot, "bear", "completed")
        if state.get("investment_plan"):
            self._set_report(snapshot, "investment_plan", state["investment_plan"])
            self._set_agent(snapshot, "research_manager", "completed")
        if state.get("trader_investment_plan"):
            self._set_report(snapshot, "trader_investment_plan", state["trader_investment_plan"])
            self._set_agent(snapshot, "trader", "completed")

        risk = state.get("risk_debate_state") or {}
        if risk.get("aggressive_history"):
            self._set_report(snapshot, "aggressive_history", risk["aggressive_history"])
            self._set_agent(snapshot, "aggressive", "completed")
        if risk.get("conservative_history"):
            self._set_report(snapshot, "conservative_history", risk["conservative_history"])
            self._set_agent(snapshot, "conservative", "completed")
        if risk.get("neutral_history"):
            self._set_report(snapshot, "neutral_history", risk["neutral_history"])
            self._set_agent(snapshot, "neutral", "completed")

        if state.get("final_trade_decision"):
            self._set_report(snapshot, "final_trade_decision", state["final_trade_decision"])
            self._set_agent(snapshot, "portfolio_manager", "completed")
            snapshot.final_decision = state["final_trade_decision"]
            snapshot.report_verification = state.get("report_verification") or None
            snapshot.final_structured_decision = state.get("final_structured_decision") or None
            snapshot.report_quality = state.get("report_quality") or None
            snapshot.evidence_ledger = state.get("evidence_ledger") or []
            snapshot.final_signal = self.signal_processor.process_signal(
                state["final_trade_decision"],
                state.get("report_verification"),
            )

        final_structured = state.get("final_structured_decision") or {}
        if final_structured and not snapshot.final_signal:
            rating = final_structured.get("rating")
            status = final_structured.get("decision_status")
            snapshot.final_signal = rating or ("No Recommendation" if status == "No Recommendation" else None)

    def decision_from_state(self, state: dict, ticker: str) -> Optional[FinalDecision]:
        payload = state.get("final_structured_decision") or {}
        if not payload:
            return None
        evidence_items = []
        for item in payload.get("primary_evidence", []):
            evidence_items.append(
                EvidenceItem(
                    kind=str(item.get("evidence_type", "")).lower(),
                    strength=str(item.get("strength", "")).lower(),
                    claim=str(item.get("claim", "")),
                    source=str(item.get("source", "")),
                    source_date=str(item.get("source_date", "")),
                    detail=f"{item.get('excerpt', '')} {item.get('interpretation', '')}".strip(),
                )
            )
        rating = payload.get("rating")
        return FinalDecision(
            ticker=ticker,
            action=(str(rating).upper().replace(" ", "_") if rating else "NO_RECOMMENDATION"),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            thesis=str(payload.get("investment_thesis", "")),
            time_horizon=str(payload.get("time_horizon", "") or ""),
            entry_plan=str(payload.get("executive_summary", "")),
            risk_controls="; ".join(payload.get("key_risks", [])),
            evidence_gap=str(payload.get("evidence_gap", "")),
            evidence_items=evidence_items,
            rationale=str(payload.get("confidence_rationale", "")),
        )

    def state_log_payload(self, state: dict) -> dict:
        debate = state.get("investment_debate_state") or {}
        risk = state.get("risk_debate_state") or {}
        return {
            "company_of_interest": state.get("company_of_interest"),
            "trade_date": state.get("trade_date"),
            "market_report": state.get("market_report", ""),
            "sentiment_report": state.get("sentiment_report", ""),
            "news_report": state.get("news_report", ""),
            "fundamentals_report": state.get("fundamentals_report", ""),
            "bull_history": debate.get("bull_history", ""),
            "bear_history": debate.get("bear_history", ""),
            "investment_plan": state.get("investment_plan", ""),
            "trader_investment_plan": state.get("trader_investment_plan", ""),
            "aggressive_history": risk.get("aggressive_history", ""),
            "conservative_history": risk.get("conservative_history", ""),
            "neutral_history": risk.get("neutral_history", ""),
            "pre_verifier_final_trade_decision": state.get("pre_verifier_final_trade_decision", ""),
            "final_trade_decision": state.get("final_trade_decision", ""),
            "report_verification": state.get("report_verification", {}),
            "report_quality": state.get("report_quality", {}),
            "evidence_ledger": state.get("evidence_ledger", []),
            "final_structured_decision": state.get("final_structured_decision", {}),
        }

    def _ingest_messages(self, snapshot: RunSnapshot, messages) -> None:
        existing_ids = {message.id for message in snapshot.messages}
        existing_tool_signatures = {(tool.name, tool.args) for tool in snapshot.tool_calls}
        for message in messages:
            message_id = getattr(message, "id", None)
            for tool_call in getattr(message, "tool_calls", []) or []:
                if isinstance(tool_call, dict):
                    name = str(tool_call.get("name", "")).strip()
                    args = str(tool_call.get("args", "")).strip()
                else:
                    name = str(getattr(tool_call, "name", "")).strip()
                    args = str(getattr(tool_call, "args", "")).strip()
                signature = (name, args)
                if not name or signature in existing_tool_signatures:
                    continue
                existing_tool_signatures.add(signature)
                snapshot.tool_calls.append(
                    ToolCallView(
                        timestamp=datetime.utcnow().strftime("%H:%M:%S"),
                        name=name,
                        args=args,
                    )
                )
            if message_id and message_id in existing_ids:
                continue
            content = extract_text(getattr(message, "content", ""))
            if not content:
                continue
            if isinstance(message, HumanMessage):
                kind = "User"
            elif isinstance(message, ToolMessage):
                kind = "Tool"
            elif isinstance(message, AIMessage):
                kind = "Agent"
            else:
                kind = "System"
            snapshot.messages.append(
                MessageView(
                    timestamp=datetime.utcnow().strftime("%H:%M:%S"),
                    kind=kind,
                    content=content,
                    id=message_id or datetime.utcnow().strftime("%H%M%S%f"),
                )
            )
        snapshot.messages = snapshot.messages[-80:]
        snapshot.tool_calls = snapshot.tool_calls[-80:]

    @staticmethod
    def _set_agent(snapshot: RunSnapshot, key: str, status: str) -> None:
        for agent in snapshot.agents:
            if agent.key == key:
                agent.status = status
                return

    @staticmethod
    def _set_report(snapshot: RunSnapshot, key: str, content: str) -> None:
        for report in snapshot.reports:
            if report.key == key:
                report.content = content
                return
