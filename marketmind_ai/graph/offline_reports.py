from __future__ import annotations

from typing import Dict, List, Tuple

from ..agents.utils.research_types import ResearchBundle
from .decision import EvidenceItem, FinalDecision


def _is_chinese(language: str) -> bool:
    return language.strip().lower().startswith("chinese") or language.strip() in {"中文", "简体中文", "繁體中文"}


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def num(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.2f}"


def _trend_phrase(score: float, language: str) -> str:
    if _is_chinese(language):
        if score > 20:
            return "趋势明显偏多"
        if score > 5:
            return "趋势温和偏多"
        if score < -20:
            return "趋势明显偏空"
        if score < -5:
            return "趋势温和偏空"
        return "趋势尚不明确"
    if score > 20:
        return "trend is decisively bullish"
    if score > 5:
        return "trend is modestly constructive"
    if score < -20:
        return "trend is decisively bearish"
    if score < -5:
        return "trend is modestly defensive"
    return "trend is unresolved"


def market_report(bundle: ResearchBundle, component_score: float, language: str) -> str:
    market = bundle.market
    indicators = market.indicators
    if _is_chinese(language):
        return (
            "市场结构\n"
            f"- 最新收盘价: {market.latest_close:.2f}\n"
            f"- 1日/5日/20日变动: {market.change_1d_pct:.2f}% / {market.change_5d_pct:.2f}% / {market.change_20d_pct:.2f}%\n"
            f"- SMA20 / SMA50: {indicators.sma_20 or 0:.2f} / {indicators.sma_50 or 0:.2f}\n"
            f"- RSI14 / ATR14: {indicators.rsi_14 or 0:.1f} / {indicators.atr_14 or 0:.2f}\n"
            f"- 波动率(20日): {pct(indicators.volatility_20)}\n"
            "解读\n"
            f"- 当前{_trend_phrase(component_score, language)}。\n"
            "- 若价格站稳 SMA20 且 RSI 未进入极端区间，短线延续概率更高。\n"
            "- 若 ATR 快速放大但趋势分数回落，需要把这视为风险而非确认。\n"
        )
    return (
        "Market Structure\n"
        f"- Last close: {market.latest_close:.2f}\n"
        f"- 1d / 5d / 20d change: {market.change_1d_pct:.2f}% / {market.change_5d_pct:.2f}% / {market.change_20d_pct:.2f}%\n"
        f"- SMA20 / SMA50: {indicators.sma_20 or 0:.2f} / {indicators.sma_50 or 0:.2f}\n"
        f"- RSI14 / ATR14: {indicators.rsi_14 or 0:.1f} / {indicators.atr_14 or 0:.2f}\n"
        f"- 20d volatility: {pct(indicators.volatility_20)}\n"
        "Interpretation\n"
        f"- The tape says the {_trend_phrase(component_score, language)}.\n"
        "- Holding above the short moving average without an overheated RSI improves continuation odds.\n"
        "- If ATR expands while trend quality deteriorates, volatility should be treated as risk rather than confirmation.\n"
    )


def sentiment_report(bundle: ResearchBundle, component_score: float, language: str) -> str:
    headlines = [item.title for item in bundle.news[: min(3, len(bundle.news))]]
    joined = "; ".join(headlines) or "No recent headlines were available."
    if _is_chinese(language):
        return (
            "情绪脉搏\n"
            f"- 聚合情绪分数: {bundle.sentiment_score:.2f}\n"
            f"- 代表性标题: {joined}\n"
            "解读\n"
            f"- 当前市场情绪对应的行为倾向为: {_trend_phrase(component_score, language)}。\n"
            "- 该席位更关注叙事强弱和参与者偏好，而不是直接给出财务判断。\n"
        )
    return (
        "Crowd Pulse\n"
        f"- Aggregate sentiment score: {bundle.sentiment_score:.2f}\n"
        f"- Representative headlines: {joined}\n"
        "Interpretation\n"
        f"- The narrative temperature suggests the {_trend_phrase(component_score, language)}.\n"
        "- This desk cares more about participation and story strength than about pure accounting quality.\n"
    )


