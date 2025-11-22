"""
Handler for third-party service OAuth2 callbacks.

This handles OAuth2 callback flows for third-party services like Dropbox, Gmail, GitHub, etc.
"""

import logging
from typing import Any

from ..handlers.base_handler import BaseHandler

logger = logging.getLogger(__name__)


class ServicesHandler(BaseHandler):
    """Handler for third-party service OAuth2 callbacks.

    Attributes:
        _service_registry: Optional service registry injected by integration layer
    """

    _service_registry: Any  # Dynamic attribute injected by integration layer

    def get(self, actor_id: str, service_name: str, **kwargs) -> dict[str, Any]:
        """
        Handle OAuth2 callback for a third-party service.

        Args:
            actor_id: Actor ID
            service_name: Name of the service (e.g., 'dropbox', 'gmail')
            **kwargs: Additional parameters including 'code', 'state', 'error'

        Returns:
            Response data
        """
        # Initialize authentication
        actor = self.require_authenticated_actor(
            actor_id, "services", "GET", service_name
        )
        if not actor:
            logger.error(f"Authentication failed for service callback: {service_name}")
            return {"error": "Authentication failed"}

        # Get service registry from app context
        service_registry = self._get_service_registry()
        if not service_registry:
            logger.error("No service registry available")
            return {"error": "Service integration not configured"}

        # Get the service client
        actor_interface = self._get_actor_interface(actor)
        if not actor_interface:
            logger.error("Failed to create actor interface")
            return {"error": "Internal error"}

        # Set service registry for this actor interface
        actor_interface._service_registry = service_registry

        service_client = actor_interface.services.get(service_name)
        if not service_client:
            logger.error(f"Service '{service_name}' not registered")
            return {"error": f"Service '{service_name}' not available"}

        # Extract callback parameters
        authorization_code = kwargs.get("code", "")
        state = kwargs.get("state", "")
        error = kwargs.get("error", "")

        if error:
            logger.error(f"OAuth2 error for {service_name}: {error}")
            return {"error": f"Authorization failed: {error}"}

        if not authorization_code:
            logger.error(f"No authorization code received for {service_name}")
            return {"error": "No authorization code received"}

        # Handle the callback
        success = service_client.handle_callback(authorization_code, state)

        if success:
            logger.info(
                f"Successfully authenticated {service_name} for actor {actor_id}"
            )
            return {
                "success": True,
                "message": f"Successfully connected to {service_name}",
                "service": service_name,
            }
        else:
            logger.error(
                f"Failed to process {service_name} callback for actor {actor_id}"
            )
            return {"error": f"Failed to connect to {service_name}"}

    def _get_service_registry(self):
        """Get service registry from config or app context."""
        # Check if service registry was injected by integration layer
        if hasattr(self, "_service_registry"):
            return self._service_registry

        # Try to get service registry from config
        return getattr(self.config, "service_registry", None)

    def delete(self, actor_id: str, service_name: str, **kwargs) -> dict[str, Any]:  # pylint: disable=unused-argument
        """
        Revoke authentication for a third-party service.

        Args:
            actor_id: Actor ID
            service_name: Name of the service to revoke
            **kwargs: Additional parameters (unused but required for interface compatibility)

        Returns:
            Response data
        """
        _ = kwargs  # Explicitly mark as unused
        # Initialize authentication
        actor = self.require_authenticated_actor(
            actor_id, "services", "DELETE", service_name
        )
        if not actor:
            logger.error(
                f"Authentication failed for service revocation: {service_name}"
            )
            return {"error": "Authentication failed"}

        # Get service registry
        service_registry = self._get_service_registry()
        if not service_registry:
            return {"error": "Service integration not configured"}

        # Get the actor interface and revoke service
        actor_interface = self._get_actor_interface(actor)
        if not actor_interface:
            return {"error": "Internal error"}

        # Set service registry for this actor interface
        actor_interface._service_registry = service_registry

        success = actor_interface.services.revoke_service(service_name)

        if success:
            logger.info(f"Successfully revoked {service_name} for actor {actor_id}")
            return {
                "success": True,
                "message": f"Successfully disconnected from {service_name}",
                "service": service_name,
            }
        else:
            logger.error(f"Failed to revoke {service_name} for actor {actor_id}")
            return {"error": f"Failed to disconnect from {service_name}"}
