from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode

from ..agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from ..agents.schemas import (
    DecisionStatus,
    EvidenceItem,
    EvidenceKind,
    EvidenceStrength,
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
)
from ..agents.utils import AnalysisContext, build_toolsets, create_msg_delete, score_bundle
from ..graph.decision import FinalDecision
from ..llm_clients import ModelBundle, build_model_bundle
from ..reporting import ReportQualityScorer, build_evidence_ledger
from ..verification import DecisionVerifier
from .conditional_logic import ConditionalLogic as GraphConditionalLogic
from .offline_reports import bear_case, bull_bear_lists, bull_case, fundamentals_report, market_report, news_report, sentiment_report
from .propagation import Propagator
from .request import AnalysisRequest
from .setup import GraphSetup
from .storage import DecisionJournal


def build_offline_data_vendor_config() -> dict[str, str]:
    return {
        "core_stock_apis": "offline",
        "technical_indicators": "offline",
        "fundamental_data": "offline",
        "fundamental_document_data": "offline",
        "news_data": "offline",
        "news_document_data": "offline",
        "symbol_resolution": "offline",
    }


@dataclass
class AutonomousRuntime:
    request: AnalysisRequest
    resolution: dict
    models: ModelBundle
    data_context: AnalysisContext
    verifier: DecisionVerifier

    def bundle(self):
        return self.data_context.load_bundle(
            self.resolution["resolved_symbol"],
            resolution=self.resolution,
        )

    def scores(self) -> Dict[str, float]:
        return score_bundle(self.bundle())

    def evidence_pack(self) -> list[EvidenceItem]:
        bundle = self.bundle()
        scores = self.scores()
        symbol = self.resolution["resolved_symbol"]
        retrieved_at = f"{self.request.analysis_date}T00:00:00Z"
        latest_bar_date = bundle.market.bars[-1].date
        news_item = bundle.news[0] if bundle.news else None
        news_date = news_item.published_at if news_item else latest_bar_date
        news_url = (
            news_item.url
            if news_item and news_item.url
            else f"marketmind://{bundle.data_source}/{symbol}/news/{news_date}/1"
        )
        return [
            EvidenceItem(
                claim=f"20-session price change is {bundle.market.change_20d_pct:.1f}% and the tape score is {scores['market']:.1f}.",
                evidence_type=EvidenceKind.FACT,
                source="Market Analyst",
                source_date=latest_bar_date,
                excerpt=f"Close={bundle.market.latest_close:.2f}, RSI={bundle.market.indicators.rsi_14 or 0:.1f}",
                interpretation="Recent price structure and momentum still matter for timing and conviction.",
                strength=EvidenceStrength.HIGH if scores["market"] > 10 else EvidenceStrength.MEDIUM,
                provider=bundle.data_source,
                url=f"marketmind://{bundle.data_source}/{symbol}/prices/{latest_bar_date}",
                source_type="price",
                retrieved_at=retrieved_at,
                raw_source_id=f"{symbol}:price:{latest_bar_date}",
            ),
            EvidenceItem(
                claim=f"News and sentiment combined indicate a catalyst tone of {bundle.sentiment_score:.2f}.",
                evidence_type=EvidenceKind.FACT,
                source="News Analyst",
                source_date=news_date,
                excerpt=news_item.title if news_item else "No recent headlines were returned.",
                interpretation="Fresh catalysts strengthen or weaken follow-through beyond the chart alone.",
                strength=EvidenceStrength.MEDIUM,
                provider=bundle.data_source,
                url=news_url,
                source_type="news",
                retrieved_at=retrieved_at,
                raw_source_id=f"{symbol}:news:{news_date}:1",
            ),
            EvidenceItem(
                claim=f"Business quality reflects revenue growth {bundle.fundamentals.revenue_growth or 0:.2f} and operating margin {bundle.fundamentals.operating_margin or 0:.2f}.",
                evidence_type=EvidenceKind.FACT,
                source="Fundamentals Analyst",
                source_date=latest_bar_date,
                excerpt=f"Debt/Equity={bundle.fundamentals.debt_to_equity or 0:.2f}, P/E={bundle.fundamentals.trailing_pe or 0:.1f}",
                interpretation="Growth durability and balance-sheet resilience constrain how much risk the setup deserves.",
                strength=EvidenceStrength.HIGH if scores["fundamentals"] > 6 else EvidenceStrength.MEDIUM,
                provider=bundle.data_source,
                url=f"marketmind://{bundle.data_source}/{symbol}/fundamentals/{latest_bar_date}",
                source_type="fundamentals",
                retrieved_at=retrieved_at,
                raw_source_id=f"{symbol}:fundamentals:{latest_bar_date}",
            ),
        ]

    def memory_context(self, audience: str) -> str:
        bundle = self.bundle()
        if not bundle.memory:
            return ""
        lines = []
        for item in bundle.memory[-3:]:
            lines.append(
                f"{item.analysis_date}: {item.action} at {item.confidence:.1f} confidence. Thesis: {item.thesis}"
            )
        prefix = {
            "research": "Prior decisions that may inform the current thesis:",
            "trader": "Past transaction framing that may improve execution discipline:",
            "portfolio": "Historical lessons and outcome memory:",
        }.get(audience, "Historical memory:")
        return prefix + "\n" + "\n".join(f"- {line}" for line in lines)

    def offline_tool_call_message(self, role: str, state) -> AIMessage:
        symbol = state["company_of_interest"]
        date = state["trade_date"]
        call_specs = {
            "market": [
                ("get_stock_data", {"symbol": symbol, "analysis_date": date}),
                ("get_indicators", {"symbol": symbol, "analysis_date": date, "indicators": ["close_50_sma", "close_10_ema", "rsi", "atr", "boll"]}),
            ],
            "sentiment": [("get_news", {"symbol": symbol, "analysis_date": date, "limit": 6})],
            "news": [
                ("get_news_event_timeline", {"symbol": symbol, "analysis_date": date, "limit": 8}),
                ("get_news", {"symbol": symbol, "analysis_date": date, "limit": 8}),
                ("get_global_news", {"analysis_date": date, "theme": "macro"}),
                ("get_insider_transactions", {"symbol": symbol, "analysis_date": date}),
            ],
            "fundamentals": [
                ("get_fundamentals", {"symbol": symbol}),
                ("get_balance_sheet", {"symbol": symbol}),
                ("get_cashflow", {"symbol": symbol}),
                ("get_income_statement", {"symbol": symbol}),
                ("get_fundamental_document_context", {"symbol": symbol, "analysis_date": date}),
            ],
        }
        tool_calls = []
        for index, (name, args) in enumerate(call_specs[role], start=1):
            tool_calls.append({"name": name, "args": args, "id": f"{role}_tool_{index}", "type": "tool_call"})
        return AIMessage(content="", tool_calls=tool_calls)

    def offline_analyst_report(self, role: str) -> str:
        bundle = self.bundle()
        scores = self.scores()
        if role == "market":
            return market_report(bundle, scores["market"], self.request.output_language)
        if role == "sentiment":
            return sentiment_report(bundle, scores["sentiment"], self.request.output_language)
        if role == "news":
            return news_report(bundle, scores["news"], self.request.output_language)
        return fundamentals_report(bundle, scores["fundamentals"], self.request.output_language)

    def offline_research_plan(self, selected_analysts: list[str]) -> ResearchPlan:
        bundle = self.bundle()
        scores = self.scores()
        used = [scores[key] for key in selected_analysts]
        combined = sum(used) / max(len(used), 1)
        completeness = len(selected_analysts) / 4.0
        if completeness < 0.5 or abs(combined) < 6:
            status = DecisionStatus.NO_RECOMMENDATION
            rating = None
        elif combined >= 24:
            status = DecisionStatus.ACTIONABLE
            rating = PortfolioRating.BUY
        elif combined >= 12:
            status = DecisionStatus.ACTIONABLE
            rating = PortfolioRating.OVERWEIGHT
        elif combined <= -24:
            status = DecisionStatus.ACTIONABLE
            rating = PortfolioRating.SELL
        elif combined <= -12:
            status = DecisionStatus.ACTIONABLE
            rating = PortfolioRating.UNDERWEIGHT
        else:
            status = DecisionStatus.ACTIONABLE
            rating = PortfolioRating.HOLD
        confidence = int(max(35, min(91, 48 + abs(combined) * 1.1 + completeness * 8)))
        evidence_gap = self._evidence_gap(status == DecisionStatus.NO_RECOMMENDATION)
        return ResearchPlan(
            recommendation_status=status,
            recommendation=rating,
            confidence=confidence,
            confidence_rationale=f"Composite score is {combined:.1f} across {len(selected_analysts)} analyst desks with completeness {completeness:.2f}.",
            rationale=self._thesis_text(rating.value if rating else "No Recommendation"),
            primary_evidence=self.evidence_pack()[: (3 if status == DecisionStatus.ACTIONABLE else 1)],
            key_risks=self._key_risks(),
            evidence_gap=evidence_gap,
            strategic_actions=self._strategic_actions(rating.value if rating else "No Recommendation"),
        )

    def offline_trader_proposal(self, research_plan: ResearchPlan) -> TraderProposal:
        bundle = self.bundle()
        latest = bundle.market.latest_close
        atr = bundle.market.indicators.atr_14 or max(1.0, latest * 0.03)
        action = None
        entry = stop = sizing = None
        if research_plan.recommendation_status == DecisionStatus.ACTIONABLE:
            if research_plan.recommendation in {PortfolioRating.BUY, PortfolioRating.OVERWEIGHT}:
                action = TraderAction.BUY
                entry = round(latest, 2)
                stop = round(latest - 1.5 * atr, 2)
                sizing = "4-6% of portfolio"
            elif research_plan.recommendation in {PortfolioRating.SELL, PortfolioRating.UNDERWEIGHT}:
                action = TraderAction.SELL
                entry = round(latest, 2)
                stop = round(latest + 1.5 * atr, 2)
                sizing = "2-4% net short or equivalent hedge"
            else:
                action = TraderAction.HOLD
                sizing = "Maintain current sizing"
        status = research_plan.recommendation_status
        return TraderProposal(
            action_status=status,
            action=action if status == DecisionStatus.ACTIONABLE else None,
            confidence=max(28, min(92, research_plan.confidence - (4 if action == TraderAction.HOLD else 0))),
            confidence_rationale="Trader confidence inherits the research plan while discounting execution slippage and volatility risk.",
            reasoning=f"Trader translation of the research plan: {research_plan.rationale}",
            primary_evidence=research_plan.primary_evidence,
            risk_controls=self._key_risks()[:2] + [self._execution_stop_text()],
            evidence_gap=research_plan.evidence_gap,
            entry_price=entry if action and action != TraderAction.HOLD else None,
            stop_loss=stop if action and action != TraderAction.HOLD else None,
            position_sizing=sizing if status == DecisionStatus.ACTIONABLE else None,
        )

    def offline_portfolio_decision(self, research_plan: ResearchPlan, trader_plan: TraderProposal) -> PortfolioDecision:
        bundle = self.bundle()
        latest = bundle.market.latest_close
        rating = research_plan.recommendation
        status = research_plan.recommendation_status
        confidence = min(94, max(25, int((research_plan.confidence + trader_plan.confidence) / 2)))
        price_target = None
        if status == DecisionStatus.ACTIONABLE and rating is not None:
            if rating in {PortfolioRating.BUY, PortfolioRating.OVERWEIGHT}:
                price_target = round(latest * 1.08, 2)
            elif rating in {PortfolioRating.SELL, PortfolioRating.UNDERWEIGHT}:
                price_target = round(latest * 0.92, 2)
        return PortfolioDecision(
            decision_status=status,
            rating=rating,
            confidence=confidence,
            confidence_rationale="Final confidence reflects the overlap between the research decision, execution viability, and the surviving risk objections.",
            executive_summary=self._strategic_actions(rating.value if rating else "No Recommendation"),
            investment_thesis=self._thesis_text(rating.value if rating else "No Recommendation"),
            primary_evidence=self.evidence_pack()[: (3 if status == DecisionStatus.ACTIONABLE else 1)],
            key_risks=self._key_risks(),
            evidence_gap=self._evidence_gap(status == DecisionStatus.NO_RECOMMENDATION),
            price_target=price_target if status == DecisionStatus.ACTIONABLE else None,
            time_horizon="1-4 weeks" if status == DecisionStatus.ACTIONABLE else None,
        )

    def _execution_stop_text(self) -> str:
        bundle = self.bundle()
        latest = bundle.market.latest_close
        atr = bundle.market.indicators.atr_14 or max(1.0, latest * 0.03)
        return f"Use an invalidation stop roughly 1.5 ATR away from the current price ({round(1.5 * atr, 2)} points)."

    def _strategic_actions(self, rating: str) -> str:
        if rating in {"Buy", "Overweight"}:
            return "Scale in only while momentum, catalyst quality, and balance-sheet confidence remain aligned."
        if rating in {"Sell", "Underweight"}:
            return "Reduce exposure or hedge strength rallies while the evidence stack remains deteriorated."
        if rating == "Hold":
            return "Maintain only core exposure and wait for either stronger confirmation or a cleaner invalidation."
        return "Do not force a trade; wait for fresher evidence and cleaner cross-desk agreement."

    def _thesis_text(self, rating: str) -> str:
        bundle = self.bundle()
        if rating in {"Buy", "Overweight"}:
            return f"{bundle.fundamentals.company_name} has enough alignment across tape, catalysts, and business quality to justify a constructive bias."
        if rating in {"Sell", "Underweight"}:
            return f"{bundle.fundamentals.company_name} is losing support across price structure and narrative quality quickly enough to justify defensive positioning."
        if rating == "Hold":
            return f"{bundle.fundamentals.company_name} has a mixed evidence stack: not weak enough to press short, not clean enough to chase long."
        return f"{bundle.fundamentals.company_name} still lacks a decisive separation between bullish and bearish evidence."

    def _evidence_gap(self, no_recommendation: bool) -> str:
        bundle = self.bundle()
        gaps = []
        if not bundle.news:
            gaps.append("recent catalysts could not be confirmed")
        if (bundle.fundamentals.trailing_pe or 0.0) > 45:
            gaps.append("valuation leaves limited room for execution misses")
        if no_recommendation:
            gaps.append("the evidence stack did not separate signal from noise strongly enough")
        if not gaps:
            gaps.append("the thesis still needs ongoing monitoring for trend durability")
        return "; ".join(gaps)

    def _key_risks(self) -> list[str]:
        bundle = self.bundle()
        risks = []
        if (bundle.fundamentals.trailing_pe or 0.0) > 40:
            risks.append("Valuation is demanding enough that strong execution may already be priced in.")
        if (bundle.market.indicators.volatility_20 or 0.0) > 0.04:
            risks.append("Volatility is elevated, so conviction can decay faster than the fundamental thesis.")
        risks.append("Catalyst tone can reverse quickly if macro liquidity or guidance quality deteriorates.")
        return risks[:3]

    @staticmethod
    def bull_bear_lists(scores, bundle, language):
        return bull_bear_lists(scores, bundle, language)

    @staticmethod
    def bull_case(bundle, bulls, language):
        return bull_case(bundle, bulls, language)

    @staticmethod
    def bear_case(bundle, bears, language):
        return bear_case(bundle, bears, language)