def news_report(bundle: ResearchBundle, component_score: float, language: str) -> str:
    lines = []
    for item in bundle.news[:4]:
        lines.append(f"- {item.published_at}: {item.title}")
    rendered = "\n".join(lines) if lines else "- No recent news items."
    if _is_chinese(language):
        return (
            "事件时间线\n"
            f"{rendered}\n"
            "解读\n"
            f"- 近期催化的综合偏向为: {_trend_phrase(component_score, language)}。\n"
            "- 如果正面事件集中且时间较新，方向性判断会更可靠；反之更适合保持谨慎。\n"
        )
    return (
        "Catalyst Timeline\n"
        f"{rendered}\n"
        "Interpretation\n"
        f"- The recent catalyst slate reads as {_trend_phrase(component_score, language)}.\n"
        "- Fresh, clustered catalysts are worth more than stale headlines; mixed chronology lowers conviction.\n"
    )


def fundamentals_report(bundle: ResearchBundle, component_score: float, language: str) -> str:
    fundamentals = bundle.fundamentals
    if _is_chinese(language):
        return (
            "基本面快照\n"
            f"- 公司: {fundamentals.company_name}\n"
            f"- 市值: {num(fundamentals.market_cap)}\n"
            f"- 收入增长: {pct(fundamentals.revenue_growth)}\n"
            f"- 毛利率 / 营业利润率: {pct(fundamentals.gross_margin)} / {pct(fundamentals.operating_margin)}\n"
            f"- 市盈率(TTM/FWD): {fundamentals.trailing_pe or 0:.1f} / {fundamentals.forward_pe or 0:.1f}\n"
            f"- 负债权益比 / 流动比率: {fundamentals.debt_to_equity or 0:.2f} / {fundamentals.current_ratio or 0:.2f}\n"
            "解读\n"
            f"- 经营与财务质量整体上表现为{_trend_phrase(component_score, language)}。\n"
            "- 高增长但估值过高时，需要由执行计划和风险席位补充约束。\n"
        )
    return (
        "Fundamental Snapshot\n"
        f"- Company: {fundamentals.company_name}\n"
        f"- Market cap: {num(fundamentals.market_cap)}\n"
        f"- Revenue growth: {pct(fundamentals.revenue_growth)}\n"
        f"- Gross / operating margin: {pct(fundamentals.gross_margin)} / {pct(fundamentals.operating_margin)}\n"
        f"- P/E (TTM/FWD): {fundamentals.trailing_pe or 0:.1f} / {fundamentals.forward_pe or 0:.1f}\n"
        f"- Debt / equity and current ratio: {fundamentals.debt_to_equity or 0:.2f} / {fundamentals.current_ratio or 0:.2f}\n"
        "Interpretation\n"
        f"- Business quality currently screens as {_trend_phrase(component_score, language)}.\n"
        "- Strong growth can still be a weak trade if valuation and execution discipline do not support it.\n"
    )


def bull_case(bundle: ResearchBundle, strengths: List[str], language: str) -> str:
    lines = "\n".join(f"- {item}" for item in strengths)
    if _is_chinese(language):
        return "多头备忘录\n" + lines + "\n- 只有当这些优势同时具备持续性与价格确认时，多头才值得加仓。\n"
    return "Bull Memo\n" + lines + "\n- The long case is strongest when these advantages remain durable and are confirmed by price action.\n"


def bear_case(bundle: ResearchBundle, risks: List[str], language: str) -> str:
    lines = "\n".join(f"- {item}" for item in risks)
    if _is_chinese(language):
        return "空头备忘录\n" + lines + "\n- 只要其中两项以上同时恶化，就应降低方向性暴露。\n"
    return "Bear Memo\n" + lines + "\n- If two or more of these risks deteriorate together, directional exposure should be reduced.\n"


