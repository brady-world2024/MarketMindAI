"""Single-user ChatGPT registrations; no API-key or external application credentials."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
import uuid
import webbrowser

import httpx

from .callback import CallbackAttempt
from .errors import PlanError, _TERMINAL_REFRESH, safe_identifier
from . import oauth
from .store import CredentialStore


def _public(account):
    signed_in = bool(account.get("id_token") or account.get("access_token"))
    return {"account_id": account["account_id"], "email": account.get("email"),
            "client_id": account["client_id"], "status": "signed_in" if signed_in else "signed_out",
            "plan_usage_enabled": bool(account.get("access_token")) and oauth.PLAN_SCOPE in account.get("scopes", []),
            "expires_at": account.get("expires_at")}


def _account(transaction, account_id):
    account = transaction.data["accounts"].get(account_id)
    if not isinstance(account, dict):
        raise PlanError("account_not_found")
    return account


def _clear(account):
    for name in ("access_token", "refresh_token", "id_token", "expires_at", "earliest_refresh_at", "token_type"):
        account.pop(name, None)
    account["generation"] = account.get("generation", 0) + 1


class LocalChatGPTAuth:
    """Protected local OAuth sessions, with explicit account selection."""

    def __init__(self, root: Path, http: httpx.Client | None = None):
        self._store = CredentialStore(Path(root))
        self._owns_http = http is None
        self._http = http if http is not None else httpx.Client(timeout=30, trust_env=False)
        self._closed = False

    def __repr__(self):
        return "<LocalChatGPTAuth>"

    def _check_open(self):
        if self._closed:
            raise PlanError("closed")

    def accounts(self) -> list[dict]:
        self._check_open()
        with self._store.locked() as transaction:
            return [_public(account) for account in transaction.data["accounts"].values()]

    def select_account(self, account_id: str | None = None) -> str:
        accounts = self.accounts()
        if account_id is not None:
            if any(account["account_id"] == account_id for account in accounts):
                return account_id
            raise PlanError("account_not_found")
        if not accounts:
            raise PlanError("account_required")
        if len(accounts) > 1:
            raise PlanError("account_ambiguous")
        return accounts[0]["account_id"]

    def connect(self, account_id=None, resume_client_id=None, timeout_seconds=600,
                open_browser=webbrowser.open) -> dict:
        self._check_open()
        if (not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
                or not 0 < timeout_seconds <= 3600):
            raise PlanError("authorization_timeout")
        if resume_client_id is not None and (not safe_identifier(resume_client_id) or resume_client_id == "dynamic_agent_client"):
            raise PlanError("registration_incomplete")
        with self._store.locked() as transaction:
            host_id = transaction.host_id()
            expected = dict(_account(transaction, account_id)) if account_id is not None else None
            if expected and resume_client_id and expected["client_id"] != resume_client_id:
                raise PlanError("identity_mismatch")
            if expected is None and resume_client_id:
                matches = [a for a in transaction.data["accounts"].values() if a["client_id"] == resume_client_id]
                if len(matches) > 1:
                    raise PlanError("account_ambiguous")
                expected = dict(matches[0]) if matches else None
        issued_client = expected["client_id"] if expected else resume_client_id
        configuration = oauth.discovery(self._http)
        state, nonce, verifier = (secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64))
        attempt = CallbackAttempt(state, timeout_seconds)
        try:
            query = {"client_id": issued_client or "dynamic_agent_client", "ext_agent_host_id": host_id,
                "response_type": "code", "redirect_uri": attempt.redirect_uri, "scope": oauth.SCOPES,
                "resource": oauth.RESOURCE, "state": state, "nonce": nonce, "code_challenge_method": "S256",
                "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
            if issued_client is None:
                query["agent_name_hint"] = "MarketMind AI"
            if expected:
                if expected.get("id_token"):
                    query["id_token_hint"] = expected["id_token"]
                if expected.get("email"):
                    query["login_hint"] = expected["email"]
            try:
                opened = open_browser(configuration["authorization_endpoint"] + "?" + urlencode(query))
            except Exception:
                raise PlanError("browser_unavailable") from None
            if opened is False:
                raise PlanError("browser_unavailable")
            callback = attempt.wait()
            callback_client = callback.get("client_id")
            if issued_client:
                if callback_client is not None and callback_client != issued_client:
                    raise PlanError("identity_mismatch")
            else:
                issued_client = callback_client
                if not safe_identifier(issued_client) or issued_client == "dynamic_agent_client":
                    raise PlanError("registration_incomplete")
            try:
                data = oauth.json_response(oauth.request(self._http, "POST", configuration["token_endpoint"], data={
                    "grant_type": "authorization_code", "client_id": issued_client, "code": callback["code"],
                    "code_verifier": verifier, "redirect_uri": attempt.redirect_uri, "resource": oauth.RESOURCE}))
            except PlanError as error:
                if error.code == "invalid_grant":
                    raise PlanError(error.code, status=error.status, request_id=error.request_id,
                        body_shape=error.body_shape, resume_client_id=issued_client) from None
                raise
            tokens = oauth.token_fields(data, require_id=True)
            identity = oauth.verify_identity(self._http, configuration, tokens["id_token"], issued_client,
                                             nonce=nonce, expected=expected)
            with self._store.locked() as transaction:
                accounts = transaction.data["accounts"]
                if expected:
                    existing = _account(transaction, expected["account_id"])
                    if existing.get("generation", 0) != expected.get("generation", 0):
                        raise PlanError("session_changed")
                else:
                    existing = next((a for a in accounts.values() if a["client_id"] == issued_client and
                        a["subject"] == identity["subject"] and a["issuer"] == identity["issuer"]), None)
                    # One issued client is never rebound to another verified identity.
                    if existing is None and any(a["client_id"] == issued_client for a in accounts.values()):
                        raise PlanError("identity_mismatch")
                saved = {"account_id": existing["account_id"] if existing else uuid.uuid4().hex,
                         "client_id": issued_client, **identity, **tokens,
                         "generation": (existing or {}).get("generation", 0) + 1}
                accounts[saved["account_id"]] = saved
                transaction.save()
                return _public(saved)
        finally:
            attempt.close()

    def access_token(self, account_id: str) -> str:
        self._check_open()
        # The lock stays held through refresh and commit. A stale request cannot
        # restore credentials after a competing process has signed the account out.
        with self._store.locked() as transaction:
            account = _account(transaction, account_id)
            if not account.get("access_token") and not account.get("id_token"):
                raise PlanError("signed_out")
            if oauth.PLAN_SCOPE not in account.get("scopes", []):
                raise PlanError("plan_usage_not_enabled")
            if not account.get("access_token"):
                raise PlanError("signed_out")
            if account.get("expires_at", 0) > time.time():
                return account["access_token"]
            if not account.get("refresh_token") or "offline_access" not in account.get("scopes", []):
                _clear(account)
                transaction.save()
                raise PlanError("signed_out")
            rotated = False
            try:
                configuration = oauth.discovery(self._http)
                # A returned ID token must be checkable without a network request
                # after the server has consumed the rotating refresh token.
                keys = oauth.identity_keys(self._http, configuration)
                response = oauth.request(self._http, "POST", configuration["token_endpoint"], data={
                    "grant_type": "refresh_token", "client_id": account["client_id"],
                    "refresh_token": account["refresh_token"], "resource": oauth.RESOURCE})
                rotated = True
                data = oauth.json_response(response)
                tokens = oauth.token_fields(data, previous=account)
                if "id_token" in data:
                    oauth.verify_identity(self._http, configuration, data["id_token"], account["client_id"],
                                          expected=account, keys=keys)
            except PlanError as error:
                terminal = error.code in _TERMINAL_REFRESH and (error.status is None or error.status < 500)
                untrusted_rotation = rotated and error.code in {"invalid_identity", "identity_mismatch", "invalid_provider_response"}
                if terminal or untrusted_rotation:
                    _clear(account)
                    transaction.save()
                raise
            account.update(tokens)
            account["generation"] = account.get("generation", 0) + 1
            transaction.save()
            if oauth.PLAN_SCOPE not in account["scopes"]:
                raise PlanError("plan_usage_not_enabled")
            return account["access_token"]

    def disconnect(self, account_id: str) -> dict:
        self._check_open()
        with self._store.locked() as transaction:
            account = _account(transaction, account_id)
            remote_revoked = False
            if account.get("refresh_token"):
                # One short backoff, at most two attempts, keeps logout bounded
                # while allowing transient discovery or revocation outages.
                for attempt_number in range(2):
                    try:
                        configuration = oauth.discovery(self._http)
                        endpoint = configuration.get("revocation_endpoint")
                        if endpoint:
                            response = oauth.request(self._http, "POST", endpoint, data={"token": account["refresh_token"],
                                "token_type_hint": "refresh_token", "client_id": account["client_id"]})
                            remote_revoked = response.status_code == 200
                        break
                    except PlanError as error:
                        temporary = ((error.status is not None and 500 <= error.status <= 599) or
                                     (error.status is None and error.code in {"request_failed", "request_timed_out"}))
                        if not temporary or attempt_number == 1:
                            break
                        time.sleep(0.25)
            _clear(account)
            transaction.save()
            return {**_public(account), "remote_revoked": remote_revoked}

    def close(self):
        if not self._closed:
            self._closed = True
            if self._owns_http:
                self._http.close()
