"""
Simplified property store interface for ActingWeb actors.
"""

import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Optional

from ..property import PropertyStore as CorePropertyStore
from ..property_list import ListItemHandle

if TYPE_CHECKING:
    from ..actor import Actor as CoreActor
    from ..config import Config
    from .hooks import HookRegistry

logger = logging.getLogger(__name__)


class PropertyStore:
    """
    Clean interface for actor property management.

    Provides dictionary-like access to actor properties with automatic
    subscription notifications and hook execution.

    Example usage:
        actor.properties.email = "user@example.com"
        actor.properties["config"] = {"theme": "dark"}

        if "email" in actor.properties:
            print(actor.properties.email)

        for key, value in actor.properties.items():
            print(f"{key}: {value}")
    """

    def __init__(
        self,
        core_store: CorePropertyStore,
        actor: Optional["CoreActor"] = None,
        hooks: Optional["HookRegistry"] = None,
        config: Optional["Config"] = None,
    ):
        self._core_store = core_store
        self._actor = actor
        self._hooks = hooks
        self._config = config

    def _execute_property_hook(
        self, key: str, operation: str, value: Any, path: list[str]
    ) -> Any:
        """Execute property hook and return transformed value (or original if no hook)."""
        if not self._hooks or not self._actor:
            return value

        try:
            from .actor_interface import ActorInterface

            # Create ActorInterface wrapper for hook execution
            actor_interface = ActorInterface(self._actor)

            # Execute hook - returns transformed value or None if rejected
            result = self._hooks.execute_property_hooks(
                key, operation, actor_interface, value, path
            )
            return result if result is not None else value
        except Exception as e:
            logger.warning(f"Error executing property hook for {key}: {e}")
            return value

    def _register_diff(self, key: str, value: Any, resource: str = "") -> None:
        """Register a diff for subscription notifications."""
        if not self._actor:
            return

        try:
            blob = json.dumps(value) if value is not None else ""
            self._actor.register_diffs(
                target="properties",
                subtarget=key,
                resource=resource or None,
                blob=blob,
            )
        except Exception as e:
            logger.warning(f"Error registering diff for {key}: {e}")

    def __getitem__(self, key: str) -> Any:
        """Get property value by key."""
        return self._core_store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set property value by key with hook execution and diff registration."""
        # Execute pre-store hook
        transformed = self._execute_property_hook(key, "put", value, [key])

        # Store the value
        self._core_store[key] = transformed

        # Register diff for subscribers
        self._register_diff(key, transformed)

    def __delitem__(self, key: str) -> None:
        """Delete property by key with diff registration."""
        self._core_store[key] = None
        self._register_diff(key, "")

    def __contains__(self, key: str) -> bool:
        """Check if property exists."""
        try:
            return self._core_store[key] is not None
        except (KeyError, AttributeError):
            return False

    def __iter__(self) -> Iterator[str]:
        """Iterate over property keys."""
        try:
            if hasattr(self._core_store, "get_all"):
                all_props = self._core_store.get_all()
                if isinstance(all_props, dict):
                    return iter(all_props.keys())
            return iter([])
        except (AttributeError, TypeError):
            return iter([])

    def __getattr__(self, key: str) -> Any:
        """Get property value as attribute."""
        try:
            return self._core_store[key]
        except (KeyError, AttributeError) as err:
            raise AttributeError(f"Property '{key}' not found") from err

    def __setattr__(self, key: str, value: Any) -> None:
        """Set property value as attribute."""
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            if hasattr(self, "_core_store") and self._core_store is not None:
                self[key] = value  # Use __setitem__ for hooks/diffs

    def get(self, key: str, default: Any = None) -> Any:
        """Get property value with default."""
        try:
            value = self._core_store[key]
            return value if value is not None else default
        except (KeyError, AttributeError):
            return default

    def set(self, key: str, value: Any) -> None:
        """Set property value with hooks and diff registration."""
        self[key] = value  # Delegate to __setitem__

    def set_without_notification(self, key: str, value: Any) -> None:
        """Set property value without triggering subscription notifications.

        Use this for internal operations where notifications are not desired.
        """
        self._core_store[key] = value

    def delete(self, key: str) -> bool:
        """Delete property and return True if it existed."""
        try:
            if key in self:
                del self[key]  # Use __delitem__ for diff registration
                return True
            return False
        except (KeyError, AttributeError):
            return False

    def keys(self) -> Iterator[str]:
        """Get all property keys."""
        return iter(self)

    def values(self) -> Iterator[Any]:
        """Get all property values (single bulk read)."""
        yield from self.to_dict().values()

    def items(self) -> Iterator[tuple[str, Any]]:
        """Get all property key-value pairs (single bulk read)."""
        yield from self.to_dict().items()

    def update(self, other: dict[str, Any]) -> None:
        """Update properties from dictionary with hooks and diff registration."""
        for key, value in other.items():
            self[key] = value

    def clear(self) -> None:
        """Clear all properties with diff registration."""
        keys = list(self.keys())
        for key in keys:
            del self[key]

        # Also register a "clear all" diff
        if self._actor and keys:
            self._actor.register_diffs(target="properties", subtarget=None, blob="")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with one backend read.

        Reads everything via get_all() instead of re-fetching each key
        individually (the old path issued one GetItem per property right
        after having bulk-read them all).
        """
        try:
            if hasattr(self._core_store, "get_all"):
                all_props = self._core_store.get_all()
                if isinstance(all_props, dict):
                    return dict(all_props)
        except (AttributeError, TypeError):
            pass
        return {}

    @property
    def core_store(self) -> CorePropertyStore:
        """Access underlying core property store."""
        return self._core_store


