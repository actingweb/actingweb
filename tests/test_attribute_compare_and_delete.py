"""A public compare-and-delete on ``Attributes``, and one JSON value compare
for every conditional attribute write
(thoughts/plans/2026-11-25-attribute-compare-and-delete.md).

``Attributes.delete_attr_if_data_equals(name, expected)`` deletes the row only
while it holds ``expected`` by JSON value: True when this call deleted it,
False when the row holds something else or is gone, ``DbError`` on a fault.
Runs on the backend ``DATABASE_BACKEND`` selects (both in the Full tier).
"""

from __future__ import annotations

import contextlib
import datetime
import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest

from actingweb.attribute import Attributes
from actingweb.config import Config
from actingweb.db import get_attribute
from actingweb.db.exceptions import DbError, UnserialisableValue
from tests._adoption_helpers import make_config, seam_fault

BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")
BUCKET = "cad"
dynamodb_only = pytest.mark.skipif(
    BACKEND != "dynamodb", reason="DynamoDB's read-then-write window"
)


@pytest.fixture
def config() -> Config:
    return make_config(database=BACKEND)


@pytest.fixture
def actor_id(config: Config) -> Iterator[str]:
    actor = "cad" + uuid.uuid4().hex[:16]
    yield actor
    db = get_attribute(config)
    for bucket in (BUCKET, "a", "a:b"):
        db.delete_bucket(actor_id=actor, bucket=bucket)


def _attrs(config: Config, actor: str, bucket: str = BUCKET) -> Attributes:
    return Attributes(actor_id=actor, bucket=bucket, config=config)


def _row(config: Config, actor: str, name: str, bucket: str = BUCKET) -> Any:
    """The stored row (``{"data": ..., ...}``), or None when there is none."""
    return get_attribute(config).get_attr(actor_id=actor, bucket=bucket, name=name)


def _put(
    config: Config, actor: str, name: str, data: Any, bucket: str = BUCKET
) -> None:
    assert get_attribute(config).set_attr(
        actor_id=actor, bucket=bucket, name=name, data=data
    )


