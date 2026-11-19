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

from .db.exceptions import AttributeKeyCollision, DbError
from .identifiers import first_control_character
from .list_core import (
    ListCorruptionError,
    ListItemTooLargeError,
    ListMetadataContentionError,
    ListNameTakenError,
    ListRankExhaustedError,
)

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Default pattern matches actingweb library's UUID v5 .hex format
DEFAULT_PEER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}\Z")

# More permissive pattern that accepts both formats
PERMISSIVE_PEER_ID_PATTERN = re.compile(
    r"^[a-f0-9]{32}\Z|^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z"
)


class ReplicaOutOfStep(Exception):
    """A list diff this replica cannot apply: the replica no longer holds
    what the publisher's list held before the change. The subscription's
    replica is rebuilt from a baseline (``SubscriptionManager.
    rebuild_subscription``)."""

    def __init__(self, list_name: str, why: str) -> None:
        super().__init__(f"list {list_name!r}: {why}")
        self.list_name = list_name
        self.why = why


# Creating list operations, which validate the list's name; deleting ones
# accept any stored name.
_CREATING_OPERATIONS = frozenset({"append", "insert", "extend"})


def _wraps_list(value: Any, name: str, *, baseline: bool = False) -> bool:
    """Whether ``value`` is a list's state keyed by the list's own name: a
    list diff for ``name``, or (``baseline``) the ``{"_list": true}`` form."""
    if not isinstance(value, dict) or set(value) != {name}:
        return False
    inner = value[name]
    return isinstance(inner, dict) and (
        (baseline and inner.get("_list") is True)
        or ("operation" in inner and inner.get("list") == name)
    )


class ReplicaApplyResult(dict[str, Any]):
    """What ``apply_callback_data``/``apply_resync_data`` did: a result per
    key, plus two attributes that are never keys (a key is a name the peer
    chose, so a property named ``out_of_step`` must not read as the mark):

    - ``out_of_step``: the first list diff the replica could not apply
      (``{"list", "operation", "why"}``), or None.
    - ``failed``: the names whose entry could not be stored (not refused
      names: those are the peer's own), for a baseline that must not count
      as a rebuild.
    - ``skipped``: nothing was stored because a subscription to the peer's
      whole ``properties`` target stores the same names (one subscription
      per name writes the replica).
    """

    def __init__(self) -> None:
        super().__init__()
        self.out_of_step: dict[str, Any] | None = None
        self.failed: list[str] = []
        self.skipped = False


