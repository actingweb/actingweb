"""SDK calls a consumer makes between two actors, which no test made.

The release validation (``thoughts/plans/2026-11-15-3-16-release-validation.md``,
Phase 2) compared this suite with how a consumer application calls the
library and found calls that only a mock, one actor or a REST twin
exercised: the asynchronous subscribe and sync, the two unsubscribe
methods, the cached peer capabilities, a permission override stored
through the SDK, the by-handle list writes as a publisher, the replica
read through ``get_all_properties`` and ``AttributeListStore``, and
delivery with synchronous callbacks (the serverless shape). Each test here
makes the call as the consumer does, between two real actors, on whichever
backend the run uses; none is a recording.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ._wire import Scenario, wait_until
from .test_wire_peer_paths import _put, _replica, _subid

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]


def _rows(s: Scenario) -> tuple[list[Any], list[Any]]:
    """A's subscriptions from B, and B's subscriptions to A."""
    a, b = s.publisher, s.subscribers[0]
    return (
        a.interface().subscriptions.get_subscriptions_from_peer(b.id),
        b.interface().subscriptions.get_subscriptions_to_peer(a.id),
    )


def _follows(s: Scenario, condition: Any) -> None:
    def settled() -> bool:
        try:
            return bool(condition(_replica(s)))
        except IndexError:
            return False

    wait_until(settled, timeout=15)
    assert settled()


def test_subscribe_to_peer_async_subscribes_and_takes_the_baseline(wire_pair):
    s = wire_pair("two_hosts", grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    assert _put(a, "note", {"text": "before"}).status_code in (200, 204)

    url = asyncio.run(
        b.interface().subscriptions.subscribe_to_peer_async(
            peer_id=a.id, target="properties", granularity="high"
        )
    )

    # The call returns the subscription's URL at the publisher.
    assert url and url.startswith(f"{a.url}/subscriptions/{b.id}/")
    subid = url.rsplit("/", 1)[1]
    at_a, at_b = _rows(s)
    assert [r.subscription_id for r in at_a] == [subid]
    assert [r.subscription_id for r in at_b] == [subid]
    # The baseline, then a later write through the new subscription.
    _follows(s, lambda r: (r["scalars"].get("note") or {}).get("text") == "before")
    assert _put(a, "note", {"text": "after"}).status_code in (200, 204)
    _follows(s, lambda r: (r["scalars"].get("note") or {}).get("text") == "after")


def test_unsubscribe_from_peer_removes_every_subscription_on_both_sides(wire_pair):
    s = wire_pair("two_hosts", grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    wire_pair.subscribe(s, b, subtarget="notes")
    assert len(_rows(s)[0]) == 2

    assert b.interface().subscriptions.unsubscribe_from_peer(a.id) is True

    wait_until(lambda: not _rows(s)[0], timeout=15)
    assert _rows(s) == ([], [])


def test_revoke_peer_subscription_removes_it_on_both_sides(wire_pair):
    s = wire_pair("two_hosts", grant=["*"])
    a, b = s.publisher, s.subscribers[0]

    assert a.interface().subscriptions.revoke_peer_subscription(b.id, _subid(s)) is True

    wait_until(lambda: not _rows(s)[1], timeout=15)
    assert _rows(s) == ([], [])


def test_sync_peer_async_pulls_a_none_subscription(wire_pair):
    s = wire_pair("two_hosts", grant=["*"], granularity="none")
    a, b = s.publisher, s.subscribers[0]
    assert _put(a, "note", {"text": "pulled"}).status_code in (200, 204)

    result = asyncio.run(b.interface().subscriptions.sync_peer_async(a.id))

    assert result.success is True, result
    assert result.subscriptions_synced == 1
    assert result.error is None
    assert (_replica(s)["scalars"].get("note") or {}).get("text") == "pulled"


def test_cached_peer_capabilities_name_the_peers_methods_and_actions(wire_pair):
    from actingweb.peer_capabilities import get_cached_capabilities_store

    s = wire_pair("two_hosts", grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    # B's side of the cache is filled by its own sync, as a consumer's is.
    asyncio.run(b.interface().subscriptions.sync_peer_async(a.id))

    through_manager = b.interface().trust.get_peer_capabilities(a.id)
    through_store = get_cached_capabilities_store(b.host.config).get_capabilities(
        b.id, a.id
    )

    assert through_manager is not None
    assert through_store is not None
    assert "wire_ping" in {m.name for m in through_manager.methods}
    # Not a comparison with the manager's copy: both read the same row.
    assert "wire_ping" in {m.name for m in through_store.methods}
    assert through_store.fetched_at


def test_store_permissions_async_reaches_the_peers_copy(wire_pair):
    from actingweb.peer_permissions import get_peer_permission_store
    from actingweb.trust_permissions import (
        TrustPermissions,
        get_trust_permission_store,
    )

    s = wire_pair("two_hosts", grant=None, subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    override = TrustPermissions(
        actor_id=a.id,
        peer_id=b.id,
        trust_type="friend",
        properties={
            "patterns": ["memory_notes"],
            "operations": ["read"],
            "excluded_patterns": [],
        },
    )

    async def store_on_a_loop_that_lives() -> bool:
        # The peer is told by a background task: a consumer calls this from
        # a request handler whose loop outlives the call, so the test lets
        # the task finish before its own loop closes.
        result = await get_trust_permission_store(
            a.host.config
        ).store_permissions_async(override)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending)
        return result

    stored = asyncio.run(store_on_a_loop_that_lives())

    assert stored is True

    def copy() -> Any:
        return get_peer_permission_store(b.host.config).get_permissions(b.id, a.id)

    wait_until(lambda: copy() is not None, timeout=15)
    received = copy()
    assert received is not None
    # The copy is the grant as it holds (the override on the trust type).
    assert "memory_notes" in (received.properties or {}).get("patterns", [])


def test_store_permissions_async_tells_the_peer_before_returning_when_sync(
    wire_pair,
):
    """With ``with_sync_callbacks()`` (a function platform freezes after the
    response) the peer is told before the call returns: a background task
    would be lost with the loop. That it stays a background task without
    the setting is ``tests/test_trust_permissions_unit.py``."""
    from actingweb.peer_permissions import get_peer_permission_store
    from actingweb.trust_permissions import (
        TrustPermissions,
        get_trust_permission_store,
    )

    s = wire_pair("two_hosts", grant=None, subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    override = TrustPermissions(
        actor_id=a.id,
        peer_id=b.id,
        trust_type="friend",
        properties={
            "patterns": ["memory_notes"],
            "operations": ["read"],
            "excluded_patterns": [],
        },
    )
    config = a.host.config
    before = config.sync_subscription_callbacks
    config.sync_subscription_callbacks = True
    try:
        # The loop ends with the call: nothing left on it can run afterwards.
        stored = asyncio.run(
            get_trust_permission_store(config).store_permissions_async(override)
        )
    finally:
        config.sync_subscription_callbacks = before

    assert stored is True
    received = get_peer_permission_store(b.host.config).get_permissions(b.id, a.id)
    assert received is not None
    assert "memory_notes" in (received.properties or {}).get("patterns", [])


def test_by_handle_list_writes_reach_the_replica(wire_pair):
    s = wire_pair("two_hosts", grant=["*"])
    a = s.publisher

    def lst() -> Any:
        return a.interface().property_lists.notes

    lst().append({"id": "a", "text": "one"})
    lst().append({"id": "b", "text": "two"})
    _follows(s, lambda r: len(r["lists"].get("notes") or []) == 2)

    first = lst().items_with_handles()[0][0]
    lst().update_by_handle(first, {"id": "a", "text": "one, again"})
    _follows(
        s,
        lambda r: (
            (r["lists"].get("notes") or [{}])[0] == {"id": "a", "text": "one, again"}
        ),
    )

    first = lst().items_with_handles()[0][0]
    lst().delete_by_handle(first)
    _follows(s, lambda r: r["lists"].get("notes") == [{"id": "b", "text": "two"}])


def test_a_replica_read_through_the_stores_a_consumer_uses(wire_pair):
    from actingweb.attribute_list_store import AttributeListStore
    from actingweb.remote_storage import RemotePeerStore

    s = wire_pair("two_hosts", grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    assert _put(a, "note", {"text": "scalar"}).status_code in (200, 204)
    a.interface().property_lists.notes.extend([{"n": 1}, {"n": 2}])
    _follows(
        s, lambda r: len(r["lists"].get("notes") or []) == 2 and "note" in r["scalars"]
    )

    store = RemotePeerStore(actor=b.interface(), peer_id=a.id)
    everything = store.get_all_properties()
    lists = AttributeListStore(actor_id=b.id, bucket=store.bucket, config=b.host.config)

    assert everything["notes"]["type"] == "list"
    assert everything["note"]["type"] == "scalar"
    assert lists.exists("notes")
    assert list(lists.notes) == [{"n": 1}, {"n": 2}]
    assert store.get_list("notes") == [{"n": 1}, {"n": 2}]


def test_the_accessors_a_consumer_reads_after_pairing(wire_pair):
    from actingweb.permission_evaluator import check_property_access

    s = wire_pair("two_hosts", grant=["*"])
    a, b = s.publisher, s.subscribers[0]

    relationships = a.interface().trust.relationships
    outbound = b.interface().subscriptions.outbound_subscriptions

    assert [r.peer_id for r in relationships] == [b.id]
    assert relationships[0].approved and relationships[0].peer_approved
    assert [sub.peer_id for sub in outbound] == [a.id]
    assert check_property_access(a.host.config, a.id, b.id, "notes", "read")
    # ``*`` is granted, and ``friend`` still excludes ``private/*``.
    assert not check_property_access(
        a.host.config, a.id, b.id, "private/secret", "read"
    )
    # The attribute form of a property write publishes like the others.
    a.interface().properties.displayname = "A's name"
    _follows(s, lambda r: "displayname" in r["scalars"])


def test_synchronous_callbacks_deliver_before_the_write_returns(wire_pair):
    """The serverless shape (``with_sync_callbacks()``): a write made on a
    running event loop (an async route) delivers its callback before it
    returns. Without the setting the same write schedules the callback on
    the loop, so right after it the subscriber has nothing yet."""
    s = wire_pair("two_hosts", grant=["*"])
    a = s.publisher
    config = a.host.config

    async def append_and_look(value: int) -> Any:
        # No await between the write and the read: a scheduled callback
        # cannot have run yet.
        a.interface().property_lists.notes.append({"n": value})
        seen = _replica(s)["lists"].get("notes")
        # Let a scheduled callback finish before the loop closes (a loop that
        # ends first cancels it: the serverless hazard the setting is for).
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*others)
        return seen

    before = config.sync_subscription_callbacks
    try:
        config.sync_subscription_callbacks = False
        scheduled = asyncio.run(append_and_look(1))
        _follows(s, lambda r: r["lists"].get("notes") == [{"n": 1}])
        config.sync_subscription_callbacks = True
        delivered = asyncio.run(append_and_look(2))
    finally:
        config.sync_subscription_callbacks = before

    assert scheduled in (None, [])
    assert delivered == [{"n": 1}, {"n": 2}]
