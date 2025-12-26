"""Tests for constants module."""

from actingweb.constants import (
    AUTHORIZATION_HEADER,
    CONTENT_TYPE_HEADER,
    DEFAULT_COOKIE_MAX_AGE,
    DEFAULT_CREATOR,
    DEFAULT_FETCH_DEADLINE,
    DEFAULT_REFRESH_TOKEN_EXPIRY,
    DEFAULT_RELATIONSHIP,
    INDEX_TTL_BUFFER,
    JSON_CONTENT_TYPE,
    LOCATION_HEADER,
    MCP_ACCESS_TOKEN_TTL,
    MCP_AUTH_CODE_TTL,
    MCP_REFRESH_TOKEN_TTL,
    MINIMUM_TOKEN_ENTROPY,
    OAUTH_SESSION_TTL,
    OAUTH_TOKEN_COOKIE,
    SPA_ACCESS_TOKEN_TTL,
    SPA_REFRESH_TOKEN_TTL,
    TRUSTEE_CREATOR,
    AuthType,
    DatabaseType,
    Environment,
    HttpMethod,
    ResponseCode,
    SubscriptionGranularity,
    TrustRelationship,
)


class TestEnums:
    """Test enum classes."""

    def test_auth_type_enum(self):
        """Test AuthType enum values."""
        assert AuthType.BASIC.value == "basic"
        assert AuthType.OAUTH.value == "oauth"
        assert AuthType.NONE.value == "none"

        # Test enum membership
        assert AuthType.BASIC in AuthType
        assert "invalid" not in [auth.value for auth in AuthType]

    def test_http_method_enum(self):
        """Test HttpMethod enum values."""
        assert HttpMethod.GET.value == "GET"
        assert HttpMethod.POST.value == "POST"
        assert HttpMethod.PUT.value == "PUT"
        assert HttpMethod.DELETE.value == "DELETE"
        assert HttpMethod.HEAD.value == "HEAD"
        assert HttpMethod.PATCH.value == "PATCH"

    def test_trust_relationship_enum(self):
        """Test TrustRelationship enum values."""
        assert TrustRelationship.CREATOR.value == "creator"
        assert TrustRelationship.FRIEND.value == "friend"
        assert TrustRelationship.ADMIN.value == "admin"
        assert TrustRelationship.TRUSTEE.value == "trustee"
        assert TrustRelationship.OWNER.value == "owner"

    def test_subscription_granularity_enum(self):
        """Test SubscriptionGranularity enum values."""
        assert SubscriptionGranularity.NONE.value == "none"
        assert SubscriptionGranularity.LOW.value == "low"
        assert SubscriptionGranularity.HIGH.value == "high"

    def test_database_type_enum(self):
        """Test DatabaseType enum values."""
        assert DatabaseType.DYNAMODB.value == "dynamodb"

    def test_environment_enum(self):
        """Test Environment enum values."""
        assert Environment.AWS.value == "aws"
        assert Environment.STANDALONE.value == "standalone"

    def test_response_code_enum(self):
        """Test ResponseCode enum values."""
        assert ResponseCode.OK.value == 200
        assert ResponseCode.CREATED.value == 201
        assert ResponseCode.ACCEPTED.value == 202
        assert ResponseCode.NO_CONTENT.value == 204
        assert ResponseCode.FOUND.value == 302
        assert ResponseCode.BAD_REQUEST.value == 400
        assert ResponseCode.UNAUTHORIZED.value == 401
        assert ResponseCode.FORBIDDEN.value == 403
        assert ResponseCode.NOT_FOUND.value == 404
        assert ResponseCode.REQUEST_TIMEOUT.value == 408
        assert ResponseCode.INTERNAL_SERVER_ERROR.value == 500


class TestConstants:
    """Test constant values."""

    def test_string_constants(self):
        """Test string constant values."""
        assert DEFAULT_CREATOR == "creator"
        assert DEFAULT_RELATIONSHIP == "friend"
        assert TRUSTEE_CREATOR == "trustee"
        assert AUTHORIZATION_HEADER == "Authorization"
        assert CONTENT_TYPE_HEADER == "Content-Type"
        assert LOCATION_HEADER == "Location"
        assert JSON_CONTENT_TYPE == "application/json"
        assert OAUTH_TOKEN_COOKIE == "oauth_token"

    def test_numeric_constants(self):
        """Test numeric constant values."""
        assert DEFAULT_FETCH_DEADLINE == 20
        assert DEFAULT_COOKIE_MAX_AGE == 1209600  # 14 days
        assert MINIMUM_TOKEN_ENTROPY == 80
        assert DEFAULT_REFRESH_TOKEN_EXPIRY == 365 * 24 * 3600  # 1 year


