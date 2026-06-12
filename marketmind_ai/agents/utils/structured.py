from __future__ import annotations

from typing import Any, Callable, Optional


def bind_structured(llm: Any, schema: type[Any], agent_label: str = "") -> Optional[Any]:
    if llm is None:
        return None
    try:
        return llm.with_structured_output(schema)
    except Exception:
        return None


def invoke_structured_or_freetext(
    structured_llm: Any,
    fallback_llm: Any,
    prompt: Any,
    renderer: Callable[[Any], str],
    agent_label: str,
) -> str:
    if structured_llm is not None:
        result = structured_llm.invoke(prompt)
        return renderer(result)
    if fallback_llm is None:
        raise RuntimeError(f"{agent_label} has no available runtime")
    response = fallback_llm.invoke(prompt)
    return str(getattr(response, "content", response))
