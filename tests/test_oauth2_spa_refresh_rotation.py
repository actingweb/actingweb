"""Tests for refresh-token rotation grace/theft handling on /oauth/spa/token.

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
from unittest.mock import MagicMock

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.constants import (
    OAUTH2_SYSTEM_ACTOR,
    SPA_REFRESH_TOKEN_REUSE_WINDOW,
)
from actingweb.handlers.oauth2_spa import (
    GRACE_PERIOD_EXTENDED,
    OAuth2SPAHandler,
)
from actingweb.oauth_session import (
    _REFRESH_TOKEN_BUCKET,
    get_oauth2_session_manager,
)


def _make_config() -> tuple[Config, dict]:
    config = MagicMock(spec=Config)
    config.new_token = MagicMock(side_effect=lambda: f"aw-access-{time.time_ns()}")

    storage: dict = {}

    class MockDbAttribute:
        def __init__(self):  # type: ignore
            self.storage = storage

        def get_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {})

        def get_attr(self, actor_id, bucket, name):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {}).get(name)

        def set_attr(
            self, actor_id, bucket, name, data, timestamp=None, ttl_seconds=None
        ):  # type: ignore
            self.storage.setdefault(f"{actor_id}:{bucket}", {})[name] = {"data": data}
            return True

        def delete_attr(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            if key in self.storage and name in self.storage[key]:
                del self.storage[key][name]
                return True
            return False

        def conditional_update_attr(
            self, actor_id, bucket, name, old_data, new_data, timestamp=None
        ):  # type: ignore
            key = f"{actor_id}:{bucket}"
            current = self.storage.get(key, {}).get(name)
            if current is None or current.get("data") != old_data:
                return False
            self.storage[key][name] = {"data": new_data}
            return True

        def delete_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.pop(f"{actor_id}:{bucket}", None) is not None

        def delete_by_chain(self, actor_id=None, buckets=None, chain_id=None):  # type: ignore
            if not actor_id or not chain_id or not buckets:
                return 0
            deleted = 0
            for bucket in buckets:
                items = self.storage.get(f"{actor_id}:{bucket}", {})
                for name, rec in list(items.items()):
                    data = rec.get("data") or {}
                    if isinstance(data, dict) and data.get("chain_id") == chain_id:
                        del items[name]
                        deleted += 1
            return deleted

    db_mod = MagicMock()
    db_mod.DbAttribute = MockDbAttribute
    config.DbAttribute = db_mod
    return config, storage


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
        config, storage, actor_id, used_seconds_ago=GRACE_PERIOD_EXTENDED - 5
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
        config, storage, actor_id, used_seconds_ago=GRACE_PERIOD_EXTENDED + 30
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
            "used_at": int(time.time()) - (GRACE_PERIOD_EXTENDED + 30),
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
