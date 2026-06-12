from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from langgraph.checkpoint.sqlite import SqliteSaver


def _safe_ticker(value: str) -> str:
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum() or ch in {".", "_", "-"})
    if not cleaned:
        raise ValueError("ticker cannot be empty for checkpointing")
    return cleaned


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    safe = _safe_ticker(ticker)
    path = Path(data_dir) / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe}.db"


def thread_id(ticker: str, date: str) -> str:
    return hashlib.sha256(f"{ticker.upper()}:{date}".encode("utf-8")).hexdigest()[:16]


@contextmanager
def get_checkpointer(data_dir: str | Path, ticker: str) -> Generator[SqliteSaver, None, None]:
    db = _db_path(data_dir, ticker)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
    finally:
        conn.close()


def checkpoint_step(data_dir: str | Path, ticker: str, date: str) -> int | None:
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return None
    with get_checkpointer(data_dir, ticker) as saver:
        payload = saver.get_tuple({"configurable": {"thread_id": thread_id(ticker, date)}})
        if payload is None:
            return None
        return payload.metadata.get("step")


def has_checkpoint(data_dir: str | Path, ticker: str, date: str) -> bool:
    return checkpoint_step(data_dir, ticker, date) is not None


def clear_checkpoint(data_dir: str | Path, ticker: str, date: str) -> None:
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return
    tid = thread_id(ticker, date)
    conn = sqlite3.connect(str(db))
    try:
        for table in ("writes", "checkpoints"):
            try:
                conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
            except sqlite3.OperationalError:
                continue
        conn.commit()
    finally:
        conn.close()

