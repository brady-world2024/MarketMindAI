from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Literal

from ..default_config import build_default_config
from ..dataflows.config import dataflow_context
from ..dataflows.results import DataUnavailableError
from ..graph.runtime_support import build_offline_data_vendor_config

from ..symbols import ResolvedTicker, SymbolResolver
from .models import ResolveSymbolRequest, SymbolSearchResponse


api_symbols_router = APIRouter(prefix="/api/symbols", tags=["symbols"])
router = api_symbols_router


def _resolver() -> SymbolResolver:
    return SymbolResolver()


def _symbol_config(mode: str):
    overrides = {'data_mode': mode}
    if mode == 'demo':
        overrides['data_vendors'] = build_offline_data_vendor_config()
    return build_default_config(overrides=overrides)


def _search_symbols(query: str, data_mode: str = 'live') -> SymbolSearchResponse:
    resolver = _resolver()
    try:
        with dataflow_context(_symbol_config(data_mode)):
            candidates = resolver.search_symbols(query)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=503, detail={'message': str(exc), 'source_attempts': [a.to_dict() for a in exc.result.attempts]}) from None
    return SymbolSearchResponse(query=query, candidates=candidates)


def _resolve_symbol(request: ResolveSymbolRequest) -> ResolvedTicker:
    resolver = _resolver()
    with dataflow_context(_symbol_config(request.data_mode)):
        try:
            return resolver.resolve(request.query, request.analysis_date)
        except DataUnavailableError as exc:
            raise HTTPException(status_code=503, detail={'message': str(exc), 'source_attempts': [a.to_dict() for a in exc.result.attempts]}) from None


@api_symbols_router.get("/search", response_model=SymbolSearchResponse)
def search_symbols(query: str, data_mode: Literal['live', 'demo'] = 'live') -> SymbolSearchResponse:
    return _search_symbols(query, data_mode)


@api_symbols_router.post("/resolve", response_model=ResolvedTicker)
def resolve_symbol(request: ResolveSymbolRequest) -> ResolvedTicker:
    return _resolve_symbol(request)
