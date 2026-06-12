from __future__ import annotations

from typing import List

from ..config import provider_catalog
from ..llm_clients.model_catalog import MODEL_OPTIONS
from .models import ModelOption, ProviderOption


def build_provider_catalog() -> List[ProviderOption]:
    providers = []
    for option in provider_catalog():
        model_options = MODEL_OPTIONS.get(option.value, {})
        quick_models = model_options.get("quick") or [(model, model) for model in option.quick_models]
        deep_models = model_options.get("deep") or [(model, model) for model in option.deep_models]
        providers.append(
            ProviderOption(
                value=option.value,
                label=option.label,
                requires_api_key=option.requires_api_key,
                supports_custom_models=option.supports_custom_models,
                custom_model_placeholder=option.custom_model_placeholder or None,
                base_url=option.base_url or None,
                quick_models=[ModelOption(label=label, value=value) for label, value in quick_models],
                deep_models=[ModelOption(label=label, value=value) for label, value in deep_models],
            )
        )
    return providers


def supported_provider_values() -> set[str]:
    return {provider.value for provider in build_provider_catalog()}
