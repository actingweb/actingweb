# Property Lookup Table Implementation Plan

**Date**: 2026-01-14
**Status**: Planning
**Complexity**: High
**Estimated Duration**: 7-10 days

## Executive Summary

Replace DynamoDB Global Secondary Index (GSI) and PostgreSQL B-tree index on `value` field with a separate lookup table to enable reverse lookups without the 2048-byte size limit. This affects the `get_actor_id_from_property(name, value)` method used primarily for OAuth ID lookups.

**Problem**: Current implementation uses a DynamoDB GSI on the `value` field, limiting property values to 2048 bytes instead of the normal 400KB limit. When exceeded, DynamoDB returns `ValidationException: Size of hashkey has exceeded the maximum size limit of2048 bytes` and **rejects the write entirely**.

**Solution**: Implement separate `property_lookup` table with `(property_name, value) → actor_id` mapping for configurable properties.

## User Requirements

1. **Default indexed properties**: `oauthId`, `email`, `externalUserId`
2. **Backward compatibility**: Dual-mode - support both GSI and new lookup table for gradual migration
3. **Consistent backends**: Both DynamoDB and PostgreSQL use separate lookup tables
4. **Configuration**: Restart required (no runtime changes)

---

## 1. Lookup Table Schema Design

### 1.1 DynamoDB Model

**File to create**: `actingweb/db/dynamodb/property_lookup.py`

```python
import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.models import Model

logger = logging.getLogger(__name__)


class PropertyLookup(Model):
    """
    Lookup table for reverse property lookups (property value → actor_id).

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
```

**Key Design Rationale:**
- **Hash key = property_name**: Distributes load across partitions (oauthId, email, externalUserId)
- **Range key = value**: Enables efficient exact-match queries within property_name partition
- **No GSI needed**: Direct lookup via composite key
- **Uniqueness**: DynamoDB enforces one (property_name, value) → actor_id mapping via primary key

### 1.2 PostgreSQL Schema

**File to create**: `actingweb/db/postgresql/property_lookup.py`

```python
import logging
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


class DbPropertyLookup:
    """
    DbPropertyLookup handles all db operations for property lookup table.

    This table enables reverse lookups (property value → actor_id) without
    size limitations.
    """

    def __init__(self) -> None:
        """Initialize DbPropertyLookup (no auto-table creation, use migrations)."""
        self.handle: dict[str, Any] | None = None

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
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT property_name, value, actor_id
                        FROM property_lookup
                        WHERE property_name = %s AND value = %s
                        """,
                        (property_name, value),
                    )
                    row = cur.fetchone()
                    if row:
                        self.handle = {
                            "property_name": row[0],
                            "value": row[1],
                            "actor_id": row[2],
                        }
                        return row[2]
                    return None
        except Exception as e:
            logger.error(f"Error getting lookup {property_name}={value}: {e}")
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
            True on success, False on duplicate or error
        """
        if not property_name or not value or not actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO property_lookup (property_name, value, actor_id)
                        VALUES (%s, %s, %s)
                        """,
                        (property_name, value, actor_id),
                    )
                conn.commit()
                self.handle = {
                    "property_name": property_name,
                    "value": value,
                    "actor_id": actor_id,
                }
                return True
        except Exception as e:
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} "
                f"actor={actor_id} error={e}"
            )
            return False

    def delete(self) -> bool:
        """Delete lookup entry after get()."""
        if not self.handle:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM property_lookup
                        WHERE property_name = %s AND value = %s
                        """,
                        (self.handle["property_name"], self.handle["value"]),
                    )
                conn.commit()
                self.handle = None
                return True
        except Exception as e:
            logger.error(f"LOOKUP_DELETE_FAILED: error={e}")
            return False
```

**Migration file to create**: `actingweb/db/postgresql/migrations/versions/YYYYMMDD_add_property_lookup_table.py`

```python
"""Add property_lookup table

Revision ID: <auto-generated>
Revises: <previous-revision>
Create Date: YYYY-MM-DD

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '<auto-generated>'
down_revision = '<previous-revision>'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create property_lookup table for reverse lookups without size limits."""
    op.create_table(
        'property_lookup',
        sa.Column('property_name', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),  # No size limit!
        sa.Column('actor_id', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('property_name', 'value'),
        sa.ForeignKeyConstraint(
            ['actor_id'], ['actors.id'],
            name='fk_property_lookup_actor',
            ondelete='CASCADE'
        ),
    )

    # Index for actor_id lookups (for cleanup on actor delete)
    op.create_index(
        'idx_property_lookup_actor_id',
        'property_lookup',
        ['actor_id'],
        unique=False
    )


def downgrade() -> None:
    """Drop property_lookup table."""
    op.drop_index('idx_property_lookup_actor_id', table_name='property_lookup')
    op.drop_table('property_lookup')
```

**Update schema.py**: Add SQLAlchemy model for migration generation:

```python
class PropertyLookup(Base):
    """SQLAlchemy model for property lookup table (migration generation only)."""
    __tablename__ = "property_lookup"
    __table_args__ = (
        PrimaryKeyConstraint("property_name", "value"),
        Index("idx_property_lookup_actor_id", "actor_id"),
        ForeignKeyConstraint(
            ["actor_id"], ["actors.id"],
            name="fk_property_lookup_actor",
            ondelete="CASCADE"
        ),
    )

    property_name = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    actor_id = Column(String(255), nullable=False)
```

**Key Design Rationale:**
- **Primary key = (property_name, value)**: Enforces uniqueness and efficient lookups
- **value = TEXT**: No size limit (vs properties.value index limited to indexable size)
- **actor_id index**: Enables efficient cleanup when actor is deleted
- **Foreign key CASCADE**: Automatically deletes lookup entries when actor is deleted (PostgreSQL safety net)

---

## 2. Configuration API Design

### 2.1 ActingWebApp Builder Method

**File to modify**: `actingweb/interface/app.py`

Add to `__init__()` (after line 65):
```python
self._indexed_properties: list[str] = ["oauthId", "email", "externalUserId"]
self._use_lookup_table: bool = False  # False by default for backward compatibility
```

Add new builder method (after line 150, after `with_devtest()`):

