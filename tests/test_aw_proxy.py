"""Tests for AwProxy module."""

import base64
from unittest.mock import Mock, patch

import httpx

from actingweb.aw_proxy import AwProxy


class TestTimeoutConfiguration:
    """Test timeout parameter configuration."""

    def test_init_default_timeout(self):
        """Test AwProxy uses default timeout of (5, 20)."""
        proxy = AwProxy()
        assert proxy.timeout == (5, 20)

    def test_init_custom_single_timeout(self):
        """Test AwProxy accepts single timeout value."""
        proxy = AwProxy(timeout=30)
        assert proxy.timeout == (30, 30)

    def test_init_custom_tuple_timeout(self):
        """Test AwProxy accepts tuple timeout value."""
        proxy = AwProxy(timeout=(3, 15))
        assert proxy.timeout == (3, 15)

    def test_init_custom_float_timeout(self):
        """Test AwProxy accepts float timeout value."""
        proxy = AwProxy(timeout=2.5)
        assert proxy.timeout == (2.5, 2.5)

    def test_init_custom_float_tuple_timeout(self):
        """Test AwProxy accepts tuple with float values."""
        proxy = AwProxy(timeout=(1.5, 10.5))
        assert proxy.timeout == (1.5, 10.5)

    def test_httpx_timeout_object_created(self):
        """Test AwProxy creates httpx.Timeout object with correct values."""
        proxy = AwProxy(timeout=(3, 15))
        assert isinstance(proxy._httpx_timeout, httpx.Timeout)
        assert proxy._httpx_timeout.connect == 3.0
        assert proxy._httpx_timeout.read == 15.0

    def test_httpx_timeout_from_single_value(self):
        """Test httpx.Timeout is correctly set from single timeout value."""
        proxy = AwProxy(timeout=30)
        assert proxy._httpx_timeout.connect == 30.0
        assert proxy._httpx_timeout.read == 30.0

    def test_sync_methods_use_configured_timeout(self):
        """Test sync methods use the configured timeout."""
        proxy = AwProxy(timeout=(7, 25))
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch(
            "actingweb.aw_proxy.requests.get", return_value=mock_response
        ) as mock_get:
            proxy.get_resource(path="test")

        # Verify timeout was passed correctly
        assert mock_get.call_args.kwargs["timeout"] == (7, 25)

    def test_sync_post_uses_configured_timeout(self):
        """Test sync POST method uses the configured timeout."""
        proxy = AwProxy(timeout=(4, 30))
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_response.headers = {}

        with patch(
            "actingweb.aw_proxy.requests.post", return_value=mock_response
        ) as mock_post:
            proxy.create_resource(path="test", params={"key": "value"})

        assert mock_post.call_args.kwargs["timeout"] == (4, 30)

    def test_sync_put_uses_configured_timeout(self):
        """Test sync PUT method uses the configured timeout."""
        proxy = AwProxy(timeout=(2, 15))
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch(
            "actingweb.aw_proxy.requests.put", return_value=mock_response
        ) as mock_put:
            proxy.change_resource(path="test", params={"key": "value"})

        assert mock_put.call_args.kwargs["timeout"] == (2, 15)

    def test_sync_delete_uses_configured_timeout(self):
        """Test sync DELETE method uses the configured timeout."""
        proxy = AwProxy(timeout=(3, 12))
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }

        mock_response = Mock()
        mock_response.status_code = 204
        mock_response.content = b""

        with patch(
            "actingweb.aw_proxy.requests.delete", return_value=mock_response
        ) as mock_delete:
            proxy.delete_resource(path="test")

        assert mock_delete.call_args.kwargs["timeout"] == (3, 12)


