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
    """A fault is reported, and the token is kept so that logging out again
    with it revokes the chain, the live refresh token included."""
    server, store, _first, second = _rotated()
    store.chain_delete_fault = "zero"

    out = _logout(server, second["access_token"])

    assert out["success"] is True
    assert out["message"] == "Logged out (token revocation failed)"
    assert second["refresh_token"] in store.names(ACTOR, REFRESH)

    store.chain_delete_fault = None
    out = _logout(server, second["access_token"])
    assert out["message"] == "Successfully logged out"
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)


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


def test_fastapi_cookie_logout_passes_a_failure_message_through() -> None:
    """The web UI branch of the FastAPI logout route builds its own response;
    it must not say "Logged out successfully" over a failed revocation."""
    from fastapi.responses import JSONResponse

    from actingweb.interface.integrations.fastapi_integration import _logout_message

    failed = JSONResponse({"message": "Logged out (token revocation failed)"})
    ok = JSONResponse({"message": "Successfully logged out"})

    assert _logout_message(failed) == "Logged out (token revocation failed)"
    assert _logout_message(ok) == "Logged out successfully"
    assert _logout_message(object()) == "Logged out successfully"
