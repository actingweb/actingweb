"""
Service registry for managing third-party OAuth2 service configurations and clients.

This provides the main interface for registering services and accessing authenticated
service clients from ActingWeb actors.
"""

import logging
from typing import Any

from .service_client import ServiceClient
from .service_config import ServiceConfig, ServiceTemplates

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """
    Registry for third-party OAuth2 services.

    Manages service configurations and provides authenticated service clients
    to ActingWeb actors. This replaces the need for manual OAuth configuration
    in each application.
    """

    def __init__(self, aw_config):
        """Initialize service registry with ActingWeb configuration."""
        self.aw_config = aw_config
        self._services: dict[str, ServiceConfig] = {}

    def register_service(self, service_config: ServiceConfig) -> "ServiceRegistry":
        """
        Register a new service configuration.

        Args:
            service_config: Service configuration object

        Returns:
            Self for method chaining
        """
        if not service_config.is_enabled():
            logger.warning(
                f"Service '{service_config.name}' is not properly configured"
            )

        self._services[service_config.name] = service_config
        logger.info(f"Registered service: {service_config.name}")
        return self

    def register_service_from_dict(
        self, name: str, config: dict[str, Any]
    ) -> "ServiceRegistry":
        """
        Register a service from a configuration dictionary.

        Args:
            name: Service name
            config: Service configuration dictionary

        Returns:
            Self for method chaining
        """
        service_config = ServiceConfig(
            name=name,
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=config.get("scopes", []),
            auth_uri=config["auth_uri"],
            token_uri=config["token_uri"],
            userinfo_uri=config.get("userinfo_uri"),
            revocation_uri=config.get("revocation_uri"),
            base_api_url=config.get("base_api_url"),
            extra_params=config.get("extra_params"),
        )
        return self.register_service(service_config)

    def register_dropbox(self, client_id: str, client_secret: str) -> "ServiceRegistry":
        """Register Dropbox service using template."""
        return self.register_service(ServiceTemplates.dropbox(client_id, client_secret))

    def register_gmail(
        self, client_id: str, client_secret: str, readonly: bool = True
    ) -> "ServiceRegistry":
        """Register Gmail service using template."""
        return self.register_service(
            ServiceTemplates.gmail(client_id, client_secret, readonly)
        )

    def register_github(self, client_id: str, client_secret: str) -> "ServiceRegistry":
        """Register GitHub service using template."""
        return self.register_service(ServiceTemplates.github(client_id, client_secret))

    def register_box(self, client_id: str, client_secret: str) -> "ServiceRegistry":
        """Register Box service using template."""
        return self.register_service(ServiceTemplates.box(client_id, client_secret))

    def get_service_config(self, name: str) -> ServiceConfig | None:
        """Get service configuration by name."""
        return self._services.get(name)

    def list_services(self) -> dict[str, ServiceConfig]:
        """Get all registered service configurations."""
        return self._services.copy()

    def is_service_registered(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._services

    def get_service_client(self, name: str, actor_interface) -> ServiceClient | None:
        """
        Get an authenticated service client for an actor.

        Args:
            name: Service name
            actor_interface: ActorInterface instance

        Returns:
            ServiceClient instance or None if service not registered
        """
        service_config = self.get_service_config(name)
        if not service_config:
            logger.error(f"Service '{name}' is not registered")
            return None

        return ServiceClient(service_config, actor_interface, self.aw_config)


class ActorServices:
    """
    Actor-specific service interface.

    This is attached to ActorInterface to provide easy access to authenticated
    service clients. Example usage:

        dropbox = actor.services.get("dropbox")
        if not dropbox.is_authenticated():
            return {"auth_url": dropbox.get_authorization_url()}

        files = dropbox.get("/2/files/list_folder", {"path": "/Documents"})
    """

    def __init__(self, actor_interface, service_registry: ServiceRegistry):
        """Initialize actor services with service registry."""
        self.actor = actor_interface
        self.registry = service_registry
        self._clients: dict[str, ServiceClient] = {}

    def get(self, service_name: str) -> ServiceClient | None:
        """
        Get authenticated service client for this actor.

        Args:
            service_name: Name of the registered service

        Returns:
            ServiceClient instance or None if service not available
        """
        # Return cached client if available
        if service_name in self._clients:
            return self._clients[service_name]

        # Create new client
        client = self.registry.get_service_client(service_name, self.actor)
        if client:
            self._clients[service_name] = client

        return client

    def list_available_services(self) -> dict[str, bool]:
        """
        List all available services and their authentication status.

        Returns:
            Dict mapping service names to authentication status
        """
        services = {}
        for service_name in self.registry.list_services():
            client = self.get(service_name)
            services[service_name] = client.is_authenticated() if client else False
        return services

    def revoke_service(self, service_name: str) -> bool:
        """
        Revoke authentication for a specific service.

        Args:
            service_name: Name of the service to revoke

        Returns:
            True if revocation was successful
        """
        client = self.get(service_name)
        if not client:
            return False

        success = client.revoke_tokens()

        # Remove from cache
        if service_name in self._clients:
            del self._clients[service_name]

        return success

    def revoke_all_services(self) -> dict[str, bool]:
        """
        Revoke authentication for all services.

        Returns:
            Dict mapping service names to revocation success status
        """
        results = {}
        for service_name in self.registry.list_services():
            results[service_name] = self.revoke_service(service_name)
        return results
