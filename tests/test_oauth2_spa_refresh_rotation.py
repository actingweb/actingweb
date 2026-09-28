"""Tests for refresh-token rotation grace/theft handling on /oauth/spa/token.

The handler runs on ``tests.mcp_token_double``, a real Config over an
in-memory store with fault hooks, shared with the MCP rotation tests.

Covers ``OAuth2SPAHandler._handle_refresh_token``:

- Reuse of an already-used refresh token *within* the grace window issues a
  FULL rotation (new access + new refresh token in the same chain) so a client
  that dropped its previous rotation can recover. Earlier revisions returned an
  access-token-only response here, which stranded such clients into a
  guaranteed theft lockout one access-token lifetime later.
- Reuse *beyond* the grace window is treated as theft and revokes only the
  offending refresh-token family (chain), not every token for the actor.
"""

import json
import time
from typing import Any

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.constants import (
    OAUTH2_SYSTEM_ACTOR,
    SPA_REFRESH_TOKEN_REUSE_WINDOW,
)
from actingweb.handlers.oauth2_spa import OAuth2SPAHandler
from actingweb.oauth_session import (
    _REFRESH_TOKEN_BUCKET,
    get_oauth2_session_manager,
)
from tests.mcp_token_double import MemoryStore, make_config

_STORES: dict[int, MemoryStore] = {}


def _make_config() -> tuple[Config, dict[str, dict[str, Any]]]:
    """A real Config on the shared in-memory store; returns its rows."""
    config, store = make_config()
    _STORES[id(config)] = store
    return config, store.rows


def storage_store(config: Config) -> MemoryStore:
    """The MemoryStore behind a config from :func:`_make_config`, for its
    fault hooks."""
    return _STORES[id(config)]


def _handler(config) -> OAuth2SPAHandler:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/spa/token",
        params={},
        body=json.dumps({}),
        headers={"Accept": "application/json"},
        cookies={},
    )
    return OAuth2SPAHandler(webobj, config, hooks=None)


def _seed_used_token(config, storage, actor_id, used_seconds_ago):
    """Create a refresh token and force it into the 'already used' state with a
    controllable used_at, returning (token, chain_id)."""
    mgr = get_oauth2_session_manager(config)
    token = mgr.create_refresh_token(actor_id, "user@example.com")
    key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
    data = storage[key][token]["data"]
    chain_id = data["chain_id"]
    data["used"] = True
    data["used_at"] = int(time.time()) - used_seconds_ago
    return token, chain_id


def test_reuse_within_grace_window_issues_full_rotation():
    """A reuse inside the grace window must return a NEW refresh token (rotation
    in the same chain), not an access-token-only response."""
    config, storage = _make_config()
    actor_id = "grace-actor"
    token, chain_id = _seed_used_token(
        config,
        storage,
        actor_id,
        used_seconds_ago=config.refresh_token_grace_period - 5,
    )

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    assert result.get("success") is True
    assert result.get("error") is not True
    new_refresh = result.get("refresh_token")
    assert new_refresh, "grace-window reuse must rotate (return a new refresh token)"
    assert new_refresh != token

    # The rotated token stays in the same family.
    mgr = get_oauth2_session_manager(config)
    new_data = mgr.validate_refresh_token(new_refresh)
    assert new_data is not None
    assert new_data["chain_id"] == chain_id

    # The access token minted on rotation is tagged with the chain, so a later
    # theft response on this family revokes it too.
    from actingweb.oauth_session import _ACCESS_TOKEN_BUCKET

    access_key = f"{OAUTH2_SYSTEM_ACTOR}:{_ACCESS_TOKEN_BUCKET}"
    access_rows = storage.get(access_key, {})
    assert any(
        (row.get("data") or {}).get("chain_id") == chain_id
        for row in access_rows.values()
    ), "rotation must mint a chain-tagged access token"


