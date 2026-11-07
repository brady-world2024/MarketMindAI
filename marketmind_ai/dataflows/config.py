from __future__ import annotations

import os
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock

from .results import SourceAttempt, SourceMaterial, VendorResult
from typing import Any, Dict, Optional

from ..default_config import DEFAULT_CONFIG as APP_DEFAULT_CONFIG
from ..default_config import build_default_config


def _configured_sec_user_agent() -> str:
    return (
        os.getenv("MARKETMIND_SEC_USER_AGENT")
        or os.getenv("MARKETMIND_AI_SEC_USER_AGENT")
        or str(APP_DEFAULT_CONFIG.get("sec_user_agent"))
    )

DEFAULT_CONFIG: Dict[str, Any] = build_default_config(
    overrides={
        "sec_user_agent": _configured_sec_user_agent(),
    }
)

_config: Optional[Dict[str, Any]] = None


@dataclass
class DataflowAudit:
    run_id: str | None = None
    attempts: list[SourceAttempt] = field(default_factory=list)
    materials: list[SourceMaterial] = field(default_factory=list)
    cache: dict[Any, VendorResult] = field(default_factory=dict)
    lock: Any = field(default_factory=RLock, repr=False)


_run_config: ContextVar[Dict[str, Any] | None] = ContextVar("dataflow_config", default=None)
_run_audit: ContextVar[DataflowAudit | None] = ContextVar("dataflow_audit", default=None)


@contextmanager
def dataflow_context(config: Dict[str, Any], run_id: str | None = None, *, audit: DataflowAudit | None = None):
    """Freeze a run's config; optionally reuse its audit/cache in a later phase.

    Copy the context with contextvars.copy_context() when dispatching threads.
    Only successful exact-argument fetches are cached, for this run alone.
    """
    collector = audit if audit is not None else DataflowAudit(run_id=run_id)
    config_token = _run_config.set(deepcopy(config))
    audit_token = _run_audit.set(collector)
    try:
        yield collector
    finally:
        _run_audit.reset(audit_token)
        _run_config.reset(config_token)


def get_audit() -> DataflowAudit | None:
    return _run_audit.get()


def initialize_config() -> None:
    global _config
    if _config is None:
        _config = deepcopy(DEFAULT_CONFIG)


def set_config(config: Dict[str, Any]) -> None:
    global _config
    if _config is None:
        initialize_config()
    assert _config is not None
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value


def get_config() -> Dict[str, Any]:
    scoped = _run_config.get()
    if scoped is not None:
        return deepcopy(scoped)
    if _config is None:
        initialize_config()
    assert _config is not None
    return deepcopy(_config)


initialize_config()