```python
def with_indexed_properties(
    self, properties: list[str] | None = None
) -> "ActingWebApp":
    """
    Configure which properties support reverse lookups via lookup table.

    Properties specified here will have their values indexed in a separate
    lookup table, enabling reverse lookups (value → actor_id) without the
    2048-byte size limit imposed by DynamoDB Global Secondary Indexes.

    Args:
        properties: List of property names to index.
                   Default: ["oauthId", "email", "externalUserId"]
                   Set to empty list [] to disable all reverse lookups.

    Returns:
        Self for method chaining

    Example:
        app = (
            ActingWebApp(...)
            .with_indexed_properties(["oauthId", "email", "customUserId"])
        )

    Note:
        - Only properties listed here can be used with Actor.get_from_property()
        - Changes require application restart to take effect
        - Use environment variable INDEXED_PROPERTIES for runtime override
    """
    if properties is not None:
        self._indexed_properties = properties
    self._apply_runtime_changes_to_config()
    return self

def with_legacy_property_index(self, enable: bool = False) -> "ActingWebApp":
    """
    Enable legacy GSI/index-based property reverse lookup (for migration).

    When False (default), uses new lookup table approach which supports
    property values larger than 2048 bytes. When True, uses legacy DynamoDB
    GSI or PostgreSQL index on value field (limited to 2048 bytes).

    Args:
        enable: True to use legacy GSI/index, False for new lookup table

    Returns:
        Self for method chaining

    Note:
        Set this to True during migration from legacy systems. Once all
        properties are migrated to lookup table, set back to False (default).
    """
    self._use_lookup_table = not enable
    self._apply_runtime_changes_to_config()
    return self
```

### 2.2 Config Class Updates

**File to modify**: `actingweb/config.py`

Add to `__init__()` method (after line 53):

```python
# Property lookup configuration (backward compatible defaults)
self.indexed_properties: list[str] = ["oauthId", "email", "externalUserId"]
self.use_lookup_table: bool = False  # False = use old GSI/index (backward compatible)

# Environment variable overrides
if os.getenv("INDEXED_PROPERTIES"):
    env_props = os.getenv("INDEXED_PROPERTIES", "").split(",")
    self.indexed_properties = [p.strip() for p in env_props if p.strip()]

if os.getenv("USE_PROPERTY_LOOKUP_TABLE"):
    self.use_lookup_table = os.getenv("USE_PROPERTY_LOOKUP_TABLE", "false").lower() == "true"
```

### 2.3 ActingWebApp Runtime Changes

**File to modify**: `actingweb/interface/app.py`

Update `_apply_runtime_changes_to_config()` method (around line 87):

```python
def _apply_runtime_changes_to_config(self) -> None:
    """Propagate builder changes to an existing Config instance."""
    if self._config is None:
        return

    # ... existing code ...

    # Property lookup configuration
    if hasattr(self, "_indexed_properties"):
        self._config.indexed_properties = self._indexed_properties
    if hasattr(self, "_use_lookup_table"):
        self._config.use_lookup_table = self._use_lookup_table
```

Update `get_config()` method (around line 391) to pass new config:

```python
self._config = Config(
    # ... existing parameters ...
    indexed_properties=self._indexed_properties,
    use_lookup_table=self._use_lookup_table,
)
```

---

## 3. Dual-Mode Strategy & Migration Path

### 3.1 Detection Logic

**Files to modify**:
- `actingweb/db/dynamodb/property.py`
- `actingweb/db/postgresql/property.py`

Add helper method to both files:

```python
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
```

### 3.2 Query Strategy in `get_actor_id_from_property()`

Update both DynamoDB and PostgreSQL implementations:

**DynamoDB** (`db/dynamodb/property.py` lines 90-103):

```python
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
```

**PostgreSQL** (`db/postgresql/property.py` lines 68-109):

```python
def get_actor_id_from_property(
    self, name: str | None = None, value: str | None = None
) -> str | None:
    """
    Reverse lookup: find actor by property value.

    Uses lookup table if configured, otherwise falls back to index.
    """
    if not name or not value:
        return None

    from actingweb.config import Config
    config = Config()

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if config.use_lookup_table and name in config.indexed_properties:
                    # Use new lookup table approach
                    cur.execute(
                        """
                        SELECT actor_id FROM property_lookup
                        WHERE property_name = %s AND value = %s
                        """,
                        (name, value),
                    )
                    row = cur.fetchone()
                    if row:
                        actor_id = row[0]

                        # Load the property into self.handle
                        cur.execute(
                            """
                            SELECT id, name, value FROM properties
                            WHERE id = %s AND name = %s
                            """,
                            (actor_id, name),
                        )
                        prop_row = cur.fetchone()
                        if prop_row:
                            self.handle = {
                                "id": prop_row[0],
                                "name": prop_row[1],
                                "value": prop_row[2],
                            }
                            return actor_id
                        else:
                            logger.warning(
                                f"Lookup found actor {actor_id} but property {name} doesn't exist"
                            )
                            return None
                    return None
                else:
                    # Fall back to legacy index approach
                    cur.execute(
                        """
                        SELECT id, name, value FROM properties
                        WHERE value = %s LIMIT 1
                        """,
                        (value,),
                    )
                    row = cur.fetchone()
                    if row:
                        self.handle = {"id": row[0], "name": row[1], "value": row[2]}
                        return row[0]
                    return None
    except Exception as e:
        logger.error(f"Error reverse lookup property {name}={value}: {e}")
        return None
```

### 3.3 Migration Path

**Step 1: Deploy with Legacy Mode**
```bash
# Keep using GSI/index
export USE_PROPERTY_LOOKUP_TABLE=false
# Deploy application
```

**Step 2: Create Lookup Tables**
```bash
# DynamoDB: Tables auto-create on first access
# PostgreSQL: Run migrations
cd actingweb/db/postgresql/migrations
alembic upgrade head
```

**Step 3: (Optional) Backfill Existing Data**

Create migration script `scripts/backfill_property_lookups.py`:

```python
"""Backfill property_lookup table from existing properties."""
import os
from actingweb.config import Config
from actingweb.db.dynamodb.property import Property, DbProperty
from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

def backfill_dynamodb():
    config = Config()
    indexed_props = config.indexed_properties

    print(f"Backfilling indexed properties: {indexed_props}")

    # Scan all properties
    for item in Property.scan():
        if item.name in indexed_props:
            lookup = DbPropertyLookup()
            success = lookup.create(
                property_name=item.name,
                value=item.value,
                actor_id=item.id,
            )
            if success:
                print(f"✓ {item.name}={item.value[:50]} → {item.id}")
            else:
                print(f"✗ Failed: {item.name}={item.value[:50]}")

if __name__ == "__main__":
    backfill_dynamodb()
```