# The longest DynamoDB sort key is 1,024 bytes: "{bucket}:list:{name}-#"
# plus a rank of up to 180 characters.
_SORT_KEY_BYTES = 1024
_LIST_KEY_OVERHEAD = len(":list:-#") + 180


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
        if not pat.fullmatch(peer_id):
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

    def get_list(self, name: str) -> list[Any]:
        """Get a list by name."""
        from .db.utils import sanitize_json_data

        list_attr = self._get_list_store().get(name)
        try:
            items = list_attr.to_list()
        except ListNameTakenError:
            # The replica holds a scalar of this name: there is no list.
            return []
        # Defense-in-depth: sanitize on read to catch surrogates that
        # survived storage (e.g., from JSON round-trip of \uD800 escapes)
        return sanitize_json_data(items, log_source=f"read:peer:{self._peer_id}")

    def set_list(
        self,
        name: str,
        items: list[Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Replace the list ``name`` with ``items`` (a baseline from the peer,
        sanitised). The name is validated first; then ``clear()`` (both
        layouts), every item encoded and size-checked, and ``extend()``. A baseline holding an item that cannot be stored
        deletes the list (and logs it), so the next diff does not find the
        stale one; a refused name raises ``ValueError``."""
        from .db.utils import sanitize_json_data

        why = self._invalid_list_name(name)
        if why is not None:
            logger.warning(
                "Refused list %r from peer %s: the name %s", name, self._peer_id, why
            )
            raise ValueError(f"list name {name!r} {why}")
        sanitized_items = sanitize_json_data(items, log_source=f"peer:{self._peer_id}")
        sanitized_metadata = (
            sanitize_json_data(metadata, log_source=f"peer:{self._peer_id}")
            if metadata
            else None
        )

        list_attr = self._get_list_store().get(name)
        if self.get_value(name) is not None:
            # A scalar of this name (a pre-4.0 publisher's REST list edit
            # arrived as one): the list replaces it.
            self.delete_value(name)
            list_attr = self._get_list_store().get(name)
        # Cleared first: clear() removes both layouts, so the size check
        # below is the new layout's (an item over the span threshold spans)
        # and a list stored in both layouts is repaired, not refused.
        list_attr.clear()
        try:
            for item in sanitized_items:
                list_attr.check_item_size(item)
        except (ListItemTooLargeError, ValueError) as e:
            logger.warning(
                "Deleting list %r of peer %s: its baseline holds an item that "
                "cannot be stored (%s)",
                name,
                self._peer_id,
                e,
            )
            list_attr.delete()
            raise
        if sanitized_items:
            list_attr.extend(sanitized_items)
        if sanitized_metadata:
            # ListAttribute only supports setting description and explanation
            if "description" in sanitized_metadata:
                list_attr.set_description(sanitized_metadata["description"])
            if "explanation" in sanitized_metadata:
                list_attr.set_explanation(sanitized_metadata["explanation"])

    def delete_list(self, name: str) -> None:
        """Delete a list entirely."""
        self._get_list_store().get(name).delete()

    def list_all_lists(self, *, strict: bool = False) -> list[str]:
        """List all stored lists for this peer (``strict``: a read fault
        raises ``DbError`` instead of answering ``[]``)."""
        store = self._get_list_store()
        return store.list_all(strict=True) if strict else store.list_all()

    def list_scalar_names(self) -> list[str]:
        """The names of the replica's scalars, read without their values and
        without the list rows: two keys-only range reads, either side of
        names starting ``list:``. A fault raises ``DbError``."""
        from .db import get_attribute

        db = get_attribute(self._actor.config)
        actor_id = self._actor.id or ""
        top = "\U0010ffff"
        below = db.get_attr_range(
            actor_id, self._bucket, "", "list9" + top, keys_only=True
        )
        above = db.get_attr_range(actor_id, self._bucket, "list;", top, keys_only=True)
        return sorted({*below, *above})

    def list_all_scalars(self) -> list[str]:
        """List all scalar property names for this peer.

        Returns:
            List of scalar property names (excludes list properties and their metadata)
        """
        db = self._get_attributes()
        all_attrs = db.get_bucket(strict=False) or {}

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
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Error reading list '{list_name}' for peer {self._peer_id}: {e}"
                    )
                    continue
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error listing list properties for peer {self._peer_id}: {e}")

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
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Error reading scalar '{scalar_name}' for peer {self._peer_id}: {e}"
                    )
                    continue
        except DbError:
            raise
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
        all_attrs = db.get_bucket(strict=False) or {}

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

    def apply_callback_data(
        self,
        data: dict[str, Any],
        *,
        subtarget: str | None = None,
        resource: str | None = None,
        target: str | None = None,
    ) -> ReplicaApplyResult:
        """Apply a subscription callback's data to the replica.

        The shape depends on the subscription's level (``subtarget``,
        ``resource``):

        - target level: a set of top-level keys. A value is a list operation
          only when it carries ``list`` and ``operation`` **and its ``list``
          is the key** (the legacy ``list:<name>`` key: ``list`` equal to
          ``<name>``); otherwise it is the scalar's value. A list diff is
          bound to the key it arrived under, never to a name its value
          carries.
        - subtarget level: a list diff whose ``list`` is the subtarget is
          one list operation; a list's state keyed by the subtarget's own name
          (a list diff, or the ``{"_list": true}`` form) is unwrapped;
          anything else, an object whose one key is the subtarget included,
          is the one scalar's value.
        - resource level: the value is merged into the stored property at
          the resource's path (segments are keys, never interpreted; a parent
          that is not an object is replaced); an empty value deletes that
          path.

        A scalar key starting ``list:`` (other than the legacy list-diff
        form) is refused. A name is a scalar or a list in a replica, never
        both: a list arriving where a scalar is stored replaces it, ``""``
        arriving for a list's name deletes the list, and any other scalar
        arriving for a list's name is out of step.

        A list diff this replica cannot apply (``ReplicaOutOfStep``) does not
        raise: the remaining keys are applied, a WARNING names the list and
        the operation, and the first such diff is the result's
        ``out_of_step`` attribute (a :class:`ReplicaApplyResult`; the
        callback path rebuilds the replica from a baseline). A ``DbError`` (a fault) raises; a key another bucket owns
        (``AttributeKeyCollision``) is refused and logged.

        SECURITY: Sanitizes untrusted data from remote peer before storage.
        """
        from .db.utils import sanitize_json_data

        if self._covered(target, subtarget):
            return self._skipped()
        data = sanitize_json_data(data, log_source=f"peer:{self._peer_id}:callback")
        results = ReplicaApplyResult()
        out_of_step: dict[str, Any] | None = None

        def record(key: str, outcome: dict[str, Any]) -> None:
            nonlocal out_of_step
            results[key] = outcome
            if outcome.get("out_of_step") and out_of_step is None:
                out_of_step = {
                    "list": outcome.get("list", key),
                    "operation": outcome.get("operation"),
                    "why": outcome.get("why"),
                }

        if subtarget and resource:
            record(
                subtarget,
                self._guarded(
                    subtarget, lambda: self._merge_resource(subtarget, resource, data)
                ),
            )
        elif subtarget:
            value: Any = data
            if (
                isinstance(value, dict)
                and "operation" in value
                and value.get("list") == subtarget
            ):
                record(
                    subtarget,
                    self._guarded(
                        subtarget,
                        lambda: self._apply_list_operation(
                            subtarget, str(value.get("operation")), value
                        ),
                    ),
                )
            else:
                if _wraps_list(value, subtarget):
                    # A list's full state keyed by its own name. Only a
                    # list's: a scalar whose one key is its own name (a
                    # property ``status`` = ``{"status": "ok"}``) is a value.
                    value = value[subtarget]
                record(
                    subtarget,
                    self._guarded(
                        subtarget, lambda: self._apply_entry(subtarget, value)
                    ),
                )
        elif not isinstance(data, dict):
            # A target-level body is a set of keys; anything else is
            # malformed and is not stored (the sequence moves on, as for
            # any callback the replica cannot use).
            logger.warning(
                "Ignored a target-level callback from peer %s for actor %s: "
                "its data is not an object (%s)",
                self._peer_id,
                self._actor.id,
                type(data).__name__,
            )
        else:
            for key, value in data.items():
                record(
                    key,
                    self._guarded(key, lambda k=key, v=value: self._apply_entry(k, v)),
                )

        if out_of_step is not None:
            logger.warning(
                "Replica of peer %s for actor %s is out of step: a %r diff for "
                "list %r could not be applied (%s); the replica is rebuilt from "
                "a baseline",
                self._peer_id,
                self._actor.id,
                out_of_step["operation"],
                out_of_step["list"],
                out_of_step["why"],
            )
            results.out_of_step = out_of_step
        return results

    def _covered(self, target: str | None, subtarget: str | None) -> bool:
        """Whether a subtarget-level ``properties`` subscription's data is
        stored by a subscription to the peer's whole ``properties`` target
        too: then only that one writes the replica, so no diff is applied
        twice (4.0; overlapping subscriptions doubled every append). Only
        when ``target`` is given; one subscription read, a fault raises."""
        if not subtarget or target != "properties":
            return False
        from .replica_revocation import subscribes_to_whole_properties

        return subscribes_to_whole_properties(
            self._actor.config, str(self._actor.id), self._peer_id
        )

    @staticmethod
    def _skipped() -> ReplicaApplyResult:
        result = ReplicaApplyResult()
        result.skipped = True
        return result

    def _guarded(self, key: str, apply: Any) -> dict[str, Any]:
        """Run one key's application: out of step and refused keys become
        results, a fault raises."""
        try:
            return apply()
        except ReplicaOutOfStep as e:
            return {"out_of_step": True, "list": e.list_name, "why": e.why}
        except AttributeKeyCollision:
            logger.warning(
                "Refused %r in the replica of peer %s: another bucket holds the key",
                key,
                self._peer_id,
            )
            return {"error": "refused", "reason": "key held by another bucket"}
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error applying callback data for {key!r}: {e}")
            return {"error": str(e)}

    def _list_exists(self, name: str) -> bool:
        return bool(self._get_list_store().exists(name))

    def _apply_entry(self, key: str, value: Any) -> dict[str, Any]:
        """One top-level key of a target-level diff (or a subtarget's own
        value)."""
        if isinstance(value, dict) and "operation" in value and "list" in value:
            if value.get("list") == key:
                return self._apply_list_operation(key, str(value["operation"]), value)
        if key.startswith("list:"):
            name = key[5:]
            if (
                isinstance(value, dict)
                and "operation" in value
                and value.get("list", name) == name
            ):
                return self._apply_list_operation(name, str(value["operation"]), value)
            logger.warning(
                "Refused the scalar %r from peer %s: a key starting 'list:' is "
                "reserved for list rows",
                key,
                self._peer_id,
            )
            return {"error": "refused", "reason": "scalar key starts with list:"}
        if value == "" or value is None:
            if self._list_exists(key):
                # A pre-4.0 publisher's list DELETE.
                self.delete_list(key)
                return {"deleted": True, "type": "list"}
            self.delete_value(key)
            return {"deleted": True, "type": "scalar"}
        if self._list_exists(key):
            raise ReplicaOutOfStep(key, "a scalar arrived for a list's name")
        if isinstance(value, dict):
            self.set_value(key, value)
            return {"stored": True, "type": "scalar"}
        self.set_value(key, {"value": value})
        return {"stored": True, "type": "scalar", "wrapped": True}

    def _merge_resource(
        self, subtarget: str, resource: str, value: Any
    ) -> dict[str, Any]:
        """A resource-level write: ``value`` at the resource's path inside
        the stored property ``subtarget``; an empty value deletes the path.
        Segments are keys; a parent that is not an object is replaced."""
        segments = [seg for seg in resource.split("/") if seg]
        if not segments:
            return self._apply_entry(subtarget, value)
        if self._list_exists(subtarget):
            # A name is a scalar or a list in a replica, never both.
            logger.warning(
                "Refused a resource write to %r from peer %s: a list holds the name",
                subtarget,
                self._peer_id,
            )
            return {"error": "refused", "reason": "a list holds the name"}
        stored = self.get_value(subtarget)
        root: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
        node = root
        for seg in segments[:-1]:
            child = node.get(seg)
            if not isinstance(child, dict):
                child = {}
            child = dict(child)
            node[seg] = child
            node = child
        if value == "" or value is None:
            node.pop(segments[-1], None)
        else:
            node[segments[-1]] = value
        if root:
            self.set_value(subtarget, root)
        else:
            self.delete_value(subtarget)
        return {"stored": True, "type": "resource", "path": "/".join(segments)}

    def _invalid_list_name(self, name: Any) -> str | None:
        """Why ``name`` cannot name a new list in this replica, or None."""
        if not isinstance(name, str) or not name:
            return "not a non-empty string"
        bad = first_control_character(name)
        if bad is not None:
            return f"contains the control character {bad}"
        for reserved in ("#", "$"):
            if reserved in name:
                return f"contains {reserved!r}"
        if name.startswith("_"):
            return "starts with '_'"
        limit = _SORT_KEY_BYTES - _LIST_KEY_OVERHEAD - len(self._bucket.encode())
        if len(name.encode("utf-8", "surrogatepass")) > limit:
            return f"longer than {limit} bytes"
        return None

    def _apply_list_operation(
        self, list_name: str, operation: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply one list operation to the list named ``list_name`` (the key
        the diff arrived under).

        A creating operation validates the name (a refused name answers an
        error result and a WARNING); a deleting one accepts any stored name.
        A list arriving where a scalar of that name is stored deletes the
        scalar first. Raises ``ReplicaOutOfStep`` when the replica no longer
        holds what the publisher's list held before the change: a damaged or
        conflicting list, the rank cap, sustained metadata contention, a
        spanned reference, an index out of range, a value-addressed
        ``update`` or ``delete`` whose item the replica does not hold once (or
        at ``index`` among equal ones), a ``delete`` whose ``length`` does not
        fit. What an overlapping subscription's second delivery looks like is
        a no-op: a ``remove`` whose item is absent, an ``update`` whose new
        item is there and old one is not, a ``delete`` whose item is gone and
        whose ``length`` the replica already has."""
        why = None if operation == "delete_all" else self._invalid_list_name(list_name)
        if why is not None and (
            operation in _CREATING_OPERATIONS or not self._list_exists(list_name)
        ):
            # Any operation on a list that does not exist yet may create it
            # (``clear``, ``update``): validated as a creation. A stored name
            # can always be deleted or changed.
            logger.warning(
                "Refused a %r diff from peer %s for list %r: the name %s",
                operation,
                self._peer_id,
                list_name,
                why,
            )
            return {"operation": operation, "error": "refused name"}
        try:
            try:
                return self._apply_list_operation_once(list_name, operation, data)
            except ListNameTakenError:
                logger.info(
                    "Replacing the scalar %r with a list in the replica of peer %s",
                    list_name,
                    self._peer_id,
                )
                self.delete_value(list_name)
                return self._apply_list_operation_once(list_name, operation, data)
        except (
            ListCorruptionError,
            ListRankExhaustedError,
            ListMetadataContentionError,
            ListItemTooLargeError,
        ) as e:
            # An item this replica cannot store leaves it short: out of step,
            # so the rebuild settles it as a baseline would (4.0).
            raise ReplicaOutOfStep(list_name, f"{type(e).__name__}: {e}") from e

    def _apply_list_operation_once(
        self, list_name: str, operation: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        if data.get("spanned") is True:
            # A reference (property_list.diff_reference): the publisher's
            # values were over the span threshold and the diff carries none.
            raise ReplicaOutOfStep(
                list_name, f"a {operation!r} diff refers to spanned values"
            )
        list_attr = self._get_list_store().get(list_name)

        if operation == "append" and "item" in data:
            list_attr.append(data["item"])
            return {"operation": "append", "success": True}

        if operation == "insert" and "item" in data and "index" in data:
            idx = data["index"]
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise ReplicaOutOfStep(list_name, f"insert index {idx!r} not an index")
            # As ``list.insert`` (and the publisher's SDK, which sends the
            # caller's index): a negative index counts from the end, and one
            # past either end clamps. (Not checked against ``length``: the
            # SDK's is the advisory count hint under v2.)
            length = len(list_attr)
            idx = max(0, length + idx) if idx < 0 else min(idx, length)
            list_attr.insert(idx, data["item"])
            return {"operation": "insert", "index": idx, "success": True}

        if (
            operation == "update"
            and "item" in data
            and ("index" in data or "old_item" in data)
        ):
            idx = data.get("index")
            if "old_item" in data:
                # Located by value when the sender said what the item was:
                # the one equal row, or the one at ``index`` among equal
                # rows. No equal row with the new item present is an applied
                # update (an overlapping subscription's second delivery);
                # anything else means the replica drifted: out of step, never
                # an overwrite of whatever sits at ``index``.
                old_item = data["old_item"]
                values = list_attr.to_list()
                matches = [i for i, v in enumerate(values) if v == old_item]
                if len(matches) == 1:
                    list_attr[matches[0]] = data["item"]
                    return {"operation": "update", "index": matches[0], "success": True}
                if matches and isinstance(idx, int) and idx in matches:
                    list_attr[idx] = data["item"]
                    return {"operation": "update", "index": idx, "success": True}
                if matches and idx is None:
                    # Equal rows and no position (``update_by_handle``,
                    # ``update_where``): any of them gives the same list.
                    list_attr[matches[0]] = data["item"]
                    return {"operation": "update", "index": matches[0], "success": True}
                if not matches and data["item"] in values:
                    return {"operation": "update", "success": True, "noop": True}
                raise ReplicaOutOfStep(
                    list_name,
                    "update of an item the replica does not hold once"
                    + (f" at index {idx!r}" if idx is not None else ""),
                )
            if isinstance(idx, int) and not isinstance(idx, bool) and idx < 0:
                idx += len(list_attr)  # a negative index counts from the end
            if not isinstance(idx, int) or not 0 <= idx < len(list_attr):
                raise ReplicaOutOfStep(list_name, f"update index {idx!r} out of range")
            list_attr[idx] = data["item"]
            return {"operation": "update", "index": idx, "success": True}

        if operation == "extend" and "items" in data:
            items = data["items"]
            if items:
                list_attr.extend(items)
            elif not self._list_exists(list_name):
                # An empty list's creation.
                list_attr.clear()
            return {"operation": "extend", "count": len(items), "success": True}

        if operation == "delete" and ("index" in data or "old_item" in data):
            idx = data.get("index")
            if "old_item" in data:
                # The item is named: delete the one equal item, or the one at
                # ``index`` among several equal ones; none left is an
                # already-applied delete. Equal items none of which is at
                # ``index`` mean the replica drifted: out of step.
                old_item = data["old_item"]
                values = list_attr.to_list()
                matches = [i for i, v in enumerate(values) if v == old_item]
                # ``length`` is not consulted: the specification makes it
                # advisory, and receivers MUST NOT use it to address rows.
                if not matches:
                    # Gone already (applied before).
                    return {"operation": "delete", "success": True, "noop": True}
                if len(matches) == 1:
                    del list_attr[matches[0]]
                    return {"operation": "delete", "index": matches[0], "success": True}
                if isinstance(idx, int) and idx in matches:
                    del list_attr[idx]
                    return {"operation": "delete", "index": idx, "success": True}
                if idx is None:
                    # Equal rows and no position: any of them gives the
                    # same list.
                    del list_attr[matches[0]]
                    return {"operation": "delete", "index": matches[0], "success": True}
                raise ReplicaOutOfStep(
                    list_name, f"delete of a duplicated item at index {idx!r}"
                )
            if isinstance(idx, int) and not isinstance(idx, bool) and idx < 0:
                idx += len(list_attr)  # a negative index counts from the end
            if not isinstance(idx, int) or not 0 <= idx < len(list_attr):
                raise ReplicaOutOfStep(list_name, f"delete index {idx!r} out of range")
            del list_attr[idx]
            return {"operation": "delete", "index": idx, "success": True}

        if operation == "pop":
            idx = data.get("index", -1)
            length = len(list_attr)
            if isinstance(idx, int) and idx < 0:
                idx += length
            if not isinstance(idx, int) or not 0 <= idx < length:
                raise ReplicaOutOfStep(
                    list_name, f"pop index {data.get('index', -1)!r} out of range"
                )
            list_attr.pop(idx)
            return {"operation": "pop", "index": idx, "success": True}

        if operation == "clear":
            list_attr.clear()
            return {"operation": "clear", "success": True}

        if operation == "delete_all":
            list_attr.delete()
            return {"operation": "delete_all", "success": True}

        if operation == "metadata":
            return {"operation": "metadata", "ignored": True}

        if operation == "remove" and "item" in data:
            try:
                list_attr.remove(data["item"])
            except ValueError:
                # Absent: already removed (an overlapping subscription's
                # second delivery). Not out of step.
                return {"operation": "remove", "success": True, "noop": True}
            return {"operation": "remove", "success": True}

        return {"operation": operation, "error": "unknown operation"}

    def apply_resync_data(
        self,
        data: Any,
        *,
        subtarget: str | None = None,
        resource: str | None = None,
        target: str | None = None,
    ) -> ReplicaApplyResult:
        """Apply a baseline, replacing only the properties it carries (other
        subscriptions' data in the same bucket stays).

        A baseline for a subtarget-level subscription is stored under the
        subtarget's name (its value, or the ``{"_list": true, "items"}`` form
        keyed by that name), never spread into top-level keys; a
        resource-level one is merged at the resource's path. A scalar key
        starting ``list:`` is refused (the legacy ``list:<name>`` key with a
        list value is a list). A baseline names what each key is: a scalar
        replaces a same-named list and a list a same-named scalar. A list
        whose baseline holds an item that cannot be stored is deleted and
        reported in its result.

        SECURITY: Sanitizes untrusted data from remote peer before storage.
        """
        from .db.utils import sanitize_json_data

        if self._covered(target, subtarget):
            return self._skipped()
        data = sanitize_json_data(data, log_source=f"peer:{self._peer_id}:resync")
        results = ReplicaApplyResult()
        if subtarget and resource:
            results[subtarget] = self._guarded(
                subtarget, lambda: self._merge_resource(subtarget, resource, data)
            )
            if "error" in results[subtarget] and results[subtarget].get(
                "error"
            ) not in ("refused", "refused name"):
                results.failed.append(subtarget)
            return results
        entries: Any = data
        if subtarget and (data is None or data == {}):
            # Nothing fetched (a failed or empty baseline): never a delete of
            # what the replica holds, and not a baseline that settles.
            results.failed.append(subtarget)
            return results
        if subtarget:
            # A list's state keyed by its own name, or the gone form
            # ``{subtarget: ""}`` the fetch answers for a 404.
            own = _wraps_list(data, subtarget, baseline=True) or data == {subtarget: ""}
            entries = data if own else {subtarget: data}
        elif not isinstance(data, dict):
            # As for a diff: a target-level baseline is a set of keys; any
            # other body is not stored.
            logger.warning(
                "Ignored a target-level baseline from peer %s for actor %s: "
                "its data is not an object (%s)",
                self._peer_id,
                self._actor.id,
                type(data).__name__,
            )
            return results
        for key, value in entries.items():
            try:
                outcome = self._resync_entry(key, value)
            except AttributeKeyCollision:
                logger.warning(
                    "Refused %r in the replica of peer %s: another bucket holds "
                    "the key",
                    key,
                    self._peer_id,
                )
                outcome = (key, {"error": "refused", "success": False})
            except DbError:
                raise
            except Exception as e:
                logger.error(f"Error applying resync data for {key!r}: {e}")
                outcome = (key, {"error": str(e)})
            results[outcome[0]] = outcome[1]
            if "error" in outcome[1] and outcome[1]["error"] not in (
                "refused",
                "refused name",
            ):
                results.failed.append(outcome[0])
        return results

    def _resync_entry(self, key: str, value: Any) -> tuple[str, dict[str, Any]]:
        from datetime import datetime

        def as_list(name: str, items: list[Any]) -> tuple[str, dict[str, Any]]:
            why = self._invalid_list_name(name)
            if why is not None:
                # The peer's own name, refused: not a baseline this replica
                # failed to store (a rebuild must not stay owed for it).
                logger.warning(
                    "Refused list %r from peer %s in a baseline: the name %s",
                    name,
                    self._peer_id,
                    why,
                )
                return name, {"error": "refused name", "success": False}
            metadata = {
                "source_actor": self._peer_id,
                "source_property": name,
                "synced_at": datetime.now(UTC).isoformat(),
                "item_count": len(items),
            }
            self.set_list(name, items, metadata=metadata)
            return name, {"operation": "resync", "items": len(items), "success": True}

        if isinstance(value, dict) and value.get("_list") is True:
            if "items" not in value:
                # List metadata without items: skipped, not emptied.
                logger.warning(
                    f"Skipping list {key!r} in resync: metadata without items "
                    f"(transformation may have failed)"
                )
                # A failure (4.0, verification M5): the baseline did not
                # carry the list, so an owed rebuild stays owed.
                return key, {
                    "operation": "skip",
                    "reason": "metadata_without_items",
                    "error": "metadata_without_items",
                    "success": False,
                }
            return as_list(key, list(value.get("items") or []))
        if key.startswith("list:"):
            if isinstance(value, list):
                return as_list(key[5:], value)
            logger.warning(
                "Refused the scalar %r from peer %s: a key starting 'list:' is "
                "reserved for list rows",
                key,
                self._peer_id,
            )
            return key, {"error": "refused", "success": False}
        if value == "":
            # Gone at the publisher (a subtarget's GET answered 404): as a
            # callback's "" for a name, the list or the scalar is deleted.
            if self._list_exists(key):
                self.delete_list(key)
            else:
                self.delete_value(key)
            return key, {"deleted": True, "success": True}
        if self._list_exists(key):
            self.delete_list(key)
        if isinstance(value, dict):
            self.set_value(key, value)
        else:
            self.set_value(key, {"value": value})
        return key, {"operation": "resync", "success": True}

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

            from .replica_revocation import cleanup_after_store

            cleans = getattr(self._actor.config, "auto_delete_on_revocation", False)
            old_grant = (
                store.read_stored_permissions(actor_id, self._peer_id)[1]
                if cleans is True
                else None
            )
            success = store.store_permissions(peer_perms)
            if success and cleans is True:
                cleanup_after_store(
                    self._actor.config,
                    self._actor,
                    self._peer_id,
                    old_grant,
                    peer_perms,
                )
            return {"operation": "permission_update", "success": success}

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error applying permission data from {self._peer_id}: {e}")
            return {"operation": "permission_update", "success": False, "error": str(e)}
