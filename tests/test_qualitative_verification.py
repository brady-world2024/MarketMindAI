import pytest

from marketmind_ai.reporting.qualitative_verification import verify_core_claims

CUTOFF = "2026-06-12T20:00:00Z"
SOURCE = {
    "record_id": "news-1", "symbol": "NVDA", "provider": "yfinance",
    "admissibility": "included", "method": "get_news",
    "published_at": "2026-06-12T19:00:00Z",
    "content": {"summary": "Management expects demand to improve next quarter."},
}
DECISION = {
    "core_claims": [{"claim": "Demand has already improved.", "evidence_ids": ["E1"]}],
    "primary_evidence": [{"raw_source_id": "news-1", "excerpt": SOURCE["content"]["summary"]}],
}


@pytest.mark.parametrize("text,claim,status", [
    ("Demand increased this quarter.", "Demand improved this quarter.", "supported"),
    ("Demand weakened this quarter.", "Demand improved this quarter.", "contradicted"),
    ("The company introduced a new logo.", "Demand improved this quarter.", "insufficient"),
    (SOURCE["content"]["summary"], "Demand has already improved.", "insufficient"),
])
def test_anchored_review_persists_three_outcomes(text, claim, status):
    record = {**SOURCE, "content": {"summary": text}}
    decision = {"core_claims": [{"claim": claim, "evidence_ids": ["E1"]}],
                "primary_evidence": [{"raw_source_id": "news-1", "excerpt": text}]}

    def judge(claims):
        assert claims[0]["claim"] == claim
        assert claims[0]["citations"][0]["quote"] == text
        return [{"claim_number": 1, "status": status, "reason": "Compared with the supplied source."}]

    check, = verify_core_claims(decision, [record], "NVDA", CUTOFF, judge)
    assert check["status"] == status
    assert check["citations"][0]["record_id"] == "news-1"


@pytest.mark.parametrize("record", [
    {**SOURCE, "published_at": "2026-06-12T20:00:01Z"},
    {**SOURCE, "published_at": "2026-06-12"},
    {**SOURCE, "symbol": "AAPL"},
    {**SOURCE, "content": {"summary": "Demand declined."}},
])
def test_invalid_sources_are_never_sent_to_the_judge(record):
    def judge(_):
        pytest.fail("Invalid evidence must not reach the judge")

    check, = verify_core_claims(DECISION, [record], "NVDA", CUTOFF, judge)
    assert check["status"] == "insufficient"


def test_missing_judgment_fails_closed():
    check, = verify_core_claims(DECISION, [SOURCE], "NVDA", CUTOFF, lambda _: [])
    assert check["status"] == "insufficient"


def test_contradicted_core_claim_blocks_rating_and_clears_target(monkeypatch):
    from marketmind_ai.agents.schemas import DecisionStatus, PortfolioDecision, PortfolioRating
    from marketmind_ai.graph import runtime_support
    from test_report_quality_gate import _fresh_evidence

    engine = runtime_support.GraphResearchEngine.__new__(runtime_support.GraphResearchEngine)
    monkeypatch.setattr(runtime_support, "verify_active_claims", lambda *_: [
        {"status": "contradicted", "claim": "Demand improved.", "reason": "The source says demand weakened."}
    ], raising=False)
    monkeypatch.setattr(engine, "_verify_decision", lambda _, decision: decision)
    monkeypatch.setattr(engine, "_reporting_payload", lambda *_: {
        "verification": {"status": "passed", "issues": []}, "report_quality": {"grade": "Strong"}})
    decision = PortfolioDecision(
        decision_status=DecisionStatus.ACTIONABLE, rating=PortfolioRating.OVERWEIGHT, confidence=80,
        confidence_rationale="Corroboration.", executive_summary="Overweight.", investment_thesis="Demand improved.",
        primary_evidence=[_fresh_evidence("News"), _fresh_evidence("SEC")],
        key_risks=["Execution risk."], evidence_gap="Watch for revisions.", price_target=120, time_horizon="one month")
    final, result = engine._verify_and_payload({}, decision)
    assert final.decision_status == DecisionStatus.NO_RECOMMENDATION
    assert final.rating is None and final.price_target is None
    assert result["verification"]["blocks_actionable_recommendation"]
    assert result["verification"]["qualitative_claims"][0]["status"] == "contradicted"


def test_model_failure_returns_insufficient_without_leaking_error_details():
    def judge(_):
        raise RuntimeError("connection includes private credentials")

    check, = verify_core_claims(DECISION, [SOURCE], "NVDA", CUTOFF, judge)
    assert check["status"] == "insufficient"
    assert "credentials" not in check["reason"]
    assert check["citations"][0]["record_id"] == "news-1"


def test_live_reviewer_gets_only_frozen_evidence_and_demo_skips(monkeypatch):
    from types import SimpleNamespace
    from marketmind_ai.reporting import qualitative_verification as module

    snapshot = SimpleNamespace(symbol="NVDA", cutoff={"cutoff_at": CUTOFF}, data_mode="live")
    audit = SimpleNamespace(frozen_inputs=SimpleNamespace(snapshot=snapshot, source_records=[SOURCE]))
    monkeypatch.setattr(module, "get_audit", lambda: audit)

    class Model:
        def with_structured_output(self, schema):
            assert schema is module.ClaimVerdicts
            return self

        def invoke(self, messages):
            assert [message.type for message in messages] == ["system", "human"]
            assert "A forecast" in messages[0].content
            assert SOURCE["content"]["summary"] in messages[1].content
            return {"verdicts": [{"claim_number": 1, "status": "insufficient", "reason": "Forecast only."}]}

    check, = module.verify_active_claims(DECISION, Model())
    assert check["reason"] == "Forecast only."
    snapshot.data_mode = "demo"
    assert module.verify_active_claims(DECISION, None) == []


def test_market_only_claim_can_bind_to_verified_price_record():
    price = {**SOURCE, "record_id": "price-1", "method": "get_price_history",
             "content": [{"date": "2026-06-12", "close": 102.0}]}
    decision = {"core_claims": [{"claim": "The latest close was 102.", "evidence_ids": ["E1"]}],
                "primary_evidence": [{"raw_source_id": "price-1", "excerpt": '{"close": 102.0, "date": "2026-06-12"}'}]}
    check, = verify_core_claims(decision, [price], "NVDA", CUTOFF, lambda _: [
        {"claim_number": 1, "status": "supported", "reason": "Matches saved close."}])
    assert check["status"] == "supported"


def test_boolean_claim_number_is_rejected():
    check, = verify_core_claims(DECISION, [SOURCE], "NVDA", CUTOFF, lambda _: [
        {"claim_number": True, "status": "supported", "reason": "Invalid identifier."}])
    assert check["status"] == "insufficient"


def test_conflicting_display_date_cannot_pass_verified_citation():
    evidence = {**DECISION["primary_evidence"][0], "source_date": "2026-06-13"}
    decision = {**DECISION, "primary_evidence": [evidence]}
    check, = verify_core_claims(decision, [SOURCE], "NVDA", CUTOFF, lambda _: [
        {"claim_number": 1, "status": "supported", "reason": "Never reached."}])
    assert check["status"] == "insufficient"
