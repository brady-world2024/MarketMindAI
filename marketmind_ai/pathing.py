from __future__ import annotations

import re


_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9.^_-]+$")


def safe_ticker_component(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ticker component must be a string")
    if any(ch.isspace() for ch in value):
        raise ValueError("ticker component contains unsupported characters")
    cleaned = value.upper()
    if not cleaned:
        raise ValueError("ticker component cannot be empty")
    if len(cleaned) > 32:
        raise ValueError("ticker component is too long")
    if any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t", " ")):
        raise ValueError("ticker component contains unsupported characters")
    if cleaned in {".", ".."} or set(cleaned) == {"."}:
        raise ValueError("ticker component cannot be dot-only")
    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("ticker component cannot contain path separators")
    if not _SAFE_COMPONENT_RE.fullmatch(cleaned):
        raise ValueError("ticker component contains unsupported characters")
    return cleaned


__all__ = ["safe_ticker_component"]
