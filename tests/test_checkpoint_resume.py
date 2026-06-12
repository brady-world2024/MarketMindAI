import tempfile
import unittest
from typing import TypedDict

from langgraph.graph import END, StateGraph

from marketmind_ai.graph.checkpointer import (
    checkpoint_step,
    clear_checkpoint,
    get_checkpointer,
    has_checkpoint,
    thread_id,
)


_should_crash = False


class CounterState(TypedDict):
    count: int


def node_a(state: CounterState) -> dict:
    return {"count": state["count"] + 1}


def node_b(state: CounterState) -> dict:
    if _should_crash:
        raise RuntimeError("simulated crash")
    return {"count": state["count"] + 10}


def build_graph() -> StateGraph:
    graph = StateGraph(CounterState)
    graph.add_node("analyst", node_a)
    graph.add_node("trader", node_b)
    graph.set_entry_point("analyst")
    graph.add_edge("analyst", "trader")
    graph.add_edge("trader", END)
    return graph


class CheckpointResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "NVDA"
        self.date = "2026-06-12"

    def test_crash_then_resume(self):
        global _should_crash
        builder = build_graph()
        config = {"configurable": {"thread_id": thread_id(self.ticker, self.date)}}

        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=config)

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))
        self.assertEqual(checkpoint_step(self.tmpdir, self.ticker, self.date), 1)

        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke(None, config=config)

        self.assertEqual(result["count"], 11)

    def test_clear_checkpoint_forces_fresh_start(self):
        global _should_crash
        builder = build_graph()
        config = {"configurable": {"thread_id": thread_id(self.ticker, self.date)}}

        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=config)

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))
        clear_checkpoint(self.tmpdir, self.ticker, self.date)
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, self.date))

        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config=config)

        self.assertEqual(result["count"], 11)


if __name__ == "__main__":
    unittest.main()

