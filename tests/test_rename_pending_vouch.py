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
from actingweb.db.exceptions import CreatorTaken
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


def test_a_lost_email_move_confirmation_puts_the_email_back() -> None:
    config = make_config()
    old, new = _mail(), _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    istore(actor).email = old
    store_cls = type(istore(actor))
    real = store_cls.set_confirmed

    def lost_ack(self: Any, k: str, v: Any, **kw: Any) -> bool:
        if k == "email" and v == new:
            real(self, k, v, **kw)  # the write lands
            return False  # the confirmation is lost
        return real(self, k, v, **kw)

    with patch.object(store_cls, "set_confirmed", lost_ack):
        assert ActorInterface(actor).modify_creator(new) is False
    reloaded = Actor(actor_id=aid(actor), config=config)
    assert reloaded.creator == old
    assert istore(reloaded).email == old


def test_a_rename_with_an_unreadable_store_under_the_pin_is_refused() -> None:
    config = make_config()
    old = _mail()
    actor = create_core_actor(config, old, auth_method="google_oauth2")
    store_cls = type(istore(actor))
    with patch.object(
        store_cls, "loaded", new_callable=lambda: property(lambda self: False)
    ):
        assert ActorInterface(actor).modify_creator(_mail()) is False
    assert Actor(actor_id=aid(actor), config=config).creator == old