def test_reuse_beyond_grace_window_revokes_only_the_chain():
    """A reuse past the grace window is theft: revoke the offending chain and
    401, while a sibling chain (another device) survives."""
    config, storage = _make_config()
    actor_id = "theft-actor"

    # Sibling chain for the same actor — must survive.
    mgr = get_oauth2_session_manager(config)
    sibling = mgr.create_refresh_token(actor_id, "user@example.com")
    sibling_chain = mgr.validate_refresh_token(sibling)["chain_id"]  # type: ignore[index]

    token, chain_id = _seed_used_token(
        config,
        storage,
        actor_id,
        used_seconds_ago=config.refresh_token_grace_period + 30,
    )

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    assert result.get("error") is True
    assert result.get("status_code") == 401
    assert handler.response is not None and handler.response.status_code == 401

    # Offending chain gone, sibling chain intact.
    key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
    refresh_store = storage.get(key, {})
    assert not any(
        (v.get("data") or {}).get("chain_id") == chain_id
        for v in refresh_store.values()
    )
    assert mgr.validate_refresh_token(sibling) is not None
    assert any(
        (v.get("data") or {}).get("chain_id") == sibling_chain
        for v in refresh_store.values()
    )


def test_reuse_past_reuse_window_is_expired_not_theft():
    """A reuse beyond SPA_REFRESH_TOKEN_REUSE_WINDOW (the row only lingers because
    the purge lagged) is rejected as expired and must NOT revoke the chain — a
    long-backgrounded client replaying a stale token can't invalidate the family
    that has long since rotated past it."""
    config, storage = _make_config()
    actor_id = "stale-actor"

    token, chain_id = _seed_used_token(
        config, storage, actor_id, used_seconds_ago=SPA_REFRESH_TOKEN_REUSE_WINDOW + 100
    )
    # A live token in the same chain (the family rotated forward) must survive.
    mgr = get_oauth2_session_manager(config)
    live = mgr.create_refresh_token(actor_id, "user@example.com", chain_id=chain_id)

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    assert result.get("error") is True
    assert result.get("status_code") == 401
    assert "expired" in result.get("message", "").lower()
    # The chain was NOT revoked: the live token still validates.
    assert mgr.validate_refresh_token(live) is not None


def test_legacy_chainless_reuse_revokes_only_the_presented_token():
    """A pre-existing refresh token with no chain_id (minted before chains
    existed), reused within the theft window, falls back to revoking just that
    token — not a chain scan — and still returns 401."""
    config, storage = _make_config()
    actor_id = "legacy-actor"
    key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"

    # Seed a used, chain-less token directly (create_refresh_token always assigns
    # a chain_id, so we craft the legacy shape by hand).
    token = "legacy-refresh-token"
    other = "legacy-other-token"
    storage.setdefault(key, {})[token] = {
        "data": {
            "actor_id": actor_id,
            "identifier": "user@example.com",
            "created_at": int(time.time()) - 1000,
            "expires_at": int(time.time()) + 100000,
            "used": True,
            "used_at": int(time.time()) - (config.refresh_token_grace_period + 30),
            # no chain_id
        }
    }
    # An unrelated token that must survive (proves we didn't revoke broadly).
    storage[key][other] = {
        "data": {"actor_id": actor_id, "identifier": "user@example.com"}
    }

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    assert result.get("error") is True
    assert result.get("status_code") == 401
    # Only the presented legacy token was revoked.
    assert token not in storage.get(key, {})
    assert other in storage.get(key, {})


def test_a_used_token_past_its_expiry_is_expired_not_theft():
    """A consumed token presented after its own ``expires_at`` reads as
    expired (401, row removed) and never reaches the reuse ladder, so its
    chain is not revoked. The MCP store checks in the same order."""
    config, storage = _make_config()
    actor_id = "expired-actor"
    token, chain_id = _seed_used_token(
        config,
        storage,
        actor_id,
        used_seconds_ago=config.refresh_token_grace_period + 30,
    )
    key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
    storage[key][token]["data"]["expires_at"] = int(time.time()) - 1
    mgr = get_oauth2_session_manager(config)
    live = mgr.create_refresh_token(actor_id, "user@example.com", chain_id=chain_id)

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    assert result.get("status_code") == 401
    assert "expired" in result.get("message", "").lower()
    assert token not in storage[key]
    assert mgr.validate_refresh_token(live) is not None


