"""``/oauth/logout`` with an MCP bearer token revokes it in the MCP token store.

Before 3.15 the route only knew the SPA session store, so an MCP connector's
token, and its refresh-token chain, stayed live after a logout.
"""

from typing import Any
from unittest import mock

from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from tests.mcp_oauth_server_helpers import make_handler, make_server
from tests.mcp_token_double import MemoryStore, make_config

ACTOR = "actor-logout"
CLIENT = "mcp_client_logout"
TOKENS = "mcp_tokens"
REFRESH = "mcp_refresh_tokens"


def _rotated() -> tuple[
    ActingWebOAuth2Server, MemoryStore, dict[str, Any], dict[str, Any]
]:
    config, store = make_config()
    server = make_server(config)
    tm = server.token_manager
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    first = tm.exchange_authorization_code(code, CLIENT)
    assert first
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    return server, store, first, second


def _logout(server: ActingWebOAuth2Server, token: str) -> dict[str, Any]:
    handler = make_handler(
        server,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    return handler._handle_logout_request("POST")


def test_logout_revokes_the_mcp_token_and_its_chain() -> None:
    server, store, first, second = _rotated()

    out = _logout(server, second["access_token"])

    assert out["success"] is True
    assert out["message"] == "Successfully logged out"
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)
    # The consumed predecessor cannot rotate inside the grace window either.
    assert (
        server.token_manager.refresh_access_token(first["refresh_token"], CLIENT)
        is None
    )


def test_logout_after_a_revocation_fault_can_be_retried() -> None:
    """A fault answers 503 with Retry-After and keeps the token, so logging
    out again with it revokes the chain, the live refresh token included."""
    server, store, _first, second = _rotated()
    store.chain_delete_fault = "zero"

    handler = make_handler(
        server,
        headers={
            "Authorization": f"Bearer {second['access_token']}",
            "Accept": "application/json",
        },
    )
    out = handler._handle_logout_request("POST")

    assert out["success"] is False
    assert out["error"] == "temporarily_unavailable"
    assert handler.response.status_code == 503
    assert handler.response.headers["Retry-After"] == "5"
    assert second["refresh_token"] in store.names(ACTOR, REFRESH)

    store.chain_delete_fault = None
    out = _logout(server, second["access_token"])
    assert out["message"] == "Successfully logged out"
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)


def test_a_lookup_fault_on_logout_still_evicts_the_cached_token() -> None:
    """When the fault hits before revoke_token can evict, the logout handler
    clears this process's cache itself; a cached token must not outlive a
    logout that answered 503."""
    from actingweb.constants import ACCESS_TOKEN_INDEX_BUCKET
    from actingweb.handlers import mcp as mcp_mod

    server, store, _first, second = _rotated()
    mcp_mod._token_cache[second["access_token"]] = {"actor_id": ACTOR}
    store.faulty_buckets.add(ACCESS_TOKEN_INDEX_BUCKET)
    try:
        handler = make_handler(
            server,
            headers={
                "Authorization": f"Bearer {second['access_token']}",
                "Accept": "application/json",
            },
        )
        out = handler._handle_logout_request("POST")
        assert out["error"] == "temporarily_unavailable"
        assert second["access_token"] not in mcp_mod._token_cache
    finally:
        store.faulty_buckets.clear()
        mcp_mod._token_cache.pop(second["access_token"], None)


def test_a_session_token_still_goes_to_the_session_store() -> None:
    server, _store, _first, _second = _rotated()
    session_manager = mock.MagicMock()
    session_manager.validate_access_token.return_value = None
    with mock.patch(
        "actingweb.oauth_session.get_oauth2_session_manager",
        return_value=session_manager,
    ):
        _logout(server, "0123456789abcdef0123456789abcdef01234567")
    session_manager.revoke_access_token.assert_called_once()


def test_sdk_logout_does_not_claim_success_on_a_fault() -> None:
    server, store, _first, second = _rotated()
    store.chain_delete_fault = "zero"

    out = server.handle_logout_request(second["access_token"])

    assert out["message"] == "Logged out (with errors)"