class TestAwProxyInitialization:
    """Test AwProxy initialization."""

    def test_init_with_trust_target(self):
        """Test AwProxy initialization with trust_target."""
        mock_trust = Mock()
        mock_trust.trust = {"baseuri": "https://peer.example.com", "secret": "token123"}
        mock_trust.id = "actor123"

        proxy = AwProxy(trust_target=mock_trust)

        assert proxy.trust == mock_trust
        assert proxy.actorid == "actor123"

    def test_init_with_peer_target_no_peerid(self):
        """Test AwProxy initialization with peer_target but no peerid."""
        mock_config = Mock()
        peer_target = {"id": "actor123", "peerid": None}

        proxy = AwProxy(peer_target=peer_target, config=mock_config)

        assert proxy.actorid == "actor123"
        assert proxy.trust is None

    def test_init_with_peer_target_and_peerid(self):
        """Test AwProxy initialization with peer_target and peerid."""
        mock_config = Mock()
        mock_trust_obj = Mock()
        mock_trust_data = {
            "baseuri": "https://peer.example.com",
            "secret": "token123",
        }
        mock_trust_obj.get.return_value = mock_trust_data

        peer_target = {"id": "actor123", "peerid": "peer456"}

        with patch("actingweb.aw_proxy.trust.Trust", return_value=mock_trust_obj):
            proxy = AwProxy(peer_target=peer_target, config=mock_config)

        assert proxy.actorid == "actor123"
        assert proxy.trust == mock_trust_data

    def test_init_with_peer_target_trust_not_found(self):
        """Test AwProxy initialization when trust relationship not found."""
        mock_config = Mock()
        mock_trust_obj = Mock()
        mock_trust_obj.get.return_value = {}  # Empty trust

        peer_target = {"id": "actor123", "peerid": "peer456"}

        with patch("actingweb.aw_proxy.trust.Trust", return_value=mock_trust_obj):
            proxy = AwProxy(peer_target=peer_target, config=mock_config)

        assert proxy.actorid == "actor123"
        assert proxy.trust is None

    def test_init_with_passphrase(self):
        """Test AwProxy initialization captures passphrase for Basic auth fallback."""
        mock_config = Mock()
        peer_target = {"id": "actor123", "peerid": None, "passphrase": "secret123"}

        proxy = AwProxy(peer_target=peer_target, config=mock_config)

        assert proxy.peer_passphrase == "secret123"

    def test_init_default_values(self):
        """Test AwProxy has correct default values."""
        proxy = AwProxy()

        assert proxy.last_response_code == 0
        assert proxy.last_response_message == 0
        assert proxy.last_location is None
        assert proxy.peer_passphrase is None


class TestBearerHeaders:
    """Test Bearer header generation."""

    def test_bearer_headers_with_trust(self):
        """Test _bearer_headers returns proper headers with trust."""
        mock_trust = Mock()
        mock_trust.trust = {"baseuri": "https://peer.example.com", "secret": "token123"}
        mock_trust.id = "actor123"

        proxy = AwProxy(trust_target=mock_trust)
        # Manually set trust since we're testing the method
        proxy.trust = {"secret": "token123"}

        headers = proxy._bearer_headers()

        # Check Authorization header is correct
        assert headers["Authorization"] == "Bearer token123"
        # Check correlation headers are present
        assert "X-Request-ID" in headers

    def test_bearer_headers_without_trust(self):
        """Test _bearer_headers returns empty dict without trust."""
        proxy = AwProxy()
        proxy.trust = None

        headers = proxy._bearer_headers()

        # Should still have correlation headers even without trust
        assert "Authorization" not in headers
        assert "X-Request-ID" in headers

    def test_bearer_headers_without_secret(self):
        """Test _bearer_headers returns empty dict when secret is missing."""
        proxy = AwProxy()
        proxy.trust = {"baseuri": "https://peer.example.com"}

        headers = proxy._bearer_headers()

        # Should still have correlation headers even without secret
        assert "Authorization" not in headers
        assert "X-Request-ID" in headers


class TestBasicHeaders:
    """Test Basic header generation."""

    def test_basic_headers_with_passphrase(self):
        """Test _basic_headers returns proper headers with passphrase."""
        mock_config = Mock()
        peer_target = {"id": "actor123", "peerid": None, "passphrase": "secret123"}

        proxy = AwProxy(peer_target=peer_target, config=mock_config)

        headers = proxy._basic_headers()

        # Expected: base64(trustee:secret123)
        expected_cred = base64.b64encode(b"trustee:secret123").decode("utf-8")
        assert headers["Authorization"] == f"Basic {expected_cred}"
        # Check correlation headers are present
        assert "X-Request-ID" in headers

    def test_basic_headers_without_passphrase(self):
        """Test _basic_headers returns empty dict without passphrase."""
        proxy = AwProxy()
        proxy.peer_passphrase = None

        headers = proxy._basic_headers()

        # Should still have correlation headers even without passphrase
        assert "Authorization" not in headers
        assert "X-Request-ID" in headers


