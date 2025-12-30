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
        """Retrives an actor_id based on the value of a property."""
        if not name or not value:
            return None
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

        if not value or (hasattr(value, "__len__") and len(value) == 0):
            if self.get(actor_id=actor_id, name=name):
                self.delete()
            return True
        if not self.handle:
            if not actor_id:
                return False
            self.handle = Property(id=actor_id, name=name, value=value)
        else:
            self.handle.value = value
        self.handle.save()
        return True

    def delete(self) -> bool:
        """Deletes the property in the database after a get()"""
        if not self.handle:
            return False
        self.handle.delete()
        self.handle = None
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
        self.handle = Property.scan(Property.id == self.actor_id)
        if not self.handle:
            return False
        for p in self.handle:
            p.delete()
        self.handle = None
        return True
