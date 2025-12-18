"""Tests for auth module."""

import base64
from unittest.mock import Mock, patch

from actingweb.auth import (
    Auth,
    add_auth_response,
    check_and_verify_auth,
)


class TestAuthClassInitialization:
    """Test Auth class initialization."""

    def test_auth_init_with_valid_actor_id(self):
        """Test Auth initialization with a valid actor ID."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor_123"
            mock_actor.passphrase = "test_passphrase"
            mock_actor.creator = "test@example.com"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor_123", auth_type="basic", config=mock_config)

            assert auth.actor == mock_actor
            assert auth.config == mock_config
            assert auth.type == "basic"
            assert auth.realm == "TestRealm"
            assert auth.token is None
            assert auth.trust is None

    def test_auth_init_with_nonexistent_actor(self):
        """Test Auth initialization when actor doesn't exist."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = None  # Actor not found
            mock_actor_class.return_value = mock_actor

            auth = Auth("nonexistent", auth_type="basic", config=mock_config)

            assert auth.actor is None

    def test_auth_init_with_basic_type(self):
        """Test Auth initialization with basic auth type sets realm."""
        mock_config = Mock()
        mock_config.auth_realm = "MyRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", auth_type="basic", config=mock_config)

            assert auth.type == "basic"
            assert auth.realm == "MyRealm"

    def test_auth_init_default_response_values(self):
        """Test Auth initialization sets correct default response."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)

            assert auth.response["code"] == 403
            assert auth.response["text"] == "Forbidden"
            assert auth.response["headers"] == {}

    def test_auth_init_default_acl_values(self):
        """Test Auth initialization sets correct default ACL."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)

            assert auth.acl["authenticated"] is False
            assert auth.acl["authorised"] is False
            assert auth.acl["rights"] == ""
            assert auth.acl["relationship"] is None
            assert auth.acl["peerid"] == ""
            assert auth.acl["approved"] is False

    def test_auth_init_without_config_creates_default(self):
        """Test Auth initialization without config creates default Config."""
        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            with patch("actingweb.auth.config_class.Config") as mock_config_class:
                mock_config = Mock()
                mock_config.auth_realm = "DefaultRealm"
                mock_config_class.return_value = mock_config
                mock_actor = Mock()
                mock_actor.id = "test_actor"
                mock_actor_class.return_value = mock_actor

                auth = Auth("test_actor", auth_type="basic", config=None)

                mock_config_class.assert_called_once()
                assert auth.config == mock_config


