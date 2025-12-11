"""
Trust Type Registry for ActingWeb Unified Access Control.

This module provides a registry for trust relationship types using the ActingWeb
property store pattern. Trust types are stored in a system actor's properties
and define the base permissions and capabilities for different kinds of relationships.
"""

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from botocore.exceptions import ClientError

from . import actor as actor_module
from . import attribute
from . import config as config_class
from .constants import ACTINGWEB_SYSTEM_ACTOR, TRUST_TYPES_BUCKET

# Backward-compatibility alias expected by tests and older integrations
TRUST_TYPE_SYSTEM_ACTOR = ACTINGWEB_SYSTEM_ACTOR

logger = logging.getLogger(__name__)

# Use standardized constants for system actor and bucket names


@dataclass
class TrustType:
    """Defines a type of trust relationship with associated permissions.

    Note: 'name' corresponds to the 'relationship' field in the database for
    backward compatibility with existing ActingWeb protocol.

    ACL Rules:
        The acl_rules field allows defining HTTP endpoint access for this trust type.
        Each rule is a tuple of (path, methods, access) where:
        - path: The HTTP path pattern (e.g., "subscriptions/<id>", "properties")
        - methods: HTTP methods allowed ("GET", "POST", "PUT", "DELETE", or "" for all)
        - access: "a" for allow, "r" for reject

        Example:
            acl_rules=[
                ("subscriptions/<id>", "POST", "a"),  # Allow creating subscriptions
                ("properties", "GET", "a"),           # Allow reading properties
            ]
    """

    name: str  # Unique identifier (e.g., "viewer", "mcp_client") - stored as 'relationship'
    display_name: str  # Human-readable name
    description: str  # Description of what this relationship allows
    base_permissions: dict[str, Any]  # Base permissions granted
    allow_user_override: bool = True  # Whether users can modify permissions
    oauth_scope: str | None = None  # OAuth2 scope mapping
    created_by: str = "system"  # Who created this relationship type
    acl_rules: list[tuple[str, str, str]] | None = None  # HTTP endpoint ACL rules

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrustType":
        """Create from dictionary loaded from storage."""
        return cls(**data)

    def validate(self) -> bool:
        """Validate the trust type definition."""
        if not self.name or not isinstance(self.name, str):
            return False
        if not self.display_name or not isinstance(self.display_name, str):
            return False
        # base_permissions must be a dictionary defining the permission schema
        if not isinstance(self.base_permissions, dict):
            return False
        return True


