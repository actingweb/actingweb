# mypy: disable-error-code="override"
import logging
import os

from pynamodb.attributes import UnicodeAttribute
from pynamodb.models import Model

logger = logging.getLogger(__name__)

"""
    DbPropertyLookup handles all db operations for property lookup table
    AWS DynamoDB is used as a backend.
"""


class PropertyLookup(Model):
    """
    DynamoDB data model for property lookup table.

    Replaces GSI on Property.value to avoid 2048-byte limit.
    Key design: (property_name, value) enables efficient lookups and
    distributes load across property name partitions.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_property_lookup"
        read_capacity_units = 2
        write_capacity_units = 1
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)
        # Optional PynamoDB configuration attributes
        connect_timeout_seconds: int | None = None
        read_timeout_seconds: int | None = None
        max_retry_attempts: int | None = None
        max_pool_connections: int | None = None
        extra_headers: dict[str, str] | None = None
        aws_access_key_id: str | None = None
        aws_secret_access_key: str | None = None
        aws_session_token: str | None = None

    # Composite primary key: property_name (hash) + value (range)
    property_name = UnicodeAttribute(hash_key=True)
    value = UnicodeAttribute(range_key=True)
    actor_id = UnicodeAttribute()


class DbPropertyLookup:
    """
    DbPropertyLookup handles all db operations for property lookup table.

    This table enables reverse lookups (property value → actor_id) without
    DynamoDB's 2048-byte GSI key size limit.
    """

    def __init__(self) -> None:
        self.handle: PropertyLookup | None = None
        if not PropertyLookup.exists():
            PropertyLookup.create_table(wait=True)

    def get(
        self, property_name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Retrieve actor_id by property name and value.

        Args:
            property_name: Property name (e.g., "oauthId")
            value: Property value to lookup

        Returns:
            Actor ID if found, None otherwise
        """
        if not property_name or not value:
            return None

        try:
            self.handle = PropertyLookup.get(property_name, value, consistent_read=True)
            return str(self.handle.actor_id) if self.handle.actor_id else None
        except Exception:  # PynamoDB DoesNotExist exception
            return None

    def create(
        self,
        property_name: str | None = None,
        value: str | None = None,
        actor_id: str | None = None,
    ) -> bool:
        """
        Create lookup entry.

        Args:
            property_name: Property name
            value: Property value
            actor_id: Actor ID

        Returns:
            True on success, False on failure
        """
        if not property_name or not value or not actor_id:
            return False

        try:
            self.handle = PropertyLookup(
                property_name=property_name,
                value=value,
                actor_id=actor_id,
            )
            self.handle.save()
            return True
        except Exception as e:
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} value_len={len(value)} "
                f"actor={actor_id} error={e}"
            )
            return False

    def delete(self) -> bool:
        """Delete lookup entry after get()."""
        if not self.handle:
            return False

        try:
            self.handle.delete()
            self.handle = None
            return True
        except Exception as e:
            logger.error(f"LOOKUP_DELETE_FAILED: error={e}")
            return False
