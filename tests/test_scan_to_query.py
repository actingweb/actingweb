"""
Tests for the scan()->query() conversion in the DynamoDB backend.

Every per-actor bulk read used to Scan the whole table with a
partition-key FilterExpression (O(table size) per call, measured at
~2,000 RCU per property fetch in production). The conversions to
query(actor_id) must preserve exact semantics:

- delete scope: deleting actor A's rows must not touch actor B's
  (the critical regression a botched conversion would introduce),
- strong consistency on the trust list reads (query() defaults
  consistent_read=False, unlike the explicit scan calls it replaced),
- the unset-actor_id delete guard.
"""

import uuid
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def actor_pair():
    """Two unique actor ids for cross-actor scope tests."""
    return f"scanq-a-{uuid.uuid4()}", f"scanq-b-{uuid.uuid4()}"


class TestPropertyDeleteScope:
    def test_bulk_delete_leaves_other_actor_intact(self, actor_pair):
        from actingweb.db.dynamodb.property import DbProperty, DbPropertyList

        actor_a, actor_b = actor_pair
        for actor in (actor_a, actor_b):
            for name in ("p1", "p2"):
                assert DbProperty().set(actor_id=actor, name=name, value=f"v-{actor}")

        lst = DbPropertyList()
        assert lst.fetch(actor_id=actor_a)
        assert lst.delete() is True

        assert DbPropertyList().fetch(actor_id=actor_a) in (None, {})
        remaining = DbPropertyList().fetch(actor_id=actor_b)
        assert remaining is not None and set(remaining) == {"p1", "p2"}

        # Cleanup
        b = DbPropertyList()
        b.fetch(actor_id=actor_b)
        b.delete()


class TestTrustListScope:
    def _create_trust(self, actor_id: str, peerid: str):
        from actingweb.db.dynamodb.trust import DbTrust

        assert DbTrust().create(
            actor_id=actor_id,
            peerid=peerid,
            baseuri=f"https://example.com/{peerid}",
            peer_type="test",
            relationship="friend",
            secret=f"secret-{uuid.uuid4()}",
        )

    def test_bulk_delete_leaves_other_actor_intact(self, actor_pair):
        from actingweb.db.dynamodb.trust import DbTrustList

        actor_a, actor_b = actor_pair
        self._create_trust(actor_a, "peer-1")
        self._create_trust(actor_a, "peer-2")
        self._create_trust(actor_b, "peer-1")

        lst = DbTrustList()
        assert len(lst.fetch(actor_a) or []) == 2
        assert lst.delete() is True

        assert DbTrustList().fetch(actor_a) == []
        b_trusts = DbTrustList().fetch(actor_b)
        assert b_trusts is not None and len(b_trusts) == 1

        b = DbTrustList()
        b.fetch(actor_b)
        b.delete()

    def test_fetch_and_delete_use_consistent_read(self, actor_pair):
        from actingweb.db.dynamodb import trust as trust_mod

        actor_a, _ = actor_pair
        with mock.patch.object(
            trust_mod.Trust, "query", return_value=iter([])
        ) as query:
            trust_mod.DbTrustList().fetch(actor_a)
        query.assert_called_once_with(actor_a, consistent_read=True)

        with mock.patch.object(
            trust_mod.Trust, "query", return_value=iter([])
        ) as query:
            lst = trust_mod.DbTrustList()
            lst.actor_id = actor_a
            lst.delete()
        query.assert_called_once_with(actor_a, consistent_read=True)

    def test_delete_without_fetch_returns_false(self):
        from actingweb.db.dynamodb.trust import DbTrustList

        assert DbTrustList().delete() is False


class TestPeerTrusteeScope:
    def _create(self, actor_id: str, peerid: str, peer_type: str = "test-type"):
        from actingweb.db.dynamodb.peertrustee import DbPeerTrustee

        assert DbPeerTrustee().create(
            actor_id=actor_id,
            peerid=peerid,
            peer_type=peer_type,
            baseuri=f"https://example.com/{peerid}",
            passphrase="pw",
        )

    def test_bulk_delete_leaves_other_actor_intact(self, actor_pair):
        from actingweb.db.dynamodb.peertrustee import DbPeerTrusteeList

        actor_a, actor_b = actor_pair
        self._create(actor_a, "peer-1")
        self._create(actor_b, "peer-1")

        lst = DbPeerTrusteeList()
        assert len(lst.fetch(actor_a) or []) == 1
        assert lst.delete() is True

        assert DbPeerTrusteeList().fetch(actor_a) == []
        b_peers = DbPeerTrusteeList().fetch(actor_b)
        assert b_peers is not None and len(b_peers) == 1

        b = DbPeerTrusteeList()
        b.fetch(actor_b)
        b.delete()

    def test_get_by_type_filters_within_actor(self, actor_pair):
        from actingweb.db.dynamodb.peertrustee import DbPeerTrustee

        actor_a, actor_b = actor_pair
        self._create(actor_a, "peer-1", peer_type="type-x")
        self._create(actor_a, "peer-2", peer_type="type-y")
        # Same type on another actor must not leak into actor_a's lookup
        self._create(actor_b, "peer-3", peer_type="type-x")

        found = DbPeerTrustee().get(actor_id=actor_a, peer_type="type-x")
        assert found and found["peerid"] == "peer-1"

        # >1 match of the same type within one actor is ambiguous -> False
        self._create(actor_a, "peer-4", peer_type="type-x")
        assert DbPeerTrustee().get(actor_id=actor_a, peer_type="type-x") is False

        from actingweb.db.dynamodb.peertrustee import DbPeerTrusteeList

        for actor in (actor_a, actor_b):
            lst_cleanup = DbPeerTrusteeList()
            lst_cleanup.fetch(actor)
            lst_cleanup.delete()

    def test_delete_without_fetch_returns_false(self):
        from actingweb.db.dynamodb.peertrustee import DbPeerTrusteeList

        assert DbPeerTrusteeList().delete() is False