class NotifyingListProperty:
    """Wrapper around ListProperty that registers diffs for subscription notifications.

    All list mutation operations will trigger register_diffs to notify subscribers
    of changes to the property list.
    """

    def __init__(
        self,
        list_prop: Any,  # ListProperty
        list_name: str,
        actor: Optional["CoreActor"] = None,
    ):
        self._list_prop = list_prop
        self._list_name = list_name
        self._actor = actor

    def _register_diff(
        self,
        operation: str = "",
        item: Any = None,
        index: int | None = None,
        items: list[Any] | None = None,
        old_item: Any = None,
    ) -> None:
        """Register a diff for the list property change.

        Args:
            operation: The operation type (append, update, delete, etc.)
            item: Single item data for append/update/insert operations
            index: Index for update/delete/insert operations
            items: Multiple items for extend operation
            old_item: pre-update value, for "update" diffs raised by
                ``update_where()``/``update_by_handle()`` -- lets a v2 peer
                match the diff to its own row by value (via
                ``old_item``) instead of by ``index``, which is only
                reliable under v1. See ``remote_storage._apply_list_operation``.
        """
        if not self._actor:
            return

        try:
            # Create a summary of the change
            # Note: For delete_all, we don't query length to avoid recreating metadata
            if operation == "delete_all":
                length = 0
            else:
                # get_metadata()["length"] rather than len(self._list_prop):
                # under v2 the latter is a whole-list range Query, doubled
                # on every notified append (once inside append() itself,
                # once here). The metadata length is exact under v1 and
                # advisory-but-bounded under v2 -- see ListProperty's class
                # docstring for the drift bound.
                length = self._list_prop.get_metadata()["length"]

            if operation == "append" and index is None:
                # Derived from the length just computed above, instead of
                # a second len(self._list_prop) call in append() below.
                index = length - 1

            diff_info: dict[str, Any] = {
                "list": self._list_name,
                "operation": operation,
                "length": length,
            }

            # Include item data for operations that add/modify items
            # This allows subscribers to receive the data directly without fetching
            if item is not None:
                diff_info["item"] = item
            if index is not None:
                diff_info["index"] = index
            if items is not None:
                diff_info["items"] = items
            if old_item is not None:
                diff_info["old_item"] = old_item

            # Note: diff_info already contains "list": self._list_name to identify
            # this as a list operation. We use clean subtarget without "list:" prefix
            # as that prefix is an internal storage detail, not exposed via HTTP/callbacks.
            self._actor.register_diffs(
                target="properties",
                subtarget=self._list_name,
                resource=None,
                blob=json.dumps(diff_info),
            )
        except Exception as e:
            logger.warning(f"Error registering diff for list {self._list_name}: {e}")

    # Read-only operations - delegate directly
    def __len__(self) -> int:
        return len(self._list_prop)

    def __getitem__(self, index: int) -> Any:
        return self._list_prop[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._list_prop)

    def get_description(self) -> str:
        return self._list_prop.get_description()

    def get_explanation(self) -> str:
        return self._list_prop.get_explanation()

    def get_metadata(self) -> dict[str, Any]:
        """List metadata -- see ListProperty.get_metadata(). Under v2,
        ``length`` is the advisory ``count_hint``, not a counted value."""
        return self._list_prop.get_metadata()

    def to_list(self, consistent: bool = True) -> list[Any]:
        return self._list_prop.to_list(consistent=consistent)

    def to_indexed_list(self, consistent: bool = True) -> list[tuple[int, Any]]:
        return self._list_prop.to_indexed_list(consistent=consistent)

    def prime_from_rows(self, rows: dict[str, Any]) -> None:
        self._list_prop.prime_from_rows(rows)

    def to_list_from_rows(self, rows: dict[str, Any]) -> list[Any]:
        return self._list_prop.to_list_from_rows(rows)

    def slice(self, start: int, end: int, consistent: bool = True) -> list[Any]:
        return self._list_prop.slice(start, end, consistent=consistent)

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        return self._list_prop.index(value, start, stop)

    def count(self, value: Any) -> int:
        return self._list_prop.count(value)

    def find(self, identity_key: str, value: Any, consistent: bool = True) -> Any:
        """Read-only -- see ListProperty.find()."""
        return self._list_prop.find(identity_key, value, consistent=consistent)

    def find_all(
        self, identity_key: str, value: Any, consistent: bool = True
    ) -> list[Any]:
        """Read-only -- see ListProperty.find_all()."""
        return self._list_prop.find_all(identity_key, value, consistent=consistent)

    def items_with_handles(self) -> list[tuple[ListItemHandle, Any]]:
        """Read-only -- see ListProperty.items_with_handles(). v2 only."""
        return self._list_prop.items_with_handles()

    def verify(self, identity_key: str | None = None) -> dict[str, Any]:
        """Read-only integrity check -- see ListProperty.verify(). No diff
        is registered; nothing changes.

        Pass ``identity_key`` if your items carry an identifying field:
        duplicate detection defaults to byte comparison, which stops
        finding a duplicate once either copy is edited."""
        return self._list_prop.verify(identity_key=identity_key)

    # Mutation operations - register diffs after completion
    def __setitem__(self, index: int, value: Any) -> None:
        self._list_prop[index] = value
        self._register_diff("update", item=value, index=index)

    def __delitem__(self, index: int) -> None:
        del self._list_prop[index]
        self._register_diff("delete", index=index)

    def set_description(self, description: str) -> None:
        self._list_prop.set_description(description)
        self._register_diff("metadata")

    def set_explanation(self, explanation: str) -> None:
        self._list_prop.set_explanation(explanation)
        self._register_diff("metadata")

    def append(self, item: Any) -> None:
        self._list_prop.append(item)
        # Include the item in the callback so subscribers can use it
        # directly. Index is length - 1 since append adds to the end --
        # left to _register_diff to derive from the length it already
        # computes, rather than a second len(self._list_prop) call here.
        self._register_diff("append", item=item)

    def extend(self, items: list[Any]) -> None:
        self._list_prop.extend(items)
        # Include all items in the callback
        self._register_diff("extend", items=items)

    def clear(self) -> None:
        self._list_prop.clear()
        self._register_diff("clear")

    def delete(self) -> None:
        self._list_prop.delete()
        self._register_diff("delete_all")

    def pop(self, index: int = -1) -> Any:
        result = self._list_prop.pop(index)
        self._register_diff("pop", index=index)
        return result

    def insert(self, index: int, item: Any) -> None:
        self._list_prop.insert(index, item)
        self._register_diff("insert", item=item, index=index)

    def remove(self, value: Any) -> None:
        self._list_prop.remove(value)
        self._register_diff("remove", item=value)

    def delete_by_handle(self, handle: ListItemHandle) -> bool:
        """Single-shot value-addressed delete -- see
        ListProperty.delete_by_handle(). Registers a "remove" diff (the
        closed operation vocabulary has no dedicated handle-delete entry)
        carrying the removed item's decoded value, only when the delete
        actually succeeded -- a ``False`` return means nothing changed."""
        item = self._list_prop._decode_item(handle.raw_value)
        removed = self._list_prop.delete_by_handle(handle)
        if removed:
            self._register_diff("remove", item=item)
        return removed

    def update_by_handle(self, handle: ListItemHandle, item: Any) -> bool:
        """Single-shot value-addressed update -- see
        ListProperty.update_by_handle(). Registers an "update" diff
        carrying both the new item and ``old_item`` (decoded from the
        handle), only when the update actually succeeded. No index --
        a handle is not positional."""
        old_item = self._list_prop._decode_item(handle.raw_value)
        updated = self._list_prop.update_by_handle(handle, item)
        if updated:
            self._register_diff("update", item=item, old_item=old_item)
        return updated

    def remove_where(self, identity_key: str, value: Any, *, first_only: bool = False) -> int:
        """See ListProperty.remove_where(). Registers one "remove" diff per
        item actually removed, carrying its decoded value -- the closed
        operation vocabulary has no dedicated bulk-remove entry, so a
        multi-match remove_where() looks to subscribers like several
        individual remove() calls.

        Matches are captured from a snapshot taken BEFORE the removal --
        one extra read, at this notifying layer only. ListProperty's own
        remove_where() stays at its documented query cost; it only
        returns a count, not the removed values, so this is the only way
        to give subscribers the item data other diffs already carry."""
        candidates = [
            item
            for _, item in self._list_prop.to_indexed_list()
            if isinstance(item, dict) and identity_key in item and item[identity_key] == value
        ]
        if first_only and candidates:
            candidates = candidates[:1]
        removed = self._list_prop.remove_where(identity_key, value, first_only=first_only)
        for item in candidates[:removed]:
            self._register_diff("remove", item=item)
        return removed

    def update_where(
        self, identity_key: str, value: Any, item: Any, *, first_only: bool = False
    ) -> int:
        """See ListProperty.update_where(). Registers one "update" diff per
        item actually updated, carrying the new value, ``old_item`` (the
        pre-update value), and its index in the pre-update snapshot --
        same snapshot-before-mutation approach as remove_where() above,
        for the same reason."""
        candidates = [
            (idx, existing)
            for idx, existing in self._list_prop.to_indexed_list()
            if isinstance(existing, dict)
            and identity_key in existing
            and existing[identity_key] == value
        ]
        if first_only and candidates:
            candidates = candidates[:1]
        updated = self._list_prop.update_where(identity_key, value, item, first_only=first_only)
        for idx, old_item in candidates[:updated]:
            self._register_diff("update", item=item, index=idx, old_item=old_item)
        return updated

    def compact(self) -> dict[str, Any]:
        """Repair holes/orphans -- see ListProperty.compact(). Registers a
        "metadata" diff (the closed operation vocabulary has no dedicated
        "compact" entry) so subscribers re-read the list rather than trust
        a positional diff for what is a storage-layer rewrite."""
        report = self._list_prop.compact()
        self._register_diff("metadata")
        return report

    def migrate_to_v2(self, allow_damaged: bool = False) -> dict[str, Any]:
        """Migrate this list from v1 to v2 storage -- see
        ListProperty.migrate_to_v2(), including what ``allow_damaged``
        gives up. Registers a "metadata" diff (same rationale as
        compact()) only when a migration actually happened."""
        report = self._list_prop.migrate_to_v2(allow_damaged=allow_damaged)
        if report.get("migrated"):
            self._register_diff("metadata")
        return report


