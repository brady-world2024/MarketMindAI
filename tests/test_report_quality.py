from marketmind_ai.agents.schemas import EvidenceItem, EvidenceKind, EvidenceStrength
from marketmind_ai.reporting import ReportQualityScorer, build_evidence_ledger


STRUCTURED_DECISION = {
    "decision_status": "Actionable",
    "rating": "Overweight",
    "confidence": 77,
    "confidence_rationale": "Research, execution, and risk views overlap.",
    "executive_summary": "Scale in on confirmation.",
    "investment_thesis": "The setup is constructive but valuation-sensitive.",
    "primary_evidence": [
        {
            "claim": "Momentum remains constructive.",
            "evidence_type": "Fact",
            "source": "Market Analyst",
            "source_date": "2026-06-12",
            "excerpt": "Close=1092.09, RSI=68.8",
            "interpretation": "Price action supports timing.",
            "strength": "High",
            "provider": "offline-fixtures",
            "url": "marketmind://offline/NVDA/prices/2026-06-12",
            "source_type": "price",
            "retrieved_at": "2026-06-12T00:00:00Z",
            "raw_source_id": "NVDA:price:2026-06-12",
        },
        {
            "claim": "Catalyst tone improved.",
            "evidence_type": "Fact",
            "source": "News Analyst",
            "source_date": "2026-06-11",
            "excerpt": "Cloud demand keeps AI accelerator backlog elevated",
            "interpretation": "Fresh catalysts support follow-through.",
            "strength": "Medium",
            "provider": "offline-fixtures",
            "url": "marketmind://offline/NVDA/news/2026-06-11/1",
            "source_type": "news",
            "retrieved_at": "2026-06-12T00:00:00Z",
            "raw_source_id": "NVDA:news:2026-06-11:1",
        },
        {
            "claim": "Business quality is strong.",
            "evidence_type": "Fact",
            "source": "Fundamentals Analyst",
            "source_date": "2026-06-12",
            "excerpt": "Revenue growth 84%, operating margin 59%",
            "interpretation": "Growth and margins support quality.",
            "strength": "High",
            "provider": "offline-fixtures",
            "url": "marketmind://offline/NVDA/fundamentals/2026-06-12",
            "source_type": "fundamentals",
            "retrieved_at": "2026-06-12T00:00:00Z",
            "raw_source_id": "NVDA:fundamentals:2026-06-12",
        },
    ],
    "key_risks": [
        "Valuation is demanding.",
        "Catalyst tone can reverse if macro liquidity deteriorates.",
    ],
    "evidence_gap": "Valuation leaves limited room for execution misses.",
    "price_target": 1179.46,
    "time_horizon": "1-4 weeks",
}


def test_evidence_item_preserves_source_provenance_fields():
    item = EvidenceItem(
        claim="Momentum remains constructive.",
        evidence_type=EvidenceKind.FACT,
        source="Market Analyst",
        source_date="2026-06-12",
        excerpt="Close=1092.09, RSI=68.8",
        interpretation="Price action supports timing.",
        strength=EvidenceStrength.HIGH,
        provider="offline-fixtures",
        url="marketmind://offline/NVDA/prices/2026-06-12",
        source_type="price",
        retrieved_at="2026-06-12T00:00:00Z",
        raw_source_id="NVDA:price:2026-06-12",
    )

    payload = item.model_dump(mode="json")

    assert payload["provider"] == "offline-fixtures"
    assert payload["url"] == "marketmind://offline/NVDA/prices/2026-06-12"
    assert payload["source_type"] == "price"
    assert payload["retrieved_at"] == "2026-06-12T00:00:00Z"
    assert payload["raw_source_id"] == "NVDA:price:2026-06-12"


def test_evidence_ledger_assigns_stable_ids_and_freshness():
    ledger = build_evidence_ledger(STRUCTURED_DECISION, analysis_date="2026-06-12")

    assert [item["evidence_id"] for item in ledger] == ["E1", "E2", "E3"]
    assert ledger[0]["freshness"] == "current"
    assert ledger[1]["freshness"] == "current"
    assert ledger[0]["source"] == "Market Analyst"
    assert ledger[0]["supports"] == "rating"
    assert ledger[0]["provider"] == "offline-fixtures"
    assert ledger[0]["url"] == "marketmind://offline/NVDA/prices/2026-06-12"
    assert ledger[0]["source_type"] == "price"
    assert ledger[0]["retrieved_at"] == "2026-06-12T00:00:00Z"
    assert ledger[0]["raw_source_id"] == "NVDA:price:2026-06-12"


def test_report_quality_score_rewards_auditable_multi_source_evidence():
    result = ReportQualityScorer().score(
        final_state={
            "trade_date": "2026-06-12",
            "investment_plan": "**Recommendation Status**: Actionable",
            "trader_investment_plan": "**Action Status**: Actionable\n\nStop if the breakout fails.",
        },
        structured_decision=STRUCTURED_DECISION,
        verification={"status": "passed", "issues": []},
    )

    assert result["score"] >= 80
    assert result["grade"] == "Strong"
    assert result["dimensions"]["evidence_count"]["score"] == 100
    assert result["dimensions"]["source_diversity"]["score"] == 100
    assert result["dimensions"]["provenance"]["score"] == 100
    assert result["issues"] == []


def test_report_quality_score_penalizes_missing_source_provenance():
    missing_provenance = {
        **STRUCTURED_DECISION,
        "primary_evidence": [
            {
                key: value
                for key, value in item.items()
                if key not in {"provider", "url", "source_type", "retrieved_at", "raw_source_id"}
            }
            for item in STRUCTURED_DECISION["primary_evidence"]
        ],
    }

    result = ReportQualityScorer().score(
        final_state={
            "trade_date": "2026-06-12",
            "investment_plan": "**Recommendation Status**: Actionable",
            "trader_investment_plan": "**Action Status**: Actionable\n\nStop if the breakout fails.",
        },
        structured_decision=missing_provenance,
        verification={"status": "passed", "issues": []},
    )

    assert result["dimensions"]["provenance"]["score"] < 100
    assert "missing_source_provenance" in {issue["code"] for issue in result["issues"]}


def test_report_quality_score_flags_weak_or_stale_reports():
    weak_decision = {
        **STRUCTURED_DECISION,
        "primary_evidence": [
            {
                **STRUCTURED_DECISION["primary_evidence"][0],
                "source_date": "2025-01-01",
            }
        ],
        "key_risks": [],
        "evidence_gap": "",
    }

    result = ReportQualityScorer().score(
        final_state={
            "trade_date": "2026-06-12",
            "investment_plan": "**Recommendation Status**: Actionable",
            "trader_investment_plan": "**Action Status**: Actionable",
        },
        structured_decision=weak_decision,
        verification={"status": "failed", "issues": [{"code": "missing_evidence_gap"}]},
    )

    assert result["score"] < 60
    assert result["grade"] == "Weak"
    assert "insufficient_evidence_count" in {issue["code"] for issue in result["issues"]}
    assert "stale_evidence" in {issue["code"] for issue in result["issues"]}
