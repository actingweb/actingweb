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
