"""
Peer Permission Caching for Trust Relationships.

This module provides first-class support for caching permission grants from
peer actors that have trust relationships. It stores what permissions the
REMOTE peer has granted US access to.

This is distinct from TrustPermissions which stores what WE grant to peers.
PeerPermissions stores what PEERS grant to us (the cached received permissions).
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import attribute
from . import config as config_class
from .constants import PEER_PERMISSIONS_BUCKET

logger = logging.getLogger(__name__)


@dataclass
class PeerPermissions:
    """
    Cached permissions granted by a peer actor.

    This represents what the peer has granted us access to, received via
    permission callbacks or fetched from the peer's /permissions endpoint.

    Permission structure follows the TrustPermissions format:
    - properties: {patterns: [], operations: [], excluded_patterns: []}
    - methods: {allowed: [], denied: []}
    - actions: {allowed: [], denied: []}
    - tools: {allowed: [], denied: []} (MCP-specific)
    - resources: {allowed: [], denied: []} (MCP-specific)
    - prompts: {allowed: []} (MCP-specific)
    """

    actor_id: str  # Actor storing this cache (receiver)
    peer_id: str  # Peer who granted permissions (grantor)

    # Full permission categories (None = use defaults from trust type)
    properties: dict[str, Any] | None = None
    methods: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None

    # Metadata
    fetched_at: str | None = None  # ISO timestamp when permissions were fetched
    fetch_error: str | None = None  # Last error message if fetch failed

    # Additional attributes stored as dict
    extra_attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerPermissions":
        """Create from dictionary loaded from storage."""
        return cls(**data)

    def get_permissions_key(self) -> str:
        """Generate unique key for these permissions (actor_id:peer_id)."""
        return f"{self.actor_id}:{self.peer_id}"

    def validate(self) -> bool:
        """Validate the peer permissions definition."""
        if not self.actor_id or not isinstance(self.actor_id, str):
            return False
        if not self.peer_id or not isinstance(self.peer_id, str):
            return False
        return True

    def has_property_access(self, pattern: str, operation: str) -> bool | None:
        """
        Check if permission grants access to a property pattern.

        Args:
            pattern: Property name pattern to check
            operation: Operation (read, write, subscribe, delete)

        Returns:
            True if allowed, False if denied, None if no explicit permission
        """
        if not self.properties:
            return None

        # Check excluded patterns first (deny takes precedence)
        excluded = self.properties.get("excluded_patterns", [])
        for excl_pattern in excluded:
            if self._glob_match(pattern, excl_pattern):
                return False

        # Check allowed patterns
        patterns = self.properties.get("patterns", [])
        operations = self.properties.get("operations", [])

        if operation not in operations:
            return None

        for allowed_pattern in patterns:
            if self._glob_match(pattern, allowed_pattern):
                return True

        return None

    def has_method_access(self, method_name: str) -> bool | None:
        """
        Check if permission grants access to a method.

        Args:
            method_name: Method name to check

        Returns:
            True if allowed, False if denied, None if no explicit permission
        """
        if not self.methods:
            return None

        # Check denied first
        denied = self.methods.get("denied", [])
        for pattern in denied:
            if self._glob_match(method_name, pattern):
                return False

        # Check allowed
        allowed = self.methods.get("allowed", [])
        for pattern in allowed:
            if self._glob_match(method_name, pattern):
                return True

        return None

    def has_tool_access(self, tool_name: str) -> bool | None:
        """
        Check if permission grants access to a tool (MCP).

        Args:
            tool_name: Tool name to check

        Returns:
            True if allowed, False if denied, None if no explicit permission
        """
        if not self.tools:
            return None

        # Check denied first
        denied = self.tools.get("denied", [])
        for pattern in denied:
            if self._glob_match(tool_name, pattern):
                return False

        # Check allowed
        allowed = self.tools.get("allowed", [])
        for pattern in allowed:
            if self._glob_match(tool_name, pattern):
                return True

        return None

    def _glob_match(self, name: str, pattern: str) -> bool:
        """
        Simple glob pattern matching.

        Supports:
        - * matches any characters (zero or more)
        - ? matches single character

        Args:
            name: String to match
            pattern: Glob pattern

        Returns:
            True if name matches pattern
        """
        import fnmatch

        return fnmatch.fnmatch(name, pattern)


class PeerPermissionStore:
    """
    Storage manager for peer permission caching.

    Permissions are stored in actor-specific attribute buckets:
    bucket="_peer_permissions", actor_id={actor_id}, name="{actor_id}:{peer_id}"

    This follows the same pattern as PeerProfileStore for consistency.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self._cache: dict[str, PeerPermissions] = {}

    def _get_permissions_bucket(
        self, actor_id: str
    ) -> attribute.Attributes | None:
        """Get the peer permissions attribute bucket for an actor."""
        try:
            return attribute.Attributes(
                actor_id=actor_id, bucket=PEER_PERMISSIONS_BUCKET, config=self.config
            )
        except Exception as e:
            logger.error(
                f"Error accessing peer permissions bucket for actor {actor_id}: {e}"
            )
            return None

    def store_permissions(self, permissions: PeerPermissions) -> bool:
        """
        Store peer permissions with timestamp ordering.

        Only stores if the new permissions are newer than cached ones
        (based on fetched_at timestamp).
        """
        if not permissions.validate():
            logger.error(
                f"Invalid peer permissions definition: {permissions.get_permissions_key()}"
            )
            return False

        # Check timestamp ordering - reject older updates
        cache_key = f"{permissions.actor_id}:{permissions.peer_id}"
        existing = self._cache.get(cache_key)
        if existing and existing.fetched_at and permissions.fetched_at:
            if permissions.fetched_at < existing.fetched_at:
                logger.debug(
                    f"Ignoring older permission update for {cache_key}: "
                    f"{permissions.fetched_at} < {existing.fetched_at}"
                )
                return False

        bucket = self._get_permissions_bucket(permissions.actor_id)
        if not bucket:
            logger.error(
                f"Cannot access peer permissions bucket for actor {permissions.actor_id}"
            )
            return False

        try:
            # Store permissions data in attribute bucket
            perm_key = permissions.get_permissions_key()
            perm_data = permissions.to_dict()

            success = bucket.set_attr(name=perm_key, data=json.dumps(perm_data))

            if success:
                # Update cache
                self._cache[cache_key] = permissions
                logger.debug(f"Stored peer permissions: {cache_key}")
                return True
            else:
                logger.error(f"Failed to store peer permissions {perm_key}")
                return False

        except Exception as e:
            logger.error(
                f"Error storing peer permissions {permissions.get_permissions_key()}: {e}"
            )
            return False

    def get_permissions(
        self, actor_id: str, peer_id: str
    ) -> PeerPermissions | None:
        """Get cached peer permissions."""
        cache_key = f"{actor_id}:{peer_id}"

        # Check cache first
        if cache_key in self._cache:
            return self._cache[cache_key]

        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return None

        try:
            perm_key = f"{actor_id}:{peer_id}"

            # Get permissions from attribute bucket
            attr_data = bucket.get_attr(name=perm_key)

            if not attr_data or "data" not in attr_data:
                return None

            # Parse JSON and create PeerPermissions
            perm_data = json.loads(attr_data["data"])
            permissions = PeerPermissions.from_dict(perm_data)

            # Cache the result
            self._cache[cache_key] = permissions

            return permissions

        except Exception as e:
            logger.error(f"Error loading peer permissions {cache_key}: {e}")
            return None

    def delete_permissions(self, actor_id: str, peer_id: str) -> bool:
        """Delete cached peer permissions."""
        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return False

        try:
            perm_key = f"{actor_id}:{peer_id}"

            # Delete from attribute bucket
            success = bucket.delete_attr(name=perm_key)

            if success:
                # Remove from cache
                cache_key = f"{actor_id}:{peer_id}"
                self._cache.pop(cache_key, None)
                logger.debug(f"Deleted peer permissions: {cache_key}")
                return True
            else:
                logger.debug(f"No peer permissions to delete: {perm_key}")
                return False

        except Exception as e:
            logger.error(f"Error deleting peer permissions {actor_id}:{peer_id}: {e}")
            return False

    def list_actor_permissions(self, actor_id: str) -> list[PeerPermissions]:
        """List all cached peer permissions for an actor."""
        bucket = self._get_permissions_bucket(actor_id)
        if not bucket:
            return []

        permissions_list = []

        try:
            # Get all attributes from the peer permissions bucket
            bucket_data = bucket.get_bucket() or {}

            for attr_name, attr_info in bucket_data.items():
                try:
                    perm_data = json.loads(attr_info["data"])
                    permissions = PeerPermissions.from_dict(perm_data)
                    permissions_list.append(permissions)

                    # Cache while we're at it
                    cache_key = f"{permissions.actor_id}:{permissions.peer_id}"
                    self._cache[cache_key] = permissions

                except Exception as e:
                    logger.error(f"Error parsing peer permissions {attr_name}: {e}")
                    continue

            return permissions_list

        except Exception as e:
            logger.error(f"Error listing peer permissions for actor {actor_id}: {e}")
            return []

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()


