"""Unit tests for PeerCapabilities class."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from actingweb.peer_capabilities import CAPABILITIES_TTL_HOURS, PeerCapabilities


class TestPeerCapabilities:
    """Test PeerCapabilities class."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor interface."""
        actor = MagicMock()
        actor.trust = MagicMock()
        return actor

    def test_init(self, mock_actor):
        """Test PeerCapabilities initialization."""
        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps._actor == mock_actor
        assert caps._peer_id == "peer123"
        assert caps._trust is None
        assert caps._supported == set()
        assert caps._loaded is False

    def test_load_trust_with_no_trust(self, mock_actor):
        """Test loading when no trust exists."""
        mock_actor.trust.get_trust.return_value = None

        caps = PeerCapabilities(mock_actor, "peer123")
        caps._load_trust()

        assert caps._loaded is True
        assert caps._trust is None
        assert caps._supported == set()

    def test_load_trust_with_capabilities(self, mock_actor):
        """Test loading trust with existing capabilities."""
        mock_actor.trust.get_trust.return_value = {
            "peerid": "peer123",
            "aw_supported": "subscriptionbatch,callbackcompression,subscriptionresync",
            "aw_version": "1.4",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        caps._load_trust()

        assert caps._loaded is True
        assert caps._supported == {
            "subscriptionbatch",
            "callbackcompression",
            "subscriptionresync",
        }

    def test_load_trust_with_empty_capabilities(self, mock_actor):
        """Test loading trust with empty capabilities string."""
        mock_actor.trust.get_trust.return_value = {
            "peerid": "peer123",
            "aw_supported": "",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        caps._load_trust()

        assert caps._loaded is True
        assert caps._supported == set()

    def test_supports(self, mock_actor):
        """Test supports() method."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch,callbackcompression",
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        assert caps.supports("subscriptionbatch") is True
        assert caps.supports("callbackcompression") is True
        assert caps.supports("unknown_option") is False

    def test_supports_batch_subscriptions(self, mock_actor):
        """Test supports_batch_subscriptions() helper."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.supports_batch_subscriptions() is True

    def test_supports_compression(self, mock_actor):
        """Test supports_compression() helper."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "callbackcompression",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.supports_compression() is True

    def test_supports_resync_callbacks(self, mock_actor):
        """Test supports_resync_callbacks() helper."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionresync",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.supports_resync_callbacks() is True

    def test_supports_health_endpoint(self, mock_actor):
        """Test supports_health_endpoint() helper."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionhealth",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.supports_health_endpoint() is True

    def test_supports_stats_endpoint(self, mock_actor):
        """Test supports_stats_endpoint() helper."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionstats",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.supports_stats_endpoint() is True

    def test_get_version(self, mock_actor):
        """Test get_version() method."""
        mock_actor.trust.get_trust.return_value = {
            "aw_version": "1.4",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.get_version() == "1.4"

    def test_get_version_not_set(self, mock_actor):
        """Test get_version() when not set."""
        mock_actor.trust.get_trust.return_value = {}

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps.get_version() is None

    def test_get_all_supported(self, mock_actor):
        """Test get_all_supported() method."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch,callbackcompression",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        supported = caps.get_all_supported()

        assert supported == {"subscriptionbatch", "callbackcompression"}
        # Verify it's a copy
        supported.add("new_option")
        assert "new_option" not in caps.get_all_supported()

    def test_is_cache_valid_no_trust(self, mock_actor):
        """Test _is_cache_valid() when no trust exists."""
        mock_actor.trust.get_trust.return_value = None

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps._is_cache_valid() is False

    def test_is_cache_valid_no_fetched_at(self, mock_actor):
        """Test _is_cache_valid() when capabilities_fetched_at not set."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps._is_cache_valid() is False

    def test_is_cache_valid_within_ttl(self, mock_actor):
        """Test _is_cache_valid() when within TTL."""
        now = datetime.now(UTC)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": now.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps._is_cache_valid() is True

    def test_is_cache_valid_expired(self, mock_actor):
        """Test _is_cache_valid() when cache expired."""
        expired = datetime.now(UTC) - timedelta(hours=CAPABILITIES_TTL_HOURS + 1)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": expired.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        assert caps._is_cache_valid() is False

    def test_is_cache_valid_naive_datetime(self, mock_actor):
        """Test _is_cache_valid() with naive datetime string."""
        now = datetime.now(UTC)
        # Create a naive ISO string (no timezone info)
        naive_iso = now.replace(tzinfo=None).isoformat()
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": naive_iso,
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        # Should handle naive datetime and treat as UTC
        assert caps._is_cache_valid() is True

    @patch("actingweb.peer_capabilities.httpx.Client")
    def test_refresh_success(self, mock_client_class, mock_actor):
        """Test refresh() fetches capabilities successfully."""
        mock_actor.trust.get_trust.return_value = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com/peer123",
        }
        mock_actor.trust.modify_trust.return_value = True

        # Mock HTTP client and responses
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        supported_response = MagicMock()
        supported_response.status_code = 200
        supported_response.text = "subscriptionbatch,subscriptionresync"

        version_response = MagicMock()
        version_response.status_code = 200
        version_response.text = "1.4"

        mock_client.get.side_effect = [supported_response, version_response]

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        assert result is True
        mock_actor.trust.modify_trust.assert_called_once()
        call_args = mock_actor.trust.modify_trust.call_args
        assert call_args[0][0] == "peer123"
        assert call_args[1]["aw_supported"] == "subscriptionbatch,subscriptionresync"
        assert call_args[1]["aw_version"] == "1.4"
        assert "capabilities_fetched_at" in call_args[1]

    def test_refresh_no_trust(self, mock_actor):
        """Test refresh() fails when no trust exists."""
        mock_actor.trust.get_trust.return_value = None

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        assert result is False

    def test_refresh_no_baseuri(self, mock_actor):
        """Test refresh() fails when no baseuri."""
        mock_actor.trust.get_trust.return_value = {
            "peerid": "peer123",
            "baseuri": "",
        }

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        assert result is False

    @patch("actingweb.peer_capabilities.httpx.Client")
    def test_refresh_http_error(self, mock_client_class, mock_actor):
        """Test refresh() handles HTTP errors."""
        mock_actor.trust.get_trust.return_value = {
            "baseuri": "https://peer.example.com/peer123",
        }

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        error_response = MagicMock()
        error_response.status_code = 500
        mock_client.get.return_value = error_response

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        assert result is False

    @patch("actingweb.peer_capabilities.httpx.Client")
    def test_refresh_network_error(self, mock_client_class, mock_actor):
        """Test refresh() handles network errors."""
        import httpx

        mock_actor.trust.get_trust.return_value = {
            "baseuri": "https://peer.example.com/peer123",
        }

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.RequestError("Network error")

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        assert result is False

    @patch("actingweb.peer_capabilities.httpx.Client")
    def test_refresh_version_fetch_fails_gracefully(self, mock_client_class, mock_actor):
        """Test refresh() handles version fetch failure gracefully."""
        mock_actor.trust.get_trust.return_value = {
            "baseuri": "https://peer.example.com/peer123",
        }
        mock_actor.trust.modify_trust.return_value = True

        mock_client = MagicMock()
        mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

        supported_response = MagicMock()
        supported_response.status_code = 200
        supported_response.text = "subscriptionbatch"

        version_response = MagicMock()
        version_response.status_code = 404

        mock_client.get.side_effect = [supported_response, version_response]

        caps = PeerCapabilities(mock_actor, "peer123")
        result = caps.refresh()

        # Should still succeed even if version fetch fails
        assert result is True
        call_args = mock_actor.trust.modify_trust.call_args
        assert call_args[1]["aw_supported"] == "subscriptionbatch"
        assert call_args[1]["aw_version"] is None

    def test_ensure_loaded_valid_cache(self, mock_actor):
        """Test ensure_loaded() does not refresh with valid cache."""
        now = datetime.now(UTC)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": now.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        with patch.object(caps, "refresh") as mock_refresh:
            caps.ensure_loaded()
            mock_refresh.assert_not_called()

    def test_ensure_loaded_expired_cache(self, mock_actor):
        """Test ensure_loaded() refreshes with expired cache."""
        expired = datetime.now(UTC) - timedelta(hours=CAPABILITIES_TTL_HOURS + 1)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": expired.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        with patch.object(caps, "refresh") as mock_refresh:
            caps.ensure_loaded()
            mock_refresh.assert_called_once()

    def test_lazy_loading(self, mock_actor):
        """Test that trust is loaded lazily."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        # Trust should not be loaded yet
        mock_actor.trust.get_trust.assert_not_called()

        # Accessing supports() should trigger load
        result = caps.supports("subscriptionbatch")

        mock_actor.trust.get_trust.assert_called_once_with("peer123")
        assert result is True

    def test_caching_after_load(self, mock_actor):
        """Test that trust is only loaded once."""
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        # Multiple accesses should only load once
        caps.supports("subscriptionbatch")
        caps.supports("callbackcompression")
        caps.get_version()

        mock_actor.trust.get_trust.assert_called_once()


@pytest.mark.asyncio
class TestPeerCapabilitiesAsync:
    """Test async methods of PeerCapabilities class."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor interface."""
        actor = MagicMock()
        actor.trust = MagicMock()
        return actor

    @patch("actingweb.peer_capabilities.httpx.AsyncClient")
    async def test_refresh_async_success(self, mock_client_class, mock_actor):
        """Test refresh_async() fetches capabilities successfully."""
        from unittest.mock import AsyncMock

        mock_actor.trust.get_trust.return_value = {
            "peerid": "peer123",
            "baseuri": "https://peer.example.com/peer123",
        }
        mock_actor.trust.modify_trust.return_value = True

        # Mock async HTTP client
        mock_client = MagicMock()

        supported_response = MagicMock()
        supported_response.status_code = 200
        supported_response.text = "subscriptionbatch,subscriptionresync"

        version_response = MagicMock()
        version_response.status_code = 200
        version_response.text = "1.4"

        # Setup async context manager with AsyncMock
        mock_client.get = AsyncMock(
            side_effect=[supported_response, version_response]
        )
        mock_client_class.return_value.__aenter__ = AsyncMock(
            return_value=mock_client
        )
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

        caps = PeerCapabilities(mock_actor, "peer123")
        result = await caps.refresh_async()

        assert result is True
        mock_actor.trust.modify_trust.assert_called_once()
        call_args = mock_actor.trust.modify_trust.call_args
        assert call_args[0][0] == "peer123"
        assert call_args[1]["aw_supported"] == "subscriptionbatch,subscriptionresync"
        assert call_args[1]["aw_version"] == "1.4"

    async def test_refresh_async_no_trust(self, mock_actor):
        """Test refresh_async() fails when no trust exists."""
        mock_actor.trust.get_trust.return_value = None

        caps = PeerCapabilities(mock_actor, "peer123")
        result = await caps.refresh_async()

        assert result is False

    async def test_ensure_loaded_async_valid_cache(self, mock_actor):
        """Test ensure_loaded_async() does not refresh with valid cache."""
        now = datetime.now(UTC)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": now.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        with patch.object(caps, "refresh_async") as mock_refresh:
            await caps.ensure_loaded_async()
            mock_refresh.assert_not_called()

    async def test_ensure_loaded_async_expired_cache(self, mock_actor):
        """Test ensure_loaded_async() refreshes with expired cache."""
        expired = datetime.now(UTC) - timedelta(hours=CAPABILITIES_TTL_HOURS + 1)
        mock_actor.trust.get_trust.return_value = {
            "aw_supported": "subscriptionbatch",
            "capabilities_fetched_at": expired.isoformat(),
        }

        caps = PeerCapabilities(mock_actor, "peer123")

        with patch.object(caps, "refresh_async", return_value=True) as mock_refresh:
            await caps.ensure_loaded_async()
            mock_refresh.assert_called_once()
