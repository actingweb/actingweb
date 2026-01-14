"""
Database backend protocols defining the contract all backends must implement.

These protocols use typing.Protocol to enable structural typing - any class
implementing these methods will be compatible, without explicit inheritance.

All database backends (DynamoDB, PostgreSQL, etc.) must implement these protocols
to ensure consistent interfaces across the ActingWeb codebase.
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# =============================================================================
# Actor Protocols
# =============================================================================


@runtime_checkable
class DbActorProtocol(Protocol):
    """Protocol for actor database operations."""

    handle: Any | None

    def get(self, actor_id: str | None = None) -> dict[str, Any] | None:
        """
        Retrieve actor by ID.

        Args:
            actor_id: The actor ID to retrieve

        Returns:
            dict with keys: id, creator, passphrase, or None if not found
        """
        ...

    def get_by_creator(
        self, creator: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        Get actors by creator field.

        Args:
            creator: The creator email to search for

        Returns:
            Single dict if one found, list of dicts if multiple found, None if none found
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Create new actor.

        Args:
            actor_id: Unique actor ID
            creator: Creator email
            passphrase: Actor passphrase

        Returns:
            True on success, False on failure
        """
        ...

    def modify(
        self, creator: str | None = None, passphrase: bytes | None = None
    ) -> bool:
        """
        Modify existing actor using self.handle.

        Args:
            creator: New creator email (optional)
            passphrase: New passphrase bytes (optional)

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete actor using self.handle.

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbActorListProtocol(Protocol):
    """Protocol for actor list operations."""

    handle: Any | None

    def fetch(self) -> list[dict[str, Any]] | bool:
        """
        Fetch all actors.

        Returns:
            List of actor dicts, or False on error
        """
        ...


# =============================================================================
# Property Protocols
# =============================================================================


@runtime_checkable
class DbPropertyProtocol(Protocol):
    """Protocol for property operations."""

    handle: Any | None

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """
        Get property value.

        Args:
            actor_id: The actor ID
            name: The property name

        Returns:
            Property value as string, or None if not found
        """
        ...

    def get_actor_id_from_property(
        self, name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Reverse lookup: find actor by property value.

        Args:
            name: Property name
            value: Property value to search for

        Returns:
            Actor ID if found, None otherwise
        """
        ...

    def set(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """
        Set property value (empty value deletes).

        Args:
            actor_id: The actor ID
            name: Property name
            value: Property value (None or empty string deletes)

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete property using self.handle.

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbPropertyListProtocol(Protocol):
    """Protocol for property list operations."""

    handle: Any | None
    actor_id: str | None
    props: dict[str, str] | None

    def fetch(self, actor_id: str | None = None) -> dict[str, str] | None:
        """
        Retrieve all properties for an actor (excluding list: properties).

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        ...

    def fetch_all_including_lists(
        self, actor_id: str | None = None
    ) -> dict[str, str] | None:
        """
        Retrieve ALL properties including list properties.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        ...

    def delete(self) -> bool:
        """
        Delete all properties for the actor.

        Returns:
            True on success, False on failure
        """
        ...


# =============================================================================
# Trust Protocols
# =============================================================================


@runtime_checkable
class DbTrustProtocol(Protocol):
    """Protocol for trust relationship operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve trust from database.

        Args:
            actor_id: The actor ID
            peerid: Peer ID (takes precedence over token)
            token: Secret token for lookup

        Returns:
            Trust dict with all fields, or None if not found
        """
        ...

    def modify(
        self,
        baseuri: str | None = None,
        secret: str | None = None,
        desc: str | None = None,
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
        # Unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # OAuth2 client metadata
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
    ) -> bool:
        """
        Modify trust using self.handle.

        Returns:
            True on success, False on failure
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        baseuri: str = "",
        peer_type: str = "",
        relationship: str = "",
        secret: str = "",
        approved: str = "",
        verified: bool = False,
        peer_approved: bool = False,
        verification_token: str = "",
        desc: str = "",
        # Unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # OAuth2 client metadata
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
    ) -> bool:
        """
        Create new trust.

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete trust using self.handle.

        Returns:
            True on success, False on failure
        """
        ...

    @staticmethod
    def is_token_in_db(actor_id: str | None = None, token: str | None = None) -> bool:
        """
        Check if token exists in database.

        Args:
            actor_id: The actor ID
            token: Secret token to check

        Returns:
            True if token found, False otherwise
        """
        ...


