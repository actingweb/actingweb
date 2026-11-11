"""Wire rows: how a diff is delivered, held, resynced and fanned out.

``thoughts/plans/2026-11-06-subscription-wire-baseline.md``, Phase 1 (rows
``WD2`` to ``WD20``; ``WD6``, ``WD8``, ``WD10``, ``WD12`` are the security
plan's). Each row records today's behaviour, right or wrong;
``wire/rows.toml`` says what is known to be wrong and which later plan phase
may change the recording.

Unless a row says otherwise: a ``friend`` pair with a grant of ``*``,
granularity ``high``, a target-level subscription, both topologies.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
import requests

from ._wire import Scenario, WireActor, check
from .test_wire_peer_paths import (
    _bearer,
    _put,
    _replica,
    _replica_settles,
    _sub_url,
    _subid,
)

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]
EXCLUDING_DENIED = {
    "patterns": ["*"],
    "operations": ["read"],
    "excluded_patterns": ["denied"],
}


def _lst(a: WireActor, name: str = "notes") -> Any:
    return getattr(a.interface().property_lists, name)


def _stored_diffs(s: Scenario) -> list[dict[str, Any]]:
    """A's queued diffs for B's one subscription, as the store returns them."""
    from actingweb.subscription import Subscription

    a, b = s.publisher, s.subscribers[0]
    sub = Subscription(
        actor_id=a.id, peerid=b.id, subid=_subid(s), config=a.host.config
    )
    return sub.get_diffs() or []


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd2_timestamp_formats(wire_pair, topology):
    """WD2: one write; B polls the queue, then fetches the diff by sequence.
    The recording keeps each timestamp's format class."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    subid = _subid(s)
    s.step("B polls", lambda: requests.get(_sub_url(s, subid), headers=_bearer(s)))
    s.step(
        "B fetches diff 1",
        lambda: requests.get(_sub_url(s, subid, "1"), headers=_bearer(s)),
    )
    check("WD2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd3_two_writes_a_second_apart(wire_pair, topology):
    """WD3: two writes a second apart. One recording for both backends; the
    stored timestamps are asserted per backend (DynamoDB stamps every diff
    with one value, PostgreSQL each with its own)."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put one", lambda: _put(a, "x", {"v": 1}))
    time.sleep(1.1)
    s.step("put two", lambda: _put(a, "x", {"v": 2}))
    stamps = [d.get("timestamp") for d in _stored_diffs(s)]
    assert len(stamps) == 2, stamps
    if os.environ.get("DATABASE_BACKEND", "dynamodb") == "postgresql":
        # A difference spec-1-5:3 owns: PostgreSQL stamps each diff.
        assert stamps[0] != stamps[1], stamps
    else:
        # A difference spec-1-5:3 owns: DynamoDB's default is evaluated once,
        # at import, so every diff carries the same value.
        assert stamps[0] == stamps[1], stamps
    check("WD3", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd5_async_append(wire_pair, topology):
    """WD5: an SDK ``append`` on a running event loop (the test's own): the
    call returns before the callback is answered; the replica holds the item
    once the loop's pending tasks have run."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher

    async def append_on_the_loop() -> dict[str, Any]:
        _lst(a).append({"id": "a"})
        return {"replica_at_return": _replica(s)["lists"].get("notes")}

    s.step("append (SDK on a running loop)", append_on_the_loop)
    assert _replica(s)["lists"].get("notes") == [{"id": "a"}]
    check("WD5", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd7_granularity_none(wire_pair, topology):
    """WD7: granularity ``none``: a write, then the subscriber's SDK
    ``sync_peer``."""
    s = wire_pair(topology, grant=["*"], granularity="none")
    a, b = s.publisher, s.subscribers[0]
    s.step("put", lambda: _put(a, "x", {"v": 1}))

    def sync() -> Any:
        result = b.interface().subscriptions.sync_peer(a.id)
        return {
            "success": result.success,
            "subscriptions_synced": result.subscriptions_synced,
            "total_diffs_processed": result.total_diffs_processed,
            "error": result.error,
        }

    s.step("B syncs (SDK)", sync)
    check("WD7", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd9_gap_resync(wire_pair, topology):
    """WD9: a grant excluding ``denied``: a write to ``denied``, one to
    ``allowed``, a wait past the wire apps' 2 s gap timeout, a third write."""
    s = wire_pair(topology, grant=EXCLUDING_DENIED)
    a = s.publisher
    s.step("put denied", lambda: _put(a, "denied", {"v": 1}))
    s.step("put allowed", lambda: _put(a, "allowed", {"v": 2}))
    time.sleep(2.5)
    s.step("put allowed again", lambda: _put(a, "allowed", {"v": 3}))
    check("WD9", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd11_resume_none(wire_pair, topology):
    """WD11: granularity ``none``: SDK suspend, a write, resume."""
    s = wire_pair(topology, grant=["*"], granularity="none")
    a = s.publisher
    s.step("suspend", lambda: a.interface().subscriptions.suspend("properties"))
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    s.step("resume", lambda: a.interface().subscriptions.resume("properties"))
    check("WD11", s.recording(), variant=topology)


def test_wd13_two_subscribers_on_the_second_host(wire_pair):
    """WD13: B and C on the second host, both subscribed; one write."""
    s = wire_pair("two_hosts", grant=["*"])
    wire_pair.add_subscriber(s, "C", host="peer", grant=["*"])
    s.sort_callbacks = True
    a = s.publisher
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    check("WD13", s.recording())


@pytest.mark.parametrize("granularity", ["high", "low"])
def test_wd14_five_subscribers_on_the_publishers_host(wire_pair, granularity):
    """WD14: five subscribers on A's own host; one REST write."""
    s = wire_pair("same_host", grant=["*"], granularity=granularity)
    for name in ("C", "D", "E", "F"):
        wire_pair.add_subscriber(s, name, grant=["*"], granularity=granularity)
    s.sort_callbacks = True
    a = s.publisher
    s.step(
        "put",
        lambda: _put(a, "x", {"v": 1}),
        settle=lambda: _all_hold(s, "x", {"v": 1}),
    )
    check(f"WD14.{granularity}", s.recording())


def _all_hold(s: Scenario, name: str, value: Any) -> None:
    from actingweb.remote_storage import RemotePeerStore

    from ._wire import wait_until

    def held() -> bool:
        for sub in s.subscribers:
            store = RemotePeerStore(
                actor=sub.interface(), peer_id=s.publisher.id, validate_peer_id=False
            )
            if store.get_value(name) != value:
                return False
        return True

    wait_until(held, timeout=15)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd15_target_and_subtarget(wire_pair, topology):
    """WD15: B subscribed to the target and to the subtarget ``notes``; an
    SDK ``append``."""
    s = wire_pair(topology, grant=["*"])
    wire_pair.subscribe(s, s.subscribers[0], subtarget="notes")
    s.sort_callbacks = True
    a = s.publisher
    s.step("append (SDK)", lambda: _lst(a).append({"id": "a"}))
    check("WD15", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd16_callback_row_removed(wire_pair, topology):
    """WD16: B's own subscription row removed through the SDK
    (``delete_subscription(callback=True)``); two writes at A."""
    from actingweb.actor import Actor

    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    subid = _subid(s)

    def remove() -> Any:
        core = Actor(config=b.host.config)
        core.get(actor_id=b.id)
        return core.delete_subscription(peerid=a.id, subid=subid, callback=True)

    s.step("B removes its callback row (SDK)", remove)
    s.step("put again", lambda: _put(a, "x", {"v": 2}))
    s.step("put once more", lambda: _put(a, "x", {"v": 3}))
    check("WD16", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd17_unreachable_subscriber(wire_pair, topology):
    """WD17: A's trust row for B points at a port nothing listens on; a write."""
    from actingweb.trust import Trust

    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    unbound = f"http://127.0.0.1:9/{b.id}"
    assert Trust(actor_id=a.id, peerid=b.id, config=a.host.config).modify(
        baseuri=unbound
    )
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    check("WD17", s.recording(), variant=topology)


def test_wd18_async_method_on_the_loop(wire_pair):
    """WD18: ``POST /methods/wire_import`` at A with ``suspend: false``: an
    asynchronous method on the server's loop appends through the interface.
    Two hosts."""
    s = wire_pair("two_hosts", grant=["*"])
    a = s.publisher
    s.step(
        "method appends (async, server loop)",
        lambda: requests.post(
            f"{a.url}/methods/wire_import",
            json={"list": "notes", "items": [{"id": "a"}], "suspend": False},
            auth=a.basic,
        ),
        settle=_replica_settles(s, lambda r: r["lists"].get("notes") == [{"id": "a"}]),
    )
    check("WD18", s.recording())


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd19_held_callbacks(wire_pair, topology):
    """WD19: callbacks posted to B by hand with A's bearer, sequences 2 to 7
    (1 never arrives): one more than ``max_pending`` (5)."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    subid = _subid(s)

    def post(sequence: int) -> requests.Response:
        return requests.post(
            f"{b.url}/callbacks/subscriptions/{a.id}/{subid}",
            json={
                "id": a.id,
                "subscriptionid": subid,
                "target": "properties",
                "granularity": "high",
                "sequence": sequence,
                "timestamp": "2026-11-11 10:00:00.000000",
                "data": {"x": {"v": sequence}},
            },
            headers=_bearer(s),
        )

    for sequence in range(2, 8):
        s.step(f"post sequence {sequence}", lambda n=sequence: post(n))
    check("WD19", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd20_subscribe_with_data(wire_pair, topology):
    """WD20: A holds a property and a list; B's creator subscribes."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    assert _put(a, "color", {"shade": "red"}).status_code == 204
    _lst(a).append({"id": "a"})
    s.step(
        "B's creator subscribes",
        lambda: requests.post(
            f"{b.url}/subscriptions",
            json={"peerid": a.id, "target": "properties", "granularity": "high"},
            auth=b.basic,
        ),
    )
    check("WD20", s.recording(), variant=topology)
