"""
ListAttribute implementation for ActingWeb distributed list storage.

This module provides a list interface that stores list items as individual
attributes in buckets, bypassing the 400KB limit while maintaining API compatibility.
Attributes are internal-only storage (not exposed via REST API).

PERFORMANCE NOTE:
This implementation creates fresh Attributes instances for each database operation
to avoid handle conflicts. This mirrors the pattern used in ListProperty (property_list.py).
While this has performance implications for large operations (O(n) DB instances for shifting),
it ensures thread safety and avoids state management issues with the underlying
database connection objects.

For optimal performance:
- Avoid frequent insert()/delete() operations at the beginning of large lists (O(n) cost)
- Use append() for adding items (O(1) cost)
- Batch operations via extend() when possible
- Consider alternative data structures if you need frequent insertions at arbitrary positions
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ListAttributeIterator:
    """
    Lazy-loading iterator for ListAttribute.

    Loads list items on-demand to minimize database queries and memory usage.
    """

    def __init__(self, list_prop: "ListAttribute") -> None:
        self.list_prop = list_prop
        self.current_index = 0

    def __iter__(self) -> "ListAttributeIterator":
        return self

    def __next__(self) -> Any:
        if self.current_index >= len(self.list_prop):
            raise StopIteration

        item = self.list_prop[self.current_index]
        self.current_index += 1
        return item


class ListAttribute:
    """
    Distributed list storage implementation using attributes within a bucket.

    Stores list items as individual attributes with pattern: list:{name}:{index}
    Maintains metadata in list:{name}:meta attribute for efficient operations.
    """

    def __init__(self, actor_id: str, bucket: str, name: str, config: Any) -> None:
        self.actor_id = actor_id
        self.bucket = bucket
        self.name = name
        self.config = config
        self._meta_cache: dict[str, Any] | None = None

    def _get_meta_attribute_name(self) -> str:
        """Get the metadata attribute name."""
        return f"list:{self.name}:meta"

    def _get_item_attribute_name(self, index: int) -> str:
        """
        Get the attribute name for a list item at given index.

        Args:
            index: Non-negative integer index

        Returns:
            Attribute name in format: list:{name}:{index}

        Raises:
            ValueError: If index is negative
        """
        if index < 0:
            raise ValueError(
                f"Attribute index must be non-negative, got {index}. "
                "Caller should resolve negative indices before calling this method."
            )
        return f"list:{self.name}:{index}"

    def _load_metadata(self) -> dict[str, Any]:
        """Load metadata from database, with caching."""
        if self._meta_cache is not None:
            return self._meta_cache

        if not self.config:
            return self._create_default_metadata()

        # Use fresh DB instance to avoid handle conflicts
        from .attribute import Attributes

        meta_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        meta_attr = meta_db.get_attr(name=self._get_meta_attribute_name())

        if meta_attr is None:
            # No metadata exists, create default
            # Don't save yet - let the caller save via set_description/set_explanation
            meta = self._create_default_metadata()
            self._meta_cache = (
                meta  # Cache it for subsequent calls within this instance
            )
            return meta

        # Extract the data from the attribute structure
        meta_data = meta_attr.get("data") if isinstance(meta_attr, dict) else None

        if meta_data is None or not isinstance(meta_data, dict):
            # Invalid metadata format, return default
            meta = self._create_default_metadata()
            self._save_metadata(meta)
            return meta

        self._meta_cache = meta_data
        return self._meta_cache

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

        if self.config:
            from .attribute import Attributes

            meta_attribute_name = self._get_meta_attribute_name()
            # Use fresh DB instance to avoid handle conflicts
            meta_db = Attributes(
                actor_id=self.actor_id, bucket=self.bucket, config=self.config
            )
            # Store the metadata directly as data (attributes support native JSON)
            meta_db.set_attr(name=meta_attribute_name, data=meta)

        self._meta_cache = meta

    def _invalidate_cache(self) -> None:
        """Invalidate the metadata cache."""
        self._meta_cache = None

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

        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        from .attribute import Attributes

        item_attribute_name = self._get_item_attribute_name(index)
        # Use fresh DB instance to avoid handle conflicts
        item_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        item_attr = item_db.get_attr(name=item_attribute_name)

        if item_attr is None:
            raise IndexError(f"List item at index {index} not found in database")

        # Extract the data from the attribute structure
        item_data = item_attr.get("data") if isinstance(item_attr, dict) else None

        if item_data is None:
            raise IndexError(f"List item at index {index} not found in database")

        return item_data

    def __setitem__(self, index: int, value: Any) -> None:
        """Set item at index."""
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        from .attribute import Attributes

        # Use fresh DB instance to avoid handle conflicts
        item_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        # Store the value directly as data (attributes support native JSON)
        item_db.set_attr(name=self._get_item_attribute_name(index), data=value)

        # Update metadata timestamp
        meta = self._load_metadata()
        self._save_metadata(meta)

    def __delitem__(self, index: int) -> None:
        """
        Delete item at index and shift remaining items.

        WARNING: This operation performs multiple database writes without
        transactional guarantees. If a failure occurs during item shifting,
        the list may be left in an inconsistent state with duplicate items
        or gaps. The metadata length will only be updated if all shifts succeed.

        Performance: O(n) where n = (length - index). Avoid frequent deletions
        from the beginning of large lists.

        Raises:
            IndexError: If index is out of range
            RuntimeError: If config is not set
            Exception: If database operations fail during shifting
        """
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        from .attribute import Attributes

        # Delete the item at index
        try:
            attr = Attributes(
                actor_id=self.actor_id, bucket=self.bucket, config=self.config
            )
            attr.delete_attr(name=self._get_item_attribute_name(index))
        except Exception as e:
            logger.error(
                f"Failed to delete item at index {index} for list '{self.name}': {e}"
            )
            raise RuntimeError(f"Failed to delete item at index {index}: {e}") from e

        # Shift all items after index down by one
        shifted_count = 0
        failed_index = None
        try:
            for i in range(index + 1, length):
                # Use fresh DB instance to avoid handle conflicts
                item_db = Attributes(
                    actor_id=self.actor_id, bucket=self.bucket, config=self.config
                )
                item_attr = item_db.get_attr(name=self._get_item_attribute_name(i))

                if item_attr is not None:
                    # Extract data from the attribute structure
                    item_data = (
                        item_attr.get("data") if isinstance(item_attr, dict) else None
                    )

                    if item_data is not None:
                        # Move item from position i to position i-1
                        move_db = Attributes(
                            actor_id=self.actor_id,
                            bucket=self.bucket,
                            config=self.config,
                        )
                        move_db.set_attr(
                            name=self._get_item_attribute_name(i - 1), data=item_data
                        )

                        # Delete the old position
                        delete_db = Attributes(
                            actor_id=self.actor_id,
                            bucket=self.bucket,
                            config=self.config,
                        )
                        delete_db.delete_attr(name=self._get_item_attribute_name(i))
                        shifted_count += 1
                failed_index = i
        except Exception as e:
            logger.error(
                f"Partial failure in __delitem__ for list '{self.name}': "
                f"Shifted {shifted_count} items before failure at index {failed_index}: {e}"
            )
            raise RuntimeError(
                f"List may be in inconsistent state: Successfully shifted {shifted_count} "
                f"items but failed at index {failed_index}. Manual recovery may be required."
            ) from e

        # Update metadata length (only if we got here without exceptions)
        try:
            meta = self._load_metadata()
            meta["length"] = length - 1
            self._save_metadata(meta)
        except Exception as e:
            logger.error(
                f"Failed to update metadata after successful deletion in list '{self.name}': {e}"
            )
            raise RuntimeError(
                f"Items were shifted successfully but metadata update failed. "
                f"List length in metadata is now incorrect (still {length} instead of {length - 1})."
            ) from e

    def __iter__(self) -> ListAttributeIterator:
        """Return iterator for lazy loading."""
        return ListAttributeIterator(self)

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        length = len(self)

        from .attribute import Attributes

        # Store the new item - use fresh DB instance to avoid handle conflicts
        item_attribute_name = self._get_item_attribute_name(length)
        item_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        # Store the item directly as data (attributes support native JSON)
        item_db.set_attr(name=item_attribute_name, data=item)
        logger.debug(
            f"append(): Stored item at '{item_attribute_name}' with value: {item}"
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
        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        length = len(self)

        from .attribute import Attributes

        # Delete all item attributes
        for i in range(length):
            item_db = Attributes(
                actor_id=self.actor_id, bucket=self.bucket, config=self.config
            )
            item_db.delete_attr(name=self._get_item_attribute_name(i))

        # Reset metadata
        meta = self._create_default_metadata()
        self._save_metadata(meta)

    def delete(self) -> None:
        """Delete the entire list including metadata."""
        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        length = len(self)

        from .attribute import Attributes

        # Delete all item attributes
        for i in range(length):
            item_db = Attributes(
                actor_id=self.actor_id, bucket=self.bucket, config=self.config
            )
            item_db.delete_attr(name=self._get_item_attribute_name(i))

        # Delete metadata
        meta_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        meta_db.delete_attr(name=self._get_meta_attribute_name())

        # Clear cache
        self._meta_cache = None

    def to_list(self) -> list[Any]:
        """
        Load entire list into memory.

        Raises:
            IndexError: If any items are missing from the list, which indicates
                data corruption or inconsistent metadata.

        Note: This method validates list integrity by ensuring all items from
        0 to length-1 exist. If you need partial data on corruption, use slice()
        with try/except for each index individually.
        """
        length = len(self)
        result = []

        for i in range(length):
            # Fail fast on missing items to detect data corruption
            result.append(self[i])

        return result

    def slice(self, start: int, end: int) -> list[Any]:
        """
        Load a range of items efficiently.

        Args:
            start: Starting index (inclusive)
            end: Ending index (exclusive)

        Returns:
            List of items from start to end (exclusive)

        Raises:
            IndexError: If any items in the range are missing, which indicates
                data corruption or inconsistent metadata.

        Note: This method validates data integrity by ensuring all requested
        items exist. Negative indices are supported.
        """
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
            # Fail fast on missing items to detect data corruption
            result.append(self[i])

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
        """
        Insert item at given index.

        WARNING: This operation performs multiple database writes without
        transactional guarantees. If a failure occurs during item shifting,
        the list may be left in an inconsistent state with duplicate items.
        The metadata length will only be updated if all operations succeed.

        Performance: O(n) where n = (length - index). Avoid frequent insertions
        at the beginning of large lists.

        Args:
            index: Position to insert at (negative indices supported)
            item: Item to insert

        Raises:
            RuntimeError: If config is not set or database operations fail
        """
        length = len(self)

        if index < 0:
            index = max(0, length + index)
        if index > length:
            index = length

        if not self.config:
            raise RuntimeError(
                "Cannot perform operation: config is None (database not initialized)"
            )

        from .attribute import Attributes

        # Shift all items from index onwards up by one (in reverse order)
        shifted_count = 0
        failed_index = None
        try:
            for i in range(length - 1, index - 1, -1):
                get_db = Attributes(
                    actor_id=self.actor_id, bucket=self.bucket, config=self.config
                )
                item_attr = get_db.get_attr(name=self._get_item_attribute_name(i))

                if item_attr is not None:
                    # Extract data from the attribute structure
                    item_data = (
                        item_attr.get("data") if isinstance(item_attr, dict) else None
                    )

                    if item_data is not None:
                        set_db = Attributes(
                            actor_id=self.actor_id,
                            bucket=self.bucket,
                            config=self.config,
                        )
                        set_db.set_attr(
                            name=self._get_item_attribute_name(i + 1), data=item_data
                        )
                        shifted_count += 1
                failed_index = i
        except Exception as e:
            logger.error(
                f"Partial failure in insert() for list '{self.name}': "
                f"Shifted {shifted_count} items before failure at index {failed_index}: {e}"
            )
            raise RuntimeError(
                f"List may be in inconsistent state: Successfully shifted {shifted_count} "
                f"items but failed at index {failed_index}. Manual recovery may be required."
            ) from e

        # Insert the new item
        try:
            insert_db = Attributes(
                actor_id=self.actor_id, bucket=self.bucket, config=self.config
            )
            insert_db.set_attr(name=self._get_item_attribute_name(index), data=item)
        except Exception as e:
            logger.error(
                f"Failed to insert item at index {index} in list '{self.name}' "
                f"after shifting {shifted_count} items: {e}"
            )
            raise RuntimeError(
                f"List is in inconsistent state: Items were shifted but new item "
                f"insertion failed. There is now a gap at index {index}."
            ) from e

        # Update metadata (only if we got here without exceptions)
        try:
            meta = self._load_metadata()
            meta["length"] = length + 1
            self._save_metadata(meta)
        except Exception as e:
            logger.error(
                f"Failed to update metadata after successful insertion in list '{self.name}': {e}"
            )
            raise RuntimeError(
                f"Item was inserted successfully but metadata update failed. "
                f"List length in metadata is now incorrect (still {length} instead of {length + 1})."
            ) from e

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
