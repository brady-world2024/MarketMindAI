"""Identify model failures that are safe to retry within a web research run."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from typing import Literal

import httpx
from anthropic import APIConnectionError as AnthropicConnectionError, APIStatusError as AnthropicStatusError
from openai import APIConnectionError as OpenAIConnectionError, APIStatusError as OpenAIStatusError

try:
    from google.genai.errors import APIError as GoogleAPIError
    from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
except ImportError:
    # Older supported LangChain Google adapters do not use the google.genai SDK.
    _GOOGLE_API_ERRORS = _GOOGLE_WRAPPERS = ()
else:
    _GOOGLE_API_ERRORS = (GoogleAPIError,)
    _GOOGLE_WRAPPERS = (ChatGoogleGenerativeAIError,)

RetryReason = Literal["rate_limit", "connection"]
DEFAULT_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 5.0
_TEMPORARY_LIMITS = {"rate_limit_error", "rate_limit_exceeded"}
_PERMANENT_LIMITS = {
    "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
    "credit_balance_too_low", "out_of_credits",
}


@dataclass(frozen=True)
class RetryInstruction:
    reason: RetryReason
    delay_seconds: float


def _rate_limit_codes(body):
    if not isinstance(body, dict):
        return set()
    error = body.get("error", body)
    if not isinstance(error, dict):
        return set()
    codes = {value.lower() for key in ("code", "type", "reason")
             if isinstance(value := error.get(key), str)}
    details = error.get("details")
    if isinstance(details, list):
        codes.update(detail["reason"].lower() for detail in details
                     if isinstance(detail, dict) and detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo"
                     and isinstance(detail.get("reason"), str))
    return codes


def _valid_delay(value):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _retry_delay(response, now):
    if response is None:
        return DEFAULT_RETRY_DELAY
    header = response.headers.get("retry-after")
    seconds = _valid_delay(header)
    if seconds is None and header:
        try:
            date = parsedate_to_datetime(header)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = max(0, (date - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    # Some SDKs also use a millisecond header. Honor both if they disagree.
    milliseconds = _valid_delay(response.headers.get("retry-after-ms"))
    delays = (seconds, milliseconds / 1000 if milliseconds is not None else None)
    return max((delay for delay in delays if delay is not None), default=DEFAULT_RETRY_DELAY)


def retry_instruction(error: Exception, *, now: datetime | None = None) -> RetryInstruction | None:
    if isinstance(error, _GOOGLE_WRAPPERS):
        error = error.__cause__
    if isinstance(error, (OpenAIConnectionError, AnthropicConnectionError)):
        error = error.__cause__
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
        return RetryInstruction("connection", DEFAULT_RETRY_DELAY)

    if isinstance(error, (OpenAIStatusError, AnthropicStatusError)):
        status, response, body = error.status_code, error.response, error.body
    elif isinstance(error, _GOOGLE_API_ERRORS):
        status, response, body = error.code, error.response, error.details
    elif isinstance(error, httpx.HTTPStatusError):
        response = error.response
        status = response.status_code
        try:
            body = response.json()
        except (ValueError, httpx.StreamError):
            return None
    else:
        return None

    if status != 429 or (response is not None and response.headers.get("x-should-retry") == "false"):
        return None
    codes = _rate_limit_codes(body)
    if codes & _PERMANENT_LIMITS or not codes & _TEMPORARY_LIMITS:
        return None
    delay = _retry_delay(response, now)
    return RetryInstruction("rate_limit", delay) if delay <= MAX_RETRY_DELAY else None