class TestGetResource:
    """Test sync get_resource method."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        return proxy

    def test_get_resource_no_path(self):
        """Test get_resource returns None without path."""
        proxy = self._create_proxy_with_trust()

        result = proxy.get_resource(path=None)

        assert result is None

    def test_get_resource_empty_path(self):
        """Test get_resource returns None with empty path."""
        proxy = self._create_proxy_with_trust()

        result = proxy.get_resource(path="")

        assert result is None

    def test_get_resource_no_trust(self):
        """Test get_resource returns None without trust."""
        proxy = AwProxy()
        proxy.trust = None

        result = proxy.get_resource(path="some/path")

        assert result is None

    def test_get_resource_no_baseuri(self):
        """Test get_resource returns None when trust has no baseuri."""
        proxy = AwProxy()
        # Both baseuri and secret must be present for the check to pass
        proxy.trust = {"baseuri": None, "secret": "token123"}

        result = proxy.get_resource(path="some/path")

        assert result is None

    def test_get_resource_success(self):
        """Test get_resource returns JSON on success."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"key": "value"}'
        mock_response.json.return_value = {"key": "value"}

        with patch("actingweb.aw_proxy.requests.get", return_value=mock_response):
            result = proxy.get_resource(path="properties/config")

        assert result == {"key": "value"}
        assert proxy.last_response_code == 200

    def test_get_resource_with_params(self):
        """Test get_resource appends query parameters."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch(
            "actingweb.aw_proxy.requests.get", return_value=mock_response
        ) as mock_get:
            proxy.get_resource(path="search", params={"q": "test"})

        # Verify URL includes query params
        call_args = mock_get.call_args
        assert "q=test" in call_args.kwargs["url"]

    def test_get_resource_exception_returns_error(self):
        """Test get_resource returns error dict on exception."""
        proxy = self._create_proxy_with_trust()

        with patch(
            "actingweb.aw_proxy.requests.get", side_effect=Exception("Network error")
        ):
            result = proxy.get_resource(path="some/path")

        assert result is not None
        assert result["error"]["code"] == 408
        assert proxy.last_response_code == 408

    def test_get_resource_retries_with_basic_on_401(self):
        """Test get_resource retries with Basic auth on 401."""
        proxy = self._create_proxy_with_trust()
        proxy.peer_passphrase = "secret123"

        mock_bearer_response = Mock()
        mock_bearer_response.status_code = 401
        mock_bearer_response.content = b"Unauthorized"

        mock_basic_response = Mock()
        mock_basic_response.status_code = 200
        mock_basic_response.content = b'{"success": true}'
        mock_basic_response.json.return_value = {"success": True}

        with patch("actingweb.aw_proxy.requests.get") as mock_get:
            mock_get.side_effect = [mock_bearer_response, mock_basic_response]
            result = proxy.get_resource(path="some/path")

        assert result == {"success": True}
        assert mock_get.call_count == 2


class TestCreateResource:
    """Test sync create_resource method."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        return proxy

    def test_create_resource_no_path(self):
        """Test create_resource returns None without path."""
        proxy = self._create_proxy_with_trust()

        result = proxy.create_resource(path=None)

        assert result is None

    def test_create_resource_no_trust(self):
        """Test create_resource returns None without trust."""
        proxy = AwProxy()
        proxy.trust = None

        result = proxy.create_resource(path="some/path")

        assert result is None

    def test_create_resource_success(self):
        """Test create_resource returns JSON on success."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.content = b'{"id": "new_id"}'
        mock_response.json.return_value = {"id": "new_id"}
        mock_response.headers = {"Location": "https://peer.example.com/new_id"}

        with patch("actingweb.aw_proxy.requests.post", return_value=mock_response):
            result = proxy.create_resource(path="items", params={"name": "test"})

        assert result == {"id": "new_id"}
        assert proxy.last_response_code == 201
        assert proxy.last_location == "https://peer.example.com/new_id"

    def test_create_resource_no_location_header(self):
        """Test create_resource handles missing Location header."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_response.headers = {}

        with patch("actingweb.aw_proxy.requests.post", return_value=mock_response):
            proxy.create_resource(path="items")

        assert proxy.last_location is None


