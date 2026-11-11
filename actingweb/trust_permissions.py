"""
Trust Permission Storage for ActingWeb Unified Access Control.

This module manages per-trust-relationship permission storage using ActingWeb's
attribute store pattern. It allows individual trust relationships to override
the default permissions defined in trust types.

When notify_peer_on_change is enabled (default), storing permissions will
automatically notify the affected peer via a callback to their
/callbacks/permissions/{actor_id} endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from . import attribute
from . import config as config_class
from ._bounded_cache import CACHE_MAX_ENTRIES, BoundedDict
from .constants import TRUST_PERMISSIONS_BUCKET
from .db.exceptions import DbError

logger = logging.getLogger(__name__)

# Timeout for peer notification HTTP requests (seconds)
PEER_NOTIFICATION_TIMEOUT = 10.0
# A permission callback answered 503 is resent this many times, with the same
# body, waiting the receiver's Retry-After (at most the cap; the sync sender,
# which cannot read the header, waits the default).
PERMISSION_CALLBACK_RESENDS = 2
PERMISSION_CALLBACK_RESEND_WAIT = 1.0
PERMISSION_CALLBACK_RESEND_WAIT_CAP = 2.0


def _retry_after(value: str | None) -> float:
    """Seconds to wait before a resend: the receiver's ``Retry-After`` in
    seconds, capped; the default when absent or not a number."""
    try:
        seconds = float(value) if value is not None else PERMISSION_CALLBACK_RESEND_WAIT
    except ValueError:
        return PERMISSION_CALLBACK_RESEND_WAIT
    if not math.isfinite(seconds):
        return PERMISSION_CALLBACK_RESEND_WAIT
    return min(max(seconds, 0.0), PERMISSION_CALLBACK_RESEND_WAIT_CAP)


@dataclass
class TrustPermissions:
    """
    Per-trust-relationship permission overrides.

    These permissions override the base permissions defined in the trust type.
    Only specified fields will override - unspecified fields use trust type defaults.
    """

    actor_id: str  # The actor granting permissions
    peer_id: str  # The peer receiving permissions
    trust_type: str  # The trust type this relationship is based on

    # Permission overrides (None means use trust type default)
    properties: dict[str, Any] | None = None
    methods: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None

    # Metadata
    created_by: str = "system"
    updated_at: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustPermissions:
        """Create from dictionary loaded from storage."""
        return cls(**data)

    def get_permission_key(self) -> str:
        """Generate unique key for this trust relationship."""
        return f"{self.actor_id}:{self.peer_id}"

    def validate(self) -> bool:
        """Validate the trust permissions definition."""
        if not self.actor_id or not isinstance(self.actor_id, str):
            return False
        if not self.peer_id or not isinstance(self.peer_id, str):
            return False
        if not self.trust_type or not isinstance(self.trust_type, str):
            return False
        return True


_EDITABLE_FIELDS = frozenset(
    {"properties", "methods", "actions", "tools", "resources", "prompts", "notes"}
)
"""What ``update_permissions`` takes from an update."""

_IDENTITY_FIELDS = frozenset(
    {"actor_id", "peer_id", "trust_type", "created_by", "updated_at"}
)
"""What it never does: an override's identity and its bookkeeping."""


_CATEGORIES = tuple(sorted(_EDITABLE_FIELDS - {"notes"}))
PERMISSION_CATEGORIES = _CATEGORIES
"""The permission categories an override holds (one list for the store, the
intake check and the evaluator)."""
_RULE_LIST_KEYS = ("patterns", "excluded_patterns", "operations", "allowed", "denied")


