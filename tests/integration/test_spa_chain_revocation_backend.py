"""SPA session-token chain revocation on the real backends.

The unit tests run on an in-memory double; these run ``revoke_session`` and
the anchored ``delete_by_chain`` over the SPA buckets under the shared
``OAUTH2_SYSTEM_ACTOR`` partition on DynamoDB and PostgreSQL. Every test uses
its own chain ids and cleans up by row name, never by bucket: the partition is
shared with every other SPA test.
"""

import os
import uuid

import pytest

from actingweb import config as config_module
from actingweb.constants import OAUTH2_SYSTEM_ACTOR
from actingweb.db import get_attribute
from actingweb.oauth_session import (
    _ACCESS_TOKEN_BUCKET,
    _REFRESH_TOKEN_BUCKET,
    OAuth2SessionManager,
)

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def mgr() -> OAuth2SessionManager:
    return OAuth2SessionManager(config_module.Config(database=DATABASE_BACKEND))


def _login(mgr: OAuth2SessionManager, actor_id: str) -> tuple[str, str, str]:
    chain = mgr.new_chain_id()
    access = f"acc-{uuid.uuid4().hex}"
    mgr.store_access_token(access, actor_id, "u@example.com", chain_id=chain)
    refresh = mgr.create_refresh_token(actor_id, "u@example.com", chain_id=chain)
    return access, refresh, chain


def _row(mgr: OAuth2SessionManager, bucket: str, name: str) -> object:
    return get_attribute(mgr.config).get_attr(
        actor_id=OAUTH2_SYSTEM_ACTOR, bucket=bucket, name=name
    )


def _cleanup(mgr: OAuth2SessionManager, *pairs: tuple[str, str]) -> None:
    db = get_attribute(mgr.config)
    for bucket, name in pairs:
        db.delete_attr(actor_id=OAUTH2_SYSTEM_ACTOR, bucket=bucket, name=name)


@pytest.mark.xdist_group(name="spa_chain_revocation_backend")
class TestSpaChainRevocationOnBackend:
    def test_an_anchored_chain_delete_removes_only_that_chain(
        self, mgr: OAuth2SessionManager
    ) -> None:
        actor_id = f"spa-chain-{uuid.uuid4().hex[:12]}"
        access, refresh, chain = _login(mgr, actor_id)
        other_access, other_refresh, _ = _login(mgr, actor_id)
        try:
            revoked = mgr.revoke_token_chain(
                actor_id, chain, anchor=(_REFRESH_TOKEN_BUCKET, refresh)
            )

            assert revoked == 2
            assert _row(mgr, _ACCESS_TOKEN_BUCKET, access) is None
            assert _row(mgr, _REFRESH_TOKEN_BUCKET, refresh) is None
            assert _row(mgr, _ACCESS_TOKEN_BUCKET, other_access) is not None
            assert _row(mgr, _REFRESH_TOKEN_BUCKET, other_refresh) is not None
        finally:
            _cleanup(
                mgr,
                (_ACCESS_TOKEN_BUCKET, access),
                (_REFRESH_TOKEN_BUCKET, refresh),
                (_ACCESS_TOKEN_BUCKET, other_access),
                (_REFRESH_TOKEN_BUCKET, other_refresh),
            )

    def test_a_second_revoke_of_the_same_chain_is_done_not_a_fault(
        self, mgr: OAuth2SessionManager
    ) -> None:
        actor_id = f"spa-chain-{uuid.uuid4().hex[:12]}"
        access, refresh, chain = _login(mgr, actor_id)
        try:
            assert mgr.revoke_session(access) is not None
            # Everything is gone: unknown token, no fault.
            assert mgr.revoke_session(access) is None
            assert mgr.revoke_session(refresh, token_type_hint="refresh_token") is None
            assert (
                mgr.revoke_token_chain(
                    actor_id, chain, anchor=(_REFRESH_TOKEN_BUCKET, refresh)
                )
                == 0
            )
        finally:
            _cleanup(
                mgr,
                (_ACCESS_TOKEN_BUCKET, access),
                (_REFRESH_TOKEN_BUCKET, refresh),
            )

    def test_revoke_session_with_the_refresh_token_ends_the_access_token_too(
        self, mgr: OAuth2SessionManager
    ) -> None:
        actor_id = f"spa-chain-{uuid.uuid4().hex[:12]}"
        access, refresh, _chain = _login(mgr, actor_id)
        try:
            row = mgr.revoke_session(refresh, token_type_hint="refresh_token")

            assert row is not None and row["actor_id"] == actor_id
            assert mgr.validate_access_token(access) is None
            assert mgr.validate_refresh_token(refresh) is None
        finally:
            _cleanup(
                mgr,
                (_ACCESS_TOKEN_BUCKET, access),
                (_REFRESH_TOKEN_BUCKET, refresh),
            )

    def test_a_chainless_token_revokes_only_itself(
        self, mgr: OAuth2SessionManager
    ) -> None:
        actor_id = f"spa-chain-{uuid.uuid4().hex[:12]}"
        access, refresh, _chain = _login(mgr, actor_id)
        legacy = f"legacy-{uuid.uuid4().hex}"
        mgr.store_access_token(legacy, actor_id, "u@example.com")
        try:
            assert mgr.revoke_session(legacy) is not None

            assert _row(mgr, _ACCESS_TOKEN_BUCKET, legacy) is None
            assert _row(mgr, _ACCESS_TOKEN_BUCKET, access) is not None
            assert _row(mgr, _REFRESH_TOKEN_BUCKET, refresh) is not None
        finally:
            _cleanup(
                mgr,
                (_ACCESS_TOKEN_BUCKET, legacy),
                (_ACCESS_TOKEN_BUCKET, access),
                (_REFRESH_TOKEN_BUCKET, refresh),
            )


