"""The attribute list primitives' contract
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2), written once
and run over the in-memory double and the run's real backend (DynamoDB or
PostgreSQL, from ``DATABASE_BACKEND``), plus the composite-key collision on
the real backend for the new primitives and the existing ``set_attr`` and
``create_attr_if_absent``.

Lives under tests/integration/ because PostgreSQL needs the migrated schema
the session fixtures provision.
"""

import json
import os
import uuid
from typing import Any

import pytest

from actingweb.db import get_attribute
from actingweb.db.exceptions import AttributeKeyCollision
from actingweb.interface.app import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"
    return ActingWebApp(
        aw_type="urn:actingweb:test:attribute_list_primitives",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    ).with_unique_creator(False)


@pytest.fixture(params=["double", "backend"])
def db(request: pytest.FixtureRequest) -> Any:
    if request.param == "double":
        from tests.mcp_token_double import make_config

        config, _ = make_config()
        return get_attribute(config)
    aw_app = request.getfixturevalue("aw_app")
    return get_attribute(aw_app.get_config())


@pytest.fixture
def backend_db(aw_app: Any) -> Any:
    return get_attribute(aw_app.get_config())


@pytest.fixture
def actor() -> str:
    return f"prim-{uuid.uuid4().hex}"


B = "lists"


class TestPrimitiveContract:
    def test_create_answers_true_once(self, db, actor):
        assert db.create_attr_if_not_exists(actor, B, "list:x-#a", "v1") is True
        assert db.create_attr_if_not_exists(actor, B, "list:x-#a", "v1") is False
        assert db.create_attr_if_not_exists(actor, B, "list:x-#a", "v2") is False
        assert db.get_attr(actor_id=actor, bucket=B, name="list:x-#a")["data"] == "v1"

    def test_batch_create_answers_the_names_it_created(self, db, actor):
        db.put_attr(actor, B, "list:x-#b", "old")
        created = db.create_attrs_if_not_exist(
            actor, B, {"list:x-#a": "1", "list:x-#b": "2", "list:x-#c": "3"}
        )
        assert created == {"list:x-#a", "list:x-#c"}
        assert db.create_attrs_if_not_exist(actor, B, {}) == set()
        rows = db.get_attr_range(actor, B, "list:x-#", "list:x-#~")
        assert rows == {"list:x-#a": "1", "list:x-#b": "old", "list:x-#c": "3"}

    def test_compare_and_swap(self, db, actor):
        db.put_attr(actor, B, "list:x-meta", '{"a": 1}')
        assert (
            db.set_attr_if_data_equals(actor, B, "list:x-meta", '{"a": 2}', "x")
            is False
        )
        assert (
            db.set_attr_if_data_equals(actor, B, "list:x-meta", '{"a": 1}', "y") is True
        )
        assert db.set_attr_if_data_equals(actor, B, "list:x-none", "y", "z") is False
        assert db.get_attr(actor_id=actor, bucket=B, name="list:x-meta")["data"] == "y"

    def test_conditional_delete(self, db, actor):
        db.put_attr(actor, B, "list:x-#a", "v")
        assert db.delete_attr_if_data_equals(actor, B, "list:x-#a", "other") is False
        assert db.delete_attr_if_data_equals(actor, B, "list:x-#a", "v") is True
        assert db.delete_attr_if_data_equals(actor, B, "list:x-#a", "v") is False
        assert db.get_attr(actor_id=actor, bucket=B, name="list:x-#a") is None

    def test_ranges_by_byte_order(self, db, actor):
        # "B" < "a" < "é" by bytes; a locale collation would put "a" first.
        for suffix in ("B", "a", "é", "Z0", "z"):
            db.put_attr(actor, B, f"list:x-#{suffix}", suffix)
        rows = db.get_attr_range(actor, B, "list:x-#", "list:x-#\U0010ffff")
        assert (
            list(rows)
            == sorted(rows)
            == [
                "list:x-#B",
                "list:x-#Z0",
                "list:x-#a",
                "list:x-#z",
                "list:x-#é",
            ]
        )
        keys = db.get_attr_range(
            actor, B, "list:x-#", "list:x-#\U0010ffff", keys_only=True
        )
        assert set(keys) == set(rows) and set(keys.values()) == {""}
        assert (
            db.get_last_attr_in_range(actor, B, "list:x-#", "list:x-#z") == "list:x-#z"
        )
        assert (
            db.get_last_attr_in_range(actor, B, "list:x-#", "list:x-#a") == "list:x-#a"
        )
        assert db.get_last_attr_in_range(actor, B, "list:y", "list:z") is None

    def test_an_empty_or_inverted_range_is_empty(self, db, actor):
        db.put_attr(actor, B, "list:x-#a", "v")
        assert db.get_attr_range(actor, B, "list:x-#b", "list:x-#a") == {}
        assert db.get_last_attr_in_range(actor, B, "list:x-#b", "list:x-#a") is None
        assert db.get_attr_range(actor, B, "list:q", "list:r") == {}

    def test_prefix(self, db, actor):
        db.put_attr(actor, B, "list:x-meta", "m")
        db.put_attr(actor, B, "list:x-#a", "a")
        db.put_attr(actor, B, "list:xy-meta", "other")
        db.put_attr(actor, B, "scalar", {"v": 1})
        assert db.get_attr_prefix(actor, B, "list:x-") == {
            "list:x-#a": "a",
            "list:x-meta": "m",
        }
        assert db.get_attr_prefix(actor, B, "scal") == {"scalar": {"v": 1}}

    @pytest.mark.parametrize("count", [0, 1, 30])
    def test_batch_delete(self, db, actor, count):
        names = [f"list:x-#a{i:03d}" for i in range(count)]
        for name in names:
            db.put_attr(actor, B, name, "v")
        db.put_attr(actor, B, "list:x-meta", "keep")
        db.delete_attrs(actor, B, names + ["list:x-#absent"])
        assert db.get_attr_range(actor, B, "list:x-", "list:x-\U0010ffff") == {
            "list:x-meta": "keep"
        }

    @pytest.mark.parametrize("falsy", ["", 0, None, [], {}])
    def test_put_refuses_falsy_data(self, db, actor, falsy):
        with pytest.raises(ValueError):
            db.put_attr(actor, B, "list:x-#a", falsy)

    def test_string_items_that_look_falsy_are_stored(self, db, actor):
        for i, value in enumerate(['"0"', "null", "[]", '""', "0", "false"]):
            db.put_attr(actor, B, f"list:x-#a{i}", value)
        rows = db.get_attr_range(actor, B, "list:x-#", "list:x-#~")
        assert list(rows.values()) == ['"0"', "null", "[]", '""', "0", "false"]

    def test_an_expired_row_is_still_a_row(self, backend_db, actor):
        """TTL is ignored: a create over an expired row answers False."""
        backend_db.set_attr(
            actor_id=actor, bucket=B, name="list:x-#a", data="old", ttl_seconds=-7200
        )
        assert (
            backend_db.create_attr_if_not_exists(actor, B, "list:x-#a", "new") is False
        )

    def test_consistent_read_is_passed_through(self, db, actor):
        db.put_attr(actor, B, "list:x-#a", "v")
        assert db.get_attr_range(
            actor, B, "list:x-#", "list:x-#~", consistent_read=False
        ) in ({}, {"list:x-#a": "v"})

    def test_a_range_over_one_megabyte_is_paged(self, backend_db, actor):
        body = "x" * 100_000
        names = [f"list:big-#a{i:02d}" for i in range(14)]
        for name in names:
            backend_db.put_attr(actor, B, name, body)
        rows = backend_db.get_attr_range(actor, B, "list:big-#", "list:big-#~")
        assert list(rows) == names
        assert (
            backend_db.get_last_attr_in_range(actor, B, "list:big-#", "list:big-#~")
            == names[-1]
        )

    def test_the_backend_declares_its_row_cap(self, backend_db):
        cap = getattr(type(backend_db), "MAX_ROW_BYTES", "absent")
        assert cap == (409_600 if DATABASE_BACKEND == "dynamodb" else None)