@pytest.mark.parametrize(
    ("grace", "used_seconds_ago", "rotates"),
    [
        (20, 15, True),
        (20, 40, False),
        (0, 5, False),
        (0, 0, False),
        (None, 5, True),
        (None, 30, True),
        (None, 90, False),
    ],
    ids=[
        "grace20-15s",
        "grace20-40s",
        "grace0-5s",
        "grace0-same-second",
        "default-5s",
        "default-30s",
        "default-90s",
    ],
)
def test_the_configured_grace_decides_rotation_or_theft(
    grace: int | None, used_seconds_ago: int, rotates: bool
) -> None:
    """The ladder reads ``config.refresh_token_grace_period``: inside it a
    reuse rotates in the same chain; past it the chain is revoked. ``None``
    leaves the default (60 s). Grace 0 means no grace, so a reuse in the
    same second is theft too."""
    config, storage = _make_config()
    if grace is not None:
        config.refresh_token_grace_period = grace
    actor_id = "grace-setting-actor"
    token, chain_id = _seed_used_token(
        config, storage, actor_id, used_seconds_ago=used_seconds_ago
    )
    mgr = get_oauth2_session_manager(config)
    live = mgr.create_refresh_token(actor_id, "user@example.com", chain_id=chain_id)

    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")

    if rotates:
        assert result.get("success") is True
        new_refresh = result.get("refresh_token")
        assert new_refresh and new_refresh != token
        new_data = mgr.validate_refresh_token(new_refresh)
        assert new_data is not None and new_data["chain_id"] == chain_id
        assert mgr.validate_refresh_token(live) is not None
    else:
        assert result.get("status_code") == 401
        assert "revoked" in result.get("message", "").lower()
        assert mgr.validate_refresh_token(live) is None


def _refresh(config, token: str) -> tuple[dict[str, Any], OAuth2SPAHandler]:
    handler = _handler(config)
    result = handler._handle_refresh_token({"refresh_token": token}, "json")
    return result, handler


def _assert_retryable_503(result: dict[str, Any], handler: OAuth2SPAHandler) -> None:
    assert result.get("status_code") == 503
    assert handler.response is not None
    assert handler.response.status_code == 503
    assert handler.response.headers.get("Retry-After") == "5"


def test_a_read_fault_answers_503_and_leaves_the_token_usable():
    """A store that cannot be read must not answer 401 "invalid or expired":
    a client following the guide treats that as final and signs out."""
    config, _ = _make_config()
    store = storage_store(config)
    mgr = get_oauth2_session_manager(config)
    token = mgr.create_refresh_token("fault-actor", "user@example.com")

    store.faulty_buckets.add(_REFRESH_TOKEN_BUCKET)
    result, handler = _refresh(config, token)
    _assert_retryable_503(result, handler)

    store.faulty_buckets.clear()
    result, _ = _refresh(config, token)
    assert result.get("success") is True


def test_a_consume_fault_answers_503_and_leaves_the_token_unused():
    config, storage = _make_config()
    store = storage_store(config)
    mgr = get_oauth2_session_manager(config)
    token = mgr.create_refresh_token("fault-actor", "user@example.com")

    store.cas_fault = True
    result, handler = _refresh(config, token)
    _assert_retryable_503(result, handler)
    key = f"{OAUTH2_SYSTEM_ACTOR}:{_REFRESH_TOKEN_BUCKET}"
    assert not storage[key][token]["data"].get("used")

    store.cas_fault = False
    result, _ = _refresh(config, token)
    assert result.get("success") is True


def test_a_mint_fault_after_the_consume_answers_503_and_a_prompt_retry_rotates():
    """The token is consumed but its successor could not be stored. The
    client gets a retryable 503, and its retry inside the grace period
    rotates in the same chain."""
    config, _ = _make_config()
    store = storage_store(config)
    mgr = get_oauth2_session_manager(config)
    token = mgr.create_refresh_token("fault-actor", "user@example.com")

    store.write_faults.add(_REFRESH_TOKEN_BUCKET)
    result, handler = _refresh(config, token)
    _assert_retryable_503(result, handler)

    store.write_faults.clear()
    result, _ = _refresh(config, token)
    assert result.get("success") is True
    assert result.get("refresh_token")


def test_create_refresh_token_raises_when_the_write_is_not_stored():
    """A token that was never stored must not be handed out: the client's
    next refresh would get a final 401."""
    from actingweb.oauth2_server.token_manager import TokenStoreUnavailable

    config, _ = _make_config()
    store = storage_store(config)
    store.write_faults.add(_REFRESH_TOKEN_BUCKET)
    with pytest.raises(TokenStoreUnavailable):
        get_oauth2_session_manager(config).create_refresh_token(
            "fault-actor", "user@example.com"
        )
