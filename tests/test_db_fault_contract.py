"""The DB-layer fault contract (3.16, Phase 1 of
``thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md``).

Every decision read raises ``DbError`` on a backend fault, ``strict=False``
answers it as absence, and absence is still an answer. Deletes on a loaded
handle answer True when the row is gone; conditional deletes keep "True only
if this call removed it".

The fault tests inject at the lowest seam of each backend, so they run
whichever backend the suite is configured for: PostgreSQL's
``get_connection`` raises, and DynamoDB's PynamoDB model methods raise.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.db.exceptions import CreatorTaken, DbError

# ---------------------------------------------------------------------------
# PostgreSQL: every read and write opens get_connection() inside its try, so
# a connection that cannot be had is the fault every method must report.
# ---------------------------------------------------------------------------

pg = pytest.importorskip("psycopg")


def _pg_down(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("connection refused (simulated)")


def _pg_module(name: str) -> Any:
    import importlib

    return importlib.import_module(f"actingweb.db.postgresql.{name}")


# (module, class, method, kwargs, folded answer with strict=False)
PG_READS: list[tuple[str, str, str, dict[str, Any], Any]] = [
    ("actor", "DbActor", "get", {"actor_id": "a"}, None),
    ("actor", "DbActor", "get_by_creator", {"creator": "x@example.com"}, None),
    ("actor", "DbActorList", "fetch", {}, False),
    ("trust", "DbTrust", "get", {"actor_id": "a", "peerid": "p"}, None),
    ("trust", "DbTrustList", "fetch", {"actor_id": "a"}, []),
    ("peertrustee", "DbPeerTrustee", "get", {"actor_id": "a", "peerid": "p"}, None),
    ("peertrustee", "DbPeerTrusteeList", "fetch", {"actor_id": "a"}, []),
    (
        "subscription",
        "DbSubscription",
        "get",
        {"actor_id": "a", "peerid": "p", "subid": "s"},
        None,
    ),
    ("subscription", "DbSubscriptionList", "fetch", {"actor_id": "a"}, []),
    (
        "subscription_diff",
        "DbSubscriptionDiff",
        "get",
        {"actor_id": "a", "subid": "s", "seqnr": 1},
        None,
    ),
    ("subscription_diff", "DbSubscriptionDiffList", "fetch", {"actor_id": "a"}, []),
    ("attribute", "DbAttribute", "get_bucket", {"actor_id": "a", "bucket": "b"}, None),
    (
        "attribute",
        "DbAttribute",
        "get_attr",
        {"actor_id": "a", "bucket": "b", "name": "n"},
        None,
    ),
    ("attribute", "DbAttributeBucketList", "fetch", {"actor_id": "a"}, None),
    (
        "attribute",
        "DbAttributeBucketList",
        "fetch_timestamps",
        {"actor_id": "a"},
        None,
    ),
    ("property", "DbPropertyList", "fetch", {"actor_id": "a"}, None),
    (
        "property",
        "DbPropertyList",
        "fetch_all_including_lists",
        {"actor_id": "a"},
        None,
    ),
    (
        "property_lookup",
        "DbPropertyLookup",
        "get",
        {"property_name": "email", "value": "x@example.com"},
        None,
    ),
]


def _pg_instance(module: Any, cls_name: str) -> Any:
    cls = getattr(module, cls_name)
    if cls_name in ("DbProperty", "DbPropertyList"):
        return cls(use_lookup_table=True, indexed_properties=["email"])
    return cls()


@pytest.mark.parametrize(
    "mod,cls_name,method,kwargs,folded",
    PG_READS,
    ids=[f"{r[1]}.{r[2]}" for r in PG_READS],
)
class TestPostgresReadFaults:
    def test_fault_raises_db_error(
        self, mod: str, cls_name: str, method: str, kwargs: dict[str, Any], folded: Any
    ) -> None:
        module = _pg_module(mod)
        obj = _pg_instance(module, cls_name)
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError) as raised:
                getattr(obj, method)(**kwargs)
        assert isinstance(raised.value.__cause__, RuntimeError)

    def test_strict_false_folds(
        self, mod: str, cls_name: str, method: str, kwargs: dict[str, Any], folded: Any
    ) -> None:
        module = _pg_module(mod)
        obj = _pg_instance(module, cls_name)
        with mock.patch.object(module, "get_connection", _pg_down):
            assert getattr(obj, method)(**kwargs, strict=False) == folded


class TestPostgresStrictOnlyReads:
    def test_reverse_lookup_fault_raises(self) -> None:
        module = _pg_module("property")
        obj = module.DbProperty(use_lookup_table=False, indexed_properties=["email"])
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError):
                obj.get_actor_id_from_property(name="email", value="x@example.com")
            assert (
                obj.get_actor_id_from_property(
                    name="email", value="x@example.com", strict=False
                )
                is None
            )

    def test_get_attr_strict_fault_raises_db_error(self) -> None:
        module = _pg_module("attribute")
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError):
                module.DbAttribute.get_attr_strict(actor_id="a", bucket="b", name="n")


class TestPostgresWriteFaults:
    """A write or delete that faults raises; it never answers False."""

    @pytest.mark.parametrize(
        "mod,cls_name,handle",
        [
            ("actor", "DbActor", {"id": "a", "creator": "c", "passphrase": "p"}),
            ("trust", "DbTrust", {"id": "a", "peerid": "p"}),
            ("peertrustee", "DbPeerTrustee", {"id": "a", "peerid": "p"}),
            (
                "subscription",
                "DbSubscription",
                {"id": "a", "peerid": "p", "subscriptionid": "s"},
            ),
        ],
    )
    def test_delete_on_a_handle_raises(
        self, mod: str, cls_name: str, handle: dict[str, Any]
    ) -> None:
        module = _pg_module(mod)
        obj = getattr(module, cls_name)()
        obj.handle = dict(handle)
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError):
                obj.delete()

    def test_actor_modify_raises_and_keeps_the_handle(self) -> None:
        module = _pg_module("actor")
        obj = module.DbActor()
        obj.handle = {"id": "a", "creator": "old@example.com", "passphrase": "p"}
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError):
                obj.modify(creator="new@example.com")
        assert obj.handle["creator"] == "old@example.com"

    def test_attribute_set_and_delete_raise(self) -> None:
        module = _pg_module("attribute")
        with mock.patch.object(module, "get_connection", _pg_down):
            with pytest.raises(DbError):
                module.DbAttribute.set_attr(
                    actor_id="a", bucket="b", name="n", data={"x": 1}
                )
            with pytest.raises(DbError):
                module.DbAttribute.set_attr(actor_id="a", bucket="b", name="n")
            with pytest.raises(DbError):
                module.DbAttribute.delete_bucket(actor_id="a", bucket="b")

    def test_conditional_delete_is_exempt(self) -> None:
        """``delete_attr_conditional`` keeps its False: single-use
        consumption reads True as "this call removed it"."""
        module = _pg_module("attribute")
        with mock.patch.object(module, "get_connection", _pg_down):
            assert (
                module.DbAttribute.delete_attr_conditional(
                    actor_id="a", bucket="b", name="n"
                )
                is False
            )


class _FakeCursor:
    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on
        self.rowcount = 1
        self.statements: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, statement: str, params: Any = None) -> None:  # noqa: ARG002
        self.statements.append(statement)
        if self.fail_on in statement:
            raise pg.errors.QueryCanceled("statement timeout (simulated)")

    def fetchone(self) -> Any:
        return None

    def fetchall(self) -> list[Any]:
        return [("email", "x@example.com")]


class _FakeConnection:
    def __init__(self, fail_on: str) -> None:
        self.cursor_obj = _FakeCursor(fail_on)
        self.commits = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


class TestPostgresPropertyRollback:
    """A failed statement aborts the transaction: committing after catching
    it rolls everything back while the method reports success."""

    def test_set_with_a_failed_lookup_sync_raises_and_never_commits(self) -> None:
        module = _pg_module("property")
        conn = _FakeConnection(fail_on="INSERT INTO property_lookup")
        obj = module.DbProperty(use_lookup_table=True, indexed_properties=["email"])
        with (
            mock.patch.object(module, "get_connection", lambda: conn),
            mock.patch.object(obj, "get", return_value=None),
        ):
            with pytest.raises(DbError):
                obj.set(actor_id="a", name="email", value="x@example.com")
        assert conn.commits == 0

    def test_list_delete_with_a_failed_lookup_delete_raises_and_never_commits(
        self,
    ) -> None:
        module = _pg_module("property")
        conn = _FakeConnection(fail_on="DELETE FROM property_lookup")
        obj = module.DbPropertyList(use_lookup_table=True, indexed_properties=["email"])
        obj.actor_id = "a"
        with mock.patch.object(module, "get_connection", lambda: conn):
            with pytest.raises(DbError):
                obj.delete()
        assert conn.commits == 0


# ---------------------------------------------------------------------------
# DynamoDB: the PynamoDB calls raise. Query faults arrive while iterating.
# ---------------------------------------------------------------------------


def _ddb() -> Any:
    import importlib

    return {
        name: importlib.import_module(f"actingweb.db.dynamodb.{name}")
        for name in (
            "actor",
            "trust",
            "peertrustee",
            "subscription",
            "subscription_diff",
            "attribute",
            "property",
            "property_lookup",
        )
    }


class _Throttled(Exception):
    """Stands in for a PynamoDB error that is not DoesNotExist."""


def _raises(*_a: Any, **_k: Any) -> Any:
    raise _Throttled("ProvisionedThroughputExceededException (simulated)")


def _faults_mid_page(first: list[Any]) -> Callable[..., Iterator[Any]]:
    """A query whose first page is served and whose next page faults: the
    fault arrives while the caller iterates."""

    def query(*_a: Any, **_k: Any) -> Iterator[Any]:
        yield from first
        raise _Throttled("throttled on the second page (simulated)")

    return query


class TestDynamoReadFaults:
    def test_actor_get(self) -> None:
        m = _ddb()["actor"]
        with mock.patch.object(m.Actor, "get", _raises):
            with pytest.raises(DbError):
                m.DbActor().get(actor_id="a")
            assert m.DbActor().get(actor_id="a", strict=False) is None

    def test_get_by_creator_index_fault(self) -> None:
        m = _ddb()["actor"]
        with mock.patch.object(m.Actor.creator_index, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbActor().get_by_creator(creator="x@example.com")
            assert (
                m.DbActor().get_by_creator(creator="x@example.com", strict=False)
                is None
            )

    def test_get_by_creator_consistent_row_fault(self) -> None:
        m = _ddb()["actor"]
        row = type("Row", (), {"id": "a1", "creator": "x", "passphrase": "p"})()
        with (
            mock.patch.object(m.Actor.creator_index, "query", lambda *a, **k: [row]),
            mock.patch.object(m.Actor, "get", _raises),
        ):
            with pytest.raises(DbError):
                m.DbActor().get_by_creator(creator="x@example.com", consistent=True)
            # Without consistent the index projection answers, no per-row get.
            assert m.DbActor().get_by_creator(creator="x@example.com") == [
                {"id": "a1", "creator": "x", "passphrase": "p"}
            ]

    def test_actor_list_scan_fault(self) -> None:
        m = _ddb()["actor"]
        with mock.patch.object(m.Actor, "scan", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbActorList().fetch()
            assert m.DbActorList().fetch(strict=False) is False

    def test_trust_get_and_list(self) -> None:
        m = _ddb()["trust"]
        with mock.patch.object(m.Trust, "get", _raises):
            with pytest.raises(DbError):
                m.DbTrust().get(actor_id="a", peerid="p")
            assert m.DbTrust().get(actor_id="a", peerid="p", strict=False) is None
        with mock.patch.object(m.Trust, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbTrustList().fetch("a")
            assert m.DbTrustList().fetch("a", strict=False) == []

    def test_peertrustee_get_and_list(self) -> None:
        m = _ddb()["peertrustee"]
        with mock.patch.object(m.PeerTrustee, "get", _raises):
            with pytest.raises(DbError):
                m.DbPeerTrustee().get(actor_id="a", peerid="p")
            assert m.DbPeerTrustee().get(actor_id="a", peerid="p", strict=False) is None
        with mock.patch.object(m.PeerTrustee, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbPeerTrusteeList().fetch("a")
            assert m.DbPeerTrusteeList().fetch("a", strict=False) == []

    def test_subscription_get_and_list(self) -> None:
        m = _ddb()["subscription"]
        with mock.patch.object(m.Subscription, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbSubscription().get(actor_id="a", peerid="p", subid="s")
            assert (
                m.DbSubscription().get(
                    actor_id="a", peerid="p", subid="s", strict=False
                )
                is None
            )
            with pytest.raises(DbError):
                m.DbSubscriptionList().fetch("a")
            assert m.DbSubscriptionList().fetch("a", strict=False) == []

    def test_subscription_diff_get_and_list(self) -> None:
        m = _ddb()["subscription_diff"]
        with mock.patch.object(m.SubscriptionDiff, "get", _raises):
            with pytest.raises(DbError):
                m.DbSubscriptionDiff().get(actor_id="a", subid="s", seqnr=1)
            assert (
                m.DbSubscriptionDiff().get(
                    actor_id="a", subid="s", seqnr=1, strict=False
                )
                is None
            )
        with mock.patch.object(m.SubscriptionDiff, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbSubscriptionDiffList().fetch(actor_id="a")
            assert m.DbSubscriptionDiffList().fetch(actor_id="a", strict=False) == []

    def test_subscription_diff_absent_seqnr_is_none(self) -> None:
        """``DoesNotExist`` for a missing seqnr is absence, not a raise."""
        m = _ddb()["subscription_diff"]
        db = m.DbSubscriptionDiff()
        assert db.get(actor_id=f"absent-{uuid.uuid4().hex}", subid="s", seqnr=7) is None

    def test_get_bucket_fault_while_iterating_raises(self) -> None:
        """Before 3.16 the ``try`` covered only the lazy ``query()`` call, so
        a fault on a later page escaped it undocumented."""
        m = _ddb()["attribute"]
        row = type(
            "Row", (), {"bucket": "b", "name": "n1", "data": 1, "timestamp": None}
        )()
        with mock.patch.object(m.Attribute, "query", _faults_mid_page([row])):
            with pytest.raises(DbError):
                m.DbAttribute.get_bucket(actor_id="a", bucket="b")
            assert (
                m.DbAttribute.get_bucket(actor_id="a", bucket="b", strict=False) is None
            )

    def test_get_attr_and_strict_read(self) -> None:
        m = _ddb()["attribute"]
        with mock.patch.object(m.Attribute, "get", _raises):
            with pytest.raises(DbError):
                m.DbAttribute.get_attr(actor_id="a", bucket="b", name="n")
            assert (
                m.DbAttribute.get_attr(actor_id="a", bucket="b", name="n", strict=False)
                is None
            )
            with pytest.raises(DbError):
                m.DbAttribute.get_attr_strict(actor_id="a", bucket="b", name="n")

    def test_bucket_list_reads(self) -> None:
        m = _ddb()["attribute"]
        with mock.patch.object(m.Attribute, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                m.DbAttributeBucketList.fetch(actor_id="a")
            with pytest.raises(DbError):
                m.DbAttributeBucketList.fetch_timestamps(actor_id="a")
            assert m.DbAttributeBucketList.fetch(actor_id="a", strict=False) is None

    def test_property_lookup_reads(self) -> None:
        m = _ddb()["property_lookup"]
        with mock.patch.object(m.PropertyLookupV2, "get", _raises):
            with pytest.raises(DbError):
                m.DbPropertyLookup().get(property_name="email", value="x")
            assert (
                m.DbPropertyLookup().get(property_name="email", value="x", strict=False)
                is None
            )
        with mock.patch.object(m.PropertyLookup, "get", _raises):
            with pytest.raises(DbError):
                m.DbPropertyLookup().get_v1(property_name="email", value="x")

    def test_v1_missing_table_is_still_none(self) -> None:
        m = _ddb()["property_lookup"]
        missing = Exception("Requested resource not found (ResourceNotFound)")
        with mock.patch.object(m.PropertyLookup, "get", side_effect=missing):
            assert m.DbPropertyLookup().get_v1(property_name="email", value="x") is None

    def test_reverse_lookup_fault_raises(self) -> None:
        m = _ddb()
        db = m["property"].DbProperty(
            use_lookup_table=True, indexed_properties=["email"]
        )
        with mock.patch.object(m["property_lookup"].PropertyLookupV2, "get", _raises):
            with pytest.raises(DbError):
                db.get_actor_id_from_property(name="email", value="x")
            assert (
                db.get_actor_id_from_property(name="email", value="x", strict=False)
                is None
            )

    def test_property_list_fetch_fault(self) -> None:
        m = _ddb()["property"]
        db = m.DbPropertyList(use_lookup_table=True, indexed_properties=["email"])
        with mock.patch.object(m.Property, "query", _faults_mid_page([])):
            with pytest.raises(DbError):
                db.fetch(actor_id="a")
            assert db.fetch(actor_id="a", strict=False) is None


class TestDynamoWriteFaults:
    def test_delete_attr_fault_raises_instead_of_true(self) -> None:
        """Before 3.16 DynamoDB answered True for a delete that faulted."""
        m = _ddb()["attribute"]
        with mock.patch.object(m.Attribute, "get", _raises):
            with pytest.raises(DbError):
                m.DbAttribute().delete_attr(actor_id="a", bucket="b", name="n")
            with pytest.raises(DbError):
                m.DbAttribute.set_attr(actor_id="a", bucket="b", name="n", data=None)

    def test_delete_on_a_handle_raises(self) -> None:
        m = _ddb()["trust"]
        db = m.DbTrust()
        db.handle = mock.MagicMock()
        db.handle.delete.side_effect = _Throttled("throttled")
        with pytest.raises(DbError):
            db.delete()


# ---------------------------------------------------------------------------
# Absence, deletes of absent rows, replay and expiry: the configured backend.
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> Any:
    from tests._adoption_helpers import make_config

    return make_config()


class TestAbsenceIsAnAnswer:
    def test_reads_of_absent_rows(self, config: Any) -> None:
        from actingweb.db import (
            get_actor,
            get_attribute,
            get_peer_trustee,
            get_subscription,
            get_subscription_list,
            get_trust,
            get_trust_list,
        )

        missing = f"absent-{uuid.uuid4().hex}"
        assert get_actor(config).get(actor_id=missing) is None
        assert get_actor(config).get_by_creator(creator=f"{missing}@x.test") == []
        assert get_trust(config).get(actor_id=missing, peerid="p") is None
        assert get_trust_list(config).fetch(actor_id=missing) == []
        assert get_peer_trustee(config).get(actor_id=missing, peerid="p") is None
        assert (
            get_subscription(config).get(actor_id=missing, peerid="p", subid="s")
            is None
        )
        assert get_subscription_list(config).fetch(actor_id=missing) == []
        db = get_attribute(config)
        assert db.get_bucket(actor_id=missing, bucket="b") == {}
        assert db.get_attr(actor_id=missing, bucket="b", name="n") is None
        assert db.get_attr_strict(actor_id=missing, bucket="b", name="n") is None

    def test_deleting_an_absent_row_through_a_loaded_handle_is_true(
        self, config: Any
    ) -> None:
        from actingweb.db import get_trust

        actor_id = f"a-{uuid.uuid4().hex}"
        assert get_trust(config).create(actor_id=actor_id, peerid="p", secret="s")
        first = get_trust(config)
        assert first.get(actor_id=actor_id, peerid="p")
        second = get_trust(config)
        assert second.get(actor_id=actor_id, peerid="p")
        assert second.delete() is True
        # The row is gone already; the first handle's delete confirms it.
        assert first.delete() is True
        assert get_trust(config).get(actor_id=actor_id, peerid="p") is None

    def test_delete_without_a_handle_is_false(self, config: Any) -> None:
        from actingweb.db import get_actor

        assert get_actor(config).delete() is False

    def test_deleting_an_absent_attribute_is_true(self, config: Any) -> None:
        from actingweb.db import get_attribute

        missing = f"absent-{uuid.uuid4().hex}"
        assert (
            get_attribute(config).delete_attr(actor_id=missing, bucket="b", name="n")
            is True
        )


class TestConditionalDeleteReplay:
    def test_second_conditional_delete_of_a_session_is_false(self, config: Any) -> None:
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET
        from actingweb.db import get_attribute

        db = get_attribute(config)
        name = f"session-{uuid.uuid4().hex}"
        # A current created_at: a parallel test's clear_expired_sessions would
        # otherwise take this row for an expired session and delete it first.
        db.set_attr(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            name=name,
            data={"x": 1, "created_at": int(time.time())},
        )
        args = {"actor_id": OAUTH2_SYSTEM_ACTOR, "bucket": OAUTH_SESSION_BUCKET}
        assert db.delete_attr_conditional(**args, name=name) is True
        assert db.delete_attr_conditional(**args, name=name) is False

    def test_second_redemption_of_a_mobile_ticket_is_refused(self, config: Any) -> None:
        from actingweb.oauth_state_store import MobileTicketStore

        store = MobileTicketStore(config)
        ticket = store.create(
            code="c", redirect_uri="https://x.test/cb", provider="google"
        )
        assert store.consume(ticket)
        assert store.consume(ticket) is None


class TestExpiry:
    """Strict never filters: only ``get_attr_strict`` hides an expired row."""

    def test_expired_row_is_hidden_only_by_get_attr_strict(self, config: Any) -> None:
        from actingweb.db import get_attribute

        db = get_attribute(config)
        actor_id = f"a-{uuid.uuid4().hex}"
        db.set_attr(
            actor_id=actor_id, bucket="b", name="n", data={"v": 1}, ttl_seconds=1
        )
        later = time.time() + 10 * 24 * 3600
        with mock.patch("time.time", return_value=later):
            assert db.get_attr_strict(actor_id=actor_id, bucket="b", name="n") is None
            row = db.get_attr(actor_id=actor_id, bucket="b", name="n")
            assert row and row["data"] == {"v": 1}
            assert "n" in (db.get_bucket(actor_id=actor_id, bucket="b") or {})

    def test_session_cleanup_still_removes_an_expired_session(
        self, config: Any
    ) -> None:
        from actingweb.constants import OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET
        from actingweb.db import get_attribute
        from actingweb.oauth_session import OAuth2SessionManager

        db = get_attribute(config)
        name = f"session-{uuid.uuid4().hex}"
        db.set_attr(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=OAUTH_SESSION_BUCKET,
            name=name,
            data={"created_at": 0},
        )
        OAuth2SessionManager(config).clear_expired_sessions()
        assert (
            db.get_attr(
                actor_id=OAUTH2_SYSTEM_ACTOR, bucket=OAUTH_SESSION_BUCKET, name=name
            )
            is None
        )


class TestAttributesWrapper:
    def test_strict_by_default_and_fold_on_request(self, config: Any) -> None:
        from actingweb.attribute import Attributes

        store = Attributes(actor_id="a", bucket="b", config=config)
        with mock.patch.object(
            type(store.dbprop), "get_bucket", side_effect=DbError("x")
        ):
            with pytest.raises(DbError):
                store.get_bucket()
            assert store.get_bucket(strict=False) == {}
            assert store.loaded is False
        with mock.patch.object(
            type(store.dbprop), "get_attr", side_effect=DbError("x")
        ):
            with pytest.raises(DbError):
                store.get_attr(name="n")
            assert store.get_attr(name="n", strict=False) is None
            # Nothing was cached as absent: a later read goes to the backend.
            assert "n" not in store.data

    def test_internal_store_never_raises_on_a_read_fault(self, config: Any) -> None:
        from actingweb.attribute import InternalStore

        store = InternalStore(actor_id="a", config=config)
        db = store.__dict__["_db"]
        with mock.patch.object(type(db.dbprop), "get_bucket", side_effect=DbError("x")):
            assert store.anything is None
        assert store.loaded is False


def test_creator_taken_is_a_db_error_with_no_actor_id_in_its_text() -> None:
    err = CreatorTaken("someone@example.com")
    assert isinstance(err, DbError)
    assert "someone@example.com" not in str(err)
