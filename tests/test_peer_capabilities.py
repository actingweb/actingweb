"""Unit tests for PeerCapabilities class and methods/actions caching."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from actingweb.peer_capabilities import (
    CAPABILITIES_TTL_HOURS,
    CachedCapabilitiesStore,
    CachedCapability,
    CachedPeerCapabilities,
    PeerCapabilities,
    _parse_actions_response,
    _parse_methods_response,
)


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
    def test_refresh_version_fetch_fails_gracefully(
        self, mock_client_class, mock_actor
    ):
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
        mock_client.get = AsyncMock(side_effect=[supported_response, version_response])
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
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


# =============================================================================
# Tests for Methods & Actions Caching
# =============================================================================


class TestCachedCapability:
    """Test CachedCapability dataclass."""

    def test_init_minimal(self):
        """Test CachedCapability with minimal fields."""
        cap = CachedCapability(name="test_method")
        assert cap.name == "test_method"
        assert cap.description is None
        assert cap.input_schema is None
        assert cap.output_schema is None
        assert cap.capability_type == "method"

    def test_init_full(self):
        """Test CachedCapability with all fields."""
        cap = CachedCapability(
            name="test_method",
            description="A test method",
            input_schema={"type": "object", "properties": {"arg1": {"type": "string"}}},
            output_schema={"type": "string"},
            capability_type="method",
        )
        assert cap.name == "test_method"
        assert cap.description == "A test method"
        assert cap.input_schema is not None
        assert cap.capability_type == "method"

    def test_to_dict(self):
        """Test CachedCapability.to_dict()."""
        cap = CachedCapability(
            name="test_method",
            description="A test method",
            capability_type="action",
        )
        data = cap.to_dict()
        assert data["name"] == "test_method"
        assert data["description"] == "A test method"
        assert data["capability_type"] == "action"

    def test_from_dict(self):
        """Test CachedCapability.from_dict()."""
        data = {
            "name": "test_action",
            "description": "A test action",
            "input_schema": None,
            "output_schema": None,
            "capability_type": "action",
        }
        cap = CachedCapability.from_dict(data)
        assert cap.name == "test_action"
        assert cap.capability_type == "action"

    def test_validate_valid(self):
        """Test CachedCapability.validate() with valid data."""
        cap = CachedCapability(name="test", capability_type="method")
        assert cap.validate() is True

        cap_action = CachedCapability(name="test", capability_type="action")
        assert cap_action.validate() is True

    def test_validate_invalid_name(self):
        """Test CachedCapability.validate() with invalid name."""
        cap = CachedCapability(name="", capability_type="method")
        assert cap.validate() is False

    def test_validate_invalid_type(self):
        """Test CachedCapability.validate() with invalid capability_type."""
        cap = CachedCapability(name="test", capability_type="invalid")
        assert cap.validate() is False


class TestCachedPeerCapabilities:
    """Test CachedPeerCapabilities dataclass."""

    def test_init_minimal(self):
        """Test CachedPeerCapabilities with minimal fields."""
        caps = CachedPeerCapabilities(actor_id="actor1", peer_id="peer1")
        assert caps.actor_id == "actor1"
        assert caps.peer_id == "peer1"
        assert caps.methods == []
        assert caps.actions == []
        assert caps.fetched_at is None
        assert caps.fetch_error is None

    def test_init_with_capabilities(self):
        """Test CachedPeerCapabilities with methods and actions."""
        method = CachedCapability(name="get_data", capability_type="method")
        action = CachedCapability(name="update_data", capability_type="action")

        caps = CachedPeerCapabilities(
            actor_id="actor1",
            peer_id="peer1",
            methods=[method],
            actions=[action],
            fetched_at="2024-01-01T00:00:00Z",
        )
        assert len(caps.methods) == 1
        assert len(caps.actions) == 1
        assert caps.methods[0].name == "get_data"
        assert caps.actions[0].name == "update_data"

    def test_to_dict(self):
        """Test CachedPeerCapabilities.to_dict()."""
        method = CachedCapability(name="get_data", capability_type="method")
        caps = CachedPeerCapabilities(
            actor_id="actor1",
            peer_id="peer1",
            methods=[method],
            fetched_at="2024-01-01T00:00:00Z",
        )
        data = caps.to_dict()
        assert data["actor_id"] == "actor1"
        assert data["peer_id"] == "peer1"
        assert len(data["methods"]) == 1
        assert data["methods"][0]["name"] == "get_data"
        assert data["fetched_at"] == "2024-01-01T00:00:00Z"

    def test_from_dict(self):
        """Test CachedPeerCapabilities.from_dict()."""
        data = {
            "actor_id": "actor1",
            "peer_id": "peer1",
            "methods": [
                {
                    "name": "get_data",
                    "description": None,
                    "input_schema": None,
                    "output_schema": None,
                    "capability_type": "method",
                }
            ],
            "actions": [],
            "fetched_at": "2024-01-01T00:00:00Z",
            "fetch_error": None,
        }
        caps = CachedPeerCapabilities.from_dict(data)
        assert caps.actor_id == "actor1"
        assert len(caps.methods) == 1
        assert caps.methods[0].name == "get_data"

    def test_get_capabilities_key(self):
        """Test CachedPeerCapabilities.get_capabilities_key()."""
        caps = CachedPeerCapabilities(actor_id="actor1", peer_id="peer1")
        assert caps.get_capabilities_key() == "actor1:peer1"

    def test_get_method(self):
        """Test CachedPeerCapabilities.get_method()."""
        method1 = CachedCapability(name="get_data", capability_type="method")
        method2 = CachedCapability(name="set_data", capability_type="method")
        caps = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1", methods=[method1, method2]
        )

        assert caps.get_method("get_data") is not None
        assert caps.get_method("get_data").name == "get_data"
        assert caps.get_method("unknown") is None

    def test_get_action(self):
        """Test CachedPeerCapabilities.get_action()."""
        action1 = CachedCapability(name="reset", capability_type="action")
        caps = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1", actions=[action1]
        )

        assert caps.get_action("reset") is not None
        assert caps.get_action("reset").name == "reset"
        assert caps.get_action("unknown") is None

    def test_get_method_names(self):
        """Test CachedPeerCapabilities.get_method_names()."""
        method1 = CachedCapability(name="get_data", capability_type="method")
        method2 = CachedCapability(name="set_data", capability_type="method")
        caps = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1", methods=[method1, method2]
        )

        names = caps.get_method_names()
        assert names == ["get_data", "set_data"]

    def test_get_action_names(self):
        """Test CachedPeerCapabilities.get_action_names()."""
        action1 = CachedCapability(name="reset", capability_type="action")
        action2 = CachedCapability(name="delete", capability_type="action")
        caps = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1", actions=[action1, action2]
        )

        names = caps.get_action_names()
        assert names == ["reset", "delete"]

    def test_validate_valid(self):
        """Test CachedPeerCapabilities.validate() with valid data."""
        caps = CachedPeerCapabilities(actor_id="actor1", peer_id="peer1")
        assert caps.validate() is True

    def test_validate_invalid_actor_id(self):
        """Test CachedPeerCapabilities.validate() with invalid actor_id."""
        caps = CachedPeerCapabilities(actor_id="", peer_id="peer1")
        assert caps.validate() is False

    def test_validate_invalid_peer_id(self):
        """Test CachedPeerCapabilities.validate() with invalid peer_id."""
        caps = CachedPeerCapabilities(actor_id="actor1", peer_id="")
        assert caps.validate() is False

    def test_validate_invalid_method(self):
        """Test CachedPeerCapabilities.validate() with invalid method."""
        invalid_method = CachedCapability(name="", capability_type="method")
        caps = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1", methods=[invalid_method]
        )
        assert caps.validate() is False


class TestParseResponses:
    """Test response parsing helper functions."""

    def test_parse_methods_response_empty(self):
        """Test parsing empty methods response."""
        response = {"methods": []}
        methods = _parse_methods_response(response)
        assert methods == []

    def test_parse_methods_response_with_methods(self):
        """Test parsing methods response with data."""
        response = {
            "methods": [
                {"name": "get_data", "description": "Get data from actor"},
                {
                    "name": "set_data",
                    "description": "Set data on actor",
                    "input_schema": {"type": "object"},
                },
            ]
        }
        methods = _parse_methods_response(response)
        assert len(methods) == 2
        assert methods[0].name == "get_data"
        assert methods[0].capability_type == "method"
        assert methods[1].input_schema == {"type": "object"}

    def test_parse_methods_response_no_methods_key(self):
        """Test parsing response without methods key."""
        response = {}
        methods = _parse_methods_response(response)
        assert methods == []

    def test_parse_methods_response_skips_invalid(self):
        """Test parsing response skips items without name."""
        response = {
            "methods": [
                {"name": "valid_method"},
                {"description": "no name"},  # Should be skipped
                None,  # Should be skipped
            ]
        }
        methods = _parse_methods_response(response)
        assert len(methods) == 1
        assert methods[0].name == "valid_method"

    def test_parse_actions_response_empty(self):
        """Test parsing empty actions response."""
        response = {"actions": []}
        actions = _parse_actions_response(response)
        assert actions == []

    def test_parse_actions_response_with_actions(self):
        """Test parsing actions response with data."""
        response = {
            "actions": [
                {"name": "reset", "description": "Reset actor state"},
                {"name": "delete", "description": "Delete actor"},
            ]
        }
        actions = _parse_actions_response(response)
        assert len(actions) == 2
        assert actions[0].name == "reset"
        assert actions[0].capability_type == "action"
        assert actions[1].description == "Delete actor"


class TestCachedCapabilitiesStore:
    """Test CachedCapabilitiesStore class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config object."""
        config = MagicMock()
        return config

    @pytest.fixture
    def store(self, mock_config):
        """Create a CachedCapabilitiesStore instance."""
        return CachedCapabilitiesStore(mock_config)

    def test_init(self, store, mock_config):
        """Test CachedCapabilitiesStore initialization."""
        assert store.config == mock_config
        assert store._cache == {}

    def test_store_capabilities_valid(self, store):
        """Test storing valid capabilities."""
        caps = CachedPeerCapabilities(
            actor_id="actor1",
            peer_id="peer1",
            fetched_at="2024-01-01T00:00:00Z",
        )

        with patch.object(store, "_get_capabilities_bucket") as mock_bucket:
            mock_attr_bucket = MagicMock()
            mock_attr_bucket.set_attr.return_value = True
            mock_bucket.return_value = mock_attr_bucket

            result = store.store_capabilities(caps)
            assert result is True
            assert "actor1:peer1" in store._cache

    def test_store_capabilities_invalid(self, store):
        """Test storing invalid capabilities fails."""
        caps = CachedPeerCapabilities(actor_id="", peer_id="peer1")
        result = store.store_capabilities(caps)
        assert result is False

    def test_get_capabilities_from_cache(self, store):
        """Test getting capabilities from cache."""
        caps = CachedPeerCapabilities(actor_id="actor1", peer_id="peer1")
        store._cache["actor1:peer1"] = caps

        result = store.get_capabilities("actor1", "peer1")
        assert result == caps

    def test_get_capabilities_not_found(self, store):
        """Test getting non-existent capabilities."""
        with patch.object(store, "_get_capabilities_bucket") as mock_bucket:
            mock_attr_bucket = MagicMock()
            mock_attr_bucket.get_attr.return_value = None
            mock_bucket.return_value = mock_attr_bucket

            result = store.get_capabilities("actor1", "peer1")
            assert result is None

    def test_delete_capabilities(self, store):
        """Test deleting capabilities."""
        store._cache["actor1:peer1"] = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1"
        )

        with patch.object(store, "_get_capabilities_bucket") as mock_bucket:
            mock_attr_bucket = MagicMock()
            mock_attr_bucket.delete_attr.return_value = True
            mock_bucket.return_value = mock_attr_bucket

            result = store.delete_capabilities("actor1", "peer1")
            assert result is True
            assert "actor1:peer1" not in store._cache

    def test_clear_cache(self, store):
        """Test clearing the cache."""
        store._cache["actor1:peer1"] = CachedPeerCapabilities(
            actor_id="actor1", peer_id="peer1"
        )
        store._cache["actor2:peer2"] = CachedPeerCapabilities(
            actor_id="actor2", peer_id="peer2"
        )

        store.clear_cache()
        assert store._cache == {}
