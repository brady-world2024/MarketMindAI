from marketmind_ai.graph.request import AnalysisRequest
from marketmind_ai.graph.snapshot_support import SnapshotProjector
from marketmind_ai.symbols import SymbolResolution, ValidationFlags
from marketmind_ai.web.report_export import render_report_html


class DummySignalProcessor:
    def process_signal(self, text, verification=None):
        return "Overweight"


def _request() -> AnalysisRequest:
    return AnalysisRequest.from_mapping(
        {
            "ticker": "NVDA",
            "analysis_date": "2026-06-12",
            "llm_provider": "offline",
            "quick_model": "heuristic-fast",
            "deep_model": "heuristic-deep",
            "analysts": ["market", "news", "fundamentals"],
            "output_language": "English",
        }
    )


def _resolution() -> SymbolResolution:
    return SymbolResolution(
        status="RESOLVED",
        original_input="NVDA",
        normalized_query="NVDA",
        resolved_symbol="NVDA",
        company_name="NVIDIA Corporation",
        exchange="NASDAQ",
        region="US",
        currency="USD",
        confidence=98.0,
        validation=ValidationFlags(price_data=True, fundamental_data=True),
    )


STRUCTURED_DECISION = {
    "decision_status": "Actionable",
    "rating": "Overweight",
    "confidence": 77,
    "executive_summary": "Scale in on confirmation.",
    "investment_thesis": "The setup is constructive.",
    "primary_evidence": [
        {
            "claim": "Momentum remains constructive.",
            "evidence_type": "Fact",
            "source": "Market Analyst",
            "source_date": "2026-06-12",
            "excerpt": "Close=1092.09, RSI=68.8",
            "interpretation": "Price action supports timing.",
            "strength": "High",
        }
    ],
    "key_risks": ["Valuation is demanding."],
    "evidence_gap": "Valuation leaves limited room for execution misses.",
    "price_target": 1179.46,
    "time_horizon": "1-4 weeks",
}


REPORT_QUALITY = {
    "score": 86,
    "grade": "Strong",
    "summary": "Report quality is strong enough for decision review.",
    "dimensions": {
        "evidence_count": {"score": 100, "label": "Evidence Count", "detail": "3 evidence items"},
        "data_freshness": {"score": 100, "label": "Data Freshness", "detail": "All dated evidence is current"},
    },
    "issues": [],
}


EVIDENCE_LEDGER = [
    {
        "evidence_id": "E1",
        "claim": "Momentum remains constructive.",
        "kind": "Fact",
        "source": "Market Analyst",
        "source_date": "2026-06-12",
        "excerpt": "Close=1092.09, RSI=68.8",
        "interpretation": "Price action supports timing.",
        "strength": "High",
        "freshness": "current",
        "supports": "rating",
        "provider": "",
        "url": "",
    }
]


def test_snapshot_projector_carries_report_quality_payloads():
    projector = SnapshotProjector(DummySignalProcessor())
    snapshot = projector.create_snapshot(run_id="run-1", request=_request(), resolution=_resolution())

    projector.apply_state(
        snapshot,
        {
            "sender": "Portfolio Manager",
            "final_trade_decision": "**Decision Status**: Actionable\n\n**Rating**: Overweight",
            "report_verification": {"status": "passed", "issues": []},
            "final_structured_decision": STRUCTURED_DECISION,
            "report_quality": REPORT_QUALITY,
            "evidence_ledger": EVIDENCE_LEDGER,
        },
    )

    payload = snapshot.to_dict()

    assert payload["report_quality"]["score"] == 86
    assert payload["final_structured_decision"]["rating"] == "Overweight"
    assert payload["evidence_ledger"][0]["evidence_id"] == "E1"


def test_report_export_renders_structured_quality_and_evidence_sections():
    html = render_report_html(
        {
            "run_id": "run-1",
            "status": "completed",
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "analysis_date": "2026-06-12",
            "provider": "offline",
            "quick_model": "heuristic-fast",
            "deep_model": "heuristic-deep",
            "selected_analysts": ["market", "news", "fundamentals"],
            "final_signal": "Overweight",
            "final_decision": "**Decision Status**: Actionable\n\n**Rating**: Overweight",
            "final_structured_decision": STRUCTURED_DECISION,
            "report_quality": REPORT_QUALITY,
            "evidence_ledger": EVIDENCE_LEDGER,
            "reports": [],
            "messages": [],
            "tool_calls": [],
        }
    )

    assert "Quality Score" in html
    assert "86" in html
    assert "Evidence Ledger" in html
    assert "E1" in html
    assert "Momentum remains constructive." in html
