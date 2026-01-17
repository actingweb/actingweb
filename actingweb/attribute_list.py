"""
ListAttribute implementation for ActingWeb distributed list storage.

This module provides a list interface that stores list items as individual
attributes in buckets, bypassing the 400KB limit while maintaining API compatibility.
Attributes are internal-only storage (not exposed via REST API).
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
        """Get the attribute name for a list item at given index."""
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
            raise RuntimeError("No database connection available")

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
            raise RuntimeError("No database connection available")

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
        """Delete item at index and shift remaining items."""
        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self.config:
            raise RuntimeError("No database connection available")

        from .attribute import Attributes

        # Delete the item at index
        attr = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        attr.delete_attr(name=self._get_item_attribute_name(index))

        # Shift all items after index down by one
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
                        actor_id=self.actor_id, bucket=self.bucket, config=self.config
                    )
                    move_db.set_attr(
                        name=self._get_item_attribute_name(i - 1), data=item_data
                    )

                    # Delete the old position
                    delete_db = Attributes(
                        actor_id=self.actor_id, bucket=self.bucket, config=self.config
                    )
                    delete_db.delete_attr(name=self._get_item_attribute_name(i))

        # Update metadata length
        meta = self._load_metadata()
        meta["length"] = length - 1
        self._save_metadata(meta)

    def __iter__(self) -> ListAttributeIterator:
        """Return iterator for lazy loading."""
        return ListAttributeIterator(self)

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        if not self.config:
            raise RuntimeError("No database connection available")

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
            raise RuntimeError("No database connection available")

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
            raise RuntimeError("No database connection available")

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
        """Load entire list into memory."""
        length = len(self)
        result = []

        for i in range(length):
            try:
                result.append(self[i])
            except IndexError as e:
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
            except IndexError as e:
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

        if not self.config:
            raise RuntimeError("No database connection available")

        from .attribute import Attributes

        # Shift all items from index onwards up by one
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
                        actor_id=self.actor_id, bucket=self.bucket, config=self.config
                    )
                    set_db.set_attr(
                        name=self._get_item_attribute_name(i + 1), data=item_data
                    )

        # Insert the new item
        insert_db = Attributes(
            actor_id=self.actor_id, bucket=self.bucket, config=self.config
        )
        insert_db.set_attr(name=self._get_item_attribute_name(index), data=item)

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
