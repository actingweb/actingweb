"""Adoption after the fourth verification (3.16).

Sibling factory actors, the emailed link's confirmed flag, provider tokens and
the stored email on a clean, ``Actor.create`` on a taken id, and the creator
change's lost acknowledgement. Faults are injected at the backend class, so
every test runs on either backend.
"""

import logging
import time
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from actingweb.actor import Actor
from actingweb.attribute import Attributes
from actingweb.aw_web_request import AWWebObj
from actingweb.constants import ACTINGWEB_SYSTEM_ACTOR, EMAIL_VERIFY_TOKEN_INDEX_BUCKET
from actingweb.db import get_actor
from actingweb.db.exceptions import DbError
from actingweb.handlers.oauth_email import OAuth2EmailHandler
from actingweb.interface.actor_interface import ActorInterface
from actingweb.maintenance import mark_actors_vouched as script
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    istore,
    make_config,
    marker_write_fault,
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


def _ids(config: Any, creator: str) -> list[str]:
    rows: Any = get_actor(config).get_by_creator(creator=creator) or []
    if isinstance(rows, dict):
        rows = [rows]
    return sorted(str(r["id"]) for r in rows if r)


def _with_id(config: Any, creator: str, prefix: str, auth_method: str | None) -> Actor:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="pass",
        actor_id=f"{prefix}{uuid.uuid4().hex}",
        auth_method=auth_method or "app",
    )
    if auth_method is None:
        istore(actor).auth_method = None
    return actor


