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
        # Multi-provider OAuth: dict of provider_name -> config dict
        # Empty string key "" is used for backward-compat single-provider calls
        self._oauth_configs: dict[str, dict[str, Any]] = {}
        self._actors_config: dict[str, dict[str, Any]] = {}
        self._enable_ui = False
        self._enable_devtest = False
        self._enable_bot = False
        self._bot_config: dict[str, Any] | None = None
        self._www_auth = "basic"
        self._unique_creator = False
        self._force_email_prop_as_creator = False
        self._enable_mcp = True  # MCP enabled by default
        self._mcp_server_name = "actingweb"
        self._mcp_instructions: str | None = None
        self._sync_subscription_callbacks = False  # Async by default
        self._thread_pool_workers = (
            10  # Default thread pool size for FastAPI integration
        )

        # Property lookup configuration
        self._indexed_properties: list[str] = ["oauthId", "email", "externalUserId"]
        self._use_lookup_table: bool = (
            False  # False by default for backward compatibility
        )

        # Peer profile caching configuration
        # None = disabled, list of attributes = enabled
        self._peer_profile_attributes: list[str] | None = None

        # Peer capabilities (methods/actions) caching configuration
        self._peer_capabilities_caching: bool = False

        # Peer permissions caching configuration
        self._peer_permissions_caching: bool = False

        # Additional allowed SPA redirect origins (split-domain deployments)
        self._spa_redirect_origins: list[str] = []

        # Allowed CORS origins for the SPA OAuth endpoints (default: allow all)
        self._spa_cors_origins: list[str] = ["*"]

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

    def _warn_lambda_async_callbacks(self) -> None:
        """Warn if running in Lambda environment without sync callbacks enabled."""
        import logging

        logger = logging.getLogger(__name__)

        # Detect Lambda environment through AWS environment variables
        # AWS_LAMBDA_FUNCTION_NAME is set in all Lambda functions
        # AWS_EXECUTION_ENV contains runtime info (e.g., "AWS_Lambda_python3.11")
        is_lambda = bool(
            os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
            or os.environ.get("AWS_EXECUTION_ENV", "").startswith("AWS_Lambda_")
        )

        if is_lambda and not self._sync_subscription_callbacks:
            logger.warning(
                "Running in AWS Lambda with async subscription callbacks enabled. "
                "Fire-and-forget callbacks may be lost when Lambda function freezes. "
                "Consider enabling sync callbacks with .with_sync_callbacks() "
                "to ensure callback delivery before function freeze. "
                "See: https://docs.actingweb.org/guides/lambda-deployment.html"
            )

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
        # OAuth configuration — multi-provider support
        if self._oauth_configs:
            # Build named providers (skip the empty-string default key)
            named: dict[str, dict[str, Any]] = {
                k: dict(v) for k, v in self._oauth_configs.items() if k
            }
            if named:
                self._config.oauth_providers = named
                # Backward compat: oauth points to the first named provider
                first_name = next(iter(named))
                self._config.oauth = dict(named[first_name])
                self._config.oauth2_provider = first_name
            else:
                # Single unnamed provider (backward compat path)
                default_cfg = self._oauth_configs.get("")
                if default_cfg is not None:
                    self._config.oauth = dict(default_cfg)
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
            # Warn if running in Lambda without sync callbacks enabled
            self._warn_lambda_async_callbacks()
        # Peer profile caching configuration
        if hasattr(self, "_peer_profile_attributes"):
            self._config.peer_profile_attributes = self._peer_profile_attributes
        # Peer capabilities (methods/actions) caching configuration
        if hasattr(self, "_peer_capabilities_caching"):
            self._config.peer_capabilities_caching = self._peer_capabilities_caching
        if hasattr(self, "_peer_capabilities_max_age_seconds"):
            self._config.peer_capabilities_max_age_seconds = (
                self._peer_capabilities_max_age_seconds
            )
        # Peer permissions caching configuration
        if hasattr(self, "_peer_permissions_caching"):
            self._config.peer_permissions_caching = self._peer_permissions_caching
        # Auto-delete on revocation configuration
        if hasattr(self, "_auto_delete_on_revocation"):
            self._config.auto_delete_on_revocation = self._auto_delete_on_revocation
        # Notify peer on change configuration
        if hasattr(self, "_notify_peer_on_change"):
            self._config.notify_peer_on_change = self._notify_peer_on_change
        # Additional allowed SPA redirect origins
        if hasattr(self, "_spa_redirect_origins"):
            self._config.spa_redirect_origins = list(self._spa_redirect_origins)
        # Allowed CORS origins for the SPA OAuth endpoints
        if hasattr(self, "_spa_cors_origins"):
            self._config.spa_cors_origins = list(self._spa_cors_origins)
        # Update supported options based on enabled features
        self._config.update_supported_options()
        # Keep service registry reference in sync
        self._attach_service_registry_to_config()

    def with_oauth(
        self,
        client_id: str,
        client_secret: str,
        scope: str = "",
        auth_uri: str = "",
        token_uri: str = "",
        provider: str = "",
        **kwargs: Any,
    ) -> "ActingWebApp":
        """Configure OAuth authentication.

        Can be called multiple times with different ``provider`` values to
        configure multiple OAuth providers simultaneously.

        .. note::

            When calling ``with_oauth()`` multiple times for different
            providers, **every** call must include an explicit ``provider``
            name.  Mixing a nameless call (legacy single-provider API) with
            named calls will silently drop the nameless provider from the
            multi-provider configuration.

        Args:
            client_id: OAuth client ID
            client_secret: OAuth client secret
            scope: OAuth scope string
            auth_uri: Authorization endpoint URL
            token_uri: Token exchange endpoint URL
            provider: Provider name (e.g. ``"google"``, ``"github"``).
                When empty, stores as the single default provider for
                backward compatibility.
            **kwargs: Additional OAuth config values
        """
        oauth_cfg: dict[str, Any] = {
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
        # Store under the provider key (empty string for backward-compat default)
        self._oauth_configs[provider] = oauth_cfg
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

    def with_spa_redirect_origins(self, *origins: str) -> "ActingWebApp":
        """Allow additional SPA redirect origins (split-domain deployments).

        The ``redirect_uri`` passed to ``POST /oauth/spa/authorize`` is validated
        against an allowlist — the backend's own FQDN plus the origins of
        configured OAuth redirect URIs / Apple mobile deep links. An off-origin
        ``redirect_uri`` is rejected with ``400`` (closing an open-redirect /
        one-time-session-id leak). Use this when your SPA is served from a
        different origin than the backend FQDN so its authorize requests are
        accepted.

        Origins must be scheme + host (+ optional port), e.g.
        ``https://app.example.com``. Same-origin SPAs need no configuration.

        Args:
            *origins: One or more allowed SPA origins. Calling with no arguments
                clears any previously configured origins.

        Returns:
            Self for method chaining

        Example::

            app = (
                ActingWebApp(...)
                .with_spa_redirect_origins("https://app.example.com")
            )
        """
        self._spa_redirect_origins = list(origins)
        self._apply_runtime_changes_to_config()
        return self

    def with_spa_cors_origins(self, *origins: str) -> "ActingWebApp":
        """Restrict the CORS origins allowed on the SPA OAuth endpoints.

        Controls ``Access-Control-Allow-Origin`` for the ``/oauth/spa/*``
        endpoints. The default is ``"*"`` (echo the request origin — allow all),
        which is convenient for development but should be tightened in production
        to the specific origins that serve your SPA. Calling with no arguments
        resets to allow-all.

        Origins are scheme + host (+ optional port), e.g.
        ``https://app.example.com``.

        Args:
            *origins: One or more allowed CORS origins. No arguments restores the
                allow-all (``"*"``) default.

        Returns:
            Self for method chaining

        Example::

            app = (
                ActingWebApp(...)
                .with_spa_cors_origins(
                    "https://app.example.com",
                    "https://staging.app.example.com",
                )
            )
        """
        self._spa_cors_origins = list(origins) if origins else ["*"]
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

    def with_mcp(
        self,
        enable: bool = True,
        server_name: str = "actingweb",
        instructions: str | None = None,
    ) -> "ActingWebApp":
        """Enable or disable MCP (Model Context Protocol) functionality.

        Args:
            enable: If True, enable MCP support.
            server_name: Name announced in the MCP initialise handshake.
                Some clients use this as the default tool prefix
                (``emm:search`` vs ``actingweb:search``). Defaults to
                ``"actingweb"``. The first ``with_mcp()`` call sets the
                process-wide singleton name; subsequent re-configuration
                does not rename existing per-actor servers.
            instructions: Optional server-level orientation string
                surfaced on the MCP ``InitializeResult.instructions``
                field per protocol. Clients display it to the LLM on
                initial connection. Use it to point new LLMs at an
                entry-point tool (e.g. ``how_to_use()``). Like
                ``server_name``, the first call wins for the singleton.
        """
        self._enable_mcp = enable
        self._mcp_server_name = server_name
        self._mcp_instructions = instructions
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

    def with_thread_pool_workers(self, workers: int) -> "ActingWebApp":
        """Configure thread pool size for FastAPI integration.

        The thread pool is used to execute synchronous ActingWeb handlers
        (database operations, HTTP requests) without blocking the async event loop.

        Tuning guidelines:
        - Default: 10 workers (suitable for most applications)
        - Low traffic: 5 workers (reduces memory overhead)
        - High traffic: 20-50 workers (handles more concurrent requests)
        - Lambda: 5-10 workers (limited by function concurrency)
        - Container: Scale based on CPU cores (e.g., 2-5 per core)

        Memory overhead: ~8MB per worker thread on average.

        Args:
            workers: Number of thread pool workers. Must be between 1 and 100.

        Returns:
            Self for method chaining.

        Raises:
            ValueError: If workers is outside the valid range [1, 100].

        Example:
            >>> app = ActingWebApp(...).with_thread_pool_workers(20)
        """
        if not 1 <= workers <= 100:
            raise ValueError(
                f"Thread pool workers must be between 1 and 100, got {workers}"
            )
        self._thread_pool_workers = workers
        return self

    def with_peer_profile(
        self,
        attributes: list[str] | None = None,
    ) -> "ActingWebApp":
        """Enable peer profile caching for trust relationships.

        When enabled, peer profile attributes are automatically fetched and cached
        when trust relationships are established. Profiles are refreshed during
        sync_peer() operations.

        Args:
            attributes: List of property names to cache from peer actors.
                Default: ["displayname", "email", "description"]
                Pass empty list to explicitly disable caching.

        Returns:
            Self for method chaining.

        Example::

            app = (
                ActingWebApp(...)
                .with_peer_profile(attributes=["displayname", "email", "avatar_url"])
            )

            # Access via TrustManager
            profile = actor.trust.get_peer_profile(peer_id)
            if profile:
                print(f"Connected with {profile.displayname}")
        """
        # Set default attributes if None provided
        if attributes is None:
            self._peer_profile_attributes = ["displayname", "email", "description"]
        else:
            self._peer_profile_attributes = attributes

        self._apply_runtime_changes_to_config()

        # Profile cleanup is now handled automatically in core delete_reciprocal_trust()
        # No hook registration needed

        return self

    def with_peer_capabilities(
        self,
        enable: bool = True,
        max_age_seconds: int = 3600,
    ) -> "ActingWebApp":
        """Enable peer capabilities (methods/actions) caching for trust relationships.

        When enabled, peer methods and actions are automatically fetched and cached
        when trust relationships are established. Capabilities are refreshed during
        sync_peer() operations only if the cache is stale (older than max_age_seconds).

        Args:
            enable: Whether to enable capabilities caching. Default True.
            max_age_seconds: Maximum age in seconds before cached capabilities are
                considered stale and refetched. Default 3600 (1 hour). Capabilities
                (methods/actions) rarely change, so 1 hour is conservative. Set to 0
                to always refetch.

        Returns:
            Self for method chaining.

        Example::

            app = (
                ActingWebApp(...)
                .with_peer_capabilities(enable=True, max_age_seconds=7200)
            )

            # Access via TrustManager
            capabilities = actor.trust.get_peer_capabilities(peer_id)
            if capabilities:
                for method in capabilities.methods:
                    print(f"Method: {method.name} - {method.description}")
        """
        self._peer_capabilities_caching = enable
        self._peer_capabilities_max_age_seconds = max_age_seconds
        self._apply_runtime_changes_to_config()

        # Capabilities cleanup is now handled automatically in core delete_reciprocal_trust()
        # No hook registration needed

        return self

    def with_peer_permissions(
        self,
        enable: bool = True,
        auto_delete_on_revocation: bool = False,
        notify_peer_on_change: bool = True,
    ) -> "ActingWebApp":
        """Enable peer permissions caching for trust relationships.

        When enabled, peer permissions are automatically fetched and cached
        when trust relationships are established. Permissions are refreshed during
        sync_peer() operations.

        This caches what permissions the REMOTE peer has granted US access to.
        It is distinct from TrustPermissions which stores what WE grant to peers.

        Permission callbacks from peers are automatically processed and stored
        when this is enabled.

        Args:
            enable: Whether to enable permissions caching. Default True.
            auto_delete_on_revocation: When True, automatically delete cached
                peer data from RemotePeerStore when the peer revokes property
                access. This ensures that when a peer revokes access to certain
                data (e.g., memory_* properties), the locally cached copies are
                deleted. Default False.
            notify_peer_on_change: When True (default), automatically notify
                peers when their permissions change. This sends a callback to
                the peer's /callbacks/permissions/{actor_id} endpoint. The
                notification is fire-and-forget (failures logged but don't
                block the store operation).

        Returns:
            Self for method chaining.

        Example::

            app = (
                ActingWebApp(...)
                .with_peer_permissions(
                    enable=True,
                    auto_delete_on_revocation=True,  # Delete cached data on revocation
                    notify_peer_on_change=True       # Auto-notify peers (default)
                )
            )

            # Access cached permissions via PeerPermissionStore
            from actingweb.peer_permissions import get_peer_permission_store
            store = get_peer_permission_store(actor.config)
            permissions = store.get_permissions(actor.id, peer_id)
            if permissions:
                if permissions.has_property_access("memory_travel", "read"):
                    print("Peer granted us access to memory_travel")
        """
        self._peer_permissions_caching = enable
        self._auto_delete_on_revocation = auto_delete_on_revocation
        self._notify_peer_on_change = notify_peer_on_change
        self._apply_runtime_changes_to_config()

        # Permissions cleanup is now handled automatically in core delete_reciprocal_trust()
        # No hook registration needed

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

    def with_apple_sign_in(
        self,
        client_id: str,
        *,
        audiences: list[str],
        team_id: str,
        key_id: str,
        private_key_path: str | None = None,
        private_key_pem: str | None = None,
        scope: str = "openid name email",
        web_redirect_uri: str = "",
        mobile_redirect_uri: str = "",
    ) -> "ActingWebApp":
        """Configure Sign in with Apple as an OAuth login provider.

        Apple differs from Google/GitHub: the ``client_secret`` is a freshly
        signed ES256 JWT (Team ID + Key ID + ``.p8``), there is no userinfo
        endpoint (identity comes from the ``id_token``), and the callback is a
        ``POST`` (``response_mode=form_post``).

        Args:
            client_id: The Apple Services ID (web/Android) used as ``client_id``.
            audiences: Acceptable ``aud`` values for id_token validation —
                typically the Services ID plus the iOS Bundle ID. Must be
                non-empty.
            team_id: Apple Developer Team ID (the JWT ``iss``).
            key_id: Key ID of the Sign in with Apple ``.p8`` key.
            private_key_path: Path to the ``.p8`` file. Takes precedence over
                ``private_key_pem`` and over the ``APPLE_PRIVATE_KEY_PATH`` env
                var.
            private_key_pem: PEM string of the ``.p8`` key (falls back to the
                ``APPLE_PRIVATE_KEY_PEM`` env var).
            scope: OAuth scope. Defaults to ``"openid name email"``.
            web_redirect_uri: Override for the web/SPA Apple ``redirect_uri``
                (must be HTTPS; defaults to ``/oauth/callback/apple``).
            mobile_redirect_uri: If set, also registers an ``apple-mobile``
                provider whose deep-link redirect the Capacitor app intercepts.

        Raises:
            ValueError: If required fields are missing or the ``.p8`` key cannot
                be loaded/parsed (validated eagerly here, not at first request).
        """
        from ..oauth2_apple import load_private_key_pem

        if not client_id:
            raise ValueError("with_apple_sign_in: client_id (Services ID) is required")
        if not team_id:
            raise ValueError("with_apple_sign_in: team_id is required")
        if not key_id:
            raise ValueError("with_apple_sign_in: key_id is required")
        if not audiences:
            raise ValueError(
                "with_apple_sign_in: audiences must be a non-empty list "
                "(e.g. [services_id, bundle_id])"
            )

        # Resolve and validate the .p8 key eagerly.
        resolve_cfg: dict[str, Any] = {}
        if private_key_path:
            resolve_cfg["apple_private_key_path"] = private_key_path
        if private_key_pem:
            resolve_cfg["apple_private_key_pem"] = private_key_pem
        pem = load_private_key_pem(resolve_cfg)

        def _apple_cfg(redirect_uri: str, deep_link: str = "") -> dict[str, Any]:
            cfg: dict[str, Any] = {
                "client_id": client_id,
                "client_secret": "",
                "scope": scope,
                "redirect_uri": redirect_uri,
                "apple_team_id": team_id,
                "apple_key_id": key_id,
                "apple_private_key_pem": pem,
                "audiences": list(audiences),
            }
            if deep_link:
                cfg["apple_mobile_deep_link"] = deep_link
            return cfg

        web_redirect = (
            web_redirect_uri or f"{self.proto}{self.fqdn}/oauth/callback/apple"
        )
        self._oauth_configs["apple"] = _apple_cfg(web_redirect)

        if mobile_redirect_uri:
            # Apple requires an HTTPS redirect_uri for both authorize and the
            # token exchange, so apple-mobile also points Apple at the HTTPS
            # callback. The custom-scheme `mobile_redirect_uri` is only the final
            # deep link the Capacitor app intercepts (carrying an opaque ticket,
            # never an ActingWeb token).
            self._oauth_configs["apple-mobile"] = _apple_cfg(
                web_redirect, deep_link=mobile_redirect_uri
            )

        self._www_auth = "oauth"
        self._apply_runtime_changes_to_config()
        return self

    def with_google_native(
        self,
        client_id: str,
        *,
        audiences: list[str] | None = None,
        web_client_id: str | None = None,
        ios_client_id: str | None = None,
        android_client_id: str | None = None,
        android_server_client_id: str | None = None,
        client_secret: str = "",
        scope: str = "openid profile email",
        redirect_uri: str = "",
    ) -> "ActingWebApp":
        """Configure Google native sign-in via the JWT-bearer grant.

        Native iOS/Android Google sign-in yields an ``id_token`` the app submits
        to ``POST /oauth/spa/token`` with the ``jwt-bearer`` grant. The library
        validates it against Google's JWKS, accepting any of the configured
        audiences (the per-platform client IDs).

        Args:
            client_id: Primary client ID (also added to ``audiences``).
            audiences: Explicit acceptable ``aud`` values. If omitted, built from
                ``client_id`` plus the four ``*_client_id`` kwargs.
            web_client_id / ios_client_id / android_client_id /
                android_server_client_id: Optional per-platform client IDs folded
                into ``audiences``.
            client_secret: Optional; only needed if this provider also performs a
                code exchange (not required for the pure JWT-bearer path).
            scope: OAuth scope.
            redirect_uri: Optional redirect override.

        Raises:
            ValueError: If no audiences can be derived.
        """
        if not client_id:
            raise ValueError("with_google_native: client_id is required")

        derived = list(audiences) if audiences else []
        for cid in (
            client_id,
            web_client_id,
            ios_client_id,
            android_client_id,
            android_server_client_id,
        ):
            if cid and cid not in derived:
                derived.append(cid)

        if not derived:
            raise ValueError(
                "with_google_native: at least one audience / client ID is required"
            )

        self._oauth_configs["google-native"] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
            "redirect_uri": redirect_uri,
            "audiences": derived,
        }
        self._www_auth = "oauth"
        self._apply_runtime_changes_to_config()
        return self

    def with_github(
        self,
        client_id: str,
        client_secret: str,
        *,
        scope: str = "read:user user:email",
        redirect_uri: str = "",
        mobile_redirect_uri: str = "",
    ) -> "ActingWebApp":
        """Configure GitHub sign-in, with optional native-mobile support.

        Ergonomic equivalent of ``with_oauth(provider="github", ...)`` that fills
        in GitHub's authorization/token endpoints. When ``mobile_redirect_uri`` is
        set it also registers a ``github-mobile`` provider whose OAuth
        ``redirect_uri`` stays on the HTTPS ``/oauth/callback`` so the
        authorization code is exchanged **server-side** and the Capacitor app only
        ever receives an opaque single-use ticket on ``mobile_redirect_uri`` (the
        ``mobile_ticket`` grant). The code therefore never rides a hijackable
        custom-scheme redirect.

        GitHub issues no OIDC ``id_token``; identity comes from the ``/user`` API
        after the code exchange, so GitHub mobile uses this ticket flow rather
        than the JWT-bearer grant used by Apple/Google native.

        Args:
            client_id: GitHub OAuth app client ID.
            client_secret: GitHub OAuth app client secret.
            scope: OAuth scope. Defaults to ``"read:user user:email"``.
            redirect_uri: Override for the web ``redirect_uri`` (defaults to
                ``/oauth/callback``).
            mobile_redirect_uri: Custom-scheme deep link the Capacitor app
                intercepts; when set, registers the ``github-mobile`` provider.
        """
        if not client_id:
            raise ValueError("with_github: client_id is required")
        if not client_secret:
            raise ValueError("with_github: client_secret is required")

        web_redirect = redirect_uri or f"{self.proto}{self.fqdn}/oauth/callback"

        def _github_cfg(deep_link: str = "") -> dict[str, Any]:
            cfg: dict[str, Any] = {
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
                "auth_uri": "https://github.com/login/oauth/authorize",
                "token_uri": "https://github.com/login/oauth/access_token",
                "redirect_uri": web_redirect,
                "response_type": "code",
                "grant_type": "authorization_code",
            }
            if deep_link:
                cfg["mobile_deep_link"] = deep_link
            return cfg

        self._oauth_configs["github"] = _github_cfg()

        if mobile_redirect_uri:
            # The OAuth redirect_uri stays HTTPS (the ticket flow); the
            # custom-scheme deep link only carries the opaque ticket.
            self._oauth_configs["github-mobile"] = _github_cfg(
                deep_link=mobile_redirect_uri
            )

        self._www_auth = "oauth"
        self._apply_runtime_changes_to_config()
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
            subscription_data_hooks=self._subscription_data_hooks,
        )

        # Cleanup is now handled automatically in core delete_reciprocal_trust()
        # No hook registration needed

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

    def get_subscription_config(self) -> SubscriptionProcessingConfig:
        """Get the subscription processing configuration."""
        return self._subscription_config

    def _get_default_oauth_config(self) -> dict[str, Any]:
        """Return the OAuth config dict to pass as ``oauth=`` to Config.

        If named providers are configured, returns the first one.
        Otherwise returns the unnamed default (or empty dict).
        """
        named = {k: v for k, v in self._oauth_configs.items() if k}
        if named:
            return dict(next(iter(named.values())))
        default = self._oauth_configs.get("")
        return dict(default) if default else {}

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
                oauth=self._get_default_oauth_config(),
                mcp=self._enable_mcp,
                mcp_server_name=self._mcp_server_name,
                mcp_instructions=self._mcp_instructions,
                indexed_properties=self._indexed_properties,
                sync_subscription_callbacks=self._sync_subscription_callbacks,
                use_lookup_table=self._use_lookup_table,
                peer_profile_attributes=self._peer_profile_attributes,
                peer_capabilities_caching=self._peer_capabilities_caching,
                peer_permissions_caching=self._peer_permissions_caching,
            )
            # Populate multi-provider OAuth config on initial creation
            named = {k: dict(v) for k, v in self._oauth_configs.items() if k}
            if named:
                self._config.oauth_providers = named
                self._config.oauth2_provider = next(iter(named))
            # Additional allowed SPA redirect origins (split-domain deployments)
            self._config.spa_redirect_origins = list(self._spa_redirect_origins)
            # Allowed CORS origins for the SPA OAuth endpoints
            self._config.spa_cors_origins = list(self._spa_cors_origins)
            self._attach_service_registry_to_config()
            # Attach hooks to config so OAuth2 and other modules can access them
            self._config._hooks = self.hooks
            # Attach subscription config so handlers can access it
            self._config._subscription_config = self._subscription_config
        else:
            # If config already exists, keep it in sync with latest builder settings
            self._apply_runtime_changes_to_config()
            # Ensure hooks are attached even if config was created early
            self._config._hooks = self.hooks
            # Ensure subscription config is attached even if config was created early
            self._config._subscription_config = self._subscription_config
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

        integration = FastAPIIntegration(
            self,
            fastapi_app,
            templates_dir=templates_dir,
            thread_pool_workers=self._thread_pool_workers,
        )
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
