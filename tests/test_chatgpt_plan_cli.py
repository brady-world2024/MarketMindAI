import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from marketmind_ai.cli.main import app


def test_local_subscription_commands_are_discoverable_without_creating_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('MARKETMIND_AI_HOME', str(tmp_path / 'not-created'))
    runner = CliRunner()
    assert 'chatgpt-plan' in runner.invoke(app, ['--help']).stdout
    result = runner.invoke(app, ['chatgpt-plan', '--help'])
    assert result.exit_code == 0
    for command in ['connect', 'accounts', 'models', 'probe', 'disconnect']:
        assert command in result.stdout
    probe = runner.invoke(app, ['chatgpt-plan', 'probe', '--help'])
    assert probe.exit_code == 0
    assert 'four' in probe.stdout.lower() and 'subscription' in probe.stdout.lower()
    assert not (tmp_path / 'not-created').exists()


@pytest.fixture
def services(monkeypatch):
    from marketmind_ai.cli import chatgpt_plan
    summary = {'account_id': 'account-one', 'email': 'one@example.com', 'status': 'signed_in',
               'client_id': 'oaiapp_one', 'plan_usage_enabled': True}
    auth = Mock()
    auth.select_account.return_value = 'account-one'
    auth.accounts.return_value = [summary]
    auth.connect.return_value = summary
    auth.disconnect.return_value = {'account_id': 'account-one', 'status': 'signed_out', 'remote_revoked': False}
    factory = Mock(return_value=auth)
    monkeypatch.setattr(chatgpt_plan, 'LocalChatGPTAuth', factory)
    probe = Mock()
    probe.models.return_value = [{'slug': 'selected-model', 'display_name': 'Selected model'}]
    probe.run.return_value = {'status': 'passed', 'model': 'selected-model', 'checks': [], 'model_usage': {'calls_started': 4}}
    probe.control.usage_snapshot.return_value = {'calls_started': 1, 'calls_failed': 1}
    probe.checks = [{'check': 'text', 'status': 'passed'}]
    probe_factory = Mock(return_value=probe)
    monkeypatch.setattr(chatgpt_plan, 'ChatGPTPlanProbe', probe_factory)
    return auth, factory, probe, probe_factory


@pytest.mark.parametrize('command', ['connect', 'accounts', 'models', 'disconnect'])
def test_commands_use_explicit_storage_and_close_their_clients(tmp_path, services, command):
    auth, factory, probe, _ = services
    result = CliRunner().invoke(app, ['chatgpt-plan', command, '--storage-root', str(tmp_path)])
    assert result.exit_code == 0, result.output
    factory.assert_called_once_with(Path(tmp_path))
    auth.close.assert_called_once()
    assert 'access_token' not in result.stdout and 'refresh_token' not in result.stdout
    json.loads(result.stdout)
    if command == 'models':
        probe.models.assert_called_once_with('account-one')
        probe.close.assert_called_once()
    if command == 'disconnect':
        assert json.loads(result.stdout)['remote_revoked'] is False


def test_probe_requires_a_model_and_does_not_make_a_default_choice(services):
    auth, factory, probe, _ = services
    result = CliRunner().invoke(app, ['chatgpt-plan', 'probe'])
    assert result.exit_code == 2
    factory.assert_not_called()
    probe.run.assert_not_called()


def test_probe_keeps_selected_account_model_and_current_call_budget(services):
    auth, _, probe, probe_factory = services
    result = CliRunner().invoke(app, ['chatgpt-plan', 'probe', '--account', 'chosen',
        '--model', 'selected-model', '--model-call-limit', '3'])
    assert result.exit_code == 0, result.output
    auth.select_account.assert_called_once_with('chosen')
    probe.run.assert_called_once_with('account-one', 'selected-model')
    control = probe_factory.call_args.kwargs['control']
    assert control.usage_snapshot()['model_call_limit'] == 3
    assert json.loads(result.stdout)['status'] == 'passed'


def test_denied_authorization_returns_a_safe_failure_exit(services):
    from marketmind_ai.auth import PlanError
    auth, _, _, _ = services
    auth.connect.side_effect = PlanError('access_denied')
    result = CliRunner().invoke(app, ['chatgpt-plan', 'connect'])
    assert result.exit_code == 1
    assert json.loads(result.stdout)['code'] == 'access_denied'
    auth.close.assert_called_once()


def test_partial_probe_failure_preserves_checks_usage_and_the_provider_code(services):
    from marketmind_ai.auth import PlanError
    _, _, probe, _ = services
    probe.run.side_effect = PlanError('subscription_sharing_usage_limit_exceeded', request_id='req-limit', status=429)
    result = CliRunner().invoke(app, ['chatgpt-plan', 'probe', '--model', 'selected-model'])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload['code'] == 'subscription_sharing_usage_limit_exceeded'
    assert payload['request_id'] == 'req-limit'
    assert payload['model_usage']['calls_started'] == 1
    assert payload['checks'] == [{'check': 'text', 'status': 'passed'}]
    probe.close.assert_called_once()


def test_call_budget_stops_probe_without_becoming_success(services):
    from marketmind_ai.run_control import RunStopped
    _, _, probe, _ = services
    probe.run.side_effect = RunStopped('budget_exhausted')
    result = CliRunner().invoke(app, ['chatgpt-plan', 'probe', '--model', 'selected-model', '--model-call-limit', '1'])
    assert result.exit_code == 1
    assert json.loads(result.stdout)['code'] == 'budget_exhausted'


def test_connect_can_resume_an_incomplete_issued_registration(services):
    auth, _, _, _ = services
    result = CliRunner().invoke(app, ['chatgpt-plan', 'connect', '--resume-client-id', 'oaiapp_incomplete'])
    assert result.exit_code == 0, result.output
    assert auth.connect.call_args.kwargs['resume_client_id'] == 'oaiapp_incomplete'
