"""Adoption under a backend write or delete fault (3.16, second iteration).

Each backend hides one kind of fault: PostgreSQL's ``set_attr`` answers
``False``, which a plain ``store.x = y`` discards, and DynamoDB's
``delete_attr`` swallows the error and answers ``True``. These tests
reproduce each shape at the backend seam, so they hold on either backend: a
sign-in must not report an adoption that did not happen, and an actor must
not be created without its marker.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.actor import Actor
from actingweb.attribute import InternalStore
from actingweb.constants import OAUTH2_SYSTEM_ACTOR
from actingweb.db import get_actor, get_attribute
from actingweb.maintenance import mark_actors_vouched as script
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from actingweb.oauth_session import get_oauth2_session_manager
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    istore,
    make_config,
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
def backend_fault(
    config: Any,
    method: str,
    matches: Callable[[Any, Any, Any], bool],
    answer: Callable[[], Any],
) -> Iterator[None]:
    """Replace one attribute-backend method for the (actor, bucket, name)
    calls ``matches`` accepts; every other call is real."""
    unpatched = get_attribute(config)
    cls = type(unpatched)
    real = getattr(unpatched, method)  # bound before patching

    def fake(*args: Any, **kw: Any) -> Any:
        if args and isinstance(args[0], cls):
            args = args[1:]
        names = ("actor_id", "bucket", "name")
        values = dict(zip(names, args, strict=False))
        values.update({k: v for k, v in kw.items() if k in names})
        if matches(values.get("actor_id"), values.get("bucket"), values.get("name")):
            return answer()
        return real(*args, **kw)

    with patch.object(cls, method, fake):
        yield


def _raise() -> Any:
    raise RuntimeError("throttled")


def marker_write_fault(config: Any, actor_id: str | None = None) -> Any:
    """``set_attr`` of ``_internal/auth_method`` answers False and writes
    nothing (PostgreSQL's caught fault)."""
    return backend_fault(
        config,
        "set_attr",
        lambda a, b, n: (
            b == "_internal" and n == "auth_method" and actor_id in (None, a)
        ),
        lambda: False,
    )


class TestSwallowedTokenDelete:
    def test_unconfirmed_session_delete_fails_the_adoption(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        manager = get_oauth2_session_manager(config)
        manager.store_access_token(f"spa-{aid(legacy)}", aid(legacy), creator)

        def spa_bucket(a: Any, b: Any, _n: Any) -> bool:
            return a == OAUTH2_SYSTEM_ACTOR and b == "spa_access_tokens"

        # DynamoDB's shape: the plain delete swallows the fault and answers
        # True, and the conditional delete is throttled.
        with (
            backend_fault(config, "delete_attr", spa_bucket, lambda: True),
            backend_fault(config, "delete_attr_conditional", spa_bucket, _raise),
        ):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        row = Actor(actor_id=aid(legacy), config=config)
        assert not istore(row).auth_method


class TestMarkerWriteFault:
    def test_actor_is_not_created_without_its_marker(self) -> None:
        config = make_config()
        creator = uuid_email()
        actor = Actor(config=config)

        with marker_write_fault(config):
            created = actor.create(
                url="https://test.example.com/",
                creator=creator,
                passphrase="own-pass",
                auth_method="google_oauth2",
            )

        assert created is False
        assert not Actor(config=config).get_from_creator(creator)

    def test_clean_in_place_fails_when_the_vouched_marker_does_not_land(
        self, auth
    ) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)

        with marker_write_fault(config, aid(legacy)):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        assert not istore(Actor(actor_id=aid(legacy), config=config)).auth_method


class TestBackfillListFault:
    def test_unreadable_actor_list_is_refused_not_a_zero_scan(self) -> None:
        config = make_config()
        failing = MagicMock()
        failing.return_value.fetch.return_value = False

        with patch("actingweb.db.get_actor_list", failing):
            with pytest.raises(script.ActorListUnavailable):
                script.mark_actors(config)
            assert script.main(["--dry-run"]) == 2

    @pytest.mark.parametrize("marker", ["factory", "creator_changed", ""])
    def test_unvouched_marker_is_refused(self, marker: str) -> None:
        with pytest.raises(ValueError):
            script.mark_actors(make_config(), marker=marker)


class TestThirdIterationFaults:
    """Writes that decide a vouch, confirmed (third iteration)."""

    def test_create_over_a_live_actor_whose_read_faults_leaves_it_intact(
        self,
    ) -> None:
        # DynamoDB's get() answers None on a throttle; the MCP bridge then
        # calls create() with the live actor's own id.
        config = make_config()
        owner = uuid_email()
        live = create_core_actor(config, owner, auth_method="google_oauth2")
        db_cls = type(get_actor(config))

        with (
            patch.object(db_cls, "get", lambda self, actor_id=None: None),
            marker_write_fault(config, aid(live)),
        ):
            # create() still answers True when the id is taken (older than
            # 3.16; see thoughts/todo/adoption-fault-and-hygiene-followups.md).
            Actor(config=config).create(
                url="https://test.example.com/",
                creator="oauth2-user@unknown.domain",
                passphrase="",
                actor_id=aid(live),
                auth_method="oauth2_bearer",
            )

        row = Actor(actor_id=aid(live), config=config)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"

    def test_clean_fails_when_the_pending_flag_is_not_cleared(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        istore(legacy).email_verified = "false"

        # DynamoDB's shape: the delete swallows the fault and answers True.
        with backend_fault(
            config,
            "delete_attr",
            lambda a, b, n: (
                a == aid(legacy) and b == "_internal" and n == "email_verified"
            ),
            lambda: True,
        ):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        assert istore(Actor(actor_id=aid(legacy), config=config)).email_verified == (
            "false"
        )

    def test_set_confirmed_reports_a_failed_write_of_the_same_value(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        store = istore(Actor(actor_id=aid(actor), config=config))

        with marker_write_fault(config, aid(actor)):
            assert store.set_confirmed("auth_method", "google_oauth2") is False

    def test_set_confirmed_does_not_raise_on_a_load_fault(self) -> None:
        config = make_config()
        actor = create_core_actor(config, uuid_email())
        store = InternalStore(actor_id=aid(actor), config=config)  # not loaded

        with backend_fault(
            config, "get_bucket", lambda a, b, _n: a == aid(actor), _raise
        ):
            assert store.set_confirmed("auth_method", "operator") is False


class TestBackfillResume:
    def test_dynamodb_scan_fault_is_an_unreadable_list(self) -> None:
        failing = MagicMock()
        failing.return_value.fetch.side_effect = RuntimeError("scan throttled")

        with patch("actingweb.db.get_actor_list", failing):
            with pytest.raises(script.ActorListUnavailable):
                script.mark_actors(make_config())
            assert script.main(["--dry-run"]) == 2

    def test_errors_say_rerun_without_start_after(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = make_config()
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)

        with (
            marker_write_fault(config, aid(legacy)),
            caplog.at_level("INFO", logger="mark_actors_vouched"),
        ):
            counts = script.mark_actors(config, creator=creator)

        assert counts["errors"] == 1
        assert "re-run without --start-after" in caplog.text
        assert f"resume with --start-after {aid(legacy)}" not in caplog.text
