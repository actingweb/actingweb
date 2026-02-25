"""Tests for ActingWebApp class."""

import os
from unittest.mock import patch

from actingweb.interface.app import ActingWebApp


class TestActingWebAppInit:
    """Test ActingWebApp initialization."""

    def test_init_minimal(self):
        """Test ActingWebApp initialization with minimal parameters."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:app")

        assert app.aw_type == "urn:actingweb:test:app"
        # Database defaults to "dynamodb" unless DATABASE_BACKEND env var is set
        expected_db = os.getenv("DATABASE_BACKEND", "dynamodb")
        assert app.database == expected_db
        assert app.proto == "https://"

    def test_init_with_all_params(self):
        """Test ActingWebApp initialization with all parameters."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:full",
                database="dynamodb",
                fqdn="test.example.com",
                proto="http://",
            )

        assert app.aw_type == "urn:actingweb:test:full"
        assert app.database == "dynamodb"
        assert app.fqdn == "test.example.com"
        assert app.proto == "http://"

    def test_default_values(self):
        """Test ActingWebApp has correct default values."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:defaults")

        assert app._enable_ui is False
        assert app._enable_devtest is False
        assert app._enable_bot is False
        assert app._www_auth == "basic"
        assert app._unique_creator is False
        assert app._force_email_prop_as_creator is False
        assert app._enable_mcp is True


class TestOAuthConfiguration:
    """Test OAuth configuration."""

    def test_with_oauth_sets_config(self):
        """Test with_oauth sets OAuth configuration."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:oauth", fqdn="test.example.com"
            )

            app.with_oauth(
                client_id="test_client_id",
                client_secret="test_client_secret",
                scope="openid email profile",
                auth_uri="https://auth.example.com/authorize",
                token_uri="https://auth.example.com/token",
            )

        # Backward-compat call (no provider) stores under "" key
        assert "" in app._oauth_configs
        cfg = app._oauth_configs[""]
        assert cfg["client_id"] == "test_client_id"
        assert cfg["client_secret"] == "test_client_secret"
        assert cfg["scope"] == "openid email profile"
        assert cfg["auth_uri"] == "https://auth.example.com/authorize"

    def test_with_oauth_sets_www_auth(self):
        """Test with_oauth sets www_auth to oauth."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:oauth")
            app.with_oauth(client_id="test", client_secret="secret")

        assert app._www_auth == "oauth"

    def test_with_oauth_returns_self(self):
        """Test with_oauth returns self for chaining."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:oauth")
            result = app.with_oauth(client_id="test", client_secret="secret")

        assert result is app


class TestFeatureToggles:
    """Test feature enable/disable."""

    def test_with_web_ui_enable(self):
        """Test with_web_ui enables web UI."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:ui")
            app.with_web_ui(enable=True)

        assert app._enable_ui is True

    def test_with_web_ui_disable(self):
        """Test with_web_ui disables web UI."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:ui")
            app.with_web_ui(enable=True)
            app.with_web_ui(enable=False)

        assert app._enable_ui is False

    def test_with_devtest_enable(self):
        """Test with_devtest enables devtest endpoints."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:devtest")
            app.with_devtest(enable=True)

        assert app._enable_devtest is True

    def test_with_devtest_disable(self):
        """Test with_devtest disables devtest endpoints."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:devtest")
            app.with_devtest(enable=True)
            app.with_devtest(enable=False)

        assert app._enable_devtest is False

    def test_with_mcp_enable(self):
        """Test with_mcp enables MCP."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:mcp")
            app.with_mcp(enable=True)

        assert app._enable_mcp is True

    def test_with_mcp_disable(self):
        """Test with_mcp disables MCP."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:mcp")
            app.with_mcp(enable=False)

        assert app._enable_mcp is False

    def test_with_unique_creator(self):
        """Test with_unique_creator enables unique creator constraint."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:unique")
            app.with_unique_creator(enable=True)

        assert app._unique_creator is True

    def test_with_email_as_creator(self):
        """Test with_email_as_creator enables email as creator."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:email")
            app.with_email_as_creator(enable=True)

        assert app._force_email_prop_as_creator is True


