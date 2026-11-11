"""Wire rows over the paths the peer-authorisation fix changes.

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 0: the
legitimate flows that run over ``/callbacks``, ``/subscriptions`` and the
permission callback, recorded on the wire harness (``_wire.py``) before any
handler changes, so each later phase shows it leaves them byte-identical or
re-records exactly the rows ``wire/rows.toml`` assigns to it.

Unless a row says otherwise: granularity ``high``, a grant of ``*``, a
target-level subscription, both topologies. A row's file is
``wire/<row>[.<topology>].json``; one file serves both backends.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import requests

from ._wire import Scenario, WireActor, check, wait_until

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]
SUBSCRIBER_TYPES = ["subscriber", "subscriber_adopted"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _put(actor: WireActor, name: str, value: Any) -> requests.Response:
    return requests.put(f"{actor.url}/properties/{name}", json=value, auth=actor.basic)


def _bearer(s: Scenario) -> dict[str, str]:
    return {"Authorization": f"Bearer {s.trust_secret}"}


def _subid(s: Scenario) -> str:
    """The id of B's subscription at A (one per pair)."""
    a, b = s.publisher, s.subscribers[0]
    rows = a.interface().subscriptions.get_subscriptions_from_peer(b.id)
    assert len(rows) == 1, rows
    return rows[0].subscription_id


def _replica(s: Scenario) -> dict[str, Any]:
    from actingweb.remote_storage import RemotePeerStore

    a, b = s.publisher, s.subscribers[0]
    store = RemotePeerStore(actor=b.interface(), peer_id=a.id, validate_peer_id=False)
    return {
        "scalars": {n: store.get_value(n) for n in store.list_all_scalars()},
        "lists": {n: store.get_list(n) for n in store.list_all_lists()},
    }


def _replica_settles(
    s: Scenario, condition: Callable[[dict[str, Any]], bool]
) -> Callable[[], None]:
    def settled() -> bool:
        # B may be rewriting the replica while this reads it: a list read
        # mid-rewrite raises IndexError (RemotePeerStore.get_list is not
        # isolated from a concurrent resync). Not settled yet, then.
        try:
            return condition(_replica(s))
        except IndexError:
            return False

    return lambda: wait_until(settled, timeout=15)


def _stored_permissions(s: Scenario) -> str:
    """B's stored copy of what A grants it, as text (empty when none)."""
    from actingweb.attribute import Attributes

    a, b = s.publisher, s.subscribers[0]
    bucket = Attributes(actor_id=b.id, bucket="_peer_permissions", config=b.host.config)
    row = bucket.get_attr(name=f"{b.id}:{a.id}") or {}
    return str(row.get("data", ""))


def _sub_url(s: Scenario, subid: str, *rest: str) -> str:
    a, b = s.publisher, s.subscribers[0]
    return "/".join([f"{a.url}/subscriptions/{b.id}/{subid}", *rest])


