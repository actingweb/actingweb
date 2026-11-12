"""Wire rows: the queue, and the life of a subscription.

``thoughts/plans/2026-11-06-subscription-wire-baseline.md``, Phase 1 (rows
``WQ4`` to ``WQ6``, ``WC5`` to ``WC7``, ``WM1``; ``WQ1`` to ``WQ3`` and
``WC1`` to ``WC4`` are the security plan's, and ``WC4``'s recording already
holds the ``subscription_deleted`` hooks ``WC8`` was to add). Each row
records today's behaviour, right or wrong; ``wire/rows.toml`` says what is
known to be wrong and which later plan phase may change the recording.

Unless a row says otherwise: a ``friend`` pair with a grant of ``*``,
granularity ``high``, a target-level subscription, both topologies.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ._wire import Scenario, WireActor, check
from .test_wire_peer_paths import _bearer, _put, _sub_url, _subid

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]


def _get(actor: WireActor, path: str, **params: str) -> requests.Response:
    return requests.get(f"{actor.url}/{path}", params=params, auth=actor.basic)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq4_listings(wire_pair, topology):
    """WQ4: ``GET /subscriptions``, ``?peerid=`` and ``?target=`` as each
    actor's creator."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    for actor, peer in ((a, b), (b, a)):
        s.step(f"{actor.name} lists", lambda x=actor: _get(x, "subscriptions"))
        s.step(
            f"{actor.name} lists ?peerid=",
            lambda x=actor, p=peer: _get(x, "subscriptions", peerid=p.id),
        )
        s.step(
            f"{actor.name} lists ?target=",
            lambda x=actor: _get(x, "subscriptions", target="properties"),
        )
    check("WQ4", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq5_granularity_medium(wire_pair, topology):
    """WQ5: a subscription with granularity ``medium``; a write."""
    s = wire_pair(topology, grant=["*"], granularity="medium")
    a = s.publisher
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    check("WQ5", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq6_null_sequence(wire_pair, topology):
    """WQ6: B clears its queue with ``{"sequence": null}``."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    subid = _subid(s)
    s.step(
        "PUT sequence null",
        lambda: requests.put(
            _sub_url(s, subid), json={"sequence": None}, headers=_bearer(s)
        ),
    )
    check("WQ6", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc5_trust_deleted(wire_pair, topology):
    """WC5: ``DELETE /<A>/trust/friend/<B>`` as A's creator, with a queued
    diff and B's replica."""
    s = wire_pair(topology, grant=["*"])
    s.snapshot_stores = True
    a, b = s.publisher, s.subscribers[0]
    assert _put(a, "x", {"v": 1}).status_code == 204
    s.step(
        "A's creator deletes the trust",
        lambda: requests.delete(f"{a.url}/trust/{s.relationship}/{b.id}", auth=a.basic),
    )
    check("WC5", s.recording(), variant=topology)


def _wc6_setup(s: Scenario) -> None:
    """A queued diff, B's replica and a suspended target at A."""
    a = s.publisher
    assert _put(a, "x", {"v": 1}).status_code == 204
    assert a.interface().subscriptions.suspend("properties", "y")


def _suspensions(a: WireActor) -> list[Any]:
    from actingweb.db import get_subscription_suspension

    store = get_subscription_suspension(a.host.config, a.id)
    return sorted([list(t) for t in store.get_all_suspended()])


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc6_publisher_deleted(wire_pair, topology):
    """WC6: A deleted over REST by its creator, with a subscriber, a queued
    diff and a suspended subtarget."""
    s = wire_pair(topology, grant=["*"])
    s.snapshot_stores = True
    a = s.publisher
    _wc6_setup(s)
    wire_pair.deleted(a)
    s.extra_snapshot = lambda: {"A.suspensions": _suspensions(a)}
    s.step(
        "A's creator deletes A",
        lambda: requests.delete(f"{a.url}", auth=a.basic),
    )
    check("WC6", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc7_publisher_recreated(wire_pair, topology):
    """WC7: after WC6 (setup), A created again under its id through the SDK;
    a write through the SDK."""
    from actingweb.actor import Actor
    from actingweb.interface.actor_interface import ActorInterface

    s = wire_pair(topology, grant=["*"])
    s.snapshot_stores = True
    a = s.publisher
    _wc6_setup(s)
    response = requests.delete(f"{a.url}", auth=a.basic)
    assert response.status_code == 204, response.text
    s.extra_snapshot = lambda: {"A.suspensions": _suspensions(a)}
    core = Actor(config=a.host.config)

    def recreate() -> bool:
        return core.create(
            url=a.host.url, creator=a.creator, passphrase=a.passphrase, actor_id=a.id
        )

    def write() -> None:
        ActorInterface(core).properties["x"] = {"v": 2}

    s.step("A created again under its id (SDK)", recreate)
    s.step("put (SDK)", write)
    check("WC7", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wm1_memo(wire_pair, topology):
    """WM1: one ``Actor`` instance of A writes (its subscription memo holds
    B), B2 subscribes over REST, the same instance writes again."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    b2 = wire_pair.add_subscriber(
        s, "B2", host="app" if topology == "same_host" else "peer", subscribe=False
    )
    one = a.interface()

    def write(value: int) -> None:
        one.properties["x"] = {"v": value}

    s.step("write through one instance (SDK)", lambda: write(1))
    memo = one.core_actor.subs_list
    assert memo and [m["peerid"] for m in memo] == [s.subscribers[0].id], memo
    s.step(
        "B2 subscribes",
        lambda: requests.post(
            f"{b2.url}/subscriptions",
            json={"peerid": a.id, "target": "properties", "granularity": "high"},
            auth=b2.basic,
        ),
    )
    s.step("write through the same instance (SDK)", lambda: write(2))
    check("WM1", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wm2_empty_memo(wire_pair: Any, topology: str) -> None:
    """WM2: one ``Actor`` instance of A writes with no subscriber (its memo
    becomes ``[]``, asserted); B subscribes over REST; the same instance
    writes again; then a second instance writes."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    one = a.interface()

    def write(actor: Any, value: int) -> None:
        actor.properties["x"] = {"v": value}

    s.step("write through one instance (SDK)", lambda: write(one, 1))
    assert one.core_actor.subs_list == [], one.core_actor.subs_list
    s.step("B subscribes", lambda: wire_pair.subscribe(s, b))
    s.step("write through the same instance (SDK)", lambda: write(one, 2))
    s.step("write through a second instance (SDK)", lambda: write(a.interface(), 3))
    check("WM2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wm3_recreated_publisher_sends(wire_pair: Any, topology: str) -> None:
    """WM3: WC6's setup and delete, A created again under its id through the
    SDK, a new subscriber B2 (set up, not recorded), a write of ``y`` (the
    target that was suspended)."""
    from actingweb.actor import Actor

    s = wire_pair(topology, grant=["*"])
    s.snapshot_stores = True
    a = s.publisher
    _wc6_setup(s)
    response = requests.delete(f"{a.url}", auth=a.basic)
    assert response.status_code == 204, response.text
    s.extra_snapshot = lambda: {"A.suspensions": _suspensions(a)}
    core = Actor(config=a.host.config)
    assert core.create(
        url=a.host.url, creator=a.creator, passphrase=a.passphrase, actor_id=a.id
    )
    assert core.get_trust_relationships() == []
    assert Actor(a.id, a.host.config).get_subscriptions() == []
    # Set up, not recorded (as every added peer is): B2 trusts the new A,
    # both approve, A grants, B2 subscribes.
    wire_pair.add_subscriber(s, "B2", host="app" if topology == "same_host" else "peer")

    def write() -> None:
        a.interface().properties["y"] = {"v": 1}

    s.step("put y (SDK)", write)
    check("WM3", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wm4_subscriber_during_suspension(wire_pair: Any, topology: str) -> None:
    """WM4: one instance of A suspends ``properties`` and writes (its memo
    becomes ``[]``); B subscribes over REST; the same instance resumes."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    one = a.interface()

    def suspend_and_write() -> None:
        assert one.subscriptions.suspend("properties")
        one.properties["x"] = {"v": 1}

    s.step("suspend and write through one instance (SDK)", suspend_and_write)
    assert one.core_actor.subs_list == [], one.core_actor.subs_list
    s.step("B subscribes", lambda: wire_pair.subscribe(s, b))
    s.step(
        "resume through the same instance (SDK)",
        lambda: one.subscriptions.resume("properties"),
    )
    check("WM4", s.recording(), variant=topology)
