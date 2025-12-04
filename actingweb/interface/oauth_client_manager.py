"""
OAuth2 Client Manager Interface for ActingWeb.

This module provides a high-level, developer-friendly interface for managing
OAuth2 clients associated with ActingWeb actors. It follows the same patterns
as other ActingWeb interfaces like TrustManager and PropertyStore.
"""

import logging
import time
from datetime import datetime
from typing import Any

from ..oauth2_server.client_registry import MCPClientRegistry

logger = logging.getLogger(__name__)


class OAuth2ClientManager:
    """
    High-level interface for managing OAuth2 clients.

    This class provides a clean, developer-friendly API for OAuth2 client
    operations while abstracting away the underlying client registry complexity.
    """

    def __init__(self, actor_id: str, config):
        """
        Initialize OAuth2 Client Manager for a specific actor.

        Args:
            actor_id: The actor ID this manager is associated with
            config: ActingWeb configuration object
        """
        self.actor_id = actor_id
        self.config = config
        self._registry = MCPClientRegistry(config)

    def create_client(
        self, client_name: str, trust_type: str = "mcp_client", **kwargs
    ) -> dict[str, Any]:
        """
        Create a new OAuth2 client for this actor.

        Args:
            client_name: Human-readable name for the client
            trust_type: Trust type for permission inheritance
            **kwargs: Additional client configuration

        Returns:
            Dictionary containing client credentials and metadata

        Example:
            >>> client_manager = OAuth2ClientManager(actor_id, config)
            >>> client = client_manager.create_client("My AI Assistant")
            >>> print(f"Client ID: {client['client_id']}")
        """
        try:
            # Prepare registration data following RFC 7591
            registration_data = {
                "client_name": client_name,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "mcp",
                "token_endpoint_auth_method": "client_secret_post",
                "trust_type": trust_type,
                **kwargs,
            }

            logger.info(
                f"Creating OAuth2 client '{client_name}' for actor {self.actor_id}"
            )

            client_data = self._registry.register_client(
                self.actor_id, registration_data
            )

            if client_data:
                # Add formatted creation time for convenience
                if "created_at" in client_data and isinstance(
                    client_data["created_at"], (int, float)
                ):
                    client_data["created_at_formatted"] = datetime.fromtimestamp(
                        client_data["created_at"]
                    ).strftime("%Y-%m-%d %H:%M")

                logger.info(f"OAuth2 client created: {client_data.get('client_id')}")
                return client_data
            else:
                raise ValueError("Failed to register OAuth2 client - no data returned")

        except Exception as e:
            logger.error(f"Error creating OAuth2 client: {e}")
            raise

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        """
        Get details for a specific OAuth2 client.

        Args:
            client_id: The client identifier

        Returns:
            Client data dictionary or None if not found
        """
        try:
            client_data = self._registry._load_client(client_id)

            # Verify client belongs to this actor
            if client_data and client_data.get("actor_id") == self.actor_id:
                return client_data
            return None

        except Exception as e:
            logger.error(f"Error retrieving OAuth2 client {client_id}: {e}")
            return None

    def list_clients(self) -> list[dict[str, Any]]:
        """
        List all OAuth2 clients for this actor.

        Returns:
            List of client data dictionaries with formatted metadata
        """
        try:
            clients = self._registry.list_clients_for_actor(self.actor_id)

            # Add formatted metadata for convenience
            for client in clients:
                if "created_at" in client and isinstance(
                    client["created_at"], (int, float)
                ):
                    client["created_at_formatted"] = datetime.fromtimestamp(
                        client["created_at"]
                    ).strftime("%Y-%m-%d %H:%M")

                # Add display-friendly status
                client["status"] = (
                    "active"  # Could be enhanced with actual status checking
                )

            return clients

        except Exception as e:
            logger.error(f"Error listing OAuth2 clients for actor {self.actor_id}: {e}")
            return []

    def delete_client(self, client_id: str) -> bool:
        """
        Delete an OAuth2 client.

        Args:
            client_id: The client identifier to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # Verify client belongs to this actor before deletion
            client_data = self._registry._load_client(client_id)
            if not client_data:
                logger.warning(f"OAuth2 client {client_id} not found for deletion")
                return False

            if client_data.get("actor_id") != self.actor_id:
                logger.error(
                    f"OAuth2 client {client_id} does not belong to actor {self.actor_id}"
                )
                return False

            # Pass actor_id explicitly for consistency and to ensure token
            # revocation happens in the correct actor context
            success = self._registry.delete_client(client_id, actor_id=self.actor_id)

            if success:
                logger.info(f"OAuth2 client {client_id} deleted successfully")
            else:
                logger.error(f"Failed to delete OAuth2 client {client_id}")

            return success

        except Exception as e:
            logger.error(f"Error deleting OAuth2 client {client_id}: {e}")
            return False

    def validate_client(self, client_id: str, client_secret: str | None = None) -> bool:
        """
        Validate OAuth2 client credentials.

        Args:
            client_id: The client identifier
            client_secret: The client secret (optional for public clients)

        Returns:
            True if client is valid, False otherwise
        """
        try:
            client_data = self._registry.validate_client(client_id, client_secret)
            return (
                client_data is not None and client_data.get("actor_id") == self.actor_id
            )

        except Exception as e:
            logger.error(f"Error validating OAuth2 client {client_id}: {e}")
            return False

    def regenerate_client_secret(self, client_id: str) -> dict[str, Any] | None:
        """
        Regenerate the client secret for an existing OAuth2 client.

        Args:
            client_id: The client identifier

        Returns:
            Dictionary with updated client credentials or None if failed
        """
        try:
            import secrets

            # Verify client belongs to this actor
            client_data = self._registry._load_client(client_id)
            if not client_data:
                logger.error(f"OAuth2 client {client_id} not found for regeneration")
                return None

            if client_data.get("actor_id") != self.actor_id:
                logger.error(
                    f"OAuth2 client {client_id} does not belong to actor {self.actor_id}"
                )
                return None

            # Only allow regeneration for custom clients (those starting with mcp_)
            if not client_id.startswith("mcp_"):
                logger.error(
                    f"Cannot regenerate secret for non-custom client {client_id}"
                )
                return None

            # Generate new client secret
            new_client_secret = secrets.token_urlsafe(32)

            # Update client data with new secret
            client_data["client_secret"] = new_client_secret
            client_data["secret_regenerated_at"] = int(time.time())

            # Store updated client data
            self._registry._store_client(self.actor_id, client_id, client_data)

            # Verify the updated data was stored correctly by re-loading it
            verify_client_data = self._registry._load_client(client_id)
            if (
                verify_client_data
                and verify_client_data.get("client_secret") == new_client_secret
            ):
                logger.info(
                    f"OAuth2 client secret successfully regenerated and verified for {client_id}"
                )
            else:
                logger.error(
                    f"OAuth2 client secret regeneration failed - stored secret does not match for {client_id}"
                )
                logger.error(
                    f"Expected: {new_client_secret}, Got: {verify_client_data.get('client_secret') if verify_client_data else 'None'}"
                )
                return None

            # Return updated client data with formatted timestamp
            if "secret_regenerated_at" in client_data:
                client_data["secret_regenerated_at_formatted"] = datetime.fromtimestamp(
                    client_data["secret_regenerated_at"]
                ).strftime("%Y-%m-%d %H:%M")

            return client_data

        except Exception as e:
            logger.error(
                f"Error regenerating OAuth2 client secret for {client_id}: {e}"
            )
            return None

    def get_client_stats(self) -> dict[str, int | dict[str, int]]:
        """
        Get statistics about OAuth2 clients for this actor.

        Returns:
            Dictionary with client statistics
        """
        try:
            clients = self.list_clients()

            # Calculate statistics
            total_clients = len(clients)
            trust_types: dict[str, int] = {}

            for client in clients:
                trust_type = client.get("trust_type", "unknown")
                trust_types[trust_type] = trust_types.get(trust_type, 0) + 1

            return {
                "total_clients": total_clients,
                "trust_types": trust_types,
                "active_clients": total_clients,  # Could be enhanced with actual activity tracking
            }

        except Exception as e:
            logger.error(f"Error getting OAuth2 client stats: {e}")
            return {"total_clients": 0, "trust_types": {}, "active_clients": 0}

    @property
    def client_count(self) -> int:
        """Get the number of OAuth2 clients for this actor."""
        return len(self.list_clients())

    def __len__(self) -> int:
        """Support len() function."""
        return self.client_count

    def __bool__(self) -> bool:
        """Support boolean evaluation (True if any clients exist)."""
        return self.client_count > 0

    def __iter__(self):
        """Support iteration over clients."""
        return iter(self.list_clients())

    def generate_access_token(
        self, client_id: str, scope: str = "mcp"
    ) -> dict[str, Any] | None:
        """
        Generate an access token for the specified OAuth2 client using client credentials flow.

        Args:
            client_id: The client identifier
            scope: The requested scope (default: "mcp")

        Returns:
            Dictionary with access token response or None if failed
            Contains: access_token, token_type, expires_in, scope
        """
        try:
            # Verify client belongs to this actor and get client data
            client_data = self.get_client(client_id)
            if not client_data:
                logger.error(
                    f"OAuth2 client {client_id} not found for token generation"
                )
                return None

            # Only allow access token generation for custom clients (those starting with mcp_)
            if not client_id.startswith("mcp_"):
                logger.error(
                    f"Cannot generate access token for non-custom client {client_id}"
                )
                return None

            # Use the token manager to create access token
            from ..oauth2_server.token_manager import get_actingweb_token_manager

            token_manager = get_actingweb_token_manager(self.config)

            # Create access token using client credentials flow
            token_response = token_manager.create_access_token(
                actor_id=self.actor_id,
                client_id=client_id,
                scope=scope,
                trust_type=client_data.get("trust_type", "mcp_client"),
                grant_type="client_credentials",
            )

            if token_response:
                logger.info(f"Access token generated for client {client_id}")
                return token_response
            else:
                logger.error(f"Failed to create access token for client {client_id}")
                return None

        except Exception as e:
            logger.error(f"Error generating access token for client {client_id}: {e}")
            return None