class TestBotConfiguration:
    """Test bot configuration."""

    def test_with_bot_sets_config(self):
        """Test with_bot sets bot configuration."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:bot")
            app.with_bot(
                token="bot_token_123",
                email="bot@example.com",
                secret="bot_secret",
                admin_room="admin_room_id",
            )

        assert app._enable_bot is True
        assert app._bot_config is not None
        assert app._bot_config["token"] == "bot_token_123"
        assert app._bot_config["email"] == "bot@example.com"
        assert app._bot_config["secret"] == "bot_secret"
        assert app._bot_config["admin_room"] == "admin_room_id"

    def test_with_bot_from_env(self):
        """Test with_bot uses environment variables as fallback."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            with patch.dict(
                os.environ,
                {
                    "APP_BOT_TOKEN": "env_token",
                    "APP_BOT_EMAIL": "env@example.com",
                },
            ):
                app = ActingWebApp(aw_type="urn:actingweb:test:bot")
                app.with_bot()

        assert app._bot_config is not None
        assert app._bot_config["token"] == "env_token"
        assert app._bot_config["email"] == "env@example.com"


class TestActorTypes:
    """Test actor type management."""

    def test_add_actor_type(self):
        """Test add_actor_type adds an actor type."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:actors")
            app.add_actor_type(
                name="friend",
                factory="https://friend.example.com/",
                relationship="friend",
            )

        assert "friend" in app._actors_config
        assert app._actors_config["friend"]["factory"] == "https://friend.example.com/"

    def test_add_multiple_actor_types(self):
        """Test adding multiple actor types."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:actors")
            app.add_actor_type(
                name="friend",
                factory="https://friend.example.com/",
                relationship="friend",
            )
            app.add_actor_type(
                name="colleague",
                factory="https://colleague.example.com/",
                relationship="colleague",
            )

        assert len(app._actors_config) == 2
        assert "friend" in app._actors_config
        assert "colleague" in app._actors_config


class TestHookDecorators:
    """Test hook registration decorators."""

    def test_property_hook_decorator(self):
        """Test property_hook decorator registers hooks."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

            @app.property_hook("notes")
            def handle_notes(
                actor,
                name,
                data,  # noqa: ARG001  # pylint: disable=unused-argument
            ):
                return {"status": "ok"}

            _ = handle_notes  # Suppress unused variable warning

        # Property hooks are stored in _property_hooks dict
        assert "notes" in app.hooks._property_hooks

    def test_callback_hook_decorator(self):
        """Test callback_hook decorator registers hooks."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

            @app.callback_hook("ping")
            def handle_ping(
                actor,
                name,
                data,  # noqa: ARG001  # pylint: disable=unused-argument
            ):
                return {"status": "pong"}

            _ = handle_ping  # Suppress unused variable warning

        # Callback hooks are stored in _callback_hooks dict
        assert "ping" in app.hooks._callback_hooks

    def test_lifecycle_hook_decorator(self):
        """Test lifecycle_hook decorator registers hooks."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

            @app.lifecycle_hook("actor_created")
            def handle_actor_created(
                actor,  # noqa: ARG001  # pylint: disable=unused-argument
            ):
                pass

            _ = handle_actor_created  # Suppress unused variable warning

        # Lifecycle hooks are stored in _lifecycle_hooks dict
        assert "actor_created" in app.hooks._lifecycle_hooks

    def test_method_hook_decorator(self):
        """Test method_hook decorator registers hooks."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

            @app.method_hook("custom_method")
            def handle_custom_method(
                actor,
                name,
                data,  # noqa: ARG001  # pylint: disable=unused-argument
            ):
                return {"result": "done"}

            _ = handle_custom_method  # Suppress unused variable warning

        # Method hooks are stored in _method_hooks dict
        assert "custom_method" in app.hooks._method_hooks

    def test_action_hook_decorator(self):
        """Test action_hook decorator registers hooks."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

            @app.action_hook("search")
            def handle_search(
                actor,
                name,
                data,  # noqa: ARG001  # pylint: disable=unused-argument
            ):
                return []

            _ = handle_search  # Suppress unused variable warning

        # Action hooks are stored in _action_hooks dict
        assert "search" in app.hooks._action_hooks


class TestGetConfig:
    """Test config retrieval."""

    def test_get_config_creates_config(self):
        """Test get_config creates Config instance."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:config")
            config = app.get_config()

        assert config is not None
        assert config.aw_type == "urn:actingweb:test:config"

    def test_get_config_returns_same_instance(self):
        """Test get_config returns same Config instance on repeated calls."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:config")
            config1 = app.get_config()
            config2 = app.get_config()

        assert config1 is config2


class TestFluentChaining:
    """Test fluent API chaining."""

    def test_method_chaining(self):
        """Test methods can be chained together."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = (
                ActingWebApp(aw_type="urn:actingweb:test:chain")
                .with_web_ui(enable=True)
                .with_devtest(enable=True)
                .with_unique_creator(enable=True)
                .with_email_as_creator(enable=True)
                .with_mcp(enable=True)
            )

        assert app._enable_ui is True
        assert app._enable_devtest is True
        assert app._unique_creator is True
        assert app._force_email_prop_as_creator is True
        assert app._enable_mcp is True


