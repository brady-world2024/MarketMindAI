import json

import httpx
import pytest

from marketmind_ai.graph import MarketMindGraph  # Initialize the existing package import order.
from marketmind_ai.auth import PlanError
from marketmind_ai.llm_clients.chatgpt_plan_probe import ChatGPTPlanProbe
from marketmind_ai.run_control import RunControl, RunStopped


class Account:
    def __init__(self):
        self.requested = []

    def access_token(self, account_id):
        self.requested.append(account_id)
        return 'private-test-access-token'


def message(text):
    return {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}


def completed(output, usage=None):
    return {'type': 'response.completed', 'response': {'id': 'response-test', 'status': 'completed',
        'output': output, 'usage': usage if usage is not None else {'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7}}}


def stream(events):
    return ''.join(f'data: {json.dumps(event)}\n\n' for event in events)


def transport(events=None):
    sent = []
    outputs = list(events) if events is not None else [
        [completed([message('plan-connection-ok')])],
        [completed([{'type': 'function_call', 'call_id': 'call-test', 'name': 'read_probe_fixture',
            'namespace': 'marketmind', 'arguments': '{"symbol":"MM_TEST"}'}])],
        [completed([message('7')])],
        [completed([message('{"probe":"ok","value":7}')])],
    ]

    def send(request):
        assert request.url.host == 'api.openai.com'
        assert request.headers['authorization'] == 'Bearer private-test-access-token'
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'models': [
                {'slug': 'hidden-model', 'display_name': 'Hidden', 'visibility': 'hide'},
                {'slug': 'account-model-b', 'display_name': 'Account B', 'visibility': 'list'},
                {'slug': 'account-model-a', 'display_name': 'Account A', 'visibility': 'list'},
            ]})
        assert request.url.path == '/v1/responses'
        sent.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream', 'x-request-id': 'req-test'},
                              text=stream(outputs.pop(0)))

    return httpx.Client(transport=httpx.MockTransport(send)), sent


def test_account_models_preserve_server_order_and_visibility():
    client, _ = transport()
    account = Account()
    probe = ChatGPTPlanProbe(account, http=client)
    assert probe.models('account-one') == [
        {'slug': 'account-model-b', 'display_name': 'Account B'},
        {'slug': 'account-model-a', 'display_name': 'Account A'},
    ]
    assert account.requested == ['account-one']
    probe.close()
    assert not client.is_closed


def test_probe_runs_all_four_calls_with_saved_tool_history_and_actual_usage():
    client, sent = transport()
    probe = ChatGPTPlanProbe(Account(), http=client)
    result = probe.run('selected-account', 'account-model-b')
    assert result['status'] == 'passed'
    assert [check['check'] for check in result['checks']] == ['text', 'tool_call', 'structured_output']
    assert result['model_usage']['calls_started'] == result['model_usage']['calls_completed'] == 4
    assert result['model_usage']['reported_total_tokens'] == 28
    assert len(sent) == 4
    for body in sent:
        assert body['model'] == 'account-model-b'
        assert body['store'] is False and body['stream'] is True
        assert isinstance(body['input'], list)
        assert not any(item.get('role') == 'system' for item in body['input'])
        for key in ['previous_response_id', 'temperature', 'metadata', 'max_output_tokens', 'background', 'conversation']:
            assert key not in body
    assert sent[1]['tools'][0]['type'] == 'namespace'
    assert sent[1]['tools'][0]['name'] == 'marketmind'
    assert sent[1]['tools'][0]['tools'][0]['name'] == 'read_probe_fixture'
    output = next(item for item in sent[2]['input'] if item.get('type') == 'function_call_output')
    assert output['call_id'] == 'call-test'
    assert json.loads(output['output']) == {'symbol': 'MM_TEST', 'value': 7, 'data_mode': 'probe_fixture'}
    assert any(item.get('type') == 'function_call' for item in sent[2]['input'])
    assert sent[3]['text']['format']['type'] == 'json_schema'
    assert 'private-test-access-token' not in repr(result)


def test_model_must_be_in_the_selected_accounts_visible_catalog():
    client, sent = transport()
    probe = ChatGPTPlanProbe(Account(), http=client)
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'arbitrary-api-model')
    assert failed.value.code == 'model_not_available'
    assert sent == []


