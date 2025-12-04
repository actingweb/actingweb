"""
Main ActingWebApp class providing fluent API for application configuration.
"""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..config import Config
from .hooks import HookRegistry

if TYPE_CHECKING:
    from .integrations.fastapi_integration import FastAPIIntegration
    from .integrations.flask_integration import FlaskIntegration


class ActingWebApp:
    """
    Main application class for ActingWeb with fluent configuration API.

    Example usage:

    .. code-block:: python

        app = (
            ActingWebApp(
                aw_type="urn:actingweb:example.com:myapp",
                database="dynamodb",
                fqdn="myapp.example.com",
            )
            .with_oauth(client_id="...", client_secret="...")
            .with_web_ui()
            .with_devtest()
        )

        @app.lifecycle_hook("actor_created")
        def handle_actor_created(actor: 'ActorInterface') -> None:
            # Custom logic after actor creation
            pass
    """

    def __init__(
        self,
        aw_type: str,
        database: str = "dynamodb",
        fqdn: str = "",
        proto: str = "https://",
    ):
        self.aw_type = aw_type
        self.database = database
        self.fqdn = fqdn or os.getenv("APP_HOST_FQDN", "localhost")
        self.proto = proto or os.getenv("APP_HOST_PROTOCOL", "https://")

        # Configuration options
        self._oauth_config: dict[str, Any] | None = None
        self._actors_config: dict[str, dict[str, Any]] = {}
        self._enable_ui = False
        self._enable_devtest = False
        self._enable_bot = False
        self._bot_config: dict[str, Any] | None = None
        self._www_auth = "basic"
        self._unique_creator = False
        self._force_email_prop_as_creator = False
        self._enable_mcp = True  # MCP enabled by default

        # Hook registry
        self.hooks = HookRegistry()

        # Service registry for third-party OAuth2 services
        self._service_registry: Any | None = None  # Lazy initialized

        # Internal config object (lazy initialized)
        self._config: Config | None = None
        # Automatically initialize permission system for better performance
        self._initialize_permission_system()

    def _attach_service_registry_to_config(self) -> None:
        """Ensure the Config instance exposes the shared service registry."""
        if self._config is None:
            return

        # Always set attribute so downstream code can rely on it existing
        self._config.service_registry = self._service_registry  # type: ignore[attr-defined]

    def _apply_runtime_changes_to_config(self) -> None:
        """Propagate builder changes to an existing Config instance.

        This keeps configuration consistent even if get_config() was called
        early (e.g., during startup warmups) before builder methods like
        with_oauth() were invoked.
        """
        if self._config is None:
            return
        # Core toggles
        self._config.ui = self._enable_ui
        self._config.devtest = self._enable_devtest
        self._config.www_auth = self._www_auth
        self._config.unique_creator = self._unique_creator
        self._config.force_email_prop_as_creator = self._force_email_prop_as_creator
        # OAuth configuration
        if self._oauth_config is not None:
            # Replace with latest provided OAuth settings
            self._config.oauth = dict(self._oauth_config)
        # Actor types and bot config
        if self._actors_config:
            self._config.actors = dict(self._actors_config)
        if self._enable_bot:
            self._config.bot = dict(self._bot_config or {})
        # Keep service registry reference in sync
        self._attach_service_registry_to_config()

    def with_oauth(
        self,
        client_id: str,
        client_secret: str,
        scope: str = "",
        auth_uri: str = "",
        token_uri: str = "",
        **kwargs: Any,
    ) -> "ActingWebApp":
        """Configure OAuth authentication."""
        self._oauth_config = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": f"{self.proto}{self.fqdn}/oauth",
            "scope": scope,
            "auth_uri": auth_uri or "https://api.actingweb.net/v1/authorize",
            "token_uri": token_uri or "https://api.actingweb.net/v1/access_token",
            "response_type": "code",
            "grant_type": "authorization_code",
            "refresh_type": "refresh_token",
            **kwargs,
        }
        self._www_auth = "oauth"
        # Ensure existing config (if already created) is updated
        self._apply_runtime_changes_to_config()
        return self

    def with_web_ui(self, enable: bool = True) -> "ActingWebApp":
        """Enable or disable the web UI."""
        self._enable_ui = enable
        self._apply_runtime_changes_to_config()
        return self

    def with_devtest(self, enable: bool = True) -> "ActingWebApp":
        """Enable or disable development/testing endpoints."""
        self._enable_devtest = enable
        self._apply_runtime_changes_to_config()
        return self

    def with_bot(
        self, token: str = "", email: str = "", secret: str = "", admin_room: str = ""
    ) -> "ActingWebApp":
        """Configure bot integration."""
        self._enable_bot = True
        self._bot_config = {
            "token": token or os.getenv("APP_BOT_TOKEN", ""),
            "email": email or os.getenv("APP_BOT_EMAIL", ""),
            "secret": secret or os.getenv("APP_BOT_SECRET", ""),
            "admin_room": admin_room or os.getenv("APP_BOT_ADMIN_ROOM", ""),
        }
        self._apply_runtime_changes_to_config()
        return self

    def with_unique_creator(self, enable: bool = True) -> "ActingWebApp":
        """Enable unique creator constraint."""
        self._unique_creator = enable
        self._apply_runtime_changes_to_config()
        return self

    def with_email_as_creator(self, enable: bool = True) -> "ActingWebApp":
        """Force email property as creator."""
        self._force_email_prop_as_creator = enable
        self._apply_runtime_changes_to_config()
        return self

    def with_mcp(self, enable: bool = True) -> "ActingWebApp":
        """Enable or disable MCP (Model Context Protocol) functionality."""
        self._enable_mcp = enable
        # Note: aw_supported is computed in Config.__init__. We keep this minimal
        # to avoid touching unrelated features; OAuth fix does not require recompute.
        return self

    def add_service(
        self,
        name: str,
        client_id: str,
        client_secret: str,
        scopes: list,
        auth_uri: str,
        token_uri: str,
        userinfo_uri: str = "",
        revocation_uri: str = "",
        base_api_url: str = "",
        **extra_params,
    ) -> "ActingWebApp":
        """Add a custom third-party OAuth2 service configuration."""
        self._get_service_registry().register_service_from_dict(
            name,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": scopes,
                "auth_uri": auth_uri,
                "token_uri": token_uri,
                "userinfo_uri": userinfo_uri,
                "revocation_uri": revocation_uri,
                "base_api_url": base_api_url,
                "extra_params": extra_params,
            },
        )
        return self

    def add_dropbox(self, client_id: str, client_secret: str) -> "ActingWebApp":
        """Add Dropbox service using pre-configured template."""
        self._get_service_registry().register_dropbox(client_id, client_secret)
        return self

    def add_gmail(
        self, client_id: str, client_secret: str, readonly: bool = True
    ) -> "ActingWebApp":
        """Add Gmail service using pre-configured template."""
        self._get_service_registry().register_gmail(client_id, client_secret, readonly)
        return self

    def add_github(self, client_id: str, client_secret: str) -> "ActingWebApp":
        """Add GitHub service using pre-configured template."""
        self._get_service_registry().register_github(client_id, client_secret)
        return self

    def add_box(self, client_id: str, client_secret: str) -> "ActingWebApp":
        """Add Box service using pre-configured template."""
        self._get_service_registry().register_box(client_id, client_secret)
        return self

    def _get_service_registry(self):
        """Get or create the service registry."""
        if self._service_registry is None:
            from .services import ServiceRegistry

            self._service_registry = ServiceRegistry(self.get_config())
        # Ensure config exposes the registry even if it existed earlier
        self._attach_service_registry_to_config()
        return self._service_registry

    def get_service_registry(self):
        """Get the service registry for advanced configuration."""
        return self._get_service_registry()

    def add_actor_type(
        self, name: str, factory: str = "", relationship: str = "friend"
    ) -> "ActingWebApp":
        """Add an actor type configuration."""
        self._actors_config[name] = {
            "type": self.aw_type,
            "factory": factory or f"{self.proto}{self.fqdn}/",
            "relationship": relationship,
        }
        self._apply_runtime_changes_to_config()
        return self

    def property_hook(self, property_name: str = "*") -> Callable[..., Any]:
        """Decorator to register property hooks."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_property_hook(property_name, func)
            return func

        return decorator

    def callback_hook(self, callback_name: str = "*") -> Callable[..., Any]:
        """Decorator to register actor-level callback hooks."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_callback_hook(callback_name, func)
            return func

        return decorator

    def app_callback_hook(self, callback_name: str) -> Callable[..., Any]:
        """Decorator to register application-level callback hooks (no actor context)."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_app_callback_hook(callback_name, func)
            return func

        return decorator

    def subscription_hook(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator to register subscription hooks."""
        self.hooks.register_subscription_hook(func)
        return func

    def lifecycle_hook(self, event: str) -> Callable[..., Any]:
        """Decorator to register lifecycle hooks."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_lifecycle_hook(event, func)
            return func

        return decorator

    def method_hook(self, method_name: str = "*") -> Callable[..., Any]:
        """Decorator to register method hooks."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_method_hook(method_name, func)
            return func

        return decorator

    def action_hook(self, action_name: str = "*") -> Callable[..., Any]:
        """Decorator to register action hooks."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.hooks.register_action_hook(action_name, func)
            return func

        return decorator

    def get_config(self) -> Config:
        """Get the underlying ActingWeb Config object."""
        if self._config is None:
            # Add default actor type
            if "myself" not in self._actors_config:
                self.add_actor_type("myself")

            self._config = Config(
                database=self.database,
                fqdn=self.fqdn,
                proto=self.proto,
                aw_type=self.aw_type,
                desc=f"ActingWeb app: {self.aw_type}",
                version=__version__,
                devtest=self._enable_devtest,
                actors=self._actors_config,
                force_email_prop_as_creator=self._force_email_prop_as_creator,
                unique_creator=self._unique_creator,
                www_auth=self._www_auth,
                logLevel=os.getenv("LOG_LEVEL", "INFO"),
                ui=self._enable_ui,
                bot=self._bot_config or {},
                oauth=self._oauth_config or {},
                mcp=self._enable_mcp,
            )
            self._attach_service_registry_to_config()
            # Attach hooks to config so OAuth2 and other modules can access them
            self._config._hooks = self.hooks
        else:
            # If config already exists, keep it in sync with latest builder settings
            self._apply_runtime_changes_to_config()
            # Ensure hooks are attached even if config was created early
            self._config._hooks = self.hooks
        return self._config

    def is_mcp_enabled(self) -> bool:
        """Check if MCP functionality is enabled."""
        return self._enable_mcp

    def integrate_flask(self, flask_app: Any) -> "FlaskIntegration":
        """Integrate with Flask application."""
        try:
            from .integrations.flask_integration import FlaskIntegration
        except ImportError as e:
            raise ImportError(
                "Flask integration requires Flask to be installed. "
                "Install with: pip install 'actingweb[flask]'"
            ) from e
        integration = FlaskIntegration(self, flask_app)
        integration.setup_routes()
        return integration

    def integrate_fastapi(
        self, fastapi_app: Any, templates_dir: str | None = None, **options: Any
    ) -> "FastAPIIntegration":
        """
        Integrate ActingWeb with FastAPI application.

        Args:
            fastapi_app: The FastAPI application instance
            templates_dir: Directory containing Jinja2 templates (optional)
            **options: Additional configuration options

        Returns:
            FastAPIIntegration instance

        Raises:
            ImportError: If FastAPI is not installed
        """
        try:
            from .integrations.fastapi_integration import FastAPIIntegration
        except ImportError as e:
            raise ImportError(
                "FastAPI integration requires FastAPI to be installed. "
                "Install with: pip install 'actingweb[fastapi]'"
            ) from e

        integration = FastAPIIntegration(self, fastapi_app, templates_dir=templates_dir)
        integration.setup_routes()
        return integration

    def run(self, host: str = "0.0.0.0", port: int = 5000, debug: bool = False) -> None:
        """Run as standalone application with Flask."""
        try:
            from flask import Flask
        except ImportError as e:
            raise ImportError(
                "Flask is required for standalone mode. "
                "Install with: pip install 'actingweb[flask]'"
            ) from e
        flask_app = Flask(__name__)
        self.integrate_flask(flask_app)
        flask_app.run(host=host, port=port, debug=debug)

    def _initialize_permission_system(self) -> None:
        """
        Automatically initialize the ActingWeb permission system.

        This method is called automatically when integrating with web frameworks
        to ensure optimal performance without requiring manual initialization.
        """
        try:
            from ..permission_initialization import initialize_permission_system

            initialize_permission_system(self.get_config())
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Permission system initialization failed: {e}")
            logger.info(
                "System will fall back to basic functionality with lazy loading"
            )
            # Graceful fallback - don't raise exceptions that would break app startup