class TestServiceRegistry:
    """Test service registry."""

    def test_get_service_registry(self):
        """Test _get_service_registry returns ServiceRegistry."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:services")
            registry = app._get_service_registry()

        assert registry is not None

    def test_add_service(self):
        """Test add_service adds a service configuration."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:services")
            result = app.add_service(
                name="custom_service",
                client_id="service_client_id",
                client_secret="service_secret",
                scopes=["read", "write"],
                auth_uri="https://auth.custom.com/authorize",
                token_uri="https://auth.custom.com/token",
            )

        # add_service returns self for chaining
        assert result is app


class TestHookRegistry:
    """Test hook registry integration."""

    def test_hooks_attribute_exists(self):
        """Test ActingWebApp has hooks attribute."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

        assert hasattr(app, "hooks")
        assert app.hooks is not None

    def test_hooks_is_hook_registry(self):
        """Test hooks is a HookRegistry instance."""
        from actingweb.interface.hooks import HookRegistry

        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(aw_type="urn:actingweb:test:hooks")

        assert isinstance(app.hooks, HookRegistry)


class TestMultiProviderOAuth:
    """Test multi-provider OAuth configuration."""

    def test_with_oauth_two_providers_accumulates(self):
        """Test with_oauth() called twice with different providers accumulates both."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:multi", fqdn="test.example.com"
            )
            app.with_oauth(
                provider="google",
                client_id="google_id",
                client_secret="google_secret",
                scope="openid email profile",
            )
            app.with_oauth(
                provider="github",
                client_id="github_id",
                client_secret="github_secret",
                scope="user:email",
            )

        assert "google" in app._oauth_configs
        assert "github" in app._oauth_configs
        assert app._oauth_configs["google"]["client_id"] == "google_id"
        assert app._oauth_configs["github"]["client_id"] == "github_id"

    def test_with_oauth_no_provider_backward_compat(self):
        """Test with_oauth() without provider param maintains backward compat."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:compat", fqdn="test.example.com"
            )
            app.with_oauth(
                client_id="my_id",
                client_secret="my_secret",
            )

        # Stored under empty-string key
        assert "" in app._oauth_configs
        assert app._oauth_configs[""]["client_id"] == "my_id"

    def test_config_oauth_backward_compat_points_to_first_provider(self):
        """Test config.oauth backward compat points to first named provider."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:compat", fqdn="test.example.com"
            )
            app.with_oauth(
                provider="google",
                client_id="google_id",
                client_secret="google_secret",
            )
            app.with_oauth(
                provider="github",
                client_id="github_id",
                client_secret="github_secret",
            )
            config = app.get_config()

        # config.oauth should point to the first named provider (google)
        assert config.oauth["client_id"] == "google_id"
        assert config.oauth2_provider == "google"

    def test_config_oauth_providers_populated(self):
        """Test config.oauth_providers is populated with both providers."""
        with patch.object(ActingWebApp, "_initialize_permission_system"):
            app = ActingWebApp(
                aw_type="urn:actingweb:test:providers", fqdn="test.example.com"
            )
            app.with_oauth(
                provider="google",
                client_id="g_id",
                client_secret="g_secret",
            )
            app.with_oauth(
                provider="github",
                client_id="gh_id",
                client_secret="gh_secret",
            )
            config = app.get_config()

        assert "google" in config.oauth_providers
        assert "github" in config.oauth_providers
        assert config.oauth_providers["google"]["client_id"] == "g_id"
        assert config.oauth_providers["github"]["client_id"] == "gh_id"

    def test_factory_uses_google_credentials_from_oauth_providers(self):
        """Test create_oauth2_authenticator('google') uses per-provider credentials."""
        from actingweb.config import Config
        from actingweb.oauth2 import create_oauth2_authenticator

        config = Config(
            fqdn="test.example.com",
            database="dynamodb",
        )
        config.oauth_providers = {
            "google": {
                "client_id": "google_cid",
                "client_secret": "google_csec",
            },
            "github": {
                "client_id": "github_cid",
                "client_secret": "github_csec",
            },
        }
        config.oauth2_provider = "google"

        auth = create_oauth2_authenticator(config, "google")
        assert auth.provider.client_id == "google_cid"
        assert auth.provider.client_secret == "google_csec"
        assert auth.provider.name == "google"

    def test_factory_uses_github_credentials_from_oauth_providers(self):
        """Test create_oauth2_authenticator('github') uses per-provider credentials."""
        from actingweb.config import Config
        from actingweb.oauth2 import create_oauth2_authenticator

        config = Config(
            fqdn="test.example.com",
            database="dynamodb",
        )
        config.oauth_providers = {
            "google": {
                "client_id": "google_cid",
                "client_secret": "google_csec",
            },
            "github": {
                "client_id": "github_cid",
                "client_secret": "github_csec",
            },
        }
        config.oauth2_provider = "google"

        auth = create_oauth2_authenticator(config, "github")
        assert auth.provider.client_id == "github_cid"
        assert auth.provider.client_secret == "github_csec"
        assert auth.provider.name == "github"

    def test_provider_class_with_explicit_provider_config(self):
        """Test provider classes constructed with explicit provider_config."""
        from actingweb.config import Config
        from actingweb.oauth2 import GitHubOAuth2Provider, GoogleOAuth2Provider

        config = Config(fqdn="test.example.com", database="dynamodb")

        explicit = {"client_id": "explicit_id", "client_secret": "explicit_sec"}
        google = GoogleOAuth2Provider(config, provider_config=explicit)
        assert google.client_id == "explicit_id"
        assert google.client_secret == "explicit_sec"

        github = GitHubOAuth2Provider(config, provider_config=explicit)
        assert github.client_id == "explicit_id"
        assert github.client_secret == "explicit_sec"


