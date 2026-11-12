"""An actor reads its subscription list once per instance, an empty one too
(3.16).

``thoughts/plans/2026-11-06-subs-list-cache-lifetime.md``, Phase 2: the memo
rule, the resets an instance makes itself (its creates and deletes, trust
deletion on every exit, the dead-subscription clean-up, a resume, the trust
calls that reach the peer), the clean-up on deletion and purge, the
suspension clear on a create under an explicit id, and
``get_subscriptions_by_peer()``. Real storage, the backend
``DATABASE_BACKEND`` selects.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb import subscription as subscription_module
from actingweb import trust as trust_module
from actingweb.actor import Actor, TrustReplaced
from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.db import get_subscription_suspension
from actingweb.db.exceptions import DbError
from actingweb.handlers.subscription import SubscriptionRelationshipHandler
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.authenticated_views import AuthContext
from actingweb.interface.subscription_manager import (
    PeerSubscriptions,
    SubscriptionManager,
    SubscriptionSyncResult,
)
from actingweb.subscription import Subscription, Subscriptions
from actingweb.trust import Trust
from actingweb.trust_permissions import initialize_trust_permission_store
from tests._adoption_helpers import aid, create_core_actor, uuid_email
from tests._read_counters import backend_of, count_dynamodb_operations, count_reads


def _config() -> Config:
    """A backend-following config (``make_config`` pins DynamoDB)."""
    cfg = Config(unique_creator=False)
    cfg.fqdn = "test.example.com"
    cfg.proto = "https://"
    cfg.aw_type = "urn:actingweb:test:memo"
    cfg.devtest = True
    initialize_trust_permission_store(cfg)
    return cfg


class World:
    """A, and approved friend trusts to as many peers as asked for."""

    def __init__(self, peers: int = 0) -> None:
        self.config = _config()
        self.a = create_core_actor(self.config, uuid_email(), passphrase="pw")
        self.id = aid(self.a)
        tag = uuid.uuid4().hex[:8]
        self.peers = [f"peer-{i}-{tag}" for i in range(peers)]
        self.secrets: dict[str, str] = {}
        for peer in self.peers:
            self.trust(peer)

    def trust(self, peer: str, *, approved: bool = True) -> None:
        secret = uuid.uuid4().hex
        self.secrets[peer] = secret
        assert Trust(actor_id=self.id, peerid=peer, config=self.config).create(
            baseuri=f"https://{peer}.example.test/{peer}",
            peer_type="urn:test",
            relationship="friend",
            secret=secret,
            approved=approved,
            verified=True,
            peer_approved=True,
        )

    def fresh(self) -> Actor:
        """Another instance of A, as another request would build."""
        return Actor(self.id, self.config)

    def subscribe(
        self, peer: str, *, callback: bool = False, through: Actor | None = None
    ) -> str:
        """A subscription for ``peer`` created on ``through`` (default: another
        instance)."""
        subid = uuid.uuid4().hex
        (through or self.fresh()).create_subscription(
            peerid=peer,
            target="properties",
            granularity="high",
            subid=subid,
            callback=callback,
        )
        return subid

    def stored(self, peer: str | None = None) -> list[dict[str, Any]]:
        """From storage, not from any memo."""
        rows = Subscriptions(actor_id=self.id, config=self.config).fetch() or []
        return [r for r in rows if peer is None or r["peerid"] == peer]

    def diffs(self, peer: str, subid: str) -> list[Any]:
        sub = Subscription(
            actor_id=self.id,
            peerid=peer,
            subid=subid,
            callback=False,
            config=self.config,
        )
        return sub.get_diffs() or []

    def cleanup(self) -> None:
        if Actor(self.id, self.config).id:
            Actor(self.id, self.config).delete(notify_peers=False)


@pytest.fixture
def world() -> Iterator[World]:
    w = World(peers=3)
    yield w
    w.cleanup()


@pytest.fixture
def bare() -> Iterator[World]:
    w = World(peers=0)
    yield w
    w.cleanup()


def _write(actor: Actor, value: int) -> None:
    actor.register_diffs(target="properties", blob=json.dumps({"x": value}))


# ---------------------------------------------------------------------------
# The memo rule
# ---------------------------------------------------------------------------


class TestTheMemo:
    def test_n_reads_of_an_empty_list_fetch_once(self, bare: World) -> None:
        with count_reads(bare.config) as counts:
            for _ in range(5):
                assert bare.a.get_subscriptions() == []
        assert counts["subscription_list_fetch"] == 1

    def test_three_property_writes_fetch_the_list_once(
        self, bare: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        iface = ActorInterface(bare.a)
        with count_reads(bare.config) as counts:
            iface.properties["one"] = 1
            ops = (
                count_dynamodb_operations(monkeypatch)
                if backend_of(bare.config) == "dynamodb"
                else None
            )
            iface.properties["two"] = 2
            iface.properties["three"] = 3
        assert counts["subscription_list_fetch"] == 1
        if ops is not None:
            assert ops["Query"] == 0, dict(ops)
            assert ops.total() > 0  # the counter is live

    def test_a_strict_read_with_rows_is_kept(self, world: World) -> None:
        world.subscribe(world.peers[0])
        assert len(world.a.get_subscriptions() or []) == 1
        assert world.a.subs_list is not None and len(world.a.subs_list) == 1

    def test_a_strict_empty_read_is_kept(self, bare: World) -> None:
        assert bare.a.get_subscriptions() == []
        assert bare.a.subs_list == []

    def test_a_strict_fault_raises_and_keeps_nothing(self, bare: World) -> None:
        with (
            mock.patch.object(Subscriptions, "fetch", side_effect=DbError("x")),
            pytest.raises(DbError),
        ):
            bare.a.get_subscriptions()
        assert bare.a.subs_list is None

    def test_a_folded_fault_answers_empty_and_reads_again(self, world: World) -> None:
        world.subscribe(world.peers[0])
        real = type(subscription_module.get_subscription_list(world.config))

        def down(self: Any, *a: Any, **k: Any) -> Any:
            raise DbError("subscription list fetch")

        with mock.patch.object(real, "fetch", down):
            assert world.a.get_subscriptions(strict=False) == []
        assert world.a.subs_list is None
        assert len(world.a.get_subscriptions() or []) == 1

    def test_a_swallowed_constructor_fault_then_a_good_read_is_kept(
        self, world: World
    ) -> None:
        world.subscribe(world.peers[0])
        real = type(subscription_module.get_subscription_list(world.config))
        real_fetch = real.fetch
        calls = {"n": 0}

        def first_faults(self: Any, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise DbError("subscription list fetch")
            return real_fetch(self, *a, **k)

        with mock.patch.object(real, "fetch", first_faults):
            assert len(world.a.get_subscriptions() or []) == 1
        assert calls["n"] == 2
        assert world.a.subs_list is not None and len(world.a.subs_list) == 1

    def test_no_actor_id_answers_none(self) -> None:
        assert Actor(config=_config()).get_subscriptions() is None

    def test_a_held_instance_does_not_see_a_subscription_created_elsewhere(
        self, bare: World
    ) -> None:
        """The rule (``WM2`` on the wire): a new instance does."""
        held = bare.a
        assert held.get_subscriptions() == []
        bare.trust("late-peer")
        subid = bare.subscribe("late-peer")
        _write(held, 1)
        assert bare.diffs("late-peer", subid) == []
        _write(bare.fresh(), 2)
        assert len(bare.diffs("late-peer", subid)) == 1


# ---------------------------------------------------------------------------
# Every creation path resets the memo
# ---------------------------------------------------------------------------


class TestCreationPaths:
    def _check(self, w: World, actor: Actor, create: Any, peer: str) -> None:
        assert actor.get_subscriptions() == []  # prime with an empty read
        create()
        _write(actor, 1)
        rows = w.stored(peer)
        assert len(rows) == 1
        assert len(w.diffs(peer, rows[0]["subscriptionid"])) == 1

    def test_actor_create_subscription(self, bare: World) -> None:
        bare.trust("p")
        self._check(bare, bare.a, lambda: bare.subscribe("p", through=bare.a), "p")

    def test_subscription_manager(self, bare: World) -> None:
        bare.trust("p")
        manager = ActorInterface(bare.a).subscriptions
        self._check(
            bare,
            bare.a,
            lambda: manager.create_local_subscription(
                peer_id="p", target="properties", granularity="high"
            ),
            "p",
        )

    def test_authenticated_subscription_manager(self, bare: World) -> None:
        bare.trust("p")
        view = ActorInterface(bare.a).as_peer("p")
        self._check(
            bare,
            bare.a,
            lambda: view.subscriptions.create_local_subscription(
                target="properties", granularity="high"
            ),
            "p",
        )

    def test_remote_subscription_with_the_peers_201(self, bare: World) -> None:
        bare.trust("p")
        body = {
            "subscriptionid": uuid.uuid4().hex,
            "target": "properties",
            "granularity": "high",
        }
        answer = mock.Mock(
            status_code=201,
            headers={"Location": "https://p.example.test/p/subscriptions/x"},
            content=json.dumps(body).encode(),
        )
        with mock.patch("actingweb.actor.requests.post", return_value=answer):
            assert bare.a.get_subscriptions() == []
            assert bare.a.create_remote_subscription(
                peerid="p", target="properties", granularity="high"
            )
        # The outbound row is ours; the memo must show it.
        assert [s["peerid"] for s in bare.a.get_subscriptions() or []] == ["p"]

    def test_the_handlers_post_then_a_write_on_the_same_actor(
        self, bare: World
    ) -> None:
        bare.trust("p")
        seen: list[Actor] = []
        real_auth = SubscriptionRelationshipHandler.authenticate_actor

        def capture(self: Any, *a: Any, **k: Any) -> Any:
            result = real_auth(self, *a, **k)
            if result.actor is not None:
                assert result.actor.get_subscriptions() == []  # prime
                seen.append(result.actor)
            return result

        webobj = AWWebObj(
            url=f"https://test.example.com/{bare.id}/subscriptions/p",
            params={},
            body=json.dumps({"target": "properties", "granularity": "high"}),
            headers={"Authorization": f"Bearer {bare.secrets['p']}"},
        )
        with mock.patch.object(
            SubscriptionRelationshipHandler, "authenticate_actor", capture
        ):
            SubscriptionRelationshipHandler(webobj, bare.config).post(bare.id, "p")
        assert webobj.response.status_code == 204 or webobj.response.status_code == 201
        assert len(seen) == 1
        _write(seen[0], 1)
        rows = bare.stored("p")
        assert len(rows) == 1
        assert len(bare.diffs("p", rows[0]["subscriptionid"])) == 1


# ---------------------------------------------------------------------------
# Trust deletion
# ---------------------------------------------------------------------------


class TestTrustDeletion:
    def test_a_subscription_created_elsewhere_after_the_memo_goes(
        self, world: World
    ) -> None:
        peer = world.peers[0]
        assert world.a.get_subscriptions() == []
        world.subscribe(peer)
        world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        assert world.stored(peer) == []
        assert world.a.subs_list is None

    def test_the_block_reads_its_own_list_not_a_filled_memo(self, world: World) -> None:
        peer = world.peers[0]
        world.subscribe(peer, through=world.a)
        assert len(world.a.get_subscriptions() or []) == 1  # non-empty memo
        world.subscribe(peer)  # a second one, elsewhere
        world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        assert world.stored(peer) == []

    def test_a_hook_that_fills_the_memo_then_subscribes(self, world: World) -> None:
        peer = world.peers[0]

        def hook(_row: dict[str, Any]) -> None:
            world.a.get_subscriptions()
            world.subscribe(peer)

        world.a.delete_reciprocal_trust(
            peerid=peer, notify_peers=False, before_local_delete=hook
        )
        assert world.stored(peer) == []

    def test_a_read_fault_deletes_the_trust_and_keeps_the_subscriptions(
        self, world: World
    ) -> None:
        peer = world.peers[0]
        world.subscribe(peer)
        world.a.get_subscriptions()
        real = type(subscription_module.get_subscription_list(world.config))
        real_fetch = real.fetch

        def down(self: Any, *a: Any, **k: Any) -> Any:
            raise DbError("subscription list fetch")

        with mock.patch.object(real, "fetch", down):
            assert world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        with mock.patch.object(real, "fetch", real_fetch):
            assert len(world.stored(peer)) == 1
        assert not Trust(actor_id=world.id, peerid=peer, config=world.config).get()
        assert world.a.subs_list is None

    def _primed(self, w: World) -> str:
        peer = w.peers[0]
        w.subscribe(peer, through=w.a)
        assert len(w.a.get_subscriptions(peerid=peer) or []) == 1
        return peer

    def test_the_row_kept_by_trust_replaced(self, world: World) -> None:
        peer = self._primed(world)
        real_delete = trust_module.Trust.delete

        def repair_then_delete(self: Trust, **kw: Any) -> bool:
            assert Trust(actor_id=world.id, peerid=peer, config=world.config).modify(
                secret=uuid.uuid4().hex
            )
            return real_delete(self, **kw)

        with (
            mock.patch.object(trust_module.Trust, "delete", repair_then_delete),
            pytest.raises(TrustReplaced),
        ):
            world.a.delete_reciprocal_trust(
                peerid=peer, notify_peers=False, expected_secret=world.secrets[peer]
            )
        assert world.a.get_subscriptions(peerid=peer) == []

    def test_the_row_kept_by_a_db_error(self, world: World) -> None:
        peer = self._primed(world)
        with (
            mock.patch.object(trust_module.Trust, "delete", return_value=False),
            pytest.raises(DbError),
        ):
            world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        assert world.a.get_subscriptions(peerid=peer) == []

    def test_a_side_store_fault(self, world: World) -> None:
        peer = self._primed(world)
        with (
            mock.patch(
                "actingweb.remote_storage.RemotePeerStore.delete_all",
                side_effect=DbError("remote store"),
            ),
            pytest.raises(DbError),
        ):
            world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        assert world.a.get_subscriptions(peerid=peer) == []

    def test_a_fault_inside_the_loop(self, world: World) -> None:
        peer = world.peers[0]
        world.subscribe(peer, through=world.a)
        world.subscribe(peer, through=world.a)
        assert len(world.a.get_subscriptions(peerid=peer) or []) == 2
        real_delete = Subscription.delete
        calls = {"n": 0}

        def second_faults(self: Subscription) -> Any:
            calls["n"] += 1
            if calls["n"] == 2:
                raise DbError("subscription delete")
            return real_delete(self)

        with (
            mock.patch.object(Subscription, "delete", second_faults),
            pytest.raises(DbError),
        ):
            world.a.delete_reciprocal_trust(peerid=peer, notify_peers=False)
        assert len(world.a.get_subscriptions(peerid=peer) or []) == 1
        assert len(world.stored(peer)) == 1

    def test_no_relationship_reads_nothing(self, bare: World) -> None:
        with count_reads(bare.config) as counts:
            bare.a.delete_reciprocal_trust(peerid="nobody", notify_peers=False)
        assert counts["subscription_list_fetch"] == 0

    def test_a_relationship_that_continues_reads_nothing(self, world: World) -> None:
        peer = world.peers[0]
        with (
            count_reads(world.config) as counts,
            mock.patch(
                "actingweb.actor.requests.delete", side_effect=OSError("unreachable")
            ),
        ):
            assert (
                world.a.delete_reciprocal_trust(peerid=peer, delete_peer=True) is False
            )
        assert counts["subscription_list_fetch"] == 0
        assert Trust(actor_id=world.id, peerid=peer, config=world.config).get()

    def test_one_read_per_relationship_and_a_late_subscriber_goes(
        self, world: World
    ) -> None:
        first, second = world.peers[0], world.peers[1]
        world.subscribe(first)
        real_profile_delete: list[Any] = []

        def late(*_a: Any, **_k: Any) -> None:
            # After the first relationship's block: the second peer subscribes.
            if not real_profile_delete:
                real_profile_delete.append(1)
                world.subscribe(second)

        with (
            count_reads(world.config) as counts,
            mock.patch(
                "actingweb.remote_storage.RemotePeerStore.delete_all", side_effect=late
            ),
        ):
            world.a.delete_reciprocal_trust(notify_peers=False)
        assert counts["subscription_list_fetch"] == len(world.peers)
        assert world.stored() == []


# ---------------------------------------------------------------------------
# The dead-subscription clean-up
# ---------------------------------------------------------------------------


def _dead(peer: str, subid: str) -> SubscriptionSyncResult:
    return SubscriptionSyncResult(
        subscription_id=subid,
        success=False,
        diffs_fetched=0,
        diffs_processed=0,
        final_sequence=0,
        error="gone",
        error_code=404,
    )


class TestDeadSubscriptionCleanUp:
    def _manager(self, w: World) -> SubscriptionManager:
        return ActorInterface(w.a).subscriptions

    def _patches(self, manager: SubscriptionManager) -> Any:
        proxy = mock.Mock()
        proxy.get_resource_async = mock.AsyncMock(return_value={})

        async def sync_async(peer_id: str, subscription_id: str, **_k: Any) -> Any:
            return _dead(peer_id, subscription_id)

        stack = mock.patch.multiple(
            manager,
            sync_subscription=lambda peer_id, subscription_id, **_k: _dead(
                peer_id, subscription_id
            ),
            sync_subscription_async=sync_async,
            _get_peer_proxy=lambda _peer: proxy,
            _own_trust_path=lambda _proxy: "trust/friend/x",
            _peer_trust_state=lambda _peer, _proxy: "exists",
        )
        return stack

    @pytest.mark.parametrize("use_async", [False, True])
    def test_the_deleted_row_leaves_the_listing(
        self, world: World, use_async: bool
    ) -> None:
        peer = world.peers[0]
        world.subscribe(peer, callback=True, through=world.a)
        manager = self._manager(world)
        assert len(manager.get_subscriptions_to_peer(peer)) == 1
        with self._patches(manager):
            if use_async:
                asyncio.run(manager.sync_peer_async(peer))
            else:
                manager.sync_peer(peer)
        assert world.stored(peer) == []
        assert manager.get_subscriptions_to_peer(peer) == []

    @pytest.mark.parametrize("use_async", [False, True])
    def test_a_faulting_second_delete_still_drops_the_first(
        self, world: World, use_async: bool
    ) -> None:
        peer = world.peers[0]
        world.subscribe(peer, callback=True, through=world.a)
        world.subscribe(peer, callback=True, through=world.a)
        manager = self._manager(world)
        assert len(manager.get_subscriptions_to_peer(peer)) == 2
        real_delete = Subscription.delete
        calls = {"n": 0}

        def second_faults(self: Subscription) -> Any:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("delete failed")
            return real_delete(self)

        with (
            self._patches(manager),
            mock.patch.object(Subscription, "delete", second_faults),
        ):
            if use_async:
                asyncio.run(manager.sync_peer_async(peer))
            else:
                manager.sync_peer(peer)
        assert len(world.stored(peer)) == 1
        assert len(manager.get_subscriptions_to_peer(peer)) == 1


# ---------------------------------------------------------------------------
# Resume and the trust calls
# ---------------------------------------------------------------------------


class TestResumeAndTrustCalls:
    def test_a_subscriber_that_arrived_while_suspended_gets_the_resync(
        self, bare: World
    ) -> None:
        one = bare.a
        assert one.suspend_subscriptions("properties")
        _write(one, 1)  # fills the memo with []
        assert one.subs_list == []
        bare.trust("late")
        subid = bare.subscribe("late")
        sent: list[list[dict[str, Any]]] = []

        def record(
            _target: Any, _subtarget: Any, subs: Any = None, *_a: Any, **_k: Any
        ) -> int:
            sent.append(list(subs or []))
            return len(subs or [])

        with mock.patch.object(Actor, "_send_resync_callbacks", side_effect=record):
            assert one.resume_subscriptions("properties") == 1
        assert [s["subscriptionid"] for batch in sent for s in batch] == [subid]

    def test_an_approval_whose_peer_subscribes_back(self, bare: World) -> None:
        bare.trust("p", approved=False)
        one = bare.a
        assert one.get_subscriptions() == []
        made: list[str] = []

        def peer_answers(*_a: Any, **_k: Any) -> Any:
            made.append(bare.subscribe("p"))
            return mock.Mock(status_code=204, content=b"")

        with mock.patch("actingweb.actor.requests.post", side_effect=peer_answers):
            assert one.modify_trust_and_notify(
                relationship="friend", peerid="p", approved=True
            )
        assert len(made) == 1
        _write(one, 1)
        assert len(bare.diffs("p", made[0])) == 1

    def _peer_info(self, peer: str) -> dict[str, Any]:
        return {"last_response_code": 200, "data": {"id": peer, "type": "urn:test"}}

    def test_create_reciprocal_trust_approving_on_create(self, bare: World) -> None:
        bare.trust("p", approved=False)
        url = "https://p.example.test/p"
        one = bare.a
        assert one.get_subscriptions() == []
        made: list[str] = []

        def peer_answers(*_a: Any, **_k: Any) -> Any:
            made.append(bare.subscribe("p"))
            return mock.Mock(status_code=204, content=b"")

        with (
            mock.patch.object(
                Actor, "get_peer_info", return_value=self._peer_info("p")
            ),
            mock.patch("actingweb.actor.requests.post", side_effect=peer_answers),
        ):
            one.create_reciprocal_trust(
                url=url, secret=uuid.uuid4().hex, relationship="friend"
            )
        assert made
        _write(one, 1)
        assert len(bare.diffs("p", made[0])) == 1

    def test_create_reciprocal_trust_requesting(self, bare: World) -> None:
        one = bare.a
        assert one.get_subscriptions() == []
        made: list[str] = []

        def peer_subscribes_and_fails(*_a: Any, **_k: Any) -> Any:
            bare.trust("q")
            made.append(bare.subscribe("q"))
            raise OSError("no answer")

        with (
            mock.patch.object(
                Actor, "get_peer_info", return_value=self._peer_info("q")
            ),
            mock.patch(
                "actingweb.actor.requests.post", side_effect=peer_subscribes_and_fails
            ),
        ):
            one.create_reciprocal_trust(
                url="https://q.example.test/q",
                secret=uuid.uuid4().hex,
                relationship="friend",
            )
        assert made
        assert one.subs_list is None

    def test_create_reciprocal_trust_async_approving_on_create(
        self, bare: World
    ) -> None:
        bare.trust("p", approved=False)
        one = bare.a
        assert one.get_subscriptions() == []
        made: list[str] = []

        def peer_answers(*_a: Any, **_k: Any) -> Any:
            made.append(bare.subscribe("p"))
            return mock.Mock(status_code=204, content=b"")

        async def info(_self: Any, _url: str) -> dict[str, Any]:
            return self._peer_info("p")

        with (
            mock.patch.object(Actor, "get_peer_info_async", info),
            mock.patch("actingweb.actor.requests.post", side_effect=peer_answers),
        ):
            asyncio.run(
                one.create_reciprocal_trust_async(
                    url="https://p.example.test/p",
                    secret=uuid.uuid4().hex,
                    relationship="friend",
                )
            )
        assert made
        _write(one, 1)
        assert len(bare.diffs("p", made[0])) == 1

    def test_create_reciprocal_trust_async_requesting(self, bare: World) -> None:
        import httpx

        one = bare.a
        assert one.get_subscriptions() == []
        made: list[str] = []

        async def info(_self: Any, _url: str) -> dict[str, Any]:
            return self._peer_info("q")

        async def peer_subscribes_and_fails(*_a: Any, **_k: Any) -> Any:
            bare.trust("q2")
            made.append(bare.subscribe("q2"))
            raise httpx.ConnectError("no answer")

        with (
            mock.patch.object(Actor, "get_peer_info_async", info),
            mock.patch.object(
                httpx.AsyncClient, "post", side_effect=peer_subscribes_and_fails
            ),
        ):
            asyncio.run(
                one.create_reciprocal_trust_async(
                    url="https://q.example.test/q",
                    secret=uuid.uuid4().hex,
                    relationship="friend",
                )
            )
        assert made
        assert one.subs_list is None


# ---------------------------------------------------------------------------
# Deletion, purge and the create under an explicit id
# ---------------------------------------------------------------------------


def _suspended(cfg: Config, actor_id: str) -> list[Any]:
    return get_subscription_suspension(cfg, actor_id).get_all_suspended()


class TestDeletion:
    def test_delete_with_three_relationships_reads_the_list_twice(
        self, world: World
    ) -> None:
        with count_reads(world.config) as counts:
            assert world.a.delete(notify_peers=False)
        assert counts["subscription_list_fetch"] == 2

    def test_a_subscription_created_during_the_wipe_goes_with_its_diff(
        self, world: World
    ) -> None:
        last = world.peers[-1]
        real = Actor.delete_reciprocal_trust
        made: dict[str, str] = {}

        def then_subscribe(self: Actor, *a: Any, **k: Any) -> Any:
            if k.get("peerid") == last and not made:
                made["subid"] = world.subscribe(last)
                Subscription(
                    actor_id=world.id,
                    peerid=last,
                    subid=made["subid"],
                    callback=False,
                    config=world.config,
                ).add_diff(blob="{}")
            return real(self, *a, **k)

        with mock.patch.object(Actor, "delete_reciprocal_trust", then_subscribe):
            assert world.a.delete(notify_peers=False)
        assert made
        assert world.stored() == []
        assert world.diffs(last, made["subid"]) == []

    @pytest.mark.parametrize("how", ["delete", "purge"])
    def test_a_diff_without_a_subscription_row_goes(
        self, bare: World, how: str
    ) -> None:
        bare.trust("gone")
        orphan = Subscription(
            actor_id=bare.id,
            peerid="gone",
            subid="orphan-sub",
            callback=False,
            config=bare.config,
        )
        assert orphan.create(target="properties", granularity="high")
        assert orphan.add_diff(blob="{}")
        # The row goes, its diff stays: what a subscription created between
        # the pre-read and the wipe leaves.
        rows = subscription_module.get_subscription_list(bare.config)
        rows.fetch(actor_id=bare.id)
        rows.delete()
        assert bare.stored() == []
        assert bare.diffs("gone", "orphan-sub")
        if how == "delete":
            assert bare.a.delete(notify_peers=False)
        else:
            assert bare.a.purge_relationships()["confirmed"]
        assert bare.diffs("gone", "orphan-sub") == []

    def test_a_diff_delete_fault_stops_the_delete(self, bare: World) -> None:
        real = type(subscription_module.get_subscription_diff_list(bare.config))
        with (
            mock.patch.object(real, "delete", side_effect=DbError("diff delete")),
            pytest.raises(DbError),
        ):
            bare.a.delete(notify_peers=False)
        assert bare.fresh().id == bare.id

    @pytest.mark.parametrize("how", ["delete", "purge"])
    def test_a_recreated_id_is_not_suspended(self, bare: World, how: str) -> None:
        assert bare.a.suspend_subscriptions("properties", "y")
        if how == "delete":
            assert bare.a.delete(notify_peers=False)
            again = Actor(config=bare.config)
            assert again.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="pw",
                actor_id=bare.id,
            )
        else:
            assert bare.a.purge_relationships()["confirmed"]
            again = bare.fresh()
        assert _suspended(bare.config, bare.id) == []
        bare.trust("p")
        subid = bare.subscribe("p")
        again.register_diffs(
            target="properties", subtarget="y", blob=json.dumps({"v": 1})
        )
        assert len(bare.diffs("p", subid)) == 1

    def test_a_suspension_clean_up_fault_stops_and_a_retry_finishes(
        self, bare: World
    ) -> None:
        assert bare.a.suspend_subscriptions("properties")
        store_cls = type(get_subscription_suspension(bare.config, bare.id))
        with (
            mock.patch.object(store_cls, "delete_all", return_value=False),
            pytest.raises(DbError),
        ):
            bare.a.delete(notify_peers=False)
        assert bare.fresh().id == bare.id
        assert bare.a.delete(notify_peers=False)
        assert bare.fresh().id is None
        assert _suspended(bare.config, bare.id) == []

    def test_a_suspension_clean_up_fault_leaves_the_purge_unconfirmed(
        self, bare: World
    ) -> None:
        store_cls = type(get_subscription_suspension(bare.config, bare.id))
        with mock.patch.object(store_cls, "delete_all", return_value=False):
            assert bare.a.purge_relationships()["confirmed"] is False

    def test_purge_reads_the_list_twice(self, world: World) -> None:
        with count_reads(world.config) as counts:
            assert world.a.purge_relationships()["confirmed"]
        assert counts["subscription_list_fetch"] == 2


class TestCreateUnderAnExplicitId:
    def _leftover(self, cfg: Config, actor_id: str) -> None:
        assert get_subscription_suspension(cfg, actor_id).suspend("properties")

    def test_a_leftover_suspension_is_cleared(self) -> None:
        cfg = _config()
        actor_id = uuid.uuid4().hex
        self._leftover(cfg, actor_id)
        a = Actor(config=cfg)
        try:
            assert a.create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="pw",
                actor_id=actor_id,
            )
            assert _suspended(cfg, actor_id) == []
            assert not a.is_subscription_suspended("properties")
        finally:
            if Actor(actor_id, cfg).id:
                Actor(actor_id, cfg).delete(notify_peers=False)

    def test_a_clear_that_fails_fails_the_create(self) -> None:
        cfg = _config()
        actor_id = uuid.uuid4().hex
        self._leftover(cfg, actor_id)
        store_cls = type(get_subscription_suspension(cfg, actor_id))
        try:
            with (
                mock.patch.object(store_cls, "delete_all", return_value=False),
                pytest.raises(DbError),
            ):
                Actor(config=cfg).create(
                    url="https://test.example.com/",
                    creator=uuid_email(),
                    passphrase="pw",
                    actor_id=actor_id,
                )
            assert Actor(actor_id, cfg).id is None
        finally:
            get_subscription_suspension(cfg, actor_id).delete_all()

    def test_a_create_under_a_live_actors_id_leaves_its_suspensions(
        self, bare: World
    ) -> None:
        assert bare.a.suspend_subscriptions("properties")
        assert (
            Actor(config=bare.config).create(
                url="https://test.example.com/",
                creator=uuid_email(),
                passphrase="pw",
                actor_id=bare.id,
            )
            is False
        )
        assert _suspended(bare.config, bare.id) == [("properties", None)] or (
            _suspended(bare.config, bare.id) == [("properties", "")]
        )

    def test_a_generated_id_makes_no_suspension_call(self) -> None:
        cfg = _config()
        with mock.patch("actingweb.actor.get_subscription_suspension") as suspension:
            a = Actor(config=cfg)
            assert a.create(
                url="https://test.example.com/", creator=uuid_email(), passphrase="pw"
            )
        suspension.assert_not_called()
        a.delete(notify_peers=False)


# ---------------------------------------------------------------------------
# get_subscriptions_by_peer
# ---------------------------------------------------------------------------


class TestByPeer:
    def test_grouping_and_absent_peers(self, world: World) -> None:
        a, b, c = world.peers
        world.subscribe(a)
        world.subscribe(a, callback=True)
        world.subscribe(b)
        groups = ActorInterface(world.fresh()).subscriptions.get_subscriptions_by_peer()
        assert set(groups) == {a, b}
        assert isinstance(groups[a], PeerSubscriptions)
        assert len(groups[a].inbound) == 1 and len(groups[a].outbound) == 1
        assert len(groups[b].inbound) == 1 and groups[b].outbound == []
        assert c not in groups

    def test_a_loop_of_per_peer_accessors_fetches_once(self, world: World) -> None:
        tag = uuid.uuid4().hex[:6]
        peers = [f"loop-{i}-{tag}" for i in range(5)]
        for peer in peers:
            world.trust(peer)
            world.subscribe(peer)
        manager = ActorInterface(world.fresh()).subscriptions
        with count_reads(world.config) as counts:
            manager.get_subscriptions_by_peer()
            for peer in peers:
                manager.get_subscriptions_to_peer(peer)
                manager.get_subscriptions_from_peer(peer)
        assert counts["subscription_list_fetch"] == 1

    def test_a_view_sees_its_own_keys(self, world: World) -> None:
        a, b, c = world.peers
        for peer in (a, b, c):
            world.subscribe(peer)
        iface = ActorInterface(world.fresh())
        assert set(iface.as_peer(a).subscriptions.get_subscriptions_by_peer()) == {a}

        client_id = f"mcp_{uuid.uuid4().hex[:12]}"
        world.subscribe(client_id)
        # A new instance: the one above read its list before this row.
        view = ActorInterface(world.fresh()).as_client(client_id)
        with mock.patch.object(
            AuthContext, "permission_id", new_callable=mock.PropertyMock
        ) as permission_id:
            permission_id.return_value = b
            keys = set(view.subscriptions.get_subscriptions_by_peer())
        assert keys == {b, client_id}
        owner = ActorInterface(world.fresh()).subscriptions.get_subscriptions_by_peer()
        assert set(owner) == {a, b, c, client_id}
