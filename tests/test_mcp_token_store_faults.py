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


def test_revoke_client_tokens_evicts_the_access_tokens_from_the_cache() -> None:
    """A deleted client's access token must not keep authenticating from
    this process's MCP token cache."""
    from actingweb.handlers import mcp as mcp_mod

    config, _store = make_config()
    tm = ActingWebTokenManager(config)
    code = tm.create_authorization_code("a1", "mcp_client_x", {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, "mcp_client_x")
    assert tokens
    mcp_mod._token_cache[tokens["access_token"]] = {"actor_id": "a1"}
    try:
        assert tm.revoke_client_tokens("a1", "mcp_client_x") == 2
        assert tokens["access_token"] not in mcp_mod._token_cache
    finally:
        mcp_mod._token_cache.pop(tokens["access_token"], None)


# ---------------------------------------------------------------------------
# Chain revocation core, eviction, expired-token removal and the sweep
# ---------------------------------------------------------------------------

from actingweb.constants import (  # noqa: E402
    ACCESS_TOKEN_INDEX_BUCKET,
    AUTH_CODE_INDEX_BUCKET,
    INDEX_TTL_BUFFER,
    MCP_ACCESS_TOKEN_TTL,
    OAUTH2_SYSTEM_ACTOR,
    REFRESH_TOKEN_INDEX_BUCKET,
    TTL_CLOCK_SKEW_BUFFER,
)
from tests.mcp_token_double import MemoryStore, index_actor  # noqa: E402

ACTOR = "a1"
CLIENT = "mcp_client_x"


def _mcp_login(tm: ActingWebTokenManager) -> dict[str, Any]:
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, CLIENT)
    assert tokens
    return tokens


def test_revoke_chain_with_a_zero_delete_and_a_faulting_anchor_read_raises() -> None:
    """The MCP counterpart of the SPA hook test: a zero delete, then an anchor
    read that faults, is a fault and not "already revoked"."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    chain = store.data(ACTOR, "mcp_refresh_tokens", tokens["refresh_token"])["chain_id"]
    store.chain_delete_fault = "zero"
    store.chain_delete_hook = lambda: store.faulty_buckets.add("mcp_refresh_tokens")
    with pytest.raises(TokenStoreUnavailable):
        tm._revoke_chain(
            ACTOR, chain, anchor=("mcp_refresh_tokens", tokens["refresh_token"])
        )


def test_revoke_chain_without_an_anchor_treats_zero_as_a_fault() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    store.chain_delete_fault = "zero"
    with pytest.raises(TokenStoreUnavailable):
        tm._revoke_chain(ACTOR, "no-such-chain")


def test_revoke_client_tokens_evicts_a_token_whose_delete_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from actingweb.handlers import mcp as mcp_mod

    config, _store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    mcp_mod._token_cache[tokens["access_token"]] = {"actor_id": ACTOR}

    def raising(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("index row delete failed")

    monkeypatch.setattr(tm, "_remove_access_token", raising)
    try:
        with pytest.raises(TokenStoreUnavailable):
            tm.revoke_client_tokens(ACTOR, CLIENT)
        assert tokens["access_token"] not in mcp_mod._token_cache
    finally:
        mcp_mod._token_cache.pop(tokens["access_token"], None)


def test_revoke_client_tokens_bumps_the_actor_generation_once_per_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _store = make_config()
    tm = ActingWebTokenManager(config)
    _mcp_login(tm)
    _mcp_login(tm)
    evicted: list[str] = []
    monkeypatch.setattr(
        "actingweb.mcp.invalidation.evict_caches_for_actor",
        lambda actor_id: evicted.append(actor_id) or 0,
    )
    assert tm.revoke_client_tokens(ACTOR, CLIENT) == 4
    assert evicted == [ACTOR]


def test_an_expired_access_token_loses_its_index_row_first() -> None:
    """With the owner known the index row goes first and the actor row's
    delete is confirmed, so a failing delete leaves a token that no longer
    validates anywhere."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]
    store.bucket(ACTOR, "mcp_tokens")[token]["data"]["expires_at"] = 1
    store.delete_faults.add((ACTOR, "mcp_tokens", token))

    assert tm.validate_access_token(token) is None
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None
    assert token in store.names(ACTOR, "mcp_tokens")


def test_remove_access_token_without_the_owner_deletes_the_index_row_first() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]
    store.delete_faults.add((ACTOR, "mcp_tokens", token))

    assert tm._remove_access_token(token) is False
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None
    # The leftover actor row is cleanup for the TTL; the token is unusable.
    assert token in store.names(ACTOR, "mcp_tokens")
    assert tm.validate_access_token(token) is None


def test_remove_access_token_without_the_owner_removes_every_row() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]

    assert tm._remove_access_token(token) is True
    assert token not in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None
    assert tm._remove_access_token("aw_unknown") is True


