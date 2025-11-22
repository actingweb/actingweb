"""Constants and enums for the ActingWeb library."""

from enum import Enum


class AuthType(Enum):
    """Authentication types supported by ActingWeb."""

    BASIC = "basic"
    OAUTH = "oauth"
    NONE = "none"


class HttpMethod(Enum):
    """HTTP methods used in ActingWeb."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    PATCH = "PATCH"


class TrustRelationship(Enum):
    """Trust relationship types in ActingWeb."""

    CREATOR = "creator"
    FRIEND = "friend"
    ADMIN = "admin"
    TRUSTEE = "trustee"
    OWNER = "owner"


class SubscriptionGranularity(Enum):
    """Subscription granularity levels."""

    NONE = "none"
    LOW = "low"
    HIGH = "high"


class DatabaseType(Enum):
    """Database backend types."""

    DYNAMODB = "dynamodb"


class Environment(Enum):
    """Runtime environment types."""

    AWS = "aws"
    STANDALONE = "standalone"


# Response codes
class ResponseCode(Enum):
    """Common HTTP response codes used in ActingWeb."""

    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204
    FOUND = 302
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    REQUEST_TIMEOUT = 408
    INTERNAL_SERVER_ERROR = 500


# Common string constants
DEFAULT_CREATOR = "creator"
DEFAULT_RELATIONSHIP = "friend"
TRUSTEE_CREATOR = "trustee"
AUTHORIZATION_HEADER = "Authorization"
CONTENT_TYPE_HEADER = "Content-Type"
LOCATION_HEADER = "Location"
JSON_CONTENT_TYPE = "application/json"
OAUTH_TOKEN_COOKIE = "oauth_token"

# Default values
DEFAULT_FETCH_DEADLINE = 20  # seconds
DEFAULT_COOKIE_MAX_AGE = 1209600  # 14 days
MINIMUM_TOKEN_ENTROPY = 80  # bits
DEFAULT_REFRESH_TOKEN_EXPIRY = 365 * 24 * 3600  # 1 year in seconds

# System Actor IDs for Global Data Storage
# ==========================================
# These actor IDs are used for storing global data in attribute buckets
# that need to be accessible across the entire ActingWeb system.

# Primary system actor for core ActingWeb functionality
ACTINGWEB_SYSTEM_ACTOR = "_actingweb_system"

# OAuth2/MCP system actor for authentication-related data
OAUTH2_SYSTEM_ACTOR = "_actingweb_oauth2"

# Standard Bucket Names for Global Data
# =====================================
# These bucket names are used consistently across the system

# Trust and relationship management
TRUST_TYPES_BUCKET = "trust_types"
TRUST_PERMISSIONS_BUCKET = "trust_permissions"

# OAuth2 and authentication indexes
AUTH_CODE_INDEX_BUCKET = "auth_code_index"
ACCESS_TOKEN_INDEX_BUCKET = "access_token_index"
REFRESH_TOKEN_INDEX_BUCKET = "refresh_token_index"
CLIENT_INDEX_BUCKET = "client_index"
OAUTH_SESSION_BUCKET = (
    "oauth_sessions"  # Temporary OAuth sessions for postponed actor creation
)

# OAuth2 token storage (per-trust)
OAUTH_TOKENS_PREFIX = (
    "oauth_tokens:"  # Used with actor.store[OAUTH_TOKENS_PREFIX + peer_id]
)

# Establishment methods for trust relationships
ESTABLISHED_VIA_ACTINGWEB = "actingweb"  # Traditional ActingWeb protocol handshake
ESTABLISHED_VIA_OAUTH2_INTERACTIVE = (
    "oauth2_interactive"  # OAuth2 interactive user authentication flow
)
ESTABLISHED_VIA_OAUTH2_CLIENT = (
    "oauth2_client"  # OAuth2 client credentials flow (MCP clients)
)

# Email verification settings
EMAIL_VERIFICATION_TOKEN_LENGTH = 32  # Length of URL-safe verification tokens
EMAIL_VERIFICATION_TOKEN_EXPIRY = 86400  # 24 hours in seconds
