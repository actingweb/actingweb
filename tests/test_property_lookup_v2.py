"""
Tests for the v2 (digest-only) property lookup table.

The v2 format keys rows by sha256(name + NUL + value) — a permanent data
format — stores no plaintext values, uses conditional puts (collisions are
logged, not silently overwritten), and has no value-size limit. These
tests lock the format and the hardening behaviour.
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
def actor_id():
    return f"lookupv2-{uuid.uuid4()}"


class TestDigestFormat:
    def test_known_answer(self):
        """Locks the permanent data format: sha256('email' NUL 'a@b.c')."""
        import hashlib

        from actingweb.db.dynamodb.property_lookup import compute_lookup_key

        expected = hashlib.sha256(b"email\x00a@b.c").hexdigest()
        assert compute_lookup_key("email", "a@b.c") == expected
        # 64 hex chars, always
        assert len(expected) == 64

    def test_separator_is_unambiguous(self):
        from actingweb.db.dynamodb.property_lookup import compute_lookup_key

        # Without a separator these two pairs would collide
        assert compute_lookup_key("ab", "c") != compute_lookup_key("a", "bc")
        # Names containing '#' or ':' are safe too
        assert compute_lookup_key("a#b", "c") != compute_lookup_key("a", "#bc")

    def test_non_ascii_values(self):
        from actingweb.db.dynamodb.property_lookup import compute_lookup_key

        key = compute_lookup_key("email", "grøger@ttwedel.nø")
        assert len(key) == 64


class TestNoSizeLimit:
    def test_large_value_roundtrip(self, actor_id):
        """v1's range key capped values at 1024 bytes; v2 has no limit."""
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        big_value = "x" * 5000
        db = DbPropertyLookup()
        assert db.create("externalUserId", big_value, actor_id) is True
        assert db.get("externalUserId", big_value) == actor_id
        assert db.delete("externalUserId", big_value) is True
        assert db.get("externalUserId", big_value) is None


class TestValueNeverStored:
    def test_row_contains_no_value(self, actor_id):
        from actingweb.db.dynamodb.property_lookup import (
            DbPropertyLookup,
            PropertyLookupV2,
            compute_lookup_key,
        )

        secret_value = f"secret-{uuid.uuid4()}"
        db = DbPropertyLookup()
        assert db.create("oauthId", secret_value, actor_id) is True
        raw = PropertyLookupV2.get(compute_lookup_key("oauthId", secret_value))
        stored = raw.to_simple_dict()
        assert secret_value not in str(stored)
        assert stored["actor_id"] == actor_id
        assert stored["property_name"] == "oauthId"
        db.delete("oauthId", secret_value)


class TestWriteFailureLogging:
    def test_failure_logs_digest_never_value(self, actor_id, caplog):
        from actingweb.db.dynamodb import property_lookup as pl

        secret_value = f"secret-{uuid.uuid4()}"
        with mock.patch.object(
            pl.PropertyLookupV2, "save", side_effect=Exception("throttled")
        ):
            db = pl.DbPropertyLookup()
            with caplog.at_level(
                "ERROR", logger="actingweb.db.dynamodb.property_lookup"
            ):
                from actingweb.db.exceptions import DbError

                # A write fault is not a collision: it raises, so a backfill
                # or a property write cannot mistake it for "another actor
                # holds the value".
                with pytest.raises(DbError):
                    db.create("email", secret_value, actor_id)
        assert any("LOOKUP_CREATE_FAILED" in r.message for r in caplog.records)
        assert all(secret_value not in r.message for r in caplog.records)


