"""Wire rows: a trust request for a peer that already has a row.

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 3, rows
``WT1`` to ``WT5``. A request for an existing peer is a re-pair: accepted
only with the trust's current secret as the bearer, and then only the
secret is swapped; anything else answers 403 and changes nothing on either
side. The creator removes a dead peer locally with ``?notify=false``.
Recorded with the fix; the pre-fix runs of ``WT1``, ``WT2`` and ``WT4`` are in
the plan's verification document.
"""

from __future__ import annotations

import uuid

import pytest
import requests

from ._wire import check

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]


def _put(actor, name, value):
    return requests.put(f"{actor.url}/properties/{name}", json=value, auth=actor.basic)


def _name_tokens(s, *pairs) -> None:
    """Name the verification tokens (and any unnamed secret) of the trust
    rows ``(holder, peer)`` as they are now; a trust request and a trust
    row read back carry them. Called before and after the steps that make
    new ones; a value already named keeps its first name."""
    from actingweb.trust import Trust

    for holder, peer in pairs:
        row = Trust(actor_id=holder.id, peerid=peer.id, config=holder.host.config).get()
        if not row:
            continue
        token = row.get("verification_token")
        if token and token not in s.secrets:
            count = sum(
                1
                for v in s.secrets.values()
                if v.startswith(f"token:{holder.name}-{peer.name}")
            )
            s.name(token, f"token:{holder.name}-{peer.name}#{count + 1}", secret=True)
        secret = row.get("secret")
        if secret and secret not in s.secrets:
            s.name(secret, f"secret:{holder.name}-{peer.name}", secret=True)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wt1_re_pair(wire_pair, topology):
    """WT1: B re-initiates its trust to A through the SDK, as the consumer
    does, then A writes: the callback carries the new secret."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    new_secret = uuid.uuid4().hex + uuid.uuid4().hex
    s.name(new_secret, "trust:A-B#2", secret=True)
    _name_tokens(s, (a, b), (b, a))

    def re_pair():
        rel = b.interface().trust.create_relationship(
            peer_url=a.url, relationship="friend", secret=new_secret
        )
        return None if rel is None else {"relationship": rel.relationship}

    s.step("B re-initiates", re_pair)
    s.step("A writes", lambda: _put(a, "x", {"v": 1}))
    _name_tokens(s, (a, b), (b, a))
    check("WT1", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wt2_request_naming_another_host(wire_pair, wire_other_app, topology):
    """WT2: a creation request for B's id naming ``wire_other_app`` as its
    base URI, without B's current secret."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    planted = uuid.uuid4().hex + uuid.uuid4().hex
    s.name(planted, "planted", secret=True)
    s.name("planted-token", "token:planted", secret=True)
    _name_tokens(s, (a, b), (b, a))
    s.step(
        "a request for B's id",
        lambda: requests.post(
            f"{a.url}/trust/friend",
            json={
                "baseuri": f"{wire_other_app.url}/{b.id}",
                "id": b.id,
                "type": "urn:actingweb:test",
                "secret": planted,
                "verify": "planted-token",
                "desc": "",
            },
        ),
    )
    _name_tokens(s, (a, b), (b, a))
    check("WT2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wt3_new_peer(wire_pair, topology):
    """WT3: a creation request for a new peer id, as before the fix: N asks A
    for a trust through its own actor."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    n = wire_pair.add_actor(s, "N")
    secret = uuid.uuid4().hex + uuid.uuid4().hex
    s.name(secret, "trust:N-A", secret=True)
    _name_tokens(s, (a, b), (b, a))

    def ask():
        rel = n.interface().trust.create_relationship(
            peer_url=a.url, relationship="friend", secret=secret
        )
        return None if rel is None else {"approved": rel.approved}

    s.step("N asks A for a trust", ask)
    _name_tokens(s, (a, n), (n, a))
    check("WT3", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wt4_re_pair_with_another_relationship(wire_pair, topology):
    """WT4: B re-initiates asking for another relationship type."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    new_secret = uuid.uuid4().hex + uuid.uuid4().hex
    s.name(new_secret, "trust:A-B#2", secret=True)
    _name_tokens(s, (a, b), (b, a))

    def re_pair():
        rel = b.interface().trust.create_relationship(
            peer_url=a.url, relationship="admin", secret=new_secret
        )
        return None if rel is None else {"relationship": rel.relationship}

    s.step("B asks for admin", re_pair)
    _name_tokens(s, (a, b), (b, a))
    check("WT4", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wt5_local_delete(wire_pair, topology):
    """WT5: ``DELETE /trust/friend/<B>?notify=false`` by B (refused: the
    creator's) and then by A's creator (the row and its cascade gone, B
    contacted by nothing)."""
    s = wire_pair(topology, grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    _name_tokens(s, (a, b), (b, a))
    url = f"{a.url}/trust/friend/{b.id}"
    s.step(
        "B, its bearer",
        lambda: requests.delete(
            url,
            params={"notify": "false"},
            headers={"Authorization": f"Bearer {s.trust_secret}"},
        ),
    )
    s.step(
        "A's creator",
        lambda: requests.delete(url, params={"notify": "false"}, auth=a.basic),
    )
    check("WT5", s.recording(), variant=topology)
