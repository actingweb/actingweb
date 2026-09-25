"""MCP refresh-token rotation, reuse detection and chain revocation.

``ActingWebTokenManager.refresh_access_token`` ports the SPA design
(``oauth_session.try_mark_refresh_token_used``): a refresh token is consumed
atomically, a consumed token presented again inside the grace period rotates
in the same chain, inside the reuse window it revokes the chain, and beyond
the window it reads as expired.
"""

import logging
import time
from typing import Any

import pytest

import actingweb.oauth2_server.token_manager as tm_mod
from actingweb.constants import (
    ACCESS_TOKEN_INDEX_BUCKET,
    MCP_REFRESH_TOKEN_GRACE_PERIOD,
    MCP_REFRESH_TOKEN_REUSE_WINDOW,
    MCP_TOKEN_PURGE_INTERVAL,
    OAUTH2_SYSTEM_ACTOR,
    REFRESH_TOKEN_INDEX_BUCKET,
)
from actingweb.handlers import mcp as mcp_mod
from actingweb.oauth2_server.token_manager import ActingWebTokenManager
from tests.mcp_token_double import MemoryStore, index_actor, make_config

ACTOR = "actor-rot"
CLIENT = "mcp_client_rot"
TOKENS = "mcp_tokens"
REFRESH = "mcp_refresh_tokens"
PROVIDER = "mcp_google_tokens"


@pytest.fixture
def env() -> tuple[ActingWebTokenManager, MemoryStore]:
    config, store = make_config()
    mcp_mod._token_cache.clear()
    mcp_mod._trust_cache.clear()
    return ActingWebTokenManager(config), store


