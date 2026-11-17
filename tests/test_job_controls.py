import threading

import pytest
from fastapi.testclient import TestClient

from marketmind_ai.run_control import RunControl, RunStopped, check_running, use_run_control
from marketmind_ai.web.app import create_app
from test_job_recovery import DEMO


def test_first_stop_reason_wins_and_completion_seals():
    clock = [0.0]
    control = RunControl(timeout_seconds=10, clock=lambda: clock[0])
    assert control.cancel()
    clock[0] = 11
    with pytest.raises(RunStopped, match="cancelled"):
        control.seal()
    completed = RunControl(timeout_seconds=10, clock=lambda: clock[0])
    completed.seal()
    clock[0] = 22
    assert not completed.cancel()
    assert completed.reason is None


def test_context_does_not_leak_and_expired_task_refuses_new_calls():
    clock = [0.0]
    control = RunControl(timeout_seconds=10, clock=lambda: clock[0])
    with use_run_control(control):
        check_running()
        clock[0] = 10
        with pytest.raises(RunStopped, match="timed_out"):
            check_running()
    check_running()


def test_cancel_keeps_capacity_until_worker_returns(tmp_path, monkeypatch):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    entered = threading.Event()
    release = threading.Event()
    workers = []

    def stream(self, request, run_id):
        from types import SimpleNamespace
        yield SimpleNamespace(to_dict=lambda: {
            "run_id": run_id, "status": "running", "final_signal": "Buy",
            "final_decision": "UNCOMMITTED-RATING",
            "reports": [{"key": "final_trade_decision", "content": "UNCOMMITTED-RATING"}],
        })
        entered.set()
        assert release.wait(10)
        check_running()
        yield SimpleNamespace(to_dict=lambda: {"run_id": run_id, "status": "completed"})


    class TrackedThread(threading.Thread):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            workers.append(self)

    monkeypatch.setattr(MarketMindGraph, "stream", stream)
    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", TrackedThread)
    client = TestClient(create_app(str(tmp_path)))
    try:
        run = client.post("/api/runs", json=DEMO).json()
        assert entered.wait(10)
        other = client.post("/api/runs", json=DEMO).json()
        cancelled = client.post(f"/api/runs/{run['run_id']}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["job_status"] == "stopping"
        assert client.get(run["result_url"]).status_code == 409
        assert client.post("/api/runs", json=DEMO).status_code == 503
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=10)
    result = client.get(run["result_url"]).json()
    assert result["job_status"] == "cancelled"
    assert result["status"] == "error"
    assert result.get("final_signal") is None
    assert result["reports"] == []
    sse = client.get(run["stream_url"]).text
    assert "cancelled" in sse and "UNCOMMITTED-RATING" not in sse
    assert client.get(other["result_url"]).json()["status"] == "completed"


def test_expiry_is_visible_while_active_and_persists_terminal_status(tmp_path, monkeypatch):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    clock = [0.0]
    workers = []
    monkeypatch.setattr("marketmind_ai.web.app.RunControl", lambda **kwargs: RunControl(timeout_seconds=900, clock=lambda: clock[0], **kwargs))

    class HeldThread:
        def __init__(self, target, args, **kwargs):
            workers.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldThread)
    def no_graph(*args, **kwargs):
        pytest.fail("An expired queued task must not resolve sources or start the graph")
        yield
    monkeypatch.setattr(MarketMindGraph, "stream", no_graph)
    client = TestClient(create_app(str(tmp_path)))
    run = client.post("/api/runs", json=DEMO).json()
    clock[0] = 900
    pending = client.get(f"/api/runs/{run['run_id']}").json()
    assert pending["job_status"] == "stopping"
    assert pending["stop_reason"] == "timed_out"
    assert client.post(f"/api/runs/{run['run_id']}/cancel").status_code == 409
    target, args = workers[0]
    target(*args)
    result = TestClient(create_app(str(tmp_path))).get(run["result_url"]).json()
    assert result["job_status"] == "timed_out"
    assert result["status"] == "error"
    assert result["review"] is None


def test_model_call_returns_no_result_after_cancellation():
    from marketmind_ai.run_control import invoke_model

    control = RunControl()
    calls = []

    class OnWire:
        def invoke(self, value):
            calls.append(value)
            assert control.cancel()
            return "completed remote response"

    with use_run_control(control):
        with pytest.raises(RunStopped):
            invoke_model(OnWire(), "first")
        with pytest.raises(RunStopped):
            invoke_model(OnWire(), "second")
    assert calls == ["first"]


@pytest.mark.parametrize("provider,expected_retries", [("openai", 0), ("google", 1), ("anthropic", 0), ("azure", 0)])
def test_controlled_models_use_requested_timeout_and_no_hidden_retries(monkeypatch, provider, expected_retries):
    from unittest.mock import Mock
    from marketmind_ai.graph.request import AnalysisRequest
    from marketmind_ai.llm_clients import bundle

    factory = Mock()
    monkeypatch.setattr(bundle, "create_llm_client", factory)
    with use_run_control(RunControl()):
        bundle.build_model_bundle(AnalysisRequest("NVDA", "2026-06-12", llm_provider=provider))
    assert len(factory.call_args_list) == 2
    for call in factory.call_args_list:
        assert call.kwargs["timeout"] == 120
        assert call.kwargs["max_retries"] == expected_retries


def test_stop_between_vendor_attempts_never_calls_fallback(monkeypatch):
    from unittest.mock import Mock
    from marketmind_ai.dataflows import interface
    from marketmind_ai.dataflows.config import dataflow_context

    control = RunControl()
    def first(*args, **kwargs):
        control.cancel()
        raise TimeoutError()
    fallback = Mock()
    monkeypatch.setattr(interface, "get_fallback_vendors", lambda _: ["yfinance", "alpha_vantage"])
    monkeypatch.setitem(interface.VENDOR_METHODS["get_price_history"], "yfinance", first)
    monkeypatch.setitem(interface.VENDOR_METHODS["get_price_history"], "alpha_vantage", fallback)
    with use_run_control(control), dataflow_context({"data_mode": "live"}):
        with pytest.raises(RunStopped):
            interface.fetch_from_vendors("get_price_history", "NVDA", "2026-06-12", 90)
    fallback.assert_not_called()


def test_langgraph_node_inherits_run_control():
    from typing import TypedDict
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        value: str

    control = RunControl()
    def node(state):
        control.cancel()
        check_running()
        pytest.fail("LangGraph worker did not inherit the run control")
    graph = StateGraph(State)
    graph.add_node("check", node)
    graph.add_edge(START, "check")
    graph.add_edge("check", END)
    with use_run_control(control), pytest.raises(RunStopped):
        graph.compile().invoke({"value": "test"})
