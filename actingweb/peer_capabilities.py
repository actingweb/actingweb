"""
Peer capability discovery and caching.

Provides an API to query what ActingWeb protocol features a peer supports.
Capabilities are stored in the trust relationship and cached with a TTL.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

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
                        version_response = await client.get(
                            version_url, timeout=5.0
                        )
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
