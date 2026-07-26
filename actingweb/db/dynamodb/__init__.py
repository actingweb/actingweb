"""DynamoDB backend for ActingWeb.

This module provides PynamoDB-based storage for ActingWeb actors,
properties, trust relationships, and subscriptions.

Table auto-creation is controlled by ``auto_create_enabled()`` — exported
here as public API so application code that does its own ``DescribeTable``
probing (boto3 ``table.load()``, ``describe_table``) can honour the same
switch and skip the probe when tables are managed externally, rather than
re-implementing the environment parsing.
"""

# Import all database classes for backward compatibility and convenience
from ._ensure import auto_create_enabled, reset_ensure_cache, set_auto_create
from .actor import Actor, CreatorIndex, DbActor, DbActorList
from .attribute import Attribute, DbAttribute, DbAttributeBucketList
from .peertrustee import DbPeerTrustee, DbPeerTrusteeList, PeerTrustee
from .property import DbProperty, DbPropertyList, Property, PropertyLegacy
from .property_lookup import DbPropertyLookup, PropertyLookup, PropertyLookupV2
from .subscription import DbSubscription, DbSubscriptionList, Subscription
from .subscription_diff import (
    DbSubscriptionDiff,
    DbSubscriptionDiffList,
    SubscriptionDiff,
)
from .trust import DbTrust, DbTrustList, SecretIndex, Trust

__all__ = [
    # Table auto-creation control (public: consumers with their own
    # DescribeTable probes should honour the same switch)
    "auto_create_enabled",
    "set_auto_create",
    "reset_ensure_cache",
    # Actor
    "Actor",
    "CreatorIndex",
    "DbActor",
    "DbActorList",
    # Attribute
    "Attribute",
    "DbAttribute",
    "DbAttributeBucketList",
    # PeerTrustee
    "PeerTrustee",
    "DbPeerTrustee",
    "DbPeerTrusteeList",
    # Property
    "Property",
    "PropertyLegacy",
    "DbProperty",
    "DbPropertyList",
    # PropertyLookup
    "PropertyLookup",
    "PropertyLookupV2",
    "DbPropertyLookup",
    # Subscription
    "Subscription",
    "DbSubscription",
    "DbSubscriptionList",
    # SubscriptionDiff
    "SubscriptionDiff",
    "DbSubscriptionDiff",
    "DbSubscriptionDiffList",
    # Trust
    "Trust",
    "SecretIndex",
    "DbTrust",
    "DbTrustList",
]
