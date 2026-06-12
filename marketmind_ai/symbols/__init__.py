from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    FundamentalValidationResult,
    PriceValidationResult,
    ResolveStatus,
    ResolvedTicker,
    SymbolCandidate,
    ValidationFlags,
)

SymbolResolution = ResolvedTicker

if TYPE_CHECKING:
    from .resolver import SymbolResolver, TickerResolutionError, format_resolution_message


def __getattr__(name: str):
    if name in {"SymbolResolver", "TickerResolutionError", "format_resolution_message"}:
        from .resolver import SymbolResolver, TickerResolutionError, format_resolution_message

        exports = {
            "SymbolResolver": SymbolResolver,
            "TickerResolutionError": TickerResolutionError,
            "format_resolution_message": format_resolution_message,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FundamentalValidationResult",
    "PriceValidationResult",
    "ResolveStatus",
    "ResolvedTicker",
    "SymbolCandidate",
    "SymbolResolution",
    "SymbolResolver",
    "TickerResolutionError",
    "ValidationFlags",
    "format_resolution_message",
]
