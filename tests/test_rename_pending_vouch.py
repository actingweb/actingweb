"""``ActorInterface.modify_creator`` keeps the actor vouched while it renames
(3.16, owner-decided plan D8).

The new address is written as ``vouched_creator_pending`` before the rename
and promoted to ``vouched_creator`` after it. A sign-in during the rename
finds the actor vouched under the old creator and under the new one, for an
email creator and a provider-id creator alike.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from actingweb.actor import Actor
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.oauth2 import (
    VOUCHED_CREATOR,
    VOUCHED_CREATOR_PENDING,
    is_vouched_store,
)
from tests._adoption_helpers import aid, create_core_actor, istore, make_config


def _pid() -> str:
    return f"github:{uuid.uuid4().int % 10**9}"


def _mail() -> str:
    return f"{uuid.uuid4().hex[:12]}@example.com"


@pytest.mark.parametrize("make", [_mail, _pid], ids=["email", "provider-id"])
class TestRenameWindow:
    def test_both_creators_read_vouched_during_the_rename(self, make: Any) -> None:
        config = make_config()
        old, new = make(), make()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        assert getattr(istore(actor), VOUCHED_CREATOR) == old
        seen: dict[str, bool] = {}
        real_modify = Actor.modify

        def modify(self: Actor, *a: Any, **k: Any) -> bool:
            # A sign-in for either address, reading the store just before the
            # rename commits.
            fresh = istore(Actor(actor_id=aid(actor), config=config))
            seen["old"] = is_vouched_store(fresh, old)
            seen["new"] = is_vouched_store(fresh, new)
            return real_modify(self, *a, **k)

        with patch.object(Actor, "modify", modify):
            assert ActorInterface(actor).modify_creator(new)
        assert seen == {"old": True, "new": True}
        done = istore(Actor(actor_id=aid(actor), config=config))
        assert getattr(done, VOUCHED_CREATOR) == new
        assert getattr(done, VOUCHED_CREATOR_PENDING, None) is None

    def test_a_raising_rename_leaves_the_old_creator_vouched(self, make: Any) -> None:
        config = make_config()
        old, new = make(), make()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        with patch.object(Actor, "modify", side_effect=CreatorTaken(new)):
            with pytest.raises(CreatorTaken):
                ActorInterface(actor).modify_creator(new)
        kept = Actor(actor_id=aid(actor), config=config)
        assert kept.creator == old
        assert is_vouched_store(istore(kept), old)
        assert getattr(istore(kept), VOUCHED_CREATOR) == old

    def test_a_fault_writing_the_pending_vouch_refuses_the_rename(
        self, make: Any
    ) -> None:
        config = make_config()
        old, new = make(), make()
        actor = create_core_actor(config, old, auth_method="google_oauth2")
        store_cls = type(istore(actor))
        real = store_cls.set_confirmed

        def set_confirmed(self: Any, k: str, v: Any, **kw: Any) -> bool:
            if k == VOUCHED_CREATOR_PENDING and v is not None:
                return False
            return real(self, k, v, **kw)

        with patch.object(store_cls, "set_confirmed", set_confirmed):
            assert ActorInterface(actor).modify_creator(new) is False
        assert Actor(actor_id=aid(actor), config=config).creator == old


def test_a_leftover_pending_vouch_is_overwritten_by_the_next_rename() -> None:
    config = make_config()
    old, stray, new = _mail(), _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    setattr(istore(actor), VOUCHED_CREATOR_PENDING, stray)
    assert ActorInterface(actor).modify_creator(new)
    done = istore(Actor(actor_id=aid(actor), config=config))
    assert getattr(done, VOUCHED_CREATOR) == new
    assert getattr(done, VOUCHED_CREATOR_PENDING, None) is None
    assert not is_vouched_store(done, stray)


def test_an_actor_vouched_before_3_16_renames_as_it_did() -> None:
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    setattr(istore(actor), VOUCHED_CREATOR, None)
    assert ActorInterface(actor).modify_creator(new)
    done = istore(Actor(actor_id=aid(actor), config=config))
    assert getattr(done, VOUCHED_CREATOR, None) is None
    assert getattr(done, VOUCHED_CREATOR_PENDING, None) is None


def test_a_rename_survives_the_next_load_under_the_email_pin() -> None:
    """Under force_email_prop_as_creator (on in make_config) the load rewrites the
    creator to the stored email; a vouched rename moves the email with it."""
    config = make_config()
    assert config.force_email_prop_as_creator
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    assert ActorInterface(actor).modify_creator(new)
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email == new


def test_a_rename_of_an_actor_without_a_stored_email_writes_none() -> None:
    """No stored email: the load rewrites nothing, so none is created (which
    would pin the creator)."""
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = None
    assert ActorInterface(actor).modify_creator(new)
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email is None


def test_a_refused_rename_puts_the_stored_email_back() -> None:
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    stored = old.replace("@example.com", "@EXAMPLE.com")
    istore(actor).email = stored  # mixed case, as a provider may store it
    with patch.object(Actor, "modify", return_value=False):
        assert ActorInterface(actor).modify_creator(new) is False
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == old
    assert istore(reloaded).email == stored  # put back exactly


def test_a_rename_to_a_provider_id_under_the_email_pin_is_refused() -> None:
    config = make_config()
    old = _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    assert ActorInterface(actor).modify_creator(_pid()) is False
    kept = Actor(actor_id=aid(actor), config=config)
    assert kept.creator == old
    assert getattr(istore(kept), VOUCHED_CREATOR_PENDING, None) is None


def _pinned_actor(config: Any) -> tuple[Actor, str]:
    old = _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    return actor, old


def test_a_lost_email_move_confirmation_goes_on_with_the_rename() -> None:
    """The email write landed but its confirmation was lost: the strict
    re-read shows it moved (the commit point), so the rename goes on."""
    config = make_config()
    actor, _old = _pinned_actor(config)
    new = _mail()
    store_cls = type(istore(actor))
    real = store_cls.set_confirmed

    def lost_ack(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == "email" and v == new:
            real(self, k, v, **kw)  # the write lands
            return False  # the confirmation is lost
        return real(self, k, v, **kw)

    with patch.object(store_cls, "set_confirmed", lost_ack):
        assert ActorInterface(actor).modify_creator(new) is True
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email == new
    assert getattr(istore(reloaded), VOUCHED_CREATOR) == new


def test_an_email_move_that_did_not_land_refuses_the_rename() -> None:
    config = make_config()
    actor, old = _pinned_actor(config)
    store_cls = type(istore(actor))
    real = store_cls.set_confirmed

    def fails(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == "email":
            return False
        return real(self, k, v, **kw)

    with patch.object(store_cls, "set_confirmed", fails):
        assert ActorInterface(actor).modify_creator(_mail()) is False
    kept = Actor(actor_id=aid(actor), config=config)
    assert kept.creator == old
    assert istore(kept).email == old
    assert is_vouched_store(istore(kept), old)


def test_an_unreadable_email_after_an_unconfirmed_move_raises() -> None:
    """Whether the commit point was passed is unknown: DbError, not False."""
    config = make_config()
    actor, _old = _pinned_actor(config)
    store_cls = type(istore(actor))
    real = store_cls.set_confirmed

    def fails(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == "email":
            return False
        return real(self, k, v, **kw)

    with (
        patch.object(store_cls, "set_confirmed", fails),
        patch.object(store_cls, "read_strict", side_effect=DbError("down")),
    ):
        with pytest.raises(DbError):
            ActorInterface(actor).modify_creator(_mail())


def test_a_load_that_moved_the_creator_first_counts_as_the_rename() -> None:
    """A request loads the actor between the email move and the rename: its
    load moves the creator to the new email, so this handle's conditional
    rename loses. That is the rename landing, not a refusal; the email is
    not put back."""
    config = make_config()
    actor, _old = _pinned_actor(config)
    new = _mail()
    real = Actor.modify
    raced: list[bool] = []

    def after_a_concurrent_load(self: Actor, *a: Any, **k: Any) -> bool:
        if not raced:
            raced.append(True)
            assert Actor(actor_id=aid(actor), config=config).creator == new
        return real(self, *a, **k)

    with patch.object(Actor, "modify", after_a_concurrent_load):
        assert ActorInterface(actor).modify_creator(new) is True
    assert actor.creator == new
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email == new
    assert getattr(istore(reloaded), VOUCHED_CREATOR) == new
    assert getattr(istore(reloaded), VOUCHED_CREATOR_PENDING, None) is None


def test_a_rename_that_raised_before_landing_completes_at_the_next_load() -> None:
    """Past the commit point the outcome converges forward: the next load
    moves the creator to the moved email, and the pending value vouches it."""
    config = make_config()
    actor, _old = _pinned_actor(config)
    new = _mail()
    with patch.object(Actor, "modify", side_effect=DbError("down")):
        with pytest.raises(DbError):
            ActorInterface(actor).modify_creator(new)
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email == new
    assert is_vouched_store(istore(reloaded), new)
    # The same call again finishes the bookkeeping.
    assert ActorInterface(reloaded).modify_creator(new) is True
    done = istore(Actor(actor_id=aid(actor), config=config))
    assert getattr(done, VOUCHED_CREATOR) == new
    assert getattr(done, VOUCHED_CREATOR_PENDING, None) is None


@pytest.mark.parametrize("pin", [True, False])
def test_a_vouch_promotion_fault_still_answers_renamed(pin: bool) -> None:
    """The creator changed, so True; the pending value keeps the new creator
    vouched until the next rename or clean."""
    import copy

    config = copy.copy(make_config())
    config.force_email_prop_as_creator = pin
    actor, _old = _pinned_actor(config)
    new = _mail()
    store_cls = type(istore(actor))
    real = store_cls.set_confirmed

    def fails(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == VOUCHED_CREATOR:
            return False
        return real(self, k, v, **kw)

    with patch.object(store_cls, "set_confirmed", fails):
        assert ActorInterface(actor).modify_creator(new) is True
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert getattr(istore(reloaded), VOUCHED_CREATOR_PENDING) == new
    assert is_vouched_store(istore(reloaded), new)


@pytest.mark.parametrize("pin", [True, False])
def test_a_rename_with_an_unreadable_store_is_refused(pin: bool) -> None:
    """Unread, a vouched actor looks unvouched: renaming it would leave its
    vouch on the old address (and, under the pin, its email)."""
    import copy

    config = copy.copy(make_config())
    config.force_email_prop_as_creator = pin
    old = _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    from actingweb.attribute import InternalStore

    with patch.object(
        InternalStore, "loaded", new_callable=lambda: property(lambda self: False)
    ):
        assert ActorInterface(actor).modify_creator(_mail()) is False
    kept = Actor(actor_id=aid(actor), config=config)
    assert kept.creator == old
    assert istore(kept).email == old
    assert getattr(istore(kept), VOUCHED_CREATOR_PENDING, None) is None


def test_a_restore_leaves_a_concurrent_renames_email_alone() -> None:
    """The restore only fires while the stored email is still the address
    this rename wrote."""
    config = make_config()
    old, mine, theirs = _mail(), _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old

    def concurrent(self: Actor, *a: Any, **k: Any) -> bool:
        # Another rename moved the email on while this one ran, then this
        # rename is refused.
        istore(Actor(actor_id=aid(actor), config=config)).email = theirs
        return False

    with patch.object(Actor, "modify", concurrent):
        assert ActorInterface(actor).modify_creator(mine) is False
    assert istore(Actor(actor_id=aid(actor), config=config)).email == theirs


def test_a_faulting_restore_keeps_the_renames_own_outcome() -> None:
    """The store faults during the rollback too: the rename's own exception
    (CreatorTaken) still reaches the caller."""
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    store_cls = type(istore(actor))
    with (
        patch.object(Actor, "modify", side_effect=CreatorTaken(new)),
        patch.object(store_cls, "replace_if_equal", side_effect=RuntimeError("down")),
    ):
        with pytest.raises(CreatorTaken):
            ActorInterface(actor).modify_creator(new)


def test_a_rename_that_landed_before_its_error_keeps_the_moved_email() -> None:
    """modify raised after its write landed (a lost acknowledgement): the
    fresh read shows the new creator, so the email is not put back."""
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    real = Actor.modify

    def landed_then_raised(self: Actor, *a: Any, **k: Any) -> bool:
        real(self, *a, **k)
        raise DbError("acknowledgement lost")

    with patch.object(Actor, "modify", landed_then_raised):
        with pytest.raises(DbError):
            ActorInterface(actor).modify_creator(new)
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == new
    assert istore(reloaded).email == new


def test_a_lost_conditional_write_does_not_read_as_an_unreadable_store() -> None:
    """A lost set_if_absent invalidates the Attributes cache on a healthy
    backend; the store's own read outcome stays good, so a rename goes on."""
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    store = istore(actor)
    assert store.set_if_absent("email", _mail()) is False  # loses: email held
    assert store.loaded
    assert ActorInterface(actor).modify_creator(new)
    assert Actor(actor_id=aid(actor), config=config).creator == new


