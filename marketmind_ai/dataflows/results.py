"""Serializable source provenance shared by preflight, tools, and reports."""
from __future__ import annotations

import math
import json
import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Generic, Literal, TypeVar


class DataMode(str, Enum):
    LIVE = "live"
    DEMO = "demo"
    UNKNOWN = "unknown"


SourceStatus = Literal["success", "empty", "timeout", "rate_limited", "unconfigured", "invalid_response", "error"]
T = TypeVar("T")
_SECRET_KEY = re.compile(r"api[_-]?key|token|password|secret|authorization|credential", re.I)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(value: str) -> str:
    # Sanitize structured JSON carried inside a textual provider response too.
    if value.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(value)
        except (ValueError, RecursionError):
            pass
        else:
            return json.dumps(safe_json(payload), ensure_ascii=False)
    # Authorization values contain a scheme plus credentials; redact the entire
    # header line rather than just its first whitespace-delimited word.
    value = re.sub(r"(?i)(authorization[\"']?\s*[=:]\s*)[^\r\n]+", r"\1[redacted]", value)
    # Optional closing key quotes support JSON fragments embedded in prose.
    value = re.sub(r"(?i)((?:api[_-]?key|access_token|token|password|secret|credential)[\"']?\s*[=:]\s*)(?:\[redacted\]|\"[^\"]*\"|'[^']*'|[^\s&,;}\]]+)", r"\1[redacted]", value)
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
    for key, secret in os.environ.items():
        if _SECRET_KEY.search(key) and secret and len(secret) >= 4:
            value = value.replace(secret, "[redacted]")
    return value


def safe_json(value: Any) -> Any:
    """Make source content JSON safe without losing zero or exposing credentials."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _safe_text(value)
    if is_dataclass(value) and not isinstance(value, type):
        return safe_json({f.name: getattr(value, f.name) for f in fields(value)})
    if isinstance(value, dict):
        return {_safe_text(str(k)): "[redacted]" if _SECRET_KEY.search(str(k)) else safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    if hasattr(value, "model_dump"):
        return safe_json(value.model_dump())
    # Do not serialize reprs of unknown provider objects or exceptions.
    return None


class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return safe_json(self)

    def model_dump(self, **kwargs) -> dict[str, Any]:
        return self.to_dict()


@dataclass
class SourceAttempt(Serializable):
    attempt_id: str
    method: str
    provider: str
    data_mode: DataMode | str
    status: SourceStatus
    started_at: datetime
    finished_at: datetime
    run_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    item_count: int | None = None


@dataclass
class SourceMaterial(Serializable):
    method: str
    provider: str
    data_mode: DataMode | str
    retrieved_at: datetime
    content: Any
    source_url: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        self.content = safe_json(self.content)
        if self.source_url:
            self.source_url = _safe_text(self.source_url)


@dataclass
class VendorResult(Serializable, Generic[T]):
    value: T | None = None
    provider: str | None = None
    data_mode: DataMode | str = DataMode.UNKNOWN
    status: SourceStatus = "empty"
    attempts: list[SourceAttempt] = field(default_factory=list)
    materials: list[SourceMaterial] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.status == "success"

    @property
    def success(self) -> bool:
        return self.available


class DataUnavailableError(RuntimeError):
    def __init__(self, result: VendorResult):
        self.result = result
        super().__init__("Requested source data is unavailable.")


class InvalidSourceResponse(ValueError):
    """An adapter received a payload without usable source data."""


class UnconfiguredSourceError(RuntimeError):
    """A required provider client or credential is unavailable."""


class DataConfigurationError(ValueError):
    """The explicitly selected providers cannot serve the requested mode/method."""


def valid_fiscal_period(value: Any) -> bool:
    if isinstance(value, (datetime, date)):
        value = value.isoformat()[:10]
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError, OverflowError):
        return False
