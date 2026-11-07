from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from unittest.mock import Mock

import pytest

from marketmind_ai.dataflows import config, interface


@pytest.fixture(autouse=True)
def isolate_legacy_config(monkeypatch):
    monkeypatch.setattr(config, "_config", config.get_config())


def scoped(vendors, **extra):
    return {"data_vendors": {"symbol_resolution": vendors}, **extra}


def test_live_fallback_is_only_explicit_and_records_real_provider(monkeypatch):
    first = Mock(side_effect=TimeoutError("apikey=secret"))
    second = Mock(return_value=[{"symbol": "NVDA"}])
    offline = Mock(return_value=[{"symbol": "FAKE"}])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": first, "alpha_vantage": second, "offline": offline})
    with config.dataflow_context(scoped("yfinance,alpha_vantage", data_mode="live"), run_id="run-1") as audit:
        result = interface.fetch_from_vendors("search_symbols", "NVDA")
    assert result.available and result.provider == "alpha_vantage"
    assert [a.provider for a in result.attempts] == ["yfinance", "alpha_vantage"]
    assert [a.status for a in result.attempts] == ["timeout", "success"]
    assert result.attempts[0].run_id == "run-1"
    assert result.materials[0].provider == "alpha_vantage"
    assert result.materials[0].attempt_id == result.attempts[1].attempt_id
    assert audit.attempts == result.attempts
    assert "secret" not in str(result.to_dict())
    offline.assert_not_called()


@pytest.mark.parametrize("vendors,mode", [("missing", "live"), ("yfinance,offline", "live"), ("offline", "live"), ("yfinance", "demo"), ("", "live")])
def test_bad_configuration_reports_failure_before_calling_provider(monkeypatch, vendors, mode):
    remote, offline = Mock(), Mock()
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": remote, "offline": offline})
    with config.dataflow_context(scoped(vendors, data_mode=mode)):
        result = interface.fetch_from_vendors("search_symbols", "NVDA", aggregate=True)
    assert not result.available
    assert result.status == "unconfigured"
    assert result.attempts[0].error_code == "configuration_error"
    remote.assert_not_called()
    offline.assert_not_called()


def test_exhausted_live_route_raises_and_aggregate_never_uses_offline(monkeypatch):
    remote, offline = Mock(return_value=None), Mock(return_value=["fixture"])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": remote, "offline": offline})
    with config.dataflow_context(scoped("yfinance")):
        with pytest.raises(interface.DataUnavailableError):
            interface.route_to_vendor("search_symbols", "NVDA")
        with pytest.raises(interface.DataUnavailableError):
            interface.collect_from_vendors("search_symbols", "NVDA")
    offline.assert_not_called()


def test_demo_aggregate_calls_only_offline(monkeypatch):
    remote, offline = Mock(), Mock(return_value=["fixture"])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": remote, "offline": offline})
    with config.dataflow_context(scoped("offline", data_mode="demo")):
        result = interface.fetch_from_vendors("search_symbols", "NVDA", aggregate=True)
    assert result.value == ["fixture"] and result.data_mode == "demo"
    remote.assert_not_called()


@pytest.mark.parametrize("response", [None, [], {}, "", "No recent insider transaction entries were returned by Yahoo Finance.", "Income-statement data could not be retrieved from Yahoo Finance.", "Error: API key secret failed with 429"])
def test_empty_or_error_text_is_not_success(monkeypatch, response):
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": lambda *a: response})
    with config.dataflow_context(scoped("yfinance")):
        result = interface.fetch_from_vendors("search_symbols", "NVDA")
    assert not result.available and not result.materials
    assert "secret" not in str(result.to_dict())


def test_context_isolation_success_cache_and_copied_threads(monkeypatch):
    provider = Mock(side_effect=[[], [{"symbol": "NVDA"}], [{"symbol": "MSFT"}]])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": provider})
    original = scoped("yfinance", data_mode="live")
    with config.dataflow_context(original, run_id="a") as audit:
        original["data_vendors"]["symbol_resolution"] = "offline"
        config.set_config(scoped("offline"))
        assert not interface.fetch_from_vendors("search_symbols", "NVDA").available
        result = interface.fetch_from_vendors("search_symbols", "NVDA")
        with ThreadPoolExecutor(max_workers=1) as pool:
            cached = pool.submit(copy_context().run, interface.fetch_from_vendors, "search_symbols", "NVDA").result()
        assert cached is result
        assert config.get_config()["data_vendors"]["symbol_resolution"] == "yfinance"
        assert len(audit.attempts) == 2
        interface.fetch_from_vendors("search_symbols", "MSFT")
    with config.dataflow_context(scoped("offline")):
        assert config.get_config()["data_vendors"]["symbol_resolution"] == "offline"
    assert provider.call_count == 3


