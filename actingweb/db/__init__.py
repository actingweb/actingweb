"""ActingWeb database abstraction layer with config-aware accessors.

This package provides database implementations for ActingWeb actors.
Backends are loaded dynamically via config.py based on DATABASE_BACKEND environment variable.

Supported backends:
- dynamodb: DynamoDB backend (requires 'pynamodb' package)
- postgresql: PostgreSQL backend (requires 'psycopg', 'sqlalchemy', 'alembic' packages)

Installation:
    poetry install --extras dynamodb    # DynamoDB only
    poetry install --extras postgresql  # PostgreSQL only
    poetry install --extras all         # Both backends

Note: Backend modules are not imported here to allow optional dependencies.
They are loaded dynamically by config.py when needed.

Config-Aware Accessors
----------------------
This module provides factory functions for creating database instances with
configuration automatically injected. This ensures all DB objects respect
application settings like indexed_properties and use_lookup_table.

Example usage:
    from actingweb.db import get_property, get_actor

    # Instead of: db = config.DbProperty.DbProperty()
    db = get_property(config)

    # Instead of: actor_db = config.DbActor.DbActor()
    actor_db = get_actor(config)

This pattern provides:
- Type safety: Full IDE autocomplete and type checking
- Explicitness: Clear configuration dependencies
- Testability: Easy to mock and test
- Maintainability: No hidden factory patterns or monkey-patching
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from actingweb.config import Config
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
        SubscriptionSuspensionProtocol,
    )


# =============================================================================
# Property Database Accessors
# =============================================================================


def get_property(config: "Config") -> "DbPropertyProtocol":
    """Create a DbProperty instance with configuration injected.

    This is the recommended way to instantiate DbProperty objects as it ensures
    that property lookup table settings (use_lookup_table, indexed_properties)
    are properly configured.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbProperty instance configured with indexed_properties and use_lookup_table

    Example:
        >>> from actingweb.db import get_property
        >>> db = get_property(config)
        >>> db.set(actor_id="abc123", name="email", value="user@example.com")
    """
    return config.DbProperty.DbProperty(
        use_lookup_table=config.use_lookup_table,
        indexed_properties=config.indexed_properties,
    )


def get_property_list(config: "Config") -> "DbPropertyListProtocol":
    """Create a DbPropertyList instance for batch property operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbPropertyList instance

    Example:
        >>> from actingweb.db import get_property_list
        >>> db_list = get_property_list(config)
        >>> props = db_list.fetch(actor_id="abc123")
    """
    return config.DbProperty.DbPropertyList()


# =============================================================================
# Actor Database Accessors
# =============================================================================


def get_actor(config: "Config") -> "DbActorProtocol":
    """Create a DbActor instance for actor database operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbActor instance

    Example:
        >>> from actingweb.db import get_actor
        >>> db = get_actor(config)
        >>> actor_data = db.get(actor_id="abc123")
    """
    return config.DbActor.DbActor()


def get_actor_list(config: "Config") -> "DbActorListProtocol":
    """Create a DbActorList instance for batch actor operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbActorList instance

    Example:
        >>> from actingweb.db import get_actor_list
        >>> db_list = get_actor_list(config)
        >>> all_actors = db_list.fetch()
    """
    return config.DbActor.DbActorList()


# =============================================================================
# Trust Database Accessors
# =============================================================================


def get_trust(config: "Config") -> "DbTrustProtocol":
    """Create a DbTrust instance for trust relationship operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbTrust instance

    Example:
        >>> from actingweb.db import get_trust
        >>> db = get_trust(config)
        >>> trust_data = db.get(actor_id="abc123", peerid="peer456")
    """
    return config.DbTrust.DbTrust()


def get_trust_list(config: "Config") -> "DbTrustListProtocol":
    """Create a DbTrustList instance for batch trust operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbTrustList instance

    Example:
        >>> from actingweb.db import get_trust_list
        >>> db_list = get_trust_list(config)
        >>> all_trusts = db_list.fetch(actor_id="abc123")
    """
    return config.DbTrust.DbTrustList()


# =============================================================================
# PeerTrustee Database Accessors
# =============================================================================


def get_peer_trustee(config: "Config") -> "DbPeerTrusteeProtocol":
    """Create a DbPeerTrustee instance for peer trustee operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbPeerTrustee instance

    Example:
        >>> from actingweb.db import get_peer_trustee
        >>> db = get_peer_trustee(config)
        >>> peer_data = db.get(actor_id="abc123", peer_type="myapp")
    """
    return config.DbPeerTrustee.DbPeerTrustee()


def get_peer_trustee_list(config: "Config") -> "DbPeerTrusteeListProtocol":
    """Create a DbPeerTrusteeList instance for batch peer trustee operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbPeerTrusteeList instance

    Example:
        >>> from actingweb.db import get_peer_trustee_list
        >>> db_list = get_peer_trustee_list(config)
        >>> all_peers = db_list.fetch(actor_id="abc123")
    """
    return config.DbPeerTrustee.DbPeerTrusteeList()


# =============================================================================
# Subscription Database Accessors
# =============================================================================


def get_subscription(config: "Config") -> "DbSubscriptionProtocol":
    """Create a DbSubscription instance for subscription operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbSubscription instance

    Example:
        >>> from actingweb.db import get_subscription
        >>> db = get_subscription(config)
        >>> sub_data = db.get(actor_id="abc123", subid="sub789")
    """
    return config.DbSubscription.DbSubscription()


def get_subscription_list(config: "Config") -> "DbSubscriptionListProtocol":
    """Create a DbSubscriptionList instance for batch subscription operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbSubscriptionList instance

    Example:
        >>> from actingweb.db import get_subscription_list
        >>> db_list = get_subscription_list(config)
        >>> all_subs = db_list.fetch(actor_id="abc123")
    """
    return config.DbSubscription.DbSubscriptionList()


# =============================================================================
# Subscription Diff Database Accessors
# =============================================================================


def get_subscription_diff(config: "Config") -> "DbSubscriptionDiffProtocol":
    """Create a DbSubscriptionDiff instance for subscription diff operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbSubscriptionDiff instance

    Example:
        >>> from actingweb.db import get_subscription_diff
        >>> db = get_subscription_diff(config)
        >>> diff_data = db.get(actor_id="abc123", subid="sub789", seqnr=5)
    """
    return config.DbSubscriptionDiff.DbSubscriptionDiff()


def get_subscription_diff_list(config: "Config") -> "DbSubscriptionDiffListProtocol":
    """Create a DbSubscriptionDiffList instance for batch diff operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbSubscriptionDiffList instance

    Example:
        >>> from actingweb.db import get_subscription_diff_list
        >>> db_list = get_subscription_diff_list(config)
        >>> all_diffs = db_list.fetch(actor_id="abc123", subid="sub789")
    """
    return config.DbSubscriptionDiff.DbSubscriptionDiffList()


# =============================================================================
# Subscription Suspension Database Accessors
# =============================================================================


def get_subscription_suspension(config: "Config") -> "SubscriptionSuspensionProtocol":
    """Create a DbSubscriptionSuspension instance for suspension state management.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbSubscriptionSuspension instance

    Example:
        >>> from actingweb.db import get_subscription_suspension
        >>> db = get_subscription_suspension(config)
        >>> db.suspend(target="properties", subtarget="email")
    """
    return config.DbSubscriptionSuspension.DbSubscriptionSuspension()


# =============================================================================
# Attribute Database Accessors
# =============================================================================


def get_attribute(config: "Config") -> "DbAttributeProtocol":
    """Create a DbAttribute instance for internal attribute storage operations.

    Attributes are used for internal storage (not exposed via ActingWeb protocol).
    They support bucketed key-value storage with timestamps and TTL.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbAttribute instance

    Example:
        >>> from actingweb.db import get_attribute
        >>> db = get_attribute(config)
        >>> db.set_attr(
        ...     actor_id="abc123",
        ...     bucket="cache",
        ...     name="profile_data",
        ...     data={"name": "John", "email": "john@example.com"}
        ... )
    """
    return config.DbAttribute.DbAttribute()


def get_attribute_bucket_list(config: "Config") -> "DbAttributeBucketListProtocol":
    """Create a DbAttributeBucketList instance for batch attribute operations.

    Args:
        config: ActingWeb configuration instance

    Returns:
        DbAttributeBucketList instance

    Example:
        >>> from actingweb.db import get_attribute_bucket_list
        >>> db_list = get_attribute_bucket_list(config)
        >>> all_attrs = db_list.fetch(actor_id="abc123")
    """
    return config.DbAttribute.DbAttributeBucketList()


# =============================================================================
# Convenience Function: Get All DB Accessors
# =============================================================================


def get_db_accessors() -> dict[str, Any]:
    """Get a dictionary of all database accessor factory functions.

    This is primarily useful for testing or bulk operations where you need
    to access all accessor functions programmatically.

    Returns:
        Dictionary mapping accessor names to callable factory functions

    Example:
        >>> from actingweb.db import get_db_accessors
        >>> accessors = get_db_accessors()
        >>> property_db = accessors['property'](config)
        >>> actor_db = accessors['actor'](config)
    """
    return {
        "property": get_property,
        "property_list": get_property_list,
        "actor": get_actor,
        "actor_list": get_actor_list,
        "trust": get_trust,
        "trust_list": get_trust_list,
        "peer_trustee": get_peer_trustee,
        "peer_trustee_list": get_peer_trustee_list,
        "subscription": get_subscription,
        "subscription_list": get_subscription_list,
        "subscription_diff": get_subscription_diff,
        "subscription_diff_list": get_subscription_diff_list,
        "subscription_suspension": get_subscription_suspension,
        "attribute": get_attribute,
        "attribute_bucket_list": get_attribute_bucket_list,
    }


# Export public API
__all__ = [
    # Property accessors
    "get_property",
    "get_property_list",
    # Actor accessors
    "get_actor",
    "get_actor_list",
    # Trust accessors
    "get_trust",
    "get_trust_list",
    # PeerTrustee accessors
    "get_peer_trustee",
    "get_peer_trustee_list",
    # Subscription accessors
    "get_subscription",
    "get_subscription_list",
    "get_subscription_diff",
    "get_subscription_diff_list",
    "get_subscription_suspension",
    # Attribute accessors
    "get_attribute",
    "get_attribute_bucket_list",
    # Utility
    "get_db_accessors",
]
