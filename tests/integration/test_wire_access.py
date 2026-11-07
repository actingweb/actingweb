"""Wire rows: who may reach ``/callbacks`` (the peer-authorisation fix).

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 1, rows
``WA1`` to ``WA11``, ``WA15`` and ``WA17``. Recorded with the fix in place;
each scenario was also run once on the tree before the fix and its outcome
written into the plan's verification document.

A is the publisher and B the subscriber, as in every wire row; the requests
here go to B, which receives callbacks. C is a third actor with an approved
``friend`` trust to B, S one of the consumer's ``subscriber`` type, D one
with an ``admin`` trust and E one whose trust B has not approved.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests

from ._wire import Scenario, check

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]
RESERVED = ["permissions", "subscription", "subscriptions", "www", "resource_x"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subid(s: Scenario) -> str:
    a, b = s.publisher, s.subscribers[0]
    rows = a.interface().subscriptions.get_subscriptions_from_peer(b.id)
    assert len(rows) == 1, rows
    return rows[0].subscription_id


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _diff_body(s: Scenario, subid: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": s.publisher.id,
        "subscriptionid": subid,
        "target": "properties",
        "sequence": 1,
        "granularity": "high",
        "timestamp": _now(),
        "data": {"planted": {"v": 1}},
        **extra,
    }


def _permission_body(s: Scenario, excluded: str, timestamp: str) -> dict[str, Any]:
    return {
        "id": s.publisher.id,
        "target": "permissions",
        "type": "permission",
        "timestamp": timestamp,
        "data": {
            "properties": {
                "patterns": ["*"],
                "operations": ["read"],
                "excluded_patterns": [excluded],
            }
        },
    }


def _post(url: str, body: Any, headers: dict[str, str] | None = None, auth=None):
    return lambda: requests.post(url, json=body, headers=headers or {}, auth=auth)


def _stored_permission_row(s: Scenario, peer_id: str) -> dict[str, Any] | None:
    """B's stored copy of what ``peer_id`` grants it, decoded, or None."""
    from actingweb.attribute import Attributes
    from actingweb.constants import PEER_PERMISSIONS_BUCKET

    b = s.subscribers[0]
    bucket = Attributes(
        actor_id=b.id, bucket=PEER_PERMISSIONS_BUCKET, config=b.host.config
    )
    row = bucket.get_attr(name=f"{b.id}:{peer_id}")
    if not row:
        return None
    data = row.get("data")
    return json.loads(data) if isinstance(data, str) else data


def _probe(s: Scenario, label: str, probe: Callable[[], Any]) -> None:
    """A step with no request: what a probe reads, recorded as its result."""
    s.step(label, probe)


