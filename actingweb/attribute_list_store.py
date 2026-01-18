"""
AttributeListStore - explicit interface for managing list attributes within buckets.

Provides a convenient interface for accessing ListAttribute instances
within a specific bucket, similar to PropertyListStore but for attributes.
"""

import logging
from typing import Any

from .attribute_list import ListAttribute

logger = logging.getLogger(__name__)


class AttributeListStore:
    """
    Explicit interface for managing list attributes within a bucket.

    Unlike PropertyListStore (which is per-actor), this is per-actor-per-bucket.
    """

    def __init__(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        config: Any | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._bucket = bucket
        self._config = config
        self._list_cache: dict[str, ListAttribute] = {}
        self.__initialised = True

    def exists(self, name: str) -> bool:
        """Check if a list attribute exists without creating it."""
        try:
            if self._config and self._actor_id and self._bucket:
                from .attribute import Attributes

                db = Attributes(
                    actor_id=self._actor_id, bucket=self._bucket, config=self._config
                )
                meta = db.get_attr(name=f"list:{name}:meta")
                return meta is not None
        except Exception:
            pass
        return False

    def list_all(self) -> list[str]:
        """List all existing attribute list names in this bucket."""
        list_names = []
        try:
            if self._config and self._actor_id and self._bucket:
                from .attribute import Attributes

                db = Attributes(
                    actor_id=self._actor_id, bucket=self._bucket, config=self._config
                )
                all_attrs = db.get_bucket() or {}
                for attr_name in all_attrs.keys():
                    if attr_name.startswith("list:") and attr_name.endswith(":meta"):
                        # Extract list name: "list:name:meta" -> "name"
                        # Split on ':' and get the middle part(s)
                        parts = attr_name.split(":")
                        if len(parts) >= 3:
                            # Join all parts between "list" and "meta"
                            list_name = ":".join(parts[1:-1])
                            list_names.append(list_name)
        except Exception as e:
            logger.error(f"Error in list_all(): {e}")
        return list_names

    def __getattr__(self, k: str) -> ListAttribute:
        """Return an ListAttribute for the requested list name."""
        if k.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{k}'"
            )

        # Validate actor_id and bucket are not None before creating ListAttribute
        if self._actor_id is None:
            raise RuntimeError("Cannot create ListAttribute without a valid actor_id")

        if self._bucket is None:
            raise RuntimeError("Cannot create ListAttribute without a valid bucket")

        # Check cache first
        if k in self._list_cache:
            return self._list_cache[k]

        # Create and cache the ListAttribute instance
        list_prop = ListAttribute(self._actor_id, self._bucket, k, self._config)
        self._list_cache[k] = list_prop
        return list_prop
