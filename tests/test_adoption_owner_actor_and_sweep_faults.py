"""Adoption after the fifth verification (3.16).

The owner's unvouched actor beside factory ones, the backfill's resume hint,
the sibling sweep under read faults, what a clean leaves in ``_internal``, a
vouched actor mid-deletion, the object a refused create returns, the MCP
bridge's create race and the creator pin on the consumer path. Faults are
injected at the backend class, so every test runs on either backend.
"""

import logging
import uuid
from typing import Any, cast
from unittest.mock import patch

import pytest

from actingweb import deletion
from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.attribute import InternalStore
from actingweb.db import get_actor
from actingweb.db.exceptions import DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.maintenance import mark_actors_vouched as script
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    istore,
    make_config,
    uuid_email,
)
from tests.mcp_helpers import make_mcp_config, make_mcp_handler


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


class TestOwnersActorBesideFactoryOnes:
    """Issue AN: the owner's actor from before 3.16 must not be left behind."""

    def test_sign_in_cleans_the_owners_actor_not_a_lower_factory_one(
        self, auth
    ) -> None:
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        owner = _with_id(config, creator, "ff", None)
        assert owner.property is not None
        owner.property["notes"] = "the owner's data"

        signed_in = auth.lookup_or_create_actor_by_identifier(creator)
        again = auth.lookup_or_create_actor_by_identifier(creator)

        assert signed_in is not None and signed_in.id == owner.id
        assert again is not None and again.id == owner.id
        kept = Actor(actor_id=aid(owner), config=config)
        assert kept.property is not None and kept.property["notes"] == (
            "the owner's data"
        )
        # The clean sweeps nothing; the second sign-in, to the now vouched
        # owner's actor, removes the factory actor beside it.
        assert _ids(config, creator) == [aid(owner)]
        assert not Actor(actor_id=aid(squat), config=config).id

    def test_replacing_a_factory_actor_cleans_the_owners_instead_of_creating(
        self, auth
    ) -> None:
        # The backstop: a sign-in that resolved to the factory actor directly.
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        owner = _with_id(config, creator, "ff", None)

        result = oauth2_module.adopt_actor(
            squat, provider=auth.provider, config=config, hooks=None
        )

        assert result is not None and result.id == owner.id
        assert istore(Actor(actor_id=aid(owner), config=config)).auth_method == (
            "google_oauth2"
        )
        assert _ids(config, creator) == [owner.id]


