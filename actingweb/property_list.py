"""
ListProperty implementation for ActingWeb distributed list storage.

This module provides a list interface that stores list items as individual
properties in DynamoDB, bypassing the 400KB limit while maintaining API compatibility.
"""

import json
import logging
from datetime import datetime
from typing import Any

from actingweb.db import get_property

logger = logging.getLogger(__name__)


class ListPropertyIterator:
    """
    Lazy-loading iterator for ListProperty.

    Loads list items on-demand to minimize database queries and memory usage.
    """

    def __init__(self, list_prop: "ListProperty") -> None:
        self.list_prop = list_prop
        self.current_index = 0

    def __iter__(self) -> "ListPropertyIterator":
        return self

    def __next__(self) -> Any:
        if self.current_index >= len(self.list_prop):
            raise StopIteration

        item = self.list_prop[self.current_index]
        self.current_index += 1
        return item


class ListProperty:
    """
    Distributed list storage implementation for ActingWeb properties.

    Stores list items as individual properties with pattern: {name}-{index}
    Maintains metadata in {name}-meta property for efficient operations.
    """

    def __init__(self, actor_id: str, name: str, config: Any) -> None:
        self.actor_id = actor_id
        self.name = name
        self.config = config
        self._meta_cache: dict[str, Any] | None = None
        self._db = get_property(self.config) if self.config else None

    def _get_meta_property_name(self) -> str:
        """Get the metadata property name."""
        return f"list:{self.name}-meta"

    def _get_item_property_name(self, index: int) -> str:
        """Get the property name for a list item at given index."""
        return f"list:{self.name}-{index}"

    def _load_metadata(self) -> dict[str, Any]:
        """Load metadata from database, with caching."""
        if self._meta_cache is not None:
            return self._meta_cache

        if not self._db:
            return self._create_default_metadata()

        # Use fresh DB instance to avoid handle conflicts
        meta_db = get_property(self.config)
        meta_str = meta_db.get(
            actor_id=self.actor_id, name=self._get_meta_property_name()
        )

        if meta_str is None:
            # No metadata exists - this is a new list
            # Check for property collision - error if property exists
            prop_db = get_property(self.config)
            existing_prop = prop_db.get(actor_id=self.actor_id, name=self.name)
            if existing_prop is not None:
                raise ValueError(
                    f"Cannot create list '{self.name}': a property with this name already exists. "
                    f"Delete the property first or use a different name."
                )

            # No metadata exists, create default
            # Don't save yet - let the caller save via set_description/set_explanation
            meta = self._create_default_metadata()
            self._meta_cache = (
                meta  # Cache it for subsequent calls within this instance
            )
            return meta

        try:
            parsed_meta = json.loads(meta_str)
            if isinstance(parsed_meta, dict):
                self._meta_cache = parsed_meta
                return self._meta_cache
            else:
                # Invalid metadata format, return default
                meta = self._create_default_metadata()
                self._save_metadata(meta)
                return meta
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse list metadata for {self.name}: {e}")
            # Return default metadata if parsing fails
            meta = self._create_default_metadata()
            self._save_metadata(meta)
            return meta

    def _create_default_metadata(self) -> dict[str, Any]:
        """Create default metadata structure."""
        now = datetime.now().isoformat()
        return {
            "length": 0,
            "created_at": now,
            "updated_at": now,
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }

    def _save_metadata(self, meta: dict[str, Any]) -> None:
        """Save metadata to database and update cache."""
        meta["updated_at"] = datetime.now().isoformat()

        if self._db:
            meta_property_name = self._get_meta_property_name()
            meta_json = json.dumps(meta)
            # Use fresh DB instance to avoid handle conflicts
            meta_db = get_property(self.config)
            if not meta_db.set(
                actor_id=self.actor_id, name=meta_property_name, value=meta_json
            ):
                raise RuntimeError(f"list metadata write failed for '{self.name}'")

        self._meta_cache = meta

    def _invalidate_cache(self) -> None:
        """Invalidate the metadata cache."""
        self._meta_cache = None

    def prime_from_rows(self, rows: dict[str, Any]) -> None:
        """Hydrate the metadata cache from a pre-fetched name->value mapping.

        `rows` is the result of a bulk fetch_all_including_lists() read.
        Priming avoids re-reading the `list:<name>-meta` row that the bulk
        read already returned. Ignores missing or unparsable metadata (the
        normal lazy path then applies).
        """
        meta_str = rows.get(self._get_meta_property_name())
        if meta_str is None:
            return
        try:
            parsed = json.loads(meta_str)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(parsed, dict):
            self._meta_cache = parsed

    def to_list_from_rows(self, rows: dict[str, Any]) -> list[Any]:
        """Like to_list(), but served from a pre-fetched name->value mapping.

        Falls back to a per-item database read for any row missing from the
        mapping. Item decoding matches __getitem__: JSON with a raw-string
        fallback.
        """
        length = len(self)
        result: list[Any] = []
        for i in range(length):
            item_str = rows.get(self._get_item_property_name(i))
            if item_str is None:
                try:
                    result.append(self[i])
                except (IndexError, json.JSONDecodeError) as e:
                    logger.error(f"Error loading list item {i}: {e}")
                continue
            try:
                result.append(json.loads(item_str))
            except (json.JSONDecodeError, TypeError):
                result.append(item_str)
        return result

    def get_description(self) -> str:
        """Get the description field for UI info about the list."""
        meta = self._load_metadata()
        description = meta.get("description", "")
        return str(description) if description is not None else ""

    def set_description(self, description: str) -> None:
        """Set the description field for UI info about the list."""
        meta = self._load_metadata()
        meta["description"] = description
        self._save_metadata(meta)

    def get_explanation(self) -> str:
        """Get the explanation field to be used for LLMs."""
        meta = self._load_metadata()
        explanation = meta.get("explanation", "")
        return str(explanation) if explanation is not None else ""

    def set_explanation(self, explanation: str) -> None:
        """Set the explanation field to be used for LLMs."""
        meta = self._load_metadata()
        meta["explanation"] = explanation
        self._save_metadata(meta)

    def get_metadata(self) -> dict[str, Any]:
        """
        Get list metadata as a read-only dictionary.

        Returns metadata including created_at, updated_at, version, item_type,
        chunk_size, and length. For description and explanation, use the
        dedicated get_description() and get_explanation() methods.

        Returns:
            Dictionary with metadata fields:
            - created_at: ISO timestamp when list was created
            - updated_at: ISO timestamp of last modification
            - version: Metadata schema version
            - item_type: Type of items stored (currently always "json")
            - chunk_size: Internal chunk size (currently always 1)
            - length: Number of items in the list

        Note: This returns a copy; modifications won't affect the stored metadata.
        Use set_description() and set_explanation() to update user-facing fields.
        """
        meta = self._load_metadata()
        return {
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "version": meta.get("version", ""),
            "item_type": meta.get("item_type", ""),
            "chunk_size": meta.get("chunk_size", 1),
            "length": meta.get("length", 0),
        }

    def __len__(self) -> int:
        """Get list length from metadata only (no item loading)."""
        meta = self._load_metadata()
        length = meta.get("length", 0)
        return int(length) if length is not None else 0

    def __getitem__(self, index: int) -> Any:
        """Get item by index, loading from database."""
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        item_property_name = self._get_item_property_name(index)
        # Use fresh DB instance to avoid handle conflicts
        item_db = get_property(self.config)
        item_str = item_db.get(actor_id=self.actor_id, name=item_property_name)

        if item_str is None:
            raise IndexError(f"List item at index {index} not found in database")

        try:
            return json.loads(item_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse list item at index {index}: {e}")
            return item_str  # Return raw string if JSON parsing fails

    def __setitem__(self, index: int, value: Any) -> None:
        """Set item at index."""
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        # Serialize the value
        try:
            value_str = json.dumps(value)
        except (TypeError, ValueError):
            value_str = str(value)

        # Use fresh DB instance to avoid handle conflicts
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=value_str,
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Update metadata timestamp
        meta = self._load_metadata()
        self._save_metadata(meta)

    def __delitem__(self, index: int) -> None:
        """Delete item at index and shift remaining items."""
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        # Delete the item at index
        prop = get_property(self.config)
        if not prop.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=None,  # This will delete the property
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Shift all items after index down by one
        for i in range(index + 1, length):
            # Use fresh DB instance to avoid handle conflicts
            item_db = get_property(self.config)
            item_value = item_db.get(
                actor_id=self.actor_id, name=self._get_item_property_name(i)
            )

            if item_value is not None:
                # Move item from position i to position i-1
                move_db = get_property(self.config)
                if not move_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i - 1),
                    value=item_value,
                ):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}'[{i - 1}]"
                    )

                # Delete the old position
                delete_db = get_property(self.config)
                if not delete_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i),
                    value=None,
                ):
                    raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        # Update metadata length
        meta = self._load_metadata()
        meta["length"] = length - 1
        self._save_metadata(meta)

    def __iter__(self) -> ListPropertyIterator:
        """Return iterator for lazy loading."""
        return ListPropertyIterator(self)

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        if not self._db:
            raise RuntimeError("No database connection available")

        length = len(self)

        # Serialize the item
        try:
            item_str = json.dumps(item)
        except (TypeError, ValueError):
            item_str = str(item)

        # Store the new item - use fresh DB instance to avoid handle conflicts
        item_property_name = self._get_item_property_name(length)
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id, name=item_property_name, value=item_str
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{length}]")
        logger.debug(
            f"append(): Stored item at '{item_property_name}' with value: {item_str}"
        )

        # Update metadata
        meta = self._load_metadata()
        meta["length"] = length + 1
        self._save_metadata(meta)

    def extend(self, items: list[Any]) -> None:
        """Add multiple items to end of list."""
        for item in items:
            self.append(item)

    def clear(self) -> None:
        """Remove all items from list."""
        if not self._db:
            raise RuntimeError("No database connection available")

        length = len(self)

        # Delete all item properties
        for i in range(length):
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        # Reset metadata
        meta = self._create_default_metadata()
        self._save_metadata(meta)

    def delete(self) -> None:
        """Delete the entire list including metadata."""
        if not self._db:
            raise RuntimeError("No database connection available")

        length = len(self)

        # Delete all item properties
        for i in range(length):
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        # Delete metadata
        meta_db = get_property(self.config)
        if not meta_db.set(
            actor_id=self.actor_id, name=self._get_meta_property_name(), value=None
        ):
            raise RuntimeError(f"list metadata write failed for '{self.name}'")

        # Clear cache
        self._meta_cache = None

    def to_list(self) -> list[Any]:
        """Load entire list into memory."""
        length = len(self)
        result = []

        for i in range(length):
            try:
                result.append(self[i])
            except (IndexError, json.JSONDecodeError) as e:
                logger.error(f"Error loading list item {i}: {e}")
                continue

        return result

    def slice(self, start: int, end: int) -> list[Any]:
        """Load a range of items efficiently."""
        length = len(self)

        # Handle negative indices
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = max(0, length + end)

        # Clamp to valid range
        start = max(0, min(start, length))
        end = max(start, min(end, length))

        result = []
        for i in range(start, end):
            try:
                result.append(self[i])
            except (IndexError, json.JSONDecodeError) as e:
                logger.error(f"Error loading list item {i}: {e}")
                continue

        return result

    def pop(self, index: int = -1) -> Any:
        """Remove and return item at index (default last)."""
        if len(self) == 0:
            raise IndexError("pop from empty list")

        if index == -1:
            index = len(self) - 1

        item = self[index]
        del self[index]
        return item

    def insert(self, index: int, item: Any) -> None:
        """Insert item at given index."""
        length = len(self)

        if index < 0:
            index = max(0, length + index)
        if index > length:
            index = length

        if not self._db:
            raise RuntimeError("No database connection available")

        # Shift all items from index onwards up by one. Fresh DB instance
        # per call (like every other mutation method) — reusing self._db
        # across get()/set() calls for different item names left a stale
        # handle that, on DynamoDB, overwrote every shifted row with the
        # last-read value instead of its own.
        for i in range(length - 1, index - 1, -1):
            item_db = get_property(self.config)
            item_value = item_db.get(
                actor_id=self.actor_id, name=self._get_item_property_name(i)
            )

            if item_value is not None:
                move_db = get_property(self.config)
                if not move_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i + 1),
                    value=item_value,
                ):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}'[{i + 1}]"
                    )

        # Insert the new item
        try:
            item_str = json.dumps(item)
        except (TypeError, ValueError):
            item_str = str(item)

        insert_db = get_property(self.config)
        if not insert_db.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=item_str,
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Update metadata
        meta = self._load_metadata()
        meta["length"] = length + 1
        self._save_metadata(meta)

    def remove(self, value: Any) -> None:
        """Remove first occurrence of value."""
        for i, item in enumerate(self):
            if item == value:
                del self[i]
                return
        raise ValueError(f"{value} not in list")

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        """Return index of first occurrence of value."""
        length = len(self)
        if stop is None:
            stop = length

        for i in range(start, min(stop, length)):
            if self[i] == value:
                return i

        raise ValueError(f"{value} is not in list")

    def count(self, value: Any) -> int:
        """Return number of occurrences of value."""
        count = 0
        for item in self:
            if item == value:
                count += 1
        return count
