"""Tests for subscription processing integration layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from actingweb.interface import (
    ActingWebApp,
    CallbackProcessor,
    CallbackType,
    FanOutManager,
    FanOutResult,
    PeerCapabilities,
    ProcessResult,
    RemotePeerStore,
    SubscriptionProcessingConfig,
    get_remote_bucket,
)
from actingweb.subscription_config import SubscriptionProcessingConfig as DirectConfig


class TestSubscriptionProcessingConfig:
    """Tests for SubscriptionProcessingConfig."""

    def test_default_values(self) -> None:
        """Config has sensible defaults."""
        config = SubscriptionProcessingConfig()
        assert config.enabled is False
        assert config.auto_sequence is True
        assert config.auto_storage is True
        assert config.auto_cleanup is True
        assert config.gap_timeout_seconds == 5.0
        assert config.max_pending == 100
        assert config.storage_prefix == "remote:"
        assert config.max_concurrent_callbacks == 10
        assert config.max_payload_for_high_granularity == 65536
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_cooldown == 60.0

    def test_custom_values(self) -> None:
        """Config accepts custom values."""
        config = SubscriptionProcessingConfig(
            enabled=True,
            auto_sequence=False,
            gap_timeout_seconds=10.0,
            max_pending=50,
        )
        assert config.enabled is True
        assert config.auto_sequence is False
        assert config.gap_timeout_seconds == 10.0
        assert config.max_pending == 50

    def test_direct_import_same_as_interface(self) -> None:
        """Verify both import paths work."""
        assert DirectConfig == SubscriptionProcessingConfig


class TestModuleExports:
    """Tests for interface module exports."""

    def test_callback_processor_exported(self) -> None:
        """CallbackProcessor is exported."""
        assert CallbackProcessor is not None

    def test_process_result_exported(self) -> None:
        """ProcessResult is exported."""
        assert ProcessResult is not None
        assert ProcessResult.PROCESSED.value == "processed"

    def test_callback_type_exported(self) -> None:
        """CallbackType is exported."""
        assert CallbackType is not None
        assert CallbackType.DIFF.value == "diff"

    def test_remote_peer_store_exported(self) -> None:
        """RemotePeerStore is exported."""
        assert RemotePeerStore is not None

    def test_get_remote_bucket_exported(self) -> None:
        """get_remote_bucket is exported."""
        assert get_remote_bucket is not None
        assert get_remote_bucket("abc123def456abc123def456abc12345") == "remote:abc123def456abc123def456abc12345"

    def test_peer_capabilities_exported(self) -> None:
        """PeerCapabilities is exported."""
        assert PeerCapabilities is not None

    def test_fanout_manager_exported(self) -> None:
        """FanOutManager is exported."""
        assert FanOutManager is not None

    def test_fanout_result_exported(self) -> None:
        """FanOutResult is exported."""
        assert FanOutResult is not None


class TestActingWebAppSubscriptionProcessing:
    """Tests for ActingWebApp subscription processing configuration."""

    def test_with_subscription_processing_returns_self(self) -> None:
        """with_subscription_processing returns self for chaining."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        result = app.with_subscription_processing()
        assert result is app

    def test_with_subscription_processing_enables_config(self) -> None:
        """with_subscription_processing enables the config."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        app.with_subscription_processing()
        assert app._subscription_config.enabled is True

    def test_with_subscription_processing_custom_values(self) -> None:
        """with_subscription_processing accepts custom values."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        app.with_subscription_processing(
            auto_sequence=False,
            auto_storage=False,
            auto_cleanup=False,
            gap_timeout_seconds=10.0,
            max_pending=50,
        )
        config = app._subscription_config
        assert config.auto_sequence is False
        assert config.auto_storage is False
        assert config.auto_cleanup is False
        assert config.gap_timeout_seconds == 10.0
        assert config.max_pending == 50

    def test_get_subscription_config(self) -> None:
        """get_subscription_config returns the config."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        app.with_subscription_processing()
        config = app.get_subscription_config()
        assert isinstance(config, SubscriptionProcessingConfig)
        assert config.enabled is True


class TestSubscriptionDataHook:
    """Tests for subscription_data_hook decorator."""

    def test_subscription_data_hook_registers_function(self) -> None:
        """subscription_data_hook registers the function."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        @app.subscription_data_hook("properties")
        def handler(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            pass

        assert "properties" in app._subscription_data_hooks
        assert handler in app._subscription_data_hooks["properties"]

    def test_subscription_data_hook_wildcard(self) -> None:
        """subscription_data_hook with wildcard registers for all targets."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        @app.subscription_data_hook("*")
        def handler(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            pass

        assert "*" in app._subscription_data_hooks
        assert handler in app._subscription_data_hooks["*"]

    def test_multiple_hooks_same_target(self) -> None:
        """Multiple hooks can be registered for the same target."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        @app.subscription_data_hook("properties")
        def handler1(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            pass

        @app.subscription_data_hook("properties")
        def handler2(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            pass

        assert len(app._subscription_data_hooks["properties"]) == 2


class TestInvokeSubscriptionDataHooks:
    """Tests for _invoke_subscription_data_hooks method."""

    def test_invoke_target_specific_hooks(self) -> None:
        """Target-specific hooks are invoked."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        invoked = []

        @app.subscription_data_hook("properties")
        def handler(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            invoked.append((peer_id, target, data, sequence, callback_type))

        mock_actor = MagicMock()
        app._invoke_subscription_data_hooks(
            actor=mock_actor,
            peer_id="peer1",
            target="properties",
            data={"key": "value"},
            sequence=1,
            callback_type="diff",
        )

        assert len(invoked) == 1
        assert invoked[0] == ("peer1", "properties", {"key": "value"}, 1, "diff")

    def test_invoke_wildcard_hooks(self) -> None:
        """Wildcard hooks are invoked for any target."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        invoked = []

        @app.subscription_data_hook("*")
        def handler(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            invoked.append(target)

        mock_actor = MagicMock()
        app._invoke_subscription_data_hooks(
            actor=mock_actor,
            peer_id="peer1",
            target="other_target",
            data={},
            sequence=1,
            callback_type="diff",
        )

        assert "other_target" in invoked

    def test_hook_error_does_not_stop_other_hooks(self) -> None:
        """Error in one hook doesn't stop other hooks."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        invoked = []

        @app.subscription_data_hook("properties")
        def handler1(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            raise ValueError("test error")

        @app.subscription_data_hook("properties")
        def handler2(
            actor: object,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str,
        ) -> None:
            invoked.append("handler2")

        mock_actor = MagicMock()
        # Should not raise
        app._invoke_subscription_data_hooks(
            actor=mock_actor,
            peer_id="peer1",
            target="properties",
            data={},
            sequence=1,
            callback_type="diff",
        )

        assert "handler2" in invoked


class TestProcessSubscriptionCallback:
    """Tests for _process_subscription_callback method."""

    def test_returns_false_if_not_enabled(self) -> None:
        """Returns False if subscription processing is not enabled."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        # Don't call with_subscription_processing

        mock_actor = MagicMock()
        result = app._process_subscription_callback(mock_actor, {})

        assert result is False

    @pytest.mark.asyncio
    async def test_processes_callback_through_processor(self) -> None:
        """Callback is processed through CallbackProcessor."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )
        app.with_subscription_processing(auto_storage=False, auto_cleanup=False)

        mock_actor = MagicMock()
        mock_actor.id = "actor123"
        mock_actor.config = MagicMock()

        callback_data = {
            "peerid": "peer123abc456def789abc456def789ab",
            "subscription": {
                "subscriptionid": "sub1",
                "target": "properties",
            },
            "data": {"key": "value"},
            "sequence": 1,
            "type": "diff",
        }

        # Mock the CallbackProcessor
        mock_processor = MagicMock()
        mock_processor.process_callback = AsyncMock(return_value=ProcessResult.PROCESSED)

        with patch("actingweb.callback_processor.CallbackProcessor", return_value=mock_processor):
            app._process_subscription_callback(mock_actor, callback_data)

        # The processor should have been called
        assert mock_processor.process_callback.called


class TestCallbackHookRegistration:
    """Tests for internal callback hook registration."""

    def test_internal_subscription_handler_registered(self) -> None:
        """Internal subscription handler is registered when enabled."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        # Before enabling
        initial_hooks = len(app.hooks._callback_hooks.get("subscription", []))

        app.with_subscription_processing()

        # After enabling
        after_hooks = len(app.hooks._callback_hooks.get("subscription", []))

        assert after_hooks > initial_hooks


class TestCleanupHookRegistration:
    """Tests for cleanup hook registration."""

    def test_cleanup_hook_registered_when_auto_cleanup_true(self) -> None:
        """Cleanup hook is registered when auto_cleanup is True."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        initial_hooks = len(app.hooks._lifecycle_hooks.get("trust_deleted", []))

        app.with_subscription_processing(auto_cleanup=True)

        after_hooks = len(app.hooks._lifecycle_hooks.get("trust_deleted", []))

        assert after_hooks > initial_hooks

    def test_cleanup_hook_not_registered_when_auto_cleanup_false(self) -> None:
        """Cleanup hook is not registered when auto_cleanup is False."""
        app = ActingWebApp(
            aw_type="urn:actingweb:test",
            database="dynamodb",
            fqdn="test.example.com",
        )

        initial_hooks = len(app.hooks._lifecycle_hooks.get("trust_deleted", []))

        app.with_subscription_processing(auto_cleanup=False)

        after_hooks = len(app.hooks._lifecycle_hooks.get("trust_deleted", []))

        # Should be same since we didn't register cleanup
        assert after_hooks == initial_hooks


class TestFullChain:
    """Tests for full method chaining."""

    def test_full_chaining(self) -> None:
        """All builder methods can be chained together."""
        app = (
            ActingWebApp(
                aw_type="urn:actingweb:test",
                database="dynamodb",
                fqdn="test.example.com",
            )
            .with_web_ui(enable=True)
            .with_devtest(enable=False)
            .with_subscription_processing(
                auto_sequence=True,
                auto_storage=True,
                auto_cleanup=True,
            )
        )

        assert app._enable_ui is True
        assert app._enable_devtest is False
        assert app._subscription_config.enabled is True