def investment_chair(action: str, confidence: float, thesis: str, language: str) -> str:
    if _is_chinese(language):
        return (
            "投资主席结论\n"
            f"- 初步动作: {action}\n"
            f"- 置信度: {confidence:.1f}\n"
            f"- 核心观点: {thesis}\n"
            "- 这一步只决定是否具备可交易结构，不代表最终仓位已经通过风控。\n"
        )
    return (
        "Investment Chair\n"
        f"- Provisional action: {action}\n"
        f"- Confidence: {confidence:.1f}\n"
        f"- Core thesis: {thesis}\n"
        "- This step decides whether a tradeable structure exists; it does not yet approve final sizing.\n"
    )


def execution_plan(action: str, entry: str, stop: str, target: str, language: str) -> str:
    if _is_chinese(language):
        return (
            "执行计划\n"
            f"- 动作: {action}\n"
            f"- 入场: {entry}\n"
            f"- 止损/失效: {stop}\n"
            f"- 目标: {target}\n"
            "- 若触发条件无法满足，应自动退回观察状态。\n"
        )
    return (
        "Execution Plan\n"
        f"- Action: {action}\n"
        f"- Entry: {entry}\n"
        f"- Stop / invalidation: {stop}\n"
        f"- Target: {target}\n"
        "- If the setup cannot satisfy these conditions, it should fall back to watchlist mode.\n"
    )


def risk_view(name: str, stance: str, language: str) -> str:
    if _is_chinese(language):
        return f"{name}\n- 立场: {stance}\n- 风险席位关注的是仓位承受能力，而不是单纯判断方向对错。\n"
    return f"{name}\n- Stance: {stance}\n- This desk focuses on survivability and sizing discipline, not just directional correctness.\n"


def render_final_decision(decision: FinalDecision, language: str) -> str:
    evidence_lines = []
    for index, item in enumerate(decision.evidence_items, start=1):
        evidence_lines.append(
            f"{index}. [{item.strength}][{item.kind}] Claim: {item.claim} | Source: {item.source} | "
            f"Date: {item.source_date} | Detail: {item.detail}"
        )
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "1. [low][gap] Claim: Evidence was insufficient | Source: internal | Date: n/a | Detail: insufficient confirmation"
    if _is_chinese(language):
        return (
            f"最终决策\n- 标的: {decision.ticker}\n- 动作: {decision.action}\n- 置信度: {decision.confidence:.1f}\n"
            f"- 核心观点: {decision.thesis}\n- 时间框架: {decision.time_horizon}\n- 执行摘要: {decision.entry_plan}\n"
            f"- 风险控制: {decision.risk_controls}\n- 证据缺口: {decision.evidence_gap}\n证据包\n{evidence_block}\n"
            f"结论说明\n{decision.rationale}"
        )
    return (
        f"Final Decision\n- Ticker: {decision.ticker}\n- Action: {decision.action}\n- Confidence: {decision.confidence:.1f}\n"
        f"- Thesis: {decision.thesis}\n- Time horizon: {decision.time_horizon}\n- Execution summary: {decision.entry_plan}\n"
        f"- Risk controls: {decision.risk_controls}\n- Evidence gap: {decision.evidence_gap}\nEvidence Pack\n{evidence_block}\n"
        f"Rationale\n{decision.rationale}"
    )


def bull_bear_lists(scores: Dict[str, float], bundle: ResearchBundle, language: str) -> Tuple[List[str], List[str]]:
    bulls = [
        f"20-day price change is {bundle.market.change_20d_pct:.1f}% with market score {scores['market']:.1f}.",
        f"Sentiment score is {bundle.sentiment_score:.2f}, which supports participation if catalysts stay fresh.",
        f"Revenue growth is {pct(bundle.fundamentals.revenue_growth)} with operating margin {pct(bundle.fundamentals.operating_margin)}.",
    ]
    bears = [
        f"Trailing P/E is {bundle.fundamentals.trailing_pe or 0:.1f}, leaving valuation exposed to even small execution misses.",
        f"20-day volatility is {pct(bundle.market.indicators.volatility_20)}, so adverse moves can overwhelm thesis quality.",
        "Macro liquidity, guidance quality, or regulation can reverse the narrative faster than fundamentals can respond.",
    ]
    return bulls, bears