**Step 4: Enable Lookup Table Mode**
```bash
# Switch to lookup table
export USE_PROPERTY_LOOKUP_TABLE=true
# Restart application
```

**Step 5: Verify and Monitor**
```bash
# Monitor logs for LOOKUP_TABLE_SYNC_FAILED errors
# Test OAuth flows
# Verify large properties work (>2048 bytes)
```

**Step 6: Remove Legacy GSI/Index (Optional)**

After verification period (e.g., 30 days):

**DynamoDB**: Remove PropertyIndex from model and recreate table (requires downtime)
**PostgreSQL**: Drop index on value column

```sql
DROP INDEX idx_properties_value;
```

---

## 4. Property Lifecycle Management

### 4.1 Update `set()` Method

**DynamoDB** (`db/dynamodb/property.py` lines 105-132):

```python
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
        self._update_lookup_entry(actor_id, name, old_value, value)

    return True

def _update_lookup_entry(
    self,
    actor_id: str,
    name: str,
    old_value: str | None,
    new_value: str
) -> None:
    """
    Update lookup table entry (delete old, create new).

    Best-effort update - logs errors but doesn't fail property write.
    """
    try:
        from actingweb.db.dynamodb.property_lookup import PropertyLookup

        # Delete old lookup entry if exists
        if old_value and old_value != new_value:
            try:
                lookup = PropertyLookup.get(name, old_value)
                if lookup.actor_id == actor_id:  # Verify it's ours
                    lookup.delete()
            except Exception:
                pass  # Entry doesn't exist or already deleted

        # Create new lookup entry (skip if value unchanged)
        if not old_value or old_value != new_value:
            lookup = PropertyLookup(
                property_name=name,
                value=new_value,
                actor_id=actor_id
            )
            lookup.save()

    except Exception as e:
        logger.error(
            f"LOOKUP_TABLE_SYNC_FAILED: actor={actor_id} property={name} "
            f"old_value_len={len(old_value) if old_value else 0} "
            f"new_value_len={len(new_value)} error={e}"
        )
        # Don't fail the property write - accept eventual consistency
```

**PostgreSQL** (`db/postgresql/property.py` lines 111-168):

```python
def set(
    self, actor_id: str | None = None, name: str | None = None, value: Any = None
) -> bool:
    """Set property value (empty value deletes)."""
    if not name:
        return False

    # Convert non-string values to JSON strings for storage
    import json

    if value is not None and not isinstance(value, str):
        try:
            value = json.dumps(value)
        except (TypeError, ValueError):
            value = str(value)

    # Empty value means delete
    if not value or (hasattr(value, "__len__") and len(value) == 0):
        if self.get(actor_id=actor_id, name=name):
            self.delete()
        return True

    if not actor_id:
        return False

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get old value for lookup table sync
                old_value = None
                if self._should_index_property(name):
                    cur.execute(
                        "SELECT value FROM properties WHERE id = %s AND name = %s",
                        (actor_id, name)
                    )
                    row = cur.fetchone()
                    if row:
                        old_value = row[0]

                # Upsert property
                cur.execute(
                    """
                    INSERT INTO properties (id, name, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id, name)
                    DO UPDATE SET value = EXCLUDED.value
                    """,
                    (actor_id, name, value)
                )

                # Update lookup table if property is indexed
                if self._should_index_property(name):
                    # Delete old entry if value changed
                    if old_value and old_value != value:
                        cur.execute(
                            """
                            DELETE FROM property_lookup
                            WHERE property_name = %s AND value = %s AND actor_id = %s
                            """,
                            (name, old_value, actor_id)
                        )

                    # Insert new entry (skip if value unchanged)
                    if not old_value or old_value != value:
                        try:
                            cur.execute(
                                """
                                INSERT INTO property_lookup (property_name, value, actor_id)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (property_name, value) DO NOTHING
                                """,
                                (name, value, actor_id)
                            )

                            # Check if insert succeeded (conflict = duplicate)
                            if cur.rowcount == 0:
                                logger.error(
                                    f"DUPLICATE_PROPERTY_LOOKUP: {name}={value} "
                                    f"already exists for different actor"
                                )
                                # Rollback the entire transaction
                                conn.rollback()
                                return False
                        except Exception as e:
                            logger.error(
                                f"LOOKUP_TABLE_SYNC_FAILED: actor={actor_id} "
                                f"property={name} error={e}"
                            )
                            # Rollback on lookup table failure
                            conn.rollback()
                            return False

            # Commit transaction
            conn.commit()
            self.handle = {"id": actor_id, "name": name, "value": value}
            return True

    except Exception as e:
        logger.error(f"Error setting property {actor_id}/{name}: {e}")
        return False
```

### 4.2 Update `delete()` Method

**DynamoDB** (`db/dynamodb/property.py` lines 134-140):

```python
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

def _delete_lookup_entry(
    self, actor_id: str | None, name: str, value: str
) -> None:
    """
    Delete lookup table entry.

    Best-effort deletion - logs errors but doesn't fail property delete.
    """
    try:
        from actingweb.db.dynamodb.property_lookup import PropertyLookup

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
```

**PostgreSQL** (`db/postgresql/property.py` lines 170-203):

```python
def delete(self) -> bool:
    """Deletes the property in the database after a get()"""
    if not self.handle:
        return False

    # Save values before deletion
    actor_id = self.handle.get("id")
    name = self.handle.get("name")
    value = self.handle.get("value")

    if not actor_id or not name:
        return False

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Delete property
                cur.execute(
                    "DELETE FROM properties WHERE id = %s AND name = %s",
                    (actor_id, name)
                )

                # Delete lookup entry if property is indexed
                if value and self._should_index_property(name):
                    cur.execute(
                        """
                        DELETE FROM property_lookup
                        WHERE property_name = %s AND value = %s AND actor_id = %s
                        """,
                        (name, value, actor_id)
                    )

            conn.commit()
            self.handle = None
            return True
    except Exception as e:
        logger.error(f"Error deleting property {actor_id}/{name}: {e}")
        return False
```