def _aw_app() -> Any:
    from actingweb.interface import ActingWebApp

    return ActingWebApp(
        aw_type="urn:actingweb:test",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_web_ui(enable=True)


def _fastapi_client() -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    _aw_app().integrate_fastapi(app)
    return TestClient(app)


def _flask_client() -> Any:
    from flask import Flask

    app = Flask(__name__)
    _aw_app().integrate_flask(app)
    return app.test_client()


RETRY = {
    "action": "retry",
    "message": "Token store temporarily unavailable; retry the logout",
}
BEARER = {"Authorization": "Bearer aw_route_token_0123456789"}


def _patched_logout(outcome: dict[str, Any]) -> Any:
    return mock.patch(
        "actingweb.handlers.oauth2_endpoints.OAuth2EndpointsHandler."
        "_handle_provider_token_logout",
        return_value=outcome,
    )


def test_faulted_bearer_logout_is_503_with_retry_after_on_fastapi() -> None:
    """A 200 would tell the client it is done; the token was kept for a
    retry, so the route says to retry."""
    with _patched_logout(RETRY):
        resp = _fastapi_client().post("/oauth/logout", headers=BEARER)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert resp.json()["error"] == "temporarily_unavailable"
    assert "set-cookie" not in resp.headers


def test_faulted_bearer_logout_is_503_with_retry_after_on_flask() -> None:
    with _patched_logout(RETRY):
        resp = _flask_client().post("/oauth/logout", headers=BEARER)
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    assert resp.get_json()["error"] == "temporarily_unavailable"


def test_bearer_logout_success_is_still_200_on_fastapi() -> None:
    ok = {
        "action": "success",
        "message": "Successfully logged out",
        "clear_cookies": ["oauth_token"],
        "redirect_url": "https://test.example.com/",
    }
    with _patched_logout(ok):
        resp = _fastapi_client().post("/oauth/logout", headers=BEARER)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_fastapi_cookie_logout_reports_a_failed_revocation() -> None:
    """The web UI branch builds its own response from the handler's."""
    failed = {
        "action": "success",
        "message": "Logged out (token revocation failed)",
        "clear_cookies": ["oauth_token"],
        "redirect_url": "https://test.example.com/",
    }
    client = _fastapi_client()
    client.cookies.set("oauth_token", "0123456789abcdef")
    with _patched_logout(failed):
        resp = client.post(
            "/oauth/logout", headers={"Content-Type": "application/json"}
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "success": True,
        "message": "Logged out (token revocation failed)",
        "redirect_url": "/",
    }


def test_fastapi_cookie_logout_reports_a_handler_failure() -> None:
    client = _fastapi_client()
    client.cookies.set("oauth_token", "0123456789abcdef")
    with mock.patch(
        "actingweb.handlers.oauth2_endpoints.OAuth2EndpointsHandler."
        "_handle_logout_request",
        autospec=True,
        side_effect=lambda self, method="GET": self.error_response(
            500, "Internal server error during logout"
        ),
    ):
        resp = client.post(
            "/oauth/logout", headers={"Content-Type": "application/json"}
        )
    body = resp.json()
    assert body["success"] is False
    assert body["message"] != "Logged out successfully"


def test_logout_outcome_helper() -> None:
    from fastapi.responses import JSONResponse

    from actingweb.interface.integrations.fastapi_integration import _logout_outcome

    assert _logout_outcome(
        JSONResponse({"message": "Logged out (token revocation failed)"})
    ) == (True, "Logged out (token revocation failed)")
    assert _logout_outcome(JSONResponse({"message": "Successfully logged out"})) == (
        True,
        "Logged out successfully",
    )
    assert _logout_outcome(
        JSONResponse({"error": "server_error", "error_description": "x"}, 500)
    ) == (False, "x")
    assert _logout_outcome(object()) == (True, "Logged out successfully")
