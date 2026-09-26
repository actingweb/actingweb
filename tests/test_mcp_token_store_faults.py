"""A token-store fault is not an invalid token.

The token lookups read strictly and raise ``TokenStoreUnavailable``; the MCP
endpoint answers 503 with ``Retry-After`` and the refresh grant answers
``server_error``, so neither a consumer's guard nor a client reads a fault as
"this token is dead".
"""

import json
from typing import Any
from unittest import mock

import pytest

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.oauth2_server import TokenStoreUnavailable
from actingweb.oauth2_server.token_manager import ActingWebTokenManager
from tests.mcp_helpers import make_mcp_config, make_mcp_handler, make_mcp_webobj
from tests.mcp_oauth_server_helpers import make_server, register
from tests.mcp_token_double import make_config

INDEX = "_access_token_index"


def test_validate_raises_on_store_fault() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    store.faulty_buckets.add(INDEX)
    with pytest.raises(TokenStoreUnavailable):
        tm.validate_access_token("aw_whatever")


def test_absent_token_is_still_none() -> None:
    config, _ = make_config()
    assert ActingWebTokenManager(config).validate_access_token("aw_nope") is None


def test_refresh_grant_answers_server_error_not_invalid_grant() -> None:
    config, store = make_config()
    server = make_server(config)
    resp = register(server, token_endpoint_auth_method="none")
    tm = server.token_manager
    code = tm.create_authorization_code("a1", resp["client_id"], {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, resp["client_id"])
    assert tokens

    store.faulty_buckets.add("_refresh_token_index")
    out = server.handle_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": resp["client_id"],
        }
    )
    assert out["error"] == "server_error"


class _FaultyServer:
    def validate_mcp_token(self, token: str) -> Any:
        raise TokenStoreUnavailable("down")


class _EmptyServer:
    def validate_mcp_token(self, token: str) -> Any:
        return None


def _handler(server: Any) -> Any:
    handler = make_mcp_handler({"Authorization": "Bearer aw_token"})
    patcher = mock.patch(
        "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
        return_value=server,
    )
    return handler, patcher


def test_mcp_post_answers_503_on_store_fault() -> None:
    handler, patcher = _handler(_FaultyServer())
    with patcher:
        out = handler.post({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert handler.response.status_code == 503
    assert handler.response.headers["Retry-After"] == "5"
    assert out["id"] == 7
    assert out["error"]["code"] == -32603


def test_mcp_get_answers_503_on_store_fault() -> None:
    handler, patcher = _handler(_FaultyServer())
    with patcher:
        handler.get()
    assert handler.response.status_code == 503


def test_mcp_post_invalid_token_is_still_401() -> None:
    handler, patcher = _handler(_EmptyServer())
    with patcher:
        handler.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert handler.response.status_code == 401


def test_body_is_json_serialisable() -> None:
    handler, patcher = _handler(_FaultyServer())
    with patcher:
        out = handler.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    json.dumps(out)


def _async_handler(server: Any) -> Any:
    handler = AsyncMCPHandler(
        make_mcp_webobj({"Authorization": "Bearer aw_token"}), make_mcp_config()
    )
    patcher = mock.patch(
        "actingweb.oauth2_server.oauth2_server.get_actingweb_oauth2_server",
        return_value=server,
    )
    return handler, patcher


async def test_async_mcp_post_answers_503_on_store_fault() -> None:
    """The FastAPI integration serves POST /mcp through AsyncMCPHandler."""
    handler, patcher = _async_handler(_FaultyServer())
    with patcher:
        out = await handler.post_async(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}
        )
    assert handler.response.status_code == 503
    assert handler.response.headers["Retry-After"] == "5"
    assert out["id"] == 9
    assert out["error"]["code"] == -32603
    # The fault's text (actor id, bucket name) never reaches the client.
    assert out["error"]["message"] == "Token store temporarily unavailable; retry"


async def test_async_mcp_get_answers_503_on_store_fault() -> None:
    handler, patcher = _async_handler(_FaultyServer())
    with patcher:
        await handler.get_async()
    assert handler.response.status_code == 503


async def test_async_mcp_post_invalid_token_is_still_401() -> None:
    handler, patcher = _async_handler(_EmptyServer())
    with patcher:
        await handler.post_async({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert handler.response.status_code == 401


@pytest.mark.parametrize("bucket", ["client_index", "mcp_clients"])
def test_client_lookup_fault_is_server_error_not_invalid_client(bucket: str) -> None:
    """A store fault while authenticating the client must not tell the client
    its registration is bad (401 ``invalid_client``)."""
    from actingweb.constants import CLIENT_INDEX_BUCKET

    config, store = make_config()
    server = make_server(config)
    resp = register(server, token_endpoint_auth_method="none")
    tm = server.token_manager
    code = tm.create_authorization_code("a1", resp["client_id"], {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, resp["client_id"])
    assert tokens

    store.faulty_buckets.add(
        CLIENT_INDEX_BUCKET if bucket == "client_index" else bucket
    )
    out = server.handle_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": resp["client_id"],
        }
    )
    assert out["error"] == "server_error"

    # The refresh token was not consumed: it works once the store is back.
    store.faulty_buckets.clear()
    out = server.handle_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": resp["client_id"],
        }
    )
    assert "access_token" in out


