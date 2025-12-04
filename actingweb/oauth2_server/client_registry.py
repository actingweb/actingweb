"""
MCP Client Registry for dynamic client registration and management.

This module handles registration of MCP clients (like ChatGPT) that need OAuth2
credentials to authenticate with ActingWeb. Client credentials are stored
per-actor but clients are not treated as actors themselves.
"""

import logging
import secrets
import time
from typing import Any

from .. import attribute
from .. import config as config_class
from ..constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR

logger = logging.getLogger(__name__)


class MCPClientRegistry:
    """
    Registry for MCP clients with per-actor storage.

    This class manages dynamic client registration (RFC 7591) for MCP clients,
    storing credentials in actor properties rather than treating clients as actors.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        # Use Attributes system for private storage instead of underscore properties
        self.clients_bucket = "mcp_clients"  # Private attribute bucket for client data

    def register_client(
        self, actor_id: str, registration_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Register an MCP client for a specific actor and create corresponding trust relationship.

        This integrates OAuth2 client registration with ActingWeb's trust system,
        ensuring that clients are properly authenticated and authorized.

        Args:
            actor_id: The actor this client will be associated with
            registration_data: Client registration request data

        Returns:
            Client registration response per RFC 7591
        """
        # Generate client credentials
        client_id = f"mcp_{secrets.token_hex(16)}"
        client_secret = secrets.token_urlsafe(32)

        # Validate required fields
        client_name = registration_data.get("client_name")
        if not client_name:
            raise ValueError("client_name is required")

        # Prepare client data
        client_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": registration_data.get("redirect_uris", []),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "trust_type": registration_data.get("trust_type", "mcp_client"),
            "created_at": int(time.time()),
            "actor_id": actor_id,
        }

        # Store client in actor properties
        logger.debug(f"register_client: storing client_id={client_id} for actor_id={actor_id}")
        self._store_client(actor_id, client_id, client_data)

        # Update global index
        logger.debug(f"register_client: updating global index client_id={client_id} -> actor_id={actor_id}")
        self._update_global_index(client_id, actor_id)

        # Create corresponding trust relationship for this OAuth2 client
        self._create_client_trust_relationship(actor_id, client_id, client_data)

        # Return registration response
        base_url = f"{self.config.proto}{self.config.fqdn}"
        response = {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": client_data["redirect_uris"],
            "grant_types": client_data["grant_types"],
            "response_types": client_data["response_types"],
            "token_endpoint_auth_method": client_data["token_endpoint_auth_method"],
            "trust_type": client_data["trust_type"],
            "created_at": client_data["created_at"],
            "client_id_issued_at": client_data["created_at"],
            "actor_id": client_data["actor_id"],
            # OAuth2 endpoints
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "issuer": base_url,
        }

        logger.debug(f"Registered MCP client {client_id} for actor {actor_id}")
        return response

    def validate_client(
        self, client_id: str, client_secret: str | None = None
    ) -> dict[str, Any] | None:
        """
        Validate client credentials.

        Args:
            client_id: Client identifier
            client_secret: Client secret (optional for public clients)

        Returns:
            Client data if valid, None otherwise
        """
        client_data = self._load_client(client_id)
        if not client_data:
            return None

        # For confidential clients, validate secret
        if client_secret is not None:
            stored_secret = client_data.get("client_secret")
            if stored_secret != client_secret:
                logger.warning(f"Invalid client secret for client {client_id}")
                logger.debug(
                    f"Client secret validation failed - Expected length: {len(stored_secret) if stored_secret else 0}, Provided length: {len(client_secret)}"
                )
                logger.debug(
                    f"Client last regenerated: {client_data.get('secret_regenerated_at', 'Never')}"
                )
                return None
            else:
                logger.debug(f"Client secret validation successful for {client_id}")
                if client_data.get("secret_regenerated_at"):
                    logger.debug(
                        f"Using regenerated secret from {client_data.get('secret_regenerated_at')}"
                    )

        return client_data

    def validate_redirect_uri(self, client_id: str, redirect_uri: str) -> bool:
        """
        Validate redirect URI for a client.

        Args:
            client_id: Client identifier
            redirect_uri: Redirect URI to validate

        Returns:
            True if URI is valid for this client
        """
        client_data = self._load_client(client_id)
        if not client_data:
            return False

        registered_uris = client_data.get("redirect_uris", [])
        return redirect_uri in registered_uris

    def get_client_actor_id(self, client_id: str) -> str | None:
        """
        Get the actor ID associated with a client.

        Args:
            client_id: Client identifier

        Returns:
            Actor ID or None if client not found
        """
        client_data = self._load_client(client_id)
        return client_data.get("actor_id") if client_data else None

    def list_clients_for_actor(self, actor_id: str) -> list[dict[str, Any]]:
        """
        List all clients registered for an actor.

        Args:
            actor_id: Actor identifier

        Returns:
            List of client data dictionaries
        """
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )

            # Get all client attributes from the bucket
            bucket_data = bucket.get_bucket()
            if not bucket_data:
                return []

            # Extract the actual client data from each attribute
            clients = []
            for attr_data in bucket_data.values():
                if attr_data and "data" in attr_data:
                    clients.append(attr_data["data"])
            return clients

        except Exception as e:
            logger.error(f"Error listing clients for actor {actor_id}: {e}")
            return []

    def delete_client(self, client_id: str, actor_id: str | None = None) -> bool:
        """
        Delete an OAuth2 client and revoke all its tokens.

        This method performs a complete cleanup:
        1. Revokes all access and refresh tokens for the client
        2. Deletes the client from actor's bucket
        3. Deletes the client from global index
        4. Deletes the corresponding trust relationship

        Args:
            client_id: Client identifier to delete
            actor_id: Optional actor ID where tokens are stored. If provided, this
                      takes precedence over the actor_id in client_data. This is
                      important when called from Trust.delete() which has the
                      authoritative actor_id for the trust relationship.

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # First find the client to get metadata (and actor_id if not provided)
            client_data = self._load_client(client_id)
            if not client_data:
                logger.warning(f"Client {client_id} not found for deletion")
                return False

            # Use provided actor_id if available, otherwise fall back to client_data
            # The provided actor_id takes precedence because it comes from the
            # trust relationship which is the authoritative source for token storage
            client_data_actor_id = client_data.get("actor_id")
            if not actor_id:
                actor_id = client_data_actor_id
            if not actor_id:
                logger.error(f"No actor_id found for client {client_id}")
                return False

            # Revoke all tokens for this client to terminate access immediately
            from .token_manager import get_actingweb_token_manager
            token_manager = get_actingweb_token_manager(self.config)
            revoked_count = token_manager.revoke_client_tokens(actor_id, client_id)
            logger.info(f"Revoked {revoked_count} tokens for client {client_id}")

            # Delete from actor's bucket
            bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )
            bucket.delete_attr(name=client_id)

            # Delete from global index
            try:
                global_bucket = attribute.Attributes(
                    actor_id=OAUTH2_SYSTEM_ACTOR,
                    bucket=CLIENT_INDEX_BUCKET,
                    config=self.config,
                )
                global_bucket.delete_attr(name=client_id)
            except Exception as e:
                logger.warning(
                    f"Failed to remove client {client_id} from global index: {e}"
                )

            # Delete corresponding trust relationship
            self._delete_client_trust_relationship(actor_id, client_id)

            logger.info(
                f"Successfully deleted OAuth2 client {client_id} for actor {actor_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Error deleting client {client_id}: {e}")
            return False

    def _store_client(
        self, actor_id: str, client_id: str, client_data: dict[str, Any]
    ) -> None:
        """Store client data using ActingWeb attributes bucket."""
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )

            # Store client data in the bucket
            logger.debug(
                f"Storing client {client_id} in mcp_clients bucket for actor {actor_id}"
            )
            bucket.set_attr(name=client_id, data=client_data)
            logger.debug("Successfully stored client data")

        except Exception as e:
            logger.error(f"Error storing client {client_id} for actor {actor_id}: {e}")
            raise

    def _load_client(self, client_id: str) -> dict[str, Any] | None:
        """Load client data by searching all actors."""
        try:
            # Extract actor ID from client data if we can find it
            # This is a simplified search - in production you might want to index this

            # For now, we'll need to search through actors
            # This is not efficient but works for the implementation
            # In production, you might want to maintain a separate client index

            # Try to find the client by searching through actor properties
            # Since we don't have a direct way to search all actors efficiently,
            # we'll implement a basic search pattern

            # The client_id contains the actor context in our implementation
            # We can optimize this later with proper indexing

            client_data: dict[str, Any] | None = self._search_client_in_actors(
                client_id
            )
            return client_data

        except Exception as e:
            logger.error(f"Error loading client {client_id}: {e}")
            return None

    def _search_client_in_actors(self, client_id: str) -> dict[str, Any] | None:
        """
        Search for client across actors.

        This is a basic implementation. In production, you would want to:
        1. Maintain a client ID -> actor ID index
        2. Use database queries for efficient lookup
        3. Cache frequently accessed clients
        """
        # For now, we'll implement a basic search
        # This method would need to be optimized for production use

        # Since we don't have an efficient way to search all actors,
        # we'll implement a property-based approach where we store
        # a global client index as well

        return self._load_from_global_index(client_id)

    def _load_from_global_index(self, client_id: str) -> dict[str, Any] | None:
        """Load client from a global index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=self.config,
            )

            # Get the actor ID for this client
            actor_id_attr = global_bucket.get_attr(name=client_id)
            if not actor_id_attr or "data" not in actor_id_attr:
                logger.debug(f"_load_from_global_index: client_id={client_id} not found in global index")
                return None

            actor_id = actor_id_attr["data"]
            logger.debug(f"_load_from_global_index: client_id={client_id} -> actor_id={actor_id} from global index")
            if not actor_id:
                return None

            # Load the actual client data from the actor's bucket
            client_bucket = attribute.Attributes(
                actor_id=actor_id, bucket="mcp_clients", config=self.config
            )
            client_attr = client_bucket.get_attr(name=client_id)
            if not client_attr or "data" not in client_attr:
                return None

            client_data: dict[str, Any] = client_attr["data"]
            logger.debug(f"_load_from_global_index: loaded client_data for {client_id}, client_data.actor_id={client_data.get('actor_id')}")

            return client_data

        except Exception as e:
            logger.error(f"Error loading client from global index: {e}")
            return None

    def _create_client_trust_relationship(
        self, actor_id: str, client_id: str, client_data: dict[str, Any]
    ) -> None:
        """
        Create a trust relationship for the OAuth2 client.

        This ensures that OAuth2 clients are integrated into ActingWeb's trust system
        and subject to permission evaluation.

        Args:
            actor_id: Actor this client belongs to
            client_id: OAuth2 client ID
            client_data: Client registration data
        """
        try:
            from .. import actor as actor_module
            from ..interface.actor_interface import ActorInterface
            from ..interface.trust_manager import TrustManager

            # Load the actor
            core_actor = actor_module.Actor(actor_id, config=self.config)
            if not core_actor.actor:
                logger.error(
                    f"Cannot create trust relationship - actor {actor_id} not found"
                )
                return

            # Create ActorInterface wrapper
            registry = getattr(self.config, "service_registry", None)
            actor_interface = ActorInterface(
                core_actor=core_actor, service_registry=registry
            )
            trust_manager = TrustManager(core_actor)

            # Create trust relationship using OAuth2 client credentials flow
            # Use client_id as the "email" identifier for this trust type
            trust_created = trust_manager.create_or_update_oauth_trust(
                email=client_id,  # Use client_id as identifier
                trust_type=client_data.get("trust_type", "mcp_client"),
                oauth_tokens={
                    "client_id": client_id,
                    "client_secret": client_data["client_secret"],
                    "grant_type": "client_credentials",
                    "created_at": client_data["created_at"],
                },
                established_via="oauth2_client",  # OAuth2 client credentials flow (not interactive)
                client_id=client_id,  # Ensure unique peer ID per client
                client_name=client_data.get("client_name"),
            )

            if trust_created:
                logger.info(f"Created trust relationship for OAuth2 client {client_id}")

                # Store client metadata in the trust relationship
                # Find the newly created trust relationship and add client metadata
                trust_relationship = None
                for trust in actor_interface.trust.relationships:
                    if hasattr(trust, "peerid") and client_id in trust.peerid:
                        trust_relationship = trust
                        break

                if trust_relationship:
                    # Store client metadata in trust relationship
                    trust_desc = (
                        f"OAuth2 Client: {client_data.get('client_name', client_id)}"
                    )
                    logger.debug(
                        f"Enhanced trust relationship for OAuth2 client: {trust_desc}"
                    )
            else:
                logger.error(
                    f"Failed to create trust relationship for OAuth2 client {client_id}"
                )

        except Exception as e:
            logger.error(
                f"Error creating trust relationship for client {client_id}: {e}"
            )
            # Don't raise - client registration can continue without trust relationship

    def _delete_client_trust_relationship(self, actor_id: str, client_id: str) -> None:
        """
        Delete the trust relationship for an OAuth2 client.

        Args:
            actor_id: Actor this client belongs to
            client_id: OAuth2 client ID
        """
        try:
            from .. import actor as actor_module
            from ..interface.actor_interface import ActorInterface

            # Load the actor
            core_actor = actor_module.Actor(actor_id, config=self.config)
            if not core_actor.actor:
                logger.error(
                    f"Cannot delete trust relationship - actor {actor_id} not found"
                )
                return

            # Create ActorInterface wrapper
            registry = getattr(self.config, "service_registry", None)
            actor_interface = ActorInterface(
                core_actor=core_actor, service_registry=registry
            )

            # Find and delete the trust relationship for this client
            # The peer ID should be in format "oauth2_client:client_id"
            expected_peer_patterns = [
                f"oauth2_client:{client_id}",  # New format
                f"oauth2:{client_id}",  # Alternative format
                client_id,  # Direct client_id match
            ]

            deleted = False
            for trust in actor_interface.trust.relationships:
                if hasattr(trust, "peerid"):
                    peer_id = trust.peerid
                    # Check if this trust relationship belongs to our client
                    for pattern in expected_peer_patterns:
                        if pattern in peer_id or peer_id.endswith(client_id):
                            try:
                                # Delete the trust relationship
                                success = actor_interface.trust.delete_relationship(
                                    peer_id
                                )
                                if success:
                                    logger.info(
                                        f"Deleted trust relationship for OAuth2 client {client_id}: {peer_id}"
                                    )
                                    deleted = True
                                    break
                                else:
                                    logger.warning(
                                        f"Failed to delete trust relationship {peer_id} for client {client_id}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error deleting trust relationship {peer_id} for client {client_id}: {e}"
                                )

                if deleted:
                    break

            if not deleted:
                logger.warning(
                    f"No trust relationship found to delete for OAuth2 client {client_id}"
                )

        except Exception as e:
            logger.error(
                f"Error deleting trust relationship for client {client_id}: {e}"
            )
            # Don't raise - client deletion can continue

    def _update_global_index(self, client_id: str, actor_id: str) -> None:
        """Update the global client index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=self.config,
            )

            # Store the client_id -> actor_id mapping
            global_bucket.set_attr(name=client_id, data=actor_id)
            logger.debug(f"Updated global index: {client_id} -> {actor_id}")

        except Exception as e:
            logger.error(f"Error updating global client index: {e}")
            raise


# Global registry instance
_client_registry: MCPClientRegistry | None = None


def get_mcp_client_registry(config: config_class.Config) -> MCPClientRegistry:
    """Get or create the global MCP client registry."""
    global _client_registry
    if _client_registry is None:
        _client_registry = MCPClientRegistry(config)
    return _client_registry
