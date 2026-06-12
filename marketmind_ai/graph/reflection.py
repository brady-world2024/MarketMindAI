from __future__ import annotations

from typing import Any


class Reflector:
    def __init__(self, quick_thinking_llm: Any = None):
        self.quick_thinking_llm = quick_thinking_llm

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
    ) -> str:
        if self.quick_thinking_llm is None:
            correctness = "worked" if alpha_return > 0 else "failed" if alpha_return < 0 else "was roughly flat"
            return (
                f"The call {correctness} with alpha of {alpha_return:+.1%}. "
                f"The strongest lesson is to re-check whether the original thesis matched the realized move instead of trusting narrative quality alone. "
                f"Future runs should size conviction in line with the durability of the catalyst, not just the direction of the story."
            )
        messages = [
            (
                "system",
                "You are reviewing a completed trading decision with the outcome now known. "
                "Write exactly 2-4 sentences of plain prose. Mention whether the directional call was correct, cite the alpha figure, "
                "name the part of the thesis that held or failed, and give one concrete lesson for future analyses.",
            ),
            (
                "human",
                f"Raw return: {raw_return:+.1%}\nAlpha vs SPY: {alpha_return:+.1%}\n\nFinal Decision:\n{final_decision}",
            ),
        ]
        return str(self.quick_thinking_llm.invoke(messages).content)
