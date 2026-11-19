"""Diagnostics that never include provider messages or credential material."""
from __future__ import annotations

import re
from typing import Any

_MESSAGES = {
    "account_required": "Connect a ChatGPT account first.",
    "account_ambiguous": "Choose a saved ChatGPT account explicitly.",
    "account_not_found": "The selected ChatGPT account was not found.",
    "signed_out": "The selected ChatGPT account is signed out.",
    "plan_usage_not_enabled": "ChatGPT plan usage has not been granted for this account.",
    "access_denied": "ChatGPT authorization was declined.",
    "invalid_callback": "The authorization callback did not match this attempt.",
    "authorization_timeout": "The ChatGPT authorization attempt expired.",
    "browser_unavailable": "The authorization browser could not be opened.",
    "callback_unavailable": "The local authorization callback could not be started.",
    "registration_incomplete": "ChatGPT did not provide an issued client registration.",
    "identity_mismatch": "The verified identity does not match the selected registration.",
    "invalid_identity": "The ChatGPT identity token could not be verified.",
    "invalid_provider_response": "ChatGPT returned an invalid response.",
    "invalid_discovery": "The ChatGPT authorization configuration was not trusted.",
    "unsafe_storage": "The local credential storage is not secure.",
    "storage_error": "The local credential storage could not be read or written.",
    "request_failed": "The ChatGPT request could not be completed.",
    "request_timed_out": "The ChatGPT request timed out.",
    "invalid_grant": "The ChatGPT authorization grant is no longer valid.",
    "closed": "The ChatGPT authorization service is closed.",
    "unsupported_storage_platform": "Secure local ChatGPT credential storage is unavailable on this platform.",
    "subscription_sharing_user_not_eligible": "ChatGPT plan usage is unavailable for the selected user, workspace, or policy.",
    "subscription_sharing_usage_limit_exceeded": "A ChatGPT plan usage limit was reached.",
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage availability could not be checked.",
    "subscription_sharing_user_unavailable": "ChatGPT user or workspace information is temporarily unavailable.",
    "subscription_sharing_unsupported_capability": "The request includes an unsupported ChatGPT plan capability.",
    "subscription_sharing_route_not_supported": "The requested ChatGPT plan route is unsupported.",
    "subscription_sharing_invalid_user": "The ChatGPT subscriber context could not be validated.",
    "chatpass_v2_scope_not_authorized": "The signed ChatGPT permission context does not authorize this operation.",
    "chatpass_v2_invalid_authorization_context": "The signed ChatGPT permission context could not be validated.",
    "model_not_available": "The selected model was not advertised for this ChatGPT account.",
    "invalid_stream": "ChatGPT returned an invalid event stream.",
    "stream_interrupted": "The ChatGPT event stream ended unexpectedly.",
    "response_incomplete": "ChatGPT did not complete the response.",
    "response_failed": "ChatGPT could not complete the response.",
    "probe_text_mismatch": "The text check did not return the expected result.",
    "probe_tool_mismatch": "The tool check did not return the expected result.",
    "probe_structured_mismatch": "The structured output check did not return the expected result.",
}
_TERMINAL_REFRESH = frozenset({"invalid_grant", "invalid_refresh_token", "token_expired",
    "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"})
_RECOVERY = {
    "subscription_sharing_usage_limit_exceeded": "Pause plan requests and review app limits at https://chatgpt.com/settings/usage. This code does not establish a plan reset time.",
    "subscription_sharing_user_not_eligible": "Review the selected user, workspace, and policy restriction. Do not repeat OAuth or the same inference request.",
    "subscription_sharing_unsupported_capability": "Inspect the error parameter and remove the unsupported request field, tool, model, or service-tier override before retrying.",
    "subscription_sharing_usage_unavailable": "Preserve credentials and retry later with bounded backoff.",
    "subscription_sharing_user_unavailable": "Preserve credentials and retry later with bounded backoff.",
    "subscription_sharing_route_not_supported": "Check the exact HTTP method and endpoint; use POST /v1/responses.",
    "subscription_sharing_invalid_user": "Preserve the request ID and diagnose the credential failure; sign in again only after confirmed revocation or a terminal refresh error.",
    "chatpass_v2_scope_not_authorized": "Check the selected client and granted scopes before trying again.",
    "chatpass_v2_invalid_authorization_context": "Check the selected client and grant configuration before trying again.",
    "invalid_client": "Fix the client registration configuration before trying again.",
    "request_failed": "Preserve credentials and check the connection before trying again.",
    "request_timed_out": "Preserve credentials and retry later with bounded backoff.",
}
_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[[0-9]+\]))*$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