class TestChangeResource:
    """Test sync change_resource method."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        return proxy

    def test_change_resource_no_path(self):
        """Test change_resource returns None without path."""
        proxy = self._create_proxy_with_trust()

        result = proxy.change_resource(path=None)

        assert result is None

    def test_change_resource_no_trust(self):
        """Test change_resource returns None without trust."""
        proxy = AwProxy()
        proxy.trust = None

        result = proxy.change_resource(path="some/path")

        assert result is None

    def test_change_resource_success(self):
        """Test change_resource returns JSON on success."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"updated": true}'
        mock_response.json.return_value = {"updated": True}

        with patch("actingweb.aw_proxy.requests.put", return_value=mock_response):
            result = proxy.change_resource(path="items/123", params={"name": "updated"})

        assert result == {"updated": True}
        assert proxy.last_response_code == 200


class TestDeleteResource:
    """Test sync delete_resource method."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        return proxy

    def test_delete_resource_no_path(self):
        """Test delete_resource returns None without path."""
        proxy = self._create_proxy_with_trust()

        result = proxy.delete_resource(path=None)

        assert result is None

    def test_delete_resource_no_trust(self):
        """Test delete_resource returns None without trust."""
        proxy = AwProxy()
        proxy.trust = None

        result = proxy.delete_resource(path="some/path")

        assert result is None

    def test_delete_resource_success(self):
        """Test delete_resource executes DELETE request."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 204
        mock_response.content = b""

        with patch(
            "actingweb.aw_proxy.requests.delete", return_value=mock_response
        ) as mock_delete:
            proxy.delete_resource(path="items/123")

        mock_delete.assert_called_once()
        assert proxy.last_response_code == 204


class TestMaybeRetryWithBasic:
    """Test Basic auth retry logic."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust and passphrase."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        proxy.peer_passphrase = "secret123"
        return proxy

    def test_maybe_retry_without_passphrase(self):
        """Test _maybe_retry_with_basic returns None without passphrase."""
        proxy = AwProxy()
        proxy.peer_passphrase = None

        result = proxy._maybe_retry_with_basic("GET", "https://example.com/path")

        assert result is None

    def test_maybe_retry_get(self):
        """Test _maybe_retry_with_basic handles GET."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 200

        with patch(
            "actingweb.aw_proxy.requests.get", return_value=mock_response
        ) as mock_get:
            result = proxy._maybe_retry_with_basic("GET", "https://example.com/path")

        assert result == mock_response
        mock_get.assert_called_once()

    def test_maybe_retry_post(self):
        """Test _maybe_retry_with_basic handles POST."""
        proxy = self._create_proxy_with_trust()

        mock_response = Mock()
        mock_response.status_code = 201

        with patch(
            "actingweb.aw_proxy.requests.post", return_value=mock_response
        ) as mock_post:
            result = proxy._maybe_retry_with_basic(
                "POST", "https://example.com/path", data='{"key": "value"}'
            )

        assert result == mock_response
        mock_post.assert_called_once()

    def test_maybe_retry_exception(self):
        """Test _maybe_retry_with_basic returns None on exception."""
        proxy = self._create_proxy_with_trust()

        with patch("actingweb.aw_proxy.requests.get", side_effect=Exception("Error")):
            result = proxy._maybe_retry_with_basic("GET", "https://example.com/path")

        assert result is None


class TestURLConstruction:
    """Test URL construction in resource methods."""

    def _create_proxy_with_trust(self) -> AwProxy:
        """Helper to create proxy with valid trust."""
        proxy = AwProxy()
        proxy.trust = {
            "baseuri": "https://peer.example.com/",
            "secret": "token123",
        }
        return proxy

    def test_url_strips_trailing_slashes(self):
        """Test URL construction handles trailing slashes properly."""
        proxy = self._create_proxy_with_trust()
        assert proxy.trust is not None
        proxy.trust["baseuri"] = "https://peer.example.com/"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch(
            "actingweb.aw_proxy.requests.get", return_value=mock_response
        ) as mock_get:
            proxy.get_resource(path="/path/to/resource/")

        call_args = mock_get.call_args
        # Should be clean URL without double slashes
        assert call_args.kwargs["url"] == "https://peer.example.com/path/to/resource"

    def test_url_handles_no_trailing_slash(self):
        """Test URL construction when baseuri has no trailing slash."""
        proxy = self._create_proxy_with_trust()
        assert proxy.trust is not None
        proxy.trust["baseuri"] = "https://peer.example.com"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"{}"
        mock_response.json.return_value = {}

        with patch(
            "actingweb.aw_proxy.requests.get", return_value=mock_response
        ) as mock_get:
            proxy.get_resource(path="path/to/resource")

        call_args = mock_get.call_args
        assert call_args.kwargs["url"] == "https://peer.example.com/path/to/resource"
