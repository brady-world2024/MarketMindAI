from __future__ import annotations

from fastapi import APIRouter

from ..symbols import ResolvedTicker, SymbolResolver
from .models import ResolveSymbolRequest, SymbolSearchResponse


api_symbols_router = APIRouter(prefix="/api/symbols", tags=["symbols"])
router = api_symbols_router


def _resolver() -> SymbolResolver:
    return SymbolResolver()


def _search_symbols(query: str) -> SymbolSearchResponse:
    resolver = _resolver()
    candidates = resolver.search_symbols(query)
    return SymbolSearchResponse(query=query, candidates=candidates)


def _resolve_symbol(request: ResolveSymbolRequest) -> ResolvedTicker:
    resolver = _resolver()
    return resolver.resolve(request.query, request.analysis_date)


@api_symbols_router.get("/search", response_model=SymbolSearchResponse)
def search_symbols(query: str) -> SymbolSearchResponse:
    return _search_symbols(query)


@api_symbols_router.post("/resolve", response_model=ResolvedTicker)
def resolve_symbol(request: ResolveSymbolRequest) -> ResolvedTicker:
    return _resolve_symbol(request)