# Singleton instance
_permission_store: PeerPermissionStore | None = None


def initialize_peer_permission_store(config: config_class.Config) -> None:
    """Initialize the peer permission store at application startup."""
    global _permission_store
    if _permission_store is None:
        logger.debug("Initializing peer permission store...")
        _permission_store = PeerPermissionStore(config)
        logger.debug("Peer permission store initialized")


def get_peer_permission_store(
    config: config_class.Config,
) -> PeerPermissionStore:
    """Get the singleton peer permission store.

    Automatically initializes the store if not already initialized.
    """
    global _permission_store
    if _permission_store is None:
        initialize_peer_permission_store(config)
    return _permission_store  # type: ignore[return-value]


def fetch_peer_permissions(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
) -> PeerPermissions:
    """
    Fetch permissions from a peer actor (sync version).

    Uses AwProxy to call the peer's /permissions/{actor_id} endpoint to get
    what permissions the peer has granted us.

    Args:
        actor_id: The actor requesting the permissions
        peer_id: The peer whose permissions to fetch
        config: Configuration object

    Returns:
        PeerPermissions with fetched data (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    permissions = PeerPermissions(
        actor_id=actor_id,
        peer_id=peer_id,
        fetched_at=datetime.now(UTC).isoformat(),
    )

    try:
        # Create proxy for peer communication
        peer_target = {
            "id": actor_id,
            "peerid": peer_id,
            "passphrase": None,
        }
        proxy = AwProxy(peer_target=peer_target, config=config)

        if not proxy.trust:
            permissions.fetch_error = "No trust relationship with peer"
            logger.warning(f"Cannot fetch peer permissions: no trust with {peer_id}")
            return permissions

        # Fetch permissions from peer's /permissions/{actor_id} endpoint
        response = proxy.get_resource(path=f"permissions/{actor_id}")

        if response is None:
            permissions.fetch_error = "Failed to communicate with peer"
            logger.warning(
                f"Failed to fetch peer permissions from {peer_id}: no response"
            )
            return permissions

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            permissions.fetch_error = f"Error {error_code}: {error_msg}"
            logger.warning(
                f"Failed to fetch peer permissions from {peer_id}: {permissions.fetch_error}"
            )
            return permissions

        # Extract permission data from response
        perm_data = response.get("permissions", response)

        # Map response to PeerPermissions fields
        if "properties" in perm_data:
            permissions.properties = perm_data["properties"]
        if "methods" in perm_data:
            permissions.methods = perm_data["methods"]
        if "actions" in perm_data:
            permissions.actions = perm_data["actions"]
        if "tools" in perm_data:
            permissions.tools = perm_data["tools"]
        if "resources" in perm_data:
            permissions.resources = perm_data["resources"]
        if "prompts" in perm_data:
            permissions.prompts = perm_data["prompts"]

        logger.debug(f"Successfully fetched peer permissions for {peer_id}")
        return permissions

    except Exception as e:
        permissions.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer permissions from {peer_id}: {e}")
        return permissions


async def fetch_peer_permissions_async(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
) -> PeerPermissions:
    """
    Fetch permissions from a peer actor (async version).

    Uses AwProxy.get_resource_async to call the peer's /permissions/{actor_id}
    endpoint without blocking the event loop.

    Args:
        actor_id: The actor requesting the permissions
        peer_id: The peer whose permissions to fetch
        config: Configuration object

    Returns:
        PeerPermissions with fetched data (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    permissions = PeerPermissions(
        actor_id=actor_id,
        peer_id=peer_id,
        fetched_at=datetime.now(UTC).isoformat(),
    )

    try:
        # Create proxy for peer communication
        peer_target = {
            "id": actor_id,
            "peerid": peer_id,
            "passphrase": None,
        }
        proxy = AwProxy(peer_target=peer_target, config=config)

        if not proxy.trust:
            permissions.fetch_error = "No trust relationship with peer"
            logger.warning(f"Cannot fetch peer permissions: no trust with {peer_id}")
            return permissions

        # Fetch permissions from peer's /permissions/{actor_id} endpoint (async)
        response = await proxy.get_resource_async(path=f"permissions/{actor_id}")

        if response is None:
            permissions.fetch_error = "Failed to communicate with peer"
            logger.warning(
                f"Failed to fetch peer permissions from {peer_id}: no response"
            )
            return permissions

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            permissions.fetch_error = f"Error {error_code}: {error_msg}"
            logger.warning(
                f"Failed to fetch peer permissions from {peer_id}: {permissions.fetch_error}"
            )
            return permissions

        # Extract permission data from response
        perm_data = response.get("permissions", response)

        # Map response to PeerPermissions fields
        if "properties" in perm_data:
            permissions.properties = perm_data["properties"]
        if "methods" in perm_data:
            permissions.methods = perm_data["methods"]
        if "actions" in perm_data:
            permissions.actions = perm_data["actions"]
        if "tools" in perm_data:
            permissions.tools = perm_data["tools"]
        if "resources" in perm_data:
            permissions.resources = perm_data["resources"]
        if "prompts" in perm_data:
            permissions.prompts = perm_data["prompts"]

        logger.debug(f"Successfully fetched peer permissions async for {peer_id}")
        return permissions

    except Exception as e:
        permissions.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer permissions async from {peer_id}: {e}")
        return permissions


def detect_revoked_property_patterns(
    old_permissions: PeerPermissions | None,
    new_permissions: PeerPermissions,
) -> list[str]:
    """
    Detect property patterns that were revoked between old and new permissions.

    A pattern is considered revoked if it was in the old permissions but is
    not in the new permissions.

    Args:
        old_permissions: Previous cached permissions (None if first callback)
        new_permissions: New permissions from callback

    Returns:
        List of property patterns that were revoked (empty if none)
    """
    if old_permissions is None:
        # No previous permissions, nothing was revoked
        return []

    old_props = old_permissions.properties or {}
    new_props = new_permissions.properties or {}

    old_patterns = set(old_props.get("patterns", []))
    new_patterns = set(new_props.get("patterns", []))

    # Patterns that were in old but not in new are revoked
    revoked = old_patterns - new_patterns

    return list(revoked)


def detect_permission_changes(
    old_permissions: PeerPermissions | None,
    new_permissions: PeerPermissions,
) -> dict[str, Any]:
    """
    Detect all permission changes between old and new permissions.

    Provides detailed information about what changed for lifecycle hooks.

    Args:
        old_permissions: Previous cached permissions (None if first callback)
        new_permissions: New permissions from callback

    Returns:
        Dict with change details:
        - is_initial: True if this is the first permission callback
        - revoked_patterns: List of property patterns that were revoked
        - granted_patterns: List of property patterns that were newly granted
        - has_revocations: True if any access was revoked
    """
    result: dict[str, Any] = {
        "is_initial": old_permissions is None,
        "revoked_patterns": [],
        "granted_patterns": [],
        "has_revocations": False,
    }

    if old_permissions is None:
        # First callback - everything is newly granted
        new_props = new_permissions.properties or {}
        result["granted_patterns"] = list(new_props.get("patterns", []))
        return result

    old_props = old_permissions.properties or {}
    new_props = new_permissions.properties or {}

    old_patterns = set(old_props.get("patterns", []))
    new_patterns = set(new_props.get("patterns", []))

    result["revoked_patterns"] = list(old_patterns - new_patterns)
    result["granted_patterns"] = list(new_patterns - old_patterns)
    result["has_revocations"] = len(result["revoked_patterns"]) > 0

    return result
