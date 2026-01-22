"""
Peer Profile Caching for Trust Relationships.

This module provides first-class support for caching profile attributes from
peer actors that have trust relationships. It enables automatic fetching and
caching of peer profile data during trust establishment.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from . import attribute
from . import config as config_class
from .constants import PEER_PROFILES_BUCKET

logger = logging.getLogger(__name__)


@dataclass
class PeerProfile:
    """
    Cached profile attributes from a peer actor.

    Standard attributes (fetched from peer's /properties endpoint):
    - displayname: Human-readable name
    - email: Contact email
    - description: Actor description

    Additional attributes can be stored in extra_attributes dict.
    """

    actor_id: str  # The actor caching this profile
    peer_id: str  # The peer whose profile is cached

    # Standard attributes (fetched from peer's /properties)
    displayname: str | None = None
    email: str | None = None
    description: str | None = None

    # Additional configurable attributes stored as dict
    extra_attributes: dict[str, Any] = field(default_factory=dict)

    # Metadata
    fetched_at: str | None = None  # ISO timestamp when profile was fetched
    fetch_error: str | None = None  # Last error message if fetch failed

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerProfile":
        """Create from dictionary loaded from storage."""
        return cls(**data)

    def get_profile_key(self) -> str:
        """Generate unique key for this profile (actor_id:peer_id)."""
        return f"{self.actor_id}:{self.peer_id}"

    def get_attribute(self, name: str) -> Any | None:
        """Get an attribute by name.

        First checks standard attributes, then extra_attributes.
        """
        # Check standard attributes first
        if name == "displayname":
            return self.displayname
        elif name == "email":
            return self.email
        elif name == "description":
            return self.description
        # Check extra_attributes
        return self.extra_attributes.get(name)

    def set_attribute(self, name: str, value: Any) -> None:
        """Set an attribute by name.

        Sets standard attributes directly, others go to extra_attributes.
        """
        if name == "displayname":
            self.displayname = value
        elif name == "email":
            self.email = value
        elif name == "description":
            self.description = value
        else:
            self.extra_attributes[name] = value

    def validate(self) -> bool:
        """Validate the peer profile definition."""
        if not self.actor_id or not isinstance(self.actor_id, str):
            return False
        if not self.peer_id or not isinstance(self.peer_id, str):
            return False
        return True


class PeerProfileStore:
    """
    Storage manager for peer profile caching.

    Profiles are stored in actor-specific attribute buckets:
    bucket="peer_profiles", actor_id={actor_id}, name="{actor_id}:{peer_id}"

    This follows the same pattern as TrustPermissionStore for consistency.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self._cache: dict[str, PeerProfile] = {}

    def _get_profiles_bucket(self, actor_id: str) -> attribute.Attributes | None:
        """Get the peer profiles attribute bucket for an actor."""
        try:
            return attribute.Attributes(
                actor_id=actor_id, bucket=PEER_PROFILES_BUCKET, config=self.config
            )
        except Exception as e:
            logger.error(
                f"Error accessing peer profiles bucket for actor {actor_id}: {e}"
            )
            return None

    def store_profile(self, profile: PeerProfile) -> bool:
        """Store a peer profile."""
        if not profile.validate():
            logger.error(
                f"Invalid peer profile definition: {profile.get_profile_key()}"
            )
            return False

        bucket = self._get_profiles_bucket(profile.actor_id)
        if not bucket:
            logger.error(
                f"Cannot access peer profiles bucket for actor {profile.actor_id}"
            )
            return False

        try:
            # Store profile data in attribute bucket
            profile_key = profile.get_profile_key()
            profile_data = profile.to_dict()

            success = bucket.set_attr(
                name=profile_key, data=json.dumps(profile_data)
            )

            if success:
                # Update cache
                cache_key = f"{profile.actor_id}:{profile.peer_id}"
                self._cache[cache_key] = profile
                logger.debug(f"Stored peer profile: {cache_key}")
                return True
            else:
                logger.error(f"Failed to store peer profile {profile_key}")
                return False

        except Exception as e:
            logger.error(
                f"Error storing peer profile {profile.get_profile_key()}: {e}"
            )
            return False

    def get_profile(self, actor_id: str, peer_id: str) -> PeerProfile | None:
        """Get a cached peer profile."""
        cache_key = f"{actor_id}:{peer_id}"

        # Check cache first
        if cache_key in self._cache:
            return self._cache[cache_key]

        bucket = self._get_profiles_bucket(actor_id)
        if not bucket:
            return None

        try:
            profile_key = f"{actor_id}:{peer_id}"

            # Get profile from attribute bucket
            attr_data = bucket.get_attr(name=profile_key)

            if not attr_data or "data" not in attr_data:
                return None

            # Parse JSON and create PeerProfile
            profile_data = json.loads(attr_data["data"])
            profile = PeerProfile.from_dict(profile_data)

            # Cache the result
            self._cache[cache_key] = profile

            return profile

        except Exception as e:
            logger.error(f"Error loading peer profile {cache_key}: {e}")
            return None

    def delete_profile(self, actor_id: str, peer_id: str) -> bool:
        """Delete a cached peer profile."""
        bucket = self._get_profiles_bucket(actor_id)
        if not bucket:
            return False

        try:
            profile_key = f"{actor_id}:{peer_id}"

            # Delete from attribute bucket
            success = bucket.delete_attr(name=profile_key)

            if success:
                # Remove from cache
                cache_key = f"{actor_id}:{peer_id}"
                self._cache.pop(cache_key, None)
                logger.debug(f"Deleted peer profile: {cache_key}")
                return True
            else:
                logger.debug(f"No peer profile to delete: {profile_key}")
                return False

        except Exception as e:
            logger.error(f"Error deleting peer profile {actor_id}:{peer_id}: {e}")
            return False

    def list_actor_profiles(self, actor_id: str) -> list[PeerProfile]:
        """List all cached peer profiles for an actor."""
        bucket = self._get_profiles_bucket(actor_id)
        if not bucket:
            return []

        profiles_list = []

        try:
            # Get all attributes from the peer profiles bucket
            bucket_data = bucket.get_bucket() or {}

            for attr_name, attr_info in bucket_data.items():
                try:
                    profile_data = json.loads(attr_info["data"])
                    profile = PeerProfile.from_dict(profile_data)
                    profiles_list.append(profile)

                    # Cache while we're at it
                    cache_key = f"{profile.actor_id}:{profile.peer_id}"
                    self._cache[cache_key] = profile

                except Exception as e:
                    logger.error(f"Error parsing peer profile {attr_name}: {e}")
                    continue

            return profiles_list

        except Exception as e:
            logger.error(f"Error listing peer profiles for actor {actor_id}: {e}")
            return []

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()


# Singleton instance
_profile_store: PeerProfileStore | None = None


def initialize_peer_profile_store(config: config_class.Config) -> None:
    """Initialize the peer profile store at application startup."""
    global _profile_store
    if _profile_store is None:
        logger.debug("Initializing peer profile store...")
        _profile_store = PeerProfileStore(config)
        logger.debug("Peer profile store initialized")


def get_peer_profile_store(
    config: config_class.Config,
) -> PeerProfileStore:
    """Get the singleton peer profile store.

    Automatically initializes the store if not already initialized.
    """
    global _profile_store
    if _profile_store is None:
        initialize_peer_profile_store(config)
    return _profile_store  # type: ignore[return-value]


def fetch_peer_profile(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
    attributes: list[str],
) -> PeerProfile:
    """
    Fetch profile attributes from a peer actor (sync version).

    Uses AwProxy to call the peer's /properties endpoint and extract
    configured attributes.

    Args:
        actor_id: The actor requesting the profile
        peer_id: The peer whose profile to fetch
        config: Configuration object
        attributes: List of attribute names to fetch

    Returns:
        PeerProfile with fetched attributes (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    profile = PeerProfile(
        actor_id=actor_id,
        peer_id=peer_id,
        fetched_at=datetime.utcnow().isoformat(),
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
            profile.fetch_error = "No trust relationship with peer"
            logger.warning(
                f"Cannot fetch peer profile: no trust with {peer_id}"
            )
            return profile

        # Fetch all properties at once
        response = proxy.get_resource(path="properties")

        if response is None:
            profile.fetch_error = "Failed to communicate with peer"
            logger.warning(
                f"Failed to fetch peer profile from {peer_id}: no response"
            )
            return profile

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            profile.fetch_error = f"Error {error_code}: {error_msg}"
            logger.warning(
                f"Failed to fetch peer profile from {peer_id}: {profile.fetch_error}"
            )
            return profile

        # Extract requested attributes
        properties = response.get("properties", response)
        if isinstance(properties, list):
            # Convert list format to dict
            props_dict = {}
            for prop in properties:
                if isinstance(prop, dict) and "name" in prop:
                    props_dict[prop["name"]] = prop.get("value")
            properties = props_dict

        for attr_name in attributes:
            value = properties.get(attr_name)
            if value is not None:
                profile.set_attribute(attr_name, value)

        logger.debug(
            f"Successfully fetched peer profile for {peer_id} with "
            f"{len([a for a in attributes if profile.get_attribute(a) is not None])} attributes"
        )
        return profile

    except Exception as e:
        profile.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer profile from {peer_id}: {e}")
        return profile


async def fetch_peer_profile_async(
    actor_id: str,
    peer_id: str,
    config: config_class.Config,
    attributes: list[str],
) -> PeerProfile:
    """
    Fetch profile attributes from a peer actor (async version).

    Uses AwProxy.get_resource_async to call the peer's /properties endpoint
    without blocking the event loop.

    Args:
        actor_id: The actor requesting the profile
        peer_id: The peer whose profile to fetch
        config: Configuration object
        attributes: List of attribute names to fetch

    Returns:
        PeerProfile with fetched attributes (or error info if fetch failed)
    """
    from .aw_proxy import AwProxy

    profile = PeerProfile(
        actor_id=actor_id,
        peer_id=peer_id,
        fetched_at=datetime.utcnow().isoformat(),
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
            profile.fetch_error = "No trust relationship with peer"
            logger.warning(
                f"Cannot fetch peer profile: no trust with {peer_id}"
            )
            return profile

        # Fetch all properties at once (async)
        response = await proxy.get_resource_async(path="properties")

        if response is None:
            profile.fetch_error = "Failed to communicate with peer"
            logger.warning(
                f"Failed to fetch peer profile from {peer_id}: no response"
            )
            return profile

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            profile.fetch_error = f"Error {error_code}: {error_msg}"
            logger.warning(
                f"Failed to fetch peer profile from {peer_id}: {profile.fetch_error}"
            )
            return profile

        # Extract requested attributes
        properties = response.get("properties", response)
        if isinstance(properties, list):
            # Convert list format to dict
            props_dict = {}
            for prop in properties:
                if isinstance(prop, dict) and "name" in prop:
                    props_dict[prop["name"]] = prop.get("value")
            properties = props_dict

        for attr_name in attributes:
            value = properties.get(attr_name)
            if value is not None:
                profile.set_attribute(attr_name, value)

        logger.debug(
            f"Successfully fetched peer profile async for {peer_id} with "
            f"{len([a for a in attributes if profile.get_attribute(a) is not None])} attributes"
        )
        return profile

    except Exception as e:
        profile.fetch_error = f"Exception: {str(e)}"
        logger.error(f"Exception fetching peer profile async from {peer_id}: {e}")
        return profile