class TestFactorySiblings:
    """Issue Y: the owner chose "replace every factory sibling"."""

    def test_one_sign_in_replaces_every_factory_sibling(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squats = [_with_id(config, creator, p, "factory") for p in ("00", "01", "02")]

        first = auth.lookup_or_create_actor_by_identifier(creator)
        second = auth.lookup_or_create_actor_by_identifier(creator)

        assert first is not None and second is not None
        assert first.id == second.id
        assert first.id not in {s.id for s in squats}
        assert _ids(config, creator) == [first.id]

    def test_lookup_prefers_a_vouched_actor_over_a_lower_unvouched_one(
        self, auth
    ) -> None:
        config = auth.config
        creator = uuid_email()
        legacy = _with_id(config, creator, "00", None)
        vouched = _with_id(config, creator, "ff", "google_oauth2")

        signed_in = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == vouched.id
        # Not cleaned: the sign-in never resolved to it.
        assert not istore(Actor(actor_id=aid(legacy), config=config)).auth_method


class TestCleanInPlace:
    def test_clean_drops_the_previous_creators_provider_tokens(self, auth) -> None:
        # Issue AA: a provider sign-in that brings no refresh token must not
        # leave the previous creator's.
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        store = istore(legacy)
        store.oauth_token = "squatter-access"
        store.oauth_refresh_token = "squatter-refresh"

        assert auth.lookup_or_create_actor_by_identifier(creator) is not None

        row = istore(Actor(actor_id=aid(legacy), config=config))
        assert row.oauth_token is None
        assert row.oauth_refresh_token is None

    def test_clean_sets_the_stored_email_to_the_proven_address(self, auth) -> None:
        # Issue AH: with the pin off at sign-in, a later switch to
        # force_email_prop_as_creator must not hand the actor back to the
        # address the previous creator stored. (With the pin on, Actor.get
        # rewrites the creator at load, before adoption: filed as a todo.)
        config = auth.config
        config.force_email_prop_as_creator = False
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        istore(legacy).email = "squatter@example.com"

        assert auth.lookup_or_create_actor_by_identifier(creator) is not None

        assert istore(Actor(actor_id=aid(legacy), config=config)).email == creator


class TestEmailedLink:
    """Issue Z: the flag is confirmed before the token goes."""

    def test_unconfirmed_flag_answers_500_and_keeps_the_link(self) -> None:
        config = make_config()
        token = f"verify-token-{uuid.uuid4()}"
        actor = ActorInterface.create(creator=uuid_email(), config=config).core_actor
        store = istore(actor)
        store.email_verified = "false"
        store.email_verification_token = token
        store.email_verification_created_at = str(int(time.time()))
        index = Attributes(
            actor_id=ACTINGWEB_SYSTEM_ACTOR,
            bucket=EMAIL_VERIFY_TOKEN_INDEX_BUCKET,
            config=config,
        )
        index.set_attr(token, data=actor.id)
        webobj = AWWebObj(
            url=f"https://test.example.com/oauth/email?verify={token}",
            params={"verify": token},
            body="",
            headers={"Accept": "application/json"},
            cookies={},
        )
        try:
            with backend_fault(
                config,
                "set_attr",
                lambda a, b, n: a == actor.id and n == "email_verified",
                lambda: False,
            ):
                OAuth2EmailHandler(webobj, config, hooks=None).get()

            assert webobj.response.status_code == 500
            row = istore(Actor(actor_id=aid(actor), config=config))
            assert row.email_verified == "false"
            assert row.email_verification_token == token
            assert index.get_attr(token)
        finally:
            index.delete_attr(token)


class TestCreateOnATakenId:
    """Issues AB and AE."""

    def test_taken_id_returns_false_without_hook_or_write(self) -> None:
        config = make_config()
        live = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        calls: list[str] = []

        class _Hooks:
            def execute_lifecycle_hooks(self, name: str, *_a: Any, **_k: Any) -> bool:
                calls.append(name)
                return True

        created = Actor(config=config).create(
            url="https://test.example.com/",
            creator=uuid_email(),
            passphrase="other",
            actor_id=aid(live),
            trustee_root="https://attacker.example/",
            hooks=_Hooks(),
        )

        assert created is False
        assert "actor_created" not in calls
        assert istore(Actor(actor_id=aid(live), config=config)).trustee_root is None

    def test_interface_create_raises_on_a_taken_id(self) -> None:
        config = make_config()
        live = create_core_actor(config, uuid_email(), auth_method="google_oauth2")

        with pytest.raises(RuntimeError):
            ActorInterface.create(
                creator=uuid_email(), config=config, actor_id=aid(live)
            )

    def test_marker_rollback_removes_only_the_row(self) -> None:
        # Issue AD: a fixed id can own buckets older than its row.
        config = make_config()
        actor_id = f"fixed-{uuid.uuid4().hex}"
        older = Attributes(actor_id=actor_id, bucket="system_state", config=config)
        assert older.set_attr("keep", data={"v": 1})
        try:
            # 3.16: a marker-write fault rolls the row back and raises (503).
            with marker_write_fault(config, actor_id), pytest.raises(DbError):
                Actor(config=config).create(
                    url="https://test.example.com/",
                    creator="system",
                    passphrase="p",
                    actor_id=actor_id,
                    auth_method="system",
                )

            assert not Actor(actor_id=actor_id, config=config).id
            fresh = Attributes(actor_id=actor_id, bucket="system_state", config=config)
            assert (fresh.get_attr("keep") or {}).get("data") == {"v": 1}
        finally:
            older.delete_attr("keep")


class TestCreatorChangeAck:
    def _vouched(self, config: Any) -> tuple[Actor, str]:
        owner = uuid_email()
        actor = create_core_actor(config, owner, auth_method="google_oauth2")
        istore(actor).email = owner
        return actor, owner

    def test_lost_ack_leaves_creator_changed(self) -> None:
        # Issue AC: the write landed, its acknowledgement did not.
        config = make_config()
        config.force_email_prop_as_creator = False  # keep the reload literal
        actor, _owner = self._vouched(config)
        real_modify = Actor.modify

        def lands_then_raises(self: Actor, **kw: Any) -> bool:
            real_modify(self, **kw)
            raise RuntimeError("timeout after commit")

        new = uuid_email()
        with patch.object(Actor, "modify", lands_then_raises):
            assert actor.modify_creator_unvouched(new) is False

        row = Actor(actor_id=aid(actor), config=config)
        assert row.creator == new
        assert istore(row).auth_method == "creator_changed"

    def test_legacy_actor_restore_deletes_the_marker_again(self) -> None:
        # Issue AJ: previous_marker None takes set_confirmed's delete branch.
        config = make_config()
        legacy = create_core_actor(config, uuid_email(), auth_method=None)

        with patch.object(Actor, "modify", lambda self, **kw: False):
            assert legacy.modify_creator_unvouched(uuid_email()) is False

        assert not istore(Actor(actor_id=aid(legacy), config=config)).auth_method

    def test_interface_unvouch_keeps_factory(self) -> None:
        # Issue AF: the consumer path follows the endpoint's rules.
        config = make_config()
        squat = create_core_actor(config, uuid_email(), auth_method="factory")
        interface = ActorInterface(squat)

        assert interface.modify_creator(uuid_email(), unvouch=True)
        assert istore(Actor(actor_id=aid(squat), config=config)).auth_method == (
            "factory"
        )

    def test_interface_unvouch_marks_a_vouched_actor(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = False
        actor, _owner = self._vouched(config)

        assert ActorInterface(actor).modify_creator(uuid_email(), unvouch=True)
        assert istore(Actor(actor_id=aid(actor), config=config)).auth_method == (
            "creator_changed"
        )


class TestBackfillProgress:
    def test_progress_line_gives_the_resume_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Issue AI: an interrupted run never reaches the closing line.
        config = make_config()
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)

        with (
            patch.object(script, "PROGRESS_EVERY", 1),
            caplog.at_level(logging.INFO, logger="mark_actors_vouched"),
        ):
            script.mark_actors(config, creator=creator, dry_run=True)

        assert f"resume with --start-after {aid(legacy)}" in caplog.text
        assert "progress:" in caplog.text
