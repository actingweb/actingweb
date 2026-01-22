"""
Peer capability discovery and caching.

This module provides:
1. Protocol capability discovery - query what ActingWeb protocol features a peer supports
   (aw_supported options like subscriptionbatch, callbackcompression, etc.)
2. Methods/Actions caching - cache the RPC methods and state-modifying actions that
   peers expose via GET /methods and GET /actions endpoints

Protocol capabilities are stored in the trust relationship with TTL.
Methods/Actions are stored in a separate attribute bucket (peer_capabilities).
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from . import attribute
from . import config as config_class
from .constants import PEER_CAPABILITIES_BUCKET

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Cache TTL for capabilities (24 hours)
CAPABILITIES_TTL_HOURS = 24


class PeerCapabilities:
    """Query and cache peer's supported ActingWeb options.

    Capabilities are lazily fetched from the peer's /meta/actingweb/supported
    endpoint and cached in the trust relationship for the configured TTL.

    Usage:
        caps = PeerCapabilities(actor, peer_id)
        if caps.supports_batch_subscriptions():
            # Use batch endpoint
        else:
            # Fall back to individual requests

    Note:
        - Capabilities are fetched lazily on first access
        - Cache TTL is 24 hours by default
        - If fetch fails, methods return False (safe default)
    """

    def __init__(self, actor: "ActorInterface", peer_id: str) -> None:
        """Initialize peer capabilities.

        Args:
            actor: The actor querying peer capabilities
            peer_id: The peer's actor ID
        """
        self._actor = actor
        self._peer_id = peer_id
        self._trust: dict[str, Any] | None = None
        self._supported: set[str] = set()
        self._loaded = False

    def _load_trust(self) -> None:
        """Load trust data and parse supported options."""
        if self._loaded:
            return

        self._trust = self._actor.trust.get_trust(self._peer_id)
        if self._trust:
            aw_supported = self._trust.get("aw_supported") or ""
            self._supported = {
                opt.strip() for opt in aw_supported.split(",") if opt.strip()
            }
        self._loaded = True

    def _is_cache_valid(self) -> bool:
        """Check if cached capabilities are still valid."""
        self._load_trust()
        if not self._trust:
            return False

        fetched_at = self._trust.get("capabilities_fetched_at")
        if not fetched_at:
            return False

        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))

        # Ensure timezone-aware comparison
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        ttl = timedelta(hours=CAPABILITIES_TTL_HOURS)
        return now - fetched_at < ttl

    def supports(self, option: str) -> bool:
        """Check if peer supports a specific option tag.

        Args:
            option: Option tag (e.g., "subscriptionbatch", "callbackcompression")

        Returns:
            True if peer supports the option, False otherwise
        """
        self._load_trust()
        return option in self._supported

    def supports_batch_subscriptions(self) -> bool:
        """Check if peer supports batch subscription creation."""
        return self.supports("subscriptionbatch")

    def supports_compression(self) -> bool:
        """Check if peer supports callback compression."""
        return self.supports("callbackcompression")

    def supports_health_endpoint(self) -> bool:
        """Check if peer supports subscription health endpoint."""
        return self.supports("subscriptionhealth")

    def supports_resync_callbacks(self) -> bool:
        """Check if peer supports resync callback type."""
        return self.supports("subscriptionresync")

    def supports_stats_endpoint(self) -> bool:
        """Check if peer supports subscription stats endpoint."""
        return self.supports("subscriptionstats")

    def get_version(self) -> str | None:
        """Get peer's ActingWeb protocol version."""
        self._load_trust()
        if self._trust:
            return self._trust.get("aw_version")
        return None

    def get_all_supported(self) -> set[str]:
        """Get all supported option tags."""
        self._load_trust()
        return self._supported.copy()

    def refresh(self) -> bool:
        """Re-fetch capabilities from peer (synchronous).

        Makes HTTP requests to the peer's /meta/actingweb/supported and
        /meta/actingweb/version endpoints, then updates the trust relationship.

        For async contexts (FastAPI), use refresh_async() instead.

        Returns:
            True if capabilities were successfully fetched
        """
        self._load_trust()
        if not self._trust:
            logger.warning(
                f"Cannot refresh capabilities: no trust for peer {self._peer_id}"
            )
            return False

        baseuri = self._trust.get("baseuri", "")
        if not baseuri:
            logger.warning(
                f"Cannot refresh capabilities: no baseuri for peer {self._peer_id}"
            )
            return False

        try:
            with httpx.Client(timeout=10.0) as client:
                # Fetch supported options
                url = f"{baseuri}/meta/actingweb/supported"
                response = client.get(url)

                if response.status_code == 200:
                    supported = response.text.strip()
                    version = None

                    # Also fetch version
                    version_url = f"{baseuri}/meta/actingweb/version"
                    try:
                        version_response = client.get(version_url, timeout=5.0)
                        if version_response.status_code == 200:
                            version = version_response.text.strip()
                    except Exception:
                        pass  # Version is optional

                    # Update trust with capabilities
                    self._update_capabilities(supported, version)

                    logger.debug(
                        f"Refreshed capabilities for peer {self._peer_id}: {supported}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Failed to fetch capabilities from {self._peer_id}: "
                        f"{response.status_code}"
                    )
                    return False

        except httpx.RequestError as e:
            logger.warning(
                f"Network error fetching capabilities from {self._peer_id}: {e}"
            )
            return False
        except Exception as e:
            logger.error(f"Error fetching capabilities from {self._peer_id}: {e}")
            return False

    async def refresh_async(self) -> bool:
        """Re-fetch capabilities from peer (asynchronous).

        Makes HTTP requests to the peer's /meta/actingweb/supported and
        /meta/actingweb/version endpoints, then updates the trust relationship.

        Use this in async contexts (FastAPI handlers).

        Returns:
            True if capabilities were successfully fetched
        """
        self._load_trust()
        if not self._trust:
            logger.warning(
                f"Cannot refresh capabilities: no trust for peer {self._peer_id}"
            )
            return False

        baseuri = self._trust.get("baseuri", "")
        if not baseuri:
            logger.warning(
                f"Cannot refresh capabilities: no baseuri for peer {self._peer_id}"
            )
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Fetch supported options
                url = f"{baseuri}/meta/actingweb/supported"
                response = await client.get(url)

                if response.status_code == 200:
                    supported = response.text.strip()
                    version = None

                    # Also fetch version
                    version_url = f"{baseuri}/meta/actingweb/version"
                    try:
                        version_response = await client.get(version_url, timeout=5.0)
                        if version_response.status_code == 200:
                            version = version_response.text.strip()
                    except Exception:
                        pass  # Version is optional

                    # Update trust with capabilities
                    self._update_capabilities(supported, version)

                    logger.debug(
                        f"Refreshed capabilities for peer {self._peer_id}: {supported}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Failed to fetch capabilities from {self._peer_id}: "
                        f"{response.status_code}"
                    )
                    return False

        except httpx.RequestError as e:
            logger.warning(
                f"Network error fetching capabilities from {self._peer_id}: {e}"
            )
            return False
        except Exception as e:
            logger.error(f"Error fetching capabilities from {self._peer_id}: {e}")
            return False

    def _update_capabilities(self, supported: str, version: str | None) -> None:
        """Update trust with fetched capabilities and reload cache."""
        now_iso = datetime.now(UTC).isoformat()
        self._actor.trust.modify_trust(
            self._peer_id,
            aw_supported=supported,
            aw_version=version,
            capabilities_fetched_at=now_iso,
        )

        # Reload cache
        self._loaded = False
        self._load_trust()

    def ensure_loaded(self) -> None:
        """Ensure capabilities are loaded, fetching if necessary (synchronous).

        This is called lazily when capabilities are first accessed.
        Uses lazy fetch strategy to avoid blocking trust establishment.

        For async contexts, use ensure_loaded_async() instead.
        """
        if self._is_cache_valid():
            return

        # Capabilities not cached or expired - fetch them
        self.refresh()

    async def ensure_loaded_async(self) -> None:
        """Ensure capabilities are loaded, fetching if necessary (asynchronous).

        This is called lazily when capabilities are first accessed.
        Uses lazy fetch strategy to avoid blocking trust establishment.

        Use this in async contexts (FastAPI handlers).
        """
        if self._is_cache_valid():
            return

        # Capabilities not cached or expired - fetch them
        await self.refresh_async()