class TestBasicAuthentication:
    """Test basic authentication methods."""

    def _create_auth_with_actor(
        self, passphrase: str = "secret123", creator: str = "user@example.com"
    ) -> tuple[Auth, Mock]:
        """Helper to create Auth instance with mocked actor."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor.passphrase = passphrase
            mock_actor.creator = creator
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", auth_type="basic", config=mock_config)

        return auth, mock_actor

    def test_check_basic_auth_creator_success(self):
        """Test successful basic auth with correct credentials."""
        auth, _ = self._create_auth_with_actor(
            passphrase="secret123", creator="user@example.com"
        )

        # Create mock request with valid basic auth
        credentials = base64.b64encode(b"user@example.com:secret123").decode("utf-8")
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Basic {credentials}"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        # The private method is __check_basic_auth_creator which is name-mangled
        auth.check_authentication(mock_appreq, "/test")

        assert auth.acl["authenticated"] is True
        assert auth.acl["relationship"] == "creator"
        assert auth.response["code"] == 200

    def test_check_basic_auth_wrong_username(self):
        """Test basic auth fails with wrong username."""
        auth, _ = self._create_auth_with_actor(
            passphrase="secret123", creator="user@example.com"
        )

        credentials = base64.b64encode(b"wrong@example.com:secret123").decode("utf-8")
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Basic {credentials}"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        auth.check_authentication(mock_appreq, "/test")

        assert auth.acl["authenticated"] is False
        assert auth.response["code"] == 403

    def test_check_basic_auth_wrong_password(self):
        """Test basic auth fails with wrong password."""
        auth, _ = self._create_auth_with_actor(
            passphrase="secret123", creator="user@example.com"
        )

        credentials = base64.b64encode(b"user@example.com:wrongpass").decode("utf-8")
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Basic {credentials}"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        auth.check_authentication(mock_appreq, "/test")

        assert auth.acl["authenticated"] is False
        assert auth.response["code"] == 403

    def test_check_basic_auth_missing_header(self):
        """Test basic auth returns 401 when no Authorization header."""
        auth, _ = self._create_auth_with_actor()

        mock_request = Mock()
        mock_request.headers = {}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        auth.check_authentication(mock_appreq, "/test")

        assert auth.response["code"] == 401
        assert "WWW-Authenticate" in auth.response["headers"]

    def test_check_basic_auth_non_basic_header(self):
        """Test basic auth fails with non-Basic auth header."""
        auth, _ = self._create_auth_with_actor()

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Digest xyz123"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        auth.check_authentication(mock_appreq, "/test")

        # Should fail since Digest auth is not supported for basic type
        assert auth.response["code"] == 403


class TestTokenAuthentication:
    """Test token/bearer authentication methods."""

    def _create_auth_with_config(self) -> tuple[Auth, Mock]:
        """Helper to create Auth instance for token testing."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor.passphrase = "passphrase"
            mock_actor.creator = "user@example.com"
            mock_actor.store = Mock()
            mock_actor.store.trustee_root = None  # Not a trustee
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", auth_type="basic", config=mock_config)

        return auth, mock_config

    def test_check_token_auth_with_valid_bearer(self):
        """Test token auth with valid bearer token."""
        auth, _ = self._create_auth_with_config()

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer valid_secret_token_12345"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        # Mock trust lookup
        mock_trust_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "secret": "valid_secret_token_12345",
            "approved": True,
        }

        with patch("actingweb.auth.trust.Trust") as mock_trust_class:
            mock_trust = Mock()
            mock_trust.get.return_value = mock_trust_data
            mock_trust_class.return_value = mock_trust

            result = auth.check_token_auth(mock_appreq)

            assert result is True
            assert auth.acl["authenticated"] is True
            assert auth.acl["relationship"] == "friend"
            assert auth.acl["peerid"] == "peer123"

    def test_check_token_auth_missing_header(self):
        """Test token auth returns False when no Authorization header."""
        auth, _ = self._create_auth_with_config()

        mock_request = Mock()
        mock_request.headers = {}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        result = auth.check_token_auth(mock_appreq)

        assert result is False

    def test_check_token_auth_invalid_format(self):
        """Test token auth returns False with invalid header format."""
        auth, _ = self._create_auth_with_config()

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Invalid format here"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        result = auth.check_token_auth(mock_appreq)

        assert result is False

    def test_check_token_auth_basic_not_bearer(self):
        """Test token auth returns False when Basic auth is used."""
        auth, _ = self._create_auth_with_config()

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        result = auth.check_token_auth(mock_appreq)

        assert result is False


