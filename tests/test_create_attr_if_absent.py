"""``create_attr_if_absent``: an atomic, TTL-aware create (both backends).

One conditional write that never overwrites a live row. An expired row counts
as absent and is replaced in the same write; a row in another bucket is never
touched; a fault raises ``DbError``; a lost condition whose stored row is
JSON-equal to what this call wrote is a win (an SDK-retried create that
landed). The older conditional operations keep answering False on a fault.
"""

from __future__ import annotations

import importlib
import os
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from actingweb.attribute import Attributes
from actingweb.db.exceptions import DbError

BACKEND = os.getenv("DATABASE_BACKEND", "dynamodb")


def _module() -> Any:
    return importlib.import_module(f"actingweb.db.{BACKEND}.attribute")


def _db() -> Any:
    return _module().DbAttribute()


@pytest.fixture
def actor_id() -> Iterator[str]:
    actor = f"create-{uuid.uuid4()}"
    yield actor
    for bucket in ("b", "other"):
        _db().delete_bucket(actor_id=actor, bucket=bucket)


def _create(actor: str, name: str, data: Any, **kw: Any) -> bool:
    return _db().create_attr_if_absent(
        actor_id=actor, bucket="b", name=name, data=data, **kw
    )


def _read(actor: str, name: str, bucket: str = "b") -> Any:
    return _db().get_attr(actor_id=actor, bucket=bucket, name=name)


def _seed_expired(actor: str, name: str, data: Any, bucket: str = "b") -> None:
    """A row whose ``ttl_timestamp`` is already in the past."""
    past = int(time.time()) - 10
    if BACKEND == "dynamodb":
        from actingweb.db.dynamodb.attribute import Attribute

        Attribute(
            id=actor,
            bucket_name=f"{bucket}:{name}",
            bucket=bucket,
            name=name,
            data=data,
            ttl_timestamp=past,
        ).save()
    else:
        import json

        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO attributes (id, bucket_name, bucket, name, data, "
                "ttl_timestamp) VALUES (%s, %s, %s, %s, %s, %s)",
                (actor, f"{bucket}:{name}", bucket, name, json.dumps(data), past),
            )
            conn.commit()


def _stored_ttl(actor: str, name: str, bucket: str = "b") -> int | None:
    if BACKEND == "dynamodb":
        from actingweb.db.dynamodb.attribute import Attribute

        row = Attribute.get(actor, f"{bucket}:{name}", consistent_read=True)
        return None if row.ttl_timestamp is None else int(row.ttl_timestamp)
    from actingweb.db.postgresql.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ttl_timestamp FROM attributes WHERE id = %s AND bucket_name = %s",
            (actor, f"{bucket}:{name}"),
        )
        row = cur.fetchone()
    return None if row is None or row[0] is None else int(row[0])