@runtime_checkable
class DbTrustListProtocol(Protocol):
    """Protocol for trust list operations."""

    handle: Any | None
    actor_id: str | None
    trusts: list[dict[str, Any]]

    def fetch(self, actor_id: str | None) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all trusts for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of trust dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all trusts for the actor.

        Returns:
            True on success, False on failure
        """
        ...


# =============================================================================
# PeerTrustee Protocols
# =============================================================================


@runtime_checkable
class DbPeerTrusteeProtocol(Protocol):
    """Protocol for peer trustee operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peer_type: str | None = None,
        peerid: str | None = None,
    ) -> dict[str, Any] | bool | None:
        """
        Retrieve peer trustee from database.

        Args:
            actor_id: The actor ID
            peer_type: Type of peer (alternative to peerid)
            peerid: Peer ID

        Returns:
            PeerTrustee dict, False on error, or None if not found
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Create new peer trustee.

        Returns:
            True on success, False on failure
        """
        ...

    def modify(
        self,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Modify peer trustee using self.handle.

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete peer trustee using self.handle.

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbPeerTrusteeListProtocol(Protocol):
    """Protocol for peer trustee list operations."""

    handle: Any | None
    actor_id: str | None
    peertrustees: list[dict[str, Any]] | None

    def fetch(self, actor_id: str | None = None) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all peer trustees for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of peer trustee dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all peer trustees for the actor.

        Returns:
            True on success, False on failure
        """
        ...


# =============================================================================
# Subscription Protocols
# =============================================================================


@runtime_checkable
class DbSubscriptionProtocol(Protocol):
    """Protocol for subscription operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription from database.

        Args:
            actor_id: The actor ID
            peerid: Peer ID
            subid: Subscription ID

        Returns:
            Subscription dict, or None if not found
        """
        ...

    def modify(
        self,
        peerid: str | None = None,
        subid: str | None = None,
        granularity: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        seqnr: int | None = None,
        callback: bool | None = None,
    ) -> bool:
        """
        Modify subscription using self.handle.

        Returns:
            True on success, False on failure
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
        granularity: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        seqnr: int = 1,
        callback: bool = False,
    ) -> bool:
        """
        Create new subscription.

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete subscription using self.handle.

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbSubscriptionListProtocol(Protocol):
    """Protocol for subscription list operations."""

    handle: Any | None
    actor_id: str | None
    subscriptions: list[dict[str, Any]]

    def fetch(self, actor_id: str | None) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all subscriptions for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of subscription dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all subscriptions for the actor.

        Returns:
            True on success, False on failure
        """
        ...


# =============================================================================
# SubscriptionDiff Protocols
# =============================================================================


@runtime_checkable
class DbSubscriptionDiffProtocol(Protocol):
    """Protocol for subscription diff operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        seqnr: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription diff from database.

        Args:
            actor_id: The actor ID
            subid: Subscription ID
            seqnr: Sequence number (optional, finds lowest if not specified)

        Returns:
            SubscriptionDiff dict, or None if not found
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        diff: str = "",
        seqnr: int = 1,
    ) -> bool:
        """
        Create new subscription diff.

        Returns:
            True on success, False on failure
        """
        ...

    def delete(self) -> bool:
        """
        Delete subscription diff using self.handle.

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbSubscriptionDiffListProtocol(Protocol):
    """Protocol for subscription diff list operations."""

    handle: Any | None
    diffs: list[dict[str, Any]]
    actor_id: str | None
    subid: str | None

    def fetch(
        self, actor_id: str | None = None, subid: str | None = None
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve subscription diffs for an actor.

        Args:
            actor_id: The actor ID
            subid: Optional subscription ID to filter

        Returns:
            List of diff dicts, or empty list
        """
        ...

    def delete(self, seqnr: int | None = None) -> bool:
        """
        Delete subscription diffs.

        Args:
            seqnr: Optional sequence number (deletes up to and including this seqnr)

        Returns:
            True on success, False on failure
        """
        ...


# =============================================================================
# Attribute Protocols
# =============================================================================


@runtime_checkable
class DbAttributeProtocol(Protocol):
    """Protocol for attribute operations (internal storage)."""

    @staticmethod
    def get_bucket(
        actor_id: str | None = None, bucket: str | None = None
    ) -> dict[str, dict[str, Any]] | None:
        """
        Get all attributes from a bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name

        Returns:
            Dict of {attr_name: {"data": ..., "timestamp": ...}}, or None
        """
        ...

    @staticmethod
    def get_attr(
        actor_id: str | None = None, bucket: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get single attribute from bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name

        Returns:
            Dict with "data" and "timestamp", or None
        """
        ...

    @staticmethod
    def set_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set attribute value.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            data: Data to store (JSON-serializable)
            timestamp: Optional timestamp
            ttl_seconds: Optional TTL in seconds

        Returns:
            True on success, False on failure
        """
        ...

    def delete_attr(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
    ) -> bool:
        """
        Delete single attribute.

        Returns:
            True on success, False on failure
        """
        ...

    @staticmethod
    def conditional_update_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        old_data: Any = None,
        new_data: Any = None,
        timestamp: datetime | None = None,
    ) -> bool:
        """
        Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp

        Returns:
            True if update succeeded (current matched old_data), False otherwise
        """
        ...

    @staticmethod
    def delete_bucket(actor_id: str | None = None, bucket: str | None = None) -> bool:
        """
        Delete entire bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name

        Returns:
            True on success, False on failure
        """
        ...


@runtime_checkable
class DbAttributeBucketListProtocol(Protocol):
    """Protocol for attribute bucket list operations."""

    @staticmethod
    def fetch(
        actor_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """
        Retrieve all attributes for an actor grouped by bucket.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {bucket: {name: {"data": ..., "timestamp": ...}}}, or None
        """
        ...

    @staticmethod
    def delete(actor_id: str | None = None) -> bool:
        """
        Delete all attributes for the actor.

        Args:
            actor_id: The actor ID

        Returns:
            True on success, False on failure
        """
        ...
