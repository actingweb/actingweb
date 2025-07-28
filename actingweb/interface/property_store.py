"""
Simplified property store interface for ActingWeb actors.
"""

from typing import Any, Dict, Iterator, Tuple
from ..property import PropertyStore as CorePropertyStore


class PropertyStore:
    """
    Clean interface for actor property management.

    Provides dictionary-like access to actor properties with type safety
    and convenience methods.

    Example usage:
        actor.properties.email = "user@example.com"
        actor.properties["config"] = {"theme": "dark"}

        if "email" in actor.properties:
            print(actor.properties.email)

        for key, value in actor.properties.items():
            print(f"{key}: {value}")
    """

    def __init__(self, core_store: CorePropertyStore):
        self._core_store = core_store

    def __getitem__(self, key: str) -> Any:
        """Get property value by key."""
        return self._core_store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set property value by key."""
        self._core_store[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete property by key."""
        self._core_store[key] = None

    def __contains__(self, key: str) -> bool:
        """Check if property exists."""
        try:
            return self._core_store[key] is not None
        except (KeyError, AttributeError):
            return False

    def __iter__(self) -> Iterator[str]:
        """Iterate over property keys."""
        # Get all properties from the core store
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
        except (KeyError, AttributeError):
            raise AttributeError(f"Property '{key}' not found")

    def __setattr__(self, key: str, value: Any) -> None:
        """Set property value as attribute."""
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            if hasattr(self, "_core_store") and self._core_store is not None:
                self._core_store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get property value with default."""
        try:
            value = self._core_store[key]
            return value if value is not None else default
        except (KeyError, AttributeError):
            return default

    def set(self, key: str, value: Any) -> None:
        """Set property value."""
        self._core_store[key] = value

    def delete(self, key: str) -> bool:
        """Delete property and return True if it existed."""
        try:
            if key in self:
                self._core_store[key] = None
                return True
            return False
        except (KeyError, AttributeError):
            return False

    def keys(self) -> Iterator[str]:
        """Get all property keys."""
        return iter(self)

    def values(self) -> Iterator[Any]:
        """Get all property values."""
        for key in self:
            yield self[key]

    def items(self) -> Iterator[Tuple[str, Any]]:
        """Get all property key-value pairs."""
        for key in self:
            yield (key, self[key])

    def update(self, other: Dict[str, Any]) -> None:
        """Update properties from dictionary."""
        for key, value in other.items():
            self[key] = value

    def clear(self) -> None:
        """Clear all properties."""
        for key in list(self.keys()):
            del self[key]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {key: value for key, value in self.items()}

    @property
    def core_store(self) -> CorePropertyStore:
        """Access underlying core property store."""
        return self._core_store
