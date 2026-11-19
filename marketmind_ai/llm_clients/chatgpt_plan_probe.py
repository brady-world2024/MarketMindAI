"""Explicit, small compatibility checks for an authorized ChatGPT plan account."""
from __future__ import annotations

import json

import httpx

from ..auth import PlanError
from ..auth.errors import response_error, safe_diagnostic
from ..run_control import MODEL_TIMEOUT_SECONDS, RunControl

API_BASE = 'https://api.openai.com/v1'
_SCHEMA = {'type': 'object', 'properties': {'probe': {'type': 'string', 'enum': ['ok']},
    'value': {'type': 'integer', 'enum': [7]}}, 'required': ['probe', 'value'], 'additionalProperties': False}
_TOOLS = [{'type': 'namespace', 'name': 'marketmind', 'description': 'Read-only connection test fixtures.',
    'tools': [{'type': 'function', 'name': 'read_probe_fixture',
        'description': 'Read a synthetic connection-test fixture. This is not market data.', 'strict': True,
        'parameters': {'type': 'object', 'properties': {'symbol': {'type': 'string', 'enum': ['MM_TEST']}},
                       'required': ['symbol'], 'additionalProperties': False}}]}]


def _request_id(response):
    value = response.headers.get('x-request-id') or response.headers.get('openai-request-id')
    return safe_diagnostic(value, _credentials(response))


def _credentials(response):
    header = response.request.headers.get('authorization', '')
    return (header[7:],) if header.startswith('Bearer ') else ()


def _http_error(response):
    return response_error(response, credentials=_credentials(response))


def _tokens(value):
    if not isinstance(value, dict):
        return None
    counts = tuple(value.get(key) if type(value.get(key)) is int and value[key] >= 0 else None
                   for key in ('input_tokens', 'output_tokens', 'total_tokens'))
    return counts if any(count is not None for count in counts) else None


def _text(response):
    chunks = []
    for item in response['output']:
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            continue
        content = item.get('content')
        if not isinstance(content, list):
            raise PlanError('invalid_provider_response')
        for part in content:
            if not isinstance(part, dict):
                raise PlanError('invalid_provider_response')
            if part.get('type') == 'output_text':
                if not isinstance(part.get('text'), str):
                    raise PlanError('invalid_provider_response')
                chunks.append(part['text'])
    return ''.join(chunks)


def _events(response, control):
    """Decode SSE data frames, including multi-line JSON and comment heartbeats."""
    data, size = [], 0
    for line in response.iter_lines():
        control.check()
        if line == '':
            if data:
                raw = '\n'.join(data)
                if raw == '[DONE]':
                    return
                try:
                    event = json.loads(raw)
                except ValueError:
                    raise PlanError('invalid_stream', status=response.status_code, request_id=_request_id(response), body_shape='non_json') from None
                if not isinstance(event, dict):
                    raise PlanError('invalid_stream', status=response.status_code, request_id=_request_id(response))
                yield event
            data, size = [], 0
        elif line.startswith('data:'):
            value = line[5:].removeprefix(' ')
            size += len(value)
            if size > 1_048_576:
                raise PlanError('invalid_stream', status=response.status_code, request_id=_request_id(response))
            data.append(value)