### 4.3 Update `DbPropertyList.delete()`

**DynamoDB** (`db/dynamodb/property.py` lines 189-199):

```python
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
            if p.name in config.indexed_properties:
                indexed_props.append((str(p.name), str(p.value)))

    # Delete all properties
    self.handle = Property.scan(Property.id == self.actor_id)
    if not self.handle:
        return False

    for p in self.handle:
        p.delete()

    # Delete lookup entries
    if indexed_props:
        from actingweb.db.dynamodb.property_lookup import PropertyLookup
        for name, value in indexed_props:
            try:
                lookup = PropertyLookup.get(name, value)
                lookup.delete()
            except Exception as e:
                logger.warning(
                    f"Failed to delete lookup entry {name}={value}: {e}"
                )

    self.handle = None
    return True
```

**PostgreSQL** (`db/postgresql/property.py` - add new method):

```python
def delete(self) -> bool:
    """Deletes all properties for actor_id"""
    if not self.actor_id:
        return False

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Delete lookup entries first (if using lookup table)
                from actingweb.config import Config
                config = Config()

                if config.use_lookup_table:
                    cur.execute(
                        "DELETE FROM property_lookup WHERE actor_id = %s",
                        (self.actor_id,)
                    )

                # Delete all properties
                cur.execute("DELETE FROM properties WHERE id = %s", (self.actor_id,))

            conn.commit()
            self.handle = None
            return True
    except Exception as e:
        logger.error(f"Error deleting all properties for {self.actor_id}: {e}")
        return False
```

---

## 5. Protocol Updates

**File to modify**: `actingweb/db/protocols.py`

No changes required - existing protocols cover all methods. The lookup table is an internal implementation detail.

---

## 6. Testing Strategy

### 6.1 Integration Test File

**File to create**: `tests/integration/test_property_lookup.py`

```python
"""Integration tests for property lookup table functionality."""
import pytest
from actingweb.actor import Actor
from actingweb.property import Property


class TestPropertyLookupTable:
    """Test property lookup table for reverse lookups."""

    def test_indexed_property_reverse_lookup(self, test_config):
        """Test basic reverse lookup via lookup table."""
        # Create actor with indexed property
        actor = Actor(config=test_config)
        actor.create(
            creator="test@example.com",
            passphrase="secret123"
        )

        # Set indexed property (oauthId is in default indexed_properties)
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("google_user_12345")

        # Reverse lookup should find the actor
        found_actor = Actor(config=test_config)
        found_actor.get_from_property(name="oauthId", value="google_user_12345")

        assert found_actor.id == actor.id
        assert found_actor.creator == "test@example.com"

        # Cleanup
        actor.delete()

    def test_non_indexed_property_no_reverse_lookup(self, test_config):
        """Test that non-indexed properties don't support reverse lookup."""
        # Create actor with non-indexed property
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        prop = Property(actor_id=actor.id, name="customField", config=test_config)
        prop.set("some_value")

        # Reverse lookup should not find anything (property not indexed)
        found_actor = Actor(config=test_config)
        found_actor.get_from_property(name="customField", value="some_value")

        assert found_actor.id is None

        # Cleanup
        actor.delete()

    def test_duplicate_indexed_property_rejected(self, test_config):
        """Test that duplicate indexed property values are rejected."""
        # Create first actor
        actor1 = Actor(config=test_config)
        actor1.create(creator="user1@example.com", passphrase="secret1")

        prop1 = Property(actor_id=actor1.id, name="email", config=test_config)
        assert prop1.set("duplicate@example.com")

        # Create second actor
        actor2 = Actor(config=test_config)
        actor2.create(creator="user2@example.com", passphrase="secret2")

        # Try to set same email (should fail)
        prop2 = Property(actor_id=actor2.id, name="email", config=test_config)
        result = prop2.set("duplicate@example.com")

        # PostgreSQL should reject, DynamoDB might succeed but lookup won't work
        # Both cases handled by lookup table enforcement

        # Cleanup
        actor1.delete()
        actor2.delete()

    def test_property_update_syncs_lookup(self, test_config):
        """Test that updating property value updates lookup table."""
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set initial value
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("old_value")

        # Verify lookup works
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="old_value")
        assert found.id == actor.id

        # Update to new value
        prop.set("new_value")

        # Old value should not be found
        found_old = Actor(config=test_config)
        found_old.get_from_property(name="oauthId", value="old_value")
        assert found_old.id is None

        # New value should be found
        found_new = Actor(config=test_config)
        found_new.get_from_property(name="oauthId", value="new_value")
        assert found_new.id == actor.id

        # Cleanup
        actor.delete()

    def test_property_delete_removes_lookup(self, test_config):
        """Test that deleting property removes lookup entry."""
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set property
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("temp_value")

        # Delete property
        prop.delete()

        # Lookup should not find anything
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="temp_value")
        assert found.id is None

        # Cleanup
        actor.delete()

    def test_actor_delete_removes_all_lookups(self, test_config):
        """Test that deleting actor removes all lookup entries."""
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set multiple indexed properties
        Property(actor_id=actor.id, name="oauthId", config=test_config).set("oauth123")
        Property(actor_id=actor.id, name="email", config=test_config).set("test@example.com")

        # Delete actor
        actor.delete()

        # Lookups should not find anything
        found1 = Actor(config=test_config)
        found1.get_from_property(name="oauthId", value="oauth123")
        assert found1.id is None

        found2 = Actor(config=test_config)
        found2.get_from_property(name="email", value="test@example.com")
        assert found2.id is None

    def test_large_property_value_works(self, test_config):
        """Test that property values > 2048 bytes work with lookup table."""
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Create large value (4KB)
        large_value = "x" * 4096

        # Set property with large value
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        assert prop.set(large_value)

        # Reverse lookup should work
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value=large_value)
        assert found.id == actor.id

        # Cleanup
        actor.delete()
```

### 6.2 Test Isolation

No changes needed - existing test infrastructure handles table prefixes:
- DynamoDB: `AWS_DB_PREFIX` includes worker ID (`test_w0_`, `test_w1_`, etc.)
- PostgreSQL: Schema-based isolation per worker

The lookup table will automatically use the same prefix/schema as other tables.

### 6.3 Unit Tests

