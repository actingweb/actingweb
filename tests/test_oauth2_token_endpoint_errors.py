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


def test_a_redirect_uri_with_a_user_name_is_refused(env: Any) -> None:
    """3.16 (verification 2026-11-10, Issue 5): ``https://claude.ai@evil.test``
    reads as claude.ai on a confirmation page while the code goes to evil.test."""
    server, _ = env
    for uri in ("https://claude.ai@evil.test/cb", "https://u:p@evil.test/cb"):
        handler = make_handler(
            server,
            body=json.dumps({"client_name": "x", "redirect_uris": [uri]}),
        )
        out = handler._handle_client_registration()
        assert handler.response.status_code == 400, uri
        assert out["error"] == "invalid_client_metadata"


def test_the_confirmation_names_the_host_without_userinfo() -> None:
    from actingweb.oauth2_server.oauth2_server import _shown_host

    assert _shown_host("https://claude.ai@evil.test/cb") == "evil.test"
    assert _shown_host("https://u:p@evil.test:8443/cb") == "evil.test:8443"
    assert _shown_host("https://claude.ai/api/mcp/auth_callback") == "claude.ai"
    assert _shown_host("not a url") == ""


def test_the_requested_trust_type_is_kept(env: Any) -> None:
    """Verification 2026-11-10: ``requested_trust_type`` was set on the
    registration data but not stored with the client."""
    server, _ = env
    resp = register(server, requested_trust_type="viewer")
    stored = server.client_registry.validate_client(resp["client_id"])
    assert stored is not None
    assert stored.get("requested_trust_type") == "viewer"
    plain = server.client_registry.validate_client(register(server)["client_id"])
    assert plain is not None and "requested_trust_type" not in plain


def test_a_registration_asking_for_admin_alone_is_refused(env: Any) -> None:
    """Verification 2026-11-10: WG14 sent admin together with
    client_credentials, so the 400 it records is the grant refusal."""
    server, _ = env
    handler = make_handler(
        server, body=json.dumps({"client_name": "x", "trust_type": "admin"})
    )
    out = handler._handle_client_registration()
    assert handler.response.status_code == 400
    assert out["error"] == "invalid_client_metadata"


@pytest.mark.parametrize(
    ("proto", "name"),
    [("https://", "__Host-aw_authz_nonce"), ("http://", "aw_authz_nonce")],
)
def test_the_flow_cookie_is_host_prefixed_over_https(
    env: Any, proto: str, name: str
) -> None:
    server, _ = env
    handler = make_handler(server)
    handler.config.proto = proto
    assert handler._cookie_name("aw_authz_nonce") == name
