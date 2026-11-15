"""The creator follows the stored email where the email is written (3.16,
email-as-creator Phase 2).

Under ``with_email_as_creator`` (on in ``make_config``) a write of a vouched
actor's ``_internal`` email to another address renames the creator in the
same atomic operation (``DbActor.rename_creator``), and a load is one read.
``ActorInterface.modify_creator`` is that same operation. Replaces the
3.15 pending-vouch protocol's tests (``test_rename_pending_vouch.py``).

Organised by the outcome table under the plan's Phase 2: for each
``InternalStore`` method, what it answers when the rename applies, loses
its own condition, meets a held address, or faults.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from actingweb.actor import Actor
from actingweb.attribute import InternalStore
from actingweb.db import get_actor, get_attribute
from actingweb.db.creator_rename import RenameOutcome
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.oauth2 import VOUCHED_CREATOR, VOUCHED_CREATOR_PENDING, is_vouched_store
from tests._adoption_helpers import aid, create_core_actor, istore, make_config


def _pid() -> str:
    return f"github:{uuid.uuid4().int % 10**9}"


def _mail() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


def _flag_off() -> Any:
    config = copy.copy(make_config())
    config.force_email_prop_as_creator = False
    return config


def _vouched(config: Any, creator: str) -> Actor:
    """A vouched actor whose stored email is its creator, written through
    the backend so no link runs."""
    actor = create_core_actor(config, creator, auth_method="google_oauth2")
    get_attribute(config).set_attr(aid(actor), "_internal", "email", creator)
    return Actor(actor_id=aid(actor), config=config)


def _reload(config: Any, actor: Actor) -> Actor:
    return Actor(actor_id=aid(actor), config=config)


def _rename_cls(config: Any) -> Any:
    return type(get_actor(config))


@contextmanager
def _before_rename(config: Any, hook: Callable[[], None]) -> Iterator[list[Any]]:
    """Run ``hook`` just before each ``rename_creator`` call commits (a
    concurrent writer), and record the outcomes."""
    cls = _rename_cls(config)
    real = cls.rename_creator
    outcomes: list[Any] = []

    def wrapped(self: Any, *a: Any, **k: Any) -> Any:
        hook()
        result = real(self, *a, **k)
        outcomes.append(result)
        return result

    with patch.object(cls, "rename_creator", wrapped):
        yield outcomes


@contextmanager
def _count_renames(config: Any) -> Iterator[list[Any]]:
    cls = _rename_cls(config)
    real = cls.rename_creator
    calls: list[Any] = []

    def counted(self: Any, *a: Any, **k: Any) -> Any:
        calls.append(k)
        return real(self, *a, **k)

    with patch.object(cls, "rename_creator", counted):
        yield calls


class TestTheLinkedWrite:
    @pytest.mark.parametrize("make", [_mail, _pid, lambda: "creator"])
    def test_writing_the_email_moves_creator_vouch_and_email_together(
        self, make: Any
    ) -> None:
        config = make_config()
        creator, new = make(), _mail()
        actor = create_core_actor(config, creator, auth_method="google_oauth2")
        istore(actor).email = new
        assert actor.creator == new
        done = _reload(config, actor)
        assert done.creator == new
        assert istore(done).email == new
        assert is_vouched_store(istore(done), new)
        if creator != "creator":
            assert getattr(istore(done), VOUCHED_CREATOR) == new

    def test_the_owner_follows_so_a_later_modify_succeeds(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        istore(actor).email = new
        assert actor.creator == new
        assert actor.modify(passphrase="rotated")
        assert _reload(config, actor).passphrase == "rotated"

    def test_a_store_without_an_owner_updates_only_itself(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        bare = InternalStore(actor_id=aid(actor), config=config)
        bare.email = new
        assert bare.email == new
        assert _reload(config, actor).creator == new

    def test_a_3_15_pending_value_is_removed(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        get_attribute(config).set_attr(
            aid(actor), "_internal", VOUCHED_CREATOR_PENDING, _mail()
        )
        istore(_reload(config, actor)).email = _mail()
        assert getattr(istore(_reload(config, actor)), VOUCHED_CREATOR_PENDING) is None

    def test_the_create_time_shortcut_is_spent_by_its_first_write(self) -> None:
        """A store created with its actor writes that actor's creator as a
        plain write once; after a rename elsewhere the same instance's
        write of its old creator is a linked one."""
        config = make_config()
        old = _mail()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        with _count_renames(config) as renames:
            istore(actor).email = old
        assert renames == []
        istore(_reload(config, actor)).email = _mail()
        istore(actor).email = old
        assert _reload(config, actor).creator == old

    def test_a_stale_instance_writing_its_loaded_creator_renames_back(self) -> None:
        """The no-read shortcut is only for a store created with its actor:
        any other instance reads afresh, sees the creator moved elsewhere,
        and its write is a linked one."""
        config = make_config()
        old = _mail()
        stale = _vouched(config, old)
        istore(_reload(config, stale)).email = _mail()
        istore(stale).email = old
        assert _reload(config, stale).creator == old


class TestPlainWrites:
    @pytest.mark.parametrize(
        "setup",
        ["flag-off", "other-bucket", "none", "not-an-address", "created-now"],
    )
    def test_no_read_and_no_rename(self, setup: str) -> None:
        config = _flag_off() if setup == "flag-off" else make_config()
        creator = _mail()
        actor = create_core_actor(config, creator, auth_method="google_oauth2")
        store = istore(actor)
        value: Any = _mail()
        if setup == "other-bucket":
            store = InternalStore(actor_id=aid(actor), config=config, bucket="other")
        elif setup == "none":
            value = None
        elif setup == "not-an-address":
            value = "not an address"
        elif setup == "created-now":
            value = creator
        with (
            _count_renames(config) as renames,
            patch.object(_rename_cls(config), "get", side_effect=AssertionError),
        ):
            store.email = value
        assert renames == []
        assert _reload(config, actor).creator == creator

    @pytest.mark.parametrize("state", ["unvouched", "trustee", "equal", "case-only"])
    def test_read_then_a_write_conditioned_on_the_creator(self, state: str) -> None:
        """The creator stays, but the write is still one operation
        conditioned on the creator just read: a rename committing in between
        is not undone by it."""
        config = make_config()
        creator = _mail()
        actor = _vouched(config, creator)
        value = _mail()
        if state == "unvouched":
            istore(actor).auth_method = "factory"
        elif state == "trustee":
            actor.modify(creator="trustee")
        elif state == "equal":
            value = creator
        elif state == "case-only":
            value = creator.upper()
        before = _reload(config, actor).creator
        with _count_renames(config) as renames:
            istore(_reload(config, actor)).email = value
        assert len(renames) == 1
        assert renames[0]["expected"] == before
        assert renames[0]["creator"] == before
        assert _reload(config, actor).creator == before
        assert istore(_reload(config, actor)).email == value


class TestOutcomes:
    """The outcome table, method by method."""

    def test_set_confirmed_applies(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        assert istore(actor).set_confirmed("email", new) is True
        assert _reload(config, actor).creator == new

    def test_replace_if_equal_applies_and_loses(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        new = _mail()
        assert istore(actor).replace_if_equal("email", _mail(), new) is False
        assert istore(actor).email == old
        assert _reload(config, actor).creator == old
        assert istore(actor).replace_if_equal("email", old, new) is True
        assert _reload(config, actor).creator == new

    def test_set_if_absent_loses_to_a_stored_email(self) -> None:
        """The seed race: a sign-in that loaded the actor before a rename
        seeds the old address; the rename's email is there, so the seed's
        condition fails and the creator stays."""
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        late = istore(_reload(config, actor))
        new = _mail()
        istore(_reload(config, actor)).email = new
        assert late.set_if_absent("email", old) is False
        assert late.email == new
        assert _reload(config, actor).creator == new

    def test_set_if_absent_applies_on_an_actor_without_one(self) -> None:
        config = make_config()
        pid = _pid()
        actor = create_core_actor(config, pid, auth_method="google_oauth2")
        new = _mail()
        assert istore(_reload(config, actor)).set_if_absent("email", new) is True
        assert _reload(config, actor).creator == new

    def test_a_row_changed_twice_is_each_methods_failure(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())

        def rename_elsewhere() -> None:
            get_actor(config).get(actor_id=aid(actor))
            other = get_actor(config)
            other.get(actor_id=aid(actor))
            other.modify(creator=_mail())

        store = istore(_reload(config, actor))
        with _before_rename(config, rename_elsewhere) as outcomes:
            assert store.set_confirmed("email", _mail()) is False
        assert outcomes == [RenameOutcome.ROW_CHANGED] * 2
        with _before_rename(config, rename_elsewhere):
            with pytest.raises(DbError):
                store.email = _mail()
        with _before_rename(config, rename_elsewhere):
            with pytest.raises(DbError):
                istore(_reload(config, actor)).set_if_absent("email", _mail())

    def test_a_sign_in_unvouching_mid_write_leaves_the_creator(self) -> None:
        """The rename loses its marker condition; the second fresh read finds
        the actor unvouched, and the email is written with the creator kept
        (conditioned on it)."""
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)

        def unvouch() -> None:
            get_attribute(config).set_attr(
                aid(actor), "_internal", "auth_method", "creator_changed"
            )

        new = _mail()
        with _before_rename(config, unvouch) as outcomes:
            assert istore(actor).set_confirmed("email", new) is True
        assert outcomes == [RenameOutcome.MARKER_CHANGED, RenameOutcome.APPLIED]
        done = _reload(config, actor)
        assert done.creator == old
        assert istore(done).email == new

    def test_a_fault_is_each_methods_fault_answer(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        with patch.object(
            _rename_cls(config), "rename_creator", side_effect=DbError("x")
        ):
            assert istore(actor).set_confirmed("email", _mail()) is False
            with pytest.raises(DbError):
                istore(actor).set_confirmed("email", _mail(), raise_on_fault=True)
            assert istore(actor).replace_if_equal("email", old, _mail()) is False
            with pytest.raises(DbError):
                istore(actor).email = _mail()
            with pytest.raises(DbError):
                istore(actor).set_if_absent("email", _mail())
        done = _reload(config, actor)
        assert done.creator == old
        assert istore(done).email == old

    def test_an_unreadable_bucket_refuses_the_write(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        attrs = type(get_attribute(config))
        with patch.object(attrs, "get_bucket", side_effect=DbError("x")):
            with pytest.raises(DbError):
                istore(actor).email = _mail()
        assert _reload(config, actor).creator == old

    def test_a_held_address_raises_creator_taken_where_the_method_raises(
        self,
    ) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        with patch.object(
            _rename_cls(config), "rename_creator", side_effect=CreatorTaken("x")
        ):
            with pytest.raises(CreatorTaken):
                istore(actor).email = _mail()
            with pytest.raises(CreatorTaken):
                istore(actor).set_if_absent("email", _mail())
            assert istore(actor).set_confirmed("email", _mail()) is False
            assert istore(actor).replace_if_equal("email", old, _mail()) is False


class TestRaces:
    def test_a_rename_between_the_read_and_the_write_is_not_undone(self) -> None:
        """A sign-in's clean-in-place writes the email of an unvouched actor;
        an application rename commits between its fresh read and its write.
        The write loses its row condition and is retried against the new
        creator, which it keeps."""
        config = make_config()
        old, renamed = _mail(), _mail()
        actor = _vouched(config, old)
        istore(actor).auth_method = "creator_changed"
        done: list[bool] = []

        def rename_once() -> None:
            if not done:
                done.append(True)
                other = get_actor(config)
                other.get(actor_id=aid(actor))
                other.modify(creator=renamed)

        with _before_rename(config, rename_once) as outcomes:
            istore(_reload(config, actor)).email = old
        assert outcomes == [RenameOutcome.ROW_CHANGED, RenameOutcome.APPLIED]
        assert _reload(config, actor).creator == renamed

    def test_a_lost_acknowledgement_reads_back_as_applied(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        cls = _rename_cls(config)
        real = cls.rename_creator

        def lands_then_faults(self: Any, *a: Any, **k: Any) -> Any:
            real(self, *a, **k)
            raise DbError("lost acknowledgement")

        with patch.object(cls, "rename_creator", lands_then_faults):
            assert istore(actor).set_confirmed("email", new) is True
        assert actor.creator == new
        assert istore(actor).email == new
        assert actor.modify(passphrase="after")


class TestTheLoad:
    def test_a_load_is_one_get_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tests._read_counters import count_dynamodb_operations

        config = make_config()
        actor = _vouched(config, _mail())
        get_attribute(config).set_attr(aid(actor), "_internal", "email", _mail())
        ops = count_dynamodb_operations(monkeypatch)
        Actor(actor_id=aid(actor), config=config)
        assert dict(ops) == {"GetItem": 1}

    def test_a_sign_in_lookup_finds_the_renamed_actor(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        istore(actor).email = new
        found = Actor(config=config)
        found.get_from_creator(new)
        assert found.id == aid(actor)

    def test_a_load_reads_no_internal_bucket(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        get_attribute(config).set_attr(aid(actor), "_internal", "email", _mail())
        attrs = type(get_attribute(config))
        with (
            patch.object(attrs, "get_bucket", side_effect=AssertionError),
            patch.object(attrs, "get_attr", side_effect=AssertionError),
        ):
            loaded = Actor(actor_id=aid(actor), config=config)
        assert loaded.id == aid(actor)

    def test_a_mismatch_written_outside_the_library_is_not_healed(self) -> None:
        config = make_config()
        creator = _mail()
        actor = _vouched(config, creator)
        get_attribute(config).set_attr(aid(actor), "_internal", "email", _mail())
        assert _reload(config, actor).creator == creator

    @pytest.mark.parametrize("recorded", [True, False])
    def test_a_direct_creator_change_is_not_undone(self, recorded: bool) -> None:
        config = make_config()
        old, x = _mail(), _mail()
        actor = _vouched(config, old)
        if not recorded:
            istore(actor).set_confirmed(VOUCHED_CREATOR, None)
        assert actor.modify(creator=x)
        done = _reload(config, actor)
        assert done.creator == x
        assert istore(done).email == old
        # With a recorded address the actor reads unvouched for X; vouched
        # before 3.16 (none recorded) it stays vouched (owner, 2026-11-15).
        assert is_vouched_store(istore(done), x) is (not recorded)

    def test_a_handoff_to_the_trustee_persists_and_is_handed_back(self) -> None:
        config = make_config()
        owner_email = _mail()
        actor = _vouched(config, owner_email)
        assert actor.modify_creator_unvouched("trustee")
        for _ in range(3):
            assert _reload(config, actor).creator == "trustee"
        back = _reload(config, actor)
        assert back.modify_creator_unvouched(owner_email)
        assert _reload(config, actor).creator == owner_email


class TestTheSdkRename:
    @pytest.mark.parametrize("make", [_mail, _pid], ids=["email", "provider-id"])
    def test_applied(self, make: Any) -> None:
        config = make_config()
        old, new = make(), _mail()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        assert ActorInterface(actor).modify_creator(new) is True
        done = _reload(config, actor)
        assert done.creator == new
        assert getattr(istore(done), VOUCHED_CREATOR) == new
        assert istore(done).email == new
        assert is_vouched_store(istore(done), new)
        assert not is_vouched_store(istore(done), old)
        assert actor.creator == new

    def test_one_operation_with_everything_in_it(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        get_attribute(config).set_attr(
            aid(actor), "_internal", VOUCHED_CREATOR_PENDING, _mail()
        )
        new = _mail()
        with _count_renames(config) as calls:
            assert ActorInterface(actor).modify_creator(new)
        assert len(calls) == 1
        call = calls[0]
        assert call["expected"] == old and call["creator"] == new
        assert call["marker"] == "google_oauth2"
        assert {w.name: w.value for w in call["internal"]} == {
            "email": new,
            VOUCHED_CREATOR: new,
            VOUCHED_CREATOR_PENDING: None,
        }

    def test_a_row_changed_since_the_read_is_refused(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        moved = _mail()

        def elsewhere() -> None:
            other = get_actor(config)
            other.get(actor_id=aid(actor))
            other.modify(creator=moved)

        with _before_rename(config, elsewhere):
            assert ActorInterface(actor).modify_creator(_mail()) is False
        done = _reload(config, actor)
        assert done.creator == moved
        assert istore(done).email == old

    def test_a_marker_changed_since_the_read_is_refused(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)

        def unvouch() -> None:
            get_attribute(config).set_attr(
                aid(actor), "_internal", "auth_method", "creator_changed"
            )

        with _before_rename(config, unvouch):
            assert ActorInterface(actor).modify_creator(_mail()) is False
        assert _reload(config, actor).creator == old

    def test_a_fault_with_the_commit_landed_answers_true(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        new = _mail()
        cls = _rename_cls(config)
        real = cls.rename_creator

        def lands_then_faults(self: Any, *a: Any, **k: Any) -> Any:
            real(self, *a, **k)
            raise DbError("lost acknowledgement")

        with patch.object(cls, "rename_creator", lands_then_faults):
            assert ActorInterface(actor).modify_creator(new) is True
        assert actor.creator == new
        assert actor.modify(passphrase="after")

    def test_a_fault_with_the_commit_lost_raises_and_moves_nothing(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        with patch.object(
            _rename_cls(config), "rename_creator", side_effect=DbError("x")
        ):
            with pytest.raises(DbError):
                ActorInterface(actor).modify_creator(_mail())
        done = _reload(config, actor)
        assert done.creator == old
        assert istore(done).email == old
        assert getattr(istore(done), VOUCHED_CREATOR) == old

    def test_an_actor_vouched_before_3_16_is_renamed_as_it_is(self) -> None:
        config = make_config()
        actor = _vouched(config, _mail())
        istore(actor).set_confirmed(VOUCHED_CREATOR, None)
        new = _mail()
        assert ActorInterface(_reload(config, actor)).modify_creator(new)
        done = istore(_reload(config, actor))
        assert getattr(done, VOUCHED_CREATOR) is None
        assert is_vouched_store(done, new)

    def test_a_provider_id_target_under_the_pin_is_refused(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        assert ActorInterface(actor).modify_creator(_pid()) is False
        assert _reload(config, actor).creator == old

    def test_without_the_flag_the_email_is_not_written(self) -> None:
        config = _flag_off()
        old, new = _mail(), _mail()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        assert ActorInterface(actor).modify_creator(new)
        done = _reload(config, actor)
        assert done.creator == new
        assert istore(done).email is None
        assert getattr(istore(done), VOUCHED_CREATOR) == new

    def test_an_unreadable_bucket_refuses_the_rename(self) -> None:
        config = make_config()
        old = _mail()
        actor = _vouched(config, old)
        attrs = type(get_attribute(config))
        with patch.object(attrs, "get_bucket", side_effect=DbError("x")):
            assert ActorInterface(actor).modify_creator(_mail()) is False
        assert _reload(config, actor).creator == old

    def test_a_vouch_written_since_the_load_moves_with_the_rename(self) -> None:
        config = make_config()
        old, new = _mail(), _mail()
        actor = create_core_actor(config, old, auth_method="factory")
        assert not is_vouched_store(istore(actor), old)
        get_attribute(config).set_attr(aid(actor), "_internal", "auth_method", "google")
        get_attribute(config).set_attr(aid(actor), "_internal", VOUCHED_CREATOR, old)
        assert ActorInterface(actor).modify_creator(new) is True
        done = istore(_reload(config, actor))
        assert getattr(done, VOUCHED_CREATOR) == new
        assert is_vouched_store(done, new)