class TestTTLConstants:
    """Test TTL constant values."""

    def test_oauth_session_ttl(self):
        """Test OAuth session TTL is 10 minutes."""
        assert OAUTH_SESSION_TTL == 600
        assert OAUTH_SESSION_TTL == 10 * 60  # 10 minutes

    def test_spa_token_ttls(self):
        """Test SPA token TTL values."""
        assert SPA_ACCESS_TOKEN_TTL == 3600  # 1 hour
        assert SPA_REFRESH_TOKEN_TTL == 86400 * 14  # 2 weeks
        assert SPA_ACCESS_TOKEN_TTL == 60 * 60  # 1 hour in minutes * seconds
        assert SPA_REFRESH_TOKEN_TTL == 1209600  # 2 weeks in seconds

    def test_mcp_token_ttls(self):
        """Test MCP token TTL values."""
        assert MCP_AUTH_CODE_TTL == 600  # 10 minutes
        assert MCP_ACCESS_TOKEN_TTL == 3600  # 1 hour
        assert MCP_REFRESH_TOKEN_TTL == 2592000  # 30 days
        assert MCP_REFRESH_TOKEN_TTL == 30 * 24 * 60 * 60  # 30 days in seconds

    def test_index_ttl_buffer(self):
        """Test index TTL buffer is 2 hours."""
        assert INDEX_TTL_BUFFER == 7200  # 2 hours
        assert INDEX_TTL_BUFFER == 2 * 60 * 60  # 2 hours in seconds

    def test_ttl_relationships(self):
        """Test TTL values have correct relationships."""
        # Auth codes and sessions should have same short TTL
        assert OAUTH_SESSION_TTL == MCP_AUTH_CODE_TTL

        # Access tokens should have same TTL across SPA and MCP
        assert SPA_ACCESS_TOKEN_TTL == MCP_ACCESS_TOKEN_TTL

        # Refresh tokens should be longer than access tokens
        assert SPA_REFRESH_TOKEN_TTL > SPA_ACCESS_TOKEN_TTL
        assert MCP_REFRESH_TOKEN_TTL > MCP_ACCESS_TOKEN_TTL

        # MCP refresh tokens should be longer than SPA refresh tokens
        assert MCP_REFRESH_TOKEN_TTL > SPA_REFRESH_TOKEN_TTL

        # Index buffer should be positive
        assert INDEX_TTL_BUFFER > 0


class TestEnumUsage:
    """Test enum usage patterns."""

    def test_enum_comparison(self):
        """Test enum comparison operations."""
        assert AuthType.BASIC == AuthType.BASIC
        assert AuthType.BASIC != AuthType.OAUTH
        assert AuthType.BASIC.value == "basic"

    def test_enum_in_collections(self):
        """Test using enums in collections."""
        supported_auth = [AuthType.BASIC, AuthType.OAUTH]
        assert AuthType.BASIC in supported_auth
        assert AuthType.NONE not in supported_auth

    def test_enum_string_representation(self):
        """Test enum string representations."""
        assert str(AuthType.BASIC) == "AuthType.BASIC"
        assert repr(AuthType.BASIC) == "<AuthType.BASIC: 'basic'>"

    def test_response_code_ranges(self):
        """Test response code categorization."""
        success_codes = [ResponseCode.OK, ResponseCode.CREATED, ResponseCode.ACCEPTED]
        client_error_codes = [
            ResponseCode.BAD_REQUEST,
            ResponseCode.UNAUTHORIZED,
            ResponseCode.FORBIDDEN,
        ]
        server_error_codes = [ResponseCode.INTERNAL_SERVER_ERROR]

        for code in success_codes:
            assert 200 <= code.value < 300

        for code in client_error_codes:
            assert 400 <= code.value < 500

        for code in server_error_codes:
            assert 500 <= code.value < 600
