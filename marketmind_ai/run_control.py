"""Cooperative stop and a single completion boundary per web research run."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from typing import Literal

TASK_TIMEOUT_SECONDS = 15 * 60
MODEL_TIMEOUT_SECONDS = 120
StopReason = Literal["cancelled", "timed_out"]


class RunStopped(RuntimeError):
    def __init__(self, reason: StopReason):
        super().__init__(reason)
        self.reason = reason


class RunControl:
    def __init__(self, timeout_seconds=TASK_TIMEOUT_SECONDS, *, clock=monotonic):
        self._clock = clock
        self._deadline = clock() + timeout_seconds
        self._lock = Lock()
        self._reason: StopReason | None = None
        self._sealed = False

    def _expire(self):
        if not self._sealed and self._reason is None and self._clock() >= self._deadline:
            self._reason = "timed_out"

    @property
    def reason(self) -> StopReason | None:
        with self._lock:
            self._expire()
            return self._reason

    def cancel(self) -> bool:
        with self._lock:
            self._expire()
            if self._sealed or self._reason == "timed_out":
                return False
            self._reason = "cancelled"
            return True

    def check(self):
        if reason := self.reason:
            raise RunStopped(reason)

    def finish_reason(self) -> StopReason | None:
        with self._lock:
            self._expire()
            self._sealed = True
            return self._reason

    def seal(self):
        """Reserve the outcome immediately before writing the final report."""
        with self._lock:
            self._expire()
            if self._reason:
                raise RunStopped(self._reason)
            self._sealed = True


_active_control: ContextVar[RunControl | None] = ContextVar("active_run_control", default=None)


@contextmanager
def use_run_control(control):
    token = _active_control.set(control)
    try:
        yield
    finally:
        _active_control.reset(token)


def active_run_control():
    return _active_control.get()


def check_running():
    if control := active_run_control():
        control.check()


def seal_run():
    if control := active_run_control():
        control.seal()


def invoke_model(model, value):
    check_running()
    result = model.invoke(value)
    check_running()
    return result
