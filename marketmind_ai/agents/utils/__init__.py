"""Lazy exports for agent utility helpers and typed research models."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "ACTIONABLE": "marketmind_ai.agents.utils.rating",
    "AnalysisContext": "marketmind_ai.agents.utils.agent_utils",
    "FundamentalSnapshot": "marketmind_ai.agents.utils.research_types",
    "IndicatorSet": "marketmind_ai.agents.utils.research_types",
    "MarketSnapshot": "marketmind_ai.agents.utils.research_types",
    "MarketMindMemoryLog": "marketmind_ai.agents.utils.memory",
    "MarketMindMemoryRetriever": "marketmind_ai.agents.utils.memory_retrieval",
    "MemoryEntry": "marketmind_ai.agents.utils.research_types",
    "NO_RECOMMENDATION": "marketmind_ai.agents.utils.rating",
    "NewsItem": "marketmind_ai.agents.utils.research_types",
    "PriceBar": "marketmind_ai.agents.utils.research_types",
    "RATINGS_5_TIER": "marketmind_ai.agents.utils.rating",
    "ResearchBundle": "marketmind_ai.agents.utils.research_types",
    "bind_structured": "marketmind_ai.agents.utils.structured",
    "build_instrument_context": "marketmind_ai.agents.utils.agent_utils",
    "build_toolsets": "marketmind_ai.agents.utils.agent_utils",
    "create_msg_delete": "marketmind_ai.agents.utils.agent_utils",
    "get_language_instruction": "marketmind_ai.agents.utils.agent_utils",
    "invoke_structured_or_freetext": "marketmind_ai.agents.utils.structured",
    "parse_confidence": "marketmind_ai.agents.utils.rating",
    "parse_decision_status": "marketmind_ai.agents.utils.rating",
    "parse_rating": "marketmind_ai.agents.utils.rating",
    "score_bundle": "marketmind_ai.agents.utils.agent_utils",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
