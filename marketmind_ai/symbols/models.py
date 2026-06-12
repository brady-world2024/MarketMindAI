from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ResolveStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SymbolCandidate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    name: str
    exchange: Optional[str] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    type: Optional[str] = Field(default=None, validation_alias=AliasChoices("type", "instrument_type"))
    provider: Optional[str] = None
    match_score: Optional[float] = None

    @property
    def instrument_type(self) -> str:
        return self.type or ""

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class PriceValidationResult(BaseModel):
    valid: bool
    latest_quote_exists: bool = False
    latest_price: Optional[float] = None
    recent_history_exists: bool = False
    history_points: int = 0
    stale: bool = False
    latest_trade_date: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class FundamentalValidationResult(BaseModel):
    valid: bool
    company_profile_exists: bool = False
    company_name_exists: bool = False
    exchange_exists: bool = False
    financial_statements_exist: bool = False
    income_statement_exists: bool = False
    balance_sheet_exists: bool = False
    cashflow_exists: bool = False
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class ValidationFlags(BaseModel):
    price_data: bool = False
    fundamental_data: bool = False

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class ResolvedTicker(BaseModel):
    status: ResolveStatus
    original_input: str
    normalized_query: str
    resolved_symbol: Optional[str] = None
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    confidence: Optional[float] = None
    candidates: list[SymbolCandidate] = Field(default_factory=list)
    reason: Optional[str] = None
    validation: ValidationFlags = Field(default_factory=ValidationFlags)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
