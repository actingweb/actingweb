# mypy: disable-error-code="override"
import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

logger = logging.getLogger(__name__)

"""
    DbProperty handles all db operations for a property
    AWS DynamoDB is used as a backend.
"""


class PropertyIndex(GlobalSecondaryIndex[Any]):
    """
    Secondary index on property
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        index_name = "property-index"
        read_capacity_units = 2
        write_capacity_units = 1
        projection = AllProjection()

    value = UnicodeAttribute(default="0", hash_key=True)


class Property(Model):
    """
    DynamoDB data model for a property
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_properties"
        read_capacity_units = 26
        write_capacity_units = 2
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

    id = UnicodeAttribute(hash_key=True)
    name = UnicodeAttribute(range_key=True)
    value = UnicodeAttribute()
    property_index = PropertyIndex()


class DbProperty:
    """
    DbProperty does all the db operations for property objects

    The actor_id must always be set. get(), set() and
    get_actor_id_from_property() will set a new internal handle
    that will be reused by set() (overwrite property) and
    delete().
    """

    def __init__(self) -> None:
        self.handle: Property | None = None
        if not Property.exists():
            Property.create_table(wait=True)

    def _should_index_property(self, name: str) -> bool:
        """
        Check if property should be indexed in lookup table.

        Returns True if:
        1. Lookup table mode is enabled (config.use_lookup_table)
        2. Property name is in configured indexed_properties list
        """
        from actingweb.config import Config

        config = Config()
        return config.use_lookup_table and name in config.indexed_properties

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """Retrieves the property from the database"""
        if not actor_id or not name:
            return None
        if self.handle:
            try:
                self.handle.refresh()
            except Exception:  # PynamoDB DoesNotExist exception
                return None
            return str(self.handle.value) if self.handle.value else None
        try:
            self.handle = Property.get(actor_id, name, consistent_read=True)
        except Exception:  # PynamoDB DoesNotExist exception
            return None
        return str(self.handle.value) if self.handle.value else None

    def get_actor_id_from_property(
        self, name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Reverse lookup: find actor by property value.

        Uses lookup table if configured, otherwise falls back to GSI.

        Args:
            name: Property name (e.g., "oauthId")
            value: Property value to search for

        Returns:
            Actor ID if found, None otherwise
        """
        if not name or not value:
            return None

        from actingweb.config import Config

        config = Config()

        if config.use_lookup_table and name in config.indexed_properties:
            # Use new lookup table approach
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            lookup = DbPropertyLookup()
            actor_id = lookup.get(property_name=name, value=value)

            if actor_id:
                # Load the property into self.handle for subsequent operations
                try:
                    self.handle = Property.get(actor_id, name, consistent_read=True)
                except Exception:
                    logger.warning(
                        f"Lookup found actor {actor_id} but property {name} doesn't exist"
                    )
                    return None

            return actor_id
        else:
            # Fall back to legacy GSI approach
            results = Property.property_index.query(value)
            self.handle = None
            for res in results:
                self.handle = res
                break

            if not self.handle:
                return None

            return str(self.handle.id) if self.handle.id else None

    def set(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Sets a new value for the property name"""
        if not name:
            return False

        # Convert non-string values to JSON strings for storage
        import json

        if value is not None and not isinstance(value, str):
            try:
                value = json.dumps(value)
            except (TypeError, ValueError):
                value = str(value)

        # Handle empty value (deletion)
        if not value or (hasattr(value, "__len__") and len(value) == 0):
            if self.get(actor_id=actor_id, name=name):
                self.delete()  # This will also delete lookup entry
            return True

        # Get old value before updating (for lookup sync)
        old_value = None
        if self._should_index_property(name):
            if self.handle and self.handle.value:
                old_value = str(self.handle.value)

        # Save property
        if not self.handle:
            if not actor_id:
                return False
            self.handle = Property(id=actor_id, name=name, value=value)
        else:
            self.handle.value = value

        self.handle.save()

        # Update lookup table if property is indexed
        if self._should_index_property(name):
            # Use handle.id which is guaranteed to be set after save()
            handle_actor_id = str(self.handle.id) if self.handle.id else actor_id
            if handle_actor_id:
                self._update_lookup_entry(handle_actor_id, name, old_value, value)

        return True

    def _update_lookup_entry(
        self, actor_id: str, name: str, old_value: str | None, new_value: str
    ) -> None:
        """
        Update lookup table entry (delete old, create new).

        Best-effort update - logs errors but doesn't fail property write.
        """
        try:
            from actingweb.db.dynamodb.property_lookup import (
                DbPropertyLookup,
                PropertyLookup,
            )

            # Ensure table exists
            DbPropertyLookup()

            # Delete old lookup entry if exists
            # Note: Theoretical race condition if another actor creates same value
            # between get() and delete(), but best-effort design accepts this edge case
            if old_value and old_value != new_value:
                try:
                    lookup = PropertyLookup.get(name, old_value)
                    if str(lookup.actor_id) == actor_id:  # Verify it's ours
                        lookup.delete()
                except Exception:
                    pass  # Entry doesn't exist or already deleted

            # Create new lookup entry (skip if value unchanged)
            if not old_value or old_value != new_value:
                lookup = PropertyLookup(
                    property_name=name, value=new_value, actor_id=actor_id
                )
                lookup.save()

        except Exception as e:
            logger.error(
                f"LOOKUP_TABLE_SYNC_FAILED: actor={actor_id} property={name} "
                f"old_value_len={len(old_value) if old_value else 0} "
                f"new_value_len={len(new_value)} error={e}"
            )
            # Don't fail the property write - accept eventual consistency

    def _delete_lookup_entry(self, actor_id: str | None, name: str, value: str) -> None:
        """
        Delete lookup table entry.

        Best-effort deletion - logs errors but doesn't fail property delete.
        """
        try:
            from actingweb.db.dynamodb.property_lookup import (
                DbPropertyLookup,
                PropertyLookup,
            )

            # Ensure table exists
            DbPropertyLookup()

            lookup = PropertyLookup.get(name, value)
            # Verify it belongs to the same actor before deleting
            if str(lookup.actor_id) == actor_id:
                lookup.delete()
        except Exception as e:
            logger.warning(
                f"LOOKUP_DELETE_FAILED: actor={actor_id} property={name} "
                f"value_len={len(value)} error={e}"
            )
            # Don't fail the property delete

    def delete(self) -> bool:
        """Deletes the property in the database after a get()"""
        if not self.handle:
            return False

        # Save values before deletion
        actor_id = str(self.handle.id) if self.handle.id else None
        name = str(self.handle.name) if self.handle.name else None
        value = str(self.handle.value) if self.handle.value else None

        # Delete property
        self.handle.delete()
        self.handle = None

        # Delete lookup entry if property is indexed
        if name and value and self._should_index_property(name):
            self._delete_lookup_entry(actor_id, name, value)

        return True


class DbPropertyList:
    """
    DbPropertyList does all the db operations for list of property objects

    The actor_id must always be set.
    """

    def __init__(self) -> None:
        self.handle: Any | None = None
        self.actor_id: str | None = None
        self.props: dict[str, str] | None = None
        if not Property.exists():
            Property.create_table(wait=True)

    def fetch(self, actor_id: str | None = None) -> dict[str, str] | None:
        """Retrieves the properties of an actor_id from the database"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Property.scan(Property.id == actor_id)
        if self.handle:
            self.props = {}
            for d in self.handle:
                # Filter out list properties (they have "list:" prefix)
                if not d.name.startswith("list:"):
                    self.props[d.name] = d.value
            return self.props
        else:
            return None

    def fetch_all_including_lists(
        self, actor_id: str | None = None
    ) -> dict[str, str] | None:
        """Retrieves ALL properties including list properties - for internal PropertyListStore use"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Property.scan(Property.id == actor_id)
        if self.handle:
            props = {}
            for d in self.handle:
                props[d.name] = d.value
            return props
        else:
            return None

    def delete(self) -> bool:
        """Deletes all the properties in the database"""
        if not self.actor_id:
            return False

        # Collect indexed properties before deletion
        indexed_props: list[tuple[str, str]] = []

        from actingweb.config import Config

        config = Config()

        if config.use_lookup_table:
            # Scan properties to find indexed ones
            self.handle = Property.scan(Property.id == self.actor_id)
            for p in self.handle:
                if str(p.name) in config.indexed_properties:
                    indexed_props.append((str(p.name), str(p.value)))

        # Delete all properties
        self.handle = Property.scan(Property.id == self.actor_id)
        if not self.handle:
            return False

        for p in self.handle:
            p.delete()

        # Delete lookup entries
        if indexed_props:
            from actingweb.db.dynamodb.property_lookup import (
                DbPropertyLookup,
                PropertyLookup,
            )

            # Ensure table exists
            DbPropertyLookup()

            for name, value in indexed_props:
                try:
                    lookup = PropertyLookup.get(name, value)
                    lookup.delete()
                except Exception as e:
                    logger.warning(f"Failed to delete lookup entry {name}={value}: {e}")

        self.handle = None
        return True