class ChatGPTPlanProbe:
    def __init__(self, auth, http: httpx.Client | None = None, control: RunControl | None = None):
        self.auth = auth
        self.http = http if http is not None else httpx.Client(timeout=MODEL_TIMEOUT_SECONDS, follow_redirects=False)
        self._owned_http = http is None
        self.control = control if control is not None else RunControl()
        self.checks = []
        self._diagnostics = {}

    def close(self):
        if self._owned_http:
            self.http.close()

    def models(self, account_id: str) -> list[dict]:
        self.control.check()
        token = self.auth.access_token(account_id)
        self.control.check()
        try:
            response = self.http.get(API_BASE + '/models', headers={'Authorization': f'Bearer {token}'})
        except httpx.HTTPError:
            raise PlanError('request_failed') from None
        if response.status_code != 200:
            raise _http_error(response)
        try:
            payload = response.json()
            entries = payload['models']
            if not isinstance(entries, list):
                raise ValueError
            visible = []
            for item in entries:
                if not isinstance(item, dict):
                    raise ValueError
                if item.get('visibility') != 'list':
                    continue
                if not isinstance(item.get('slug'), str) or not item['slug'] or not isinstance(item.get('display_name'), str):
                    raise ValueError
                visible.append({'slug': item['slug'], 'display_name': item['display_name']})
        except (ValueError, KeyError, TypeError):
            raise PlanError('invalid_provider_response', request_id=_request_id(response)) from None
        return visible

    def _respond(self, account_id: str, payload: dict) -> dict:
        self.control.check()
        token = self.auth.access_token(account_id)
        started = self.control.begin_model_call()
        failed, usage, result = True, None, None
        try:
            with self.http.stream('POST', API_BASE + '/responses', json=payload,
                                  headers={'Authorization': f'Bearer {token}'}) as response:
                if response.status_code != 200:
                    response.read()
                    raise _http_error(response)
                if response.headers.get('content-type', '').split(';')[0].strip() != 'text/event-stream':
                    raise PlanError('invalid_stream', request_id=_request_id(response))
                for event in _events(response, self.control):
                    recorded = event.get('response')
                    if isinstance(recorded, dict) and isinstance(recorded.get('usage'), dict):
                        usage = _tokens(recorded['usage'])
                    kind = event.get('type')
                    if kind in {'response.failed', 'error'}:
                        error = recorded.get('error') if isinstance(recorded, dict) else event
                        code = safe_diagnostic(error.get('code'), (token,)) if isinstance(error, dict) else None
                        raise PlanError(code or 'response_failed', status=response.status_code,
                            request_id=_request_id(response), body_shape=[key for key in sorted(event) if safe_diagnostic(key, (token,))],
                            param=safe_diagnostic(error.get('param'), (token,)) if isinstance(error, dict) else None)
                    if kind == 'response.incomplete':
                        raise PlanError('response_incomplete', status=response.status_code,
                            request_id=_request_id(response), body_shape=[key for key in sorted(event) if safe_diagnostic(key, (token,))])
                    if kind == 'response.completed':
                        if not isinstance(recorded, dict) or recorded.get('status') != 'completed' or not isinstance(recorded.get('output'), list):
                            raise PlanError('invalid_provider_response', request_id=_request_id(response))
                        if not all(isinstance(item, dict) for item in recorded['output']):
                            raise PlanError('invalid_provider_response', request_id=_request_id(response))
                        self._diagnostics = {'status': response.status_code, 'request_id': _request_id(response),
                                             'body_shape': [key for key in sorted(recorded) if safe_diagnostic(key, (token,))]}
                        result = recorded
                        break
                if result is None:
                    raise PlanError('stream_interrupted', request_id=_request_id(response))
            failed = False
        except httpx.TimeoutException:
            raise PlanError('request_timed_out') from None
        except httpx.HTTPError:
            raise PlanError('request_failed') from None
        finally:
            self.control.finish_model_call(started, failed=failed, tokens=usage)
        self.control.check()
        return result

    def run(self, account_id: str, model: str) -> dict:
        self.checks = []
        if model not in [entry['slug'] for entry in self.models(account_id)]:
            raise PlanError('model_not_available')

        def request(input_, **options):
            return self._respond(account_id, {'model': model, 'input': input_, 'store': False, 'stream': True,
                'include': ['reasoning.encrypted_content'], **options})

        plain = request([{'role': 'user', 'content': 'Reply with exactly plan-connection-ok and nothing else.'}])
        if _text(plain).strip() != 'plan-connection-ok':
            raise PlanError('probe_text_mismatch', **self._diagnostics)
        self.checks.append({'check': 'text', 'status': 'passed'})

        history = [{'role': 'user', 'content': 'Call marketmind.read_probe_fixture with symbol MM_TEST. '
                    'After receiving the tool result, reply with its integer value and nothing else.'}]
        asked = request(history, tools=_TOOLS, tool_choice='required')
        calls = [item for item in asked['output'] if item.get('type') == 'function_call']
        if len(calls) != 1:
            raise PlanError('probe_tool_mismatch', **self._diagnostics)
        call = calls[0]
        try:
            arguments = json.loads(call.get('arguments', ''))
        except (ValueError, TypeError):
            raise PlanError('probe_tool_mismatch', **self._diagnostics) from None
        if (call.get('name') != 'read_probe_fixture' or call.get('namespace') != 'marketmind'
                or arguments != {'symbol': 'MM_TEST'} or not isinstance(call.get('call_id'), str) or not call['call_id']):
            raise PlanError('probe_tool_mismatch', **self._diagnostics)
        fixture = {'symbol': 'MM_TEST', 'value': 7, 'data_mode': 'probe_fixture'}
        answered = request([*history, *asked['output'], {'type': 'function_call_output', 'call_id': call['call_id'],
                                                      'output': json.dumps(fixture)}], tools=_TOOLS, tool_choice='none')
        if _text(answered).strip() != '7':
            raise PlanError('probe_tool_mismatch', **self._diagnostics)
        self.checks.append({'check': 'tool_call', 'status': 'passed'})

        structured = request([{'role': 'user', 'content': 'Return JSON with probe set to ok and value set to 7.'}],
            text={'format': {'type': 'json_schema', 'name': 'plan_connection_probe', 'strict': True, 'schema': _SCHEMA}})
        try:
            value = json.loads(_text(structured))
        except (ValueError, TypeError):
            raise PlanError('probe_structured_mismatch', **self._diagnostics) from None
        if value != {'probe': 'ok', 'value': 7}:
            raise PlanError('probe_structured_mismatch', **self._diagnostics)
        self.checks.append({'check': 'structured_output', 'status': 'passed'})
        self.control.seal()
        return {'status': 'passed', 'mode': 'subscription_probe', 'account_id': account_id, 'model': model,
                'checks': list(self.checks), 'model_usage': self.control.usage_snapshot()}