def _urls(s: Scenario, subid: str) -> tuple[str, str]:
    a, b = s.publisher, s.subscribers[0]
    return (
        f"{b.url}/callbacks/subscriptions/{a.id}/{subid}",
        f"{b.url}/callbacks/permissions/{a.id}",
    )


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa1_unauthenticated_subscription_callback(wire_pair, topology):
    """WA1: no credentials, a subscription callback for B's subscription and
    for an unknown id."""
    s = wire_pair(topology, grant=["*"])
    subid = _subid(s)
    cb_url, _ = _urls(s, subid)
    s.step("for B's subscription", _post(cb_url, _diff_body(s, subid)))
    unknown = cb_url.rsplit("/", 1)[0] + "/unknown-subscription"
    s.step(
        "for an unknown id",
        _post(unknown, _diff_body(s, "unknown-subscription")),
    )
    check("WA1", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa2_unauthenticated_permission_callback(wire_pair, topology):
    """WA2: no credentials, a permission callback for a peer with a trust (A)
    and for one without (X)."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    x_id = uuid.uuid4().hex
    s.name(x_id, "X")
    _, perm_url = _urls(s, _subid(s))
    s.step("for A", _post(perm_url, _permission_body(s, "planted", _now())))
    s.step(
        "for X",
        _post(
            f"{b.url}/callbacks/permissions/{x_id}",
            _permission_body(s, "planted", _now()),
        ),
    )
    _probe(s, "B holds a row for X", lambda: _stored_permission_row(s, x_id))
    check("WA2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa3_unauthenticated_generic_callback(wire_pair, topology):
    """WA3: no credentials, every method on ``/callbacks/<name>``."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    url = f"{b.url}/callbacks/wire_ping"
    for method in ("GET", "POST", "PUT", "DELETE"):
        s.step(
            method,
            lambda method=method: requests.request(method, url, json={"x": 1}),
        )
    check("WA3", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa4_unknown_bearer(wire_pair, topology):
    """WA4: a bearer that is nobody's, on the three kinds of callback."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    nobody = f"nobody-{uuid.uuid4().hex}"
    s.name(nobody, "nobody", secret=True)
    subid = _subid(s)
    cb_url, perm_url = _urls(s, subid)
    s.step("subscription", _post(cb_url, _diff_body(s, subid), _bearer(nobody)))
    s.step(
        "permission",
        _post(perm_url, _permission_body(s, "planted", _now()), _bearer(nobody)),
    )
    s.step(
        "generic",
        _post(f"{b.url}/callbacks/wire_ping", {"x": 1}, _bearer(nobody)),
    )
    check("WA4", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa5_other_peers_under_the_publishers_id(wire_pair, topology):
    """WA5: C (friend), S (subscriber) and D (admin) each post a
    subscription callback and a permission callback under A's id."""
    s = wire_pair(topology, grant=["*"])
    subid = _subid(s)
    cb_url, perm_url = _urls(s, subid)
    for name, relationship in (("C", "friend"), ("S", "subscriber"), ("D", "admin")):
        _, secret = wire_pair.add_peer(s, name, relationship)
        s.step(
            f"{name}: subscription callback",
            _post(cb_url, _diff_body(s, subid), _bearer(secret)),
        )
        s.step(
            f"{name}: permission callback",
            _post(perm_url, _permission_body(s, "planted", _now()), _bearer(secret)),
        )
    check("WA5", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa6_the_subscribers_creator(wire_pair, topology):
    """WA6: B's creator posts a subscription and a permission callback."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    subid = _subid(s)
    cb_url, perm_url = _urls(s, subid)
    s.step("subscription", _post(cb_url, _diff_body(s, subid), auth=b.basic))
    s.step(
        "permission",
        _post(perm_url, _permission_body(s, "planted", _now()), auth=b.basic),
    )
    check("WA6", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa7_unapproved_peer(wire_pair, topology):
    """WA7: E, whose trust B has not approved, posts callbacks under its own
    id."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    e, secret = wire_pair.add_peer(s, "E", "friend", approve=False)
    s.step(
        "permission callback",
        _post(
            f"{b.url}/callbacks/permissions/{e.id}",
            _permission_body(s, "planted", _now()),
            _bearer(secret),
        ),
    )
    s.step(
        "subscription callback",
        _post(
            f"{b.url}/callbacks/subscriptions/{e.id}/unknown-subscription",
            _diff_body(s, "unknown-subscription"),
            _bearer(secret),
        ),
    )
    check("WA7", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa8_fetch_goes_to_the_stored_base_uri(wire_pair, wire_other_app, topology):
    """WA8: a low-granularity callback with A's bearer whose body ``url``
    names ``wire_other_app``; B must fetch from A's stored base URI."""
    from actingweb.subscription import Subscription

    s = wire_pair(topology, grant=["*"], granularity="low")
    a, b = s.publisher, s.subscribers[0]
    subid = _subid(s)
    # Setup: a diff A holds and has not announced.
    diff = Subscription(
        actor_id=a.id, peerid=b.id, subid=subid, config=a.host.config
    ).add_diff(blob=json.dumps({"planted": {"v": 1}}))
    assert diff, "the planted diff was not stored"
    sequence = diff["sequence"]
    cb_url, _ = _urls(s, subid)
    body = {
        "id": a.id,
        "subscriptionid": subid,
        "target": "properties",
        "sequence": sequence,
        "granularity": "low",
        "timestamp": _now(),
        "url": f"{wire_other_app.url}/{a.id}/subscriptions/{b.id}/{subid}/{sequence}",
    }
    s.step(
        "A's bearer, a url on another host",
        _post(cb_url, body, _bearer(s.trust_secret)),
    )
    check("WA8", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa9_delete_the_subscription_callback(wire_pair, topology):
    """WA9: ``DELETE /<B>/callbacks/subscriptions/<A>/<subid>`` by C and by
    B's creator."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    _, secret = wire_pair.add_peer(s, "C", "friend")
    cb_url, _ = _urls(s, _subid(s))
    s.step("C", lambda: requests.delete(cb_url, headers=_bearer(secret)))
    s.step("B's creator", lambda: requests.delete(cb_url, auth=b.basic))
    check("WA9", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa10_subscriber_posts_to_its_publisher(wire_pair, topology):
    """WA10: B, with its bearer, posts a callback to A under the id of its
    own subscription at A (a row A holds as publisher)."""
    from actingweb.remote_storage import RemotePeerStore

    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    subid = _subid(s)
    body = {**_diff_body(s, subid), "id": b.id}
    s.step(
        "B posts to A",
        _post(
            f"{a.url}/callbacks/subscriptions/{b.id}/{subid}",
            body,
            _bearer(s.trust_secret),
        ),
    )

    def a_holds_of_b() -> dict[str, Any]:
        store = RemotePeerStore(
            actor=a.interface(), peer_id=b.id, validate_peer_id=False
        )
        return {
            "scalars": sorted(store.list_all_scalars()),
            "lists": sorted(store.list_all_lists()),
        }

    _probe(s, "what A holds of B", a_holds_of_b)
    check("WA10", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa11_generic_and_reserved_names(wire_pair, topology):
    """WA11: A's bearer: GET, POST and DELETE to a name a hook handles, to one
    no hook handles, and to each of the library's own names."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    for name in ["wire_ping", "unhandled", *RESERVED]:
        for method in ("GET", "POST", "DELETE"):
            s.step(
                f"{method} {name}",
                lambda method=method, name=name: requests.request(
                    method,
                    f"{b.url}/callbacks/{name}",
                    json={"x": 1},
                    headers=_bearer(s.trust_secret),
                ),
            )
    check("WA11", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa15_callback_type(wire_pair, topology):
    """WA15: A's bearer, a subscription callback of type ``permission`` and
    of an unknown type."""
    s = wire_pair(topology, grant=["*"])
    subid = _subid(s)
    cb_url, _ = _urls(s, subid)
    for kind in ("permission", "bogus"):
        s.step(
            f"type {kind}",
            _post(cb_url, _diff_body(s, subid, type=kind), _bearer(s.trust_secret)),
        )
    check("WA15", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa17_permission_timestamp(wire_pair, topology):
    """WA17: A's bearer, a permission callback a day ahead (refused: more
    than the allowed skew ahead), then one with a current timestamp (applied);
    the stored time is never ahead."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    _, perm_url = _urls(s, _subid(s))

    def stored() -> dict[str, Any]:
        row = _stored_permission_row(s, a.id) or {}
        fetched = datetime.fromisoformat(
            str(row.get("fetched_at")).replace("Z", "+00:00")
        )
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        return {
            "excluded": (row.get("properties") or {}).get("excluded_patterns"),
            "fetched_at_in_the_future": fetched > datetime.now(UTC),
        }

    ahead = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    s.step(
        "a day ahead",
        _post(perm_url, _permission_body(s, "first", ahead), _bearer(s.trust_secret)),
    )
    _probe(s, "stored after the first", stored)
    s.step(
        "current",
        lambda: requests.post(
            perm_url,
            json=_permission_body(s, "second", _now()),
            headers=_bearer(s.trust_secret),
        ),
    )
    _probe(s, "stored after the second", stored)
    check("WA17", s.recording(), variant=topology)


# ---------------------------------------------------------------------------
# Phase 2: /subscriptions, /permissions and /trust for the peer they name.
# The requests go to A; C, S, D and the other peers hold trusts to A.
# ---------------------------------------------------------------------------


def _put_property(s: Scenario, name: str, value: Any) -> requests.Response:
    a = s.publisher
    return requests.put(f"{a.url}/properties/{name}", json=value, auth=a.basic)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa12_another_peers_subscriptions(wire_pair, topology):
    """WA12: C reads, clears, consumes and deletes B's subscription at A."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    _, secret = wire_pair.add_peer(s, "C", "friend", to="A")
    s.step("A writes", lambda: _put_property(s, "x", {"v": 1}))
    subid = _subid(s)
    base = f"{a.url}/subscriptions/{b.id}"
    for label, method, url, body in (
        ("C lists B's subscriptions", "GET", base, None),
        ("C reads B's subscription", "GET", f"{base}/{subid}", None),
        ("C consumes B's diff", "GET", f"{base}/{subid}/1", None),
        ("C clears B's queue", "PUT", f"{base}/{subid}", {"sequence": 1}),
        ("C deletes B's subscription", "DELETE", f"{base}/{subid}", None),
    ):
        s.step(
            label,
            lambda method=method, url=url, body=body: requests.request(
                method, url, json=body, headers=_bearer(secret)
            ),
        )
    check("WA12", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa13_subscribe_under_another_peers_id(wire_pair, topology):
    """WA13: C creates a subscription at A under B's id."""
    s = wire_pair(topology, grant=["*"], subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    _, secret = wire_pair.add_peer(s, "C", "friend", to="A")
    s.step(
        "C subscribes as B",
        _post(
            f"{a.url}/subscriptions/{b.id}",
            {"target": "properties", "granularity": "high"},
            _bearer(secret),
        ),
    )
    check("WA13", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa14_permission_query(wire_pair, topology):
    """WA14: ``GET /permissions/<peer>`` at A: each peer reads its own, for
    every built-in type and the consumer's; C reads B's; A's creator and an
    admin peer read B's; C asks for an unknown id."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]

    def query(peer_id: str, **kwargs: Any) -> Callable[[], requests.Response]:
        return lambda: requests.get(f"{a.url}/permissions/{peer_id}", **kwargs)

    s.step("B reads its own (friend)", query(b.id, headers=_bearer(s.trust_secret)))
    for name, relationship in (
        ("P1", "associate"),
        ("P2", "partner"),
        ("P3", "subscriber"),
    ):
        peer, secret = wire_pair.add_peer(s, name, relationship, to="A")
        s.step(
            f"{name} reads its own ({relationship})",
            query(peer.id, headers=_bearer(secret)),
        )
    _, c_secret = wire_pair.add_peer(s, "C", "friend", to="A")
    d, d_secret = wire_pair.add_peer(s, "D", "admin", to="A")
    s.step("D reads its own (admin)", query(d.id, headers=_bearer(d_secret)))
    s.step("C reads B's", query(b.id, headers=_bearer(c_secret)))
    s.step("A's creator reads B's", query(b.id, auth=a.basic))
    s.step("D reads B's", query(b.id, headers=_bearer(d_secret)))
    x_id = uuid.uuid4().hex
    s.name(x_id, "X")
    s.step("C asks for an unknown id", query(x_id, headers=_bearer(c_secret)))
    check("WA14", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa16_application_trust_row(wire_pair, topology):
    """WA16: S, of the consumer's ``subscriber`` type (whose rows grant GET on
    ``trust/<type>/<id>``), reads B's trust row and its permissions at A, then
    its own."""
    from actingweb.trust import Trust

    s = wire_pair(topology, relationship="subscriber", grant=["allowed"])
    a, b = s.publisher, s.subscribers[0]
    peer, secret = wire_pair.add_peer(s, "S", "subscriber", to="A")
    # A trust row read back carries its verification token: name A's.
    for other, name in ((b, "B"), (peer, "S")):
        row = Trust(actor_id=a.id, peerid=other.id, config=a.host.config).get()
        if row and row.get("verification_token"):
            s.name(row["verification_token"], f"token:A-{name}", secret=True)
    for label, url in (
        ("S reads B's trust", f"{a.url}/trust/subscriber/{b.id}"),
        ("S reads B's permissions", f"{a.url}/trust/subscriber/{b.id}/permissions"),
        ("S reads its own trust", f"{a.url}/trust/subscriber/{peer.id}"),
        (
            "S reads its own permissions",
            f"{a.url}/trust/subscriber/{peer.id}/permissions",
        ),
    ):
        s.step(label, lambda url=url: requests.get(url, headers=_bearer(secret)))
    check("WA16", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wa18_subscription_root_query(wire_pair, topology):
    """WA18: C lists A's subscriptions naming B in the query."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    _, secret = wire_pair.add_peer(s, "C", "friend", to="A")
    s.step(
        "C lists ?peerid=<B>",
        lambda: requests.get(
            f"{a.url}/subscriptions", params={"peerid": b.id}, headers=_bearer(secret)
        ),
    )
    s.step(
        "C lists with no query",
        lambda: requests.get(f"{a.url}/subscriptions", headers=_bearer(secret)),
    )
    check("WA18", s.recording(), variant=topology)
