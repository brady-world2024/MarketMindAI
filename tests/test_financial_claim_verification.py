from marketmind_ai.reporting.financial_claims import collect_metrics, verify_financial_claims

RECORD = {
    "record_id": "income", "method": "get_income_statement", "provider": "sec",
    "admissibility": "included", "symbol": "NVDA", "accession": "0001045810-26-000052",
    "period_end": "2026-04-26", "currency": "USD", "published_at": "2026-05-20T20:35:52Z",
    "content": "Condensed Consolidated Statements of Income - USD ($) $ in Millions\t3 Months Ended\n"
               "\tApr. 26, 2026\tApr. 27, 2025\nRevenue\t$ 81,615\t$ 44,062\n"
               "Operating income\t53,536\t21,638",
}
CUTOFF = "2026-06-12T20:00:00Z"


def metrics(record=RECORD):
    return collect_metrics([record], "NVDA", CUTOFF)


def test_metrics_preserve_original_rows_dates_units_and_formula():
    found = metrics()
    growth, margin = found["revenue_yoy"], found["operating_margin"]
    assert growth["inputs"][1]["raw_value"] == "$ 44,062"
    assert growth["inputs"][1]["period_end"] == "2025-04-27"
    assert growth["inputs"][0]["value"] == "81615000000"
    assert margin["currency"] == "USD"
    assert margin["inputs"][0]["label"] == "Operating income"


def test_ambiguous_or_future_material_is_excluded():
    assert metrics({**RECORD, "published_at": "2026-06-12T20:00:01Z"}) == {}
    assert metrics({**RECORD, "content": RECORD["content"].replace("Apr. 27, 2025", "Apr. 26, 2026")}) == {}
    assert metrics({**RECORD, "content": RECORD["content"].replace("$ in Millions", "per share")}) == {}


def test_claims_require_known_binding_and_match_at_declared_precision():
    evidence = {"claim": "Revenue grew 85.2% year over year", "raw_source_id": "income",
                "financial_claim": {"metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"}}
    decision = {"primary_evidence": [evidence]}
    assert verify_financial_claims(decision, metrics())[0]["status"] == "supported"
    assert verify_financial_claims({"primary_evidence": [{**evidence, "raw_source_id": "news"}]}, metrics())[0]["status"] == "insufficient"
    assert any(result["status"] == "contradicted" for result in
               verify_financial_claims({"primary_evidence": [{**evidence, "claim": "Revenue doubled year over year"}]}, metrics()))
    assert verify_financial_claims({"executive_summary": "营业利润率为 65.6%"}, metrics())[0]["status"] == "insufficient"


def test_live_financial_gate_blocks_unbound_claim_even_if_other_checks_pass(monkeypatch):
    from marketmind_ai.agents.schemas import DecisionStatus, PortfolioDecision, PortfolioRating
    from marketmind_ai.graph import runtime_support
    from test_report_quality_gate import _fresh_evidence

    engine = runtime_support.GraphResearchEngine.__new__(runtime_support.GraphResearchEngine)
    engine.resolution = {"resolved_symbol": "NVDA"}
    monkeypatch.setattr(runtime_support, "active_financial_metrics", metrics, raising=False)
    monkeypatch.setattr(engine, "_verify_decision", lambda state, decision: decision)
    monkeypatch.setattr(engine, "_reporting_payload", lambda state, decision: {
        "verification": {"status": "passed", "issues": []}, "report_quality": {"grade": "Strong"}})
    decision = PortfolioDecision(decision_status=DecisionStatus.ACTIONABLE, rating=PortfolioRating.OVERWEIGHT,
        confidence=75, confidence_rationale="Test confidence", executive_summary="营业利润率为 99%",
        investment_thesis="Test thesis", primary_evidence=[_fresh_evidence("Market"), _fresh_evidence("SEC")],
        key_risks=["Business risk"], evidence_gap="Open question", price_target=100, time_horizon="one month")
    final, payload = engine._verify_and_payload({}, decision)
    assert final.decision_status == DecisionStatus.NO_RECOMMENDATION
    assert final.price_target is None and final.rating is None
    assert payload["verification"]["blocks_actionable_recommendation"]
    assert payload["verification"]["financial_claims"][0]["status"] == "insufficient"


def test_core_claim_cannot_borrow_unrelated_evidence_id():
    decision = {
        "primary_evidence": [{"raw_source_id": "income",
            "financial_claim": {"metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"}},
            {"raw_source_id": "news"}],
        "core_claims": [{"claim": "Revenue grew 85.2% YoY", "evidence_ids": ["E2"]}],
    }
    assert any(item["status"] == "insufficient" for item in verify_financial_claims(decision, metrics()))