@pytest.mark.parametrize('event,code', [
    ({'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}},
     'subscription_sharing_usage_limit_exceeded'),
    ({'type': 'response.incomplete', 'response': {'status': 'incomplete'}}, 'response_incomplete'),
    ({'type': 'error', 'code': 'subscription_sharing_unsupported_capability'}, 'subscription_sharing_unsupported_capability'),
])
def test_failed_or_incomplete_streams_are_not_counted_as_success(event, code):
    client, sent = transport([[{'type': 'response.output_text.delta', 'delta': 'plan-connection-ok'}, event]])
    probe = ChatGPTPlanProbe(Account(), http=client)
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.code == code
    assert failed.value.request_id == 'req-test'
    assert failed.value.status == 200
    assert failed.value.as_dict()['body_shape']
    assert len(sent) == 1
    assert probe.control.usage_snapshot()['calls_failed'] == 1
    assert probe.control.usage_snapshot()['calls_completed'] == 0


def test_text_deltas_and_done_without_response_completed_are_an_interrupted_stream():
    client, sent = transport([[{'type': 'response.output_text.delta', 'delta': 'plan-connection-ok'}]])
    probe = ChatGPTPlanProbe(Account(), http=client)
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.code == 'stream_interrupted'
    assert len(sent) == 1


def test_stream_decoder_handles_comments_multiline_data_and_blank_frames():
    payload = json.dumps(completed([message('plan-connection-ok')]), indent=2)
    body = ': heartbeat\n\nevent: response.completed\n' + ''.join('data: ' + line + '\n' for line in payload.splitlines()) + '\n'
    def send(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=body)
    probe = ChatGPTPlanProbe(Account(), http=httpx.Client(transport=httpx.MockTransport(send)))
    result = probe._respond('one', {'model': 'account-model-b', 'input': [{'role': 'user', 'content': 'test'}],
                                 'store': False, 'stream': True})
    assert result['output'][0]['content'][0]['text'] == 'plan-connection-ok'


def test_detail_http_errors_keep_status_shape_request_id_and_do_not_echo_credentials():
    client, sent = transport()
    def send(request):
        if request.url.path == '/v1/models':
            return client.send(request)
        return httpx.Response(403, headers={'x-request-id': 'req-denied'}, json={'detail': 'private-test-access-token'})
    probe = ChatGPTPlanProbe(Account(), http=httpx.Client(transport=httpx.MockTransport(send)))
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.status == 403 and failed.value.request_id == 'req-denied'
    assert 'detail' in str(failed.value.as_dict()['body_shape'])
    assert 'private-test-access-token' not in repr(failed.value.as_dict())


@pytest.mark.parametrize('bad_call', [
    {'name': 'run_shell', 'namespace': 'marketmind', 'arguments': '{}'},
    {'name': 'read_probe_fixture', 'namespace': 'another', 'arguments': '{"symbol":"MM_TEST"}'},
    {'name': 'read_probe_fixture', 'namespace': 'marketmind', 'arguments': '{"symbol":"LIVE"}'},
    {'name': 'read_probe_fixture', 'namespace': 'marketmind', 'arguments': '{"symbol":"MM_TEST","extra":1}'},
])
def test_unexpected_tool_names_or_arguments_stop_before_executing_a_tool(bad_call):
    client, sent = transport([[completed([message('plan-connection-ok')])],
        [completed([{'type': 'function_call', 'call_id': 'call-test', **bad_call}])]])
    with pytest.raises(PlanError) as failed:
        ChatGPTPlanProbe(Account(), http=client).run('one', 'account-model-b')
    assert failed.value.code == 'probe_tool_mismatch'
    assert len(sent) == 2


def test_subscription_budget_is_checked_before_the_next_request():
    client, sent = transport()
    probe = ChatGPTPlanProbe(Account(), http=client, control=RunControl(model_call_limit=2))
    with pytest.raises(RunStopped) as stopped:
        probe.run('one', 'account-model-b')
    assert stopped.value.reason == 'budget_exhausted'
    assert len(sent) == 2
    assert probe.control.usage_snapshot()['calls_started'] == 2


def test_token_totals_are_not_invented_and_failed_usage_is_retained():
    failed = {'type': 'response.failed', 'response': {'usage': {'input_tokens': 9, 'output_tokens': 1},
        'error': {'code': 'subscription_sharing_usage_unavailable'}}}
    client, _ = transport([[failed]])
    probe = ChatGPTPlanProbe(Account(), http=client)
    with pytest.raises(PlanError):
        probe.run('one', 'account-model-b')
    usage = probe.control.usage_snapshot()
    assert usage['reported_input_tokens'] == 9 and usage['reported_output_tokens'] == 1
    assert usage['reported_total_tokens'] is None


@pytest.mark.parametrize('output', [
    [message('ignored') | {'content': None}],
    [message('ignored') | {'content': ['not-a-content-item']}],
    [message(7)],
])
def test_malformed_completed_content_produces_a_safe_provider_error(output):
    client, _ = transport([[completed(output)]])
    with pytest.raises(PlanError) as failed:
        ChatGPTPlanProbe(Account(), http=client).run('one', 'account-model-b')
    assert failed.value.code == 'invalid_provider_response'


@pytest.mark.parametrize('events,code', [
    ([[completed([message('different text')])]], 'probe_text_mismatch'),
    ([[completed([message('plan-connection-ok')])],
      [completed([{'type': 'function_call', 'call_id': 'call-test', 'name': 'read_probe_fixture',
        'namespace': 'marketmind', 'arguments': '{"symbol":"MM_TEST"}'}])],
      [completed([message('7')])], [completed([message('{"probe":"ok","value":8}')])]], 'probe_structured_mismatch'),
])
def test_completed_but_incorrect_outputs_do_not_pass_the_compatibility_check(events, code):
    client, _ = transport(events)
    with pytest.raises(PlanError) as failed:
        ChatGPTPlanProbe(Account(), http=client).run('one', 'account-model-b')
    assert failed.value.code == code
    assert failed.value.status == 200
    assert failed.value.request_id == 'req-test'


def test_cancelled_check_does_not_start_a_model_call():
    client, sent = transport()
    control = RunControl()
    control.cancel()
    account = Account()
    probe = ChatGPTPlanProbe(account, http=client, control=control)
    with pytest.raises(RunStopped) as stopped:
        probe.run('one', 'account-model-b')
    assert stopped.value.reason == 'cancelled'
    assert sent == []
    assert account.requested == []
    assert control.usage_snapshot()['calls_started'] == 0


def test_http_timeout_is_counted_once_without_leaking_raw_transport_errors():
    client, _ = transport()
    def send(request):
        if request.url.path == '/v1/models':
            return client.send(request)
        raise httpx.ReadTimeout('private-test-access-token', request=request)
    probe = ChatGPTPlanProbe(Account(), http=httpx.Client(transport=httpx.MockTransport(send)))
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.code == 'request_timed_out'
    assert 'private-test-access-token' not in str(failed.value.as_dict())
    assert probe.control.usage_snapshot()['calls_failed'] == 1


def test_a_completed_first_request_does_not_hide_an_interrupted_second_request():
    # response.completed is the official terminal event; a request can finish
    # without requiring an additional [DONE] transport marker.
    client, sent = transport([[completed([message('plan-connection-ok')])], []])
    probe = ChatGPTPlanProbe(Account(), http=client)
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.code == 'stream_interrupted'
    assert len(sent) == 2
    assert probe.control.usage_snapshot()['calls_completed'] == 1


def test_probe_does_not_receive_or_send_an_api_key_fallback_when_plan_permission_fails():
    class Disabled(Account):
        def access_token(self, account_id):
            raise PlanError('plan_usage_not_enabled')
    requested = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requested.append(request)))
    with pytest.raises(PlanError) as failed:
        ChatGPTPlanProbe(Disabled(), http=client).run('one', 'account-model-b')
    assert failed.value.code == 'plan_usage_not_enabled'
    assert requested == []