def _is_name_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def permission_updates_problem(updates: Any) -> str | None:
    """Why ``updates`` (a grant edit from a request) cannot be stored, or
    None (3.16). An edit is an object; each permission category is an object
    or null; a rule's pattern and operation keys are lists of strings (a
    string in their place replaced the trust type's list on merge, dropping
    its base exclusions)."""
    if not isinstance(updates, dict):
        return "Permissions must be an object"
    if updates.get("notes") is not None and not isinstance(updates["notes"], str):
        return "notes must be text"
    for category in _CATEGORIES:
        rule = updates.get(category)
        if rule is None:
            continue
        if category == "properties" and isinstance(rule, list):
            # The shorthand list of property names.
            if not all(isinstance(item, str) for item in rule):
                return "properties must be names"
            continue
        if not isinstance(rule, dict):
            return f"{category} must be an object"
        for key in _RULE_LIST_KEYS:
            if key in rule and not _is_name_list(rule[key]):
                return f"{category}.{key} must be a list of strings"
    return None


def is_client_peer(peer_id: str) -> bool:
    """An OAuth2/MCP client's peer id (``oauth2_client:...``), the rows a
    client authorisation creates and re-types (3.16)."""
    return str(peer_id or "").startswith("oauth2_client:")


def override_applies(permissions: Any, peer_id: str, row_type: str | None) -> bool:
    """Whether a stored override is applied for this trust (3.16, owner
    decision 2026-11-11): always for a peer; for an OAuth2/MCP client only
    when it names the row's type (its level is the one the user approved).
    The evaluator, the owner's grant API and the views use this one rule."""
    if permissions is None:
        return False
    if not is_client_peer(peer_id):
        return True
    return str(getattr(permissions, "trust_type", "") or "") == str(row_type or "")


