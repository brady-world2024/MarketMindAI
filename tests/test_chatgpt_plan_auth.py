"""Local ChatGPT OAuth behavior, using signed identities and no external network."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import stat
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from marketmind_ai.auth import LocalChatGPTAuth, PlanError

ISSUER = "https://auth.openai.com"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Provider:
    def __init__(self, key):
        self.key = key
        self.claims = {}
        self.scope = SCOPES
        self.requests = []
        self.authorizations = []
        self.client_id = "oaiapp_test"
        self.token_error = None
        self.refresh_error = None
        self.refresh_count = 0
        self.revocation_error = None
        self.expires_in = 3600
        self.callback_mutate = lambda values: values
        self.subject = "subject-one"
        self.discover_updates = {}

    def token(self, nonce=None):
        claims = {"iss": ISSUER, "aud": self.client_id, "sub": self.subject,
                  "email": "same@example.com", "exp": int(time.time()) + 3600,
                  "iat": int(time.time())}
        if nonce is not None:
            claims["nonce"] = nonce
        claims.update(self.claims)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "key-one"})

    def handle(self, request):
        self.requests.append(request)
        if request.url.path.endswith("openid-configuration"):
            data = {"issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/api/accounts/authorize",
                    "token_endpoint": ISSUER + "/api/accounts/oauth/token",
                    "jwks_uri": ISSUER + "/.well-known/jwks.json",
                    "revocation_endpoint": ISSUER + "/oauth/revoke"}
            data.update(self.discover_updates)
            return httpx.Response(200, json=data)
        if request.url.path.endswith("jwks.json"):
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            jwk.update({"kid": "key-one", "use": "sig", "alg": "RS256"})
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path.endswith("/revoke"):
            return self.revocation_error or httpx.Response(200)
        assert request.url.path.endswith("/oauth/token")
        fields = parse_qs(request.content.decode())
        if fields["grant_type"] == ["refresh_token"]:
            self.refresh_count += 1
            time.sleep(0.03)
            if self.refresh_error:
                return self.refresh_error
            return httpx.Response(200, json={"access_token": "access-rotated-secret",
                "refresh_token": "refresh-rotated-secret", "token_type": "Bearer", "expires_in": 3600})
        if self.token_error:
            return self.token_error
        return httpx.Response(200, json={"access_token": "access-secret", "refresh_token": "refresh-secret",
            "id_token": self.token(self.authorizations[-1]["nonce"][0]),
            "token_type": "Bearer", "expires_in": self.expires_in, "scope": self.scope})

    def browser(self, url):
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.netloc == "auth.openai.com"
        values = parse_qs(parsed.query)
        self.authorizations.append(values)
        callback = {"code": "callback-code-secret", "state": values["state"][0], "client_id": self.client_id}
        callback = self.callback_mutate(callback)
        # A real loopback request establishes that the listener is already accepting connections.
        with httpx.Client(trust_env=False) as client:
            response = client.get(values["redirect_uri"][0], params=callback)
        assert "callback-code-secret" not in response.text
        return True


@pytest.fixture
def provider(signing_key):
    return Provider(signing_key)


@pytest.fixture
def auth(tmp_path, provider):
    client = httpx.Client(transport=httpx.MockTransport(provider.handle))
    service = LocalChatGPTAuth(tmp_path, http=client)
    yield service
    service.close()
    assert not client.is_closed
    client.close()


def connect(auth, provider, **kwargs):
    return auth.connect(timeout_seconds=2, open_browser=provider.browser, **kwargs)


def form(request):
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def test_constructor_accounts_and_selection_are_offline(tmp_path):
    def fail(request):
        pytest.fail("unexpected network access")
    client = httpx.Client(transport=httpx.MockTransport(fail))
    auth = LocalChatGPTAuth(tmp_path, http=client)
    assert auth.accounts() == []
    with pytest.raises(PlanError) as error:
        auth.select_account(None)
    assert error.value.code == "account_required"
    auth.close()
    assert not client.is_closed


def test_new_registration_validates_identity_and_exact_pkce_exchange(auth, provider):
    account = connect(auth, provider)
    values = provider.authorizations[0]
    assert values["client_id"] == ["dynamic_agent_client"]
    assert values["agent_name_hint"] == ["MarketMind AI"]
    assert values["scope"] == [SCOPES]
    assert values["resource"] == ["https://api.openai.com/v1"]
    redirect = urlsplit(values["redirect_uri"][0])
    assert (redirect.scheme, redirect.hostname, redirect.path) == ("http", "127.0.0.1", "/auth/callback")
    request = next(r for r in provider.requests if r.method == "POST")
    body = form(request)
    assert set(body) == {"grant_type", "client_id", "code", "code_verifier", "redirect_uri", "resource"}
    assert body["client_id"] == provider.client_id
    assert body["redirect_uri"] == values["redirect_uri"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert values["code_challenge"] == [challenge]
    assert values["code_challenge_method"] == ["S256"]
    assert account["email"] == "same@example.com"
    assert account["plan_usage_enabled"] is True
    assert account["status"] == "signed_in"
    assert auth.select_account(None) == account["account_id"]
    assert auth.access_token(account["account_id"]) == "access-secret"
    public = repr(account) + repr(auth.accounts()) + repr(auth)
    for secret in ["access-secret", "refresh-secret", "callback-code-secret", body["code_verifier"], values["nonce"][0]]:
        assert secret not in public


@pytest.mark.parametrize("change, expected", [
    (lambda c: {**c, "state": "wrong-state"}, "invalid_callback"),
    (lambda c: {**c, "state": [c["state"], c["state"]]}, "invalid_callback"),
    (lambda c: {"error": "access_denied", "state": c["state"]}, "access_denied"),
    (lambda c: {"error": "access_denied", "state": "wrong-state"}, "invalid_callback"),
    (lambda c: {"code": c["code"], "state": c["state"]}, "registration_incomplete"),
    (lambda c: {**c, "client_id": "dynamic_agent_client"}, "registration_incomplete"),
])
def test_callbacks_rejected_before_exchange(auth, provider, change, expected):
    provider.callback_mutate = change
    with pytest.raises(PlanError) as error:
        connect(auth, provider)
    assert error.value.code == expected
    assert not any(r.method == "POST" for r in provider.requests)
    assert auth.accounts() == []


@pytest.mark.parametrize("claims", [
    {"iss": "https://attacker.example"}, {"aud": "other-app"},
    {"exp": 1}, {"nonce": "wrong-nonce"}, {"sub": ""}, {"iat": int(time.time()) + 7200},
    {"aud": ["oaiapp_test", "other-app"]},
])
def test_invalid_signed_identity_never_saved(auth, provider, claims):
    provider.claims = claims
    with pytest.raises(PlanError) as error:
        connect(auth, provider)
    assert error.value.code == "invalid_identity"
    assert auth.accounts() == []


def test_missing_plan_permission_retains_identity_but_blocks_access(auth, provider):
    provider.scope = "openid profile email offline_access"
    account = connect(auth, provider)
    assert account["plan_usage_enabled"] is False
    assert account["status"] == "signed_in"
    with pytest.raises(PlanError) as error:
        auth.access_token(account["account_id"])
    assert error.value.code == "plan_usage_not_enabled"


def test_multiple_registrations_same_email_and_stable_host(auth, provider, tmp_path):
    first = connect(auth, provider)
    host = provider.authorizations[-1]["ext_agent_host_id"]
    assert host[0].startswith("urn:uuid:")
    provider.client_id = "oaiapp_second"
    second = connect(auth, provider)
    assert first["account_id"] != second["account_id"]
    assert provider.authorizations[-1]["ext_agent_host_id"] == host
    with pytest.raises(PlanError) as error:
        auth.select_account(None)
    assert error.value.code == "account_ambiguous"
    assert auth.select_account(second["account_id"]) == second["account_id"]
    later = LocalChatGPTAuth(tmp_path, http=auth._http)
    try:
        connect(later, provider, account_id=second["account_id"])
        values = provider.authorizations[-1]
        assert values["client_id"] == ["oaiapp_second"]
        assert "agent_name_hint" not in values
        assert values["ext_agent_host_id"] == host
        assert "id_token_hint" in values
    finally:
        later.close()


def test_reauth_identity_mismatch_preserves_original(auth, provider):
    original = connect(auth, provider)
    provider.subject = "someone-else"
    with pytest.raises(PlanError) as error:
        connect(auth, provider, account_id=original["account_id"])
    assert error.value.code == "identity_mismatch"
    assert auth.accounts() == [original]
    assert auth.access_token(original["account_id"]) == "access-secret"


def test_refresh_is_serialized_and_rotates_as_single_record(auth, provider, tmp_path):
    provider.expires_in = 0.01
    account = connect(auth, provider)
    time.sleep(0.02)
    other = LocalChatGPTAuth(tmp_path, http=auth._http)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            services = [auth, other] * 4
            results = list(pool.map(lambda service: service.access_token(account["account_id"]), services))
        assert results == ["access-rotated-secret"] * 8
        assert provider.refresh_count == 1
        request = next(r for r in provider.requests if r.method == "POST" and form(r).get("grant_type") == "refresh_token")
        assert form(request) == {"grant_type": "refresh_token", "client_id": provider.client_id,
                                 "refresh_token": "refresh-secret", "resource": "https://api.openai.com/v1"}
        assert auth.accounts()[0]["plan_usage_enabled"] is True  # omitted scope retains grant
    finally:
        other.close()


@pytest.mark.parametrize("code,terminal", [("invalid_grant", True), ("refresh_token_reused", True), ("server_error", False)])
def test_refresh_error_clears_only_terminal_session(auth, provider, code, terminal):
    provider.expires_in = 0.01
    first = connect(auth, provider)
    provider.client_id = "oaiapp_second"
    provider.expires_in = 3600
    second = connect(auth, provider)
    time.sleep(0.02)
    provider.refresh_error = httpx.Response(400 if terminal else 503, json={"error": code, "detail": "refresh-secret"}, headers={"x-request-id": "req-test"})
    with pytest.raises(PlanError) as error:
        auth.access_token(first["account_id"])
    assert error.value.code == code
    assert error.value.request_id == "req-test"
    assert "refresh-secret" not in str(error.value.as_dict()) + repr(error.value)
    first_after = next(a for a in auth.accounts() if a["account_id"] == first["account_id"])
    assert first_after["status"] == ("signed_out" if terminal else "signed_in")
    assert auth.access_token(second["account_id"]) == "access-secret"


def test_disconnect_unconfirmed_clears_local_session_and_keeps_registration(auth, provider):
    account = connect(auth, provider)
    provider.revocation_error = httpx.Response(503, json={"detail": "access-secret"})
    result = auth.disconnect(account["account_id"])
    assert result["remote_revoked"] is False
    assert result["status"] == "signed_out"
    request = next(r for r in provider.requests if r.url.path.endswith("/revoke"))
    assert form(request) == {"token": "refresh-secret", "token_type_hint": "refresh_token", "client_id": provider.client_id}
    count = len(provider.requests)
    with pytest.raises(PlanError) as error:
        auth.access_token(account["account_id"])
    assert error.value.code == "signed_out"
    assert len(provider.requests) == count
    assert auth.accounts()[0]["account_id"] == account["account_id"]


def test_protected_storage_and_symlink_refusal(auth, provider, tmp_path):
    connect(auth, provider)
    files = list((tmp_path / "chatgpt-plan").iterdir())
    assert stat.S_IMODE((tmp_path / "chatgpt-plan").stat().st_mode) == 0o700
    assert files
    assert all(stat.S_IMODE(file.stat().st_mode) == 0o600 for file in files)
    target = tmp_path / "other"
    target.write_text("untouched")
    credentials = tmp_path / "chatgpt-plan" / "credentials.json"
    credentials.unlink()
    credentials.symlink_to(target)
    with pytest.raises(PlanError) as error:
        auth.accounts()
    assert error.value.code == "unsafe_storage"
    assert target.read_text() == "untouched"


def test_error_contract_uses_only_safe_diagnostics():
    error = PlanError("invalid_grant", "access-secret", status=400, request_id="req-123",
                      recovery="refresh-secret", body_shape={"detail": "string"}, resume_client_id="oaiapp_resume")
    data = error.as_dict()
    assert error.code == "invalid_grant"
    assert data["resume_client_id"] == "oaiapp_resume"
    assert data["body_shape"] == {"detail": "string"}
    assert "access-secret" not in repr(error) + str(data)
    assert "refresh-secret" not in repr(error) + str(data)


def test_error_param_is_a_safe_field_path_and_shared_http_errors_keep_it():
    from marketmind_ai.auth.errors import response_error

    error = PlanError("subscription_sharing_unsupported_capability", param="tools[0]")
    assert error.param == "tools[0]"
    assert error.as_dict()["param"] == "tools[0]"
    response = httpx.Response(400, json={"error": {"code": error.code, "param": "input[1].content[0]",
                                                   "message": "refresh-secret"}})
    diagnosed = response_error(response)
    assert diagnosed.param == "input[1].content[0]"
    assert "refresh-secret" not in repr(diagnosed) + str(diagnosed.as_dict())
    for unsafe in ("Bearer access-secret", "tools[0]\nrefresh-secret", "https://attacker.example", 123):
        assert PlanError(error.code, param=unsafe).param is None


@pytest.mark.parametrize("code, recovery_fragment", [
    ("subscription_sharing_usage_limit_exceeded", "https://chatgpt.com/settings/usage"),
    ("subscription_sharing_user_not_eligible", "Do not repeat OAuth"),
    ("subscription_sharing_unsupported_capability", "unsupported"),
    ("subscription_sharing_usage_unavailable", "Preserve credentials"),
    ("subscription_sharing_user_unavailable", "Preserve credentials"),
])
def test_subscription_errors_explain_specific_recovery(code, recovery_fragment):
    assert recovery_fragment in PlanError(code).recovery


def test_storage_module_imports_without_posix_file_locking(tmp_path, monkeypatch):
    import builtins
    import importlib.util
    import marketmind_ai.auth.store as storage

    original_import = builtins.__import__

    def without_posix(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("not a POSIX platform")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_posix)
    spec = importlib.util.spec_from_file_location("marketmind_ai.auth._platform_test_store", storage.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.CredentialStore(tmp_path)
    with pytest.raises(PlanError) as error:
        with store.locked():
            pass
    assert error.value.code == "unsupported_storage_platform"
    assert not (tmp_path / "chatgpt-plan").exists()


def test_identity_only_token_response_has_no_inference_credentials():
    from marketmind_ai.auth.oauth import token_fields

    fields = token_fields({"id_token": "verified-separately", "scope": "openid profile email"}, require_id=True)
    assert fields["access_token"] is None
    assert fields["refresh_token"] is None
    assert fields["expires_at"] is None


def test_id_token_only_sign_in_is_retained(auth, provider, monkeypatch):
    original_handle = provider.handle

    def identity_only(request):
        response = original_handle(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"id_token": provider.token(provider.authorizations[-1]["nonce"][0]),
                                             "scope": "openid profile email"})
        return response

    monkeypatch.setattr(auth._http, "_transport", httpx.MockTransport(identity_only))
    account = connect(auth, provider)
    assert account["status"] == "signed_in"
    assert account["plan_usage_enabled"] is False
    assert account["expires_at"] is None
    with pytest.raises(PlanError) as error:
        auth.access_token(account["account_id"])
    assert error.value.code == "plan_usage_not_enabled"
    assert auth.disconnect(account["account_id"])["status"] == "signed_out"


def test_non_ascii_callback_state_fails_immediately(auth, provider):
    provider.callback_mutate = lambda values: {**values, "state": "☃"}
    started = time.monotonic()
    with pytest.raises(PlanError) as error:
        connect(auth, provider)
    assert error.value.code == "invalid_callback"
    assert time.monotonic() - started < 1
    assert not any(r.method == "POST" for r in provider.requests)


def test_partial_callback_headers_cannot_outlive_attempt():
    import socket
    from marketmind_ai.auth.callback import CallbackAttempt

    attempt = CallbackAttempt("state", timeout_seconds=0.2)
    parsed = urlsplit(attempt.redirect_uri)
    slow = socket.create_connection((parsed.hostname, parsed.port), timeout=1)
    try:
        slow.sendall(b"GET /auth/callback HTTP/1.1\r\nHost: ")
        with pytest.raises(PlanError) as error:
            attempt.wait()
        assert error.value.code == "authorization_timeout"
        attempt.close()
        assert not attempt._thread.is_alive()
    finally:
        slow.close()
        attempt.close()


def saved_session(auth, provider):
    """A stored session isolates logout retry tests from the browser transport."""
    account = {"account_id": "saved-account", "client_id": provider.client_id,
               "issuer": ISSUER, "subject": "subject-one", "email": "same@example.com",
               "access_token": "access-secret", "refresh_token": "refresh-secret",
               "id_token": "previously-verified", "scopes": SCOPES.split(),
               "expires_at": time.time() + 3600}
    with auth._store.locked() as transaction:
        transaction.data["accounts"][account["account_id"]] = account
        transaction.save()
    return account


@pytest.mark.parametrize("first_response", [httpx.Response(503), "network"])
def test_disconnect_retries_one_temporary_failure_then_confirms(auth, provider, monkeypatch, first_response):
    account = saved_session(auth, provider)
    original_handle = provider.handle
    calls = []
    delays = []

    def sometimes_unavailable(request):
        if request.url.path.endswith("/revoke"):
            calls.append(request)
            if len(calls) == 1:
                if first_response == "network":
                    raise httpx.ConnectError("refresh-secret", request=request)
                return first_response
        return original_handle(request)

    monkeypatch.setattr(auth._http, "_transport", httpx.MockTransport(sometimes_unavailable))
    monkeypatch.setattr("marketmind_ai.auth.service.time.sleep", delays.append)
    result = auth.disconnect(account["account_id"])
    assert result["remote_revoked"] is True
    assert result["status"] == "signed_out"
    assert len(calls) == 2
    assert delays == [0.25]


@pytest.mark.parametrize("status,expected_attempts", [(401, 1), (503, 2)])
def test_disconnect_retry_is_bounded_and_only_temporary(auth, provider, monkeypatch, status, expected_attempts):
    account = saved_session(auth, provider)
    provider.revocation_error = httpx.Response(status)
    monkeypatch.setattr("marketmind_ai.auth.service.time.sleep", lambda _: None)
    result = auth.disconnect(account["account_id"])
    assert result["remote_revoked"] is False
    assert len([r for r in provider.requests if r.url.path.endswith("/revoke")]) == expected_attempts
    assert auth.accounts()[0]["status"] == "signed_out"


def test_http_error_metadata_redacts_known_request_credentials():
    from marketmind_ai.auth.errors import response_error, safe_diagnostic
    from marketmind_ai.auth.oauth import request

    credential = "opaqueRequestCredential"
    assert safe_diagnostic("tools[0]", (credential,)) == "tools[0]"
    assert safe_diagnostic("prefix" + credential, (credential,)) is None
    response = httpx.Response(400, json={credential: "string", "error": {
        "code": credential, "param": "input." + credential}}, headers={"x-request-id": credential})
    diagnosed = response_error(response, credentials=(credential,))
    assert diagnosed.code == "request_failed"
    assert diagnosed.param is None
    assert diagnosed.request_id is None
    assert credential not in repr(diagnosed) + str(diagnosed.as_dict())
    client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(PlanError) as error:
            request(client, "POST", ISSUER + "/api/accounts/oauth/token", data={
                "grant_type": "authorization_code", "code": credential, "code_verifier": "other-secret"})
        assert credential not in repr(error.value) + str(error.value.as_dict())
    finally:
        client.close()


def test_refresh_fetches_verification_keys_before_rotating_and_recovers(auth, provider, monkeypatch):
    account = saved_session(auth, provider)
    with auth._store.locked() as transaction:
        transaction.data["accounts"][account["account_id"]]["expires_at"] = time.time() - 1
        transaction.save()
    original_handle = provider.handle
    key_unavailable = True
    order = []

    def rotating_with_identity(request):
        order.append((request.method, request.url.path))
        if request.url.path.endswith("jwks.json") and key_unavailable:
            return httpx.Response(503, json={"error": "server_error"})
        response = original_handle(request)
        if request.method == "POST" and request.url.path.endswith("/oauth/token"):
            body = response.json()
            body["id_token"] = provider.token()
            return httpx.Response(200, json=body)
        return response

    monkeypatch.setattr(auth._http, "_transport", httpx.MockTransport(rotating_with_identity))
    with pytest.raises(PlanError) as error:
        auth.access_token(account["account_id"])
    assert error.value.code == "server_error"
    assert provider.refresh_count == 0
    assert not any(method == "POST" for method, _ in order)
    with auth._store.locked() as transaction:
        saved = transaction.data["accounts"][account["account_id"]]
        assert saved["refresh_token"] == "refresh-secret"
        assert saved["access_token"] == "access-secret"
    key_unavailable = False
    order.clear()
    assert auth.access_token(account["account_id"]) == "access-rotated-secret"
    assert provider.refresh_count == 1
    key_index = next(i for i, (_, path) in enumerate(order) if path.endswith("jwks.json"))
    post_index = next(i for i, (method, _) in enumerate(order) if method == "POST")
    assert key_index < post_index
    assert not any(method == "GET" for method, _ in order[post_index + 1:])
    with auth._store.locked() as transaction:
        assert transaction.data["accounts"][account["account_id"]]["refresh_token"] == "refresh-rotated-secret"


@pytest.mark.parametrize("claim_change,expected", [({"sub": "other-person"}, "identity_mismatch"),
                                                     ({"aud": "other-client"}, "invalid_identity")])
def test_refresh_unusable_returned_identity_clears_session_after_rotation(auth, provider, monkeypatch, claim_change, expected):
    account = saved_session(auth, provider)
    with auth._store.locked() as transaction:
        transaction.data["accounts"][account["account_id"]]["expires_at"] = time.time() - 1
        transaction.save()
    provider.claims = claim_change
    original_handle = provider.handle

    def invalid_identity_after_rotation(request):
        response = original_handle(request)
        if request.method == "POST" and request.url.path.endswith("/oauth/token"):
            body = response.json()
            body["id_token"] = provider.token()
            return httpx.Response(200, json=body)
        return response

    monkeypatch.setattr(auth._http, "_transport", httpx.MockTransport(invalid_identity_after_rotation))
    with pytest.raises(PlanError) as error:
        auth.access_token(account["account_id"])
    assert error.value.code == expected
    assert provider.refresh_count == 1
    assert auth.accounts()[0]["status"] == "signed_out"
    count = len(provider.requests)
    with pytest.raises(PlanError) as signed_out:
        auth.access_token(account["account_id"])
    assert signed_out.value.code == "signed_out"
    assert len(provider.requests) == count