# ---------------------------------------------------------------------------
# Writes and their callbacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws1_target(wire_pair, topology):
    """WS1.target: ``PUT /properties/<p>`` with an object, a string, a number."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put object", lambda: _put(a, "color", {"shade": "red", "hex": "#f00"}))
    s.step("put string", lambda: _put(a, "color", "blue"))
    s.step("put number", lambda: _put(a, "count", 3))
    check("WS1.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl11_target(wire_pair, topology):
    """WL11.target: every list operation through the SDK (test thread, so
    each callback is a top-level request)."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher

    def lst():
        return a.interface().property_lists.notes

    s.step("append", lambda: lst().append({"id": "a", "text": "one"}))
    s.step("insert at the front", lambda: lst().insert(0, {"id": "b", "text": "two"}))
    s.step(
        "insert in the middle", lambda: lst().insert(1, {"id": "c", "text": "three"})
    )

    def update_by_index():
        lst()[0] = {"id": "b", "text": "two, again"}

    s.step("update by index", update_by_index)
    s.step(
        "update_where",
        lambda: lst().update_where("id", "c", {"id": "c", "text": "three, again"}),
    )

    def delete_by_index():
        del lst()[1]

    s.step("delete by index", delete_by_index)
    s.step("extend", lambda: lst().extend([{"id": "d"}, {"id": "e"}, {"id": "f"}]))
    s.step("pop()", lambda: lst().pop())
    s.step("pop(0)", lambda: lst().pop(0))
    s.step("remove_where", lambda: lst().remove_where("id", "d"))
    s.step("set_description", lambda: lst().set_description("wire notes"))
    s.step("clear", lambda: lst().clear())
    s.step("delete", lambda: lst().delete())
    check("WL11.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd6_low_granularity(wire_pair, topology):
    """WD6: granularity ``low``: the callback carries no data; B fetches the
    diff with its bearer and acknowledges it with ``PUT {"sequence": n}``."""
    s = wire_pair(topology, grant=["*"], granularity="low")
    a = s.publisher
    s.step("put", lambda: _put(a, "color", {"shade": "red"}))
    check("WD6", s.recording(), variant=topology)


@pytest.mark.parametrize("relationship", SUBSCRIBER_TYPES)
def test_wd6_subscriber(wire_pair, relationship):
    """WD6 in a pair of the consumer's type: B's acknowledgement is a PUT
    that only a GET row admits under ``subscriber``."""
    s = wire_pair(
        "same_host", relationship=relationship, grant=["allowed"], granularity="low"
    )
    a = s.publisher
    s.step("put", lambda: _put(a, "allowed", {"v": 1}))
    check(f"WD6.{relationship}", s.recording())


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd8_duplicate(wire_pair, topology):
    """WD8: the recorded callback of an SDK ``append`` posted again, with
    the same bearer: a duplicate."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    s.step("append", lambda: a.interface().property_lists.notes.append({"n": 1}))
    sent = [e for e in s.steps[-1]["wire"] if "/callbacks/subscriptions/" in e["path"]]
    assert len(sent) == 1, sent
    callback = sent[0]
    s.step(
        "post the same callback again",
        lambda: requests.post(
            f"{b.host.url}{callback['path']}",
            json=callback["request"],
            headers={"Authorization": callback["auth"]},
        ),
    )
    check("WD8", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd10_suspend_resume(wire_pair, topology):
    """WD10: SDK ``suspend("properties")``; two writes and a delete; ``resume``.
    The resync and B's baseline fetch."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("suspend", lambda: a.interface().subscriptions.suspend("properties"))
    s.step("put x", lambda: _put(a, "x", {"v": 1}))
    s.step("put y", lambda: _put(a, "y", {"v": 2}))
    s.step(
        "delete x",
        lambda: requests.delete(f"{a.url}/properties/x", auth=a.basic),
    )
    s.step(
        "resume",
        lambda: a.interface().subscriptions.resume("properties"),
        settle=_replica_settles(
            s, lambda r: r["scalars"].get("y") == {"v": 2} and "x" not in r["scalars"]
        ),
    )
    check("WD10", s.recording(), variant=topology)


def test_wd10_import(wire_pair):
    """WD10.import: the consumer's import, an asynchronous method on A's loop
    that suspends one subtarget, clears and refills a list, and resumes; the
    resync arrives after the method answers. Two hosts."""
    s = wire_pair("two_hosts", grant=["*"])
    a = s.publisher

    def seed():
        lst = a.interface().property_lists.memories
        lst.append({"text": "old one"})
        lst.append({"text": "old two"})
        return len(lst)

    s.step("seed two items (SDK, test thread)", seed)
    new_items = [{"text": "new one"}, {"text": "new two"}, {"text": "new three"}]
    s.step(
        "import (async method hook on the loop)",
        lambda: requests.post(
            f"{a.url}/methods/wire_import",
            json={"list": "memories", "items": new_items, "clear": True},
            auth=a.basic,
        ),
        settle=_replica_settles(s, lambda r: r["lists"].get("memories") == new_items),
    )
    check("WD10.import", s.recording())


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wd12_full_state_fallback(wire_pair, topology):
    """WD12: as WD10, with A's trust row for B lacking ``subscriptionresync``
    (freshly stamped, so no refresh) and B already holding a list."""
    from actingweb.trust import Trust

    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    s.step("append", lambda: a.interface().property_lists.notes.append({"n": 1}))

    # Setup, not a step: A's cached capabilities for B, without resync.
    trust = Trust(actor_id=a.id, peerid=b.id, config=a.host.config)
    row = trust.get() or {}
    supported = [
        o
        for o in (row.get("aw_supported") or "").split(",")
        if o.strip() and o.strip() != "subscriptionresync"
    ]
    assert trust.modify(
        aw_supported=",".join(supported),
        capabilities_fetched_at=datetime.now(UTC).isoformat(),
    )

    s.step("suspend", lambda: a.interface().subscriptions.suspend("properties"))
    s.step("put x", lambda: _put(a, "x", {"v": 1}))
    s.step("put y", lambda: _put(a, "y", {"v": 2}))
    s.step(
        "delete x",
        lambda: requests.delete(f"{a.url}/properties/x", auth=a.basic),
    )
    s.step(
        "resume",
        lambda: a.interface().subscriptions.resume("properties"),
        # Sent from the test thread and answered synchronously: what B does
        # with the fallback is nested in the callback, so nothing to wait for.
    )
    check("WD12", s.recording(), variant=topology)


# ---------------------------------------------------------------------------
# The queue, polled and cleared by the subscriber
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq1_poll_queue(wire_pair, topology):
    """WQ1: ``GET /subscriptions/<B>/<subid>`` as B after two writes."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put one", lambda: _put(a, "x", {"v": 1}))
    s.step("put two", lambda: _put(a, "x", {"v": 2}))
    subid = _subid(s)
    s.step("B polls", lambda: requests.get(_sub_url(s, subid), headers=_bearer(s)))
    check("WQ1", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq2_single_diff(wire_pair, topology):
    """WQ2: ``GET …/<subid>/<seq>`` as B, twice: one diff, consumed by the
    first GET (the specification forbids it; ``spec-1-5`` owns the change)."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("put", lambda: _put(a, "x", {"v": 1}))
    subid = _subid(s)
    for label in ("B fetches diff 1", "B fetches diff 1 again"):
        s.step(label, lambda: requests.get(_sub_url(s, subid, "1"), headers=_bearer(s)))
    check("WQ2", s.recording(), variant=topology)


def _wq3_steps(s: Scenario, prop: str) -> None:
    a = s.publisher
    for v in (1, 2, 3):
        s.step(f"put {v}", lambda v=v: _put(a, prop, {"v": v}))
    subid = _subid(s)
    s.step(
        "PUT sequence 1",
        lambda: requests.put(
            _sub_url(s, subid), json={"sequence": 1}, headers=_bearer(s)
        ),
    )
    s.step(
        "PUT sequence 0",
        lambda: requests.put(
            _sub_url(s, subid), json={"sequence": 0}, headers=_bearer(s)
        ),
    )
    s.step(
        "PUT without a sequence",
        lambda: requests.put(_sub_url(s, subid), json={}, headers=_bearer(s)),
    )
    s.step(
        "PUT text",
        lambda: requests.put(
            _sub_url(s, subid),
            data="not json",
            headers={**_bearer(s), "Content-Type": "text/plain"},
        ),
    )
    s.step(
        "PUT on an unknown subscription id",
        lambda: requests.put(
            _sub_url(s, "unknown-subscription"),
            json={"sequence": 1},
            headers=_bearer(s),
        ),
    )
    s.step(
        "GET ?_method=PUT&sequence=2",
        lambda: requests.get(
            _sub_url(s, subid),
            params={"_method": "PUT", "sequence": "2"},
            headers=_bearer(s),
        ),
    )


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wq3_clear(wire_pair, topology):
    """WQ3: B clears its queue at A in every shape the handler takes."""
    s = wire_pair(topology, grant=["*"])
    _wq3_steps(s, "x")
    check("WQ3", s.recording(), variant=topology)


@pytest.mark.parametrize("relationship", SUBSCRIBER_TYPES)
def test_wq3_subscriber(wire_pair, relationship):
    """WQ3 in a pair of the consumer's type: each clear is a PUT that only
    a GET row admits under ``subscriber``."""
    s = wire_pair("same_host", relationship=relationship, grant=["allowed"])
    _wq3_steps(s, "allowed")
    check(f"WQ3.{relationship}", s.recording())


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc1_subscribe_through_own_actor(wire_pair, topology):
    """WC1: ``POST /<B>/subscriptions`` as B's creator: B subscribes at A."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    s.step(
        "B's creator subscribes",
        lambda: requests.post(
            f"{b.url}/subscriptions",
            json={"peerid": a.id, "target": "properties", "granularity": "high"},
            auth=b.basic,
        ),
    )
    check("WC1", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc2_subscribe_direct(wire_pair, topology):
    """WC2: ``POST /<A>/subscriptions/<B>`` with B's bearer."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    s.step(
        "B subscribes directly at A",
        lambda: requests.post(
            f"{a.url}/subscriptions/{b.id}",
            json={"target": "properties", "granularity": "high"},
            headers=_bearer(s),
        ),
    )
    check("WC2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc3_subscriber_unsubscribes(wire_pair, topology):
    """WC3: ``DELETE /<B>/subscriptions/<A>/<subid>`` as B's creator; B's
    delete reaches A on the callback path."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    subid = _subid(s)
    s.step(
        "B's creator deletes its subscription",
        lambda: requests.delete(f"{b.url}/subscriptions/{a.id}/{subid}", auth=b.basic),
    )
    check("WC3", s.recording(), variant=topology)


def _wc4_step(s: Scenario) -> None:
    a, b = s.publisher, s.subscribers[0]
    subid = _subid(s)
    s.step(
        "A's creator deletes B's subscription",
        lambda: requests.delete(f"{a.url}/subscriptions/{b.id}/{subid}", auth=a.basic),
    )


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wc4_publisher_unsubscribes(wire_pair, topology):
    """WC4: ``DELETE /<A>/subscriptions/<B>/<subid>`` as A's creator; A's
    delete reaches B on B's subscription path."""
    s = wire_pair(topology, grant=["*"])
    _wc4_step(s)
    check("WC4", s.recording(), variant=topology)


@pytest.mark.parametrize("relationship", SUBSCRIBER_TYPES)
def test_wc4_subscriber(wire_pair, relationship):
    """WC4 in a pair of the consumer's type: A's delete to B is a DELETE
    that only a GET row admits under ``subscriber``."""
    s = wire_pair("same_host", relationship=relationship, grant=["allowed"])
    _wc4_step(s)
    check(f"WC4.{relationship}", s.recording())


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wp1_permission_callback(wire_pair, topology):
    """WP1: ``PUT /<A>/trust/<rel>/<B>/permissions`` with an exclusion: the
    permission callback and B's follow-up fetch."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    s.step("put shown", lambda: _put(a, "shown", {"v": 1}))
    s.step("put hidden", lambda: _put(a, "hidden", {"v": 1}))
    s.step(
        "A excludes hidden",
        lambda: requests.put(
            f"{a.url}/trust/{s.relationship}/{b.id}/permissions",
            json={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read"],
                    "excluded_patterns": ["hidden"],
                }
            },
            auth=a.basic,
        ),
        # The permission callback is sent off the request (fire-and-forget):
        # wait until B has stored the exclusion.
        settle=lambda: wait_until(lambda: "hidden" in _stored_permissions(s)),
    )
    check("WP1", s.recording(), variant=topology)
