"""Tests for trust module core functionality."""

from unittest.mock import Mock, patch

from actingweb.trust import Trust, Trusts, canonical_connection_method


class TestCanonicalConnectionMethod:
    """Test canonical_connection_method function."""

    def test_oauth2_variants_normalize_to_oauth(self):
        """Test OAuth2 variants all normalize to 'oauth'."""
        oauth_variants = ["oauth2", "OAuth2", "OAUTH2", "oauth2_spa", "oauth2_mcp"]
        for variant in oauth_variants:
            result = canonical_connection_method(variant)
            assert result == "oauth", f"{variant} should normalize to 'oauth'"

    def test_known_methods_pass_through(self):
        """Test known connection methods pass through unchanged."""
        known_methods = ["trust", "subscription", "mcp"]
        for method in known_methods:
            result = canonical_connection_method(method)
            assert result == method

    def test_oauth_normalizes_to_oauth(self):
        """Test 'oauth' stays as 'oauth'."""
        result = canonical_connection_method("oauth")
        assert result == "oauth"

    def test_unknown_methods_returned_as_is(self):
        """Test unknown methods are returned unchanged."""
        unknown = "custom_auth_method"
        result = canonical_connection_method(unknown)
        assert result == unknown

    def test_none_input_returns_none(self):
        """Test None input returns None."""
        result = canonical_connection_method(None)
        assert result is None

    def test_empty_string_returns_none(self):
        """Test empty string returns None."""
        result = canonical_connection_method("")
        assert result is None

    def test_non_string_input_returns_none(self):
        """Test non-string input returns None."""
        result = canonical_connection_method(123)  # type: ignore
        assert result is None


class TestTrustClassInitialization:
    """Test Trust class initialization."""

    def test_trust_init_with_actor_and_peerid(self):
        """Test Trust initialization with actor_id and peerid."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_db_trust.get.return_value = {}
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)

        assert trust.actor_id == "test_actor"
        assert trust.peerid == "peer123"
        assert trust.config == mock_config

    def test_trust_init_with_actor_and_token(self):
        """Test Trust initialization with actor_id and token."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_db_trust.get.return_value = {}
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", token="secret_token_123", config=mock_config)

        assert trust.actor_id == "test_actor"
        assert trust.token == "secret_token_123"

    def test_trust_init_no_actor_id(self):
        """Test Trust initialization without actor_id."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id=None, peerid="peer123", config=mock_config)

        assert trust.actor_id is None
        assert trust.peerid == "peer123"

    def test_trust_init_defaults(self):
        """Test Trust initialization default values - trust is empty dict."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_db_trust.get.return_value = {}
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)

        # Trust.trust starts as {} and get() is called during init
        assert trust.trust == {}
        assert trust.token is None

    def test_trust_init_without_peerid_or_token(self):
        """Test Trust initialization without peerid or token returns early."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", config=mock_config)

        # Without peerid or token, get() is not called
        assert trust.peerid is None
        assert trust.token is None


class TestTrustCRUD:
    """Test Trust CRUD operations."""

    def _create_trust_with_mock(self) -> tuple[Trust, Mock, Mock]:
        """Helper to create Trust with mocked db."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_db_trust.get.return_value = {}  # Empty initially
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        return trust, mock_db_trust, mock_config

    def test_trust_get_returns_relationship(self):
        """Test trust.get() returns existing relationship."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "secret": "secret123",
            "approved": "true",
            "baseuri": "https://peer.example.com/peer123",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.get()

        assert result is not None
        assert result["relationship"] == "friend"
        assert result["approved"] == "true"

    def test_trust_get_nonexistent_returns_empty(self):
        """Test trust.get() returns empty dict when not found."""
        trust, mock_db, _ = self._create_trust_with_mock()
        mock_db.get.return_value = {}

        result = trust.get()

        assert result == {}

    def test_trust_create_establishes_relationship(self):
        """Test trust.create() establishes new relationship."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_db_trust.get.return_value = {}
        mock_db_trust.create.return_value = True
        mock_db_trust.is_token_in_db.return_value = False
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust
        mock_config.default_relationship = "friend"
        mock_config.new_token.return_value = "generated_token_123"

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.create(
            relationship="friend",
            peer_type="urn:actingweb:test:peer",
            baseuri="https://peer.example.com/peer123",
            secret="secret123",
            desc="Test peer",
        )

        assert result is True
        mock_db_trust.create.assert_called_once()

    def test_trust_delete_removes_relationship(self):
        """Test trust.delete() removes the trust relationship."""
        trust, mock_db, _ = self._create_trust_with_mock()
        mock_db.delete.return_value = True

        result = trust.delete()

        assert result is True
        mock_db.delete.assert_called_once()

    def test_trust_modify_updates_fields(self):
        """Test trust.modify() updates relationship fields."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_trust_data = {"peerid": "peer123", "relationship": "friend"}
        mock_db_trust.get.return_value = mock_trust_data
        mock_db_trust.modify.return_value = True
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.modify(
            baseuri="https://new.example.com/peer123", approved=True
        )

        assert result is True
        mock_db_trust.modify.assert_called_once()

    def test_trust_get_by_token(self):
        """Test Trust can retrieve relationship by token."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "secret": "secret_token_xyz",
            "approved": "true",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", token="secret_token_xyz", config=mock_config)
        result = trust.get()

        assert result is not None
        assert result["secret"] == "secret_token_xyz"
        assert trust.token == "secret_token_xyz"

    def test_trust_delete_cleans_oauth2_client(self):
        """Test trust.delete() cleans up OAuth2 client registration."""
        mock_config = Mock()
        mock_db_trust = Mock()

        # Setup trust data with oauth2 client_id in peerid format
        mock_trust_data = {
            "peerid": "oauth2_client:user@example.com:mcp_client_abc123",
            "relationship": "friend",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_db_trust.delete.return_value = True
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="oauth2_client:user@example.com:mcp_client_abc123", config=mock_config)

        # Mock OAuth2 client registry - patch it at the location it's imported in the trust module
        with patch("actingweb.oauth2_server.client_registry.get_mcp_client_registry") as mock_get_registry:
            mock_registry = Mock()
            mock_get_registry.return_value = mock_registry

            result = trust.delete()

            assert result is True
            # OAuth2 client should be deleted
            mock_registry.delete_client.assert_called_once()


