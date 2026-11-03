"""Fault-contract and subscription follow-ups (Phase 3): the revocation order,
clear_all_state_for_peer, diff registration, is_suspended, DynamoDB
DbSubscription.modify and the resync record.

Plan: thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md, Phase 3.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.db.exceptions import DbError
from tests._adoption_helpers import (
    aid,
    create_core_actor,
    make_config,
    seam_fault,
    uuid_email,
)


@pytest.fixture
def config() -> Any:
    return make_config()


class TestRevocationOrder:
    @patch("actingweb.remote_storage.RemotePeerStore")
    def test_a_listing_fault_raises(self, store_cls: Any) -> None:
        from actingweb.handlers.callbacks import CallbacksHandler

        store = Mock()
        store.list_all_lists.side_effect = DbError("listing")
        store_cls.return_value = store
        handler = CallbacksHandler(config=Mock())
        with pytest.raises(DbError):
            handler._delete_revoked_peer_data(Mock(id="a"), "peer", ["memory_*"])
        store.list_all_lists.assert_called_once_with(strict=True)

    @patch("actingweb.remote_storage.RemotePeerStore")
    def test_a_delete_fault_raises(self, store_cls: Any) -> None:
        from actingweb.handlers.callbacks import CallbacksHandler

        store = Mock()
        store.list_all_lists.return_value = ["memory_a"]
        store.delete_list.side_effect = DbError("delete")
        store_cls.return_value = store
        handler = CallbacksHandler(config=Mock())
        with pytest.raises(DbError):
            handler._delete_revoked_peer_data(Mock(id="a"), "peer", ["memory_*"])

    def test_the_listing_reads_strictly(self, config: Any) -> None:
        from actingweb.attribute_list_store import AttributeListStore

        actor = create_core_actor(config, uuid_email())
        store = AttributeListStore(actor_id=aid(actor), bucket="peer-x", config=config)
        with (
            seam_fault(config, "attribute", "Attribute", "query"),
            pytest.raises(DbError),
        ):
            store.list_all(strict=True)
        with seam_fault(config, "attribute", "Attribute", "query"):
            assert store.list_all() == []  # the other callers keep the fold


class TestClearAllStateForPeer:
    def test_a_bucket_fault_raises(self, config: Any) -> None:
        from actingweb.callback_processor import CallbackProcessor
        from actingweb.interface.actor_interface import ActorInterface

        actor = create_core_actor(config, uuid_email())
        processor = CallbackProcessor(ActorInterface(actor))
        with (
            seam_fault(config, "attribute", "Attribute", "query"),
            pytest.raises(DbError),
        ):
            processor.clear_all_state_for_peer("peer-1")


class TestDiffRegistration:
    def test_a_fault_raises_and_the_value_is_written(self, config: Any) -> None:
        from actingweb.db import get_subscription
        from actingweb.interface.actor_interface import ActorInterface

        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor), peerid="p1", subid="s1", target="properties"
        )
        iface = ActorInterface(actor)
        with (
            patch.object(type(actor), "register_diffs", side_effect=DbError("diff")),
            pytest.raises(DbError),
        ):
            iface.properties["colour"] = "blue"
        reloaded = ActorInterface(type(actor)(actor_id=aid(actor), config=config))
        assert reloaded.properties["colour"] == "blue"


class TestIsSuspended:
    def test_a_backend_fault_raises(self, config: Any) -> None:
        actor = create_core_actor(config, uuid_email())
        with (
            seam_fault(
                config,
                "subscription_suspension",
                "SubscriptionSuspension",
                "get",
            ),
            pytest.raises(DbError),
        ):
            actor.is_subscription_suspended("properties")

    def test_not_suspended_is_false(self, config: Any) -> None:
        actor = create_core_actor(config, uuid_email())
        assert actor.is_subscription_suspended("properties") is False


class TestResyncRecord:
    def _subscribed(self, config: Any, n: int) -> Any:
        from actingweb.db import get_subscription

        actor = create_core_actor(config, uuid_email())
        for i in range(n):
            assert get_subscription(config).create(
                actor_id=aid(actor),
                peerid=f"p{i}",
                subid=f"s{i}",
                target="properties",
                callback=False,
            )
        return actor

    def test_a_retry_re_sends_only_to_the_ones_that_missed(self, config: Any) -> None:
        actor = self._subscribed(config, 3)
        assert actor.suspend_subscriptions("properties")
        sent: list[str] = []

        def resync(self: Any, sub: dict[str, Any], _sub: Any = None) -> bool:
            sent.append(str(sub.get("peerid")))
            return sub.get("peerid") != "p1"  # p1's resync fails over HTTP

        with patch.object(type(actor), "_callback_subscription_resync", resync):
            assert actor.resume_subscriptions("properties") == 2
            assert sorted(sent) == ["p0", "p1", "p2"]
            sent.clear()
            assert actor.resume_subscriptions("properties") == 0  # p1 fails again
            assert sent == ["p1"]
        sent.clear()
        with patch.object(
            type(actor), "_callback_subscription_resync", lambda *_a, **_k: True
        ):
            assert actor.resume_subscriptions("properties") == 1
        assert actor._resync_pending("properties", None) is None
        # Nothing left to re-send, and not suspended: nothing happens.
        assert actor.resume_subscriptions("properties") == 0

    def test_a_deleted_subscription_drops_out_of_the_record(self, config: Any) -> None:

        actor = self._subscribed(config, 2)
        assert actor.suspend_subscriptions("properties")
        with patch.object(
            type(actor), "_callback_subscription_resync", lambda *_a, **_k: False
        ):
            actor.resume_subscriptions("properties")
        from actingweb.subscription import Subscription

        assert Subscription(
            actor_id=aid(actor), peerid="p0", subid="s0", config=config
        ).delete()
        seen: list[str] = []
        # A later request: a fresh actor (one instance memoises its
        # subscriptions).
        later = type(actor)(actor_id=aid(actor), config=config)
        with patch.object(
            type(actor),
            "_callback_subscription_resync",
            lambda _s, sub, *_a: seen.append(str(sub.get("peerid"))) or True,
        ):
            later.resume_subscriptions("properties")
        assert seen == ["p1"]


@pytest.mark.skipif(
    os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb",
    reason="the DynamoDB whole-item save is what this pins",
)
class TestDynamoDbModify:
    def _sub(self, config: Any) -> tuple[str, Any]:
        from actingweb.db import get_subscription

        actor_id = aid(create_core_actor(config, uuid_email()))
        handle = get_subscription(config)
        assert handle.create(
            actor_id=actor_id, peerid="p", subid="s", target="properties"
        )
        return actor_id, handle

    def test_a_stale_handle_keeps_a_newer_seqnr(self, config: Any) -> None:
        from actingweb.db import get_subscription

        actor_id, _ = self._sub(config)
        stale = get_subscription(config)
        stale.get(actor_id=actor_id, peerid="p", subid="s")
        newer = get_subscription(config).increment_seq(
            actor_id=actor_id, peerid="p", subid="s"
        )
        assert stale.modify(granularity="low")
        fresh = get_subscription(config).get(actor_id=actor_id, peerid="p", subid="s")
        assert fresh is not None
        # The whole-item save of 3.15 wrote the stale handle's seqnr back.
        assert fresh["sequence"] == newer and fresh["granularity"] == "low"

    def test_no_fields_is_a_no_op(self, config: Any) -> None:
        _actor_id, handle = self._sub(config)
        assert handle.modify() is True

    def test_a_deleted_row_is_not_recreated(self, config: Any) -> None:
        from actingweb.db import get_subscription
        from actingweb.subscription import Subscription

        actor_id, _ = self._sub(config)
        handle = get_subscription(config)
        handle.get(actor_id=actor_id, peerid="p", subid="s")
        assert Subscription(
            actor_id=actor_id, peerid="p", subid="s", config=config
        ).delete()
        assert handle.modify(granularity="low") is False
        assert (
            get_subscription(config).get(actor_id=actor_id, peerid="p", subid="s")
            is None
        )


class TestResyncRecordKeysByPeer:
    def test_the_same_subscription_id_at_two_peers_is_two_entries(
        self, config: Any
    ) -> None:
        from actingweb.db import get_subscription

        actor = create_core_actor(config, uuid_email())
        for peer in ("pa", "pb"):
            assert get_subscription(config).create(
                actor_id=aid(actor),
                peerid=peer,
                subid="same",
                target="properties",
                callback=False,
            )
        assert actor.suspend_subscriptions("properties")
        with patch.object(
            type(actor),
            "_callback_subscription_resync",
            lambda _s, sub, *_a: sub.get("peerid") != "pa",
        ):
            actor.resume_subscriptions("properties")
        assert actor._resync_pending("properties", None) == ["pa:same"]
        sent: list[str] = []
        later = type(actor)(actor_id=aid(actor), config=config)
        with patch.object(
            type(actor),
            "_callback_subscription_resync",
            lambda _s, sub, *_a: sent.append(str(sub.get("peerid"))) or True,
        ):
            later.resume_subscriptions("properties")
        assert sent == ["pa"]


class TestLostDiffRaises:
    def test_no_diff_and_no_gap_raises_after_the_others(self, config: Any) -> None:
        from actingweb.db import get_subscription

        actor = create_core_actor(config, uuid_email())
        assert get_subscription(config).create(
            actor_id=aid(actor), peerid="p1", subid="s1", target="properties"
        )
        with (
            patch.object(type(actor), "_leave_sequence_gap", return_value=False),
            patch(
                "actingweb.subscription.Subscription.add_diff",
                side_effect=DbError("diff write"),
            ),
            pytest.raises(DbError),
        ):
            actor.register_diffs(target="properties", subtarget="x", blob='"v"')
