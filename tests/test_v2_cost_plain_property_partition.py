"""
Phase 4 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): plain-property reads stop paying for the
actor's list rows.

DynamoDB: DbPropertyList.fetch() used to Query the whole partition and
filter out "list:"-prefixed rows client-side, so a read of 5 plain
properties paid for every list item row too (measured: 254 RCU for a
1,190-row partition, 241 of which is one list). Fixed with a pair of
range-constrained Queries -- DynamoDB cannot OR on a sort key, so
excluding one contiguous range takes two Queries covering everything
below and everything above it.

PostgreSQL: the same client-side filter, fixed with `NOT LIKE 'list:%'`
in the query itself -- collation-proof, unlike a range comparison (text
ordering is collation-dependent and does not always agree with byte
order on punctuation).
"""

import os
import uuid

import pytest


@pytest.fixture
def config():
    from actingweb.config import Config

    backend = os.getenv("DATABASE_BACKEND", "dynamodb")
    return Config(database=backend)


@pytest.fixture
def actor_id():
    return f"v2cost-partition-{uuid.uuid4()}"


class TestDynamoDBPlainPropertyFetch:
    @pytest.fixture(autouse=True)
    def _require_dynamodb(self):
        if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
            pytest.skip("DynamoDB-only test")

    def test_returns_only_plain_properties_and_never_queries_list_rows(
        self, config, actor_id
    ):
        from unittest import mock

        from actingweb.db.dynamodb.property import DbProperty, DbPropertyList, Property

        db = DbProperty()
        for i in range(5):
            db.set(actor_id=actor_id, name=f"prop{i}", value=f"val{i}")

        from actingweb.property_list import ListProperty

        big_list = ListProperty(actor_id, "biglist", config)
        for i in range(200):
            big_list.append(f"item{i}")

        yielded_names = []
        orig_query = Property.query

        def spy(cls, *a, **kw):
            for item in orig_query(*a, **kw):
                yielded_names.append(str(item.name))
                yield item

        db_list = DbPropertyList()
        with mock.patch.object(Property, "query", classmethod(spy)):
            result = db_list.fetch(actor_id=actor_id)

        assert result == {f"prop{i}": f"val{i}" for i in range(5)}
        assert all(not n.startswith("list:") for n in yielded_names), (
            "list rows must never be returned by the API, not merely "
            "filtered afterwards"
        )

        db_list.delete()

    def test_non_ascii_list_name_is_excluded(self, config, actor_id):
        from actingweb.db.dynamodb.property import DbPropertyList
        from actingweb.property_list import ListProperty

        # A list name starting above '~' (0x7E) is the case that leaks
        # through the "list:~" sentinel the todo originally sketched --
        # 'list;' (0x3B) does not have that hole.
        lst = ListProperty(actor_id, "étag", config)  # 'é' > '~' in bytes
        lst.append("x")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {}

        db_list.delete()

    def test_plain_properties_named_list_and_listen_are_both_returned(
        self, config, actor_id
    ):
        from actingweb.db.dynamodb.property import DbProperty, DbPropertyList

        db = DbProperty()
        db.set(actor_id=actor_id, name="list", value="a")
        db.set(actor_id=actor_id, name="listen", value="b")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {"list": "a", "listen": "b"}

        db_list.delete()

    def test_only_list_rows_still_returns_empty_dict_not_none(self, config, actor_id):
        from actingweb.db.dynamodb.property import DbPropertyList
        from actingweb.property_list import ListProperty

        lst = ListProperty(actor_id, "onlylist", config)
        lst.append("x")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {}
        assert result is not None

        db_list.delete()

    def test_fetch_all_including_lists_still_returns_list_rows(self, config, actor_id):
        from actingweb.db.dynamodb.property import DbProperty, DbPropertyList
        from actingweb.property_list import ListProperty

        db = DbProperty()
        db.set(actor_id=actor_id, name="plain", value="v")
        lst = ListProperty(actor_id, "notes", config)
        lst.append("a")

        db_list = DbPropertyList()
        result = db_list.fetch_all_including_lists(actor_id=actor_id) or {}
        assert result.get("plain") == "v"
        assert any(k.startswith("list:notes-") for k in result)

        db_list.delete()


class TestPostgreSQLPlainPropertyFetch:
    @pytest.fixture(autouse=True)
    def _require_postgresql(self):
        if os.getenv("DATABASE_BACKEND") != "postgresql":
            pytest.skip("PostgreSQL-only test (run with DATABASE_BACKEND=postgresql)")

    def test_returns_only_plain_properties(self, config, actor_id):
        from actingweb.db.postgresql.property import DbProperty, DbPropertyList
        from actingweb.property_list import ListProperty

        db = DbProperty()
        for i in range(5):
            db.set(actor_id=actor_id, name=f"prop{i}", value=f"val{i}")
        lst = ListProperty(actor_id, "biglist", config)
        for i in range(20):
            lst.append(f"item{i}")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {f"prop{i}": f"val{i}" for i in range(5)}

        db_list.delete()

    def test_plain_properties_named_list_and_listen_are_both_returned(
        self, config, actor_id
    ):
        from actingweb.db.postgresql.property import DbProperty, DbPropertyList

        db = DbProperty()
        db.set(actor_id=actor_id, name="list", value="a")
        db.set(actor_id=actor_id, name="listen", value="b")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {"list": "a", "listen": "b"}

        db_list.delete()

    def test_only_list_rows_still_returns_empty_dict_not_none(self, config, actor_id):
        from actingweb.db.postgresql.property import DbPropertyList
        from actingweb.property_list import ListProperty

        lst = ListProperty(actor_id, "onlylist", config)
        lst.append("x")

        db_list = DbPropertyList()
        result = db_list.fetch(actor_id=actor_id)
        assert result == {}
        assert result is not None

        db_list.delete()

    def test_fetch_all_including_lists_still_returns_list_rows(self, config, actor_id):
        from actingweb.db.postgresql.property import DbProperty, DbPropertyList
        from actingweb.property_list import ListProperty

        db = DbProperty()
        db.set(actor_id=actor_id, name="plain", value="v")
        lst = ListProperty(actor_id, "notes", config)
        lst.append("a")

        db_list = DbPropertyList()
        result = db_list.fetch_all_including_lists(actor_id=actor_id) or {}
        assert result.get("plain") == "v"
        assert any(k.startswith("list:notes-") for k in result)

        db_list.delete()
