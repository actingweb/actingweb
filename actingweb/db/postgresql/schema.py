"""
SQLAlchemy models for PostgreSQL schema definition.

These models are ONLY used for Alembic migration generation.
The actual database implementation uses raw psycopg3 queries, not SQLAlchemy ORM.

This ensures:
1. Clean migration management via Alembic
2. No ORM overhead in production code
3. Consistent schema across environments
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Actor(Base):
    """Actor table - stores actor entities."""

    __tablename__ = "actors"

    id = Column(String(255), primary_key=True)
    creator = Column(String(255), nullable=False, index=True)
    passphrase = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Property(Base):
    """Property table - key-value storage per actor."""

    __tablename__ = "properties"
    __table_args__ = (
        PrimaryKeyConstraint("id", "name"),
        Index("idx_properties_value", "value"),
    )

    id = Column(String(255), nullable=False)  # actor_id
    name = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)


class PropertyLookup(Base):
    """Property lookup table - reverse index for property values → actor_id."""

    __tablename__ = "property_lookup"
    __table_args__ = (
        PrimaryKeyConstraint("property_name", "value"),
        Index("idx_property_lookup_actor_id", "actor_id"),
        ForeignKeyConstraint(
            ["actor_id"],
            ["actors.id"],
            name="fk_property_lookup_actor",
            ondelete="CASCADE",
        ),
    )

    property_name = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)  # No size limit!
    actor_id = Column(String(255), nullable=False)


class Trust(Base):
    """Trust table - trust relationships between actors."""

    __tablename__ = "trusts"
    __table_args__ = (
        PrimaryKeyConstraint("id", "peerid"),
        Index("idx_trusts_secret", "secret"),
    )

    # Composite primary key
    id = Column(String(255), nullable=False)  # actor_id
    peerid = Column(String(255), nullable=False)

    # Core trust fields
    baseuri = Column(Text, nullable=False)
    type = Column(String(255), nullable=False)
    relationship = Column(String(255), nullable=False)
    secret = Column(String(255), nullable=False)
    desc = Column(Text)
    approved = Column(Boolean, nullable=False)
    peer_approved = Column(Boolean, nullable=False)
    verified = Column(Boolean, nullable=False)
    verification_token = Column(String(255))

    # Unified trust fields
    peer_identifier = Column(String(255))
    established_via = Column(String(255))
    created_at = Column(DateTime)
    last_accessed = Column(DateTime)
    last_connected_via = Column(String(255))

    # OAuth2 client metadata
    client_name = Column(String(255))
    client_version = Column(String(255))
    client_platform = Column(String(255))
    oauth_client_id = Column(String(255))


class PeerTrustee(Base):
    """PeerTrustee table - peers where this actor is trustee."""

    __tablename__ = "peertrustees"
    __table_args__ = (PrimaryKeyConstraint("id", "peerid"),)

    id = Column(String(255), nullable=False)  # actor_id
    peerid = Column(String(255), nullable=False)
    baseuri = Column(Text, nullable=False)
    type = Column(String(255), nullable=False)
    passphrase = Column(Text, nullable=False)


class Subscription(Base):
    """Subscription table - event subscriptions between actors."""

    __tablename__ = "subscriptions"
    __table_args__ = (PrimaryKeyConstraint("id", "peer_sub_id"),)

    id = Column(String(255), nullable=False)  # actor_id
    peer_sub_id = Column(String(255), nullable=False)  # peerid:subid composite
    peerid = Column(String(255), nullable=False)
    subid = Column(String(255), nullable=False)
    granularity = Column(String(255))
    target = Column(String(255))
    subtarget = Column(String(255))
    resource = Column(String(255))
    seqnr = Column(Integer, default=1, nullable=False)
    callback = Column(Boolean, nullable=False)


class SubscriptionDiff(Base):
    """SubscriptionDiff table - subscription change diffs."""

    __tablename__ = "subscription_diffs"
    __table_args__ = (PrimaryKeyConstraint("id", "subid_seqnr"),)

    id = Column(String(255), nullable=False)  # actor_id
    subid_seqnr = Column(String(255), nullable=False)  # subid:seqnr composite
    subid = Column(String(255), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    diff = Column(Text, nullable=False)
    seqnr = Column(Integer, default=1, nullable=False)


class Attribute(Base):
    """Attribute table - internal attributes with bucketing and TTL support."""

    __tablename__ = "attributes"
    __table_args__ = (
        PrimaryKeyConstraint("id", "bucket_name"),
        # Index for TTL cleanup queries
        Index(
            "idx_attributes_ttl",
            "ttl_timestamp",
            postgresql_where="ttl_timestamp IS NOT NULL",
        ),
    )

    id = Column(String(255), nullable=False)  # actor_id
    bucket_name = Column(String(255), nullable=False)  # bucket:name composite
    bucket = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    data = Column(JSONB)
    timestamp = Column(DateTime)
    # TTL timestamp for automatic cleanup (Unix epoch timestamp)
    ttl_timestamp = Column(BigInteger)
