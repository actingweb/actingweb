"""
Remote peer data storage.

Provides storage abstraction for data received from peer actors,
using internal attributes (not exposed via HTTP).
"""

import logging
import re
from datetime import UTC
from re import Pattern
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Default pattern matches actingweb library's UUID v5 .hex format
DEFAULT_PEER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")

# More permissive pattern that accepts both formats
PERMISSIVE_PEER_ID_PATTERN = re.compile(
    r"^[a-f0-9]{32}$|^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
)


def get_remote_bucket(
    peer_id: str, validate: bool = True, pattern: Pattern[str] | None = None
) -> str:
    """Get the standard bucket name for a remote peer's data.

    Args:
        peer_id: The peer's actor ID
        validate: Whether to validate peer_id format (default: True)
        pattern: Custom regex pattern for validation (default: 32-char hex)

    Returns:
        Bucket name in format "remote:{peer_id}"

    Raises:
        ValueError: If validate=True and peer_id format is invalid
    """
    if validate:
        pat = pattern or PERMISSIVE_PEER_ID_PATTERN
        if not pat.match(peer_id):
            raise ValueError(
                f"Invalid peer_id format: {peer_id}. Expected pattern: {pat.pattern}"
            )
    return f"remote:{peer_id}"


class RemotePeerStore:
    """
    Storage abstraction for data received from peer actors.

    Provides a clean interface for storing data in internal attributes
    (not exposed via HTTP). Each peer gets isolated storage in bucket
    "remote:{peer_id}".

    Supports automatic list operation handling for subscription callbacks.
    """

    def __init__(
        self,
        actor: "ActorInterface",
        peer_id: str,
        validate_peer_id: bool = True,
    ) -> None:
        """
        Initialize remote peer store.

        Args:
            actor: The actor storing peer data
            peer_id: The peer's actor ID
            validate_peer_id: Whether to validate peer_id format
        """
        self._actor = actor
        self._peer_id = peer_id
        self._bucket = get_remote_bucket(peer_id, validate=validate_peer_id)
        self._list_store: Any = None  # Lazy loaded

    @property
    def bucket(self) -> str:
        """Get the bucket name for this peer's data."""
        return self._bucket

    def _get_attributes(self) -> Any:
        """Get Attributes instance for this bucket."""
        from .attribute import Attributes

        return Attributes(
            actor_id=self._actor.id,
            bucket=self._bucket,
            config=self._actor.config,
        )

    def _get_list_store(self) -> Any:
        """Get AttributeListStore for this bucket (lazy loaded)."""
        if self._list_store is None:
            from .attribute_list_store import AttributeListStore

            self._list_store = AttributeListStore(
                actor_id=self._actor.id,
                bucket=self._bucket,
                config=self._actor.config,
            )
        return self._list_store

    # Scalar operations

    def get_value(self, name: str) -> dict[str, Any] | None:
        """Get a scalar value by name."""
        from .db.utils import sanitize_json_data

        db = self._get_attributes()
        attr = db.get_attr(name=name)
        # get_attr returns {"data": ..., "timestamp": ...} or None
        data = attr.get("data") if attr else None
        # Defense-in-depth: sanitize on read to catch surrogates that
        # survived storage (e.g., from JSON round-trip of \uD800 escapes)
        if data is not None:
            data = sanitize_json_data(data, log_source=f"read:peer:{self._peer_id}")
        return data

    def set_value(self, name: str, value: dict[str, Any]) -> None:
        """Set a scalar value from remote peer (sanitizes for security)."""
        from .db.utils import sanitize_json_data

        # Sanitize untrusted data from remote peer
        sanitized_value = sanitize_json_data(value, log_source=f"peer:{self._peer_id}")

        db = self._get_attributes()
        db.set_attr(name=name, data=sanitized_value)

    def delete_value(self, name: str) -> None:
        """Delete a scalar value."""
        db = self._get_attributes()
        db.delete_attr(name=name)

    # List operations

    def get_list(self, name: str) -> list[dict[str, Any]]:
        """Get a list by name."""
        from .db.utils import sanitize_json_data

        store = self._get_list_store()
        list_attr = getattr(store, name)
        items = list(list_attr)
        # Defense-in-depth: sanitize on read to catch surrogates that
        # survived storage (e.g., from JSON round-trip of \uD800 escapes)
        return sanitize_json_data(items, log_source=f"read:peer:{self._peer_id}")

    def set_list(
        self,
        name: str,
        items: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set a list from remote peer (sanitizes for security)."""
        from .db.utils import sanitize_json_data

        # Sanitize untrusted data from remote peer
        sanitized_items = sanitize_json_data(items, log_source=f"peer:{self._peer_id}")
        sanitized_metadata = (
            sanitize_json_data(metadata, log_source=f"peer:{self._peer_id}")
            if metadata
            else None
        )

        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.clear()
        list_attr.extend(sanitized_items)
        if sanitized_metadata:
            # ListAttribute only supports setting description and explanation
            if "description" in sanitized_metadata:
                list_attr.set_description(sanitized_metadata["description"])
            if "explanation" in sanitized_metadata:
                list_attr.set_explanation(sanitized_metadata["explanation"])

    def delete_list(self, name: str) -> None:
        """Delete a list entirely."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.delete()

    def list_all_lists(self) -> list[str]:
        """List all stored lists for this peer."""
        store = self._get_list_store()
        return store.list_all()

    def list_all_scalars(self) -> list[str]:
        """List all scalar property names for this peer.

        Returns:
            List of scalar property names (excludes list properties and their metadata)
        """
        db = self._get_attributes()
        all_attrs = db.get_bucket() or {}

        scalar_names = []
        for name in all_attrs.keys():
            # Skip internal list storage keys (list:*:meta, list:*:0, etc.)
            if not name.startswith("list:"):
                scalar_names.append(name)

        return scalar_names

    def get_all_properties(self) -> dict[str, Any]:
        """Get all properties (both lists and scalars) for this peer.

        Returns:
            Dictionary mapping property names to their metadata:
            {
                "property_name": {
                    "type": "list" | "scalar",
                    "value": <list of items> | <scalar value>,
                    "item_count": <int> (for lists only)
                }
            }

        Example:
            >>> store = RemotePeerStore(actor, peer_id)
            >>> props = store.get_all_properties()
            >>> print(props)
            {
                "memory_personal": {
                    "type": "list",
                    "value": [{"id": 1, "text": "..."}],
                    "item_count": 1
                },
                "status": {
                    "type": "scalar",
                    "value": {"active": True}
                }
            }
        """
        properties = {}

        # Get all list properties
        try:
            for list_name in self.list_all_lists():
                try:
                    items = self.get_list(list_name)
                    properties[list_name] = {
                        "type": "list",
                        "value": items,
                        "item_count": len(items),
                    }
                except Exception as e:
                    logger.warning(
                        f"Error reading list '{list_name}' for peer {self._peer_id}: {e}"
                    )
                    continue
        except Exception as e:
            logger.error(
                f"Error listing list properties for peer {self._peer_id}: {e}"
            )

        # Get all scalar properties
        try:
            for scalar_name in self.list_all_scalars():
                try:
                    value = self.get_value(scalar_name)
                    if value is not None:
                        properties[scalar_name] = {
                            "type": "scalar",
                            "value": value,
                        }
                except Exception as e:
                    logger.warning(
                        f"Error reading scalar '{scalar_name}' for peer {self._peer_id}: {e}"
                    )
                    continue
        except Exception as e:
            logger.error(
                f"Error listing scalar properties for peer {self._peer_id}: {e}"
            )

        return properties

    # Cleanup

    def delete_all(self) -> None:
        """Delete all data for this peer.

        Call this when trust relationship ends.
        """
        db = self._get_attributes()
        db.delete_bucket()
        logger.info(f"Deleted all data for peer {self._peer_id}")

    # Storage statistics

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics for this peer."""
        db = self._get_attributes()
        all_attrs = db.get_bucket() or {}

        list_count = 0
        scalar_count = 0
        for name in all_attrs.keys():
            if name.startswith("list:"):
                list_count += 1
            else:
                scalar_count += 1

        return {
            "peer_id": self._peer_id,
            "bucket": self._bucket,
            "list_count": list_count,
            "scalar_count": scalar_count,
            "total_attributes": len(all_attrs),
        }

    # Callback data application

    def apply_callback_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply callback data to storage, handling list operations.

        This is the main method for automatic storage mode. It:
        - Detects list operations (append, update, delete, etc.)
        - Applies them to the appropriate list
        - Stores scalar values directly

        SECURITY: Sanitizes untrusted data from remote peer before storage.

        Args:
            data: Callback data dict from subscription callback

        Returns:
            Dict of {property_name: operation_result} for each processed property
        """
        from .db.utils import sanitize_json_data

        # Sanitize untrusted callback data from remote peer
        data = sanitize_json_data(data, log_source=f"peer:{self._peer_id}:callback")

        results: dict[str, Any] = {}

        for key, value in data.items():
            try:
                # Detect list operations per ActingWeb spec:
                # List diff payloads have "list" and "operation" fields in the value
                if isinstance(value, dict) and "list" in value and "operation" in value:
                    # List operation (spec-compliant format)
                    list_name = value.get("list", key)
                    operation = value.get("operation", "unknown")
                    results[list_name] = self._apply_list_operation(
                        list_name, operation, value
                    )
                elif key.startswith("list:") and isinstance(value, dict):
                    # Legacy format: key has "list:" prefix
                    list_name = value.get("list", key[5:])
                    operation = value.get("operation", "unknown")
                    results[list_name] = self._apply_list_operation(
                        list_name, operation, value
                    )
                else:
                    # Per ActingWeb spec: "an empty attribute is defined as the
                    # same as a non-existent attribute, thus an attribute can be
                    # deleted by setting it to ''."
                    if value == "" or value is None:
                        self.delete_value(key)
                        results[key] = {"deleted": True, "type": "scalar"}
                    elif isinstance(value, dict):
                        self.set_value(key, value)
                        results[key] = {"stored": True, "type": "scalar"}
                    else:
                        # Wrap non-dict values
                        self.set_value(key, {"value": value})
                        results[key] = {
                            "stored": True,
                            "type": "scalar",
                            "wrapped": True,
                        }
            except Exception as e:
                logger.error(f"Error applying callback data for {key}: {e}")
                results[key] = {"error": str(e)}

        return results

    def _apply_list_operation(
        self, list_name: str, operation: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply a single list operation."""
        store = self._get_list_store()
        list_attr = getattr(store, list_name)

        if operation == "append" and "item" in data:
            list_attr.append(data["item"])
            return {"operation": "append", "success": True}

        elif operation == "insert" and "item" in data and "index" in data:
            list_attr.insert(data["index"], data["item"])
            return {"operation": "insert", "index": data["index"], "success": True}

        elif operation == "update" and "item" in data and "index" in data:
            idx = data["index"]
            if 0 <= idx < len(list_attr):
                list_attr[idx] = data["item"]
                return {"operation": "update", "index": idx, "success": True}
            return {"operation": "update", "error": "index out of range"}

        elif operation == "extend" and "items" in data:
            list_attr.extend(data["items"])
            return {
                "operation": "extend",
                "count": len(data["items"]),
                "success": True,
            }

        elif operation == "delete" and "index" in data:
            idx = data["index"]
            if 0 <= idx < len(list_attr):
                del list_attr[idx]
                return {"operation": "delete", "index": idx, "success": True}
            return {"operation": "delete", "error": "index out of range"}

        elif operation == "pop":
            idx = data.get("index", -1)
            if len(list_attr) > 0:
                if idx == -1:
                    idx = len(list_attr) - 1
                if 0 <= idx < len(list_attr):
                    list_attr.pop(idx)
                    return {"operation": "pop", "index": idx, "success": True}
            return {"operation": "pop", "error": "index out of range or empty list"}

        elif operation == "clear":
            list_attr.clear()
            return {"operation": "clear", "success": True}

        elif operation == "delete_all":
            list_attr.delete()
            return {"operation": "delete_all", "success": True}

        elif operation == "metadata":
            # Metadata-only change, no storage action needed
            return {"operation": "metadata", "ignored": True}

        elif operation == "remove" and "item" in data:
            # Remove by value - find and delete first matching item
            item_to_remove = data["item"]
            for i, existing in enumerate(list_attr):
                if existing == item_to_remove:
                    del list_attr[i]
                    return {"operation": "remove", "index": i, "success": True}
            return {"operation": "remove", "error": "item not found"}

        return {"operation": operation, "error": "unknown operation"}

    def apply_resync_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply resync data, replacing only the properties included in the data.

        Unlike a full delete-and-replace, this method only replaces the specific
        properties provided, preserving any other synced data from other
        subscriptions. This is important when multiple subscriptions exist to
        the same peer - a resync on one subscription should not destroy data
        from other subscriptions.

        SECURITY: Sanitizes untrusted data from remote peer before storage.

        Args:
            data: Resync data from callback (only these properties are replaced)

        Returns:
            Dict of {property_name: operation_result}
        """
        from datetime import datetime

        from .db.utils import sanitize_json_data

        # Sanitize untrusted resync data from remote peer
        data = sanitize_json_data(data, log_source=f"peer:{self._peer_id}:resync")

        results: dict[str, Any] = {}

        # NOTE: We do NOT call delete_all() here.
        # Each property is replaced individually, preserving unrelated properties.
        # For lists, set_list() already clears before extending.
        # For scalars, set_value() overwrites the existing value.

        # Apply new data
        for key, value in data.items():
            try:
                # Check for flag-based list format (preferred)
                if isinstance(value, dict) and value.get("_list") is True:
                    # Only process if items key is present to avoid treating
                    # metadata-only dicts as empty lists (which causes data loss)
                    if "items" in value:
                        items = value.get("items", [])

                        # Create sync metadata
                        metadata = {
                            "source_actor": self._peer_id,
                            "source_property": key,
                            "synced_at": datetime.now(UTC).isoformat(),
                            "item_count": len(items),
                        }

                        self.set_list(key, items, metadata=metadata)
                        results[key] = {
                            "operation": "resync",
                            "items": len(items),
                            "success": True,
                        }
                    else:
                        # List metadata without items - skip to avoid data loss
                        logger.warning(
                            f"Skipping list '{key}' in resync: metadata without items "
                            f"(transformation may have failed)"
                        )
                        results[key] = {
                            "operation": "skip",
                            "reason": "metadata_without_items",
                            "success": False,
                        }
                # Keep "list:" prefix detection for backward compatibility
                elif key.startswith("list:") and isinstance(value, list):
                    # Full list replacement
                    list_name = key[5:]

                    # Create sync metadata
                    metadata = {
                        "source_actor": self._peer_id,
                        "source_property": list_name,
                        "synced_at": datetime.now(UTC).isoformat(),
                        "item_count": len(value),
                    }

                    self.set_list(list_name, value, metadata=metadata)
                    results[list_name] = {
                        "operation": "resync",
                        "items": len(value),
                        "success": True,
                    }
                elif isinstance(value, dict):
                    self.set_value(key, value)
                    results[key] = {"operation": "resync", "success": True}
                else:
                    self.set_value(key, {"value": value})
                    results[key] = {"operation": "resync", "success": True}
            except Exception as e:
                logger.error(f"Error applying resync data for {key}: {e}")
                results[key] = {"error": str(e)}

        return results

    def apply_permission_data(self, permissions: dict[str, Any]) -> dict[str, Any]:
        """Apply permission update from peer.

        Stores what the REMOTE peer has granted US access to.
        Uses PeerPermissionStore in _peer_permissions bucket.

        This is typically called when receiving a permission callback from a peer.

        Args:
            permissions: Permission grant data {
                "properties": {"patterns": [...], "operations": [...],
                               "excluded_patterns": [...]},
                "methods": {"allowed": [...], "denied": [...]},
                "actions": {"allowed": [...], "denied": [...]},
                "tools": {"allowed": [...], "denied": [...]},
                "resources": {"allowed": [...], "denied": [...]},
                "prompts": {"allowed": [...]}
            }

        Returns:
            Result dict with success status
        """
        from datetime import UTC, datetime

        from .peer_permissions import (
            PeerPermissions,
            get_peer_permission_store,
            normalize_property_permission,
        )

        try:
            actor_id = self._actor.id
            if actor_id is None:
                logger.error("Cannot apply permission data: actor has no ID")
                return {
                    "operation": "permission_update",
                    "success": False,
                    "error": "Actor has no ID",
                }

            store = get_peer_permission_store(self._actor.config)

            peer_perms = PeerPermissions(
                actor_id=actor_id,
                peer_id=self._peer_id,
                properties=normalize_property_permission(permissions.get("properties")),
                methods=permissions.get("methods"),
                actions=permissions.get("actions"),
                tools=permissions.get("tools"),
                resources=permissions.get("resources"),
                prompts=permissions.get("prompts"),
                fetched_at=datetime.now(UTC).isoformat(),
            )

            success = store.store_permissions(peer_perms)
            return {"operation": "permission_update", "success": success}

        except Exception as e:
            logger.error(f"Error applying permission data from {self._peer_id}: {e}")
            return {"operation": "permission_update", "success": False, "error": str(e)}
