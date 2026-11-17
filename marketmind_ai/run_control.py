"""Cooperative stop and a single completion boundary per web research run."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from typing import Literal

TASK_TIMEOUT_SECONDS = 15 * 60
MODEL_TIMEOUT_SECONDS = 120
StopReason = Literal["cancelled", "timed_out", "budget_exhausted"]


class RunStopped(RuntimeError):
    def __init__(self, reason: StopReason):
        super().__init__(reason)
        self.reason = reason


class RunControl:
    def __init__(self, timeout_seconds=TASK_TIMEOUT_SECONDS, *, clock=monotonic, model_call_limit: int | None = None):
        self._clock = clock
        self._deadline = clock() + timeout_seconds
        self._lock = Lock()
        self._reason: StopReason | None = None
        self._sealed = False
        self._model_call_limit = model_call_limit
        self._calls_started = self._calls_completed = self._calls_failed = self._calls_with_tokens = 0
        self._calls_with_total_tokens = 0
        self._model_seconds = 0.0
        self._reported_tokens = None

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
            if self._sealed or self._reason not in (None, "cancelled"):
                return False
            self._reason = "cancelled"
            return True

    def check(self):
        if reason := self.reason:
            raise RunStopped(reason)

    def begin_model_call(self):
        with self._lock:
            self._expire()
            if self._reason is None and self._model_call_limit is not None and self._calls_started >= self._model_call_limit:
                self._reason = "budget_exhausted"
            if self._reason:
                raise RunStopped(self._reason)
            self._calls_started += 1
            return self._clock()

    def finish_model_call(self, started: float, *, failed: bool, tokens):
        with self._lock:
            if failed:
                self._calls_failed += 1
            else:
                self._calls_completed += 1
            self._model_seconds += max(0, self._clock() - started)
            if tokens is not None:
                self._calls_with_tokens += 1
                self._calls_with_total_tokens += tokens[2] is not None
                from .model_usage import combine_tokens
                self._reported_tokens = combine_tokens(self._reported_tokens or (None, None, None), tokens)

    def usage_snapshot(self) -> dict:
        with self._lock:
            tokens = self._reported_tokens or (None, None, None)
            return {
                "model_call_limit": self._model_call_limit,
                "calls_started": self._calls_started,
                "calls_completed": self._calls_completed,
                "calls_failed": self._calls_failed,
                "calls_with_reported_tokens": self._calls_with_tokens,
                "calls_with_reported_total_tokens": self._calls_with_total_tokens,
                "reported_input_tokens": tokens[0],
                "reported_output_tokens": tokens[1],
                "reported_total_tokens": tokens[2],
                "model_elapsed_ms": round(self._model_seconds * 1000),
            }

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
    control = active_run_control()
    if control is None:
        return model.invoke(value)

    from langchain_core.runnables import Runnable
    from .model_usage import UsageCapture, message_tokens

    capture = UsageCapture()
    started = control.begin_model_call()
    try:
        result = (model.invoke(value, config={"callbacks": [capture]})
                  if isinstance(model, Runnable) else model.invoke(value))
    except BaseException:
        control.finish_model_call(started, failed=True, tokens=capture.tokens)
        raise
    tokens = capture.tokens if isinstance(model, Runnable) else message_tokens(result)
    control.finish_model_call(started, failed=False, tokens=tokens)
    control.check()
    return result
