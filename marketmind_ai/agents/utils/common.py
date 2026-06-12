from __future__ import annotations


def build_instrument_context(ticker: str) -> str:
    return (
        f"The instrument to analyze is `{ticker}`. Use this exact ticker in every tool call, "
        "evidence citation, and recommendation, including any exchange suffix."
    )


def get_language_instruction(language: str) -> str:
    cleaned = str(language or "").strip()
    if not cleaned or cleaned.lower() == "english":
        return ""
    return f" Write your full response in {cleaned}."