class TrustPermissionStore:
    """
    Storage manager for per-trust-relationship permissions.

    Permissions are stored in actor-specific attribute buckets:
    bucket="trust_permissions", actor_id={actor_id}, name="{actor_id}:{peer_id}"

    This allows each actor to manage permissions for their trust relationships
    while maintaining the ActingWeb attribute store pattern.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        # Values may be None: a confirmed "no override stored" is cached too,
        # otherwise every permission evaluation for a peer without an
        # override re-reads the attribute bucket.
        # Bounded LRU: one entry per actor:peer pair, not one per pair ever
        # seen (actingweb/_bounded_cache.py).
        self._cache: BoundedDict[str, TrustPermissions | None] = BoundedDict(
            CACHE_MAX_ENTRIES
        )

    def _get_permissions_bucket(self, actor_id: str) -> attribute.Attributes | None:
        """Get the trust permissions attribute bucket for an actor."""
        try:
            return attribute.Attributes(
                actor_id=actor_id, bucket=TRUST_PERMISSIONS_BUCKET, config=self.config
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error accessing trust permissions bucket for actor {actor_id}: {e}"
            )
            return None

    def _store_permissions_internal(self, permissions: TrustPermissions) -> bool:
        """Internal storage logic shared by sync and async methods.

        Args:
            permissions: The TrustPermissions to store.

        Returns:
            True if storage succeeded, False otherwise.
        """
        if not permissions.validate():
            logger.error(
                f"Invalid trust permissions definition: {permissions.get_permission_key()}"
            )
            return False

        bucket = self._get_permissions_bucket(permissions.actor_id)
        if not bucket:
            logger.error(
                f"Cannot access trust permissions bucket for actor {permissions.actor_id}"
            )
            return False

        try:
            # Store permissions data in attribute bucket
            permission_key = permissions.get_permission_key()
            permissions_data = permissions.to_dict()

            success = bucket.set_attr(
                name=permission_key, data=json.dumps(permissions_data)
            )

            if success:
                # Update cache
                cache_key = f"{permissions.actor_id}:{permissions.peer_id}"
                self._cache[cache_key] = permissions
                # This store's own cache is not the only one holding the old
                # permissions: the MCP handler caches the resolved trust
                # relationship for five minutes, so a downgrade would otherwise
                # keep being honoured at the old level from a warm process.
                from .mcp.invalidation import evict_caches_for_actor

                evict_caches_for_actor(permissions.actor_id)
                logger.info(f"Stored trust permissions: {cache_key}")
                return True
            else:
                logger.error(f"Failed to store trust permissions {permission_key}")
                return False

        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Error storing trust permissions {permissions.get_permission_key()}: {e}"
            )
            return False

    def _should_notify_peer(self, notify_peer: bool | None) -> bool:
        """Determine if peer should be notified based on parameter and config.

        Args:
            notify_peer: Override for peer notification. If None (default),
                uses config.notify_peer_on_change.

        Returns:
            True if peer should be notified, False otherwise.
        """
        if notify_peer is not None:
            return notify_peer
        return getattr(self.config, "notify_peer_on_change", True)

    def store_permissions(
        self, permissions: TrustPermissions, notify_peer: bool | None = None
    ) -> bool:
        """Store trust relationship permissions.

        If notify_peer_on_change is enabled in config (default True) and
        notify_peer is not explicitly False, automatically sends a permission
        callback to the affected peer.

        Args:
            permissions: The TrustPermissions to store.
            notify_peer: Override for peer notification. If None (default),
                uses config.notify_peer_on_change. If True/False, overrides config.

        Returns:
            True if storage succeeded. Notification failures are logged but
            don't affect the return value.

        Performance Notes:
            Sync version: Notification uses blocking HTTP request. For high-throughput
            scenarios, use store_permissions_async() instead.
        """
        success = self._store_permissions_internal(permissions)

        if success and self._should_notify_peer(notify_peer):
            try:
                self._notify_peer(permissions)
            except Exception as e:  # folds DbError: peer notification after the permissions were stored
                # Fire-and-forget: log but don't affect return value
                logger.warning(
                    f"Exception during peer notification for {permissions.actor_id}: {e}",
                    exc_info=True,
                )

        return success

    async def store_permissions_async(
        self, permissions: TrustPermissions, notify_peer: bool | None = None
    ) -> bool:
        """Store trust relationship permissions asynchronously.

        Same as store_permissions() but uses async notification.

        Args:
            permissions: The TrustPermissions to store.
            notify_peer: Override for peer notification. If None (default),
                uses config.notify_peer_on_change. If True/False, overrides config.

        Returns:
            True if storage succeeded. Notification failures are logged but
            don't affect the return value.

        Performance Notes:
            Async version: Notification is fire-and-forget using background task.
            This prevents blocking when the peer is on the same server.
        """
        success = self._store_permissions_internal(permissions)

        if success and self._should_notify_peer(notify_peer):
            # Fire-and-forget: schedule notification as background task

            async def _notify_with_error_handling():
                try:
                    await self._notify_peer_async(permissions)
                except Exception as e:  # folds DbError: peer notification after the permissions were stored
                    logger.warning(
                        f"Exception during async peer notification for {permissions.actor_id}: {e}",
                        exc_info=True,
                    )

            asyncio.create_task(_notify_with_error_handling())

        return success

    def _notify_peer(self, permissions: TrustPermissions) -> None:
        """Send permission callback to the affected peer.

        This is fire-and-forget - failures are logged but don't affect
        the store operation.

        Uses AwProxy which handles trust relationship lookup and HTTP
        communication internally.

        Args:
            permissions: The TrustPermissions that were stored.
        """
        actor_id = permissions.actor_id
        peer_id = permissions.peer_id

        logger.debug(
            f"Notifying peer {peer_id} of permission change from actor {actor_id}"
        )

        try:
            from .aw_proxy import AwProxy

            proxy = AwProxy(
                peer_target={
                    "id": actor_id,
                    "peerid": peer_id,
                    "passphrase": None,
                },
                config=self.config,
            )

            if not proxy.trust:
                logger.warning(
                    f"Cannot notify peer {peer_id} from actor {actor_id}: "
                    "no trust relationship"
                )
                return

            callback_data = self._build_callback_data(permissions)

            # POST to peer's /callbacks/permissions/{our_actor_id}. A 503 (the
            # receiver lost concurrent writes, or faulted) is resent with the
            # same body, so the same timestamp orders it.
            response = proxy.create_resource(
                path=f"callbacks/permissions/{actor_id}",
                params=callback_data,
            )
            for _resend in range(PERMISSION_CALLBACK_RESENDS):
                if proxy.last_response_code != 503:
                    break
                time.sleep(PERMISSION_CALLBACK_RESEND_WAIT)
                response = proxy.create_resource(
                    path=f"callbacks/permissions/{actor_id}",
                    params=callback_data,
                )

            # Decided by the status: a 204 answers with no body ({}), and so
            # does a 503 whose body does not parse.
            code = proxy.last_response_code
            if response is not None and isinstance(code, int) and 200 <= code < 300:
                logger.debug(
                    f"Successfully notified peer {peer_id} of permission change "
                    f"from actor {actor_id}"
                )
            else:
                logger.warning(
                    f"Failed to notify peer {peer_id} from actor {actor_id}: "
                    f"status={code} {response}"
                )

        except Exception as e:  # folds DbError: notify after the store
            logger.warning(
                f"Error notifying peer {peer_id} from actor {actor_id}: {e}",
                exc_info=True,
            )

    async def _notify_peer_async(self, permissions: TrustPermissions) -> None:
        """Send permission callback to the affected peer asynchronously.

        This is fire-and-forget - failures are logged but don't affect
        the store operation.

        Note: Uses Trust directly instead of AwProxy because AwProxy doesn't
        support async HTTP. This approach manually constructs the callback URL
        and uses httpx.AsyncClient for non-blocking HTTP requests.

        Args:
            permissions: The TrustPermissions that were stored.
        """
        actor_id = permissions.actor_id
        peer_id = permissions.peer_id

        logger.debug(
            f"Notifying peer {peer_id} of permission change from actor {actor_id} (async)"
        )

        try:
            import httpx

            from .trust import Trust

            # Get trust relationship to find peer URL and secret
            trust = Trust(
                actor_id=actor_id,
                peerid=peer_id,
                config=self.config,
            )
            trust_info = trust.get()

            if not trust_info:
                logger.warning(
                    f"Cannot notify peer {peer_id} from actor {actor_id}: "
                    "no trust relationship"
                )
                return

            peer_baseuri = trust_info.get("baseuri", "")
            peer_secret = trust_info.get("secret", "")

            if not peer_baseuri:
                logger.warning(
                    f"Cannot notify peer {peer_id} from actor {actor_id}: "
                    "no baseuri in trust"
                )
                return

            callback_url = (
                f"{peer_baseuri.rstrip('/')}/callbacks/permissions/{actor_id}"
            )
            callback_data = self._build_callback_data(permissions)

            headers = {"Content-Type": "application/json"}
            if peer_secret:
                headers["Authorization"] = f"Bearer {peer_secret}"

            async with httpx.AsyncClient(timeout=PEER_NOTIFICATION_TIMEOUT) as client:
                response = await client.post(
                    callback_url,
                    json=callback_data,
                    headers=headers,
                )
                # A 503 is resent with the same body (same timestamp).
                for _resend in range(PERMISSION_CALLBACK_RESENDS):
                    if response.status_code != 503:
                        break
                    await asyncio.sleep(
                        _retry_after(response.headers.get("Retry-After"))
                    )
                    response = await client.post(
                        callback_url,
                        json=callback_data,
                        headers=headers,
                    )

                if response.status_code in (200, 201, 202, 204):
                    logger.debug(
                        f"Successfully notified peer {peer_id} of permission change "
                        f"from actor {actor_id} (async)"
                    )
                else:
                    logger.warning(
                        f"Failed to notify peer {peer_id} from actor {actor_id}: "
                        f"status={response.status_code}"
                    )

        except Exception as e:  # folds DbError: notify after the store
            logger.warning(
                f"Error notifying peer {peer_id} from actor {actor_id}: {e}",
                exc_info=True,
            )

    def _get_effective_permissions(
        self, permissions: TrustPermissions
    ) -> dict[str, Any]:
        """Get the full effective permissions by merging overrides with base trust-type defaults.

        For each permission category, returns the override if set, otherwise
        falls back to the base trust-type default. This ensures the callback
        payload and GET /permissions responses contain the complete effective
        permission set, not just the overrides.

        Args:
            permissions: The TrustPermissions with overrides.

        Returns:
            Dict with all permission categories populated with effective values.
        """
        from .trust_type_registry import get_registry

        # Build override dict from TrustPermissions fields
        override_dict: dict[str, Any] = {}
        categories = [
            "properties",
            "methods",
            "actions",
            "tools",
            "resources",
            "prompts",
        ]
        for category in categories:
            value = getattr(permissions, category, None)
            if value is not None:
                override_dict[category] = value

        # Look up base permissions from trust type registry
        base_permissions: dict[str, Any] = {}
        try:
            registry = get_registry(self.config)
            trust_type = registry.get_type(permissions.trust_type)
            if trust_type and trust_type.base_permissions:
                base_permissions = trust_type.base_permissions
        except DbError:
            raise
        except Exception as e:
            logger.warning(
                f"Could not load base permissions for trust type "
                f"'{permissions.trust_type}': {e}"
            )

        if not base_permissions:
            # No base permissions available, return overrides only
            return {cat: override_dict.get(cat) for cat in categories}

        # Merge base permissions with overrides
        merged = merge_permissions(base_permissions, override_dict)

        # Return only the standard categories
        return {cat: merged.get(cat) for cat in categories}

    def _build_callback_data(self, permissions: TrustPermissions) -> dict[str, Any]:
        """Build the callback data payload for permission notification.

        Sends the full effective permissions (base trust-type defaults merged
        with overrides) so the receiving peer can accurately detect what changed.

        Args:
            permissions: The TrustPermissions to send.

        Returns:
            Dict containing the callback payload with full effective permissions.
        """
        effective = self._get_effective_permissions(permissions)

        return {
            "id": permissions.actor_id,
            "target": "permissions",
            "type": "permission",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": effective,
        }

    def get_permissions(self, actor_id: str, peer_id: str) -> TrustPermissions | None:
        """Get trust relationship permissions."""
        cache_key = f"{actor_id}:{peer_id}"

        # Check cache first: one locked read (a cached None is a hit)
        hit, cached = self._cache.lookup(cache_key)
        if hit:
            return cached

        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return None

        try:
            permission_key = f"{actor_id}:{peer_id}"

            # Get permissions from attribute bucket
            attr_data = bucket.get_attr(name=permission_key)

            if not attr_data or "data" not in attr_data:
                # Cache the negative: store/delete paths update the cache, so
                # this stays correct within the process.
                self._cache[cache_key] = None
                return None

            # Parse JSON and create TrustPermissions
            permissions_data = json.loads(attr_data["data"])
            permissions = TrustPermissions.from_dict(permissions_data)

            # Cache the result
            self._cache[cache_key] = permissions

            return permissions

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error loading trust permissions {cache_key}: {e}")
            return None

    def list_actor_permissions(self, actor_id: str) -> list[TrustPermissions]:
        """List all permission overrides for an actor."""
        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return []

        permissions_list = []

        try:
            # Get all attributes from the trust permissions bucket
            bucket_data = bucket.get_bucket() or {}

            for attr_name, attr_info in bucket_data.items():
                try:
                    permissions_data = json.loads(attr_info["data"])
                    permissions = TrustPermissions.from_dict(permissions_data)
                    permissions_list.append(permissions)

                    # Cache while we're at it
                    cache_key = f"{permissions.actor_id}:{permissions.peer_id}"
                    self._cache[cache_key] = permissions

                except Exception as e:  # folds DbError: no DB access
                    logger.error(f"Error parsing trust permissions {attr_name}: {e}")
                    continue

            return permissions_list

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error listing trust permissions for actor {actor_id}: {e}")
            return []

    def get_permissions_uncached(
        self, actor_id: str, peer_id: str
    ) -> TrustPermissions | None:
        """The stored override, read from the store, not the cache (3.16: a
        delete decides from what is there). A fault raises ``DbError``."""
        self._cache.pop(f"{actor_id}:{peer_id}", None)
        return self.get_permissions(actor_id, peer_id)

    def notify_default_grant(
        self, actor_id: str, peer_id: str, trust_type: str
    ) -> None:
        """Tell the peer its grant is back to its trust type's default (3.16:
        the override was deleted), through the sender a store uses, with its
        resends; when peer notification is on. Fire-and-forget."""
        if not self._should_notify_peer(None):
            return
        try:
            self._notify_peer(
                create_permission_override(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    trust_type=trust_type,
                    permission_updates={},
                )
            )
        except Exception as e:  # folds DbError: notification after the delete
            logger.warning(
                f"Could not tell {peer_id} its grant from {actor_id} was reset: {e}"
            )

    def notify_stored_grant(self, actor_id: str, peer_id: str) -> None:
        """Send the peer the grant stored for it now, when peer notification
        is on (3.16: the trust ``PUT`` stores a grant silently and tells the
        peer only once the trust write landed). Fire-and-forget."""
        if not self._should_notify_peer(None):
            return
        try:
            stored = self.get_permissions_uncached(actor_id, peer_id)
            if stored:
                self._notify_peer(stored)
        except Exception as e:  # folds DbError: notification after the write
            logger.warning(f"Could not tell {peer_id} its grant from {actor_id}: {e}")

    def delete_permissions(self, actor_id: str, peer_id: str) -> bool:
        """Delete trust relationship permissions. Sends nothing to the peer:
        its callers delete a row's override with the row or before a new one
        (the REST delete of a grant notifies, ``notify_default_grant``)."""
        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return False

        try:
            permission_key = f"{actor_id}:{peer_id}"

            # Delete from attribute bucket
            success = bucket.delete_attr(name=permission_key)

            if success:
                # Remove from cache
                cache_key = f"{actor_id}:{peer_id}"
                self._cache.pop(cache_key, None)
                # Same reason as _store_permissions_internal(): the MCP
                # handler's cached trust relationship outlives this one.
                from .mcp.invalidation import evict_caches_for_actor

                evict_caches_for_actor(actor_id)
                logger.info(f"Deleted trust permissions: {cache_key}")
                return True
            else:
                logger.error(f"Failed to delete trust permissions {permission_key}")
                return False

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error deleting trust permissions {actor_id}:{peer_id}: {e}")
            return False

    def update_permissions(
        self,
        actor_id: str,
        peer_id: str,
        updates: dict[str, Any],
        notify_peer: bool | None = None,
    ) -> bool:
        """Update specific permission fields for a trust relationship.

        Normalizes any shorthand permission formats to the spec-compliant
        structured format before storage.
        """
        # Load existing permissions
        existing = self.get_permissions(actor_id, peer_id)
        if not existing:
            logger.error(
                f"Cannot update non-existent permissions for {actor_id}:{peer_id}"
            )
            return False

        try:
            # Apply updates to the existing permissions
            updated_data = existing.to_dict()

            # Update only the specified fields, normalizing properties format
            for field, value in updates.items():
                if field in _IDENTITY_FIELDS:
                    # Which actor, peer and base type an override belongs to
                    # is the store's, never the request's (3.16: the store
                    # keys on these, so an owner's PUT could write into
                    # another actor's grants).
                    logger.warning(f"Refused to update permission field: {field}")
                elif field in _EDITABLE_FIELDS:
                    # Normalize properties to spec-compliant format
                    if field == "properties":
                        from .peer_permissions import normalize_property_permission

                        value = normalize_property_permission(value)
                    updated_data[field] = value
                else:
                    logger.warning(f"Unknown permission field: {field}")

            # Create updated permissions object
            updated_permissions = TrustPermissions.from_dict(updated_data)

            # Store the updated permissions
            return self.store_permissions(updated_permissions, notify_peer=notify_peer)

        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error updating trust permissions {actor_id}:{peer_id}: {e}")
            return False

    def clear_cache(self):
        """Clear the internal cache."""
        self._cache.clear()


# Permission helper functions


_EXCLUSION_KEYS = ("excluded_patterns", "denied")
_DENY_RULE: dict[str, Any] = {"patterns": [], "operations": [], "allowed": []}
"""A rule that allows nothing, in both rule shapes (patterns/operations and
allowed); it replaces the trust type's rule, never merges into it."""