def test_a_vouch_written_since_the_load_moves_with_the_rename() -> None:
    """A sign-in vouched the actor after this handle cached its store: the
    rename reads the store afresh and moves that vouch."""
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="factory")
    assert not is_vouched_store(istore(actor), old)  # cached: unvouched
    other = istore(Actor(actor_id=aid(actor), config=config))
    other.auth_method = "google_oauth2"
    setattr(other, VOUCHED_CREATOR, old)
    other.email = old
    assert ActorInterface(actor).modify_creator(new) is True
    done = istore(Actor(actor_id=aid(actor), config=config))
    assert getattr(done, VOUCHED_CREATOR) == new
    assert is_vouched_store(done, new)


def test_a_creator_vouched_only_by_its_email_stays_vouched_mid_rename() -> None:
    """A provider-id actor whose creator the pin moved to its email: the
    recorded vouch still names the provider id, so the rename records the
    current creator first. Mid-rename both addresses read vouched."""
    config = make_config()
    pid, current, new = _pid(), _mail(), _mail()
    actor = create_core_actor(config, pid, auth_method="google_oauth2")
    istore(actor).email = current
    loaded = Actor(actor_id=aid(actor), config=config)
    assert loaded.creator == current  # the pin moved it
    assert getattr(istore(loaded), VOUCHED_CREATOR) == pid
    seen: dict[str, bool] = {}
    real_modify = Actor.modify

    def modify(self: Actor, *a: Any, **k: Any) -> bool:
        fresh = istore(Actor(actor_id=aid(actor), config=config))
        seen["current"] = is_vouched_store(fresh, current)
        seen["new"] = is_vouched_store(fresh, new)
        return real_modify(self, *a, **k)

    with patch.object(Actor, "modify", modify):
        assert ActorInterface(loaded).modify_creator(new) is True
    assert seen == {"current": True, "new": True}
    done = istore(Actor(actor_id=aid(actor), config=config))
    assert getattr(done, VOUCHED_CREATOR) == new


def test_a_failed_vouch_anchor_refuses_the_rename() -> None:
    config = make_config()
    pid, current = _pid(), _mail()
    actor = create_core_actor(config, pid, auth_method="google_oauth2")
    istore(actor).email = current
    loaded = Actor(actor_id=aid(actor), config=config)
    store_cls = type(istore(loaded))
    real = store_cls.set_confirmed

    def fails(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == VOUCHED_CREATOR and v == current:
            return False
        return real(self, k, v, **kw)

    with patch.object(store_cls, "set_confirmed", fails):
        assert ActorInterface(loaded).modify_creator(_mail()) is False
    kept = Actor(actor_id=aid(actor), config=config)
    assert kept.creator == current
    assert istore(kept).email == current
    assert is_vouched_store(istore(kept), current)