class TestOAuth2TokenDetection:
    """Test OAuth2 token detection heuristics."""

    def _create_auth(self) -> Auth:
        """Helper to create Auth instance."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)

        return auth

    def test_looks_like_oauth2_token_hex_trust_secret(self):
        """Test hex trust secrets are detected as non-OAuth2."""
        auth = self._create_auth()

        # 40-char hex string (SHA-1 trust secret)
        hex_token = "a" * 40
        result = auth._looks_like_oauth2_token(hex_token)

        assert result is False

    def test_looks_like_oauth2_token_github_prefix(self):
        """Test GitHub tokens are detected as OAuth2."""
        auth = self._create_auth()

        github_tokens = [
            "gho_1234567890abcdef1234567890abcdef12345678",
            "ghu_1234567890abcdef1234567890abcdef12345678",
            "ghs_1234567890abcdef1234567890abcdef12345678",
            "ghr_1234567890abcdef1234567890abcdef12345678",
        ]

        for token in github_tokens:
            result = auth._looks_like_oauth2_token(token)
            assert result is True, f"GitHub token {token[:4]}... should be detected"

    def test_looks_like_oauth2_token_jwt_format(self):
        """Test JWT tokens are detected as OAuth2."""
        auth = self._create_auth()

        # JWT has 3 dot-separated parts
        jwt_token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
        result = auth._looks_like_oauth2_token(jwt_token)

        assert result is True

    def test_looks_like_oauth2_token_short_token(self):
        """Test very short tokens are not OAuth2."""
        auth = self._create_auth()

        result = auth._looks_like_oauth2_token("abc123")

        assert result is False

    def test_looks_like_oauth2_token_long_token(self):
        """Test long tokens are detected as potential OAuth2."""
        auth = self._create_auth()

        # Token longer than 80 chars
        long_token = "x" * 100
        result = auth._looks_like_oauth2_token(long_token)

        assert result is True

    def test_looks_like_oauth2_token_empty(self):
        """Test empty token returns False."""
        auth = self._create_auth()

        assert auth._looks_like_oauth2_token("") is False
        assert auth._looks_like_oauth2_token(None) is False  # type: ignore


class TestAuthorisation:
    """Test authorisation/ACL methods."""

    def _create_authenticated_auth(
        self, relationship: str = "creator", peerid: str = "", approved: bool = True
    ) -> Auth:
        """Helper to create authenticated Auth instance."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"
        mock_config.access = [
            ("creator", "properties/", "GET,POST,PUT,DELETE", "a"),
            ("friend", "properties/", "GET", "r"),
            ("any", "meta/", "GET", "r"),
            ("", "trust/", "DELETE", "a"),  # Allow any authenticated user to delete trust
        ]

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)
            auth.acl["authenticated"] = True
            auth.acl["relationship"] = relationship
            auth.acl["peerid"] = peerid
            auth.acl["approved"] = approved

        return auth

    def test_check_authorisation_creator_access(self):
        """Test creator has access to properties."""
        auth = self._create_authenticated_auth(relationship="creator")

        result = auth.check_authorisation(
            path="properties", subpath="config", method="GET"
        )

        assert result is True
        assert auth.acl["rights"] == "a"

    def test_check_authorisation_peer_access(self):
        """Test friend peer has read access to properties."""
        auth = self._create_authenticated_auth(
            relationship="friend", peerid="peer123", approved=True
        )

        result = auth.check_authorisation(
            path="properties", subpath="public", method="GET"
        )

        assert result is True
        assert auth.acl["rights"] == "r"

    def test_check_authorisation_denied_unapproved(self):
        """Test unapproved peer is denied access."""
        auth = self._create_authenticated_auth(
            relationship="friend", peerid="peer123", approved=False
        )

        result = auth.check_authorisation(
            path="properties", subpath="data", method="GET", approved=True
        )

        assert result is False

    def test_check_authorisation_allows_trust_delete_unapproved(self):
        """Test DELETE on trust is allowed even for unapproved relationships."""
        auth = self._create_authenticated_auth(
            relationship="friend", peerid="peer123", approved=False
        )

        # Trust DELETE should be allowed regardless of approval status
        result = auth.check_authorisation(
            path="trust", subpath="", method="DELETE", approved=True
        )

        assert result is True

    def test_connection_hint_from_path_mcp(self):
        """Test MCP path returns 'mcp' hint."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)
            result = auth._connection_hint_from_path("/mcp/endpoint")

            assert result == "mcp"

    def test_connection_hint_from_path_trust(self):
        """Test trust path returns 'trust' hint."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)
            result = auth._connection_hint_from_path("/trust/friend")

            assert result == "trust"

    def test_connection_hint_from_path_subscription(self):
        """Test subscription path returns 'subscription' hint."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)
            result = auth._connection_hint_from_path("/subscriptions/peer123")

            assert result == "subscription"

    def test_connection_hint_from_path_unknown(self):
        """Test unknown path returns None."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)
            result = auth._connection_hint_from_path("/properties/config")

            assert result is None


