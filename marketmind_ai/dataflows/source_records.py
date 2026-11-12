"""Versioned source and immutable snapshot manifests shared by every surface."""
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .results import safe_json
from .source_policy import POLICY_VERSION, PROCESSING_VERSION

SNAPSHOT_FORMAT_VERSION = 1


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    record_id: str = Field(default_factory=lambda: uuid4().hex)
    method: str
    provider: str
    publisher: str | None = None
    symbol: str
    data_mode: Literal['live', 'demo', 'unknown']
    source_url: str | None = None
    cik: str | None = None
    accession: str | None = None
    filing_form: str | None = None
    period_end: str | None = None
    currency: str | None = None
    unit_context: str | None = None
    price_basis: dict[str, Any] | None = None
    published_at: str | None = None
    public_time_basis: str | None = None
    time_precision: Literal['instant', 'date', 'unknown'] = 'unknown'
    retrieved_at: str = Field(default_factory=timestamp)
    admissibility: Literal['included', 'excluded', 'unverified']
    reason_codes: list[str] = Field(default_factory=list)
    content: Any = None
    raw_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    raw_content_kind: Literal['http_body', 'vendor_object', 'derived', 'demo'] = 'vendor_object'
    content_type: str = 'application/json'

    def to_dict(self):
        return safe_json(self.model_dump(mode='json'))


class ResearchDataSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    snapshot_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r'^[0-9a-f]{32}$')
    format_version: int = SNAPSHOT_FORMAT_VERSION
    policy_version: str = POLICY_VERSION
    processing_version: str = PROCESSING_VERSION
    created_at: str = Field(default_factory=timestamp)
    origin_run_id: str
    original_input: str
    symbol: str
    data_mode: Literal['live', 'demo']
    cutoff: dict[str, Any]
    resolution: dict[str, Any]
    availability: dict[str, Any]
    records: list[SourceRecord] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    attempts: list[dict] = Field(default_factory=list)
    materials: list[dict] = Field(default_factory=list)
    memory_contexts: dict[str, str] = Field(default_factory=dict)
    memory_entries: list[dict] = Field(default_factory=list)
    calibration_summary: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self):
        return safe_json(self.model_dump(mode='json'))