class TestCreate:
    def test_first_wins_second_loses_and_the_row_is_unchanged(
        self, actor_id: str
    ) -> None:
        assert _create(actor_id, "n", {"who": "first"}) is True
        assert _create(actor_id, "n", {"who": "second"}) is False
        row = _read(actor_id, "n")
        assert row["data"] == {"who": "first"}

    def test_the_name_is_stored(self, actor_id: str) -> None:
        assert _create(actor_id, "named", {"a": 1}) is True
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.attribute import Attribute

            assert (
                Attribute.get(actor_id, "b:named", consistent_read=True).name == "named"
            )
        assert "named" in (_db().get_bucket(actor_id=actor_id, bucket="b") or {})

    def test_an_expired_row_is_replaced_with_the_new_ttl(self, actor_id: str) -> None:
        _seed_expired(actor_id, "n", {"old": True})
        before = int(time.time())
        assert _create(actor_id, "n", {"new": True}, ttl_seconds=60) is True
        assert _read(actor_id, "n")["data"] == {"new": True}
        ttl = _stored_ttl(actor_id, "n")
        assert ttl is not None and ttl >= before + 60

    def test_a_live_ttl_row_is_not_replaced(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}, ttl_seconds=600) is True
        assert _create(actor_id, "n", {"v": 2}, ttl_seconds=600) is False
        assert _read(actor_id, "n")["data"] == {"v": 1}

    def test_a_permanent_row_is_not_replaced(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}) is True
        assert _create(actor_id, "n", {"v": 2}, ttl_seconds=5) is False
        assert _stored_ttl(actor_id, "n") is None

    def test_another_buckets_row_is_never_touched(self, actor_id: str) -> None:
        # Same composite key (bucket:name) from a different (bucket, name)
        # pair: "other:x" cannot collide with "b:..." here, so build the clash
        # by writing the stored key of bucket "b" through bucket "other".
        assert _create(actor_id, "n", {"v": 1}) is True
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.attribute import Attribute

            Attribute(
                id=actor_id,
                bucket_name="b:clash",
                bucket="other",
                name="clash",
                data={"owner": "other"},
                ttl_timestamp=int(time.time()) - 10,
            ).save()
        else:
            import json

            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO attributes (id, bucket_name, bucket, name, data, "
                    "ttl_timestamp) VALUES (%s, 'b:clash', 'other', 'clash', %s, %s)",
                    (actor_id, json.dumps({"owner": "other"}), int(time.time()) - 10),
                )
                conn.commit()
        # Expired, but in another bucket: not replaced, not claimed.
        assert _create(actor_id, "clash", {"owner": "b"}) is False
        assert _stored_ttl(actor_id, "clash") is not None  # row untouched

    def test_ttl_and_timestamp_are_stored(self, actor_id: str) -> None:
        before = int(time.time())
        assert _create(actor_id, "n", {"v": 1}, ttl_seconds=100) is True
        ttl = _stored_ttl(actor_id, "n")
        assert ttl is not None and ttl >= before + 100

    def test_a_missing_name_raises(self) -> None:
        with pytest.raises(ValueError):
            _db().create_attr_if_absent(actor_id="a", bucket="b", name=None, data={})
        with pytest.raises(ValueError):
            _db().create_attr_if_absent(actor_id=None, bucket="b", name="n", data={})
        with pytest.raises(ValueError):
            _db().create_attr_if_absent(actor_id="a", bucket=None, name="n", data={})


class TestFaults:
    def _fault(self) -> Any:
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.attribute import Attribute

            return mock.patch.object(
                Attribute, "save", side_effect=RuntimeError("connection refused")
            )
        mod = _module()
        return mock.patch.object(
            mod, "get_connection", side_effect=RuntimeError("connection refused")
        )

    def test_a_fault_raises_db_error_not_false(self, actor_id: str) -> None:
        with self._fault():
            with pytest.raises(DbError):
                _create(actor_id, "n", {"v": 1})

    def test_a_lost_condition_whose_row_is_ours_is_a_win(self, actor_id: str) -> None:
        """An SDK retry of a create that landed reports a lost condition; the
        stored row is JSON-equal to ours, so it is not reported as lost."""
        data = {"b": 2, "a": 1}
        if BACKEND == "dynamodb":
            from botocore.exceptions import ClientError
            from pynamodb.exceptions import PutError

            from actingweb.db.dynamodb.attribute import Attribute

            real_save = Attribute.save
            cause = ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
                "PutItem",
            )

            def landed_then_reported_lost(self: Any, *a: Any, **k: Any) -> None:
                real_save(self)  # the write landed
                raise PutError("lost", cause)

            with mock.patch.object(Attribute, "save", landed_then_reported_lost):
                assert _create(actor_id, "n", data) is True
        else:
            assert _create(actor_id, "n", data) is True
            # Same data again, key order differs: JSONB-equal, so a win.
            assert _create(actor_id, "n", {"a": 1, "b": 2}) is True

    def test_a_lost_condition_with_different_data_is_lost(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}) is True
        assert _create(actor_id, "n", {"v": 2}) is False

    def test_a_fault_while_reading_back_raises(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}) is True
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.attribute import Attribute

            with mock.patch.object(
                Attribute, "get", side_effect=RuntimeError("read failed")
            ):
                with pytest.raises(DbError):
                    _create(actor_id, "n", {"v": 2})
        else:
            mod = _module()
            real = mod.get_connection
            calls = {"n": 0}

            def second_call_fails() -> Any:
                calls["n"] += 1
                raise RuntimeError("down")

            with mock.patch.object(mod, "get_connection", second_call_fails):
                with pytest.raises(DbError):
                    _create(actor_id, "n", {"v": 2})
            assert mod.get_connection is real