def _well_formed_rule(category: str, rule: Any) -> dict[str, Any]:
    """An override's rule for ``category`` in the shape the evaluator reads,
    failing toward less access (3.16; a row written before the intake check
    or through the store API may hold anything):

    - not an object: the ``properties`` shorthand list of names is
      normalised; anything else is an empty rule, which denies (it replaced
      the trust type's rule and denied before; falling back to the trust
      type's rule granted more);
    - an allow list (``patterns``, ``operations``, ``allowed``) that is not
      a list of names is empty: for ``operations`` and ``allowed``, which
      replace the trust type's, it allows nothing; ``patterns`` merges by
      union, so an empty one leaves the trust type's patterns, as a valid
      empty override does;
    - an exclusion (``excluded_patterns``, ``denied``) given as one string
      excludes that pattern; any other malformed one is dropped, so the
      trust type's own exclusions stay (it replaced them).
    """
    if not isinstance(rule, dict):
        if category == "properties" and _is_name_list(rule):
            from .peer_permissions import normalize_property_permission

            normalized = normalize_property_permission(rule)
            if isinstance(normalized, dict):
                return normalized
        logger.debug(f"Override {category} is not an object; it allows nothing")
        return dict(_DENY_RULE)
    out: dict[str, Any] = {}
    for key, value in rule.items():
        if key not in _RULE_LIST_KEYS or _is_name_list(value):
            out[key] = value
        elif key in _EXCLUSION_KEYS:
            if isinstance(value, str):
                out[key] = [value]
            # else: dropped, the trust type's exclusions apply
        else:
            out[key] = []
    return out