@pytest.mark.xdist_group(name="spa_chain_revocation_backend")
class TestChainRevokedMarkerOnBackend:
    """The marker a revocation writes before its sweep (3.16)."""

    def test_the_marker_is_readable_with_a_ttl_and_reaped_after_it(
        self, mgr: OAuth2SessionManager
    ) -> None:
        import time

        from actingweb.constants import CHAIN_REVOKED_MARKER_TTL, TTL_CLOCK_SKEW_BUFFER
        from actingweb.oauth_session import _CHAIN_REVOKED_BUCKET
        from actingweb.single_use import chain_revoked

        actor_id = f"spa-marker-{uuid.uuid4().hex[:12]}"
        access, refresh, chain = _login(mgr, actor_id)
        try:
            assert not chain_revoked(
                mgr.config, OAUTH2_SYSTEM_ACTOR, _CHAIN_REVOKED_BUCKET, chain
            )
            mgr.revoke_token_chain(
                actor_id, chain, anchor=(_REFRESH_TOKEN_BUCKET, refresh)
            )
            assert chain_revoked(
                mgr.config, OAUTH2_SYSTEM_ACTOR, _CHAIN_REVOKED_BUCKET, chain
            )
            deadline = int(time.time()) + CHAIN_REVOKED_MARKER_TTL
            if DATABASE_BACKEND == "dynamodb":
                from actingweb.db.dynamodb.attribute import Attribute

                row = Attribute.get(
                    OAUTH2_SYSTEM_ACTOR,
                    f"{_CHAIN_REVOKED_BUCKET}:{chain}",
                    consistent_read=True,
                )
                assert row.ttl_timestamp is not None
                assert deadline - 5 <= row.ttl_timestamp - TTL_CLOCK_SKEW_BUFFER
                assert row.ttl_timestamp - TTL_CLOCK_SKEW_BUFFER <= deadline + 5
            else:
                db = get_attribute(mgr.config)
                now = int(time.time())
                # Other tests' expired markers may go; this one stays.
                db.delete_expired(now_epoch=now, buckets=[_CHAIN_REVOKED_BUCKET])
                assert _row(mgr, _CHAIN_REVOKED_BUCKET, chain) is not None
                db.delete_expired(
                    now_epoch=now
                    + CHAIN_REVOKED_MARKER_TTL
                    + TTL_CLOCK_SKEW_BUFFER
                    + 5,
                    buckets=[_CHAIN_REVOKED_BUCKET],
                )
                assert _row(mgr, _CHAIN_REVOKED_BUCKET, chain) is None
        finally:
            _cleanup(
                mgr,
                (_ACCESS_TOKEN_BUCKET, access),
                (_REFRESH_TOKEN_BUCKET, refresh),
                (_CHAIN_REVOKED_BUCKET, chain),
            )