# =============================================================================
# Methods & Actions Caching
# =============================================================================
#
# The following classes provide first-class support for caching the methods
# and actions that peer actors expose via GET /methods and GET /actions.
# This is separate from protocol capabilities (aw_supported) above.
# =============================================================================


@dataclass
class CachedCapability:
    """
    Single method or action definition from a peer.

    This represents either a method (RPC-style function) or an action
    (state-modifying operation) that a peer actor exposes.
    """

    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None  # JSON Schema for parameters
    output_schema: dict[str, Any] | None = None  # JSON Schema for return value
    capability_type: str = "method"  # "method" or "action"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedCapability":
        """Create from dictionary loaded from storage."""
        return cls(**data)

    def validate(self) -> bool:
        """Validate the capability definition."""
        if not self.name or not isinstance(self.name, str):
            return False
        if self.capability_type not in ("method", "action"):
            return False
        return True


@dataclass
class CachedPeerCapabilities:
    """
    Cached methods and actions from a peer actor.

    This contains all capabilities (methods and actions) that a peer actor
    exposes, along with metadata about when they were fetched.
    """

    actor_id: str  # The actor caching this data
    peer_id: str  # The peer whose capabilities are cached

    # Cached capabilities
    methods: list[CachedCapability] = field(default_factory=list)
    actions: list[CachedCapability] = field(default_factory=list)

    # Metadata
    fetched_at: str | None = None  # ISO timestamp when capabilities were fetched
    fetch_error: str | None = None  # Last error message if fetch failed

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "actor_id": self.actor_id,
            "peer_id": self.peer_id,
            "methods": [m.to_dict() for m in self.methods],
            "actions": [a.to_dict() for a in self.actions],
            "fetched_at": self.fetched_at,
            "fetch_error": self.fetch_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedPeerCapabilities":
        """Create from dictionary loaded from storage."""
        methods = [CachedCapability.from_dict(m) for m in data.get("methods", []) if m]
        actions = [CachedCapability.from_dict(a) for a in data.get("actions", []) if a]
        return cls(
            actor_id=data["actor_id"],
            peer_id=data["peer_id"],
            methods=methods,
            actions=actions,
            fetched_at=data.get("fetched_at"),
            fetch_error=data.get("fetch_error"),
        )

    def get_capabilities_key(self) -> str:
        """Generate unique key for this capabilities entry (actor_id:peer_id)."""
        return f"{self.actor_id}:{self.peer_id}"

    def get_method(self, name: str) -> CachedCapability | None:
        """Get a method by name."""
        for method in self.methods:
            if method.name == name:
                return method
        return None

    def get_action(self, name: str) -> CachedCapability | None:
        """Get an action by name."""
        for action in self.actions:
            if action.name == name:
                return action
        return None

    def get_method_names(self) -> list[str]:
        """Get list of all method names."""
        return [m.name for m in self.methods]

    def get_action_names(self) -> list[str]:
        """Get list of all action names."""
        return [a.name for a in self.actions]

    def validate(self) -> bool:
        """Validate the peer capabilities definition."""
        if not self.actor_id or not isinstance(self.actor_id, str):
            return False
        if not self.peer_id or not isinstance(self.peer_id, str):
            return False
        # Validate all methods and actions
        for method in self.methods:
            if not method.validate():
                return False
        for action in self.actions:
            if not action.validate():
                return False
        return True


