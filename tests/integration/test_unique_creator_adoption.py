"""The sign-in adoption rule with ``with_unique_creator()`` on (3.16, PR 2
Phase 4).

Under the flag the lookup reads the one holder of the creator consistently,
there is nothing to rank and no siblings to sweep, and a ``factory`` actor is
replaced by moving the creator to the successor in one backend step before the
squatter is removed. Runs on an isolated store in the ``unique_creator``
xdist group.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest import mock

import pytest

from actingweb import actor as actor_module
from actingweb import deletion
from actingweb import oauth2 as oauth2_module
from actingweb.actor import Actor
from actingweb.db import get_actor
from actingweb.db.creator_rules import dup_value
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.deletion import DeletionStatus
from actingweb.maintenance import unique_creators
from actingweb.oauth2 import OAuth2Authenticator, OAuth2Provider
from tests._adoption_helpers import plant_squat_state

from .conftest import DATABASE_BACKEND

pytestmark = pytest.mark.xdist_group(name="unique_creator")

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def _email() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _auth(config: Any) -> OAuth2Authenticator:
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
    return OAuth2Authenticator(config, provider)


def _create(config: Any, creator: str, auth_method: str | None = "factory") -> Actor:
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=creator,
        passphrase="squatter-passphrase",
        auth_method=auth_method or "app",
    )
    if auth_method is None and actor.store is not None:
        actor.store.auth_method = None
    return actor


def _holder(config: Any, creator: str) -> str | None:
    return get_actor(config).get_creator_holder(creator)


def _row(config: Any, actor_id: str) -> dict[str, Any] | None:
    return get_actor(config).get(actor_id=actor_id)


class TestFactorySquatter:
    def test_the_owner_replaces_it_and_one_actor_holds_the_creator(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        plant_squat_state(enforced_store, squatter)
        assert squatter.id

        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert result is not None and result.id and result.id != squatter.id
        assert _row(enforced_store, squatter.id) is None
        assert _holder(enforced_store, creator) == result.id
        assert result.store is not None
        assert result.store.auth_method == "google_oauth2"
        assert result.store.auth_method_replaced_actor_id == squatter.id
        again = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert again is not None and again.id == result.id

    def test_hooks_fire_created_before_deleted(self, enforced_store: Any) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        order: list[str] = []
        hooks = mock.MagicMock()
        hooks.execute_lifecycle_hooks.side_effect = lambda event, *a, **kw: (
            order.append(event)
        )
        auth = _auth(enforced_store)

        result = auth.lookup_or_create_actor_by_identifier(creator, hooks=hooks)

        assert result is not None and result.id != squatter.id
        assert order.index("actor_created") < order.index("actor_deleted")
        assert order[-1] == "actor_adopted"

    def test_a_factory_post_in_the_gap_is_refused_and_the_sign_in_wins(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        refused: list[bool] = []
        real = actor_module.relationship_summary

        def factory_post_in_the_gap(*args: Any, **kwargs: Any) -> Any:
            try:
                _create(enforced_store, creator)
            except CreatorTaken:
                refused.append(True)
            return real(*args, **kwargs)

        with mock.patch.object(
            actor_module, "relationship_summary", factory_post_in_the_gap
        ):
            result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert refused == [True]
        assert result is not None and result.id != squatter.id
        assert _holder(enforced_store, creator) == result.id

    def test_a_rename_in_the_gap_fails_the_sign_in_closed(
        self, enforced_store: Any
    ) -> None:
        creator, elsewhere = _email(), _email()
        squatter = _create(enforced_store, creator)
        assert squatter.id
        real = actor_module.relationship_summary

        def rename_in_the_gap(*args: Any, **kwargs: Any) -> Any:
            # PUT /<id>/trust/trustee by the squatter.
            renamed = Actor(actor_id=squatter.id, config=enforced_store)
            assert renamed.modify_creator_unvouched(elsewhere)
            return real(*args, **kwargs)

        with mock.patch.object(actor_module, "relationship_summary", rename_in_the_gap):
            with pytest.raises(CreatorTaken):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        # The renamed actor is not adopted and nothing took the address.
        row = _row(enforced_store, squatter.id)
        assert row is not None and row["creator"] == elsewhere
        assert _holder(enforced_store, creator) is None
        assert _holder(enforced_store, elsewhere) == squatter.id


class TestDeletionStatus:
    def test_an_unfinished_wipe_is_finished_by_the_swap(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        assert squatter.id
        deletion.mark_actor_deleted(squatter.id, enforced_store)

        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert result is not None and result.id != squatter.id
        assert _row(enforced_store, squatter.id) is None
        assert _holder(enforced_store, creator) == result.id

    def test_an_unknown_status_answers_503_and_writes_nothing(
        self, enforced_store: Any
    ) -> None:
        from actingweb import deletion as deletion_module

        creator = _email()
        squatter = _create(enforced_store, creator)
        assert squatter.id
        with mock.patch.object(
            deletion_module,
            "get_deletion_status",
            return_value=DeletionStatus.UNKNOWN,
        ):
            with pytest.raises(DbError) as exc:
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert not isinstance(exc.value, CreatorTaken)
        assert _row(enforced_store, squatter.id) is not None
        assert _holder(enforced_store, creator) == squatter.id

    def test_a_vouched_actor_with_a_tombstone_still_signs_in_untouched(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        owner = _create(enforced_store, creator, auth_method="google_oauth2")
        assert owner.id and owner.property is not None
        owner.property["notes"] = "kept"
        deletion.mark_actor_deleted(owner.id, enforced_store)
        try:
            result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
            assert result is not None and result.id == owner.id
            kept = Actor(actor_id=owner.id, config=enforced_store)
            assert kept.property is not None and kept.property["notes"] == "kept"
        finally:
            deletion.clear_actor_tombstone(owner.id, enforced_store)


class TestOtherBranches:
    def test_an_unmarked_actor_is_cleaned_in_place(self, enforced_store: Any) -> None:
        creator = _email()
        legacy = _create(enforced_store, creator, auth_method=None)
        plant_squat_state(enforced_store, legacy)

        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert result is not None and result.id == legacy.id
        assert result.store is not None
        assert result.store.auth_method == "google_oauth2"
        assert _holder(enforced_store, creator) == legacy.id

    def test_a_first_sign_in_creates_and_holds_the_creator(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert result is not None and result.id
        assert _holder(enforced_store, creator) == result.id


class TestFaults:
    def test_a_creators_read_fault_answers_503_and_creates_nothing(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        db_class = type(get_actor(enforced_store))
        with mock.patch.object(
            db_class, "get_creator_holder", side_effect=DbError("throttled")
        ):
            with pytest.raises(DbError):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert _holder(enforced_store, creator) is None

    def test_a_removal_fault_after_the_swap_leaves_the_successor(
        self, enforced_store: Any
    ) -> None:
        creator = _email()
        squatter = _create(enforced_store, creator)
        assert squatter.id
        with mock.patch.object(
            oauth2_module,
            "_remove_for_replacement",
            side_effect=DbError("throttled"),
        ):
            with pytest.raises(DbError):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        successor = _holder(enforced_store, creator)
        assert successor and successor != squatter.id
        left = _row(enforced_store, squatter.id)
        assert left is not None
        report = unique_creators.collect(enforced_store)
        if DYNAMODB:
            # Still named the creator, with no record: report shows both.
            assert sorted(report.exact[creator]) == sorted([squatter.id, successor])
        else:
            assert left["creator"] == dup_value(creator, squatter.id)
            assert squatter.id in report.dup_actors
        # The next sign-in finds the successor.
        again = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert again is not None and again.id == successor

    @pytest.mark.skipif(not DYNAMODB, reason="the creators table is DynamoDB's")
    def test_an_orphaned_record_is_repaired_and_the_sign_in_creates(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        creator = _email()
        Creator(creator=creator, actor_id="no-such-actor").save()
        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert result is not None and result.id
        assert _holder(enforced_store, creator) == result.id
        report = unique_creators.collect(enforced_store)
        assert not report.orphans


@pytest.mark.skipif(not DYNAMODB, reason="PostgreSQL's holder is the row itself")
class TestMismatchedRecord:
    """A7, then the audit's R1: a record naming an actor whose creator
    changed is repaired; the sign-in never lands on that actor nor hands
    over its new address, and the owner of the old address gets an actor."""

    def _rename_raw(self, actor_id: str, creator: str) -> None:
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        row = ActorModel.get(actor_id, consistent_read=True)
        row.update(actions=[ActorModel.creator.set(creator)])

    def test_a_vouched_actor_is_not_signed_in_to(self, enforced_store: Any) -> None:
        old, new = _email(), _email()
        owner = _create(enforced_store, old, auth_method="google_oauth2")
        assert owner.id
        self._rename_raw(owner.id, new)  # the record still says old -> owner
        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(old)
        assert result is not None and result.id and result.id != owner.id
        assert _holder(enforced_store, old) == result.id
        row = _row(enforced_store, owner.id)
        assert row is not None and row["creator"] == new

    def test_a_factory_actor_does_not_hand_over_its_new_address(
        self, enforced_store: Any
    ) -> None:
        from actingweb.db.dynamodb.creator import Creator

        old, new = _email(), _email()
        squatter = _create(enforced_store, old)
        assert squatter.id
        self._rename_raw(squatter.id, new)
        Creator(creator=new, actor_id=squatter.id).save()
        result = _auth(enforced_store).lookup_or_create_actor_by_identifier(old)
        assert result is not None and result.id != squatter.id
        assert result.creator == old
        assert _holder(enforced_store, new) == squatter.id
        row = _row(enforced_store, squatter.id)
        assert row is not None and row["creator"] == new


class TestCreateFaultAfterTheSwap:
    """B7, and entry 66: the successor's marker is written before the swap
    (a generated id), so a fault there leaves the squatter holding the
    creator and nothing swapped; the next sign-in replaces it."""

    def test_a_marker_fault_swaps_nothing_and_the_next_sign_in_replaces(
        self, enforced_store: Any
    ) -> None:
        from actingweb.attribute import InternalStore

        creator = _email()
        squatter = _create(enforced_store, creator)
        assert squatter.id
        real = InternalStore.set_confirmed

        def marker_faults(self: Any, name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "auth_method" and self._db.actor_id != squatter.id:
                raise DbError("throttled")
            return real(self, name, *args, **kwargs)

        with mock.patch.object(InternalStore, "set_confirmed", marker_faults):
            with pytest.raises(DbError):
                _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert _holder(enforced_store, creator) == squatter.id
        assert _row(enforced_store, squatter.id) is not None
        again = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)
        assert again is not None and again.id and again.id != squatter.id
        assert _holder(enforced_store, creator) == again.id
        assert _row(enforced_store, squatter.id) is None
        assert again.store is not None
        assert again.store.auth_method == "google_oauth2"


class TestConcurrentFirstSignIn:
    def test_the_second_create_loads_the_winner(self, enforced_store: Any) -> None:
        creator = _email()
        real = oauth2_module._create_actor_for_identifier
        winners: list[str] = []

        def other_tab_first(*args: Any, **kwargs: Any) -> Any:
            if not winners:
                first = real(*args, **kwargs)  # the other tab's request
                winners.append(first.id or "")
            return real(*args, **kwargs)

        with mock.patch.object(
            oauth2_module, "_create_actor_for_identifier", other_tab_first
        ):
            result = _auth(enforced_store).lookup_or_create_actor_by_identifier(creator)

        assert result is not None and result.id == winners[0]
        assert _holder(enforced_store, creator) == winners[0]
