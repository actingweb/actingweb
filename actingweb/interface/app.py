"""
Main ActingWebApp class providing fluent API for application configuration.
"""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..config import Config
from ..subscription_config import SubscriptionProcessingConfig
from .hooks import HookMetadata, HookRegistry

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
        database: str | None = None,
        fqdn: str = "",
        proto: str = "https://",
    ):
        self.aw_type = aw_type
        # Allow DATABASE_BACKEND environment variable to override default
        self.database = database or os.getenv("DATABASE_BACKEND", "dynamodb")
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
        self._sync_subscription_callbacks = False  # Async by default

        # Property lookup configuration
        self._indexed_properties: list[str] = ["oauthId", "email", "externalUserId"]
        self._use_lookup_table: bool = (
            False  # False by default for backward compatibility
        )

        # Hook registry
        self.hooks = HookRegistry()

        # Subscription processing configuration
        self._subscription_config = SubscriptionProcessingConfig()
        self._subscription_data_hooks: dict[str, list[Callable[..., Any]]] = {}

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
        # Property lookup configuration
        if hasattr(self, "_indexed_properties"):
            self._config.indexed_properties = self._indexed_properties
        if hasattr(self, "_use_lookup_table"):
            self._config.use_lookup_table = self._use_lookup_table
        # Subscription callback mode
        if hasattr(self, "_sync_subscription_callbacks"):
            self._config.sync_subscription_callbacks = self._sync_subscription_callbacks
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

    def with_indexed_properties(
        self, properties: list[str] | None = None
    ) -> "ActingWebApp":
        """Configure which properties support reverse lookups via lookup table.

        Properties specified here will have their values indexed in a separate
        lookup table, enabling reverse lookups (value -> actor_id) without the
        2048-byte size limit imposed by DynamoDB Global Secondary Indexes.

        Args:
            properties: List of property names to index. Default is
                ["oauthId", "email", "externalUserId"]. Set to empty list []
                to disable all reverse lookups.

        Returns:
            Self for method chaining

        Example::

            app = (
                ActingWebApp(...)
                .with_indexed_properties(["oauthId", "email", "customUserId"])
            )

        Note:
            Only properties listed here can be used with Actor.get_from_property().
            Changes require application restart to take effect.
            Use environment variable INDEXED_PROPERTIES for runtime override.
        """
        if properties is not None:
            self._indexed_properties = properties
        self._apply_runtime_changes_to_config()
        return self

    def with_legacy_property_index(self, enable: bool = False) -> "ActingWebApp":
        """
        Enable legacy GSI/index-based property reverse lookup (for migration).

        When False (default), uses new lookup table approach which supports
        property values larger than 2048 bytes. When True, uses legacy DynamoDB
        GSI or PostgreSQL index on value field (limited to 2048 bytes).

        Args:
            enable: True to use legacy GSI/index, False for new lookup table

        Returns:
            Self for method chaining

        Note:
            Set this to True during migration from legacy systems. Once all
            properties are migrated to lookup table, set back to False (default).
        """
        self._use_lookup_table = not enable
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

    def with_sync_callbacks(self, enable: bool = True) -> "ActingWebApp":
        """Enable synchronous subscription callbacks.

        When enabled, subscription callbacks use blocking HTTP requests instead of
        async fire-and-forget. This ensures callbacks complete before the request
        handler returns, which is important for Lambda/serverless where async tasks
        may be lost when the function freezes after returning a response.

        Args:
            enable: If True, use synchronous callbacks. Default is True.

        Returns:
            Self for method chaining.
        """
        self._sync_subscription_callbacks = enable
        self._apply_runtime_changes_to_config()
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

    def method_hook(
        self,
        method_name: str = "*",
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register method hooks with optional metadata.

        Args:
            method_name: Name of method to hook ("*" for all methods)
            description: Human-readable description of what the method does
            input_schema: JSON schema describing expected input parameters
            output_schema: JSON schema describing the expected return value
            annotations: Safety/behavior hints (e.g., readOnlyHint, idempotentHint)
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            # Store metadata on function
            metadata = HookMetadata(
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                annotations=annotations,
            )
            setattr(func, "_hook_metadata", metadata)  # noqa: B010

            self.hooks.register_method_hook(method_name, func)
            return func

        return decorator

    def action_hook(
        self,
        action_name: str = "*",
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register action hooks with optional metadata.

        Args:
            action_name: Name of action to hook ("*" for all actions)
            description: Human-readable description of what the action does
            input_schema: JSON schema describing expected input parameters
            output_schema: JSON schema describing the expected return value
            annotations: Safety/behavior hints (e.g., destructiveHint, readOnlyHint)
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            # Store metadata on function
            metadata = HookMetadata(
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                annotations=annotations,
            )
            setattr(func, "_hook_metadata", metadata)  # noqa: B010

            self.hooks.register_action_hook(action_name, func)
            return func

        return decorator

    def with_subscription_processing(
        self,
        auto_sequence: bool = True,
        auto_storage: bool = True,
        auto_cleanup: bool = True,
        gap_timeout_seconds: float = 5.0,
        max_pending: int = 100,
        storage_prefix: str = "remote:",
        max_concurrent_callbacks: int = 10,
        max_payload_for_high_granularity: int = 65536,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
    ) -> "ActingWebApp":
        """Enable automatic subscription processing.

        When enabled, the library automatically handles:
        - Callback sequencing and deduplication
        - Gap detection and resync triggering
        - Data storage in RemotePeerStore (if auto_storage=True)
        - Cleanup when trust is deleted (if auto_cleanup=True)

        Args:
            auto_sequence: Enable CallbackProcessor for sequence handling
            auto_storage: Automatically store received data in RemotePeerStore
            auto_cleanup: Register hook to clean up when trust is deleted
            gap_timeout_seconds: Time before triggering resync on sequence gap
            max_pending: Maximum pending callbacks before back-pressure (429)
            storage_prefix: Bucket prefix for RemotePeerStore
            max_concurrent_callbacks: Max concurrent callback deliveries
            max_payload_for_high_granularity: Payload size before granularity downgrade
            circuit_breaker_threshold: Failures before opening circuit
            circuit_breaker_cooldown: Seconds before testing recovery

        Returns:
            Self for method chaining
        """
        self._subscription_config = SubscriptionProcessingConfig(
            enabled=True,
            auto_sequence=auto_sequence,
            auto_storage=auto_storage,
            auto_cleanup=auto_cleanup,
            gap_timeout_seconds=gap_timeout_seconds,
            max_pending=max_pending,
            storage_prefix=storage_prefix,
            max_concurrent_callbacks=max_concurrent_callbacks,
            max_payload_for_high_granularity=max_payload_for_high_granularity,
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_cooldown=circuit_breaker_cooldown,
        )

        # Register internal callback hook to route through processor
        self._register_internal_subscription_handler()

        # Register cleanup hook if enabled
        if auto_cleanup:
            self._register_cleanup_hook()

        return self

    def subscription_data_hook(self, target: str = "*") -> Callable[..., Any]:
        """Decorator to register subscription data hooks.

        Use with .with_subscription_processing() for automatic handling.
        The handler receives already-sequenced, deduplicated data.

        Args:
            target: Target to hook (e.g., "properties", "*" for all)

        Example::

            @app.subscription_data_hook("properties")
            def on_property_change(
                actor: ActorInterface,
                peer_id: str,
                target: str,
                data: dict,
                sequence: int,
                callback_type: str
            ) -> None:
                # Data is already sequenced and stored
                pass
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if target not in self._subscription_data_hooks:
                self._subscription_data_hooks[target] = []
            self._subscription_data_hooks[target].append(func)
            return func

        return decorator

    def _register_internal_subscription_handler(self) -> None:
        """Register internal handler for subscription callbacks."""
        from .actor_interface import ActorInterface

        @self.callback_hook("subscription")
        def _internal_subscription_handler(
            actor: ActorInterface,
            name: str,
            data: dict[str, Any],
        ) -> bool:
            """Internal handler that routes through CallbackProcessor."""
            return self._process_subscription_callback(actor, data)

    def _process_subscription_callback(
        self,
        actor: Any,
        data: dict[str, Any],
    ) -> bool:
        """Process subscription callback through the automatic pipeline."""
        import asyncio
        import logging

        from ..callback_processor import CallbackProcessor, ProcessResult
        from ..remote_storage import RemotePeerStore

        config = self._subscription_config
        if not config.enabled:
            return False

        peer_id = data.get("peerid", "")
        subscription = data.get("subscription", {})
        subscription_id = subscription.get("subscriptionid", "")
        callback_data = data.get("data", {})
        sequence = data.get("sequence", 0)
        callback_type = data.get("type", "diff")
        target = subscription.get("target", "properties")

        logger = logging.getLogger(__name__)

        async def process() -> bool:
            # Create processor
            processor = CallbackProcessor(
                actor,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            # Define handler for processed callbacks
            async def handler(cb: Any) -> None:
                # Auto-storage
                if config.auto_storage:
                    store = RemotePeerStore(actor, peer_id, validate_peer_id=False)
                    if cb.callback_type.value == "resync":
                        store.apply_resync_data(cb.data)
                    else:
                        store.apply_callback_data(cb.data)

                # Invoke user hooks
                await self._invoke_subscription_data_hooks(
                    actor=actor,
                    peer_id=peer_id,
                    target=target,
                    data=cb.data,
                    sequence=cb.sequence,
                    callback_type=cb.callback_type.value,
                )

            # Process through CallbackProcessor
            result = await processor.process_callback(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=sequence,
                data=callback_data,
                callback_type=callback_type,
                handler=handler,
            )

            return result in (ProcessResult.PROCESSED, ProcessResult.DUPLICATE)

        # Run async processing
        try:
            _loop = asyncio.get_running_loop()  # Check if event loop is running
            # If we're in an event loop, use run_in_executor
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, process())
                return future.result()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run
            return asyncio.run(process())
        except Exception as e:
            logger.error(f"Error processing subscription callback: {e}")
            return False

    async def _invoke_subscription_data_hooks(
        self,
        actor: Any,
        peer_id: str,
        target: str,
        data: dict[str, Any],
        sequence: int,
        callback_type: str,
    ) -> None:
        """Invoke registered subscription data hooks."""
        import inspect
        import logging

        logger = logging.getLogger(__name__)

        # Invoke target-specific hooks
        if target in self._subscription_data_hooks:
            for hook in self._subscription_data_hooks[target]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        await hook(actor, peer_id, target, data, sequence, callback_type)
                    else:
                        hook(actor, peer_id, target, data, sequence, callback_type)
                except Exception as e:
                    logger.error(f"Error in subscription_data_hook for {target}: {e}")

        # Invoke wildcard hooks
        if "*" in self._subscription_data_hooks:
            for hook in self._subscription_data_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        await hook(actor, peer_id, target, data, sequence, callback_type)
                    else:
                        hook(actor, peer_id, target, data, sequence, callback_type)
                except Exception as e:
                    logger.error(f"Error in subscription_data_hook wildcard: {e}")

    def _register_cleanup_hook(self) -> None:
        """Register hook to clean up when trust is deleted."""
        import logging

        from ..callback_processor import CallbackProcessor
        from ..remote_storage import RemotePeerStore

        logger = logging.getLogger(__name__)

        @self.lifecycle_hook("trust_deleted")
        def _cleanup_peer_data(
            actor: Any,
            peer_id: str = "",
            **kwargs: Any,
        ) -> None:
            """Clean up remote peer data when trust is deleted."""
            if not peer_id:
                return

            # Clean up stored data
            try:
                store = RemotePeerStore(actor, peer_id, validate_peer_id=False)
                store.delete_all()
            except Exception as e:
                logger.error(f"Error cleaning up RemotePeerStore for {peer_id}: {e}")

            # Clean up callback state
            try:
                processor = CallbackProcessor(actor)
                processor.clear_all_state_for_peer(peer_id)
            except Exception as e:
                logger.error(f"Error cleaning up callback state for {peer_id}: {e}")

    def get_subscription_config(self) -> SubscriptionProcessingConfig:
        """Get the subscription processing configuration."""
        return self._subscription_config

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
                indexed_properties=self._indexed_properties,
                sync_subscription_callbacks=self._sync_subscription_callbacks,
                use_lookup_table=self._use_lookup_table,
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
