"""
Reciprocal trust approval must reach the initiator.

``tests/integration/test_trust_flow.py`` approves a reciprocal trust and
asserts only the status code, so it passes whether or not the approving side
ever tells the peer. That gap is why a regression breaking the notification
can leave the whole suite green.

The property under test: after the approving side answers the approval, the
*initiator's* record shows ``peer_approved`` true. That flip only happens
because ``Actor.modify_trust_and_notify`` POSTs to the peer, gated on
``approved is True and this_trust["approved"] is False`` — a gate that goes
silent if the record is already approved when the approval arrives.
"""

import time

import pytest
import requests


def _find_trust(base: str, actor_id: str, creator: str, passphrase: str, peer_id: str):
    resp = requests.get(f"{base}/{actor_id}/trust", auth=(creator, passphrase))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = list(body.values()) if isinstance(body, dict) else body
    for row in rows:
        if isinstance(row, dict) and row.get("peerid") == peer_id:
            return row
    return None


def _poll_trust(base, actor_id, creator, passphrase, peer_id, predicate, timeout=15):
    """Peer notification is a live HTTP call and may be dispatched async."""
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        row = _find_trust(base, actor_id, creator, passphrase, peer_id)
        if row and predicate(row):
            return row
        time.sleep(0.5)
    return row


def _truthy(value) -> bool:
    """The wire carries booleans as JSON bools or as strings, per backend."""
    return value in (True, "true", "True")


@pytest.mark.integration
@pytest.mark.parametrize("relationship", ["friend", "subscriber", "associate"])
class TestReciprocalApprovalReachesInitiator:
    def test_approving_side_notifies_the_initiator(self, http_client, relationship):
        base = http_client.base_url
        peer_base = getattr(http_client, "peer_url", base)

        creator1 = f"recip1-{int(time.time() * 1000)}@actingweb.net"
        creator2 = f"recip2-{int(time.time() * 1000)}@actingweb.net"

        r1 = http_client.post(f"{base}/", json={"creator": creator1})
        assert r1.status_code == 201, r1.text
        actor1_id = r1.json()["id"]
        pass1 = r1.json()["passphrase"]

        r2 = http_client.post(f"{peer_base}/", json={"creator": creator2})
        assert r2.status_code == 201, r2.text
        actor2_id = r2.json()["id"]
        pass2 = r2.json()["passphrase"]

        try:
            # Actor1 initiates. This makes a blocking call to actor2, which
            # writes its reciprocal row before answering.
            created = requests.post(
                f"{base}/{actor1_id}/trust",
                auth=(creator1, pass1),
                json={
                    "url": f"{peer_base}/{actor2_id}",
                    "relationship": relationship,
                    "desc": "reciprocal approval regression",
                },
            )
            assert created.status_code in (200, 201, 202), created.text

            # Actor2's side exists and is NOT yet approved. If this is already
            # approved, the approval below cannot notify anyone — the notify is
            # gated on the stored value still being False.
            row2 = _find_trust(peer_base, actor2_id, creator2, pass2, actor1_id)
            assert row2 is not None, "actor2 has no reciprocal trust row"
            assert not _truthy(row2.get("approved")), (
                "actor2's row is already approved before anyone approved it; "
                "modify_trust_and_notify() will skip notifying the initiator"
            )
            # Separately: the peer callback has to have worked at all. A
            # deployment whose advertised baseuri is unreachable — a preview
            # server behind a tunnel that is down, say — still creates both
            # rows and still answers the approval 204, but leaves verified
            # false and never propagates anything. Asserting it here names
            # that cause directly instead of leaving a bare peer_approved
            # failure to be mistaken for a library regression.
            assert _truthy(row2.get("verified")), (
                "actor2 could not verify back to actor1: the peer callback did "
                "not complete. Check that the advertised baseuri is reachable "
                "from the peer before suspecting the approval path"
            )

            # Actor2 approves.
            approved = requests.put(
                f"{peer_base}/{actor2_id}/trust/{row2.get('relationship', relationship)}/{actor1_id}",
                auth=(creator2, pass2),
                json={"approved": True},
            )
            assert approved.status_code in (200, 204), approved.text

            # The point of the test: actor1 must learn about it.
            row1 = _poll_trust(
                base,
                actor1_id,
                creator1,
                pass1,
                actor2_id,
                lambda r: _truthy(r.get("peer_approved")),
            )
            assert row1 is not None, "actor1 lost its trust row"
            assert _truthy(row1.get("peer_approved")), (
                "actor1's peer_approved never flipped: the approving side did "
                "not notify the peer"
            )
        finally:
            requests.delete(f"{base}/{actor1_id}", auth=(creator1, pass1))
            requests.delete(f"{peer_base}/{actor2_id}", auth=(creator2, pass2))
