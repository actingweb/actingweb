"""MCP refresh-token rotation and single-use codes on the real backends.

The unit tests run the token manager on an in-memory double; these run the
same flows on DynamoDB and PostgreSQL, where the compare-and-swap compares
the stored JSON (including ``None`` fields), ``delete_by_chain`` runs as a
query, and TTLs are real.
"""

import os
import time
import uuid

import pytest

from actingweb import config as config_module
from actingweb.constants import OAUTH2_SYSTEM_ACTOR, REFRESH_TOKEN_INDEX_BUCKET
from actingweb.oauth2_server.token_manager import ActingWebTokenManager

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")
CLIENT = "mcp_backend_rotation"


@pytest.fixture
def tm() -> ActingWebTokenManager:
    return ActingWebTokenManager(config_module.Config(database=DATABASE_BACKEND))


def _login(tm: ActingWebTokenManager, actor_id: str) -> dict:
    code = tm.create_authorization_code(actor_id, CLIENT, {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, CLIENT)
    assert tokens is not None
    assert tm.exchange_authorization_code(code, CLIENT) is None  # single-use
    return tokens


def _age_consumed(tm: ActingWebTokenManager, actor_id: str, token: str, s: int) -> None:
    from actingweb import attribute

    bucket = attribute.Attributes(
        actor_id=actor_id, bucket=tm.refresh_tokens_bucket, config=tm.config
    )
    row = bucket.get_attr(name=token)
    assert row and row["data"]["used"] is True
    data = dict(row["data"])
    data["used_at"] = int(time.time()) - s
    bucket.set_attr(name=token, data=data, ttl_seconds=3600)


@pytest.mark.xdist_group(name="mcp_refresh_rotation_backend")
class TestRotationOnBackend:
    def test_rotate_grace_and_theft(self, tm: ActingWebTokenManager) -> None:
        actor_id = f"rot-{uuid.uuid4().hex[:12]}"
        other = _login(tm, actor_id)
        first = _login(tm, actor_id)

        second = tm.refresh_access_token(first["refresh_token"], CLIENT)
        assert second is not None
        assert second["refresh_token"] != first["refresh_token"]
        # The old access token is gone.
        assert tm.validate_access_token(first["access_token"]) is None
        assert tm.validate_access_token(second["access_token"]) is not None

        # Replayed right away: inside the grace period, rotates again.
        again = tm.refresh_access_token(first["refresh_token"], CLIENT)
        assert again is not None

        # Replayed five minutes after the consume: the chain is revoked.
        _age_consumed(tm, actor_id, first["refresh_token"], 300)
        assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None
        for token in (second, again):
            assert tm.refresh_access_token(token["refresh_token"], CLIENT) is None
            assert tm.validate_access_token(token["access_token"]) is None

        # Another chain on the same actor is untouched.
        assert tm.validate_access_token(other["access_token"]) is not None
        assert tm.refresh_access_token(other["refresh_token"], CLIENT) is not None

    def test_replay_past_window_is_expired(self, tm: ActingWebTokenManager) -> None:
        from actingweb import attribute

        actor_id = f"rot-{uuid.uuid4().hex[:12]}"
        first = _login(tm, actor_id)
        second = tm.refresh_access_token(first["refresh_token"], CLIENT)
        assert second is not None

        _age_consumed(tm, actor_id, first["refresh_token"], 3 * 86400)
        assert tm.refresh_access_token(first["refresh_token"], CLIENT) is None
        # Not revoked: the live branch still refreshes.
        assert tm.refresh_access_token(second["refresh_token"], CLIENT) is not None
        index = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=REFRESH_TOKEN_INDEX_BUCKET,
            config=tm.config,
        )
        assert index.get_attr(name=first["refresh_token"]) is None


@pytest.mark.xdist_group(name="mcp_refresh_rotation_backend")
class TestBackendKeywordsForSingleUse:
    """The two keywords 3.15 adds to the attribute protocol, on the real
    backends: the TTL written by the compare-and-swap itself, and the row a
    chain delete removes last."""

    def test_conditional_update_sets_the_ttl_and_never_creates_a_row(
        self, tm: ActingWebTokenManager
    ) -> None:
        from actingweb.constants import TTL_CLOCK_SKEW_BUFFER
        from actingweb.db import get_attribute

        db = get_attribute(tm.config)
        actor_id = f"cas-{uuid.uuid4().hex[:12]}"
        bucket = "cas_ttl_probe"
        db.set_attr(
            actor_id=actor_id,
            bucket=bucket,
            name="row",
            data={"v": 1},
            ttl_seconds=3600,
        )
        # A TTL already in the past makes the row read as absent on both
        # backends, which shows the swap wrote it.
        assert db.conditional_update_attr(
            actor_id=actor_id,
            bucket=bucket,
            name="row",
            old_data={"v": 1},
            new_data={"v": 2},
            ttl_seconds=-TTL_CLOCK_SKEW_BUFFER - 60,
        )
        assert db.get_attr_strict(actor_id=actor_id, bucket=bucket, name="row") is None

        assert not db.conditional_update_attr(
            actor_id=actor_id,
            bucket=bucket,
            name="missing",
            old_data={"v": 1},
            new_data={"v": 2},
            ttl_seconds=60,
        )
        assert db.get_attr(actor_id=actor_id, bucket=bucket, name="missing") is None
        db.delete_bucket(actor_id=actor_id, bucket=bucket)

    def test_chain_delete_with_a_deferred_row_deletes_the_whole_chain(
        self, tm: ActingWebTokenManager
    ) -> None:
        from actingweb.db import get_attribute

        db = get_attribute(tm.config)
        actor_id = f"chain-{uuid.uuid4().hex[:12]}"
        bucket = "chain_probe"
        for name in ("a", "b", "c"):
            db.set_attr(
                actor_id=actor_id,
                bucket=bucket,
                name=name,
                data={"chain_id": "ch-1"},
                ttl_seconds=3600,
            )
        db.set_attr(
            actor_id=actor_id,
            bucket=bucket,
            name="other",
            data={"chain_id": "ch-2"},
            ttl_seconds=3600,
        )

        deleted = db.delete_by_chain(
            actor_id=actor_id, buckets=[bucket], chain_id="ch-1", defer_name="b"
        )

        assert deleted == 3
        for name in ("a", "b", "c"):
            assert db.get_attr(actor_id=actor_id, bucket=bucket, name=name) is None
        assert db.get_attr(actor_id=actor_id, bucket=bucket, name="other") is not None
        db.delete_bucket(actor_id=actor_id, bucket=bucket)
