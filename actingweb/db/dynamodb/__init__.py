"""DynamoDB backend for ActingWeb.

This module provides PynamoDB-based storage for ActingWeb actors,
properties, trust relationships, and subscriptions.
"""

# Import all database classes for backward compatibility and convenience
from .actor import Actor, CreatorIndex, DbActor, DbActorList
from .attribute import Attribute, DbAttribute, DbAttributeBucketList
from .peertrustee import DbPeerTrustee, DbPeerTrusteeList, PeerTrustee
from .property import DbProperty, DbPropertyList, Property
from .property_lookup import DbPropertyLookup, PropertyLookup
from .subscription import DbSubscription, DbSubscriptionList, Subscription
from .subscription_diff import (
    DbSubscriptionDiff,
    DbSubscriptionDiffList,
    SubscriptionDiff,
)
from .trust import DbTrust, DbTrustList, SecretIndex, Trust

__all__ = [
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
    "DbProperty",
    "DbPropertyList",
    # PropertyLookup
    "PropertyLookup",
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