def _age_past_access_ttl(store: MemoryStore) -> None:
    store.enforce_ttl = True
    store.advance(MCP_ACCESS_TOKEN_TTL + TTL_CLOCK_SKEW_BUFFER + 1)


def test_sweep_removes_the_rows_of_a_ttl_past_access_token() -> None:
    """A strict read cannot tell "absent" from "past its TTL but not yet
    reaped"; the sweep removes the actor row as well as the index row."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]
    _age_past_access_ttl(store)

    cleaned = tm.cleanup_expired_tokens()

    assert token not in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None
    assert cleaned["index_entries"] >= 1
    assert cleaned["skipped"] == 0
    # The refresh token is live and untouched.
    assert tokens["refresh_token"] in store.names(ACTOR, "mcp_refresh_tokens")
    assert (
        index_actor(store, REFRESH_TOKEN_INDEX_BUCKET, tokens["refresh_token"]) == ACTOR
    )


def test_sweep_leaves_a_live_row_and_its_index_alone() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    store.enforce_ttl = True

    cleaned = tm.cleanup_expired_tokens()

    assert tokens["access_token"] in store.names(ACTOR, "mcp_tokens")
    assert (
        index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, tokens["access_token"]) == ACTOR
    )
    assert cleaned["access_tokens"] == 0
    assert cleaned["skipped"] == 0


def test_sweep_removes_an_access_token_past_its_expires_at() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]
    store.bucket(ACTOR, "mcp_tokens")[token]["data"]["expires_at"] = 1

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["access_tokens"] == 1
    assert token not in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None


def test_sweep_keeps_the_index_row_when_the_actor_row_delete_is_unconfirmed() -> None:
    """A delete the store did not perform is skipped, never counted as removed,
    and the index row stays so the next run retries it."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    token = _mcp_login(tm)["access_token"]
    store.bucket(ACTOR, "mcp_tokens")[token]["data"]["expires_at"] = 1
    store.delete_faults.add((ACTOR, "mcp_tokens", token))

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["access_tokens"] == 0
    assert cleaned["skipped"] >= 1
    assert token in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) == ACTOR

    store.delete_faults.clear()
    retried = tm.cleanup_expired_tokens()

    assert retried["access_tokens"] == 1
    assert token not in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) is None


def test_sweep_leaves_a_row_with_a_non_mapping_payload_alone() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    token = _mcp_login(tm)["access_token"]
    store.bucket(ACTOR, "mcp_tokens")[token]["data"] = "not a mapping"

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["skipped"] == 1
    assert token in store.names(ACTOR, "mcp_tokens")
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, token) == ACTOR


def test_sweep_skips_a_row_it_cannot_read_and_finishes() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    store.bucket(ACTOR, "mcp_refresh_tokens")[tokens["refresh_token"]]["data"][
        "expires_at"
    ] = 1
    store.faulty_buckets.add("mcp_tokens")

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["skipped"] == 1
    # The unreadable access row and its index row are untouched...
    assert tokens["access_token"] in store.names(ACTOR, "mcp_tokens")
    assert (
        index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, tokens["access_token"]) == ACTOR
    )
    # ...and the sweep went on to the next index.
    assert cleaned["refresh_tokens"] == 1


def test_sweep_reports_an_unreadable_index_as_skipped_not_empty() -> None:
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    store.faulty_buckets.add(ACCESS_TOKEN_INDEX_BUCKET)

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["skipped"] == 1
    assert tokens["access_token"] in store.names(ACTOR, "mcp_tokens")


def test_a_live_auth_code_survives_a_sweep_with_a_fault_on_its_bucket() -> None:
    """The regression the strict reader closes: a transient fault reading a
    live code's row must not read as "no such code" and delete its index."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    code = tm.create_authorization_code(ACTOR, CLIENT, {"access_token": "g"})
    store.faulty_buckets.add("mcp_auth_codes")

    cleaned = tm.cleanup_expired_tokens()

    store.faulty_buckets.clear()
    assert cleaned["skipped"] >= 1
    assert index_actor(store, AUTH_CODE_INDEX_BUCKET, code) == ACTOR
    assert code in store.names(ACTOR, "mcp_auth_codes")


def test_sweep_index_rows_outlive_their_actor_rows_by_design() -> None:
    """The safety invariant the sweep relies on: an index row's TTL exceeds
    its actor row's, so a strict read that returns nothing never hides a
    live row."""
    config, store = make_config()
    tm = ActingWebTokenManager(config)
    tokens = _mcp_login(tm)
    token = tokens["access_token"]
    assert (
        store.deadlines[(OAUTH2_SYSTEM_ACTOR, ACCESS_TOKEN_INDEX_BUCKET, token)]
        - store.deadlines[(ACTOR, "mcp_tokens", token)]
        >= INDEX_TTL_BUFFER - 1
    )