def merge_permissions(
    base_permissions: dict[str, Any],
    override_permissions: dict[str, Any] | None,
    merge_base: bool = True,
) -> dict[str, Any]:
    """
    Merge base permissions with override permissions.

    By default (merge_base=True), 'patterns' and 'excluded_patterns' arrays are
    combined (union) rather than replaced. This provides fail-safe security:
    - Base trust type patterns (e.g., profile/*, public/*) are preserved
    - Base security exclusions (e.g., private/*, security/*) are preserved
    - Overrides can only ADD patterns/exclusions, not remove them

    When merge_base=False, override values completely replace base values,
    allowing full control over permissions when explicitly needed.

    Args:
        base_permissions: Default permissions from trust type
        override_permissions: Override permissions from trust relationship (can be None)
        merge_base: If True (default), union patterns and excluded_patterns arrays.
                   If False, override values replace base values entirely.

    Returns:
        Merged permissions dict

    Security Notes:
        - With merge_base=True: Cannot accidentally remove base security exclusions
        - With merge_base=False: Full override capability, use with caution
        - Other fields (operations, allowed, denied) are replaced by overrides
        - A malformed rule fails toward less access (``_well_formed_rule``)
    """
    if not override_permissions:
        return base_permissions.copy()

    # Fields that use union merge when merge_base=True
    UNION_MERGE_FIELDS = {"patterns", "excluded_patterns"}

    # Deep merge the permissions
    merged = base_permissions.copy()

    for category, overrides in override_permissions.items():
        if overrides is None:
            # None means use base permissions for this category
            continue
        replaces = not isinstance(overrides, dict) and not (
            category == "properties" and _is_name_list(overrides)
        )
        overrides = _well_formed_rule(category, overrides)

        if replaces:
            # Not a rule: it allows nothing, whatever the trust type allows.
            merged[category] = overrides
        elif category in merged and isinstance(merged[category], dict):
            # Deep merge dictionaries
            merged_category = merged[category].copy()
            for key, value in overrides.items():
                if merge_base and key in UNION_MERGE_FIELDS:
                    # Union merge: combine arrays, preserving base values
                    # - Empty override arrays preserve base values (fail-safe)
                    # - To clear base values entirely, use merge_base=False
                    # - Pattern order: base patterns first, then new patterns
                    #   (order doesn't affect evaluation; all patterns are matched)
                    base_list = merged_category.get(key, [])
                    if isinstance(base_list, list):
                        # Combine and deduplicate, base values first
                        merged_category[key] = list(base_list) + [
                            item for item in value if item not in base_list
                        ]
                    else:
                        merged_category[key] = value
                else:
                    # Replace: override value replaces base value
                    merged_category[key] = value
            merged[category] = merged_category
        else:
            # Add new category (or replace a base that is not an object)
            merged[category] = overrides

    return merged


