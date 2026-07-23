"""
Conditional GSI schema: the properties-table shape must match the
configured reverse-lookup mode.

Lookup-table mode creates the table WITHOUT the legacy value-keyed
``property-index`` GSI (no write/storage amplification, no 2048-byte
GSI-key write rejection on real AWS); legacy mode creates it WITH the
GSI so the legacy reverse-lookup path works. Existing tables are never
altered.

These tests use throwaway clone models with unique table names — the
shared unit-test properties table must never be deleted or recreated
mid-run (other xdist workers use it concurrently), and its shape is
whatever the first creator chose.
"""

import os
import uuid
from typing import Any
from unittest import mock

import pytest
from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

from actingweb.db.dynamodb import _ensure


@pytest.fixture(autouse=True)
def _require_dynamodb():
    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


def _make_clone_models(table_name: str):
    """Build GSI-less and GSI'd model clones bound to the same table name,
    mirroring actingweb.db.dynamodb.property.Property / PropertyLegacy."""

    clone_table = table_name
    clone_region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
    clone_host = os.getenv("AWS_DB_HOST", "http://localhost:8001")

    class CloneIndex(GlobalSecondaryIndex[Any]):
        class Meta:
            index_name = "property-index"
            projection = AllProjection()

        value = UnicodeAttribute(default="0", hash_key=True)

    class CloneNoGsi(Model):
        class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
            table_name = clone_table
            billing_mode = PAY_PER_REQUEST_BILLING_MODE
            region = clone_region
            host = clone_host

        id = UnicodeAttribute(hash_key=True)
        name = UnicodeAttribute(range_key=True)
        value = UnicodeAttribute()

    class CloneWithGsi(Model):
        class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
            table_name = clone_table
            billing_mode = PAY_PER_REQUEST_BILLING_MODE
            region = clone_region
            host = clone_host

        id = UnicodeAttribute(hash_key=True)
        name = UnicodeAttribute(range_key=True)
        value = UnicodeAttribute()
        property_index = CloneIndex()

    return CloneNoGsi, CloneWithGsi


@pytest.fixture
def clone_models():
    table_name = f"awtest_gsi_{uuid.uuid4().hex[:12]}"
    no_gsi, with_gsi = _make_clone_models(table_name)
    yield no_gsi, with_gsi
    for model in (no_gsi, with_gsi):
        try:
            model.delete_table()
            break
        except Exception:
            continue


def _boto_client():
    import boto3

    return boto3.client(
        "dynamodb",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-1"),
        endpoint_url=os.getenv("AWS_DB_HOST", "http://localhost:8001"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


def test_lookup_shape_has_no_gsi(clone_models):
    no_gsi, _ = clone_models
    _ensure.ensure_table(no_gsi)
    desc = _boto_client().describe_table(TableName=no_gsi.Meta.table_name)["Table"]
    assert desc.get("GlobalSecondaryIndexes") is None
    # No GSI key constraint: large values store fine (note: DynamoDB Local
    # does not enforce the 2048-byte GSI-key limit either way, so the
    # meaningful assertion is the table shape above; on real AWS the limit
    # only exists when the GSI does).
    big = "x" * 5000
    no_gsi(id="actor-a", name="bigprop", value=big).save()
    assert no_gsi.get("actor-a", "bigprop").value == big


def test_legacy_shape_has_gsi_and_serves_reverse_lookup(clone_models):
    _, with_gsi = clone_models
    _ensure.ensure_table(with_gsi)
    desc = _boto_client().describe_table(TableName=with_gsi.Meta.table_name)["Table"]
    gsis = desc.get("GlobalSecondaryIndexes") or []
    assert [g["IndexName"] for g in gsis] == ["property-index"]

    value = f"legacy-{uuid.uuid4()}"
    with_gsi(id="actor-b", name="oauthId", value=value).save()
    hits = [str(r.id) for r in with_gsi.property_index.query(value)]
    assert hits == ["actor-b"]


def test_first_creator_wins_shape(clone_models):
    """Mixing modes in one process: the first creator fixes the schema;
    the second mode's ensure must not alter the live table."""
    no_gsi, with_gsi = clone_models
    _ensure.ensure_table(no_gsi)
    _ensure.ensure_table(with_gsi)  # table exists — must be a no-op
    desc = _boto_client().describe_table(TableName=no_gsi.Meta.table_name)["Table"]
    assert desc.get("GlobalSecondaryIndexes") is None


class TestAccessorWiring:
    """DbProperty/DbPropertyList must ensure the mode-appropriate class."""

    @pytest.mark.parametrize("accessor_name", ["DbProperty", "DbPropertyList"])
    @pytest.mark.parametrize("use_lookup", [True, False])
    def test_mode_selects_schema_class(self, accessor_name, use_lookup):
        from actingweb.db.dynamodb import property as prop_mod

        with mock.patch.object(prop_mod, "ensure_table") as ensure_spy:
            accessor_cls = getattr(prop_mod, accessor_name)
            accessor_cls(use_lookup_table=use_lookup, indexed_properties=["email"])
        expected = prop_mod.Property if use_lookup else prop_mod.PropertyLegacy
        ensure_spy.assert_called_once_with(expected)