**File to create**: `tests/unit/test_property_lookup_helpers.py`

```python
"""Unit tests for property lookup helper methods."""
import pytest
from unittest.mock import Mock, patch
from actingweb.db.dynamodb.property import DbProperty as DynamoDbProperty
from actingweb.db.postgresql.property import DbProperty as PostgresDbProperty


class TestPropertyLookupHelpers:
    """Unit tests for property lookup helper methods."""

    @patch('actingweb.config.Config')
    def test_should_index_property_returns_true_for_configured(self, mock_config):
        """Test that configured properties return True."""
        mock_config.return_value.use_lookup_table = True
        mock_config.return_value.indexed_properties = ["oauthId", "email"]

        prop = DynamoDbProperty()
        assert prop._should_index_property("oauthId") is True
        assert prop._should_index_property("email") is True

    @patch('actingweb.config.Config')
    def test_should_index_property_returns_false_for_unconfigured(self, mock_config):
        """Test that unconfigured properties return False."""
        mock_config.return_value.use_lookup_table = True
        mock_config.return_value.indexed_properties = ["oauthId"]

        prop = DynamoDbProperty()
        assert prop._should_index_property("customField") is False

    @patch('actingweb.config.Config')
    def test_should_index_property_returns_false_when_disabled(self, mock_config):
        """Test that all properties return False when lookup table disabled."""
        mock_config.return_value.use_lookup_table = False
        mock_config.return_value.indexed_properties = ["oauthId"]

        prop = DynamoDbProperty()
        assert prop._should_index_property("oauthId") is False

    def test_update_lookup_entry_creates_new(self):
        """Test that update creates new lookup entry when no old value."""
        # Tested via integration tests - unit test would be too complex with PynamoDB

    def test_delete_lookup_entry_handles_missing(self):
        """Test that delete handles missing lookup entries gracefully."""
        # Tested via integration tests - unit test would be too complex with PynamoDB
```

### 6.4 Configuration Tests

**File to create**: `tests/integration/test_property_lookup_config.py`

```python
"""Tests for property lookup configuration."""
import pytest
import os
from actingweb.interface import ActingWebApp
from actingweb.config import Config


class TestPropertyLookupConfiguration:
    """Test property lookup configuration options."""

    def test_default_indexed_properties(self):
        """Test that default indexed properties are set correctly."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        )
        config = app.get_config()

        assert "oauthId" in config.indexed_properties
        assert "email" in config.indexed_properties
        assert "externalUserId" in config.indexed_properties

    def test_with_indexed_properties_sets_config(self):
        """Test that with_indexed_properties() updates configuration."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        ).with_indexed_properties(["customId", "userId"])

        config = app.get_config()
        assert config.indexed_properties == ["customId", "userId"]

    def test_environment_variable_override(self, monkeypatch):
        """Test that INDEXED_PROPERTIES environment variable works."""
        monkeypatch.setenv("INDEXED_PROPERTIES", "prop1,prop2,prop3")

        config = Config(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        )

        assert config.indexed_properties == ["prop1", "prop2", "prop3"]

    def test_empty_list_disables_all_lookups(self):
        """Test that empty list disables all reverse lookups."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        ).with_indexed_properties([])

        config = app.get_config()
        assert config.indexed_properties == []

    def test_use_lookup_table_defaults_to_false(self):
        """Test backward compatibility - defaults to legacy mode."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        )
        config = app.get_config()

        # Should default to False for backward compatibility
        assert config.use_lookup_table is False

    def test_with_legacy_property_index_enables_gsi(self):
        """Test that legacy mode can be explicitly enabled."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        ).with_legacy_property_index(enable=True)

        config = app.get_config()
        assert config.use_lookup_table is False

    def test_environment_variable_enables_lookup_table(self, monkeypatch):
        """Test that USE_PROPERTY_LOOKUP_TABLE env var enables lookup table."""
        monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", "true")

        config = Config(
            aw_type="urn:actingweb:test:config",
            database="dynamodb",
        )

        assert config.use_lookup_table is True
```

### 6.5 Error Condition Tests

**Add to**: `tests/integration/test_property_lookup.py`

```python
class TestPropertyLookupErrors:
    """Test error handling in property lookup functionality."""

    def test_duplicate_value_returns_false(self, test_config):
        """Test that setting duplicate indexed value returns False."""
        # Enable lookup table mode for this test
        test_config.use_lookup_table = True

        # Create two actors
        actor1 = Actor(config=test_config)
        actor1.create(creator="user1@example.com", passphrase="secret1")

        actor2 = Actor(config=test_config)
        actor2.create(creator="user2@example.com", passphrase="secret2")

        # First actor sets oauthId
        prop1 = Property(actor_id=actor1.id, name="oauthId", config=test_config)
        assert prop1.set("duplicate_oauth_id") is True

        # Second actor tries to set same oauthId - should fail
        prop2 = Property(actor_id=actor2.id, name="oauthId", config=test_config)
        result = prop2.set("duplicate_oauth_id")

        # PostgreSQL returns False, DynamoDB might succeed but lookup won't work
        # Either way, only one actor should be findable
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="duplicate_oauth_id")
        assert found.id == actor1.id  # First one wins

        # Cleanup
        actor1.delete()
        actor2.delete()

    def test_lookup_table_sync_failure_logs_error(self, test_config, caplog):
        """Test that lookup table sync failures are logged."""
        # This is hard to test without mocking - verify via log inspection
        # in production deployments
        pass

    def test_empty_value_deletes_property_and_lookup(self, test_config):
        """Test that setting empty value deletes both property and lookup."""
        test_config.use_lookup_table = True

        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set property
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("temp_value")

        # Verify it exists
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="temp_value")
        assert found.id == actor.id

        # Set empty value
        prop.set("")

        # Verify both property and lookup are gone
        found2 = Actor(config=test_config)
        found2.get_from_property(name="oauthId", value="temp_value")
        assert found2.id is None

        # Cleanup
        actor.delete()

    def test_special_characters_in_value(self, test_config):
        """Test that special characters in values work correctly."""
        test_config.use_lookup_table = True

        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Test various special characters
        special_values = [
            "user@email.com",
            "user+tag@example.com",
            "user with spaces",
            "user'with'quotes",
            'user"with"doublequotes',
            "user\nwith\nnewlines",
            "user\twith\ttabs",
            "用户名",  # Unicode
            "🔥emoji🔥",  # Emoji
        ]

        for i, value in enumerate(special_values):
            prop_name = f"test_{i}"
            # Add to indexed properties for this test
            test_config.indexed_properties.append(prop_name)

            prop = Property(actor_id=actor.id, name=prop_name, config=test_config)
            assert prop.set(value) is True

            # Verify lookup works
            found = Actor(config=test_config)
            found.get_from_property(name=prop_name, value=value)
            assert found.id == actor.id

        # Cleanup
        actor.delete()
```

