"""Collect provider usage before structured-output parsing discards it."""
from langchain_core.callbacks import BaseCallbackHandler


def _count(value):
    return value if type(value) is int and value >= 0 else None


def combine_tokens(left, right):
    return tuple(b if a is None else a if b is None else a + b for a, b in zip(left, right))


def message_tokens(message):
    usage = getattr(message, "usage_metadata", None) or {}
    metadata = getattr(message, "response_metadata", None) or {}
    provider = metadata.get("model_provider")
    if provider == "google_genai":
        # The adapter substitutes zero for omitted fields. A positive total
        # survives unchanged, but individual counts cannot be recovered here.
        total = _count(usage.get("total_tokens"))
        return (None, None, total) if total else None
    if provider in {"openai", "anthropic"}:
        # These adapters can fill missing counts and synthesize totals.
        return None
    values = tuple(_count(usage.get(key)) for key in ("input_tokens", "output_tokens", "total_tokens"))
    return values if any(value is not None for value in values) else None


class UsageCapture(BaseCallbackHandler):
    def __init__(self):
        self.tokens = None

    def _add(self, values):
        if values and any(value is not None for value in values):
            self.tokens = combine_tokens(self.tokens or (None, None, None), values)

    def on_llm_end(self, response, **kwargs):
        output = response.llm_output or {}
        if "token_usage" in output:
            raw = output["token_usage"] or {}
            self._add((_count(raw.get("prompt_tokens", raw.get("input_tokens"))),
                       _count(raw.get("completion_tokens", raw.get("output_tokens"))),
                       _count(raw.get("total_tokens"))))
            return
        if isinstance(raw := output.get("usage"), dict):
            self._add((_count(raw.get("input_tokens")), _count(raw.get("output_tokens")),
                       _count(raw.get("total_tokens"))))
            return
        for choices in response.generations:
            # Multiple choices can repeat one request's usage. Use one per prompt.
            for choice in choices:
                if tokens := message_tokens(getattr(choice, "message", None)):
                    self._add(tokens)
                    break
