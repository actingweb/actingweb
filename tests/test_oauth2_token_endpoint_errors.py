"""``/oauth/token`` and ``/oauth/register`` return the server's OAuth error
code (RFC 6749 §5.2, RFC 7591 §3.2.2), not one derived from the status."""

import json
from typing import Any

import pytest

from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from tests.mcp_oauth_server_helpers import make_handler, make_server, register
from tests.mcp_token_double import MemoryStore, make_config


@pytest.fixture
def env() -> tuple[ActingWebOAuth2Server, MemoryStore]:
    config, store = make_config()
    return make_server(config), store


def _token(
    server: ActingWebOAuth2Server, body: dict[str, str]
) -> tuple[dict[str, Any], int, dict[str, str]]:
    handler = make_handler(server, body=body)
    out = handler._handle_token_request()
    return out, handler.response.status_code, handler.response.headers


def test_dead_refresh_token_is_invalid_grant(env: Any) -> None:
    server, _ = env
    resp = register(server)
    out, status, _ = _token(
        server,
        {
            "grant_type": "refresh_token",
            "refresh_token": "rt_dead",
            "client_id": resp["client_id"],
            "client_secret": resp["client_secret"],
        },
    )
    assert status == 400
    assert out["error"] == "invalid_grant"


def test_bad_code_is_invalid_grant(env: Any) -> None:
    server, _ = env
    resp = register(server)
    out, status, _ = _token(
        server,
        {
            "grant_type": "authorization_code",
            "code": "ac_bad",
            "redirect_uri": "https://client/cb",
            "client_id": resp["client_id"],
            "client_secret": resp["client_secret"],
        },
    )
    assert status == 400
    assert out["error"] == "invalid_grant"


def test_unknown_grant_is_unsupported_grant_type(env: Any) -> None:
    server, _ = env
    out, status, _ = _token(server, {"grant_type": "password", "client_id": "x"})
    assert status == 400
    assert out["error"] == "unsupported_grant_type"


def test_bad_secret_is_invalid_client_with_www_authenticate(env: Any) -> None:
    server, _ = env
    resp = register(server)
    out, status, headers = _token(
        server,
        {
            "grant_type": "refresh_token",
            "refresh_token": "rt_x",
            "client_id": resp["client_id"],
            "client_secret": "wrong",
        },
    )
    assert status == 401
    assert out["error"] == "invalid_client"
    assert "WWW-Authenticate" in headers


def test_registration_with_bad_auth_method_is_invalid_client_metadata(
    env: Any,
) -> None:
    server, _ = env
    handler = make_handler(
        server,
        body=json.dumps(
            {"client_name": "x", "token_endpoint_auth_method": "private_key_jwt"}
        ),
    )
    out = handler._handle_client_registration()
    assert handler.response.status_code == 400
    assert out["error"] == "invalid_client_metadata"


def test_purge_runs_before_the_grant(env: Any) -> None:
    """A slow first purge must not delay the response after a refresh token
    was consumed: the client would never receive the rotated pair and its
    retry after the grace period would read as theft."""
    server, _ = env
    order: list[str] = []
    tm = server.token_manager
    real_grant = server.handle_token_request

    def grant(params: dict[str, Any]) -> dict[str, Any]:
        order.append("grant")
        return real_grant(params)

    def purge() -> int:
        order.append("purge")
        return 0

    server.handle_token_request = grant  # type: ignore[method-assign]
    tm.maybe_purge_expired_tokens = purge  # type: ignore[method-assign]
    _token(server, {"grant_type": "nope"})
    assert order == ["purge", "grant"]


def test_purge_fault_does_not_fail_the_grant(env: Any) -> None:
    server, _ = env

    def purge() -> int:
        raise RuntimeError("store down")

    server.token_manager.maybe_purge_expired_tokens = purge  # type: ignore[method-assign]
    out, status, _ = _token(server, {"grant_type": "nope"})
    assert status == 400
    assert out["error"] == "unsupported_grant_type"