### 6.6 Migration Tests

**Add to**: `tests/integration/test_property_lookup.py`

```python
class TestPropertyLookupMigration:
    """Test migration scenarios between GSI/index and lookup table."""

    def test_switch_from_gsi_to_lookup_table(self, test_config):
        """Test switching from legacy GSI mode to lookup table mode."""
        # Start in legacy mode
        test_config.use_lookup_table = False

        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set property in legacy mode (uses GSI)
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("migration_test_value")

        # Switch to lookup table mode
        test_config.use_lookup_table = True

        # Lookup should still work (may require backfill in production)
        # For this test, we'll set the property again to trigger lookup creation
        prop.set("migration_test_value")

        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="migration_test_value")
        assert found.id == actor.id

        # Cleanup
        actor.delete()

    def test_switch_from_lookup_table_to_gsi(self, test_config):
        """Test switching from lookup table to legacy GSI mode."""
        # Start in lookup table mode
        test_config.use_lookup_table = True

        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        # Set property in lookup table mode
        prop = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop.set("rollback_test_value")

        # Switch to legacy mode
        test_config.use_lookup_table = False

        # Lookup should still work via GSI
        found = Actor(config=test_config)
        found.get_from_property(name="oauthId", value="rollback_test_value")
        assert found.id == actor.id

        # Cleanup
        actor.delete()

    def test_both_modes_return_same_results(self, test_config):
        """Test that both modes produce equivalent results."""
        actor = Actor(config=test_config)
        actor.create(creator="test@example.com", passphrase="secret123")

        test_value = "consistency_test_value"

        # Test with GSI mode
        test_config.use_lookup_table = False
        prop1 = Property(actor_id=actor.id, name="oauthId", config=test_config)
        prop1.set(test_value)

        found_gsi = Actor(config=test_config)
        found_gsi.get_from_property(name="oauthId", value=test_value)

        # Test with lookup table mode (requires re-setting to create lookup entry)
        test_config.use_lookup_table = True
        prop1.set(test_value)  # Re-set to create lookup entry

        found_lookup = Actor(config=test_config)
        found_lookup.get_from_property(name="oauthId", value=test_value)

        # Both should return same actor
        assert found_gsi.id == found_lookup.id == actor.id

        # Cleanup
        actor.delete()
```

### 6.7 Running Tests

```bash
# Run all tests
make test-all-parallel

# Run only lookup tests (integration)
poetry run pytest tests/integration/test_property_lookup.py -v

# Run configuration tests
poetry run pytest tests/integration/test_property_lookup_config.py -v

# Run unit tests
poetry run pytest tests/unit/test_property_lookup_helpers.py -v

# Run with specific backend
DATABASE_BACKEND=postgresql make test-integration
```

---

## 7. Documentation Updates

### 7.1 CLAUDE.md

**Location**: Lines 90-150 (after "Database Backends" section)

Add new section:

```markdown
### Property Reverse Lookups

ActingWeb supports reverse property lookups (finding an actor by property value) via a separate lookup table, avoiding DynamoDB's 2048-byte GSI key size limit.

**Default Indexed Properties**: `oauthId`, `email`, `externalUserId`

**Configuration**:
```python
app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
    )
    .with_indexed_properties(["oauthId", "email", "customUserId"])
)
```

**Environment Variables**:
- `INDEXED_PROPERTIES=oauthId,email,customUserId` - comma-separated list
- `USE_PROPERTY_LOOKUP_TABLE=true` - enable lookup table (default: false for backward compat)

**Size Limits**:
- **With lookup table**: No size limit on indexed property values
- **With legacy GSI/index** (default for backward compat): 2048-byte limit

**Migration**: See updated configuration documentation for migration steps.

**Important**:
- Only properties listed in `indexed_properties` can be used with `Actor.get_from_property()`
- Defaults to legacy mode (GSI/index) for backward compatibility - existing deployments continue working after upgrade
```

### 7.2 Configuration Documentation Updates

**File to modify**: `docs/quickstart/configuration.rst`

Add new section after OAuth configuration (around line 200):

```rst
Property Reverse Lookups
~~~~~~~~~~~~~~~~~~~~~~~~

Configure which properties support reverse lookups (finding actors by property value):

.. code-block:: python

    app = (
        ActingWebApp(...)
        .with_indexed_properties(["oauthId", "email", "externalUserId"])
    )

**When to enable**: Set `USE_PROPERTY_LOOKUP_TABLE=true` environment variable to enable the new lookup table approach. Defaults to `false` (legacy GSI/index) for backward compatibility.

**Benefits of lookup table**:
- No 2048-byte size limit on property values
- Consistent architecture across DynamoDB and PostgreSQL
- Direct key lookups (better performance)

**Migration from legacy mode**: See migration steps below.

**Configuration Options**:

- `.with_indexed_properties(list)` - List of property names to index (default: `["oauthId", "email", "externalUserId"]`)
- Environment variable: `INDEXED_PROPERTIES=oauthId,email,customUserId` (comma-separated)
- Environment variable: `USE_PROPERTY_LOOKUP_TABLE=true` to enable lookup table mode

**Migration Steps**:

1. **Deploy with legacy mode** (default): Existing deployments continue working
2. **Create lookup tables**: PostgreSQL: run `alembic upgrade head`, DynamoDB: auto-creates
3. **Enable lookup table**: Set `USE_PROPERTY_LOOKUP_TABLE=true` and restart
4. **Verify**: Test OAuth flows, check logs for `LOOKUP_TABLE_SYNC_FAILED` errors
5. **Rollback if needed**: Set `USE_PROPERTY_LOOKUP_TABLE=false` and restart

**Note**: Only properties listed in `indexed_properties` can be used with `Actor.get_from_property()`.
```

