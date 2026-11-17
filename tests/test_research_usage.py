from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from marketmind_ai.run_control import RunControl, RunStopped, invoke_model, use_run_control


class Model:
    def __init__(self):
        self.calls = 0

    def invoke(self, value):
        self.calls += 1
        if value == "fail":
            raise RuntimeError("provider error")
        return value


def test_failure_counts_and_next_call_is_blocked():
    model = Model()
    control = RunControl(model_call_limit=1)
    with use_run_control(control):
        with pytest.raises(RuntimeError, match="provider error"):
            invoke_model(model, "fail")
        with pytest.raises(RunStopped, match="budget_exhausted"):
            invoke_model(model, "forbidden")
    assert model.calls == 1
    usage = control.usage_snapshot()
    assert usage["calls_started"] == usage["calls_failed"] == 1
    assert usage["reported_total_tokens"] is None


def test_exact_limit_can_complete_and_default_only_records():
    model = Model()
    for limit in [1, None]:
        control = RunControl(model_call_limit=limit)
        with use_run_control(control):
            assert invoke_model(model, "ok") == "ok"
        control.seal()
        assert control.usage_snapshot()["calls_completed"] == 1
        assert control.reason is None


def test_workers_cannot_both_claim_the_last_slot():
    barrier = Barrier(2)
    model = Model()
    control = RunControl(model_call_limit=1)

    def worker():
        with use_run_control(control):
            barrier.wait(timeout=5)
            try:
                invoke_model(model, "ok")
            except RunStopped as stop:
                assert stop.reason == "budget_exhausted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        workers = [executor.submit(worker) for _ in range(2)]
        for result in workers:
            result.result(timeout=5)
    assert model.calls == 1


def test_raw_tokens_are_recorded_through_structured_runnable():
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    response = AIMessage(content='{"rating":"Hold"}',
                         usage_metadata={"input_tokens": 19, "output_tokens": 3, "total_tokens": 22})
    model = GenericFakeChatModel(messages=iter([response])) | RunnableLambda(lambda message: {"rating": "Hold"})
    control = RunControl()
    with use_run_control(control):
        assert invoke_model(model, "Analyze") == {"rating": "Hold"}
    usage = control.usage_snapshot()
    assert usage["reported_total_tokens"] == 22
    assert usage["calls_with_reported_tokens"] == 1


def test_reported_zero_and_usage_returned_after_cancellation_are_preserved():
    from langchain_core.messages import AIMessage

    control = RunControl()
    class OnWire:
        def invoke(self, value):
            assert control.cancel()
            return AIMessage(content="", usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    with use_run_control(control), pytest.raises(RunStopped, match="cancelled"):
        invoke_model(OnWire(), "started")
    usage = control.usage_snapshot()
    assert usage["calls_completed"] == 1
    assert usage["reported_total_tokens"] == 0
    assert usage["calls_with_reported_tokens"] == 1


def test_api_persists_usage_and_budget_stop_without_final_recommendation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient

    from marketmind_ai.graph.marketmind_graph import MarketMindGraph
    from marketmind_ai.web.app import create_app
    from test_job_recovery import DEMO

    models = []
    def stream(self, request, run_id):
        model = Model()
        models.append(model)
        assert request.model_call_limit == 1
        invoke_model(model, "first")
        yield SimpleNamespace(to_dict=lambda: {
            "run_id": run_id, "status": "running", "data_snapshot": {"snapshot_id": "a" * 32},
            "final_decision": "Uncommitted recommendation",
        })
        invoke_model(model, "must-stop")
        pytest.fail("No second call or draft is allowed")

    class InlineThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(MarketMindGraph, "stream", stream)
    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", InlineThread)
    with TestClient(create_app(str(tmp_path))) as client:
        for limit in [True, 0, -1, 1.5]:
            assert client.post("/api/runs", json={**DEMO, "model_call_limit": limit}).status_code == 422
        first = client.post("/api/runs", json={**DEMO, "model_call_limit": 1})
        assert first.status_code == 200
        first = first.json()
        completed = client.get(first["result_url"]).json()
        assert completed["status"] == "error"
        assert completed["job_status"] == "budget_exhausted"
        assert completed["model_usage"]["model_call_limit"] == completed["model_usage"]["calls_started"] == 1
        assert completed["data_snapshot"]["snapshot_id"] == "a" * 32
        assert completed["final_decision"] is None and completed["review"] is None
        assert "budget_exhausted" in client.get(first["stream_url"]).text
        assert "Provider-reported tokens" in client.get(first["report_url"]).text
        second = client.post("/api/runs", json={**DEMO, "model_call_limit": 1}).json()
        assert second["run_id"] != first["run_id"]
        assert [model.calls for model in models] == [1, 1]
    assert TestClient(create_app(str(tmp_path))).get(first["result_url"]).json() == completed


def test_raw_partial_usage_cannot_be_replaced_with_sdk_defaults():
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from marketmind_ai.model_usage import UsageCapture

    defaulted = AIMessage(content="answer", usage_metadata={"input_tokens": 7, "output_tokens": 0, "total_tokens": 7})
    capture = UsageCapture()
    capture.on_llm_end(LLMResult(generations=[[ChatGeneration(message=defaulted)]],
                                llm_output={"token_usage": {"prompt_tokens": 7}}))
    assert capture.tokens == (7, None, None)


def test_google_normalized_zeros_are_not_counted_as_reported_fields():
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from marketmind_ai.model_usage import UsageCapture

    normalized = AIMessage(content="answer", response_metadata={"model_provider": "google_genai"},
                           usage_metadata={"input_tokens": 8, "output_tokens": 0, "total_tokens": 10})
    capture = UsageCapture()
    capture.on_llm_end(LLMResult(generations=[[ChatGeneration(message=normalized)]]))
    assert capture.tokens == (None, None, 10)


def test_openai_adapter_does_not_turn_partial_usage_into_a_total():
    import httpx
    from marketmind_ai.llm_clients.openai_client import NormalizedChatOpenAI

    calls = []
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "model": "gpt-4o-mini", "created": 1,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7},
        })

    control = RunControl()
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client, use_run_control(control):
        model = NormalizedChatOpenAI(model="gpt-4o-mini", api_key="fixture", http_client=http_client)
        assert invoke_model(model, "Research").content == "answer"

    assert calls == ["/v1/chat/completions"]
    usage = control.usage_snapshot()
    assert usage["reported_input_tokens"] == 7
    assert usage["reported_output_tokens"] is None
    assert usage["reported_total_tokens"] is None


def test_restart_labels_usage_as_last_recorded(tmp_path):
    from marketmind_ai.web.jobs import JobStore

    first = JobStore(tmp_path)
    first.save({"run_id": "usage-example", "status": "running", "model_usage": RunControl().usage_snapshot()})
    restored = JobStore(tmp_path).get("usage-example")
    assert restored["job_status"] == "interrupted"
    assert restored["model_usage"]["possibly_incomplete"]
