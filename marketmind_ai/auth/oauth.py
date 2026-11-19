"""OpenAI public-client OAuth transport and signed OIDC identity verification."""
from __future__ import annotations

import math
import secrets
import time
from urllib.parse import urlsplit

import httpx
import jwt

from .errors import PlanError, response_error

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


def request(http, method, url, **kwargs):
    try:
        response = http.request(method, url, follow_redirects=False, **kwargs)
    except httpx.TimeoutException:
        raise PlanError("request_timed_out") from None
    except httpx.HTTPError:
        raise PlanError("request_failed") from None
    if not 200 <= response.status_code < 300:
        data = kwargs.get("data")
        credentials = tuple(data[key] for key in ("code", "code_verifier", "nonce", "access_token", "refresh_token", "id_token", "token")
                            if isinstance(data, dict) and isinstance(data.get(key), str))
        raise response_error(response, credentials=credentials)
    return response


def json_response(response):
    try:
        data = response.json()
    except (ValueError, UnicodeError):
        raise PlanError("invalid_provider_response", status=response.status_code, body_shape="non_json") from None
    if not isinstance(data, dict):
        raise PlanError("invalid_provider_response", status=response.status_code)
    return data


def trusted_endpoint(value):
    if not isinstance(value, str):
        raise PlanError("invalid_discovery")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "auth.openai.com" or
            parsed.username or parsed.password or parsed.fragment or parsed.query or not parsed.path.startswith("/")):
        raise PlanError("invalid_discovery")
    return value


def discovery(http):
    data = json_response(request(http, "GET", DISCOVERY))
    if data.get("issuer") != ISSUER:
        raise PlanError("invalid_discovery")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        data[key] = trusted_endpoint(data.get(key))
    if data.get("revocation_endpoint"):
        data["revocation_endpoint"] = trusted_endpoint(data["revocation_endpoint"])
    # Retained ID tokens are sent only to this exact documented authorization endpoint.
    if data["authorization_endpoint"] != ISSUER + "/api/accounts/authorize":
        raise PlanError("invalid_discovery")
    return data


def identity_keys(http, configuration):
    """Fetch and parse trusted keys before an irreversible token rotation."""
    jwks = json_response(request(http, "GET", configuration["jwks_uri"]))
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise PlanError("invalid_identity")
    parsed = {}
    try:
        for key in keys:
            if (not isinstance(key, dict) or key.get("kty") != "RSA" or key.get("use", "sig") != "sig"
                    or key.get("alg", "RS256") != "RS256"):
                continue
            operations = key.get("key_ops", ["verify"])
            if not isinstance(operations, list) or "verify" not in operations:
                continue
            kid = key.get("kid")
            if not isinstance(kid, str) or not kid or kid in parsed:
                raise PlanError("invalid_identity")
            parsed[kid] = jwt.PyJWK.from_dict(key, algorithm="RS256").key
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
        raise PlanError("invalid_identity") from None
    if not parsed:
        raise PlanError("invalid_identity")
    return parsed


def verify_identity(http, configuration, encoded, client_id, *, nonce=None, expected=None, keys=None):
    if not isinstance(encoded, str) or not encoded:
        raise PlanError("invalid_identity")
    try:
        header = jwt.get_unverified_header(encoded)
        # Algorithms are selected locally. Never use jku/x5u or a URL in the token.
        if header.get("alg") not in ("RS256",) or not isinstance(header.get("kid"), str):
            raise PlanError("invalid_identity")
        verification_keys = keys if keys is not None else identity_keys(http, configuration)
        key = verification_keys.get(header["kid"])
        if key is None:
            raise PlanError("invalid_identity")
        required = ["iss", "aud", "sub", "exp", "iat"] + (["nonce"] if nonce is not None else [])
        claims = jwt.decode(encoded, key, algorithms=["RS256"], audience=client_id, issuer=ISSUER,
                            options={"require": required})
        if (not isinstance(claims.get("sub"), str) or not claims["sub"] or
                not isinstance(claims.get("iat"), (float, int)) or isinstance(claims["iat"], bool) or
                not isinstance(claims.get("exp"), (float, int)) or isinstance(claims["exp"], bool) or
                not math.isfinite(claims["iat"]) or not math.isfinite(claims["exp"]) or
                claims["iat"] > time.time() or claims["exp"] <= time.time() or claims["exp"] <= claims["iat"]):
            raise PlanError("invalid_identity")
        if nonce is not None and (not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(claims["nonce"], nonce)):
            raise PlanError("invalid_identity")
        audiences = claims["aud"]
        if ((isinstance(audiences, list) and len(audiences) > 1 and claims.get("azp") != client_id)
                or ("azp" in claims and claims["azp"] != client_id)):
            raise PlanError("invalid_identity")
    except PlanError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
        raise PlanError("invalid_identity") from None
    if expected and (claims["sub"] != expected["subject"] or client_id != expected["client_id"] or claims["iss"] != expected["issuer"]):
        raise PlanError("identity_mismatch")
    return {"issuer": claims["iss"], "subject": claims["sub"],
            "email": claims.get("email") if isinstance(claims.get("email"), str) else None}


def token_fields(data, *, previous=None, require_id=False):
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if require_id and (not isinstance(data.get("id_token"), str) or not data["id_token"]):
        raise PlanError("invalid_provider_response")
    if previous is None or "scope" in data:
        if not isinstance(data.get("scope"), str):
            raise PlanError("invalid_provider_response")
        scopes = sorted(set(data["scope"].split()))
    else:
        scopes = previous["scopes"]
    # A signed identity can survive declined plan permission without any grant to
    # call inference. Verification still happens before these fields are saved.
    if require_id and not access and PLAN_SCOPE not in scopes:
        if any(data.get(key) is not None for key in ("access_token", "refresh_token", "token_type", "expires_in")):
            raise PlanError("invalid_provider_response")
        return {"access_token": None, "refresh_token": None, "id_token": data["id_token"],
                "token_type": None, "scopes": scopes, "expires_at": None, "earliest_refresh_at": None}
    if (not isinstance(access, str) or not access or
            not isinstance(data.get("token_type"), str) or data["token_type"].lower() != "bearer" or
            not isinstance(expires_in, (float, int)) or isinstance(expires_in, bool) or
            not math.isfinite(expires_in) or expires_in <= 0):
        raise PlanError("invalid_provider_response")
    # The direct renewable-session flow rotates its refresh token on every refresh.
    if (previous is not None or "offline_access" in scopes) and (not isinstance(refresh, str) or not refresh):
        raise PlanError("invalid_provider_response")
    if refresh is not None and not isinstance(refresh, str):
        raise PlanError("invalid_provider_response")
    return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
            "id_token": data.get("id_token") if "id_token" in data else (previous or {}).get("id_token"),
            "scopes": scopes, "expires_at": time.time() + expires_in,
            "earliest_refresh_at": data.get("earliest_refresh_at")}