@contextlib.contextmanager
def _untouchable() -> Iterator[None]:
    """Fails the test if the call reaches the store."""

    def reached(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the store was touched")

    if BACKEND == "postgresql":
        import actingweb.db.postgresql.attribute as pg

        with patch.object(pg, "get_connection", reached):
            yield
        return
    from actingweb.db.dynamodb.attribute import Attribute

    with (
        patch.object(Attribute, "get", reached),
        patch.object(Attribute, "delete", reached),
        patch.object(Attribute, "update", reached),
        patch.object(Attribute, "save", reached),
    ):
        yield


@contextlib.contextmanager
def _after_the_read(action: Callable[[], None]) -> Iterator[None]:
    """DynamoDB: ``action`` runs right after the backend's consistent read,
    before its conditional write (another writer in the window)."""
    from actingweb.db.dynamodb.attribute import Attribute

    real = Attribute.get

    def get_then_act(*a: Any, **k: Any) -> Any:
        item = real(*a, **k)
        action()
        return item

    with patch.object(Attribute, "get", get_then_act):
        yield


@pytest.mark.integration
class TestPublicCompareAndDelete:
    def test_deletes_when_the_value_matches(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-1"""
        _put(config, actor_id, "r", {"v": 1, "s": "x"})
        attrs = _attrs(config, actor_id)
        assert attrs.delete_attr_if_data_equals("r", {"v": 1, "s": "x"}) is True
        assert _row(config, actor_id, "r") is None

    def test_a_deleted_row_is_absent_on_a_loaded_instance(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-2"""
        _put(config, actor_id, "r", {"v": 1})
        attrs = _attrs(config, actor_id)
        assert "r" in (attrs.get_bucket() or {})
        assert attrs.delete_attr_if_data_equals("r", {"v": 1}) is True
        assert attrs.get_attr("r") is None
        assert "r" not in (attrs.get_bucket() or {})

    def test_key_order_does_not_matter(self, config: Config, actor_id: str) -> None:
        """AC-3: flat and nested."""
        _put(config, actor_id, "r", {"a": 1, "b": {"x": 1, "y": 2}})
        attrs = _attrs(config, actor_id)
        assert attrs.delete_attr_if_data_equals("r", {"b": {"y": 2, "x": 1}, "a": 1})
        assert _row(config, actor_id, "r") is None

    def test_a_float_matches_an_equal_integer(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-4"""
        _put(config, actor_id, "r", {"n": 1})
        assert _attrs(config, actor_id).delete_attr_if_data_equals("r", {"n": 1.0})
        assert _row(config, actor_id, "r") is None

    def test_another_value_is_kept(self, config: Config, actor_id: str) -> None:
        """AC-5"""
        _put(config, actor_id, "r", {"v": 2})
        assert (
            _attrs(config, actor_id).delete_attr_if_data_equals("r", {"v": 1}) is False
        )
        assert _row(config, actor_id, "r")["data"] == {"v": 2}

    def test_an_absent_row_answers_false(self, config: Config, actor_id: str) -> None:
        """AC-6"""
        assert (
            _attrs(config, actor_id).delete_attr_if_data_equals("nothing", {"v": 1})
            is False
        )

    def test_another_buckets_row_is_kept(self, config: Config, actor_id: str) -> None:
        """AC-7: bucket ``a`` name ``b:c`` and bucket ``a:b`` name ``c`` share
        a key."""
        _put(config, actor_id, "c", {"v": 1}, bucket="a:b")
        attrs = _attrs(config, actor_id, bucket="a")
        assert attrs.delete_attr_if_data_equals("b:c", {"v": 1}) is False
        assert _row(config, actor_id, "c", bucket="a:b")["data"] == {"v": 1}

    @pytest.mark.parametrize("seam", ["get", "delete"])
    def test_a_fault_raises(self, config: Config, actor_id: str, seam: str) -> None:
        """AC-8"""
        _put(config, actor_id, "r", {"v": 1})
        with (
            seam_fault(config, "attribute", "Attribute", seam),
            pytest.raises(DbError),
        ):
            _attrs(config, actor_id).delete_attr_if_data_equals("r", {"v": 1})
        assert _row(config, actor_id, "r")["data"] == {"v": 1}

    def test_a_fault_unloads_the_cached_entry(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-9"""
        _put(config, actor_id, "r", {"v": 1})
        attrs = _attrs(config, actor_id)
        attrs.get_bucket()
        with (
            seam_fault(config, "attribute", "Attribute", "get"),
            pytest.raises(DbError),
        ):
            attrs.delete_attr_if_data_equals("r", {"v": 1})
        _put(config, actor_id, "r", {"v": 2})
        row = attrs.get_attr("r")
        assert row is not None and row["data"] == {"v": 2}

    @pytest.mark.parametrize(
        "bad", [{"when": datetime.datetime(2026, 11, 25)}, {1, 2}], ids=["dt", "set"]
    )
    def test_a_value_json_cannot_encode_is_refused(
        self, config: Config, actor_id: str, bad: Any
    ) -> None:
        """AC-10"""
        attrs = _attrs(config, actor_id)
        with _untouchable(), pytest.raises(UnserialisableValue):
            attrs.delete_attr_if_data_equals("r", bad)

    def test_a_missing_name_is_refused(self, config: Config, actor_id: str) -> None:
        """AC-11"""
        with pytest.raises(ValueError):
            _attrs(config, actor_id).delete_attr_if_data_equals("", {"v": 1})

    def test_a_write_between_read_and_delete_wins(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-12: DynamoDB reads, compares, then deletes on a condition; a
        writer in between makes the delete lose. PostgreSQL compares in its
        one DELETE, so its window is a value written first."""
        _put(config, actor_id, "r", {"v": 1})
        attrs = _attrs(config, actor_id)
        if BACKEND == "dynamodb":
            with _after_the_read(lambda: _put(config, actor_id, "r", {"v": 2})):
                assert attrs.delete_attr_if_data_equals("r", {"v": 1}) is False
        else:
            _put(config, actor_id, "r", {"v": 2})
            assert attrs.delete_attr_if_data_equals("r", {"v": 1}) is False
        assert _row(config, actor_id, "r")["data"] == {"v": 2}

    def test_true_is_not_one(self, config: Config, actor_id: str) -> None:
        """AC-15"""
        _put(config, actor_id, "r", {"done": True})
        assert (
            _attrs(config, actor_id).delete_attr_if_data_equals("r", {"done": 1})
            is False
        )
        assert _row(config, actor_id, "r")["data"] == {"done": True}

    @pytest.mark.parametrize("maker", ["create_attr_if_absent", "conditional_update"])
    def test_a_null_row_matches_none(
        self, config: Config, actor_id: str, maker: str
    ) -> None:
        """AC-17: DynamoDB stores null without a ``data`` attribute
        (``create_attr_if_absent``) or as ``data: {NULL: true}``
        (``conditional_update_attr``); both match ``None``."""
        attrs = _attrs(config, actor_id)
        if maker == "create_attr_if_absent":
            assert attrs.create_attr_if_absent(name="r", data=None)
        else:
            _put(config, actor_id, "r", {"v": 1})
            assert attrs.conditional_update_attr(
                name="r", old_data={"v": 1}, new_data=None
            )
        row = _row(config, actor_id, "r")
        assert row is not None and row["data"] is None
        assert attrs.delete_attr_if_data_equals("r", None) is True
        assert _row(config, actor_id, "r") is None

    def test_a_loss_unloads_the_cached_entry(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-18"""
        _put(config, actor_id, "r", {"v": 1})
        attrs = _attrs(config, actor_id)
        attrs.get_bucket()
        _put(config, actor_id, "r", {"v": 2})
        assert attrs.delete_attr_if_data_equals("r", {"v": 1}) is False
        row = attrs.get_attr("r")
        assert row is not None and row["data"] == {"v": 2}

    @pytest.mark.parametrize("number", [float("nan"), float("inf")], ids=["nan", "inf"])
    def test_a_non_finite_number_is_refused(
        self, config: Config, actor_id: str, number: float
    ) -> None:
        """AC-19"""
        attrs = _attrs(config, actor_id)
        with _untouchable(), pytest.raises(UnserialisableValue):
            attrs.delete_attr_if_data_equals("r", {"x": number})

    def test_a_tuple_and_an_int_key_match(self, config: Config, actor_id: str) -> None:
        """AC-20: the caller's value is compared as its JSON encoding."""
        _put(config, actor_id, "r", {"1": "x", "t": [1, 2]})
        assert _attrs(config, actor_id).delete_attr_if_data_equals(
            "r", {1: "x", "t": (1, 2)}
        )
        assert _row(config, actor_id, "r") is None

    @pytest.mark.parametrize(
        "value", [{"s": "a\ud800b"}, "a\ud800b"], ids=["dict", "string"]
    )
    def test_a_surrogate_in_expected_is_not_a_fault(
        self, config: Config, actor_id: str, value: Any
    ) -> None:
        """AC-21: stored data was sanitised on write, and so is ``expected``."""
        attrs = _attrs(config, actor_id)
        assert attrs.set_attr(name="r", data=value)
        assert attrs.delete_attr_if_data_equals("r", value) is True
        assert _row(config, actor_id, "r") is None

    def test_the_documented_sweep_runs(self, config: Config, actor_id: str) -> None:
        """docs/sdk/attributes-buckets.rst, "Deleting only what you read":
        a sweep over a copy of ``get_bucket()`` deletes what it read and
        keeps a row renewed in between."""
        for name, expires in (("old1", 1), ("old2", 2), ("live", 99)):
            _put(config, actor_id, name, {"expires_at": expires})
        records = _attrs(config, actor_id)
        bucket = records.get_bucket() or {}
        _put(config, actor_id, "old2", {"expires_at": 100})  # renewed meanwhile
        for name, row in list(bucket.items()):
            if row["data"]["expires_at"] < 50:
                records.delete_attr_if_data_equals(name, row["data"])
        assert _row(config, actor_id, "old1") is None
        assert _row(config, actor_id, "old2")["data"] == {"expires_at": 100}
        assert _row(config, actor_id, "live")["data"] == {"expires_at": 99}


@pytest.mark.integration
class TestBackendCompare:
    def test_swap_matches_whatever_the_key_order(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-13"""
        _put(config, actor_id, "r", {"a": 1, "b": {"x": 1, "y": 2}})
        db = get_attribute(config)
        assert (
            db.set_attr_if_data_equals(
                actor_id, BUCKET, "r", {"b": {"y": 2, "x": 1}, "a": 1}, {"v": "new"}
            )
            is True
        )
        assert _row(config, actor_id, "r")["data"] == {"v": "new"}

    @dynamodb_only
    @pytest.mark.parametrize("method", ["delete", "set"])
    def test_a_string_takes_one_conditional_write(
        self, config: Config, actor_id: str, method: str
    ) -> None:
        """AC-14: list storage's strings keep a single conditional write."""
        from actingweb.db.dynamodb.attribute import Attribute

        _put(config, actor_id, "r", "a string")
        calls: list[str] = []
        real_get, real_delete, real_update = (
            Attribute.get,
            Attribute.delete,
            Attribute.update,
        )

        def get(*a: Any, **k: Any) -> Any:
            calls.append("get")
            return real_get(*a, **k)

        def delete(self: Any, *a: Any, **k: Any) -> Any:
            calls.append("delete")
            return real_delete(self, *a, **k)

        def update(self: Any, *a: Any, **k: Any) -> Any:
            calls.append("update")
            return real_update(self, *a, **k)

        db = get_attribute(config)
        with (
            patch.object(Attribute, "get", get),
            patch.object(Attribute, "delete", delete),
            patch.object(Attribute, "update", update),
        ):
            if method == "delete":
                assert db.delete_attr_if_data_equals(actor_id, BUCKET, "r", "a string")
            else:
                assert db.set_attr_if_data_equals(
                    actor_id, BUCKET, "r", "a string", "another"
                )
        assert calls == (["delete"] if method == "delete" else ["update"])

    def test_swap_keeps_another_value(self, config: Config, actor_id: str) -> None:
        """AC-22"""
        _put(config, actor_id, "r", {"v": 2})
        db = get_attribute(config)
        assert (
            db.set_attr_if_data_equals(actor_id, BUCKET, "r", {"v": 1}, {"v": 3})
            is False
        )
        assert _row(config, actor_id, "r")["data"] == {"v": 2}

    @dynamodb_only
    def test_a_write_between_read_and_swap_wins(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-23"""
        _put(config, actor_id, "r", {"v": 1})
        db = get_attribute(config)
        with _after_the_read(lambda: _put(config, actor_id, "r", {"v": 2})):
            assert (
                db.set_attr_if_data_equals(actor_id, BUCKET, "r", {"v": 1}, {"v": 3})
                is False
            )
        assert _row(config, actor_id, "r")["data"] == {"v": 2}

    def test_a_swap_read_fault_raises(self, config: Config, actor_id: str) -> None:
        """AC-24"""
        _put(config, actor_id, "r", {"v": 1})
        db = get_attribute(config)
        with (
            seam_fault(config, "attribute", "Attribute", "get"),
            pytest.raises(DbError),
        ):
            db.set_attr_if_data_equals(actor_id, BUCKET, "r", {"v": 1}, {"v": 3})
        assert _row(config, actor_id, "r")["data"] == {"v": 1}


TYPE_NAMED = [{"S": "x"}, {"N": 5}, {"M": {}}, {"NULL": True}, {"L": [1]}]


@pytest.mark.integration
@pytest.mark.parametrize("value", TYPE_NAMED, ids=lambda v: next(iter(v)))
class TestValuesNamedLikeDynamoDBTypes:
    """AC-32 (added in iteration 1): a dict whose one key is a DynamoDB type
    name (``S``, ``N``, ``M``...) is data like any other. PynamoDB took it
    as an already-serialised value in a condition or an update, so a compare
    never matched or faulted, and an update wrote a row that could no
    longer be read (which also failed ``delete_bucket``)."""

    def test_the_compare_and_delete_matches_it(
        self, config: Config, actor_id: str, value: Any
    ) -> None:
        _put(config, actor_id, "r", value)
        assert _attrs(config, actor_id).delete_attr_if_data_equals("r", value) is True
        assert _row(config, actor_id, "r") is None

    def test_the_swap_matches_and_writes_it(
        self, config: Config, actor_id: str, value: Any
    ) -> None:
        _put(config, actor_id, "r", value)
        db = get_attribute(config)
        assert db.set_attr_if_data_equals(actor_id, BUCKET, "r", value, value) is True
        assert _row(config, actor_id, "r")["data"] == value

    def test_a_conditional_update_writes_a_readable_row(
        self, config: Config, actor_id: str, value: Any
    ) -> None:
        _put(config, actor_id, "r", {"v": 1})
        attrs = _attrs(config, actor_id)
        assert attrs.conditional_update_attr(
            name="r", old_data={"v": 1}, new_data=value
        )
        assert _row(config, actor_id, "r")["data"] == value
        assert attrs.conditional_update_attr(
            name="r", old_data=value, new_data={"v": 2}
        )
        assert _row(config, actor_id, "r")["data"] == {"v": 2}


@pytest.mark.integration
class TestIterationThree:
    """Low findings of the 2026-11-25 verification (iteration 3)."""

    @pytest.mark.parametrize(
        ("stored", "expected", "match"),
        [(10**30, 1e30, True), (2**70, float(2**70), False)],
        ids=["equal-as-decimal", "equal-as-binary-only"],
    )
    def test_large_numbers_compare_as_jsonb_does(
        self,
        config: Config,
        actor_id: str,
        stored: int,
        expected: float,
        match: bool,
    ) -> None:
        """AC-36: an int and a float compare as the decimals their JSON
        text names, as PostgreSQL's ``numeric`` does: ``1e30`` equals
        ``10**30``; ``float(2**70)`` encodes as ``1.1805916207174113e+21``
        and does not equal ``2**70``."""
        _put(config, actor_id, "r", {"n": stored})
        attrs = _attrs(config, actor_id)
        assert attrs.delete_attr_if_data_equals("r", {"n": expected}) is match

    def test_a_circular_value_is_refused_as_unserialisable(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-37: refused before the sanitiser recurses."""
        circular: dict[str, Any] = {}
        circular["self"] = circular
        with _untouchable(), pytest.raises(UnserialisableValue):
            _attrs(config, actor_id).delete_attr_if_data_equals("r", circular)

    @dynamodb_only
    def test_a_row_under_another_name_is_not_deleted(
        self, config: Config, actor_id: str
    ) -> None:
        """AC-38: the stored-data condition names the row's ``name`` too: a
        row at the key whose ``name`` differs (written outside the library)
        is never matched by a null compare."""
        from actingweb.db.dynamodb.attribute import Attribute

        Attribute(
            id=actor_id, bucket_name=f"{BUCKET}:r", bucket=BUCKET, name="other"
        ).save()
        assert _attrs(config, actor_id).delete_attr_if_data_equals("r", None) is False
        assert Attribute.get(actor_id, f"{BUCKET}:r", consistent_read=True)


@pytest.mark.integration
@dynamodb_only
class TestRowsTheOldUpdateCorrupted:
    """AC-40 (added in iteration 8): a row that 3.15.1 to 4.0.0rc3 wrote
    with a type-named dict through an update holds text JSON cannot read.
    The deletes read keys only, so such a row can be removed."""

    @staticmethod
    def _corrupt(actor: str, name: str = "bad") -> None:
        from actingweb.db.dynamodb.attribute import Attribute

        _put(make_config(database="dynamodb"), actor, name, {"v": 1})
        # The update lands; reading the returned row back is what fails.
        with contextlib.suppress(ValueError):
            Attribute(id=actor, bucket_name=f"{BUCKET}:{name}").update(
                actions=[Attribute.data.set({"S": "not json"})]
            )

    def test_delete_attr_removes_it(self, config: Config, actor_id: str) -> None:
        self._corrupt(actor_id)
        assert _attrs(config, actor_id).delete_attr("bad") is True
        assert get_attribute(config).get_bucket(actor_id=actor_id, bucket=BUCKET) == {}

    def test_delete_bucket_removes_it(self, config: Config, actor_id: str) -> None:
        self._corrupt(actor_id)
        _put(config, actor_id, "good", {"v": 1})
        db = get_attribute(config)
        assert db.delete_bucket(actor_id=actor_id, bucket=BUCKET) is True
        assert db.get_bucket(actor_id=actor_id, bucket=BUCKET) == {}

    def test_a_conditional_delete_removes_it(
        self, config: Config, actor_id: str
    ) -> None:
        self._corrupt(actor_id)
        db = get_attribute(config)
        assert db.delete_attr_conditional(actor_id=actor_id, bucket=BUCKET, name="bad")
        assert db.get_bucket(actor_id=actor_id, bucket=BUCKET) == {}

    def test_deleting_all_of_an_actor_removes_it(
        self, config: Config, actor_id: str
    ) -> None:
        self._corrupt(actor_id)
        config.DbAttribute.DbAttributeBucketList().delete(actor_id=actor_id)  # type: ignore[attr-defined]
        assert get_attribute(config).get_bucket(actor_id=actor_id, bucket=BUCKET) == {}