def safe_identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


class PlanError(Exception):
    """A safe error surface; untrusted messages/recovery are deliberately ignored."""

    def __init__(self, code: str, message: str | None = None, *, status: int | None = None,
                 request_id: str | None = None, recovery: str | None = None,
                 body_shape: Any = None, resume_client_id: str | None = None, param: str | None = None):
        self.code = safe_identifier(code) or "provider_error"
        self.status = status if isinstance(status, int) and 100 <= status <= 599 else None
        self.request_id = safe_identifier(request_id)
        self.resume_client_id = safe_identifier(resume_client_id)
        self.body_shape = _safe_shape(body_shape)
        self.param = param if isinstance(param, str) and len(param) <= 128 and _FIELD_PATH.fullmatch(param) else None
        self.message = _MESSAGES.get(self.code, "The ChatGPT request was not successful.")
        self.recovery = _RECOVERY.get(self.code) or (
            "Start a fresh sign-in using the retained client registration."
            if self.resume_client_id else
            "Sign in again to the selected ChatGPT account."
            if self.code in _TERMINAL_REFRESH or self.code in {"signed_out", "invalid_identity", "identity_mismatch"} else
            "Enable app access in ChatGPT Settings, then sign in again."
            if self.code == "plan_usage_not_enabled" else
            "Check the connection and account settings before trying again."
        )
        super().__init__(self.message)

    def as_dict(self) -> dict:
        data = {"error": self.code, "code": self.code, "message": self.message,
                "status": self.status, "request_id": self.request_id,
                "recovery": self.recovery, "body_shape": self.body_shape, "param": self.param}
        if self.resume_client_id:
            data["resume_client_id"] = self.resume_client_id
        return data


def _safe_shape(value: Any) -> Any:
    # Callers may give key names or a map of key names to JSON type labels.
    labels = {"string", "number", "boolean", "null", "object", "array"}
    if value in ("non_json", "object", "array", "string", "number", "boolean", "null"):
        return value
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if safe_identifier(k) and isinstance(v, str) and v in labels}
    if isinstance(value, (list, tuple)):
        return [key for key in value if safe_identifier(key)]
    return None


def safe_diagnostic(value, credentials=()):
    """Remove known credential echoes without rewriting safe provider metadata."""
    if isinstance(value, str) and any(isinstance(secret, str) and secret and secret in value for secret in credentials):
        return None
    return value


def response_error(response, *, credentials=()) -> PlanError:
    """Keep only provider error codes, status, request ID and JSON structure."""
    credentials = tuple(credentials)
    try:
        body = response.json()
    except (ValueError, UnicodeError):
        body = None
        shape = "non_json"
    else:
        shape = sorted(k for k in body if safe_identifier(k) and safe_diagnostic(k, credentials) is not None) if isinstance(body, dict) else type_shape(body)
    code = param = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code") or error.get("type")
            param = error.get("param")
        elif isinstance(error, str):
            code = error
        code = code or body.get("code")
    return PlanError(safe_identifier(safe_diagnostic(code, credentials)) or "request_failed", status=response.status_code,
        request_id=safe_diagnostic(response.headers.get("x-request-id") or response.headers.get("openai-request-id"), credentials),
        body_shape=shape, param=safe_diagnostic(param, credentials))


def type_shape(value: Any) -> str:
    return "null" if value is None else "boolean" if isinstance(value, bool) else "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "number" if isinstance(value, (int, float)) else "string"
