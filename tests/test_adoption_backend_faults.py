"""Adoption under a backend read fault (3.16 iteration).

PostgreSQL catches a read error and answers with an empty result: ``None``
for a bucket, ``[]`` for a trust or subscription list. DynamoDB raises. These
tests reproduce the PostgreSQL shape at the backend seam, so they hold on
either backend: the adoption must fail the sign-in closed, never read the
fault as "nothing there".
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from actingweb import trust as trust_module
from actingweb.actor import Actor
from actingweb.constants import OAUTH2_SYSTEM_ACTOR
from actingweb.db import get_attribute, get_subscription_list, get_trust_list
from actingweb.maintenance import mark_actors_vouched as script
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from actingweb.oauth_session import get_oauth2_session_manager
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
    plant_squat_state,
    uuid_email,
)


@pytest.fixture
def auth() -> OAuth2Authenticator:
    provider = OAuth2Provider(
        "google",
        {
            "client_id": "cid",
            "client_secret": "csec",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )
    return OAuth2Authenticator(make_config(), provider)


@contextmanager
def bucket_read_fault(config: Any, actor_id: str, bucket: str) -> Iterator[None]:
    """``get_bucket`` answers ``None`` (PostgreSQL's caught fault) for one
    bucket of one actor; every other read is real."""
    unpatched = get_attribute(config)
    cls = type(unpatched)
    real = unpatched.get_bucket  # bound before patching; static on DynamoDB

    def fake(*args: Any, **kw: Any) -> Any:
        if args and isinstance(args[0], cls):
            args = args[1:]
        a = kw.get("actor_id", args[0] if args else None)
        b = kw.get("bucket", args[1] if len(args) > 1 else None)
        if a == actor_id and b == bucket:
            return None
        return real(actor_id=a, bucket=b)

    with patch.object(cls, "get_bucket", fake):
        yield


@contextmanager
def list_read_fault(factory: Any, config: Any, actor_id: str) -> Iterator[None]:
    """A list ``fetch`` behaves as PostgreSQL does on a caught error: ``[]``,
    or a raise when the caller asked for ``strict``."""
    cls = type(factory(config))
    real = cls.fetch

    def fake(self: Any, actor_id_: Any = None, **kw: Any) -> Any:
        a = kw.pop("actor_id", actor_id_)
        if a == actor_id:
            if kw.get("strict"):
                raise RuntimeError("simulated backend read fault")
            return []
        return real(self, actor_id=a, **kw)

    with patch.object(cls, "fetch", fake):
        yield


class TestVouchingReadFault:
    def test_unreadable_marker_fails_closed_and_wipes_nothing(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        vouched = create_core_actor(
            config, creator, auth_method="google_oauth2", passphrase="own-pass"
        )
        plant_squat_state(config, vouched, peer="peer-own")

        with bucket_read_fault(config, aid(vouched), "_internal"):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        row = Actor(actor_id=aid(vouched), config=config)
        assert row.passphrase == "own-pass"
        assert trust_module.Trust(
            actor_id=aid(vouched), peerid="peer-own", config=config
        ).get()
        assert istore(row).auth_method == "google_oauth2"


class TestWipeConfirmationReadFault:
    @pytest.mark.parametrize("which", ["trusts", "subscriptions"])
    def test_unreadable_list_leaves_actor_unvouched(self, auth, which) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        plant_squat_state(config, legacy)
        factory = get_trust_list if which == "trusts" else get_subscription_list

        with list_read_fault(factory, config, aid(legacy)):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        row = Actor(actor_id=aid(legacy), config=config)
        assert not istore(row).auth_method, "a fault must not mark it vouched"


class TestSpaRevokeReadFault:
    def test_unreadable_session_bucket_fails_the_adoption(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        manager = get_oauth2_session_manager(config)
        token = f"spa-{aid(legacy)}"
        manager.store_access_token(token, aid(legacy), creator)

        with bucket_read_fault(config, OAUTH2_SYSTEM_ACTOR, "spa_access_tokens"):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        row = Actor(actor_id=aid(legacy), config=config)
        assert not istore(row).auth_method


class TestBackfillReadFault:
    def test_unreadable_marker_is_an_error_not_a_mark(self) -> None:
        config = make_config()
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")

        with bucket_read_fault(config, aid(squat), "_internal"):
            counts = script.mark_actors(config, creator=creator)

        assert counts["marked"] == 0 and counts["errors"] == 1
        assert istore(Actor(actor_id=aid(squat), config=config)).auth_method == (
            "factory"
        )
