"""Local subscription compatibility checks, separate from report generation."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from ..auth import LocalChatGPTAuth, PlanError
from ..default_config import default_storage_root
from ..llm_clients.chatgpt_plan_probe import ChatGPTPlanProbe
from ..run_control import RunControl, RunStopped

app = typer.Typer(help='Verify an officially authorized ChatGPT plan on this local computer.', no_args_is_help=True)


def _execute(action, storage_root, *, account=None, resume_client_id=None, timeout=600, model=None, limit=None):
    auth, probe = None, None
    exit_code = 0
    try:
        root = Path(storage_root).expanduser() if storage_root else default_storage_root()
        auth = LocalChatGPTAuth(root)
        if action == 'connect':
            typer.echo('Continue with ChatGPT in your browser, then return here.', err=True)
            result = auth.connect(account_id=account, resume_client_id=resume_client_id, timeout_seconds=timeout)
        elif action == 'accounts':
            result = {'accounts': auth.accounts()}
        else:
            selected = auth.select_account(account)
            if action == 'disconnect':
                result = auth.disconnect(selected)
            else:
                probe = ChatGPTPlanProbe(auth, control=RunControl(model_call_limit=limit))
                result = {'models': probe.models(selected)} if action == 'models' else probe.run(selected, model)
    except PlanError as error:
        result = error.as_dict()
        exit_code = 1
    except RunStopped as error:
        result = {'error': True, 'code': error.reason, 'message': 'The subscription check stopped before another request.'}
        exit_code = 1
    except KeyboardInterrupt:
        result = {'error': True, 'code': 'cancelled', 'message': 'The subscription check was cancelled.'}
        exit_code = 130
    except OSError:
        result = {'error': True, 'code': 'local_storage_error', 'message': 'Unable to access protected local connection storage.'}
        exit_code = 1
    finally:
        if probe is not None:
            probe.close()
        if auth is not None:
            auth.close()
    if exit_code and probe is not None:
        result['checks'] = list(probe.checks)
        result['model_usage'] = probe.control.usage_snapshot()
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(exit_code)


@app.command('connect')
def connect(
    account: str | None = typer.Option(None, '--account', help='Reauthorize a saved registration; omit to add an account.'),
    resume_client_id: str | None = typer.Option(None, '--resume-client-id', help='Retry an issued registration after an interrupted code exchange.'),
    timeout: int = typer.Option(600, '--timeout', min=1, max=3600, help='Maximum seconds to wait for browser authorization.'),
    storage_root: str = typer.Option('', '--storage-root'),
):
    """Continue with ChatGPT using official browser authorization. No model requests."""
    _execute('connect', storage_root, account=account, resume_client_id=resume_client_id, timeout=timeout)


@app.command('accounts')
def accounts(storage_root: str = typer.Option('', '--storage-root')):
    """List local account registrations without exposing credentials."""
    _execute('accounts', storage_root)


@app.command('models')
def models(
    account: str | None = typer.Option(None, '--account'),
    storage_root: str = typer.Option('', '--storage-root'),
):
    """Fetch the selected account's current visible model catalog."""
    _execute('models', storage_root, account=account)


@app.command('probe')
def probe(
    model: str = typer.Option(..., '--model', help='An exact model slug returned by chatgpt-plan models.'),
    account: str | None = typer.Option(None, '--account'),
    model_call_limit: int | None = typer.Option(None, '--model-call-limit', min=1),
    storage_root: str = typer.Option('', '--storage-root'),
):
    """Use subscription allowance for four model calls: text, tool round trip, and structured output."""
    _execute('probe', storage_root, account=account, model=model, limit=model_call_limit)


@app.command('disconnect')
def disconnect(
    account: str | None = typer.Option(None, '--account'),
    storage_root: str = typer.Option('', '--storage-root'),
):
    """End the selected renewable session and clear its local tokens."""
    _execute('disconnect', storage_root, account=account)
