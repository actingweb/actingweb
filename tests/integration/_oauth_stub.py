"""A stand-in OAuth2 provider for the ``wire_oauth`` app.

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 0: the
OAuth2 and MCP rows (``WG14`` to ``WG17``) drive the library's real authorize,
callback and token handlers, so the provider's token, userinfo and JWKS
endpoints must answer. They are served by the ``wire_oauth`` app itself under
``/_stub/`` (one free port per test worker; the recorder skips the prefix,
since a real provider is not part of what crosses the wire), and they answer
fixed values, so a recording has nothing random from the provider in it.

The library's provider classes carry the real providers' endpoints. Two
subclasses replace them for an app whose ``fqdn`` was registered here, and
behave exactly as the library's classes for every other app in the process.
Not a test file.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import parse_qs

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jwt.algorithms import RSAAlgorithm

from actingweb import oauth2
from actingweb.interface import ActingWebApp

GOOGLE_CLIENT_ID = "wire-google-client"
GOOGLE_CLIENT_SECRET = "wire-google-secret"
APPLE_CLIENT_ID = "wire.apple.client"
# What the provider hands back, the same in every run.
PROVIDER_ACCESS_TOKEN = "wire-provider-access-token"
PROVIDER_CODE = "wire-provider-code"
_KID = "wire-kid"
# The provider's sign-in page: never fetched (a row plays the browser and goes
# straight to the callback), and https because the library's OAuth2 client
# refuses an http authorization endpoint.
AUTHORIZE_URL = "https://wire-provider.example.test/authorize"

# The user the provider signs in: set by a row before it drives a callback.
STUB: dict[str, Any] = {"email": None}

# fqdn -> the app's base URL, for the apps that use the stand-in.
_STUB_HOSTS: dict[str, str] = {}

_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def new_apple_signing_key_pem() -> str:
    """An ES256 key for Apple's client secret (the library mints it)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class _StubGoogle(oauth2.GoogleOAuth2Provider):
    def __init__(self, config: Any, provider_config: dict[str, Any] | None = None):
        super().__init__(config, provider_config)
        base = _STUB_HOSTS.get(config.fqdn)
        if base:
            self.auth_uri = AUTHORIZE_URL
            self.token_uri = f"{base}/_stub/token"
            self.userinfo_uri = f"{base}/_stub/userinfo"


class _StubApple(oauth2.AppleOAuth2Provider):
    def __init__(self, config: Any, provider_config: dict[str, Any] | None = None):
        base = _STUB_HOSTS.get(config.fqdn)
        if base:
            # Read by the parent's __init__ through ``self``.
            self.AUTH_URI = AUTHORIZE_URL
            self.TOKEN_URI = f"{base}/_stub/token"
            self.REVOCATION_URI = f"{base}/_stub/revoke"
            self.JWKS_URI = f"{base}/_stub/jwks"
        super().__init__(config, provider_config)


def configure_stub_providers(
    aw_app: ActingWebApp, proto: str, fqdn: str, apple_key_pem: str
) -> ActingWebApp:
    """Google and Apple, both pointed at this app's own ``/_stub/``."""
    _STUB_HOSTS[fqdn] = f"{proto}{fqdn}"
    oauth2._PROVIDER_REGISTRY["google"] = _StubGoogle  # pyright: ignore[reportPrivateUsage]
    oauth2._PROVIDER_REGISTRY["apple"] = _StubApple  # pyright: ignore[reportPrivateUsage]
    return aw_app.with_oauth(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scope="openid email profile",
        provider="google",
    ).with_oauth(
        client_id=APPLE_CLIENT_ID,
        client_secret="",
        scope="openid name email",
        provider="apple",
        apple_team_id="WIRETEAM01",
        apple_key_id="WIREKEY001",
        apple_private_key_pem=apple_key_pem,
        audiences=[APPLE_CLIENT_ID],
    )


def _id_token(email: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": APPLE_CLIENT_ID,
            "sub": "wire-apple-sub",
            "email": email,
            "email_verified": True,
            "iat": now,
            "exp": now + 600,
        },
        _RSA_KEY,
        algorithm="RS256",
        headers={"kid": _KID},
    )


def add_stub_routes(app: FastAPI) -> None:
    """The provider's token, userinfo and JWKS endpoints."""

    @app.post("/_stub/token")
    async def stub_token(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Parsed by hand: the harness does not install python-multipart.
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        email = STUB["email"]
        if form.get("code") != PROVIDER_CODE or not email:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        body: dict[str, Any] = {
            "access_token": PROVIDER_ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        if form.get("client_id") == APPLE_CLIENT_ID:
            body["id_token"] = _id_token(str(email))
        return JSONResponse(body)

    @app.get("/_stub/userinfo")
    async def stub_userinfo(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if request.headers.get("authorization") != f"Bearer {PROVIDER_ACCESS_TOKEN}":
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse(
            {
                "id": "wire-google-sub",
                "sub": "wire-google-sub",
                "email": STUB["email"],
                "verified_email": True,
                "name": "Wire User",
            }
        )

    @app.get("/_stub/jwks")
    async def stub_jwks() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        jwk = json.loads(RSAAlgorithm.to_jwk(_RSA_KEY.public_key()))
        jwk.update({"kid": _KID, "alg": "RS256", "use": "sig"})
        return JSONResponse({"keys": [jwk]})
