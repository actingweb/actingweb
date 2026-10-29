"""Adoption under a backend read fault (3.16 iteration).

Since 3.16 both backends raise ``DbError`` on a read fault. These tests
inject one at the backend seam: the adoption must fail the sign-in closed,
never read the fault as "nothing there".
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
from actingweb.db.exceptions import DbError
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
    """``get_bucket`` raises ``DbError`` (a backend fault, both backends
    since 3.16) for one bucket of one actor; every other read is real."""
    unpatched = get_attribute(config)
    cls = type(unpatched)
    real = unpatched.get_bucket  # bound before patching; static on DynamoDB

    def fake(*args: Any, **kw: Any) -> Any:
        if args and isinstance(args[0], cls):
            args = args[1:]
        a = kw.get("actor_id", args[0] if args else None)
        b = kw.get("bucket", args[1] if len(args) > 1 else None)
        if a == actor_id and b == bucket:
            raise DbError("simulated backend read fault")
        rest = {k: v for k, v in kw.items() if k not in ("actor_id", "bucket")}
        return real(actor_id=a, bucket=b, **rest)

    with patch.object(cls, "get_bucket", fake):
        yield


@contextmanager
def list_read_fault(factory: Any, config: Any, actor_id: str) -> Iterator[None]:
    """A list ``fetch`` faults: it raises ``DbError``, or answers ``[]``
    when the caller asked for ``strict=False``."""
    cls = type(factory(config))
    real = cls.fetch

    def fake(self: Any, actor_id_: Any = None, **kw: Any) -> Any:
        a = kw.pop("actor_id", actor_id_)
        if a == actor_id:
            if kw.get("strict", True):
                raise DbError("simulated backend read fault")
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

        # 3.16: the fault propagates (the integrations answer 503).
        with list_read_fault(factory, config, aid(legacy)), pytest.raises(DbError):
            auth.lookup_or_create_actor_by_identifier(creator)

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
