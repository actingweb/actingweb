"""
PostgreSQL database backend for ActingWeb.

This module provides PostgreSQL implementations of all ActingWeb database operations,
matching the interface defined by the database protocols.

Usage:
    Set DATABASE_BACKEND=postgresql in environment to use this backend.
    Configure connection via environment variables:
        PG_DB_HOST, PG_DB_PORT, PG_DB_NAME, PG_DB_USER, PG_DB_PASSWORD

Installation:
    poetry install --extras postgresql
"""

# Import all database classes for backward compatibility and convenience
from .actor import DbActor, DbActorList
from .attribute import DbAttribute, DbAttributeBucketList
from .peertrustee import DbPeerTrustee, DbPeerTrusteeList
from .property import DbProperty, DbPropertyList
from .property_lookup import DbPropertyLookup
from .subscription import DbSubscription, DbSubscriptionList
from .subscription_diff import DbSubscriptionDiff, DbSubscriptionDiffList
from .trust import DbTrust, DbTrustList

__all__ = [
    # Actor
    "DbActor",
    "DbActorList",
    # Attribute
    "DbAttribute",
    "DbAttributeBucketList",
    # PeerTrustee
    "DbPeerTrustee",
    "DbPeerTrusteeList",
    # Property
    "DbProperty",
    "DbPropertyList",
    # PropertyLookup
    "DbPropertyLookup",
    # Subscription
    "DbSubscription",
    "DbSubscriptionList",
    # SubscriptionDiff
    "DbSubscriptionDiff",
    "DbSubscriptionDiffList",
    # Trust
    "DbTrust",
    "DbTrustList",
]
