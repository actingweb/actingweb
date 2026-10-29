"""A fault part-way through an operation leaves no worse state than before
(3.16 iteration, Issues H, I, K, L and M of
``thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness.md``).
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from actingweb.actor import Actor
from actingweb.db import get_attribute, get_subscription, get_subscription_diff
from actingweb.db.exceptions import DbError
from tests._adoption_helpers import (
    aid,
    backend_fault,
    create_core_actor,
    make_config,
    raise_db_error,
    seam_fault,
    uuid_email,
)


@pytest.fixture
def config() -> Any:
    return make_config()


def _raise(*_a: Any, **_k: Any) -> Any:
    raise DbError("simulated backend fault")


class TestHDiffSequence:
    """Entries 3 and 23 (H, B3): a faulted diff write is ambiguous, so the
    sequence is kept; the next diff never reuses the seqnr."""

    def test_a_faulted_diff_write_keeps_the_sequence(self, config: Any) -> None:
        from actingweb.subscription import Subscription

        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor), peerid="p1", subid="s1", target="properties"
        )
        sub = Subscription(actor_id=aid(actor), peerid="p1", subid="s1", config=config)

        with mock.patch.object(type(get_subscription_diff(config)), "create", _raise):
            assert sub.add_diff(blob='{"x": 1}') is False

        stored = get_subscription(config).get(
            actor_id=aid(actor), peerid="p1", subid="s1"
        )
        assert stored and stored["sequence"] == 1

        again = Subscription(
            actor_id=aid(actor), peerid="p1", subid="s1", config=config
        )
        diff = again.add_diff(blob='{"x": 2}')
        assert diff and diff["sequence"] == 2


class TestIUniqueCreatorMatch:
    def test_the_matched_actor_is_bound_to_its_row(self, config: Any) -> None:
        config.unique_creator = True
        creator = uuid_email()
        first = Actor(config=config)
        assert first.create(
            url="https://test.example.com/", creator=creator, passphrase="pw-1"
        )

        again = Actor(config=config)
        assert again.create(
            url="https://test.example.com/", creator=creator, passphrase="pw-1"
        )
        assert again.id == first.id
        # Before the fix the handle held no row on DynamoDB, and this
        # delete answered False with the actor still there.
        assert again.delete() is True
        assert not Actor(actor_id=aid(first), config=config).id


class TestKCallbackDrain:
    def test_a_faulted_state_write_keeps_the_buffered_callbacks(
        self, config: Any
    ) -> None:
        from actingweb.callback_processor import CallbackProcessor
        from actingweb.interface.actor_interface import ActorInterface

        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor),
            peerid="p1",
            subid="s1",
            target="properties",
            callback=True,
        )
        processor = CallbackProcessor(ActorInterface(actor))
        pending = [{"sequence": 2, "data": {"y": 2}}]
        processor._set_pending("p1", "s1", pending)

        with (
            mock.patch.object(processor, "_set_state", _raise),
            pytest.raises(DbError),
        ):
            processor.process_callback_sync(
                peer_id="p1", subscription_id="s1", sequence=1, data={"x": 1}
            )

        assert [c["sequence"] for c in processor._get_pending("p1", "s1")] == [2]


class TestLReplacementOrder:
    def test_a_list_fault_fires_no_hook_and_writes_no_tombstone(
        self, config: Any
    ) -> None:
        from actingweb import oauth2 as oauth2_module
        from actingweb.deletion import DeletionStatus, get_deletion_status

        victim = create_core_actor(config, uuid_email())
        hooks = mock.Mock()

        with (
            seam_fault(config, "trust", "Trust", "query"),
            pytest.raises(DbError),
        ):
            oauth2_module._remove_for_replacement(
                victim,
                config=config,
                hooks=hooks,
                creator=victim.creator or "",
                client_ids=[],
            )

        hooks.execute_lifecycle_hooks.assert_not_called()
        assert get_deletion_status(aid(victim), config) != DeletionStatus.DELETED
        assert Actor(actor_id=aid(victim), config=config).id == aid(victim)


class TestMTrusteeRootWrite:
    def test_a_faulted_trustee_root_write_leaves_no_actor(self, config: Any) -> None:
        actor = Actor(config=config)
        actor_id = f"fixed{uuid_email().split('@')[0].replace('-', '')}"

        with (
            backend_fault(
                config,
                "set_attr",
                lambda a, b, n: b == "_internal" and n == "trustee_root",
                raise_db_error,
            ),
            pytest.raises(DbError),
        ):
            actor.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="pw",
                actor_id=actor_id,
                trustee_root="https://trustee.example.com/",
            )

        assert actor.id is None
        assert not Actor(actor_id=actor_id, config=config).id
        assert get_attribute(config) is not None
