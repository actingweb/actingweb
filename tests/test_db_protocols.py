"""
Test that database backends conform to the defined protocols.

This ensures that all database backends (DynamoDB, PostgreSQL, etc.) implement
the required interfaces consistently.

NOTE: These tests require the database backend to be available:
- DynamoDB: Requires DynamoDB local running on localhost:8001
- PostgreSQL: Requires PostgreSQL running with configured connection details
"""

import importlib

import pytest

from actingweb.db.protocols import (
    DbActorListProtocol,
    DbActorProtocol,
    DbAttributeBucketListProtocol,
    DbAttributeProtocol,
    DbPeerTrusteeListProtocol,
    DbPeerTrusteeProtocol,
    DbPropertyListProtocol,
    DbPropertyProtocol,
    DbSubscriptionDiffListProtocol,
    DbSubscriptionDiffProtocol,
    DbSubscriptionListProtocol,
    DbSubscriptionProtocol,
    DbTrustListProtocol,
    DbTrustProtocol,
)

# Note: This file previously had a setup_dynamodb_env fixture that set
# AWS_DB_PREFIX="protocol_test", but it was unused by any tests.
# All tests rely on the global conftest.py environment setup instead.

# Actor and Property implemented for both backends
@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPhase2ProtocolCompliance:
    """Test Actor and Property protocols for both backends."""

    def test_actor_protocol_compliance(self, backend: str) -> None:
        """Verify DbActor implements DbActorProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.actor")
        instance = mod.DbActor()
        assert isinstance(instance, DbActorProtocol)

    def test_actor_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbActorList implements DbActorListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.actor")
        instance = mod.DbActorList()
        assert isinstance(instance, DbActorListProtocol)

    def test_property_protocol_compliance(self, backend: str) -> None:
        """Verify DbProperty implements DbPropertyProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.property")
        instance = mod.DbProperty()
        assert isinstance(instance, DbPropertyProtocol)

    def test_property_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbPropertyList implements DbPropertyListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.property")
        instance = mod.DbPropertyList()
        assert isinstance(instance, DbPropertyListProtocol)


# Trust tables implemented for both backends
@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPhase3ProtocolCompliance:
    """Test Trust and PeerTrustee protocols for both backends."""

    def test_trust_protocol_compliance(self, backend: str) -> None:
        """Verify DbTrust implements DbTrustProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.trust")
        instance = mod.DbTrust()
        assert isinstance(instance, DbTrustProtocol)

    def test_trust_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbTrustList implements DbTrustListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.trust")
        instance = mod.DbTrustList()
        assert isinstance(instance, DbTrustListProtocol)

    def test_peertrustee_protocol_compliance(self, backend: str) -> None:
        """Verify DbPeerTrustee implements DbPeerTrusteeProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.peertrustee")
        instance = mod.DbPeerTrustee()
        assert isinstance(instance, DbPeerTrusteeProtocol)

    def test_peertrustee_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbPeerTrusteeList implements DbPeerTrusteeListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.peertrustee")
        instance = mod.DbPeerTrusteeList()
        assert isinstance(instance, DbPeerTrusteeListProtocol)


# Subscriptions and Attributes implemented for both backends
@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPhase4ProtocolCompliance:
    """Test Subscription and Attribute protocols for both backends."""

    def test_subscription_protocol_compliance(self, backend: str) -> None:
        """Verify DbSubscription implements DbSubscriptionProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.subscription")
        instance = mod.DbSubscription()
        assert isinstance(instance, DbSubscriptionProtocol)

    def test_subscription_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbSubscriptionList implements DbSubscriptionListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.subscription")
        instance = mod.DbSubscriptionList()
        assert isinstance(instance, DbSubscriptionListProtocol)

    def test_subscription_diff_protocol_compliance(self, backend: str) -> None:
        """Verify DbSubscriptionDiff implements DbSubscriptionDiffProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.subscription_diff")
        instance = mod.DbSubscriptionDiff()
        assert isinstance(instance, DbSubscriptionDiffProtocol)

    def test_subscription_diff_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbSubscriptionDiffList implements DbSubscriptionDiffListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.subscription_diff")
        instance = mod.DbSubscriptionDiffList()
        assert isinstance(instance, DbSubscriptionDiffListProtocol)

    def test_attribute_protocol_compliance(self, backend: str) -> None:
        """Verify DbAttribute implements DbAttributeProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.attribute")
        instance = mod.DbAttribute()
        assert isinstance(instance, DbAttributeProtocol)

    def test_attribute_bucket_list_protocol_compliance(self, backend: str) -> None:
        """Verify DbAttributeBucketList implements DbAttributeBucketListProtocol."""
        mod = importlib.import_module(f"actingweb.db.{backend}.attribute")
        instance = mod.DbAttributeBucketList()
        assert isinstance(instance, DbAttributeBucketListProtocol)
