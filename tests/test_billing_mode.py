"""
Auto-created DynamoDB tables must use on-demand (PAY_PER_REQUEST) billing.

The old Meta defaults created provisioned tables with tiny fixed
capacities (e.g. the property lookup table at 2 RCU / 1 WCU — a hard
throughput wall on the login path). A library cannot know its consumers'
traffic shape; on-demand is the only safe default. Existing tables are
unaffected (DynamoDB never alters live tables) — the migration doc covers
the one-time update-table conversion.
"""

import os

import pytest

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


def test_fresh_table_is_on_demand():
    """Delete + recreate the suspension table and verify billing mode."""
    from actingweb.db.dynamodb.subscription_suspension import (
        DbSubscriptionSuspension,
        SubscriptionSuspension,
    )

    client = _boto_client()
    table_name = SubscriptionSuspension.Meta.table_name

    try:
        client.delete_table(TableName=table_name)
        client.get_waiter("table_not_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 15}
        )
    except client.exceptions.ResourceNotFoundException:
        pass
    _ensure.reset_ensure_cache()

    # Accessor construction auto-creates the table
    DbSubscriptionSuspension("billing-test-actor")

    desc = client.describe_table(TableName=table_name)["Table"]
    assert desc.get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST"


def test_fresh_table_with_gsi_is_on_demand():
    """A model with a GSI must create table AND index without throughput."""
    from actingweb.db.dynamodb.actor import Actor, DbActor

    client = _boto_client()
    table_name = Actor.Meta.table_name

    try:
        client.delete_table(TableName=table_name)
        client.get_waiter("table_not_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 15}
        )
    except client.exceptions.ResourceNotFoundException:
        pass
    _ensure.reset_ensure_cache()

    DbActor()

    desc = client.describe_table(TableName=table_name)["Table"]
    assert desc.get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST"
    for gsi in desc.get("GlobalSecondaryIndexes", []):
        throughput = gsi.get("ProvisionedThroughput", {})
        assert throughput.get("ReadCapacityUnits", 0) == 0
        assert throughput.get("WriteCapacityUnits", 0) == 0