class CachedCapabilitiesStore:
    """
    Storage manager for peer methods/actions caching.

    Capabilities are stored in actor-specific attribute buckets:
    bucket="peer_capabilities", actor_id={actor_id}, name="{actor_id}:{peer_id}"

    This follows the same pattern as PeerProfileStore for consistency.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self._cache: dict[str, CachedPeerCapabilities] = {}

    def _get_capabilities_bucket(self, actor_id: str) -> attribute.Attributes | None:
        """Get the peer capabilities attribute bucket for an actor."""
        try:
            return attribute.Attributes(
                actor_id=actor_id,
                bucket=PEER_CAPABILITIES_BUCKET,
                config=self.config,
            )
        except Exception as e:
            logger.error(
                f"Error accessing peer capabilities bucket for actor {actor_id}: {e}"
            )
            return None

    def store_capabilities(self, capabilities: CachedPeerCapabilities) -> bool:
        """Store peer capabilities."""
        if not capabilities.validate():
            logger.error(
                f"Invalid peer capabilities definition: "
                f"{capabilities.get_capabilities_key()}"
            )
            return False

        bucket = self._get_capabilities_bucket(capabilities.actor_id)
        if not bucket:
            logger.error(
                f"Cannot access peer capabilities bucket for actor "
                f"{capabilities.actor_id}"
            )
            return False

        try:
            # Store capabilities data in attribute bucket
            capabilities_key = capabilities.get_capabilities_key()
            capabilities_data = capabilities.to_dict()

            success = bucket.set_attr(
                name=capabilities_key, data=json.dumps(capabilities_data)
            )

            if success:
                # Update cache
                cache_key = f"{capabilities.actor_id}:{capabilities.peer_id}"
                self._cache[cache_key] = capabilities
                logger.debug(f"Stored peer capabilities: {cache_key}")
                return True
            else:
                logger.error(f"Failed to store peer capabilities {capabilities_key}")
                return False

        except Exception as e:
            logger.error(
                f"Error storing peer capabilities "
                f"{capabilities.get_capabilities_key()}: {e}"
            )
            return False

    def get_capabilities(
        self, actor_id: str, peer_id: str
    ) -> CachedPeerCapabilities | None:
        """Get cached peer capabilities."""
        cache_key = f"{actor_id}:{peer_id}"

        # Check cache first
        if cache_key in self._cache:
            return self._cache[cache_key]

        bucket = self._get_capabilities_bucket(actor_id)
        if not bucket:
            return None

        try:
            capabilities_key = f"{actor_id}:{peer_id}"

            # Get capabilities from attribute bucket
            attr_data = bucket.get_attr(name=capabilities_key)

            if not attr_data or "data" not in attr_data:
                return None

            # Parse JSON and create CachedPeerCapabilities
            capabilities_data = json.loads(attr_data["data"])
            capabilities = CachedPeerCapabilities.from_dict(capabilities_data)

            # Cache the result
            self._cache[cache_key] = capabilities

            return capabilities

        except Exception as e:
            logger.error(f"Error loading peer capabilities {cache_key}: {e}")
            return None

    def delete_capabilities(self, actor_id: str, peer_id: str) -> bool:
        """Delete cached peer capabilities."""
        bucket = self._get_capabilities_bucket(actor_id)
        if not bucket:
            return False

        try:
            capabilities_key = f"{actor_id}:{peer_id}"

            # Delete from attribute bucket
            success = bucket.delete_attr(name=capabilities_key)

            if success:
                # Remove from cache
                cache_key = f"{actor_id}:{peer_id}"
                self._cache.pop(cache_key, None)
                logger.debug(f"Deleted peer capabilities: {cache_key}")
                return True
            else:
                logger.debug(f"No peer capabilities to delete: {capabilities_key}")
                return False

        except Exception as e:
            logger.error(f"Error deleting peer capabilities {actor_id}:{peer_id}: {e}")
            return False

    def list_actor_capabilities(self, actor_id: str) -> list[CachedPeerCapabilities]:
        """List all cached peer capabilities for an actor."""
        bucket = self._get_capabilities_bucket(actor_id)
        if not bucket:
            return []

        capabilities_list = []

        try:
            # Get all attributes from the peer capabilities bucket
            bucket_data = bucket.get_bucket() or {}

            for attr_name, attr_info in bucket_data.items():
                try:
                    capabilities_data = json.loads(attr_info["data"])
                    capabilities = CachedPeerCapabilities.from_dict(capabilities_data)
                    capabilities_list.append(capabilities)

                    # Cache while we're at it
                    cache_key = f"{capabilities.actor_id}:{capabilities.peer_id}"
                    self._cache[cache_key] = capabilities

                except Exception as e:
                    logger.error(f"Error parsing peer capabilities {attr_name}: {e}")
                    continue

            return capabilities_list

        except Exception as e:
            logger.error(f"Error listing peer capabilities for actor {actor_id}: {e}")
            return []

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()


# Singleton instance for methods/actions store
_capabilities_store: CachedCapabilitiesStore | None = None


def initialize_cached_capabilities_store(config: config_class.Config) -> None:
    """Initialize the cached capabilities store at application startup."""
    global _capabilities_store
    if _capabilities_store is None:
        logger.debug("Initializing cached capabilities store...")
        _capabilities_store = CachedCapabilitiesStore(config)
        logger.debug("Cached capabilities store initialized")


def get_cached_capabilities_store(
    config: config_class.Config,
) -> CachedCapabilitiesStore:
    """Get the singleton cached capabilities store.

    Automatically initializes the store if not already initialized.
    """
    global _capabilities_store
    if _capabilities_store is None:
        initialize_cached_capabilities_store(config)
    return _capabilities_store  # type: ignore[return-value]


def _parse_methods_response(response: dict[str, Any]) -> list[CachedCapability]:
    """Parse the response from GET /methods endpoint."""
    methods_data = response.get("methods", [])
    if not isinstance(methods_data, list):
        return []

    methods = []
    for method_data in methods_data:
        if not isinstance(method_data, dict):
            continue
        name = method_data.get("name")
        if not name:
            continue
        method = CachedCapability(
            name=name,
            description=method_data.get("description"),
            input_schema=method_data.get("input_schema"),
            output_schema=method_data.get("output_schema"),
            capability_type="method",
        )
        methods.append(method)
    return methods


def _parse_actions_response(response: dict[str, Any]) -> list[CachedCapability]:
    """Parse the response from GET /actions endpoint."""
    actions_data = response.get("actions", [])
    if not isinstance(actions_data, list):
        return []

    actions = []
    for action_data in actions_data:
        if not isinstance(action_data, dict):
            continue
        name = action_data.get("name")
        if not name:
            continue
        action = CachedCapability(
            name=name,
            description=action_data.get("description"),
            input_schema=action_data.get("input_schema"),
            output_schema=action_data.get("output_schema"),
            capability_type="action",
        )
        actions.append(action)
    return actions


def fetch_peer_methods_and_actions(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
) -> CachedPeerCapabilities:
    """
    Fetch capabilities (methods and actions) from a peer actor (sync version).

    Uses AwProxy to call the peer's /methods and /actions endpoints.

    Args:
        actor_id: The actor requesting the capabilities
        peer_id: The peer whose capabilities to fetch
        config: Configuration object

    Returns:
        CachedPeerCapabilities with fetched methods and actions
        (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    capabilities = CachedPeerCapabilities(
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
            capabilities.fetch_error = "No trust relationship with peer"
            logger.warning(f"Cannot fetch peer capabilities: no trust with {peer_id}")
            return capabilities

        # Track fetch errors - empty responses indicate non-JSON errors
        fetch_errors: list[str] = []

        # Fetch methods
        methods_response = proxy.get_resource(path="methods")
        if methods_response is None:
            fetch_errors.append("methods: no response")
        elif methods_response == {}:
            # Empty dict indicates non-JSON response (e.g., 401/403/500 HTML)
            fetch_errors.append("methods: invalid response (non-JSON)")
            logger.debug(f"Empty/non-JSON response fetching methods from {peer_id}")
        elif "error" in methods_response:
            error_code = methods_response["error"].get("code", 500)
            # 404 is OK - peer might not support methods
            if error_code != 404:
                fetch_errors.append(f"methods: error {error_code}")
                logger.debug(
                    f"Error fetching methods from {peer_id}: "
                    f"{methods_response['error']}"
                )
        else:
            capabilities.methods = _parse_methods_response(methods_response)

        # Fetch actions
        actions_response = proxy.get_resource(path="actions")
        if actions_response is None:
            fetch_errors.append("actions: no response")
        elif actions_response == {}:
            # Empty dict indicates non-JSON response (e.g., 401/403/500 HTML)
            fetch_errors.append("actions: invalid response (non-JSON)")
            logger.debug(f"Empty/non-JSON response fetching actions from {peer_id}")
        elif "error" in actions_response:
            error_code = actions_response["error"].get("code", 500)
            # 404 is OK - peer might not support actions
            if error_code != 404:
                fetch_errors.append(f"actions: error {error_code}")
                logger.debug(
                    f"Error fetching actions from {peer_id}: "
                    f"{actions_response['error']}"
                )
        else:
            capabilities.actions = _parse_actions_response(actions_response)

        # Set fetch_error if any errors occurred
        if fetch_errors:
            capabilities.fetch_error = "; ".join(fetch_errors)

        logger.debug(
            f"Successfully fetched peer capabilities for {peer_id}: "
            f"{len(capabilities.methods)} methods, "
            f"{len(capabilities.actions)} actions"
        )
        return capabilities

    except Exception as e:
        capabilities.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer capabilities from {peer_id}: {e}")
        return capabilities


async def fetch_peer_methods_and_actions_async(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
) -> CachedPeerCapabilities:
    """
    Fetch capabilities (methods and actions) from a peer actor (async version).

    Uses AwProxy.get_resource_async to call the peer's /methods and /actions
    endpoints without blocking the event loop.

    Args:
        actor_id: The actor requesting the capabilities
        peer_id: The peer whose capabilities to fetch
        config: Configuration object

    Returns:
        CachedPeerCapabilities with fetched methods and actions
        (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    capabilities = CachedPeerCapabilities(
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
            capabilities.fetch_error = "No trust relationship with peer"
            logger.warning(f"Cannot fetch peer capabilities: no trust with {peer_id}")
            return capabilities

        # Track fetch errors - empty responses indicate non-JSON errors
        fetch_errors: list[str] = []

        # Fetch methods (async)
        methods_response = await proxy.get_resource_async(path="methods")
        if methods_response is None:
            fetch_errors.append("methods: no response")
        elif methods_response == {}:
            # Empty dict indicates non-JSON response (e.g., 401/403/500 HTML)
            fetch_errors.append("methods: invalid response (non-JSON)")
            logger.debug(f"Empty/non-JSON response fetching methods from {peer_id}")
        elif "error" in methods_response:
            error_code = methods_response["error"].get("code", 500)
            # 404 is OK - peer might not support methods
            if error_code != 404:
                fetch_errors.append(f"methods: error {error_code}")
                logger.debug(
                    f"Error fetching methods from {peer_id}: "
                    f"{methods_response['error']}"
                )
        else:
            capabilities.methods = _parse_methods_response(methods_response)

        # Fetch actions (async)
        actions_response = await proxy.get_resource_async(path="actions")
        if actions_response is None:
            fetch_errors.append("actions: no response")
        elif actions_response == {}:
            # Empty dict indicates non-JSON response (e.g., 401/403/500 HTML)
            fetch_errors.append("actions: invalid response (non-JSON)")
            logger.debug(f"Empty/non-JSON response fetching actions from {peer_id}")
        elif "error" in actions_response:
            error_code = actions_response["error"].get("code", 500)
            # 404 is OK - peer might not support actions
            if error_code != 404:
                fetch_errors.append(f"actions: error {error_code}")
                logger.debug(
                    f"Error fetching actions from {peer_id}: "
                    f"{actions_response['error']}"
                )
        else:
            capabilities.actions = _parse_actions_response(actions_response)

        # Set fetch_error if any errors occurred
        if fetch_errors:
            capabilities.fetch_error = "; ".join(fetch_errors)

        logger.debug(
            f"Successfully fetched peer capabilities async for {peer_id}: "
            f"{len(capabilities.methods)} methods, "
            f"{len(capabilities.actions)} actions"
        )
        return capabilities

    except Exception as e:
        capabilities.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer capabilities async from {peer_id}: {e}")
        return capabilities
