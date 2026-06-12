from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import provider_defaults
from ..graph.request import AnalysisRequest
from .factory import create_llm_client


@dataclass
class ModelBundle:
    provider: str
    quick: Any | None
    deep: Any | None
    offline: bool


def build_model_bundle(request: AnalysisRequest) -> ModelBundle:
    provider = request.llm_provider.lower()
    if provider == "offline":
        return ModelBundle(provider=provider, quick=None, deep=None, offline=True)

    quick = _build_model(provider, request.quick_model, request)
    deep = _build_model(provider, request.deep_model, request)
    return ModelBundle(provider=provider, quick=quick, deep=deep, offline=False)


def _build_model(provider: str, model: str, request: AnalysisRequest):
    defaults = provider_defaults(provider)
    client = create_llm_client(
        provider,
        model,
        base_url=request.base_url or defaults.base_url or None,
        api_key=request.api_key or None,
        reasoning_effort=request.openai_reasoning_effort or None,
        thinking_level=request.google_thinking_level or None,
        effort=request.anthropic_effort or None,
        temperature=0.15,
        max_retries=1,
    )
    return client.get_llm()
