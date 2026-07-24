"""
Auto-created DynamoDB tables must use on-demand (PAY_PER_REQUEST) billing.

The old Meta defaults created provisioned tables with tiny fixed
capacities (e.g. the property lookup table at 2 RCU / 1 WCU — a hard
throughput wall on the login path). A library cannot know its consumers'
traffic shape; on-demand is the only safe default. Existing tables are
unaffected (DynamoDB never alters live tables) — the migration doc covers
the one-time update-table conversion.

These tests create throwaway clone tables mirroring the production model
Metas — shared unit-test tables must never be deleted mid-run (other
xdist workers use them concurrently).
"""

import os
import uuid
from typing import Any

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


def _boto_client():
    import boto3

    return boto3.client(
        "dynamodb",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-1"),
        endpoint_url=os.getenv("AWS_DB_HOST", "http://localhost:8001"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


def test_production_model_metas_declare_on_demand():
    """Every real model Meta must carry the on-demand billing mode (and no
    stale provisioned capacity values)."""
    from actingweb.db.dynamodb import (
        Actor,
        Attribute,
        PeerTrustee,
        Property,
        PropertyLegacy,
        PropertyLookup,
        PropertyLookupV2,
        Subscription,
        SubscriptionDiff,
        Trust,
    )
    from actingweb.db.dynamodb.subscription_suspension import SubscriptionSuspension

    for model in (
        Actor,
        Attribute,
        PeerTrustee,
        Property,
        PropertyLegacy,
        PropertyLookup,
        PropertyLookupV2,
        Subscription,
        SubscriptionDiff,
        SubscriptionSuspension,
        Trust,
    ):
        assert getattr(model.Meta, "billing_mode", None) == "PAY_PER_REQUEST", (
            model.__name__
        )
        assert not hasattr(model.Meta, "read_capacity_units"), model.__name__
        assert not hasattr(model.Meta, "write_capacity_units"), model.__name__


@pytest.fixture
def clone_table_name():
    return f"awtest_billing_{uuid.uuid4().hex[:12]}"


def test_fresh_table_is_on_demand(clone_table_name):
    """A table created via ensure_table with the standard Meta shape comes
    up PAY_PER_REQUEST."""
    table = clone_table_name
    aws_region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
    db_host = os.getenv("AWS_DB_HOST", "http://localhost:8001")

    class CloneSimple(Model):
        class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
            table_name = table
            billing_mode = PAY_PER_REQUEST_BILLING_MODE
            region = aws_region
            host = db_host

        id = UnicodeAttribute(hash_key=True)
        name = UnicodeAttribute(range_key=True)

    try:
        _ensure.ensure_table(CloneSimple)
        desc = _boto_client().describe_table(TableName=table)["Table"]
        assert (
            desc.get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST"
        )
    finally:
        try:
            CloneSimple.delete_table()
        except Exception:
            pass


def test_fresh_table_with_gsi_is_on_demand(clone_table_name):
    """A model with a GSI must create table AND index without provisioned
    throughput."""
    table = clone_table_name
    aws_region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
    db_host = os.getenv("AWS_DB_HOST", "http://localhost:8001")

    class CloneIndex(GlobalSecondaryIndex[Any]):
        class Meta:
            index_name = "clone-index"
            projection = AllProjection()

        creator = UnicodeAttribute(default="0", hash_key=True)

    class CloneWithGsi(Model):
        class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
            table_name = table
            billing_mode = PAY_PER_REQUEST_BILLING_MODE
            region = aws_region
            host = db_host

        id = UnicodeAttribute(hash_key=True)
        creator = UnicodeAttribute()
        clone_index = CloneIndex()

    try:
        _ensure.ensure_table(CloneWithGsi)
        desc = _boto_client().describe_table(TableName=table)["Table"]
        assert (
            desc.get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST"
        )
        for gsi in desc.get("GlobalSecondaryIndexes", []):
            throughput = gsi.get("ProvisionedThroughput", {})
            assert throughput.get("ReadCapacityUnits", 0) == 0
            assert throughput.get("WriteCapacityUnits", 0) == 0
    finally:
        try:
            CloneWithGsi.delete_table()
        except Exception:
            pass
