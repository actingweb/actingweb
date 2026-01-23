"""
Remote peer data storage.

Provides storage abstraction for data received from peer actors,
using internal attributes (not exposed via HTTP).
"""

import logging
import re
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
        db = self._get_attributes()
        attr = db.get_attr(name=name)
        # get_attr returns {"data": ..., "timestamp": ...} or None
        return attr.get("data") if attr else None

    def set_value(self, name: str, value: dict[str, Any]) -> None:
        """Set a scalar value."""
        db = self._get_attributes()
        db.set_attr(name=name, data=value)

    def delete_value(self, name: str) -> None:
        """Delete a scalar value."""
        db = self._get_attributes()
        db.delete_attr(name=name)

    # List operations

    def get_list(self, name: str) -> list[dict[str, Any]]:
        """Get a list by name."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        return list(list_attr)

    def set_list(
        self,
        name: str,
        items: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set a list (replaces all items)."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.clear()
        list_attr.extend(items)
        if metadata:
            list_attr.set_metadata(metadata)

    def delete_list(self, name: str) -> None:
        """Delete a list entirely."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.delete()

    def list_all_lists(self) -> list[str]:
        """List all stored lists for this peer."""
        store = self._get_list_store()
        return store.list_all()

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

        Args:
            data: Callback data dict from subscription callback

        Returns:
            Dict of {property_name: operation_result} for each processed property
        """
        results: dict[str, Any] = {}

        for key, value in data.items():
            try:
                if key.startswith("list:") and isinstance(value, dict):
                    # List operation
                    list_name = value.get("list", key[5:])
                    operation = value.get("operation", "unknown")
                    results[list_name] = self._apply_list_operation(
                        list_name, operation, value
                    )
                else:
                    # Scalar value
                    if isinstance(value, dict):
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
        """Apply full resync data, replacing all existing data.

        Args:
            data: Full state data from resync callback

        Returns:
            Dict of {property_name: operation_result}
        """
        results: dict[str, Any] = {}

        # Delete existing data first
        self.delete_all()

        # Apply all new data
        for key, value in data.items():
            try:
                if key.startswith("list:") and isinstance(value, list):
                    # Full list replacement
                    list_name = key[5:]
                    self.set_list(list_name, value)
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

        from .peer_permissions import PeerPermissions, get_peer_permission_store

        try:
            actor_id = self._actor.id
            if actor_id is None:
                logger.error("Cannot apply permission data: actor has no ID")
                return {"operation": "permission_update", "success": False, "error": "Actor has no ID"}

            store = get_peer_permission_store(self._actor.config)

            peer_perms = PeerPermissions(
                actor_id=actor_id,
                peer_id=self._peer_id,
                properties=permissions.get("properties"),
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