class PropertyListStore:
    """Property list store wrapper that adds register_diffs for subscription notifications.

    Wraps the core PropertyListStore and returns NotifyingListProperty instances
    for all list accesses, ensuring that list mutations trigger subscription notifications.
    """

    def __init__(
        self,
        core_list_store: Any,  # PropertyListStore from property.py
        actor: Optional["CoreActor"] = None,
    ):
        self._core_store = core_list_store
        self._actor = actor

    def exists(self, name: str) -> bool:
        """Check if a list property exists."""
        return self._core_store.exists(name)

    def list_all(self) -> list[str]:
        """List all existing list property names."""
        return self._core_store.list_all()

    def list_all_with_rows(self) -> tuple[list[str], dict[str, str]]:
        """List all existing list property names, alongside the raw rows
        the names were derived from -- see
        `property.PropertyListStore.list_all_with_rows()`.

        The rows are an opaque, point-in-time snapshot of the actor's
        whole partition: feed them to a list's `prime_from_rows()` /
        `to_list_from_rows()`, never inspect or parse a row name.
        """
        return self._core_store.list_all_with_rows()

    def __getattr__(self, name: str) -> NotifyingListProperty:
        """Return a NotifyingListProperty for the requested list name."""
        if name.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

        # Get the underlying ListProperty from core store
        list_prop = getattr(self._core_store, name)
        # Wrap it with notification support
        return NotifyingListProperty(list_prop, name, self._actor)
