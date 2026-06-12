from __future__ import annotations

import os
from copy import deepcopy
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
    if _config is None:
        initialize_config()
    assert _config is not None
    return deepcopy(_config)


initialize_config()
