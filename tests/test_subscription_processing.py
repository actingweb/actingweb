"""Tests for subscription processing integration layer."""

from actingweb.interface import (
    ActingWebApp,
    CallbackProcessor,
    CallbackType,
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
        assert config.max_concurrent_callbacks == 4
        assert config.callback_delivery_budget_seconds is None
        assert config.serialize_own_host_callbacks is True
        assert not hasattr(config, "circuit_breaker_threshold")

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
        assert (
            get_remote_bucket("abc123def456abc123def456abc12345")
            == "remote:abc123def456abc123def456abc12345"
        )

    def test_peer_capabilities_exported(self) -> None:
        """PeerCapabilities is exported."""
        assert PeerCapabilities is not None

    def test_the_removed_fanout_names_raise_their_pointer(self) -> None:
        import importlib

        import pytest

        for name in ("FanOutManager", "FanOutResult"):
            with pytest.raises(ImportError, match="removed in 3.16"):
                getattr(importlib.import_module("actingweb.interface"), name)
        with pytest.raises(ImportError, match="v3.16"):
            importlib.import_module("actingweb.fanout")

    def test_the_removed_settings_raise_their_pointer(self) -> None:
        import pytest

        app = ActingWebApp(aw_type="urn:actingweb:test:removed", fqdn="x.example")
        with pytest.raises(RuntimeError, match="Callback delivery"):
            app.with_subscription_processing(max_payload_for_high_granularity=1)
        with pytest.raises(RuntimeError, match="Callback delivery"):
            app.with_subscription_processing(circuit_breaker_threshold=5)
        with pytest.raises(RuntimeError, match="Callback delivery"):
            app.with_subscription_processing(circuit_breaker_cooldown=60.0)

    def test_the_new_settings_reach_the_config(self) -> None:
        app = ActingWebApp(aw_type="urn:actingweb:test:new", fqdn="x.example")
        app.with_subscription_processing(
            max_concurrent_callbacks=2,
            callback_delivery_budget_seconds=20,
            serialize_own_host_callbacks=False,
        )
        sub = app.get_subscription_config()
        assert sub.max_concurrent_callbacks == 2
        assert sub.callback_delivery_budget_seconds == 20
        assert sub.serialize_own_host_callbacks is False


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