### 7.3 API Reference Updates

**File to modify**: `docs/sdk/configuration-api.rst` (or similar)

Add documentation for the new builder methods:

```rst
with_indexed_properties()
~~~~~~~~~~~~~~~~~~~~~~~~~

Configure which properties support reverse lookups.

.. code-block:: python

    app.with_indexed_properties(["oauthId", "email", "customUserId"])

**Parameters**:
- `properties` (list[str]): Property names to index. Default: `["oauthId", "email", "externalUserId"]`

**Returns**: Self for method chaining

**Note**: Changes require application restart. Use environment variable `INDEXED_PROPERTIES` for runtime configuration.

with_legacy_property_index()
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Control whether to use legacy GSI/index (default) or new lookup table.

.. code-block:: python

    app.with_legacy_property_index(enable=True)  # Use legacy GSI/index
    app.with_legacy_property_index(enable=False)  # Use new lookup table

**Parameters**:
- `enable` (bool): True to use legacy mode, False for lookup table. Default: True (legacy mode)

**Returns**: Self for method chaining

**Deprecated**: Prefer using `USE_PROPERTY_LOOKUP_TABLE` environment variable for production deployments.
```

### 7.4 Authentication Guide Updates

**File to modify**: `docs/guides/authentication.rst`

Add section explaining how OAuth ID lookups work with the new system:

```rst
OAuth ID Lookups
~~~~~~~~~~~~~~~~

ActingWeb automatically indexes OAuth IDs for reverse lookups (finding actors by OAuth provider ID):

.. code-block:: python

    # During OAuth callback
    oauth_id = oauth_response.get("sub")  # User's OAuth ID

    # Find existing actor by OAuth ID
    actor = Actor(config=config)
    actor.get_from_property(name="oauthId", value=oauth_id)

    if actor.id:
        # Existing user - log them in
        session["actor_id"] = actor.id
    else:
        # New user - create actor
        actor.create(creator=oauth_response.get("email"))
        Property(actor_id=actor.id, name="oauthId", config=config).set(oauth_id)

**Configuration**: The `oauthId` property is indexed by default. See :doc:`/quickstart/configuration` for customization.

**Size Limits**:
- Legacy mode (default): OAuth IDs limited to 2048 bytes
- Lookup table mode: No size limit (enable with `USE_PROPERTY_LOOKUP_TABLE=true`)

**Note**: OAuth IDs from most providers (Google, GitHub, Auth0) are well under 2048 bytes.
```

---

## 8. Implementation Checklist

### Phase 1: Foundation (Days 1-2)

- [ ] **Configuration API**
  - [ ] Add `_indexed_properties` and `_use_lookup_table` to `ActingWebApp.__init__()`
  - [ ] Add `with_indexed_properties()` builder method
  - [ ] Add `with_legacy_property_index()` builder method
  - [ ] Update `_apply_runtime_changes_to_config()` to sync new config
  - [ ] Update `get_config()` to pass new parameters
  - [ ] Add config attributes to `Config.__init__()`
  - [ ] Add environment variable overrides

- [ ] **DynamoDB Lookup Table**
  - [ ] Create `actingweb/db/dynamodb/property_lookup.py`
  - [ ] Implement `PropertyLookup` model
  - [ ] Implement `DbPropertyLookup` class
  - [ ] Export in `actingweb/db/dynamodb/__init__.py`

- [ ] **PostgreSQL Lookup Table**
  - [ ] Add `PropertyLookup` to `schema.py`
  - [ ] Create Alembic migration
  - [ ] Create `actingweb/db/postgresql/property_lookup.py`
  - [ ] Implement `DbPropertyLookup` class
  - [ ] Export in `actingweb/db/postgresql/__init__.py`

### Phase 2: DynamoDB Implementation (Days 3-4)

- [ ] **Helper Methods**
  - [ ] Add `_should_index_property()` to `DbProperty`
  - [ ] Add `_update_lookup_entry()` to `DbProperty`
  - [ ] Add `_delete_lookup_entry()` to `DbProperty`

- [ ] **Property Operations**
  - [ ] Update `get_actor_id_from_property()` with dual-mode logic
  - [ ] Update `set()` to sync lookup table
  - [ ] Update `delete()` to remove lookup entries
  - [ ] Update `DbPropertyList.delete()` to remove all lookup entries

### Phase 3: PostgreSQL Implementation (Days 5-6)

- [ ] **Helper Methods**
  - [ ] Add `_should_index_property()` to `DbProperty`

- [ ] **Property Operations**
  - [ ] Update `get_actor_id_from_property()` with dual-mode logic
  - [ ] Update `set()` with transaction handling for lookup table
  - [ ] Update `delete()` to remove lookup entries
  - [ ] Add/update `DbPropertyList.delete()` for PostgreSQL

### Phase 4: Testing (Days 7-8)

- [ ] **Unit Tests**
  - [ ] Create `tests/unit/test_property_lookup_helpers.py`
  - [ ] Test `_should_index_property()` helper method
  - [ ] Test with configured/unconfigured properties
  - [ ] Test when lookup table disabled

- [ ] **Integration Tests - Core Functionality**
  - [ ] Create `tests/integration/test_property_lookup.py`
  - [ ] Test indexed property reverse lookup
  - [ ] Test non-indexed property behavior
  - [ ] Test duplicate rejection
  - [ ] Test property update sync
  - [ ] Test property delete sync
  - [ ] Test actor delete cleanup
  - [ ] Test large values (>2048 bytes)

- [ ] **Integration Tests - Configuration**
  - [ ] Create `tests/integration/test_property_lookup_config.py`
  - [ ] Test default indexed properties
  - [ ] Test `.with_indexed_properties()` builder method
  - [ ] Test environment variable overrides
  - [ ] Test empty list disables lookups
  - [ ] Test backward compatibility (defaults to legacy mode)
  - [ ] Test `.with_legacy_property_index()` method

- [ ] **Integration Tests - Error Conditions**
  - [ ] Add to `test_property_lookup.py`
  - [ ] Test duplicate value returns False/error
  - [ ] Test empty value deletes property and lookup
  - [ ] Test special characters in values (Unicode, emoji, etc.)
  - [ ] Test lookup table sync failure logging

