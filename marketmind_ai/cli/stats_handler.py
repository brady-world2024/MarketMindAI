from __future__ import annotations

import threading
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult

from .models import RunStatistics


@dataclass
class _SnapshotState:
    message_ids: set[str]
    tool_ids: set[str]


class StatsCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._started_at = perf_counter()
        self._snapshot_state = _SnapshotState(message_ids=set(), tool_ids=set())
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.agent_updates = 0
        self.snapshots_seen = 0

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return
        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata
        if usage_metadata:
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        with self._lock:
            self.tool_calls += 1

    def observe_snapshot(self, snapshot: Any) -> None:
        payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot
        with self._lock:
            self.snapshots_seen += 1
            for tool_call in payload.get("tool_calls", []):
                tool_id = str(tool_call.get("id", ""))
                if tool_id and tool_id not in self._snapshot_state.tool_ids:
                    self._snapshot_state.tool_ids.add(tool_id)
                    self.tool_calls = max(self.tool_calls, len(self._snapshot_state.tool_ids))
            current_agent = payload.get("current_agent")
            if current_agent:
                self.agent_updates += 1
            for message in payload.get("messages", []):
                message_id = str(message.get("id", ""))
                if message_id:
                    self._snapshot_state.message_ids.add(message_id)

    def get_stats(self) -> RunStatistics:
        with self._lock:
            return RunStatistics(
                llm_calls=self.llm_calls,
                tool_calls=self.tool_calls,
                tokens_in=self.tokens_in,
                tokens_out=self.tokens_out,
                agent_updates=self.agent_updates,
                snapshots_seen=self.snapshots_seen,
                message_count=len(self._snapshot_state.message_ids),
                elapsed_seconds=perf_counter() - self._started_at,
            )