class TestVanishedWinner:
    @pytest.mark.skipif(BACKEND != "dynamodb", reason="DynamoDB conditional put")
    def test_a_winner_that_vanished_before_the_read_back_is_retried(
        self, actor_id: str
    ) -> None:
        """A lost condition whose winning row is gone by the read-back means
        the name is free: the write is tried once more, not reported lost."""
        from botocore.exceptions import ClientError
        from pynamodb.exceptions import PutError

        from actingweb.db.dynamodb.attribute import Attribute

        cause = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
            "PutItem",
        )
        real_save = Attribute.save
        calls = {"n": 0}

        def lost_once(self: Any, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PutError("lost", cause)
            return real_save(self, *a, **k)

        with mock.patch.object(Attribute, "save", lost_once):
            assert _create(actor_id, "n", {"v": 1}) is True
        assert calls["n"] == 2
        row = _read(actor_id, "n")
        assert row is not None and row["data"] == {"v": 1}


class TestRaces:
    def test_two_threads_with_a_nonce_have_exactly_one_winner(
        self, actor_id: str
    ) -> None:
        results: list[bool] = []
        barrier = threading.Barrier(2)

        def run(nonce: str) -> None:
            barrier.wait()
            results.append(_create(actor_id, "race", {"nonce": nonce}))

        threads = [
            threading.Thread(target=run, args=(uuid.uuid4().hex,)) for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [False, True]

    def test_identical_data_makes_both_callers_win(self, actor_id: str) -> None:
        """The documented consequence: use a nonce for one winner."""
        assert _create(actor_id, "same", {"v": 1}) is True
        assert _create(actor_id, "same", {"v": 1}) is True


class TestAttributesWrapper:
    def _store(self, actor_id: str) -> Attributes:
        config_mod = importlib.import_module("actingweb.config")
        config = config_mod.Config(unique_creator=False)
        return Attributes(actor_id=actor_id, bucket="b", config=config)

    def test_a_win_caches_our_row(self, actor_id: str) -> None:
        store = self._store(actor_id)
        assert store.create_attr_if_absent("n", {"v": 1}) is True
        row = store.get_attr("n")
        assert row is not None and row["data"] == {"v": 1}

    def test_a_loss_reads_the_winners_row_through(self, actor_id: str) -> None:
        store = self._store(actor_id)
        assert store.get_attr("n") is None  # caches a miss
        assert _create(actor_id, "n", {"winner": True}) is True  # someone else wins
        assert store.create_attr_if_absent("n", {"v": 2}) is False
        row = store.get_attr("n")
        assert row is not None and row["data"] == {"winner": True}

    def test_a_missing_name_raises(self, actor_id: str) -> None:
        with pytest.raises(ValueError):
            self._store(actor_id).create_attr_if_absent(None, {})

    def test_a_fault_propagates(self, actor_id: str) -> None:
        store = self._store(actor_id)
        with mock.patch.object(
            store.dbprop, "create_attr_if_absent", side_effect=DbError("x")
        ):
            with pytest.raises(DbError):
                store.create_attr_if_absent("n", {"v": 1})


class TestOlderConditionalsKeepFalseOnFault:
    """D10: ``consume_once`` relies on False-on-fault for these two."""

    def _fault(self) -> Any:
        if BACKEND == "dynamodb":
            from actingweb.db.dynamodb.attribute import Attribute

            return mock.patch.object(
                Attribute, "get", side_effect=RuntimeError("connection refused")
            )
        return mock.patch.object(
            _module(), "get_connection", side_effect=RuntimeError("connection refused")
        )

    def test_conditional_update_answers_false_on_a_fault(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}) is True
        with self._fault():
            assert (
                _db().conditional_update_attr(
                    actor_id=actor_id,
                    bucket="b",
                    name="n",
                    old_data={"v": 1},
                    new_data={"v": 2},
                )
                is False
            )

    def test_delete_conditional_answers_false_on_a_fault(self, actor_id: str) -> None:
        assert _create(actor_id, "n", {"v": 1}) is True
        with self._fault():
            assert (
                _db().delete_attr_conditional(actor_id=actor_id, bucket="b", name="n")
                is False
            )
