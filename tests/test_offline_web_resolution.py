"""Offline requests must remain local even after a live-provider request."""
from unittest.mock import Mock

import pytest

from marketmind_ai.dataflows.config import get_config, set_config
from marketmind_ai.dataflows.interface import VENDOR_METHODS, collect_from_vendors, get_fallback_vendors
from marketmind_ai.graph.marketmind_graph import MarketMindGraph, build_offline_data_vendor_config
from marketmind_ai.web.models import AnalysisRequest
from marketmind_ai.web.runner import resolve_request_symbol


@pytest.fixture
def isolated_data_config():
    previous = get_config()
    try:
        yield
    finally:
        set_config(previous)


def block_remote_vendors(monkeypatch):
    remote_calls = []
    for method, vendors in VENDOR_METHODS.items():
        for vendor in vendors:
            if vendor != "offline":
                blocked = Mock(side_effect=RuntimeError(f"Remote {vendor}/{method} must not run offline"))
                monkeypatch.setitem(vendors, vendor, blocked)
                remote_calls.append(blocked)
    return remote_calls


@pytest.mark.parametrize("existing_workflow", [False, True])
def test_offline_web_symbol_resolution_ignores_prior_live_config(tmp_path, monkeypatch, isolated_data_config, existing_workflow):
    monkeypatch.setenv("MARKETMIND_AI_HOME", str(tmp_path))
    remote_calls = block_remote_vendors(monkeypatch)
    workflow = MarketMindGraph(storage_root=tmp_path) if existing_workflow else None
    set_config({"llm_provider": "openai", "data_vendors": {
        category: "yfinance" for category in build_offline_data_vendor_config()
    }})
    request = AnalysisRequest(ticker="NVDA", analysis_date="2026-06-12", llm_provider="offline",
                              quick_model="heuristic-fast", deep_model="heuristic-deep")
    resolved = resolve_request_symbol(request, workflow)
    assert resolved.status == "RESOLVED"
    assert resolved.resolved_symbol == "NVDA"
    # Per-request mode must not overwrite the process configuration.
    assert get_config()["data_vendors"]["symbol_resolution"] == "yfinance"
    assert sum(call.call_count for call in remote_calls) == 0


def test_explicit_offline_vendor_excludes_live_fallbacks_for_every_method(monkeypatch, isolated_data_config):
    remote_calls = block_remote_vendors(monkeypatch)
    set_config({"data_vendors": build_offline_data_vendor_config()})
    for method in VENDOR_METHODS:
        assert get_fallback_vendors(method) == ["offline"]
    documents = collect_from_vendors("get_fundamental_documents", "NVDA", "2026-06-12")
    assert documents
    assert sum(call.call_count for call in remote_calls) == 0


def test_live_vendor_fallback_order_remains_available(isolated_data_config):
    set_config({"data_vendors": {"symbol_resolution": "yfinance"}})
    vendors = get_fallback_vendors("search_symbols")
    assert vendors[0] == "yfinance"
    assert vendors == ["yfinance"]


def test_demo_symbol_api_search_and_validation_never_call_remote(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from marketmind_ai.web.app import create_app
    remote = block_remote_vendors(monkeypatch)
    client = TestClient(create_app(str(tmp_path)))
    response = client.get('/api/symbols/search', params={'query': 'NVDA', 'data_mode': 'demo'})
    assert response.status_code == 200 and response.json()['candidates']
    response = client.post('/api/symbols/resolve', json={'query': 'NVDA', 'analysis_date': '2026-06-12', 'data_mode': 'demo'})
    assert response.status_code == 200 and response.json()['status'] == 'RESOLVED'
    assert sum(call.call_count for call in remote) == 0