def test_numeric_zero_is_available(monkeypatch):
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": lambda *a: 0})
    with config.dataflow_context(scoped("yfinance")):
        assert interface.fetch_from_vendors("search_symbols", "NVDA").value == 0
        assert interface.fetch_from_vendors("search_symbols", "NVDA").available


@pytest.mark.parametrize("response", [{"Error Message": "rate limit 429"}, {"Note": "Call frequency exceeded"}, "API rate limit exceeded", float("nan"), float("inf")])
def test_invalid_provider_payload_is_not_success(monkeypatch, response):
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": lambda *a: response})
    with config.dataflow_context(scoped("yfinance")):
        assert not interface.fetch_from_vendors("search_symbols", "NVDA").available


def test_partial_aggregation_does_not_cache_failed_providers(monkeypatch):
    first = Mock(return_value=[{"symbol": "NVDA"}])
    retry = Mock(side_effect=[TimeoutError(), [{"symbol": "NVDA.NZ"}]])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": first, "alpha_vantage": retry})
    with config.dataflow_context(scoped("yfinance,alpha_vantage")):
        initial = interface.fetch_from_vendors("search_symbols", "NVDA", aggregate=True)
        later = interface.fetch_from_vendors("search_symbols", "NVDA", aggregate=True)
    assert len(initial.value) == 1
    assert len(later.value) == 2
    assert retry.call_count == 2


def test_successful_cache_can_be_reused_by_explicit_audit_context(monkeypatch):
    first = Mock(return_value=[{"symbol": "NVDA"}])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": first})
    request_config = scoped("yfinance")
    with config.dataflow_context(request_config, run_id="reuse") as audit:
        initial = interface.fetch_from_vendors("search_symbols", "NVDA")
    with config.dataflow_context(request_config, audit=audit):
        later = interface.fetch_from_vendors("search_symbols", "NVDA")
    assert later is initial
    assert first.call_count == 1
    assert len(audit.attempts) == 1


@pytest.mark.parametrize("candidate", ["offline", "alpha_vantage"])
def test_direct_invoke_cannot_bypass_explicit_provider_list(monkeypatch, candidate):
    live, forbidden = Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setitem(interface.VENDOR_METHODS, "validate_price_data", {"yfinance": live, candidate: forbidden})
    with config.dataflow_context(scoped("yfinance", data_mode="live")):
        with pytest.raises(interface.DataConfigurationError):
            interface.invoke_vendor_method("validate_price_data", candidate, "NVDA", "2026-06-12")
    forbidden.assert_not_called()


def test_direct_invocation_records_one_attempt_and_sanitizes_failure(monkeypatch):
    failed = Mock(side_effect=RuntimeError("https://example.test/?apikey=private-direct-secret"))
    fallback = Mock(return_value=True)
    monkeypatch.setitem(interface.VENDOR_METHODS, "validate_price_data", {"yfinance": failed, "alpha_vantage": fallback})
    with config.dataflow_context(scoped("yfinance,alpha_vantage", data_mode="live")) as audit:
        before = config.get_config()
        with pytest.raises(interface.DataUnavailableError) as captured:
            interface.invoke_vendor_method("validate_price_data", "yfinance", "NVDA", "2026-06-12")
        assert config.get_config() == before
    assert "private-direct-secret" not in str(captured.value)
    assert len(audit.attempts) == 1
    assert audit.attempts[0].provider == "yfinance"
    assert audit.attempts[0].status == "error"
    fallback.assert_not_called()


def test_direct_invocation_and_fetch_never_double_record(monkeypatch):
    provider = Mock(return_value=[{"symbol": "NVDA"}])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": provider})
    with config.dataflow_context(scoped("yfinance")) as audit:
        first = interface.invoke_vendor_method("search_symbols", "yfinance", "NVDA")
        result = interface.fetch_from_vendors("search_symbols", "NVDA")
    assert first == result.value
    assert len(audit.attempts) == 1
    assert len(audit.materials) == 1
    assert provider.call_count == 1


@pytest.mark.parametrize("bad_config", [
    {"data_vendors": None},
    {"data_vendors": ["yfinance"]},
    {"data_vendors": "yfinance"},
    {"data_vendors": {"symbol_resolution": "yfinance"}, "tool_vendors": None},
    {"data_vendors": {"symbol_resolution": "yfinance"}, "tool_vendors": ["search_symbols"]},
])
def test_malformed_vendor_maps_report_audited_configuration_error(monkeypatch, bad_config):
    provider = Mock(return_value=[{"symbol": "NVDA"}])
    monkeypatch.setitem(interface.VENDOR_METHODS, "search_symbols", {"yfinance": provider})
    with config.dataflow_context(bad_config, run_id="bad-map") as audit:
        result = interface.fetch_from_vendors("search_symbols", "NVDA")
    assert not result.available and result.status == "unconfigured"
    assert len(audit.attempts) == 1
    assert audit.attempts[0].error_code == "configuration_error"
    assert audit.attempts[0].run_id == "bad-map"
    provider.assert_not_called()