def test_zero_and_negative_operating_income_are_values():
    for value, expected in [("0", "0"), ("(81,615)", "-100")]:
        found = metrics({**RECORD, "content": RECORD["content"].replace("53,536", value)})
        assert found["operating_margin"]["computed_percentage"] == expected


def test_mixed_period_groups_and_wrong_fiscal_period_are_not_verified():
    assert metrics({**RECORD, "content": RECORD["content"].replace("3 Months Ended", "3 Months Ended\t9 Months Ended")}) == {}
    evidence = {"raw_source_id": "income", "financial_claim": {
        "metric": "revenue_yoy", "percentage": "85.2", "period_end": "2025-04-27"}}
    assert verify_financial_claims({"primary_evidence": [evidence]}, metrics())[0]["status"] == "insufficient"


def test_filing_parser_rows_feed_verifier_without_model_or_source_network():
    from marketmind_ai.dataflows.sec_statements import _parse_statement

    html = """<table class="report">
      <tr><th rowspan="2">Statements of Income - USD ($)<br>$ in Millions</th><th colspan="2">3 Months Ended</th></tr>
      <tr><th>Apr. 26, 2026</th><th>Apr. 27, 2025</th></tr>
      <tr><td>Revenue</td><td class="num">$ 81,615</td><td class="num">$ 44,062</td></tr>
      <tr><td>Operating income</td><td class="num">53,536</td><td class="num">21,638</td></tr>
    </table>"""
    statement = _parse_statement(html, "income_statement", "Income", "", RECORD["period_end"])
    found = metrics({**RECORD, "content": statement.text, "currency": statement.currency})
    assert set(found) == {"operating_margin", "revenue_yoy"}
    claim = {"primary_evidence": [{"raw_source_id": "income", "financial_claim": {
        "metric": "operating_margin", "percentage": "65.61", "period_end": RECORD["period_end"]}}]}
    assert verify_financial_claims(claim, found)[0]["status"] == "contradicted"


def test_export_displays_financial_checks_and_escapes_claim_text():
    from marketmind_ai.web.report_export import render_report_html

    result = render_report_html({"report_verification": {"financial_claims": [
        {"metric": "operating_margin", "claim": "<script>invalid</script>", "status": "insufficient"}]}})
    assert "Financial Claim Verification" in result
    assert "&lt;script&gt;invalid&lt;/script&gt;" in result
    assert "<script>invalid</script>" not in result


def test_decline_wording_cannot_pass_using_a_positive_growth_rate():
    decision = {"primary_evidence": [{
        "claim": "Revenue declined 85.2% year over year", "raw_source_id": "income",
        "financial_claim": {"metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"},
    }]}
    assert any(item["status"] == "contradicted" for item in verify_financial_claims(decision, metrics()))


def test_wrapped_text_and_year_earlier_wording_still_require_citations():
    for claim in ("Operating\nmargin was 100%", "Sales rose 85.2% from a year earlier"):
        assert verify_financial_claims({"executive_summary": claim}, metrics())[0]["status"] == "insufficient"


def test_conflicting_source_metadata_cannot_bind_to_sec():
    evidence = {"raw_source_id": "income", "provider": "yfinance",
                "financial_claim": {"metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"}}
    assert verify_financial_claims({"primary_evidence": [evidence]}, metrics())[0]["status"] == "insufficient"


def test_unverified_monetary_amount_cannot_pass_with_correct_ratio():
    evidence = {"claim": "Revenue grew 85.2% YoY to 81,615 billion USD", "raw_source_id": "income",
                "financial_claim": {"metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"}}
    assert any(item["status"] == "insufficient" for item in
               verify_financial_claims({"primary_evidence": [evidence]}, metrics()))


def test_summary_with_two_cited_ratios_and_precision_mismatch():
    decision = {"primary_evidence": [
        {"raw_source_id": "income", "financial_claim": {
            "metric": "revenue_yoy", "percentage": "85.2", "period_end": "2026-04-26"}},
        {"raw_source_id": "income", "financial_claim": {
            "metric": "operating_margin", "percentage": "65.6", "period_end": "2026-04-26"}},
    ], "executive_summary": "Operating margin was 65.6%, with revenue up 85.2% YoY."}
    assert [item["status"] for item in verify_financial_claims(decision, metrics())] == ["supported", "supported"]
    decision["counterargument_response"] = "Operating margin was 65.600%."
    assert any(item["status"] == "contradicted" for item in verify_financial_claims(decision, metrics()))