@pytest.mark.parametrize('streamed', [False, True])
def test_unsupported_capability_keeps_the_returned_parameter(streamed):
    catalog, _ = transport()
    def send(request):
        if request.url.path == '/v1/models':
            return catalog.send(request)
        error = {'code': 'subscription_sharing_unsupported_capability', 'param': 'tools[0]'}
        return (httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text=stream([{'type': 'response.failed', 'response': {'error': error}}])) if streamed
            else httpx.Response(400, json={'error': error}))
    probe = ChatGPTPlanProbe(Account(), http=httpx.Client(transport=httpx.MockTransport(send)))
    with pytest.raises(PlanError) as failed:
        probe.run('one', 'account-model-b')
    assert failed.value.as_dict()['param'] == 'tools[0]'


@pytest.mark.parametrize('streamed', [False, True, 'incomplete'])
def test_known_bearer_credentials_are_redacted_even_if_echoed_as_error_metadata(streamed):
    catalog, _ = transport()
    secret = 'private-test-access-token'
    def send(request):
        if request.url.path == '/v1/models':
            return catalog.send(request)
        if streamed == 'incomplete':
            return httpx.Response(200, headers={'content-type': 'text/event-stream', 'x-request-id': secret},
                text=stream([{'type': 'response.incomplete', secret: 'ignored', 'response': {'status': 'incomplete'}}]))
        error = {'code': secret, 'param': secret}
        return (httpx.Response(200, headers={'content-type': 'text/event-stream', 'x-request-id': secret},
            text=stream([{'type': 'response.failed', 'response': {'error': error}}])) if streamed
            else httpx.Response(400, headers={'x-request-id': secret}, json={'error': error, secret: 'ignored'}))
    with pytest.raises(PlanError) as failed:
        ChatGPTPlanProbe(Account(), http=httpx.Client(transport=httpx.MockTransport(send))).run('one', 'account-model-b')
    assert secret not in str(failed.value.as_dict())