class GraphResearchEngine:
    def __init__(
        self,
        *,
        request: AnalysisRequest,
        resolution: dict,
        journal: DecisionJournal,
        verifier: DecisionVerifier,
        max_recur_limit: int = 100,
    ) -> None:
        self.request = request
        self.resolution = resolution
        self.journal = journal
        self.verifier = verifier
        self.models = build_model_bundle(request)
        self.data_context = AnalysisContext(journal=journal, analysis_date=request.analysis_date)
        self.runtime = AutonomousRuntime(
            request=request,
            resolution=resolution,
            models=self.models,
            data_context=self.data_context,
            verifier=verifier,
        )
        self.toolsets = build_toolsets(self.data_context)
        self.conditional = GraphConditionalLogic(max_debate_rounds=request.research_depth, max_risk_rounds=request.research_depth)
        self.graph_setup = GraphSetup(self.conditional)
        self.propagator = Propagator(max_recur_limit=max_recur_limit)

    def build_graph(self):
        selected = [self._runtime_key(item) for item in self.request.analysts]
        analyst_nodes = {
            "market": create_market_analyst(self.models.quick, self.toolsets["market"], self.runtime),
            "sentiment": create_sentiment_analyst(self.models.quick, self.toolsets["sentiment"], self.runtime),
            "news": create_news_analyst(self.models.quick, self.toolsets["news"], self.runtime),
            "fundamentals": create_fundamentals_analyst(self.models.quick, self.toolsets["fundamentals"], self.runtime),
        }
        analyst_nodes = {key: value for key, value in analyst_nodes.items() if key in selected}
        delete_nodes = {key: create_msg_delete() for key in analyst_nodes}
        tool_nodes = {key: ToolNode(self.toolsets[key]) for key in analyst_nodes}
        shared_nodes = {
            "Bull Researcher": create_bull_researcher(self.models.quick, self.runtime),
            "Bear Researcher": create_bear_researcher(self.models.quick, self.runtime),
            "Research Manager": create_research_manager(self.models.deep, self.runtime),
            "Trader": create_trader(self.models.quick, self.runtime),
            "Aggressive Analyst": create_aggressive_debator(self.models.quick, self.runtime),
            "Conservative Analyst": create_conservative_debator(self.models.quick, self.runtime),
            "Neutral Analyst": create_neutral_debator(self.models.quick, self.runtime),
            "Portfolio Manager": create_portfolio_manager(self.models.deep, self.runtime, self._verify_and_payload),
        }
        return self.graph_setup.setup_graph(
            selected_analysts=selected,
            analyst_nodes=analyst_nodes,
            delete_nodes=delete_nodes,
            tool_nodes=tool_nodes,
            shared_nodes=shared_nodes,
        )

    def initial_state(self) -> dict:
        symbol = self.resolution["resolved_symbol"]
        return self.propagator.create_initial_state(
            ticker=symbol,
            original_query=self.request.ticker,
            company_name=self.resolution.get("company_name") or symbol,
            trade_date=self.request.analysis_date,
            output_language=self.request.output_language,
            selected_analysts=[self._runtime_key(item) for item in self.request.analysts],
            symbol_resolution=self.resolution,
            research_memory_context=self.runtime.memory_context("research"),
            trader_memory_context=self.runtime.memory_context("trader"),
            portfolio_memory_context=self.runtime.memory_context("portfolio"),
        )

    def _verify_decision(self, state, decision: PortfolioDecision) -> PortfolioDecision:
        final_state = self._final_state_for_verification(state, decision)
        result = self.verifier.verify_final_state(
            final_state,
            self.resolution,
        )
        if result.blocks_actionable_recommendation and decision.decision_status == DecisionStatus.ACTIONABLE:
            decision = decision.model_copy(deep=True)
            decision.decision_status = DecisionStatus.NO_RECOMMENDATION
            decision.rating = None
            decision.confidence = min(decision.confidence, 49)
            decision.evidence_gap = (decision.evidence_gap + "; verifier downgrade: " + result.summary).strip()
        return decision

    def _verify_and_payload(self, state, decision: PortfolioDecision) -> tuple[PortfolioDecision, dict]:
        final_decision = self._verify_decision(state, decision)
        reporting_payload = self._reporting_payload(state, final_decision)
        if (
            final_decision.decision_status == DecisionStatus.ACTIONABLE
            and self._quality_blocks_actionable(reporting_payload["report_quality"])
        ):
            final_decision = self._downgrade_for_quality(final_decision, reporting_payload["report_quality"])
            reporting_payload = self._reporting_payload(state, final_decision)
        return final_decision, reporting_payload

    def _reporting_payload(self, state, final_decision: PortfolioDecision) -> dict:
        verification = self._verification_payload(state, final_decision)
        structured = final_decision.model_dump(mode="json")
        evidence_ledger = build_evidence_ledger(structured, analysis_date=state["trade_date"])
        report_quality = ReportQualityScorer().score(
            final_state=self._final_state_for_verification(state, final_decision),
            structured_decision=structured,
            verification=verification,
        )
        return {
            "verification": verification,
            "report_quality": report_quality,
            "evidence_ledger": evidence_ledger,
        }

    @staticmethod
    def _quality_blocks_actionable(report_quality: dict) -> bool:
        blocking_codes = {
            "insufficient_evidence_count",
            "stale_evidence",
            "missing_key_risks",
            "missing_evidence_gap",
            "verifier_failed",
        }
        issue_codes = {str(issue.get("code")) for issue in report_quality.get("issues", []) if isinstance(issue, dict)}
        return report_quality.get("grade") == "Weak" or bool(blocking_codes & issue_codes)

    @staticmethod
    def _downgrade_for_quality(decision: PortfolioDecision, report_quality: dict) -> PortfolioDecision:
        downgraded = decision.model_copy(deep=True)
        downgraded.decision_status = DecisionStatus.NO_RECOMMENDATION
        downgraded.rating = None
        downgraded.confidence = min(downgraded.confidence, 49)
        downgraded.price_target = None
        downgraded.time_horizon = None
        summary = str(report_quality.get("summary") or "report quality did not clear the actionable threshold")
        downgraded.evidence_gap = (downgraded.evidence_gap + "; quality gate downgrade: " + summary).strip()
        return downgraded

    def _verification_payload(self, state, decision: PortfolioDecision) -> dict:
        final_state = self._final_state_for_verification(state, decision)
        result = self.verifier.verify_final_state(
            final_state,
            self.resolution,
        )
        return result.to_dict()

    def _final_state_for_verification(self, state, decision: PortfolioDecision) -> dict:
        from ..agents.schemas import render_portfolio_decision

        rendered = render_portfolio_decision(decision)
        return {
            "final_trade_decision": rendered,
            "pre_verifier_final_trade_decision": rendered,
            "investment_plan": state["investment_plan"],
            "trader_investment_plan": state["trader_investment_plan"],
            "trade_date": state["trade_date"],
            "company_of_interest": self.resolution["resolved_symbol"],
        }

    @staticmethod
    def _runtime_key(value: str) -> str:
        return "sentiment" if str(value).lower() == "social" else str(value).lower()