class TrustTypeRegistry:
    """
    Registry for trust relationship types using ActingWeb attribute buckets.

    Trust types are stored in a global attribute bucket for searchability:
    bucket="trust_types", actor_id="_global_system", name={trust_type_name}
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self._cache: dict[str, TrustType] = {}
        self._cache_valid = False
        # Cache for the system actor instance
        self._system_actor: Any = None

    def _get_trust_types_bucket(self) -> attribute.Attributes | None:
        """Get the global trust types attribute bucket."""
        try:
            return attribute.Attributes(
                actor_id=ACTINGWEB_SYSTEM_ACTOR,
                bucket=TRUST_TYPES_BUCKET,
                config=self.config,
            )
        except Exception as e:
            logger.error(f"Error accessing trust types bucket: {e}")
            return None

    # Backward-compatibility helpers for tests that expect a system actor
    def _get_system_actor(self) -> Any | None:
        try:
            if (
                self._system_actor is not None
                and getattr(self._system_actor, "id", None) == ACTINGWEB_SYSTEM_ACTOR
            ):
                return self._system_actor
            sys_actor = actor_module.Actor(ACTINGWEB_SYSTEM_ACTOR, config=self.config)
            if not getattr(sys_actor, "id", None):
                # Create if missing
                base_root = getattr(self.config, "root", "") or "http://localhost/"
                url = f"{base_root}{ACTINGWEB_SYSTEM_ACTOR}"
                passphrase = (
                    self.config.new_token()
                    if hasattr(self.config, "new_token")
                    else "system-pass"
                )
                try:
                    created = sys_actor.create(
                        url=url,
                        creator="system",
                        passphrase=passphrase,
                        actor_id=ACTINGWEB_SYSTEM_ACTOR,
                    )
                    if not created:
                        return None
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceInUseException":
                        logger.debug(
                            "System actor table already exists; another worker created it"
                        )
                        # Continue with the actor instance even if creation failed due to existing table
                    else:
                        raise  # Re-raise genuine errors
                except Exception as e:
                    logger.error(f"Error creating system actor: {e}")
                    return None
            self._system_actor = sys_actor
            return self._system_actor
        except Exception as e:
            logger.error(f"Error ensuring system actor: {e}")
            return None

    def register_type(self, trust_type: TrustType) -> bool:
        """Register a new trust type (property-store based for compatibility)."""
        if not trust_type.validate():
            logger.error(f"Invalid trust type definition: {trust_type.name}")
            return False

        sys_actor = self._get_system_actor()
        if not sys_actor:
            logger.error("Cannot access system actor for trust type registration")
            return False

        try:
            prop_name = f"trust_type:{trust_type.name}"
            trust_type_json = json.dumps(trust_type.to_dict())
            setattr(sys_actor.property, prop_name, trust_type_json)
            # Update cache
            self._cache[trust_type.name] = trust_type
            logger.info(f"Registered trust type: {trust_type.name}")
            logger.debug(f"Trust type '{trust_type.name}' stored with permissions: {trust_type.base_permissions}")
            return True
        except Exception as e:
            logger.error(f"Error registering trust type {trust_type.name}: {e}")
            return False

    def get_type(self, name: str) -> TrustType | None:
        """Get a trust type by name (from system actor properties)."""
        if self._cache_valid and name in self._cache:
            logger.debug(f"Returning cached trust type '{name}'")
            return self._cache[name]

        sys_actor = self._get_system_actor()
        if not sys_actor:
            return None

        try:
            prop_name = f"trust_type:{name}"
            raw = getattr(sys_actor.property, prop_name, None)
            if not raw:
                logger.debug(f"Trust type '{name}' not found in system actor properties")
                return None
            trust_type_data = json.loads(raw)
            trust_type = TrustType.from_dict(trust_type_data)
            logger.debug(f"Loaded trust type '{name}' from DB: base_permissions={trust_type.base_permissions}")
            self._cache[name] = trust_type
            return trust_type
        except Exception as e:
            logger.error(f"Error loading trust type {name}: {e}")
            return None

    def list_types(self) -> list[TrustType]:
        """List all registered trust types from system actor properties."""
        sys_actor = self._get_system_actor()
        if not sys_actor:
            return []

        trust_types: list[TrustType] = []
        try:
            props = sys_actor.get_properties() or {}
            for key, raw in props.items():
                if not isinstance(key, str) or not key.startswith("trust_type:"):
                    continue
                try:
                    trust_type_data = json.loads(raw)
                    trust_type = TrustType.from_dict(trust_type_data)
                    trust_types.append(trust_type)
                    self._cache[trust_type.name] = trust_type
                except Exception as e:
                    logger.error(f"Error parsing trust type {key}: {e}")
                    continue
            self._cache_valid = True
            return trust_types
        except Exception as e:
            logger.error(f"Error listing trust types: {e}")
            return []

    def delete_type(self, name: str) -> bool:
        """Delete a trust type."""
        bucket = self._get_trust_types_bucket()
        if not bucket:
            return False

        try:
            # Delete from attribute bucket
            success = bucket.delete_attr(name=name)

            if success:
                # Remove from cache
                self._cache.pop(name, None)
                logger.info(f"Deleted trust type: {name}")
                return True
            else:
                logger.error(f"Failed to delete trust type {name}")
                return False

        except Exception as e:
            logger.error(f"Error deleting trust type {name}: {e}")
            return False

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()
        self._cache_valid = False


# Singleton instance
_registry: TrustTypeRegistry | None = None


def initialize_registry(config: config_class.Config) -> None:
    """Initialize the trust type registry at application startup."""
    global _registry
    if _registry is None:
        logger.info("Initializing trust type registry...")
        _registry = TrustTypeRegistry(config)
        _register_default_types(_registry)
        logger.info(
            f"Trust type registry initialized with {len(_registry.list_types())} types"
        )


def get_registry(config: config_class.Config) -> TrustTypeRegistry:
    """Get the singleton trust type registry, initializing lazily if needed."""
    global _registry
    if _registry is None:
        # Lazy initialization to keep backward compatibility with tests and apps
        _registry = TrustTypeRegistry(config)
        _register_default_types(_registry)
    return _registry


def _register_default_types(registry: TrustTypeRegistry) -> None:
    """Register the default trust types."""

    # Viewer - Read-only access
    viewer = TrustType(
        name="viewer",
        display_name="Viewer",
        description="Read-only access to public properties and basic methods",
        base_permissions={
            "properties": {
                "patterns": ["public/*", "shared/*"],
                "operations": ["read"],
            },
            "methods": {
                "allowed": ["get_*", "list_*", "export_*"],
                "denied": ["delete_*", "admin_*"],
            },
            "actions": {"allowed": [], "denied": ["*"]},
            "tools": {"allowed": [], "denied": ["*"]},
            "resources": {"patterns": ["public/*"], "operations": ["read"]},
        },
        oauth_scope="actingweb.viewer",
    )

    # Friend - Standard trusted relationship
    friend = TrustType(
        name="friend",
        display_name="Friend",
        description="Access to shared resources and most actions",
        base_permissions={
            "properties": {
                "patterns": ["*"],
                "operations": ["read", "write"],
                "excluded_patterns": ["private/*", "security/*", "_internal/*"],
            },
            "methods": {
                "allowed": ["*"],
                "denied": ["delete_*", "admin_*", "system_*"],
            },
            "actions": {
                "allowed": ["*"],
                "denied": ["delete_*", "admin_*", "system_*"],
            },
            "tools": {"allowed": ["*"], "denied": ["admin_*", "system_*"]},
            "resources": {
                "patterns": ["*"],
                "operations": ["read", "write"],
                "excluded_patterns": ["private/*", "security/*"],
            },
        },
        oauth_scope="actingweb.friend",
    )

    # Partner - Enhanced access for business partners
    partner = TrustType(
        name="partner",
        display_name="Partner",
        description="Enhanced access for business partners and collaborators",
        base_permissions={
            "properties": {
                "patterns": ["*"],
                "operations": ["read", "write"],
                "excluded_patterns": ["_internal/*"],
            },
            "methods": {"allowed": ["*"], "denied": ["admin_*", "system_*"]},
            "actions": {"allowed": ["*"], "denied": ["admin_*", "system_*"]},
            "tools": {"allowed": ["*"], "denied": ["admin_*", "system_*"]},
            "resources": {
                "patterns": ["*"],
                "operations": ["read", "write"],
                "excluded_patterns": ["security/*"],
            },
        },
        oauth_scope="actingweb.partner",
    )

    # Admin - Full access
    admin = TrustType(
        name="admin",
        display_name="Administrator",
        description="Full administrative access to all resources",
        base_permissions={
            "properties": {
                "patterns": ["*"],
                "operations": ["read", "write", "delete"],
            },
            "methods": {"allowed": ["*"]},
            "actions": {"allowed": ["*"]},
            "tools": {"allowed": ["*"]},
            "resources": {"patterns": ["*"], "operations": ["read", "write", "delete"]},
        },
        oauth_scope="actingweb.admin",
    )

    # MCP Client - AI assistant access with secure defaults
    mcp_client = TrustType(
        name="mcp_client",
        display_name="MCP Client (AI Assistant)",
        description="AI assistant with secure access to read data and use specific tools",
        base_permissions={
            "properties": {
                "patterns": ["public/*", "shared/*", "notes/*", "profile/*"],
                "operations": ["read"],
                "excluded_patterns": [
                    "private/*",
                    "security/*",
                    "_internal/*",
                    "oauth_*",
                    "auth_*",
                ],
            },
            "methods": {
                "allowed": [
                    "get_*",
                    "list_*",
                    "search_*",
                    "export_*",
                ],  # Safe read-only methods
                "denied": ["delete_*", "admin_*", "system_*", "oauth_*", "auth_*"],
            },
            "actions": {
                "allowed": ["search", "fetch", "export"],  # Safe informational actions
                "denied": ["delete_*", "admin_*", "system_*", "oauth_*", "auth_*"],
            },
            "tools": {
                # Allow common MCP tools including a generic 'list' tool name
                # Some MCP clients (e.g., mcp_power) use 'list' without suffix
                "allowed": [
                    "search",
                    "fetch",
                    "create_note",
                    "list",
                    "get_*",
                    "list_*",
                ],  # Common MCP tools
                "denied": ["admin_*", "system_*", "delete_*", "oauth_*", "auth_*"],
            },
            "resources": {
                "patterns": [
                    "public/*",
                    "shared/*",
                    "notes://*",
                    "usage://*",
                    "actingweb://properties/all",
                ],
                "operations": ["read"],
                "excluded_patterns": [
                    "private/*",
                    "security/*",
                    "oauth://*",
                    "auth://*",
                ],
            },
            "prompts": {
                "allowed": [
                    "analyze_*",
                    "create_*",
                    "summarize_*",
                    "generate_*",
                ]  # AI-specific prompts
            },
        },
        allow_user_override=True,  # Users should customize MCP permissions
        oauth_scope="actingweb.mcp",
    )

    # Associate - Traditional default ActingWeb relationship
    associate = TrustType(
        name="associate",
        display_name="Associate",
        description="Basic ActingWeb peer relationship with limited access",
        base_permissions={
            "properties": {"patterns": ["public/*"], "operations": ["read"]},
            "methods": {
                "allowed": ["get_*", "ping"],
                "denied": ["delete_*", "admin_*", "system_*"],
            },
            "actions": {"allowed": [], "denied": ["*"]},
            "tools": {"allowed": [], "denied": ["*"]},
            "resources": {"patterns": ["public/*"], "operations": ["read"]},
        },
        oauth_scope="actingweb.associate",
    )

    # Register all default types (maintaining ActingWeb compatibility)
    default_types = [associate, viewer, friend, partner, admin, mcp_client]

    for trust_type in default_types:
        try:
            registry.register_type(trust_type)
        except Exception as e:
            logger.error(
                f"Failed to register default trust type {trust_type.name}: {e}"
            )