class TestCompositeKeyCollision:
    """Bucket ``a`` name ``b:c`` and bucket ``a:b`` name ``c`` share the key
    ``a:b:c`` on both backends; neither ever touches the other's row."""

    @pytest.fixture
    def held(self, backend_db, actor):
        backend_db.set_attr(
            actor_id=actor, bucket="a:b", name="c", data={"v": "theirs"}
        )
        return backend_db

    def _theirs(self, db: Any, actor: str) -> Any:
        return db.get_attr(actor_id=actor, bucket="a:b", name="c")["data"]

    def test_put_raises(self, held, actor):
        with pytest.raises(AttributeKeyCollision):
            held.put_attr(actor, "a", "b:c", "mine")
        assert self._theirs(held, actor) == {"v": "theirs"}

    def test_create_raises(self, held, actor):
        with pytest.raises(AttributeKeyCollision):
            held.create_attr_if_not_exists(actor, "a", "b:c", "mine")
        with pytest.raises(AttributeKeyCollision):
            held.create_attrs_if_not_exist(actor, "a", {"b:c": "mine"})
        assert self._theirs(held, actor) == {"v": "theirs"}

    def test_a_batch_create_that_collides_names_the_colliding_key(self, held, actor):
        with pytest.raises(AttributeKeyCollision) as caught:
            held.create_attrs_if_not_exist(actor, "a", {"a-ok": "1", "b:c": "2"})
        assert caught.value.name == "b:c"
        if DATABASE_BACKEND == "postgresql":
            # One statement, rolled back: none of the batch is created.
            assert held.get_attr(actor_id=actor, bucket="a", name="a-ok") is None

    def test_set_attr_raises(self, held, actor):
        with pytest.raises(AttributeKeyCollision):
            held.set_attr(actor_id=actor, bucket="a", name="b:c", data={"v": "mine"})
        assert self._theirs(held, actor) == {"v": "theirs"}

    def test_create_attr_if_absent_answers_false(self, held, actor):
        assert (
            held.create_attr_if_absent(
                actor_id=actor, bucket="a", name="b:c", data={"v": "mine"}
            )
            is False
        )
        assert self._theirs(held, actor) == {"v": "theirs"}

    def test_conditional_writes_and_deletes_do_not_match(self, held, actor):
        stored = json.dumps({"v": "theirs"})
        assert held.set_attr_if_data_equals(actor, "a", "b:c", stored, "x") is False
        assert held.delete_attr_if_data_equals(actor, "a", "b:c", stored) is False
        held.delete_attrs(actor, "a", ["b:c"])
        assert self._theirs(held, actor) == {"v": "theirs"}

    def test_reads_do_not_return_it(self, held, actor):
        assert held.get_attr(actor_id=actor, bucket="a", name="b:c") is None
        assert held.get_attr_prefix(actor, "a", "b:") == {}
        assert held.get_attr_range(actor, "a", "b", "b:\U0010ffff") == {}
        assert held.get_last_attr_in_range(actor, "a", "b", "b:\U0010ffff") is None

    def test_a_range_whose_greatest_key_is_another_buckets(self, backend_db, actor):
        backend_db.put_attr(actor, "a", "list:x-#a", "mine")
        backend_db.set_attr(actor_id=actor, bucket="a:list", name="x-#b", data="theirs")
        assert (
            backend_db.get_last_attr_in_range(actor, "a", "list:x-#", "list:x-#~")
            == "list:x-#a"
        )
        assert backend_db.get_attr_range(actor, "a", "list:x-#", "list:x-#~") == {
            "list:x-#a": "mine"
        }
