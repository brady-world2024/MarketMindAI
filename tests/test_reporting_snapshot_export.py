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
            "provider": "offline-fixtures",
            "url": "marketmind://offline/NVDA/prices/2026-06-12",
            "source_type": "price",
            "retrieved_at": "2026-06-12T00:00:00Z",
            "raw_source_id": "NVDA:price:2026-06-12",
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
        "provider": "offline-fixtures",
        "url": "marketmind://offline/NVDA/prices/2026-06-12",
        "source_type": "price",
        "retrieved_at": "2026-06-12T00:00:00Z",
        "raw_source_id": "NVDA:price:2026-06-12",
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
    assert "offline-fixtures" in html
    assert "price" in html
    assert "marketmind://offline/NVDA/prices/2026-06-12" in html


def test_export_marks_pending_report_and_preserves_version_and_review_context():
    html = render_report_html({
        "ticker": "NVDA", "status": "completed", "final_decision": "No Recommendation",
        "review": {
            "status": "pending", "version": 2, "report_hash": "abc123",
            "requested_at": "2026-10-25T00:00:00Z", "history": [],
            "parent_run_id": "original-run",
        },
    })
    assert "Awaiting human review" in html
    assert "Report version" in html
    assert "abc123" in html
    assert "original-run" in html


def test_export_shows_approval_and_escapes_reviewer_feedback():
    html = render_report_html({
        "ticker": "NVDA", "status": "completed", "final_decision": "No Recommendation",
        "review": {
            "status": "approved", "version": 1, "report_hash": "abc123",
            "history": [{"decision": "approve", "reviewer": "Brady <admin>",
                         "comment": "<script>alert(1)</script>",
                         "reviewed_at": "2026-10-25T00:00:00Z", "version": 1,
                         "report_hash": "abc123"}],
        },
    })
    assert "Approved by human reviewer" in html
    assert "Brady &lt;admin&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_legacy_export_does_not_imply_human_approval():
    html = render_report_html({"ticker": "NVDA", "status": "completed"})
    assert "No human review recorded" in html


def test_export_carries_frozen_provenance_and_marks_legacy_unverified():
    snapshot = {"ticker": "NVDA", "research_cutoff": {"requested_date": "2026-07-04", "effective_session_date": "2026-07-02", "cutoff_at": "2026-07-02T20:00:00Z", "cutoff_at_local": "2026-07-02T16:00:00-04:00", "market_timezone": "America/New_York"},
                "data_snapshot": {"snapshot_id": "saved", "manifest_sha256": "hash", "policy_version": "p2", "processing_version": "v2"},
                "source_records": [{"record_id": "r1", "admissibility": "excluded", "reason_codes": ["after_cutoff"], "publisher": "SEC <official>", "accession": "001", "period_end": "2026-03-31", "raw_sha256": "hash"}]}
    html = render_report_html(snapshot)
    for value in ["2026-07-04", "2026-07-02", "America/New_York", "saved", "hash", "p2", "v2", "Excluded", "after_cutoff", "SEC &lt;official&gt;", "001", "/api/snapshots/saved/sources/r1"]:
        assert value in html
    assert "Snapshot provenance: Unverified" in render_report_html({"ticker": "NVDA"})


def test_cli_provenance_keeps_sources_and_marks_legacy_unverified():
    from types import SimpleNamespace
    from io import StringIO
    from rich.console import Console
    from marketmind_ai.cli.main import _render_provenance
    output = StringIO()
    console = Console(file=output, width=160, color_system=None)
    console.print(_render_provenance(SimpleNamespace(research_cutoff={"requested_date": "2026-07-04", "effective_session_date": "2026-07-02", "market_timezone": "America/New_York"}, data_snapshot={"snapshot_id": "saved", "policy_version": "p2"}, source_records=[{"record_id": "r1", "admissibility": "unverified", "reason_codes": ["public_time_unverified"], "publisher": "SEC", "accession": "001"}])))
    for value in ["2026-07-04", "2026-07-02", "America/New_York", "saved", "p2", "unverified", "public_time_unverified", "SEC", "001"]:
        assert value in output.getvalue()
    output.truncate(0)
    output.seek(0)
    console.print(_render_provenance(SimpleNamespace()))
    assert "Snapshot provenance: Unverified" in output.getvalue()


def test_cli_keeps_provenance_in_final_output_after_live_dashboard_closes():
    import importlib
    from io import StringIO
    from types import SimpleNamespace
    from unittest.mock import patch
    from rich.console import Console
    cli = importlib.import_module('marketmind_ai.cli.main')
    snapshot = SnapshotProjector(DummySignalProcessor()).create_snapshot(run_id='cli', request=_request(), resolution=_resolution())
    snapshot.data_snapshot = {'snapshot_id': 'saved-cli'}
    snapshot.research_cutoff = {'effective_session_date': '2026-06-11'}
    output = StringIO()
    with patch.object(cli, 'console', Console(file=output, width=160, color_system=None)), \
         patch.object(cli, 'workflow_from_storage_root', return_value=SimpleNamespace(stream=lambda request: iter([snapshot]))), \
         patch.object(cli, 'build_analysis_request', return_value=_request()):
        assert cli.run_analyze(SimpleNamespace(storage_root=None, emit_json=False)) == 0
    assert 'saved-cli' in output.getvalue()
    assert '2026-06-11' in output.getvalue()
