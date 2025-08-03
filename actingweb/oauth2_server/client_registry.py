"""
MCP Client Registry for dynamic client registration and management.

This module handles registration of MCP clients (like ChatGPT) that need OAuth2
credentials to authenticate with ActingWeb. Client credentials are stored
per-actor but clients are not treated as actors themselves.
"""

import json
import logging
import secrets
import time
from typing import Dict, Any, Optional, List
from .. import actor as actor_module
from .. import attribute
from .. import config as config_class

logger = logging.getLogger(__name__)


class MCPClientRegistry:
    """
    Registry for MCP clients with per-actor storage.

    This class manages dynamic client registration (RFC 7591) for MCP clients,
    storing credentials in actor properties rather than treating clients as actors.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self.clients_property = "_mcp_clients"  # Actor property to store clients

    def register_client(self, actor_id: str, registration_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register an MCP client for a specific actor.

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
            "created_at": int(time.time()),
            "actor_id": actor_id,
        }

        # Store client in actor properties
        self._store_client(actor_id, client_id, client_data)

        # Update global index
        self._update_global_index(client_id, actor_id)

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
            "client_id_issued_at": client_data["created_at"],
            # OAuth2 endpoints
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "issuer": base_url,
        }

        logger.info(f"Registered MCP client {client_id} for actor {actor_id}")
        return response

    def validate_client(self, client_id: str, client_secret: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
            if client_data.get("client_secret") != client_secret:
                logger.warning(f"Invalid client secret for client {client_id}")
                return None

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

    def get_client_actor_id(self, client_id: str) -> Optional[str]:
        """
        Get the actor ID associated with a client.

        Args:
            client_id: Client identifier

        Returns:
            Actor ID or None if client not found
        """
        client_data = self._load_client(client_id)
        return client_data.get("actor_id") if client_data else None

    def list_clients_for_actor(self, actor_id: str) -> List[Dict[str, Any]]:
        """
        List all clients registered for an actor.

        Args:
            actor_id: Actor identifier

        Returns:
            List of client data dictionaries
        """
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(actor_id=actor_id, bucket="mcp_clients", config=self.config)
            
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

    def _store_client(self, actor_id: str, client_id: str, client_data: Dict[str, Any]) -> None:
        """Store client data using ActingWeb attributes bucket."""
        try:
            # Use the proper ActingWeb pattern with attribute buckets
            bucket = attribute.Attributes(actor_id=actor_id, bucket="mcp_clients", config=self.config)

            # Store client data in the bucket
            logger.info(f"Storing client {client_id} in mcp_clients bucket for actor {actor_id}")
            bucket.set_attr(name=client_id, data=client_data)
            logger.info(f"Successfully stored client data")

        except Exception as e:
            logger.error(f"Error storing client {client_id} for actor {actor_id}: {e}")
            raise

    def _load_client(self, client_id: str) -> Optional[Dict[str, Any]]:
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

            client_data: Optional[Dict[str, Any]] = self._search_client_in_actors(client_id)
            return client_data

        except Exception as e:
            logger.error(f"Error loading client {client_id}: {e}")
            return None

    def _search_client_in_actors(self, client_id: str) -> Optional[Dict[str, Any]]:
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

    def _load_from_global_index(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Load client from a global index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(actor_id="_mcp_global", bucket="client_index", config=self.config)
            
            # Get the actor ID for this client
            actor_id_attr = global_bucket.get_attr(name=client_id)
            if not actor_id_attr or "data" not in actor_id_attr:
                return None
            
            actor_id = actor_id_attr["data"]
            if not actor_id:
                return None
                
            # Load the actual client data from the actor's bucket
            client_bucket = attribute.Attributes(actor_id=actor_id, bucket="mcp_clients", config=self.config)
            client_attr = client_bucket.get_attr(name=client_id)
            if not client_attr or "data" not in client_attr:
                return None
            
            client_data: Dict[str, Any] = client_attr["data"]
            
            return client_data
            
        except Exception as e:
            logger.error(f"Error loading client from global index: {e}")
            return None

    def _update_global_index(self, client_id: str, actor_id: str) -> None:
        """Update the global client index using attribute buckets."""
        try:
            # Use global attribute bucket for client index
            # This stores client_id -> actor_id mapping
            global_bucket = attribute.Attributes(actor_id="_mcp_global", bucket="client_index", config=self.config)
            
            # Store the client_id -> actor_id mapping
            global_bucket.set_attr(name=client_id, data=actor_id)
            logger.info(f"Updated global index: {client_id} -> {actor_id}")
            
        except Exception as e:
            logger.error(f"Error updating global client index: {e}")
            raise


# Global registry instance
_client_registry: Optional[MCPClientRegistry] = None


def get_mcp_client_registry(config: config_class.Config) -> MCPClientRegistry:
    """Get or create the global MCP client registry."""
    global _client_registry
    if _client_registry is None:
        _client_registry = MCPClientRegistry(config)
    return _client_registry