class TestTrustsCollection:
    """Test Trusts collection class."""

    def test_trusts_init_with_actor_id(self):
        """Test Trusts initialization with actor_id."""
        mock_config = Mock()
        mock_db_trust_list = Mock()
        mock_db_trust_list.fetch.return_value = {}
        mock_config.DbTrust.DbTrustList.return_value = mock_db_trust_list

        trusts = Trusts(actor_id="test_actor", config=mock_config)

        assert trusts.actor_id == "test_actor"

    def test_trusts_init_without_actor_id(self):
        """Test Trusts initialization without actor_id."""
        mock_config = Mock()

        trusts = Trusts(actor_id=None, config=mock_config)

        assert trusts.actor_id is None
        # Should gracefully handle None actor_id

    def test_trusts_fetch_retrieves_all(self):
        """Test trusts.fetch() retrieves all relationships."""
        mock_config = Mock()
        mock_db_trust_list = Mock()

        mock_trusts = {
            "peer1": {"peerid": "peer1", "relationship": "friend"},
            "peer2": {"peerid": "peer2", "relationship": "colleague"},
        }
        mock_db_trust_list.fetch.return_value = mock_trusts
        mock_config.DbTrust.DbTrustList.return_value = mock_db_trust_list

        trusts = Trusts(actor_id="test_actor", config=mock_config)
        result = trusts.fetch()

        assert result == mock_trusts
        assert result is not None and len(result) == 2

    def test_trusts_delete_removes_all(self):
        """Test trusts.delete() removes all relationships."""
        mock_config = Mock()
        mock_db_trust_list = Mock()
        mock_db_trust_list.fetch.return_value = {}
        mock_db_trust_list.delete.return_value = True
        mock_config.DbTrust.DbTrustList.return_value = mock_db_trust_list

        trusts = Trusts(actor_id="test_actor", config=mock_config)
        result = trusts.delete()

        assert result is True
        mock_db_trust_list.delete.assert_called_once()


class TestTrustApproval:
    """Test trust approval flow."""

    def test_trust_approve_updates_status(self):
        """Test approving a trust updates its status."""
        mock_config = Mock()
        mock_db_trust = Mock()
        mock_trust_data = {"peerid": "peer123", "relationship": "friend", "approved": "false"}
        mock_db_trust.get.return_value = mock_trust_data
        mock_db_trust.modify.return_value = True
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.modify(approved=True)

        assert result is True
        # Verify approved was passed to modify
        call_kwargs = mock_db_trust.modify.call_args.kwargs
        assert call_kwargs["approved"] is True


class TestTrustMetadata:
    """Test trust metadata tracking."""

    def test_trust_created_at_timestamp(self):
        """Test trust records created_at timestamp."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "created_at": "2025-01-01T00:00:00",
            "last_accessed": "2025-01-15T12:00:00",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.get()

        assert result is not None
        assert "created_at" in result
        assert "last_accessed" in result

    def test_trust_connection_method_stored(self):
        """Test trust records connection method."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "connection_method": "oauth",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="peer123", config=mock_config)
        result = trust.get()

        assert result is not None
        assert result["connection_method"] == "oauth"


class TestTrustOAuth2Detection:
    """Test OAuth2 client trust detection."""

    def test_is_oauth2_client_trust_by_peerid(self):
        """Test _is_oauth2_client_trust detects OAuth2 client by peerid format."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "oauth2_client:user@example.com:mcp_client_123",
            "relationship": "friend",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="oauth2_client:user@example.com:mcp_client_123", config=mock_config)

        assert trust._is_oauth2_client_trust() is True

    def test_is_oauth2_client_trust_by_established_via(self):
        """Test _is_oauth2_client_trust detects OAuth2 client by established_via."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "some_peer",
            "relationship": "friend",
            "established_via": "oauth2_client",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="some_peer", config=mock_config)

        assert trust._is_oauth2_client_trust() is True

    def test_is_oauth2_client_trust_regular_trust(self):
        """Test _is_oauth2_client_trust returns False for regular trusts."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "regular_peer",
            "relationship": "friend",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="regular_peer", config=mock_config)

        assert trust._is_oauth2_client_trust() is False

    def test_extract_client_id_from_peerid(self):
        """Test _extract_client_id_from_peerid extracts client_id."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "oauth2_client:user@example.com:mcp_client_abc123",
            "relationship": "friend",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="oauth2_client:user@example.com:mcp_client_abc123", config=mock_config)

        client_id = trust._extract_client_id_from_peerid()
        assert client_id == "mcp_client_abc123"

    def test_extract_client_id_from_regular_peerid(self):
        """Test _extract_client_id_from_peerid returns None for regular peerids."""
        mock_config = Mock()
        mock_db_trust = Mock()

        mock_trust_data = {
            "peerid": "regular_peer",
            "relationship": "friend",
        }
        mock_db_trust.get.return_value = mock_trust_data
        mock_config.DbTrust.DbTrust.return_value = mock_db_trust

        trust = Trust(actor_id="test_actor", peerid="regular_peer", config=mock_config)

        client_id = trust._extract_client_id_from_peerid()
        assert client_id is None