class TestBackfillResumeHint:
    """Issue AO: the hint names only an actor already handled."""

    def test_interrupted_actor_is_not_named_as_the_resume_point(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = make_config()
        creator = uuid_email()
        first = _with_id(config, creator, "00", None)
        second = _with_id(config, creator, "ff", None)
        real = InternalStore.set_confirmed

        def interrupt_on_second(self: Any, k: str, v: Any) -> bool:
            if self.__dict__["_db"].actor_id == second.id:
                raise KeyboardInterrupt
            return real(self, k, v)

        with (
            patch.object(script, "PROGRESS_EVERY", 1),
            patch.object(InternalStore, "set_confirmed", interrupt_on_second),
            caplog.at_level(logging.INFO, logger="mark_actors_vouched"),
            pytest.raises(KeyboardInterrupt),
        ):
            script.mark_actors(config, creator=creator)

        assert f"resume with --start-after {aid(first)}" in caplog.text
        assert f"resume with --start-after {aid(second)}" not in caplog.text
        assert not istore(Actor(actor_id=aid(second), config=config)).auth_method


class TestSweepReadFaults:
    """Issue AP: a read that did not answer fails the sign-in with every
    actor still in place."""

    def test_unlisted_creator_fails_closed_before_any_removal(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squat = create_core_actor(config, creator, auth_method="factory")
        cls = type(get_actor(config))

        def faulting(self: Any, creator: str | None = None, **kw: Any) -> Any:
            raise DbError("simulated listing fault")  # 3.16: a fault raises

        def empty(self: Any, creator: str | None = None, **kw: Any) -> Any:
            return []  # a listing that misses the actor being replaced

        with patch.object(cls, "get_by_creator", faulting), pytest.raises(DbError):
            oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )
        assert Actor(actor_id=aid(squat), config=config).id == squat.id

        with patch.object(cls, "get_by_creator", empty):
            result = oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )
        assert result is None
        assert Actor(actor_id=aid(squat), config=config).id == squat.id

    def test_unreadable_listed_row_fails_closed_before_any_removal(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        sibling = _with_id(config, creator, "ff", "factory")
        cls = type(get_actor(config))
        real_get = cls.get

        def get(self: Any, actor_id: str | None = None, **kw: Any) -> Any:
            if actor_id == sibling.id:
                raise DbError("simulated read fault")  # 3.16: a fault raises
            return real_get(self, actor_id=actor_id, **kw)

        with patch.object(cls, "get", get), pytest.raises(DbError):
            oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )

        assert Actor(actor_id=aid(squat), config=config).id == squat.id
        assert Actor(actor_id=aid(sibling), config=config).id == sibling.id

    def test_sibling_vouched_since_listing_is_kept(self, auth) -> None:
        # The backfill (--include-factory) marked it between list and delete.
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        sibling = _with_id(config, creator, "ff", "factory")
        real_list = oauth2_module._factory_siblings

        def list_then_vouch(*a: Any, **k: Any) -> Any:
            listed = real_list(*a, **k)
            assert istore(Actor(actor_id=aid(sibling), config=config)).set_confirmed(
                "auth_method", "operator"
            )
            return listed

        with patch.object(oauth2_module, "_factory_siblings", list_then_vouch):
            result = oauth2_module.adopt_actor(
                squat, provider=auth.provider, config=config, hooks=None
            )

        assert result is not None
        assert Actor(actor_id=aid(sibling), config=config).id == sibling.id

    def test_actor_adopted_names_the_swept_siblings(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        squat = _with_id(config, creator, "00", "factory")
        sibling = _with_id(config, creator, "ff", "factory")
        seen: dict[str, Any] = {}

        class _Hooks:
            def execute_lifecycle_hooks(self, name: str, *_a: Any, **kw: Any) -> bool:
                if name == "actor_adopted":
                    seen.update(kw)
                return True

        assert oauth2_module.adopt_actor(
            squat, provider=auth.provider, config=config, hooks=cast(Any, _Hooks())
        )

        assert seen["removed_sibling_ids"] == [sibling.id]


class TestCleanLeavesNothingOfThePreviousCreator:
    def test_clean_clears_trustee_root(self, auth) -> None:
        # Issue AS: the previous creator chose it.
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        istore(legacy).trustee_root = "https://attacker.example/"

        assert auth.lookup_or_create_actor_by_identifier(creator) is not None

        assert istore(Actor(actor_id=aid(legacy), config=config)).trustee_root is None

    def test_unconfirmed_token_reset_leaves_the_actor_unvouched(self, auth) -> None:
        # Issue AV: the resets are confirmed like the marker.
        config = auth.config
        creator = uuid_email()
        legacy = create_core_actor(config, creator, auth_method=None)
        istore(legacy).oauth_refresh_token = "squatter-refresh"

        with backend_fault(
            config,
            "delete_attr",
            lambda a, b, n: a == legacy.id and n == "oauth_refresh_token",
            lambda: True,  # DynamoDB's shape: answers True, deletes nothing
        ):
            assert auth.lookup_or_create_actor_by_identifier(creator) is None

        assert not istore(Actor(actor_id=aid(legacy), config=config)).auth_method


class TestVouchedActorMidDeletion:
    """Issue AW (entry 35 reverted): a tombstone alone never wipes a live
    vouched actor; it can be stale (a clear on create that faulted) or left
    by a DELETE that stalled."""

    def test_sign_in_returns_a_tombstoned_vouched_actor_untouched(self, auth) -> None:
        config = auth.config
        creator = uuid_email()
        live = create_core_actor(config, creator, auth_method="google_oauth2")
        assert live.property is not None
        live.property["notes"] = "kept"
        deletion.mark_actor_deleted(aid(live), config)
        try:
            signed_in = auth.lookup_or_create_actor_by_identifier(creator)

            assert signed_in is not None and signed_in.id == live.id
            kept = Actor(actor_id=aid(live), config=config)
            assert kept.property is not None and kept.property["notes"] == "kept"
        finally:
            deletion.clear_actor_tombstone(aid(live), config)


class TestRefusedCreateUnbinds:
    """Issue AU."""

    def test_false_create_leaves_no_handle_on_the_other_actor(self) -> None:
        config = make_config()
        live = create_core_actor(config, uuid_email(), auth_method="google_oauth2")
        loser = Actor(config=config)

        assert (
            loser.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="other",
                actor_id=aid(live),
            )
            is False
        )

        assert loser.id is None and loser.handle is None and loser.store is None
        assert loser.delete() is False
        assert Actor(actor_id=aid(live), config=config).id == live.id


class TestMcpBridgeCreateRace:
    """Issue AR: the loser of the race loads the winner's actor."""

    def test_lost_race_returns_the_existing_actor(self) -> None:
        config = make_mcp_config()
        handler = make_mcp_handler(cfg=config)
        actor_id = f"mcp{uuid.uuid4().hex}"
        real_create = Actor.create

        def other_request_wins(self: Actor, *a: Any, **kw: Any) -> bool:
            assert real_create(Actor(config=config), *a, **kw)
            return real_create(self, *a, **kw)

        with patch.object(Actor, "create", other_request_wins):
            result = handler._get_or_create_actor_cached(
                actor_id, {"email": uuid_email()}, 0.0
            )

        assert result is not None and result.id == actor_id


class TestCreatorPinOnTheConsumerPath:
    """Issue AV: ActorInterface.modify_creator(unvouch=True) honours the pin."""

    def test_pinned_interface_change_is_refused(self) -> None:
        config = make_config()
        config.force_email_prop_as_creator = True
        owner = uuid_email()
        actor = create_core_actor(config, owner, auth_method="google_oauth2")
        istore(actor).email = owner

        assert not ActorInterface(actor).modify_creator(uuid_email(), unvouch=True)

        row = Actor(actor_id=aid(actor), config=config)
        assert row.creator == owner
        assert istore(row).auth_method == "google_oauth2"