class TestGitHubEmailVerification:
    """Test GitHub email verification security in _get_github_primary_email()."""

    def _make_authenticator(self):
        """Create a GitHub OAuth2Authenticator for testing."""
        from actingweb.config import Config
        from actingweb.oauth2 import create_github_authenticator

        config = Config(fqdn="test.example.com", database="dynamodb")
        config.oauth = {"client_id": "test_id", "client_secret": "test_secret"}
        config.oauth2_provider = "github"
        return create_github_authenticator(config)

    def test_primary_verified_email_returned(self):
        """Test primary+verified email is returned (normal case)."""
        auth = self._make_authenticator()
        mock_response = patch(
            "requests.get",
            return_value=type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json": lambda self: [
                        {
                            "email": "user@example.com",
                            "primary": True,
                            "verified": True,
                        },
                        {
                            "email": "alt@example.com",
                            "primary": False,
                            "verified": True,
                        },
                    ],
                },
            )(),
        )
        with mock_response:
            result = auth._get_github_primary_email("fake_token")
        assert result == "user@example.com"

    def test_unverified_primary_email_skipped(self):
        """Test primary but unverified email is skipped — falls back to first verified."""
        auth = self._make_authenticator()
        mock_response = patch(
            "requests.get",
            return_value=type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json": lambda self: [
                        {
                            "email": "attacker@evil.com",
                            "primary": True,
                            "verified": False,
                        },
                        {
                            "email": "real@example.com",
                            "primary": False,
                            "verified": True,
                        },
                    ],
                },
            )(),
        )
        with mock_response:
            result = auth._get_github_primary_email("fake_token")
        assert result == "real@example.com"

    def test_no_verified_emails_returns_none(self):
        """Test all unverified emails returns None."""
        auth = self._make_authenticator()
        mock_response = patch(
            "requests.get",
            return_value=type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json": lambda self: [
                        {
                            "email": "a@example.com",
                            "primary": True,
                            "verified": False,
                        },
                        {
                            "email": "b@example.com",
                            "primary": False,
                            "verified": False,
                        },
                    ],
                },
            )(),
        )
        with mock_response:
            result = auth._get_github_primary_email("fake_token")
        assert result is None

    def test_no_primary_but_verified_email_returned(self):
        """Test no primary email but verified non-primary is returned."""
        auth = self._make_authenticator()
        mock_response = patch(
            "requests.get",
            return_value=type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "json": lambda self: [
                        {
                            "email": "noprimary@example.com",
                            "primary": False,
                            "verified": True,
                        },
                        {
                            "email": "other@example.com",
                            "primary": False,
                            "verified": False,
                        },
                    ],
                },
            )(),
        )
        with mock_response:
            result = auth._get_github_primary_email("fake_token")
        assert result == "noprimary@example.com"