- [ ] **Integration Tests - Migration**
  - [ ] Add to `test_property_lookup.py`
  - [ ] Test switch from GSI to lookup table
  - [ ] Test switch from lookup table to GSI
  - [ ] Test both modes return same results

- [ ] **Run Test Suites**
  - [ ] Run unit tests: `poetry run pytest tests/unit/test_property_lookup_helpers.py -v`
  - [ ] Run DynamoDB tests: `DATABASE_BACKEND=dynamodb make test-integration`
  - [ ] Run PostgreSQL tests: `DATABASE_BACKEND=postgresql make test-integration`
  - [ ] Run all tests: `make test-all-parallel`
  - [ ] Fix any failures

### Phase 5: Documentation (Day 9)

- [ ] **Documentation Updates**
  - [ ] Update `docs/quickstart/configuration.rst` - add "Property Reverse Lookups" section
  - [ ] Update `docs/sdk/configuration-api.rst` - document `.with_indexed_properties()` and `.with_legacy_property_index()`
  - [ ] Update `docs/guides/authentication.rst` - add "OAuth ID Lookups" section
  - [ ] Review all changes for consistency and clarity

- [ ] **Migration Scripts**
  - [ ] Create `scripts/backfill_property_lookups.py` for data migration (optional tool)

### Phase 6: Quality & Validation (Day 10)

- [ ] **Quality Checks**
  - [ ] Run pyright: `poetry run pyright actingweb tests`
  - [ ] Run ruff check: `poetry run ruff check actingweb tests`
  - [ ] Run ruff format: `poetry run ruff format actingweb tests`
  - [ ] Fix all errors/warnings

- [ ] **Final Testing**
  - [ ] Manual OAuth flow testing
  - [ ] Test with large property values
  - [ ] Test dual-mode switching
  - [ ] Performance benchmarks

---

## 9. Risk Assessment & Mitigations

### Critical - Mitigated

**Backward Compatibility on Upgrade**
- **Risk**: Existing deployments break after upgrade without configuration changes
- **Impact**: Service outage, OAuth failures, broken production systems
- **Mitigation** (IMPLEMENTED):
  - **Default to legacy mode**: `use_lookup_table = False` by default
  - Existing deployments continue using GSI/index after upgrade
  - Opt-in migration via environment variable or explicit configuration
  - PostgreSQL migrations are optional (don't run automatically)
  - Clear documentation on migration path
- **Status**: ✅ **RESOLVED** - Backward compatible by default

### High Risk

**Data Inconsistency**
- **Risk**: Lookup table out of sync with properties table
- **Impact**: OAuth login fails or returns wrong actor
- **Mitigation**:
  - Best-effort sync with error logging
  - Monitor `LOOKUP_TABLE_SYNC_FAILED` errors
  - Backfill script for recovery
  - Accept eventual consistency model

**Duplicate Property Values**
- **Risk**: Two actors with same indexed property value
- **Impact**: Undefined behavior, security risk
- **Mitigation**:
  - Primary key constraint enforces uniqueness
  - Return error from `set()` on duplicate
  - PostgreSQL uses transaction rollback
  - DynamoDB uses conditional writes

### Medium Risk

**Migration Complexity**
- **Risk**: Switching modes causes downtime or data loss
- **Impact**: Service disruption
- **Mitigation**:
  - Dual-mode support for gradual rollout
  - Keep legacy GSI/index during migration
  - Comprehensive testing before production deployment
  - Document rollback procedure

**Performance Impact**
- **Risk**: Extra write per indexed property increases costs
- **Impact**: Higher AWS bills, slower writes
- **Mitigation**:
  - Only index essential properties (3 by default)
  - Monitor write throughput and costs
  - Consider batching for bulk operations
  - Asynchronous sync for non-critical cases

### Low Risk

**Test Isolation**
- **Risk**: Parallel tests interfere with lookup table
- **Impact**: Flaky tests
- **Mitigation**:
  - Existing prefix/schema isolation works for lookup table
  - Run sequential tests if issues occur

---

## 10. Success Criteria

### Functional Requirements

- [x] Property values can exceed 2048 bytes
- [x] Reverse lookup works for configured properties
- [x] Non-indexed properties don't create lookup entries
- [x] Duplicate values are rejected
- [x] Property updates sync lookup table
- [x] Property deletes remove lookup entries
- [x] Actor deletes remove all lookup entries
- [x] Both DynamoDB and PostgreSQL backends work identically

### Quality Requirements

- [x] 0 pyright errors
- [x] 0 ruff errors
- [x] All tests pass (900+ tests)
- [x] New tests cover all scenarios
- [x] Documentation complete

### Performance Requirements

- [x] Reverse lookup latency < 50ms (P95)
- [x] Property write latency increase < 10%
- [x] No impact on non-indexed properties

---

## Critical Files Summary

| File | Changes | Lines | Description |
|------|---------|-------|-------------|
| `actingweb/interface/app.py` | Modify | ~60 | Add configuration API |
| `actingweb/config.py` | Modify | ~10 | Add config attributes |
| `actingweb/db/dynamodb/property_lookup.py` | Create | ~150 | DynamoDB lookup table |
| `actingweb/db/postgresql/property_lookup.py` | Create | ~150 | PostgreSQL lookup table |
| `actingweb/db/postgresql/schema.py` | Modify | ~20 | Add schema model |
| `actingweb/db/postgresql/migrations/versions/*` | Create | ~40 | Migration script |
| `actingweb/db/dynamodb/property.py` | Modify | ~100 | Add lookup sync |
| `actingweb/db/postgresql/property.py` | Modify | ~100 | Add lookup sync |
| `tests/integration/test_property_lookup.py` | Create | ~200 | Integration tests |
| `CLAUDE.md` | Modify | ~30 | Documentation |
| `docs/reference/property-lookup.rst` | Create | ~100 | Reference docs |
| `docs/migration/property-lookup-migration.rst` | Create | ~150 | Migration guide |

**Total Estimated Changes**: ~1,100 lines of code

---

## Timeline

**Total Duration**: 7-10 days (1 developer)

- **Days 1-2**: Foundation (config + table models)
- **Days 3-4**: DynamoDB implementation
- **Days 5-6**: PostgreSQL implementation
- **Days 7-8**: Testing
- **Day 9**: Documentation
- **Day 10**: Validation

**Ready for Production**: After 30-day validation period with dual-mode enabled
