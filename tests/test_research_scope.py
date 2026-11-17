import pytest
from pydantic import ValidationError

from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.graph.review import report_hash
from marketmind_ai.web.models import AnalysisRequest as WebAnalysisRequest
from marketmind_ai.web.runner import to_core_request


PAYLOAD = {
    "ticker": "NVDA", "analysis_date": "2026-06-12", "llm_provider": "offline",
    "quick_model": "heuristic-fast", "deep_model": "heuristic-deep",
}


@pytest.mark.parametrize("objective,horizon", [
    ("company_overview", None), ("earnings", "1_to_4_weeks"),
    ("risk_counterevidence", "6_to_12_months"), (None, "1_to_3_months"), (None, None),
])
def test_web_and_core_accept_optional_research_presets(objective, horizon):
    payload = {**PAYLOAD, "research_objective": objective, "research_horizon": horizon}
    request = to_core_request(WebAnalysisRequest.model_validate(payload))
    assert request.research_objective == objective
    assert request.research_horizon == horizon
    assert AnalysisRequest.from_mapping(PAYLOAD).research_horizon is None


@pytest.mark.parametrize("setting,value", [
    ("research_objective", "custom"), ("research_horizon", 12), ("research_horizon", "forever"),
])
def test_unknown_presets_are_rejected_by_both_request_boundaries(setting, value):
    payload = {**PAYLOAD, setting: value}
    with pytest.raises(ValidationError):
        WebAnalysisRequest.model_validate(payload)
    with pytest.raises(ValueError, match=setting):
        AnalysisRequest.from_mapping(payload)


def test_review_hash_binds_scope_and_preserves_legacy_default():
    old = {"ticker": "NVDA", "final_signal": "No Recommendation"}
    original = report_hash(old)
    assert report_hash({**old, "research_objective": None, "research_horizon": None}) == original
    assert report_hash({**old, "research_objective": "earnings"}) != original
    assert report_hash({**old, "research_horizon": "1_to_4_weeks"}) != original


def test_engine_builds_each_run_with_its_own_manager_scope(tmp_path, monkeypatch):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph
    from marketmind_ai.graph import runtime_support

    workflow = MarketMindGraph(storage_root=tmp_path)
    captured = []
    for name in ("create_research_manager", "create_portfolio_manager"):
        original = getattr(runtime_support, name)

        def capture(*args, _original=original, **kwargs):
            captured.append(kwargs["scope_guidance"])
            return _original(*args, **kwargs)

        monkeypatch.setattr(runtime_support, name, capture)
    for settings in (
        {"research_objective": "earnings", "research_horizon": "1_to_3_months"},
        {"research_objective": "risk_counterevidence", "research_horizon": "6_to_12_months"},
        {},
    ):
        engine = runtime_support.GraphResearchEngine(
            request=AnalysisRequest.from_mapping({**PAYLOAD, **settings}),
            resolution={"resolved_symbol": "NVDA"}, journal=workflow.journal, verifier=workflow.verifier,
        )
        engine.build_graph()
    assert "reported earnings" in captured[0] and "1–3 months" in captured[1]
    assert "downside risks and counterevidence" in captured[2] and "6–12 months" in captured[3]
    assert captured[4:] == ["", ""]
