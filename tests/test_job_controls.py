from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading

import pytest
from fastapi.testclient import TestClient

from marketmind_ai.run_control import RunControl, RunStopped, check_running, use_run_control
from marketmind_ai.web.app import create_app
from test_job_recovery import DEMO


def next_run_event(session, stream):
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(next, stream)
        try:
            return pending.result(timeout=2)
        except TimeoutError:
            session.finish()
            pytest.fail("Run progress event was not emitted")


def test_stream_replays_identical_snapshots_and_recovers_to_latest_when_cursor_is_expired(monkeypatch):
    from marketmind_ai.web.app import RunSession

    monkeypatch.setattr("marketmind_ai.web.app.STREAM_HISTORY_LIMIT", 3, raising=False)
    session = RunSession("cursor-fixture")
    separate = RunSession("cursor-fixture")
    for target in (session, separate):
        target.publish("snapshot", {"status": "running", "latest_update": "first"})
    initial = next(session.stream_events())
    other_id = next(separate.stream_events())["id"]
    stream = session.stream_events(after=initial["id"])
    session.publish("snapshot", {"status": "running", "latest_update": "second"})
    second = next_run_event(session, stream)
    assert second["payload"]["latest_update"] == "second"
    session.control.begin_model_call()
    assert next_run_event(session, session.stream_events(after=initial["id"])) == second
    for label in ("third", "fourth", "latest"):
        session.publish("snapshot", {"status": "running", "latest_update": label})
    for after in (initial["id"], other_id, "broken", second["id"].split(":")[0] + ":9999", None):
        latest = next_run_event(session, session.stream_events(after=after))
        assert latest["payload"]["latest_update"] == "latest"
        assert latest["payload"]["stream_cursor"] == latest["id"]
    session.finish()


def test_sse_keepalive_comment_does_not_advance_cursor(monkeypatch):
    from marketmind_ai.web.app import RunSession, _to_sse

    monkeypatch.setattr("marketmind_ai.web.app.STREAM_HEARTBEAT_SECONDS", 0, raising=False)
    session = RunSession("heartbeat")
    session.publish("snapshot", {"status": "running"})
    stream = session.stream_events()
    first = next(stream)
    assert f"id: {first['id']}".encode() in _to_sse(first)
    assert _to_sse(next_run_event(session, stream)) == b": keep-alive\n\n"
    session.publish("snapshot", {"status": "completed"})
    final = next_run_event(session, stream)
    assert int(final["id"].rsplit(":", 1)[-1]) == int(first["id"].rsplit(":", 1)[-1]) + 1
    session.finish()


def test_stream_replay_is_unchanged_after_nested_snapshot_mutations():
    from marketmind_ai.web.app import RunSession, _to_sse

    session = RunSession("immutable-snapshot")
    raw = {"status": "running", "reports": [{"content": "original"}]}
    session.publish("snapshot", raw)
    first = next(session.stream_events())
    original_wire = _to_sse(first)
    raw["reports"][0]["content"] = "publisher edit"
    session.latest_snapshot["reports"][0]["content"] = "worker edit"
    session.current_snapshot()["reports"][0]["content"] = "GET edit"
    first["payload"]["reports"][0]["content"] = "stream consumer edit"
    assert _to_sse(next(session.stream_events())) == original_wire
    session.finish()


def test_call_retry_wait_honors_provider_delay_and_deadline(monkeypatch):
    clock = [0.0]
    control = RunControl(timeout_seconds=3, clock=lambda: clock[0])
    # Simulate a spurious wake before Retry-After, then let the clock reach the target.
    waits = []

    def advance(timeout):
        waits.append(timeout)
        clock[0] += min(timeout, 1.0)

    monkeypatch.setattr(control._changed, "wait", advance)
    control.wait_for_retry("rate_limit", 2)
    assert waits == [2, 1]
    assert control.retry_reason is None
    with pytest.raises(RunStopped, match="timed_out"):
        control.wait_for_retry("connection", 2)
    assert clock[0] == 3
    assert control.retry_reason is None
    assert control.usage_snapshot()["calls_retried"] == 0


def test_waiting_for_provider_is_visible_and_cancel_interrupts_the_wait(monkeypatch):
    from marketmind_ai.web.app import RunSession

    session = RunSession("retry-progress", model_call_limit=3)
    session.publish("snapshot", {"run_id": session.run_id, "status": "running", "latest_update": "Research"})
    stream = session.stream_events()
    assert next(stream)["payload"].get("model_retry") is None
    entered_wait = threading.Event()
    stopped = []
    original_wait = session.control._changed.wait

    def signal_wait(timeout):
        entered_wait.set()
        return original_wait(timeout)

    monkeypatch.setattr(session.control._changed, "wait", signal_wait)

    def worker():
        try:
            session.control.wait_for_retry("rate_limit", 5)
            session.control.begin_model_call(retry=True)
        except RunStopped as error:
            stopped.append(error.reason)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert entered_wait.wait(2)
        view = session.view(session.latest_snapshot)
        assert view["model_retry"] == "rate_limit"
        assert "limit" in view["latest_update"].lower()
        assert next_run_event(session, stream)["payload"]["model_retry"] == "rate_limit"
        assert session.control.cancel()
        thread.join(timeout=0.5)
        assert not thread.is_alive()
        stop = next_run_event(session, stream)["payload"]
        assert stop["job_status"] == "stopping" and "model_retry" not in stop
        assert stopped == ["cancelled"]
        assert session.control.usage_snapshot()["calls_retried"] == 0
    finally:
        session.control.cancel()
        thread.join(timeout=1)
        session.finish()
        stream.close()


def test_stream_clears_waiting_state_as_soon_as_model_retry_starts(monkeypatch):
    from marketmind_ai.web.app import RunSession

    session = RunSession("retry-start")
    session.publish("snapshot", {"run_id": session.run_id, "status": "running", "latest_update": "Research"})
    events = session.stream_events()
    assert next(events)["payload"]["latest_update"] == "Research"
    reason = ["connection"]
    monkeypatch.setattr(type(session.control), "retry_reason", property(lambda _: reason[0]))
    assert session.view(session.latest_snapshot)["model_retry"] == "connection"
    assert next_run_event(session, events)["payload"]["model_retry"] == "connection"
    reason[0] = None
    restored = next_run_event(session, events)["payload"]
    assert restored["latest_update"] == "Research" and "model_retry" not in restored
    session.finish()
    events.close()


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