def create_permission_override(
    actor_id: str, peer_id: str, trust_type: str, permission_updates: dict[str, Any]
) -> TrustPermissions:
    """
    Create a permission override object for a trust relationship.

    Normalizes any shorthand permission formats to the spec-compliant structured
    format before storage. This ensures consistent storage format regardless of
    input format.

    Args:
        actor_id: The actor granting permissions
        peer_id: The peer receiving permissions
        trust_type: The trust type this relationship is based on
        permission_updates: Dict containing permission category updates.
            Accepts both spec-compliant format and shorthand list format for
            properties (e.g., ["prop1", "prop2"] is converted to
            {"patterns": [...], "operations": ["read"]}).

    Returns:
        TrustPermissions object ready for storage with normalized permissions
    """
    # Import here to avoid circular import
    from .peer_permissions import normalize_property_permission

    # Extract and normalize permission categories from updates
    permissions = TrustPermissions(
        actor_id=actor_id,
        peer_id=peer_id,
        trust_type=trust_type,
        properties=normalize_property_permission(permission_updates.get("properties")),
        methods=permission_updates.get("methods"),
        actions=permission_updates.get("actions"),
        tools=permission_updates.get("tools"),
        resources=permission_updates.get("resources"),
        prompts=permission_updates.get("prompts"),
        # The store's bookkeeping, not the request's (3.16; an update
        # refuses it too).
        created_by="system",
        notes=permission_updates.get("notes"),
    )

    return permissions


