"""``DbProperty.get_prefix()`` — parameter forwarding and fault behaviour.

The cross-backend byte-exactness lives in
``tests/integration/test_db_property_range.py::TestGetPrefix``, which needs
real storage. What is checkable without it is the wiring: that
``keys_only``/``consistent_read`` reach the backend call rather than being
dropped on the way, that the falsy-prefix guard short-circuits BEFORE the
backend (DynamoDB's ``begins_with(name, "")`` is a ``ValidationException``,
so a guard that ran after the call would be no guard at all), and that a
backend fault raises ``DbError`` rather than returning ``{}`` — which for a
scoped read would be indistinguishable from a real, common answer.
"""

import pytest

from actingweb.db.exceptions import DbError


class _Recorder:
    """Stands in for the backend call, capturing what it was handed."""

    def __init__(self, items=(), fail=False):
        self.items = list(items)
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.fail:
            raise RuntimeError("ProvisionedThroughputExceededException")
        return self.items


class _Row:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class TestDynamoDbGetPrefix:
    def _db(self):
        from actingweb.db.dynamodb.property import DbProperty

        return DbProperty()

    def test_forwards_consistent_read_and_projects_all_attributes(self, monkeypatch):
        from actingweb.db.dynamodb import property as dynamo_property

        rec = _Recorder([_Row("list:memory_a-meta", "{}")])
        monkeypatch.setattr(dynamo_property.Property, "query", rec)

        result = self._db().get_prefix(
            actor_id="actor1", prefix="list:memory_", consistent_read=False
        )

        assert result == {"list:memory_a-meta": "{}"}
        assert rec.calls[0]["kwargs"]["consistent_read"] is False
        assert rec.calls[0]["kwargs"]["attributes_to_get"] == ["name", "value"]

    def test_keys_only_projects_names_and_blanks_values(self, monkeypatch):
        from actingweb.db.dynamodb import property as dynamo_property

        rec = _Recorder([_Row("list:memory_a-meta", "{}")])
        monkeypatch.setattr(dynamo_property.Property, "query", rec)

        result = self._db().get_prefix(
            actor_id="actor1", prefix="list:memory_", keys_only=True
        )

        assert result == {"list:memory_a-meta": ""}
        assert rec.calls[0]["kwargs"]["attributes_to_get"] == ["name"]

    def test_the_range_condition_is_begins_with_the_prefix(self, monkeypatch):
        from actingweb.db.dynamodb import property as dynamo_property

        rec = _Recorder()
        monkeypatch.setattr(dynamo_property.Property, "query", rec)

        self._db().get_prefix(actor_id="actor1", prefix="list:memory_")

        condition = rec.calls[0]["kwargs"]["range_key_condition"]
        assert "begins_with" in repr(condition)
        assert condition.values[1].value["S"] == "list:memory_"

    def test_a_falsy_prefix_never_reaches_the_backend(self, monkeypatch):
        from actingweb.db.dynamodb import property as dynamo_property

        rec = _Recorder()
        monkeypatch.setattr(dynamo_property.Property, "query", rec)

        assert self._db().get_prefix(actor_id="actor1", prefix="") == {}
        assert self._db().get_prefix(actor_id="actor1", prefix=None) == {}
        assert self._db().get_prefix(actor_id=None, prefix="list:") == {}

        assert rec.calls == [], (
            "begins_with(name, '') is a DynamoDB ValidationException -- the "
            "guard has to run before the call, not after"
        )

    def test_a_backend_fault_raises_db_error(self, monkeypatch):
        from actingweb.db.dynamodb import property as dynamo_property

        monkeypatch.setattr(dynamo_property.Property, "query", _Recorder(fail=True))

        with pytest.raises(DbError):
            self._db().get_prefix(actor_id="actor1", prefix="list:memory_")


class TestPostgreSqlGetPrefix:
    def _db(self):
        from actingweb.db.postgresql.property import DbProperty

        return DbProperty()

    def _patch_connection(self, monkeypatch, rows, fail=False):
        """Patch get_connection with a cursor recording every execute()."""
        from actingweb.db.postgresql import property as pg_property

        executed: list[tuple] = []

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                executed.append((sql, params))
                if fail:
                    raise RuntimeError("connection reset")

            def fetchall(self):
                return rows

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return FakeCursor()

        monkeypatch.setattr(pg_property, "get_connection", lambda: FakeConn())
        return executed

    def test_uses_starts_with_and_binds_the_prefix(self, monkeypatch):
        executed = self._patch_connection(monkeypatch, [("list:memory_a-meta", "{}")])

        result = self._db().get_prefix(actor_id="actor1", prefix="list:memory_")

        assert result == {"list:memory_a-meta": "{}"}
        sql, params = executed[0]
        assert "starts_with(name, %s)" in sql
        assert "LIKE" not in sql.upper(), (
            "LIKE would make '_' and '%' metacharacters -- every family "
            "prefix a caller passes contains an underscore"
        )
        assert params == ("actor1", "list:memory_")

    def test_keys_only_selects_name_only(self, monkeypatch):
        executed = self._patch_connection(monkeypatch, [("list:memory_a-meta",)])

        result = self._db().get_prefix(
            actor_id="actor1", prefix="list:memory_", keys_only=True
        )

        assert result == {"list:memory_a-meta": ""}
        sql, _params = executed[0]
        assert "SELECT name" in sql
        assert "value" not in sql

    def test_a_falsy_prefix_never_reaches_sql(self, monkeypatch):
        executed = self._patch_connection(monkeypatch, [])

        assert self._db().get_prefix(actor_id="actor1", prefix="") == {}
        assert self._db().get_prefix(actor_id="actor1", prefix=None) == {}
        assert self._db().get_prefix(actor_id=None, prefix="list:") == {}

        assert executed == [], (
            "starts_with(x, '') is true for every row -- an unguarded empty "
            "prefix silently becomes the partition dump this avoids"
        )

    def test_consistent_read_is_accepted_and_ignored(self, monkeypatch):
        executed = self._patch_connection(monkeypatch, [("list:memory_a-meta", "{}")])

        strong = self._db().get_prefix(
            actor_id="actor1", prefix="list:memory_", consistent_read=True
        )
        eventual = self._db().get_prefix(
            actor_id="actor1", prefix="list:memory_", consistent_read=False
        )

        assert strong == eventual
        assert executed[0][0] == executed[1][0]

    def test_a_backend_fault_raises_db_error(self, monkeypatch):
        self._patch_connection(monkeypatch, [], fail=True)

        with pytest.raises(DbError):
            self._db().get_prefix(actor_id="actor1", prefix="list:memory_")


class TestBothBackendsShareTheSignature:
    def test_signatures_match_the_protocol(self):
        import inspect

        from actingweb.db.dynamodb.property import DbProperty as DynamoDbProperty
        from actingweb.db.postgresql.property import DbProperty as PgDbProperty
        from actingweb.db.protocols import DbPropertyProtocol

        expected = inspect.signature(DbPropertyProtocol.get_prefix)
        for impl in (DynamoDbProperty, PgDbProperty):
            assert inspect.signature(impl.get_prefix) == expected, impl