class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_add_auth_response_sets_status(self):
        """Test add_auth_response sets HTTP status."""
        mock_response = Mock()
        mock_appreq = Mock()
        mock_appreq.response = mock_response

        auth_obj = Mock()
        auth_obj.response = {"code": 200, "text": "Ok", "headers": {}}
        auth_obj.redirect = None

        result = add_auth_response(appreq=mock_appreq, auth_obj=auth_obj)

        assert result is True
        mock_response.set_status.assert_called_once_with(200, "Ok")

    def test_add_auth_response_handles_redirect(self):
        """Test add_auth_response handles 302 redirect."""
        mock_response = Mock()
        mock_appreq = Mock()
        mock_appreq.response = mock_response

        auth_obj = Mock()
        auth_obj.response = {"code": 302, "text": "Redirecting", "headers": {}}
        auth_obj.redirect = "https://oauth.example.com/auth"

        result = add_auth_response(appreq=mock_appreq, auth_obj=auth_obj)

        assert result is True
        mock_response.set_redirect.assert_called_once_with(
            url="https://oauth.example.com/auth"
        )

    def test_add_auth_response_sets_headers(self):
        """Test add_auth_response sets custom headers."""
        mock_response = Mock()
        mock_response.headers = {}
        mock_appreq = Mock()
        mock_appreq.response = mock_response

        auth_obj = Mock()
        auth_obj.response = {
            "code": 401,
            "text": "Unauthorized",
            "headers": {"WWW-Authenticate": 'Basic realm="Test"'},
        }
        auth_obj.redirect = None

        result = add_auth_response(appreq=mock_appreq, auth_obj=auth_obj)

        assert result is True
        assert mock_response.headers["WWW-Authenticate"] == 'Basic realm="Test"'

    def test_add_auth_response_returns_false_without_appreq(self):
        """Test add_auth_response returns False without appreq."""
        auth_obj = Mock()
        auth_obj.response = {"code": 200, "text": "Ok", "headers": {}}

        result = add_auth_response(appreq=None, auth_obj=auth_obj)

        assert result is False

    def test_add_auth_response_returns_false_without_auth_obj(self):
        """Test add_auth_response returns False without auth_obj."""
        mock_appreq = Mock()

        result = add_auth_response(appreq=mock_appreq, auth_obj=None)

        assert result is False

    def test_check_and_verify_auth_success(self):
        """Test check_and_verify_auth returns authenticated result."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        mock_request = Mock()
        credentials = base64.b64encode(b"user@example.com:secret").decode("utf-8")
        mock_request.headers = {"Authorization": f"Basic {credentials}"}
        mock_appreq = Mock()
        mock_appreq.request = mock_request

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor.creator = "user@example.com"
            mock_actor.passphrase = "secret"
            mock_actor_class.return_value = mock_actor

            result = check_and_verify_auth(
                appreq=mock_appreq, actor_id="test_actor", config=mock_config
            )

            assert result["authenticated"] is True
            assert result["actor"] == mock_actor
            assert result["response"]["code"] == 200

    def test_check_and_verify_auth_actor_not_found(self):
        """Test check_and_verify_auth returns 404 when actor not found."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        mock_appreq = Mock()
        mock_appreq.request = Mock()
        mock_appreq.request.headers = {}

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = None  # Actor not found
            mock_actor_class.return_value = mock_actor

            result = check_and_verify_auth(
                appreq=mock_appreq, actor_id="nonexistent", config=mock_config
            )

            assert result["authenticated"] is False
            assert result["actor"] is None
            assert result["response"]["code"] == 404


class TestTrustUsageRecording:
    """Test trust usage metadata recording."""

    def test_record_trust_usage_updates_timestamp(self):
        """Test _record_trust_usage updates last_accessed."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)

            trust_record = {
                "peerid": "peer123",
                "last_accessed": None,
                "created_at": "2025-01-01T00:00:00",
            }

            with patch("actingweb.auth.trust.Trust") as mock_trust_class:
                mock_trust = Mock()
                mock_trust_class.return_value = mock_trust

                auth._record_trust_usage(trust_record, via_hint="mcp")

                # Should have updated last_accessed in the record
                assert trust_record["last_accessed"] is not None

    def test_record_trust_usage_handles_missing_peerid(self):
        """Test _record_trust_usage handles missing peerid gracefully."""
        mock_config = Mock()
        mock_config.auth_realm = "TestRealm"

        with patch("actingweb.auth.actor.Actor") as mock_actor_class:
            mock_actor = Mock()
            mock_actor.id = "test_actor"
            mock_actor_class.return_value = mock_actor

            auth = Auth("test_actor", config=mock_config)

            trust_record = {"last_accessed": None}  # No peerid

            # Should not raise exception
            auth._record_trust_usage(trust_record)
