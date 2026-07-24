# mypy: disable-error-code="override"
import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.indexes import AllProjection, GlobalSecondaryIndex
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table

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
        projection = AllProjection()

    value = UnicodeAttribute(default="0", hash_key=True)


class Property(Model):
    """
    DynamoDB data model for a property.

    Deliberately declares NO global secondary index: in lookup-table mode
    (the reverse-lookup mechanism of record) the legacy value-keyed GSI
    would only add write/storage amplification and DynamoDB's 2048-byte
    GSI-key limit on every property value. Tables created through this
    class therefore have no GSI. Legacy-mode deployments create the table
    through :class:`PropertyLegacy` instead — the schema a deployment
    creates matches the code path its configuration selects.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_properties"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
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


class PropertyLegacy(Model):
    """Legacy schema variant of the SAME properties table (deprecated).

    Identical item shape to :class:`Property` plus the value-keyed
    ``property-index`` GSI. Used only (a) to create the table when the
    deployment runs in legacy reverse-lookup mode, and (b) to query the
    GSI on the legacy reverse-lookup path. All regular data-plane
    operations go through :class:`Property` — the two classes are
    item-compatible. Removed in the next major release together with the
    legacy path.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_properties"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

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

    def __init__(
        self,
        use_lookup_table: bool | None = None,
        indexed_properties: list[str] | None = None,
    ) -> None:
        """Initialize DbProperty.

        Args:
            use_lookup_table: Whether to use property lookup table. If None, reads from env.
            indexed_properties: List of property names to index. If None, uses defaults.
        """
        self.handle: Property | PropertyLegacy | None = None

        # Store configuration for lookup table (resolved before table
        # creation — the mode decides which schema a fresh table gets)
        if use_lookup_table is not None:
            self._use_lookup_table = use_lookup_table
        else:
            self._use_lookup_table = (
                os.getenv("USE_PROPERTY_LOOKUP_TABLE", "true").lower() == "true"
            )

        if indexed_properties is not None:
            self._indexed_properties = indexed_properties
        else:
            self._indexed_properties = ["oauthId", "email", "externalUserId"]
            if os.getenv("INDEXED_PROPERTIES"):
                env_props = os.getenv("INDEXED_PROPERTIES", "").split(",")
                self._indexed_properties = [p.strip() for p in env_props if p.strip()]

        # Lookup mode creates the table WITHOUT the legacy GSI; legacy mode
        # keeps it. Existing tables are never altered — first creator wins.
        ensure_table(Property if self._use_lookup_table else PropertyLegacy)

    def _should_index_property(self, name: str) -> bool:
        """
        Check if property should be indexed in lookup table.

        Returns True if:
        1. Lookup table mode is enabled
        2. Property name is in configured indexed_properties list
        """
        return self._use_lookup_table and name in self._indexed_properties

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

        if self._use_lookup_table:
            if name not in self._indexed_properties:
                # Enforce the documented contract: only properties configured
                # via with_indexed_properties() support reverse lookup. The
                # old behaviour silently fell through to the legacy GSI,
                # which crashes on tables created without that index.
                logger.warning(
                    f"Reverse lookup requested for non-indexed property "
                    f"'{name}' — add it to with_indexed_properties() (or "
                    f"INDEXED_PROPERTIES) to enable reverse lookup; "
                    f"returning None"
                )
                return None

            # Use lookup table approach
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            lookup = DbPropertyLookup()
            actor_id = lookup.get(property_name=name, value=value)

            if actor_id is None:
                # Migration fallback tier 1: the deprecated v1 lookup table
                # (deployments that adopted lookup mode before the v2 digest
                # format). A hit means the v2 backfill has not run yet.
                actor_id = lookup.get_v1(property_name=name, value=value)
                if actor_id:
                    logger.warning(
                        f"DEPRECATED: reverse lookup for '{name}' served from "
                        f"the v1 lookup table — run "
                        f"scripts/backfill_property_lookup.py to migrate to "
                        f"the v2 format, then drop the v1 table. This "
                        f"fallback is removed in the next major release."
                    )

            if actor_id is None:
                # Migration fallback tier 2: the legacy value-keyed GSI
                # (deployments upgrading from legacy mode with an un-backfilled
                # lookup table). Missing index/table is a normal state.
                try:
                    # The GSI is keyed on value alone; filter by name so a
                    # same-value/different-property row on another actor
                    # can't hijack the lookup.
                    for res in PropertyLegacy.property_index.query(
                        value, filter_condition=PropertyLegacy.name == name
                    ):
                        actor_id = str(res.id) if res.id else None
                        break
                except Exception:
                    actor_id = None
                if actor_id:
                    logger.warning(
                        f"DEPRECATED: reverse lookup for '{name}' served from "
                        f"the legacy property-index GSI — run "
                        f"scripts/backfill_property_lookup.py to populate the "
                        f"lookup table. This fallback is removed in the next "
                        f"major release."
                    )

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
            # Legacy GSI approach (deprecated)
            try:
                results = PropertyLegacy.property_index.query(value)
                self.handle = None
                for res in results:
                    self.handle = res
                    break
            except Exception as e:
                if "index" in str(e).lower() or "ValidationException" in str(e):
                    raise RuntimeError(
                        f"Legacy property-index GSI is missing from table "
                        f"'{Property.Meta.table_name}'. Reverse lookup is "
                        f"configured to use the legacy DynamoDB GSI "
                        f"(use_lookup_table=False), but this table has no "
                        f"'property-index' GSI — it was created without one, "
                        f"and the library cannot add a GSI to a live table. "
                        f"Three ways to resolve: "
                        f"(1) RECOMMENDED: switch to lookup-table mode with "
                        f"with_legacy_property_index(enable=False) and run "
                        f"scripts/backfill_property_lookup.py; "
                        f"(2) keep legacy mode and add the GSI to the live "
                        f"table via 'aws dynamodb update-table' — note this "
                        f"imposes a 2048-byte limit on ALL property values; "
                        f"(3) disable reverse lookup entirely with "
                        f"with_indexed_properties([]). "
                        f"See docs/migration/v3.13 for details."
                    ) from e
                raise

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

        from actingweb.db.utils import sanitize_json_data

        if value is not None and not isinstance(value, str):
            try:
                # Defensive sanitization of own data before JSON encoding
                sanitized_value = sanitize_json_data(value, log_source="property")
                value = json.dumps(sanitized_value)
            except (TypeError, ValueError):
                value = str(value)
        elif isinstance(value, str):
            # Sanitize string values too — surrogates in pre-serialized JSON
            # strings bypass json.dumps sanitization and corrupt storage
            value = sanitize_json_data(value, log_source="property")

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
            elif actor_id:
                # PropertyStore.__setattr__ builds a fresh DbProperty for
                # every write, so self.handle is unset on the primary public
                # path. Read the current stored value (like the PostgreSQL
                # backend) so changing an indexed value deletes its stale
                # lookup row instead of leaving it to resolve forever.
                old_value = self.get(actor_id=actor_id, name=name)

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
        # Unchanged value: nothing to sync — avoids a delete+put per
        # repeated write of the same indexed value.
        if old_value is not None and old_value == new_value:
            return
        try:
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            db = DbPropertyLookup()

            # Delete the old entry if it exists and belongs to this actor.
            # Note: theoretical race if another actor creates the same value
            # between get() and delete(); best-effort design accepts this.
            if old_value:
                if db.get(property_name=name, value=old_value) == actor_id:
                    db.delete()

            # Conditional create: a row owned by another actor is a logged
            # collision, not a silent overwrite (see DbPropertyLookup.create).
            db.create(property_name=name, value=new_value, actor_id=actor_id)

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
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            db = DbPropertyLookup()
            # Verify it belongs to the same actor before deleting
            if db.get(property_name=name, value=value) == actor_id:
                db.delete()
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

    def __init__(
        self,
        use_lookup_table: bool | None = None,
        indexed_properties: list[str] | None = None,
    ) -> None:
        """Initialize DbPropertyList.

        Args:
            use_lookup_table: Whether to use property lookup table. If None, reads from env.
            indexed_properties: List of property names to index. If None, uses defaults.
        """
        self.handle: Any | None = None
        self.actor_id: str | None = None
        self.props: dict[str, str] | None = None

        if use_lookup_table is not None:
            self._use_lookup_table = use_lookup_table
        else:
            self._use_lookup_table = (
                os.getenv("USE_PROPERTY_LOOKUP_TABLE", "true").lower() == "true"
            )

        if indexed_properties is not None:
            self._indexed_properties = indexed_properties
        else:
            self._indexed_properties = ["oauthId", "email", "externalUserId"]
            if os.getenv("INDEXED_PROPERTIES"):
                env_props = os.getenv("INDEXED_PROPERTIES", "").split(",")
                self._indexed_properties = [p.strip() for p in env_props if p.strip()]

        # Lookup mode creates the table WITHOUT the legacy GSI; legacy mode
        # keeps it. Existing tables are never altered — first creator wins.
        ensure_table(Property if self._use_lookup_table else PropertyLegacy)

    def fetch(self, actor_id: str | None = None) -> dict[str, str] | None:
        """Retrieves the properties of an actor_id from the database"""
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.handle = Property.query(actor_id)
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
        self.handle = Property.query(actor_id)
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

        # Single partition read: collect indexed properties (for lookup-row
        # cleanup) and delete in the same pass.
        indexed_props: list[tuple[str, str]] = []
        self.handle = Property.query(self.actor_id)
        for p in self.handle:
            if self._use_lookup_table and str(p.name) in self._indexed_properties:
                indexed_props.append((str(p.name), str(p.value)))
            p.delete()

        # Delete lookup entries
        if indexed_props:
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            db = DbPropertyLookup()
            for name, value in indexed_props:
                try:
                    # Verify ownership before deleting: a shared indexed value
                    # may map to another actor's row, which must survive this
                    # actor's deletion.
                    if db.get(property_name=name, value=value) == self.actor_id:
                        db.delete()
                except Exception as e:
                    logger.warning(
                        f"Failed to delete lookup entry for property {name}: {e}"
                    )

        self.handle = None
        return True
