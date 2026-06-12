from __future__ import annotations

from .aggressive import _create_risk_node


def create_neutral_debator(llm, offline_runtime):
    return _create_risk_node("Neutral", llm, offline_runtime)