class TestUnchangedValueSkipsSync:
    def test_unchanged_value_is_a_plain_write(self, actor_id):
        """The value-unchanged shortcut writes the property alone: no
        transaction, no lookup access."""
        from actingweb.db.dynamodb.actor import DbActor
        from actingweb.db.dynamodb.property import DbProperty

        value = f"same-{uuid.uuid4()}@x.y"
        seed = DbProperty(indexed_properties=["email"])
        assert seed.set(actor_id=actor_id, name="email", value=value)
        try:
            with mock.patch.object(DbActor, "_run_transaction") as txn:
                again = DbProperty(indexed_properties=["email"])
                assert again.set(actor_id=actor_id, name="email", value=value)
            txn.assert_not_called()
        finally:
            DbProperty(indexed_properties=["email"]).get(actor_id, "email")
            cleanup = DbProperty(indexed_properties=["email"])
            cleanup.get(actor_id=actor_id, name="email")
            cleanup.delete()

    def test_changed_value_moves_the_lookup_row(self, actor_id):
        from actingweb.db.dynamodb.property import DbProperty
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        old = f"old-{uuid.uuid4()}@x.y"
        new = f"new-{uuid.uuid4()}@x.y"
        writer = DbProperty(indexed_properties=["email"])
        assert writer.set(actor_id=actor_id, name="email", value=old)
        try:
            assert DbPropertyLookup().get("email", old) == actor_id
            second = DbProperty(indexed_properties=["email"])
            assert second.set(actor_id=actor_id, name="email", value=new)
            assert DbPropertyLookup().get("email", old) is None
            assert DbPropertyLookup().get("email", new) == actor_id
        finally:
            cleanup = DbProperty(indexed_properties=["email"])
            cleanup.get(actor_id=actor_id, name="email")
            cleanup.delete()


class TestReverseLookupContract:
    def test_non_indexed_name_returns_none_with_warning(self, actor_id, caplog):
        from actingweb.db.dynamodb import property as prop_mod

        prop = prop_mod.DbProperty(indexed_properties=["email"])
        with (
            mock.patch.object(prop_mod.Property, "scan") as scan,
            caplog.at_level("WARNING", logger="actingweb.db.dynamodb.property"),
        ):
            result = prop.get_actor_id_from_property(name="notIndexed", value="v")
        assert result is None
        scan.assert_not_called()
        assert any("non-indexed" in r.message for r in caplog.records)

    def test_a_miss_is_one_get_item(self):
        """A reverse lookup with no lookup row answers None after exactly one
        GetItem on the lookup table: no scan, no query, no second tier."""
        from pynamodb.exceptions import DoesNotExist

        from actingweb.db.dynamodb import property as prop_mod
        from actingweb.db.dynamodb import property_lookup as pl

        prop = prop_mod.DbProperty(indexed_properties=["email"])
        with (
            mock.patch.object(
                pl.PropertyLookupV2, "get", side_effect=DoesNotExist()
            ) as get,
            mock.patch.object(pl.PropertyLookupV2, "scan") as scan,
            mock.patch.object(pl.PropertyLookupV2, "query") as query,
            mock.patch.object(prop_mod.Property, "scan") as prop_scan,
            mock.patch.object(prop_mod.Property, "query") as prop_query,
        ):
            assert (
                prop.get_actor_id_from_property(
                    name="email", value=f"miss-{uuid.uuid4()}"
                )
                is None
            )
        assert get.call_count == 1
        scan.assert_not_called()
        query.assert_not_called()
        prop_scan.assert_not_called()
        prop_query.assert_not_called()

    def test_the_constructor_requires_indexed_properties(self):
        from actingweb.db.dynamodb import property as prop_mod

        with pytest.raises(TypeError, match="indexed_properties"):
            prop_mod.DbProperty()  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="indexed_properties"):
            prop_mod.DbPropertyList()  # type: ignore[call-arg]

    def test_indexed_roundtrip_via_v2(self, actor_id):
        """Set an indexed property -> reverse lookup -> delete cleans up."""
        from actingweb.db.dynamodb.property import DbProperty
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        value = f"user-{uuid.uuid4()}@example.com"
        writer = DbProperty(indexed_properties=["email"])
        assert writer.set(actor_id=actor_id, name="email", value=value)

        reader = DbProperty(indexed_properties=["email"])
        assert reader.get_actor_id_from_property(name="email", value=value) == actor_id

        # Deleting the property removes the lookup row
        deleter = DbProperty(indexed_properties=["email"])
        assert deleter.get(actor_id=actor_id, name="email") == value
        assert deleter.delete() is True
        assert DbPropertyLookup().get("email", value) is None
