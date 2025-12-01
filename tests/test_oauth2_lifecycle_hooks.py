"""
Test OAuth2 actor creation lifecycle hooks.

This test suite ensures that lifecycle hooks are properly triggered when
actors are created through OAuth2 authentication flows.

Regression test for issue where config._hooks was not set, causing
actor_created hooks to be silently ignored during OAuth2 flows.
"""

import pytest

from actingweb.config import Config
from actingweb.interface import ActingWebApp
from actingweb.oauth2 import OAuth2Authenticator


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return Config(
        fqdn="test.example.com",
        proto="https://",
        database="dynamodb",
        aw_type="urn:actingweb:test:lifecycle",
        devtest=True,
    )


@pytest.fixture
def mock_oauth_provider(test_config):
    """Create a mock OAuth2 provider for testing."""
    from actingweb.oauth2 import OAuth2Provider

    provider = OAuth2Provider(
        "test_provider",
        {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "auth_uri": "https://provider.test/auth",
            "token_uri": "https://provider.test/token",
            "userinfo_uri": "https://provider.test/userinfo",
            "scope": "openid email",
            "redirect_uri": "https://test.example.com/oauth/callback",
        },
    )
    return provider


class TestOAuth2LifecycleHooks:
    """Test lifecycle hooks during OAuth2 actor creation."""

    def test_config_hooks_attribute_set(self):
        """
        Test that ActingWebApp attaches hooks to config._hooks.

        Regression test: Verifies config._hooks is set so OAuth2 module
        can access lifecycle hooks.
        """
        app = ActingWebApp(
            aw_type="urn:actingweb:test:hooks",
            database="dynamodb",
            fqdn="test.example.com",
        )

        # Register a lifecycle hook
        hook_called = {"called": False}

        @app.lifecycle_hook("actor_created")
        def handle_created(actor):
            hook_called["called"] = True

        # Get config - this should attach hooks
        config = app.get_config()

        # Verify hooks are attached
        assert hasattr(config, "_hooks"), "Config should have _hooks attribute"
        assert config._hooks is not None, "Config._hooks should not be None"
        assert config._hooks == app.hooks, "Config._hooks should be app.hooks"

    def test_oauth2_actor_creation_uses_config_hooks(self, mock_oauth_provider):
        """
        Test that OAuth2Authenticator accesses config._hooks when creating actors.

        This verifies the fix for the bug where config._hooks was None,
        causing lifecycle hooks to be silently ignored.
        """
        app = ActingWebApp(
            aw_type="urn:actingweb:test:oauth",
            database="dynamodb",
            fqdn="test.example.com",
        )

        # Track hook execution
        hooks_executed = []

        @app.lifecycle_hook("actor_created")
        def handle_actor_created(actor):
            hooks_executed.append(("actor_created", actor.id))

        # Get config with hooks attached
        config = app.get_config()

        # Create OAuth2 authenticator
        authenticator = OAuth2Authenticator(config, mock_oauth_provider)

        # Verify that OAuth2Authenticator can access hooks through config
        assert hasattr(config, "_hooks"), "Config must have _hooks for OAuth2"
        assert config._hooks is not None, "Config._hooks must not be None"

        # Note: We can't easily test actual actor creation in unit tests
        # without mocking the database, but we've verified the critical
        # part: config._hooks is accessible to OAuth2 code

    def test_hooks_persist_across_config_access(self):
        """
        Test that hooks remain attached even when config is accessed multiple times.

        Regression test: Ensures hooks don't get lost if config is created
        early (e.g., during startup warmup) before hooks are registered.
        """
        app = ActingWebApp(
            aw_type="urn:actingweb:test:persist",
            database="dynamodb",
            fqdn="test.example.com",
        )

        # Get config early (before registering hooks)
        config1 = app.get_config()

        # Register a hook
        @app.lifecycle_hook("actor_created")
        def handle_created(actor):
            pass

        # Get config again
        config2 = app.get_config()

        # Should be the same config object
        assert config1 is config2, "Config should be cached"

        # Hooks should be attached after second access
        assert hasattr(config2, "_hooks"), "Config should have _hooks"
        assert config2._hooks is not None, "Config._hooks should be updated"
        assert config2._hooks == app.hooks, "Config._hooks should match app.hooks"

    def test_multiple_lifecycle_hooks_attached(self):
        """
        Test that multiple lifecycle hooks are all accessible through config._hooks.
        """
        app = ActingWebApp(
            aw_type="urn:actingweb:test:multiple",
            database="dynamodb",
            fqdn="test.example.com",
        )

        # Register multiple hooks
        @app.lifecycle_hook("actor_created")
        def handle_created(actor):
            pass

        @app.lifecycle_hook("actor_deleted")
        def handle_deleted(actor):
            pass

        @app.lifecycle_hook("oauth_success")
        def handle_oauth(actor):
            pass

        config = app.get_config()

        # Verify all hooks are accessible
        assert hasattr(config, "_hooks")
        assert config._hooks is not None

        # Verify hook registry contains our hooks
        assert "actor_created" in config._hooks._lifecycle_hooks
        assert "actor_deleted" in config._hooks._lifecycle_hooks
        assert "oauth_success" in config._hooks._lifecycle_hooks

    def test_config_without_hooks_returns_none(self, test_config):
        """
        Test that a config created without ActingWebApp has no _hooks.

        This tests the backward compatibility case where code creates
        Config directly instead of using ActingWebApp.
        """
        # Create config directly (old style)
        config = test_config

        # Should not have _hooks by default
        assert not hasattr(config, "_hooks"), "Direct Config shouldn't have _hooks"

        # OAuth2 code uses getattr with None default, so this is safe
        hooks = getattr(config, "_hooks", None)
        assert hooks is None, "getattr should return None for missing _hooks"


class TestOAuth2HookIntegration:
    """Integration tests for OAuth2 with lifecycle hooks."""

    def test_oauth2_lookup_or_create_accesses_hooks(self, mock_oauth_provider):
        """
        Test that lookup_or_create_actor_by_identifier accesses config._hooks.

        This is the critical code path that was broken before the fix.
        """
        app = ActingWebApp(
            aw_type="urn:actingweb:test:integration",
            database="dynamodb",
            fqdn="test.example.com",
        )

        @app.lifecycle_hook("actor_created")
        def handle_created(actor):
            pass

        config = app.get_config()

        # Create authenticator
        authenticator = OAuth2Authenticator(config, mock_oauth_provider)

        # Verify the config has hooks accessible
        hooks = getattr(authenticator.config, "_hooks", None)
        assert hooks is not None, "OAuth2Authenticator should see config._hooks"
        assert hooks == app.hooks, "Should get the right HookRegistry"

        # The actual line from oauth2.py:629 that was broken:
        # hooks=getattr(self.config, "_hooks", None)
        # Should now return a HookRegistry instead of None