def _login(tm: ActingWebTokenManager, actor: str = ACTOR) -> dict[str, Any]:
    code = tm.create_authorization_code(actor, CLIENT, {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, CLIENT)
    assert tokens
    return tokens


def _set_used(store: MemoryStore, refresh_token: str, seconds_ago: int) -> None:
    data = store.bucket(ACTOR, REFRESH)[refresh_token]["data"]
    data["used"] = True
    data["used_at"] = int(time.time()) - seconds_ago


def _chain(store: MemoryStore, bucket: str, name: str) -> Any:
    return store.data(ACTOR, bucket, name)["chain_id"]


def test_rotation_issues_new_refresh_token_and_revokes_old_access_token(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    old_access, old_refresh = first["access_token"], first["refresh_token"]
    mcp_mod._token_cache[old_access] = {"actor_id": ACTOR}
    mcp_mod._trust_cache[(ACTOR, CLIENT)] = {"cached_at": time.time()}

    second = tm.refresh_access_token(old_refresh, CLIENT)

    assert second is not None
    assert second["refresh_token"] != old_refresh
    assert store.data(ACTOR, REFRESH, old_refresh)["used"] is True
    # Old access token gone from the actor bucket, the index and the cache.
    assert old_access not in store.names(ACTOR, TOKENS)
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, old_access) is None
    assert old_access not in mcp_mod._token_cache
    # Rotation pops the token only; the actor's trust cache survives.
    assert (ACTOR, CLIENT) in mcp_mod._trust_cache
    # Same chain.
    chain = _chain(store, REFRESH, old_refresh)
    assert _chain(store, REFRESH, second["refresh_token"]) == chain
    assert _chain(store, TOKENS, second["access_token"]) == chain
    # Consumed row and its index row re-stamped to the reuse window.
    assert store.ttls[(ACTOR, REFRESH, old_refresh)] == MCP_REFRESH_TOKEN_REUSE_WINDOW
    index_ttl = store.ttls[
        (OAUTH2_SYSTEM_ACTOR, REFRESH_TOKEN_INDEX_BUCKET, old_refresh)
    ]
    assert index_ttl is not None
    assert index_ttl < 86400 * 30


def test_first_refresh_deletes_provider_row_of_code_minted_token(
    env: tuple[ActingWebTokenManager, MemoryStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    tm, store = env
    first = _login(tm)
    provider_key = store.data(ACTOR, TOKENS, first["access_token"])["google_token_key"]
    assert provider_key in store.names(ACTOR, PROVIDER)

    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    assert provider_key not in store.names(ACTOR, PROVIDER)
    assert store.names(ACTOR, PROVIDER) == set()

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="actingweb.oauth2_server"):
        third = tm.refresh_access_token(second["refresh_token"], CLIENT)
    assert third
    # The no-op revoke helper used to log a WARNING on every refresh.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_mint_fault_after_consume_recovers_in_grace_and_is_theft_after(
    env: tuple[ActingWebTokenManager, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    tm, store = env
    first = _login(tm)
    refresh = first["refresh_token"]
    chain = _chain(store, REFRESH, refresh)

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("storage fault")

    with monkeypatch.context() as m:
        m.setattr(tm, "_store_access_token", boom)
        with pytest.raises(RuntimeError):
            tm.refresh_access_token(refresh, CLIENT)
    assert store.data(ACTOR, REFRESH, refresh)["used"] is True

    # Retry 30 s later: inside the grace period, rotates in the same chain.
    _set_used(store, refresh, 30)
    retry = tm.refresh_access_token(refresh, CLIENT)
    assert retry is not None
    assert _chain(store, REFRESH, retry["refresh_token"]) == chain

    # Retry 90 s after the consume: theft, the chain is revoked.
    _set_used(store, refresh, 90)
    assert tm.refresh_access_token(refresh, CLIENT) is None
    assert retry["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert retry["access_token"] not in store.names(ACTOR, TOKENS)


def test_reuse_inside_grace_rotates_without_revoking(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 10)

    again = tm.refresh_access_token(first["refresh_token"], CLIENT)

    assert again is not None
    assert again["refresh_token"] not in (
        first["refresh_token"],
        second["refresh_token"],
    )
    chain = _chain(store, REFRESH, first["refresh_token"])
    assert _chain(store, REFRESH, again["refresh_token"]) == chain
    # Nothing revoked: the branch from the first rotation still works.
    assert second["refresh_token"] in store.names(ACTOR, REFRESH)
    assert second["access_token"] in store.names(ACTOR, TOKENS)


def test_reuse_inside_window_revokes_the_whole_chain_only(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    other = _login(tm)  # a second connector on the same actor
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    mcp_mod._token_cache[second["access_token"]] = {"actor_id": ACTOR}
    mcp_mod._trust_cache[(ACTOR, CLIENT)] = {"cached_at": time.time()}
    _set_used(store, first["refresh_token"], 5 * 60)

    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None

    for name in (first["refresh_token"], second["refresh_token"]):
        assert name not in store.names(ACTOR, REFRESH)
        assert index_actor(store, REFRESH_TOKEN_INDEX_BUCKET, name) is None
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert index_actor(store, ACCESS_TOKEN_INDEX_BUCKET, second["access_token"]) is None
    # A different chain on the same actor survives.
    assert other["refresh_token"] in store.names(ACTOR, REFRESH)
    assert other["access_token"] in store.names(ACTOR, TOKENS)
    # Actor-wide cache eviction.
    assert second["access_token"] not in mcp_mod._token_cache
    assert (ACTOR, CLIENT) not in mcp_mod._trust_cache


def test_reuse_past_window_is_expired_not_theft(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 3 * 86400)

    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None

    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert second["refresh_token"] in store.names(ACTOR, REFRESH)
    assert second["access_token"] in store.names(ACTOR, TOKENS)


def test_legacy_record_rotates_into_a_fresh_chain(
    env: tuple[ActingWebTokenManager, MemoryStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    tm, store = env
    legacy = "rt_legacy_token_value_0123456789"
    now = int(time.time())
    record = {
        "token": legacy,
        "actor_id": ACTOR,
        "client_id": CLIENT,
        "access_token_id": "deadbeef",
        "created_at": now,
        "expires_at": now + 3600,
    }
    tm._store_refresh_token(ACTOR, legacy, record)

    with caplog.at_level(logging.DEBUG, logger="actingweb.oauth2_server"):
        result = tm.refresh_access_token(legacy, CLIENT)

    assert result is not None
    assert _chain(store, REFRESH, result["refresh_token"])
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_cas_loser_rotates_in_the_same_chain(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    refresh = first["refresh_token"]
    chain = _chain(store, REFRESH, refresh)

    def lose(actor_id: str, bucket: str, name: str) -> bool:
        # Another request consumes the token just before this CAS.
        if bucket == REFRESH and name == refresh:
            row = store.bucket(actor_id, bucket)[name]["data"]
            row["used"] = True
            row["used_at"] = int(time.time())
            return False
        return True

    store.cas_hook = lose
    result = tm.refresh_access_token(refresh, CLIENT)
    store.cas_hook = None

    assert result is not None
    assert _chain(store, REFRESH, result["refresh_token"]) == chain


def test_old_access_token_delete_fault_still_issues_tokens(
    env: tuple[ActingWebTokenManager, MemoryStore],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tm, _store = env
    first = _login(tm)

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("delete fault")

    monkeypatch.setattr(tm, "_remove_access_token", boom)
    with caplog.at_level(logging.WARNING, logger="actingweb.oauth2_server"):
        result = tm.refresh_access_token(first["refresh_token"], CLIENT)

    assert result is not None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_revoke_refresh_token_removes_its_access_token(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    assert tm.revoke_token(first["refresh_token"])
    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert first["access_token"] not in store.names(ACTOR, TOKENS)
    assert store.names(ACTOR, PROVIDER) == set()


def test_revoke_access_token_removes_its_chains_refresh_tokens(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    other = _login(tm)
    first = _login(tm)
    assert tm.revoke_token(first["access_token"])
    assert first["access_token"] not in store.names(ACTOR, TOKENS)
    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert other["refresh_token"] in store.names(ACTOR, REFRESH)


def test_cleanup_removes_used_refresh_tokens_past_the_window(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    old = _login(tm)
    recent = _login(tm)
    _set_used(store, old["refresh_token"], MCP_REFRESH_TOKEN_REUSE_WINDOW + 60)
    _set_used(store, recent["refresh_token"], MCP_REFRESH_TOKEN_GRACE_PERIOD)

    cleaned = tm.cleanup_expired_tokens()

    assert cleaned["refresh_tokens"] == 1
    assert old["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert recent["refresh_token"] in store.names(ACTOR, REFRESH)
    assert [PROVIDER] in store.purges


def test_maybe_purge_runs_once_per_interval(
    env: tuple[ActingWebTokenManager, MemoryStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    tm, store = env
    monkeypatch.setattr(tm_mod._mcp_purge_throttle, "last_attempt", None)

    tm.maybe_purge_expired_tokens()
    tm.maybe_purge_expired_tokens()

    assert len(store.purges) == 1
    purged = store.purges[0]
    assert purged is not None
    assert len(purged) == 7
    assert {TOKENS, REFRESH, PROVIDER, "mcp_auth_codes"} <= set(purged)

    monkeypatch.setattr(
        tm_mod._mcp_purge_throttle,
        "last_attempt",
        time.monotonic() - MCP_TOKEN_PURGE_INTERVAL - 1,
    )
    tm.maybe_purge_expired_tokens()
    assert len(store.purges) == 2


def test_theft_revocation_with_unreadable_bucket(
    env: tuple[ActingWebTokenManager, MemoryStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 5 * 60)
    store.faulty_buckets.add(TOKENS)

    with caplog.at_level(logging.WARNING, logger="actingweb.oauth2_server"):
        assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None

    assert "Could not read bucket mcp_tokens" in caplog.text
    # delete_by_chain still removed the chain's actor rows.
    store.faulty_buckets.clear()
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)


def test_legacy_record_replayed_after_grace_revokes_its_new_chain(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """A pre-3.15 token's first rotation stamps the new chain on the consumed
    row, so a replay of it is caught as theft like any other."""
    tm, store = env
    legacy = "rt_legacy_token_value_9876543210"
    now = int(time.time())
    tm._store_refresh_token(
        ACTOR,
        legacy,
        {
            "token": legacy,
            "actor_id": ACTOR,
            "client_id": CLIENT,
            "access_token_id": "deadbeef",
            "created_at": now,
            "expires_at": now + 3600,
        },
    )
    rotated = tm.refresh_access_token(legacy, CLIENT)
    assert rotated is not None
    new_chain = _chain(store, REFRESH, rotated["refresh_token"])
    assert _chain(store, REFRESH, legacy) == new_chain

    _set_used(store, legacy, 5 * 60)
    assert tm.refresh_access_token(legacy, CLIENT) is None
    assert rotated["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert rotated["access_token"] not in store.names(ACTOR, TOKENS)


def test_revoke_refresh_token_revokes_its_whole_chain(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """Revoking the current refresh token also kills the consumed one, so a
    replay inside the grace window cannot mint a pair after the revocation."""
    tm, store = env
    other = _login(tm)
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second

    assert tm.revoke_token(second["refresh_token"])
    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert (
        index_actor(store, REFRESH_TOKEN_INDEX_BUCKET, first["refresh_token"]) is None
    )
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    # Inside the grace window the consumed token would otherwise re-rotate.
    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None
    assert other["refresh_token"] in store.names(ACTOR, REFRESH)
    assert other["access_token"] in store.names(ACTOR, TOKENS)


def test_revoke_access_token_revokes_its_whole_chain(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    third = tm.refresh_access_token(first["refresh_token"], CLIENT)  # grace sibling
    assert third

    assert tm.revoke_token(second["access_token"])
    for name in (
        first["refresh_token"],
        second["refresh_token"],
        third["refresh_token"],
    ):
        assert name not in store.names(ACTOR, REFRESH)
    assert third["access_token"] not in store.names(ACTOR, TOKENS)


def test_theft_revocation_when_bucket_read_raises(
    env: tuple[ActingWebTokenManager, MemoryStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DynamoDB raises mid-page on a throttle; the chain is still deleted."""
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 5 * 60)
    store.raising_buckets.add(TOKENS)

    with caplog.at_level(logging.WARNING, logger="actingweb.oauth2_server"):
        assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None

    assert "Could not read bucket mcp_tokens" in caplog.text
    store.raising_buckets.clear()
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)


@pytest.mark.parametrize("fault", ["zero", "raise"])
def test_theft_revocation_that_deletes_nothing_is_a_fault(
    env: tuple[ActingWebTokenManager, MemoryStore], fault: str
) -> None:
    """A chain delete that faults (PostgreSQL returns 0, DynamoDB raises) is
    not reported as a revocation: the grant errors, the chain is intact, and
    the next presentation tries the revocation again."""
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 5 * 60)

    store.chain_delete_fault = fault
    with pytest.raises(tm_mod.TokenStoreUnavailable):
        tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert first["refresh_token"] in store.names(ACTOR, REFRESH)

    store.chain_delete_fault = None
    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None
    assert second["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert second["access_token"] not in store.names(ACTOR, TOKENS)


def test_cas_fault_is_a_store_fault_not_a_dead_token(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """Both backends answer False from the swap on a fault. That must not
    read as "already used": the token stays, unused, and works once the
    store recovers."""
    tm, store = env
    first = _login(tm)

    store.cas_fault = True
    with pytest.raises(tm_mod.TokenStoreUnavailable):
        tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert first["refresh_token"] in store.names(ACTOR, REFRESH)
    assert not store.data(ACTOR, REFRESH, first["refresh_token"]).get("used")

    store.cas_fault = False
    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is not None


def test_cas_fault_with_unreadable_store_is_a_store_fault(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)

    store.cas_fault = True
    # The loser's strict re-read faults too; the index lookup before the
    # swap already succeeded, so only the actor's refresh bucket is faulty
    # from here on.
    original = tm._consume

    def consume_then_fault(*args: Any, **kwargs: Any) -> Any:
        store.faulty_buckets.add(REFRESH)
        return original(*args, **kwargs)

    tm._consume = consume_then_fault  # type: ignore[method-assign]
    with pytest.raises(tm_mod.TokenStoreUnavailable):
        tm.refresh_access_token(first["refresh_token"], CLIENT)
    store.faulty_buckets.clear()
    assert first["refresh_token"] in store.names(ACTOR, REFRESH)


def test_revocation_between_swap_and_mint_is_not_undone(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """The consumed row's TTL is written by the swap itself. A revocation
    that lands right after the swap stays in force: nothing re-creates the
    consumed row, so no replay inside the grace window can rotate it."""
    tm, store = env
    first = _login(tm)
    config_db = tm.config.DbAttribute.DbAttribute
    original = config_db.conditional_update_attr

    def swap_then_revoke(
        self: Any, actor_id: str, bucket: str, name: str, *a: Any, **k: Any
    ) -> bool:
        ok = original(self, actor_id, bucket, name, *a, **k)
        if ok and bucket == REFRESH:
            store.rows[f"{actor_id}:{bucket}"].pop(name, None)
        return ok

    config_db.conditional_update_attr = swap_then_revoke
    try:
        tm.refresh_access_token(first["refresh_token"], CLIENT)
    finally:
        config_db.conditional_update_attr = original

    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)
    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None


def test_consumed_row_ttl_is_set_by_the_swap(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    tm, store = env
    first = _login(tm)
    assert tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert (
        store.ttls[(ACTOR, REFRESH, first["refresh_token"])]
        == MCP_REFRESH_TOKEN_REUSE_WINDOW
    )


def test_revocation_fault_still_removes_the_presented_token_and_evicts(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """When the chain cannot be revoked, the token that was presented still
    goes, this process forgets it, and the fault is reported."""
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    mcp_mod._token_cache[second["access_token"]] = {"actor_id": ACTOR}

    store.chain_delete_fault = "zero"
    with pytest.raises(tm_mod.TokenStoreUnavailable):
        tm.revoke_token(second["access_token"])
    assert second["access_token"] not in store.names(ACTOR, TOKENS)
    assert second["access_token"] not in mcp_mod._token_cache


def test_a_chain_revoked_concurrently_is_not_a_fault(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """Two revocations of one chain race: the loser deletes nothing, and its
    anchor row is gone too, so the chain is revoked, not faulted."""
    tm, store = env
    first = _login(tm)
    chain = _chain(store, REFRESH, first["refresh_token"])
    assert tm._revoke_chain(ACTOR, chain, anchor=(REFRESH, first["refresh_token"]))

    assert tm._revoke_chain(ACTOR, chain, anchor=(REFRESH, first["refresh_token"])) == 0


def test_partial_chain_delete_leaves_the_replayed_token_to_retry_from(
    env: tuple[ActingWebTokenManager, MemoryStore],
) -> None:
    """DynamoDB deletes a chain row by row. A fault part-way must not take
    the replayed token with it, or nothing is left to retry the revocation
    and the thief's branch lives on."""
    tm, store = env
    first = _login(tm)
    second = tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert second
    _set_used(store, first["refresh_token"], 5 * 60)

    store.chain_delete_fault = "partial"
    with pytest.raises(tm_mod.TokenStoreUnavailable):
        tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert first["refresh_token"] in store.names(ACTOR, REFRESH)

    store.chain_delete_fault = None
    assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None
    assert first["refresh_token"] not in store.names(ACTOR, REFRESH)


def test_unconfirmed_delete_of_the_old_access_token_is_logged(
    env: tuple[ActingWebTokenManager, MemoryStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    tm, store = env
    first = _login(tm)
    store.delete_faults.add((ACTOR, TOKENS, first["access_token"]))

    with caplog.at_level(logging.ERROR, logger="actingweb.oauth2_server"):
        assert tm.refresh_access_token(first["refresh_token"], CLIENT)
    assert "Could not confirm removal of access token" in caplog.text
