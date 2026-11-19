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


def provider_error(status, code=None, retry_after="0", **metadata):
    import httpx
    from openai import APIStatusError

    body = {"code": code, **metadata}
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://provider.example/v1/responses")
    response = httpx.Response(status, request=request, json={"error": body}, headers=headers)
    return APIStatusError("private provider diagnostic", response=response, body=body)


class ModelAttempts:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.inputs = []

    def invoke(self, value):
        self.inputs.append(value)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_transient_rate_limit_plus_success_counts_each_attempt_and_uses_same_input():
    from langchain_core.messages import AIMessage
    reply = AIMessage(content="answer", usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4})
    model = ModelAttempts(provider_error(429, "rate_limit_exceeded"), reply)
    control = RunControl(model_call_limit=2)
    with use_run_control(control):
        assert invoke_model(model, "Original input") == reply
    control.seal()
    assert model.inputs == ["Original input", "Original input"]
    usage = control.usage_snapshot()
    assert (usage["calls_started"], usage["calls_failed"], usage["calls_completed"], usage["calls_retried"]) == (2, 1, 1, 1)
    assert usage["reported_total_tokens"] == 4


def test_retry_ceiling_surfaces_the_second_failure_without_a_third_call():
    first = provider_error(429, "rate_limit_exceeded")
    second = provider_error(429, "rate_limit_exceeded")
    model = ModelAttempts(first, second)
    control = RunControl()
    with use_run_control(control), pytest.raises(type(second)) as failed:
        invoke_model(model, "research")
    assert failed.value is second
    assert control.usage_snapshot()["calls_retried"] == 1
    assert control.usage_snapshot()["calls_failed"] == 2


@pytest.mark.parametrize("status,code,wait,metadata", [
    (401, None, "0", {}),
    (503, None, "0", {}),
    (429, "insufficient_quota", "0", {"type": "rate_limit_error"}),
    (429, None, "0", {}),
    (429, "rate_limit_exceeded", "6", {}),
    (429, "rate_limit_exceeded", "0", {"type": "billing_hard_limit_reached"}),
])
def test_uncertain_or_non_transient_http_failures_are_not_retried(status, code, wait, metadata):
    first = provider_error(status, code, wait, **metadata)
    model = ModelAttempts(first)
    with use_run_control(RunControl()), pytest.raises(type(first)) as failed:
        invoke_model(model, "research")
    assert failed.value is first
    assert len(model.inputs) == 1


def test_sdk_connection_failure_before_send_is_retried_but_read_timeout_is_not(monkeypatch):
    import httpx
    from openai import APIConnectionError, APITimeoutError

    request = httpx.Request("POST", "https://provider.example/v1/responses")
    not_connected = APIConnectionError(request=request)
    not_connected.__cause__ = httpx.ConnectError("connection refused", request=request)
    control = RunControl()
    def await_retry(reason, delay):
        assert reason == "connection"
        assert delay == 1
    monkeypatch.setattr(control, "wait_for_retry", await_retry, raising=False)
    model = ModelAttempts(not_connected, "recovered")
    with use_run_control(control):
        assert invoke_model(model, "same") == "recovered"

    timed_out = APITimeoutError(request=request)
    timed_out.__cause__ = httpx.ReadTimeout("may have been processed", request=request)
    model = ModelAttempts(timed_out)
    with use_run_control(RunControl()), pytest.raises(APITimeoutError):
        invoke_model(model, "same")
    assert len(model.inputs) == 1


def test_retry_uses_an_available_budget_slot():
    first = provider_error(429, "rate_limit_exceeded")
    model = ModelAttempts(first)
    control = RunControl(model_call_limit=1)
    with use_run_control(control), pytest.raises(RunStopped, match="budget_exhausted"):
        invoke_model(model, "attempt")
    assert model.inputs == ["attempt"]
    assert control.usage_snapshot()["calls_retried"] == 0


def test_retry_after_can_be_a_date():
    from datetime import datetime, timezone
    from marketmind_ai.model_retry import retry_instruction

    error = provider_error(429, "rate_limit_exceeded", "Thu, 01 Jan 2026 00:00:04 GMT")
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert retry_instruction(error, now=fixed).delay_seconds == 4


def test_retry_respects_millisecond_delays_and_provider_refusal():
    from marketmind_ai.model_retry import retry_instruction

    error = provider_error(429, "rate_limit_exceeded", None)
    error.response.headers["retry-after-ms"] = "6000"
    assert retry_instruction(error) is None
    error.response.headers["retry-after-ms"] = "1500"
    assert retry_instruction(error).delay_seconds == 1.5
    error.response.headers["x-should-retry"] = "false"
    assert retry_instruction(error) is None


def test_openai_sdk_requests_are_retried_once_by_the_run_not_the_sdk():
    import httpx
    from marketmind_ai.llm_clients.openai_client import NormalizedChatOpenAI

    requests = []

    def respond(request):
        requests.append(request.content)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"},
                                  json={"error": {"code": "rate_limit_exceeded", "message": "Retry"}})
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "model": "gpt-4o-mini", "created": 1,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        })

    control = RunControl(model_call_limit=2)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client, use_run_control(control):
        model = NormalizedChatOpenAI(model="gpt-4o-mini", api_key="test-fixture", http_client=http_client, max_retries=0)
        assert invoke_model(model, "Research").content == "answer"
    assert len(requests) == 2 and requests[0] == requests[1]
    usage = control.usage_snapshot()
    assert usage["calls_retried"] == 1 and usage["reported_total_tokens"] == 5


def test_retry_classification_accepts_provider_formats_only_when_rate_limit_is_clear():
    import httpx
    from anthropic import RateLimitError
    from marketmind_ai.model_retry import retry_instruction

    response = httpx.Response(429, headers={"Retry-After": "0"}, request=httpx.Request("POST", "https://provider.example/messages"))
    assert retry_instruction(RateLimitError("rate limited", response=response, body={"type": "rate_limit_error"})).reason == "rate_limit"


def test_google_resource_exhausted_requires_explicit_rate_limit_reason():
    import httpx
    from marketmind_ai.model_retry import retry_instruction

    google_errors = pytest.importorskip("google.genai.errors")
    from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

    response = httpx.Response(429, headers={"Retry-After": "0"})
    wrapped = ChatGoogleGenerativeAIError("private provider diagnostic")
    wrapped.__cause__ = google_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED"},
    ]}}, response)
    assert retry_instruction(wrapped).reason == "rate_limit"
    wrapped.__cause__ = google_errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, response)
    assert retry_instruction(wrapped) is None


def test_rate_limit_handling_works_without_new_google_sdk(monkeypatch):
    import builtins
    from pathlib import Path
    import runpy
    import marketmind_ai

    import_module = builtins.__import__

    def without_google_genai(name, *args, **kwargs):
        if name == "google.genai.errors":
            raise ModuleNotFoundError(name)
        return import_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_google_genai)
    path = Path(marketmind_ai.__file__).with_name("model_retry.py")
    classify = runpy.run_path(str(path))["retry_instruction"]
    assert classify(provider_error(429, "rate_limit_exceeded")).reason == "rate_limit"
