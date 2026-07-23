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
            with caplog.at_level("ERROR"):
                assert db.create("email", secret_value, actor_id) is False
        assert any("LOOKUP_CREATE_FAILED" in r.message for r in caplog.records)
        assert all(secret_value not in r.message for r in caplog.records)


class TestUnchangedValueSkipsSync:
    def test_update_lookup_entry_short_circuits(self, actor_id):
        from actingweb.db.dynamodb.property import DbProperty

        prop = DbProperty(use_lookup_table=True, indexed_properties=["email"])
        with mock.patch(
            "actingweb.db.dynamodb.property_lookup.DbPropertyLookup"
        ) as accessor:
            prop._update_lookup_entry(actor_id, "email", "same@x.y", "same@x.y")
        accessor.assert_not_called()

    def test_changed_value_syncs(self, actor_id):
        from actingweb.db.dynamodb.property import DbProperty

        prop = DbProperty(use_lookup_table=True, indexed_properties=["email"])
        with mock.patch(
            "actingweb.db.dynamodb.property_lookup.DbPropertyLookup"
        ) as accessor:
            accessor.return_value.get.return_value = actor_id
            prop._update_lookup_entry(actor_id, "email", "old@x.y", "new@x.y")
        accessor.return_value.delete.assert_called_once()
        accessor.return_value.create.assert_called_once_with(
            property_name="email", value="new@x.y", actor_id=actor_id
        )


class TestReverseLookupContract:
    def test_non_indexed_name_returns_none_with_warning(self, actor_id, caplog):
        from actingweb.db.dynamodb import property as prop_mod

        prop = prop_mod.DbProperty(use_lookup_table=True, indexed_properties=["email"])
        with (
            mock.patch.object(prop_mod.PropertyLegacy, "property_index") as gsi,
            caplog.at_level("WARNING"),
        ):
            result = prop.get_actor_id_from_property(name="notIndexed", value="v")
        assert result is None
        gsi.query.assert_not_called()
        assert any("non-indexed" in r.message for r in caplog.records)

    def test_legacy_missing_gsi_raises_actionable_error(self):
        from actingweb.db.dynamodb import property as prop_mod

        prop = prop_mod.DbProperty(use_lookup_table=False)
        with mock.patch.object(
            prop_mod.PropertyLegacy.property_index,
            "query",
            side_effect=Exception(
                "ValidationException: The table does not have the specified index"
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                prop.get_actor_id_from_property(name="email", value="v")
        message = str(exc_info.value)
        assert "property-index" in message
        assert "with_legacy_property_index" in message
        assert "backfill_property_lookup" in message

    def test_indexed_roundtrip_via_v2(self, actor_id):
        """Set an indexed property -> reverse lookup -> delete cleans up."""
        from actingweb.db.dynamodb.property import DbProperty
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        value = f"user-{uuid.uuid4()}@example.com"
        writer = DbProperty(use_lookup_table=True, indexed_properties=["email"])
        assert writer.set(actor_id=actor_id, name="email", value=value)

        reader = DbProperty(use_lookup_table=True, indexed_properties=["email"])
        assert reader.get_actor_id_from_property(name="email", value=value) == actor_id

        # Deleting the property removes the lookup row
        deleter = DbProperty(use_lookup_table=True, indexed_properties=["email"])
        assert deleter.get(actor_id=actor_id, name="email") == value
        assert deleter.delete() is True
        assert DbPropertyLookup().get("email", value) is None


class TestV1Fallback:
    def test_get_v1_reads_old_format(self, actor_id):
        from actingweb.db.dynamodb.property_lookup import (
            DbPropertyLookup,
            PropertyLookup,
        )

        # Simulate a pre-migration deployment: row exists only in v1.
        # (Create the v1 table on demand for the test; the library itself
        # never auto-creates it.)
        if not PropertyLookup.exists():
            PropertyLookup.create_table(wait=True)
        value = f"v1-{uuid.uuid4()}"
        PropertyLookup(property_name="email", value=value, actor_id=actor_id).save()

        db = DbPropertyLookup()
        assert db.get("email", value) is None  # not in v2
        assert db.get_v1("email", value) == actor_id
        PropertyLookup.get("email", value).delete()

    def test_get_v1_missing_table_is_none(self, monkeypatch):
        from actingweb.db.dynamodb import property_lookup as pl

        with mock.patch.object(
            pl.PropertyLookup, "get", side_effect=Exception("ResourceNotFound")
        ):
            assert pl.DbPropertyLookup().get_v1("email", "x") is None