# Singleton instance
_permission_store: TrustPermissionStore | None = None
# Config the singleton above was built with -- see get_trust_permission_store().
_permission_store_config: config_class.Config | None = None


def initialize_trust_permission_store(config: config_class.Config) -> None:
    """Initialize the trust permission store at application startup."""
    global _permission_store, _permission_store_config
    if _permission_store is None or _permission_store_config is not config:
        logger.info("Initializing trust permission store...")
        _permission_store = TrustPermissionStore(config)
        _permission_store_config = config
        logger.info("Trust permission store initialized")


def get_trust_permission_store(
    config: config_class.Config,
) -> TrustPermissionStore:
    """Get the singleton trust permission store (must be initialized first).

    The ``config`` argument used to be documented as "kept for interface
    consistency but not used". That made the store bind permanently to
    whichever application initialized it first, so a second ActingWeb
    application in the same interpreter silently got the first one's store --
    including its database backend. It is now honored: a different config
    rebuilds the store.
    """
    if _permission_store is None or _permission_store_config is not config:
        # Building the store reads nothing, so a store missed at startup is
        # built here rather than raising: a RuntimeError sent the property
        # handlers to the legacy grant, which ignores DENY overrides.
        initialize_trust_permission_store(config)
    assert _permission_store is not None
    return _permission_store