def test_unknown_client_is_still_invalid_client() -> None:
    config, _ = make_config()
    server = make_server(config)
    out = server.handle_token_request(
        {"grant_type": "refresh_token", "refresh_token": "x", "client_id": "nope"}
    )
    assert out["error"] == "invalid_client"


def test_revoke_client_tokens_reports_an_unreadable_bucket() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    store.faulty_buckets.add("mcp_tokens")
    with pytest.raises(TokenStoreUnavailable):
        tm.revoke_client_tokens("a1", "mcp_client_x")


def test_delete_client_still_deletes_when_tokens_cannot_be_listed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deleting the client is what stops its refresh tokens (the grant cannot
    authenticate it any more), so a token-listing fault must not keep the
    client alive; it is logged at ERROR instead."""
    import logging

    config, store = make_config()
    server = make_server(config)
    resp = register(server)
    cid = resp["client_id"]
    tm = server.token_manager
    code = tm.create_authorization_code("actor-owner", cid, {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, cid)
    assert tokens

    store.raising_buckets.add("mcp_refresh_tokens")
    with (
        caplog.at_level(logging.ERROR, logger="actingweb.oauth2_server"),
        mock.patch.object(server.client_registry, "_delete_client_trust_relationship"),
    ):
        assert server.client_registry.delete_client(cid, actor_id="actor-owner")
    assert "could not list" in caplog.text
    store.raising_buckets.clear()
    assert server.client_registry.load_client_strict(cid) is None
    out = server.handle_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": cid,
            "client_secret": resp["client_secret"],
        }
    )
    assert out["error"] == "invalid_client"


def test_delete_client_fails_when_nothing_is_confirmed_deleted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A delete that cannot be confirmed (DynamoDB swallows a failed delete
    and answers True) must not be reported as success while the client can
    still authenticate."""
    import logging

    from actingweb.constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR

    config, store = make_config()
    server = make_server(config)
    cid = register(server)["client_id"]
    owner = store.data(OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET, cid)
    store.delete_faults |= {
        (owner, "mcp_clients", cid),
        (OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET, cid),
    }

    with (
        caplog.at_level(logging.ERROR, logger="actingweb.oauth2_server"),
        mock.patch.object(server.client_registry, "_delete_client_trust_relationship"),
    ):
        assert not server.client_registry.delete_client(cid, actor_id=owner)
    assert "can still authenticate" in caplog.text
    assert server.client_registry.load_client_strict(cid) is not None


def test_delete_client_succeeds_when_its_index_row_is_gone() -> None:
    """Either row gone disables the client, so one confirmed delete is a
    successful client deletion."""
    from actingweb.constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR

    config, store = make_config()
    server = make_server(config)
    cid = register(server)["client_id"]
    owner = store.data(OAUTH2_SYSTEM_ACTOR, CLIENT_INDEX_BUCKET, cid)
    store.delete_faults.add((owner, "mcp_clients", cid))

    with mock.patch.object(server.client_registry, "_delete_client_trust_relationship"):
        assert server.client_registry.delete_client(cid, actor_id=owner)
    assert server.client_registry.load_client_strict(cid) is None


def test_revoke_client_tokens_counts_only_confirmed_deletes() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    code = tm.create_authorization_code("a1", "mcp_client_x", {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, "mcp_client_x")
    assert tokens
    store.delete_faults.add(("a1", "mcp_tokens", tokens["access_token"]))

    with pytest.raises(TokenStoreUnavailable, match="could not confirm 1 delete"):
        tm.revoke_client_tokens("a1", "mcp_client_x")
    assert tokens["access_token"] in store.names("a1", "mcp_tokens")
    assert tokens["refresh_token"] not in store.names("a1", "mcp_refresh_tokens")


def test_revoke_client_tokens_counts_a_raising_delete_and_goes_on() -> None:
    """One token whose revocation raises is counted as unconfirmed; the
    client's other tokens are still revoked and the fault is reported."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    code = tm.create_authorization_code("a1", "mcp_client_x", {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, "mcp_client_x")
    assert tokens

    real = tm._remove_access_token

    def raising(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("index row delete failed")

    tm._remove_access_token = raising  # type: ignore[method-assign]
    try:
        with pytest.raises(TokenStoreUnavailable, match="could not confirm 1 delete"):
            tm.revoke_client_tokens("a1", "mcp_client_x")
    finally:
        tm._remove_access_token = real  # type: ignore[method-assign]
    assert tokens["refresh_token"] not in store.names("a1", "mcp_refresh_tokens")
