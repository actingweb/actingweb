"""
Permission Integration for ActingWeb Handlers.

This module integrates the Unified Access Control system directly into ActingWeb's
existing handler and hook system, making permission checks completely transparent
to 3rd party developers.

3rd party developers only need to:
1. Define custom trust types (if needed)
2. Write their hooks as normal
3. ActingWeb handles all permission checking automatically
"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from . import config as config_class
from .permission_evaluator import (
    PermissionResult,
    PermissionType,
    get_permission_evaluator,
)

logger = logging.getLogger(__name__)


def with_permission_check(permission_type: PermissionType, operation: str = "access"):
    """
    Decorator to add automatic permission checking to handler methods.

    This decorator should be applied to ActingWeb handler methods to automatically
    check permissions before executing the handler logic.

    Args:
        permission_type: Type of permission to check
        operation: Operation being performed
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Extract context from handler
            actor_id = getattr(self, "actor_id", None) or getattr(
                self.actor, "id", None
            )
            peer_id = self._get_peer_id()

            if not actor_id or not peer_id:
                logger.warning(
                    f"Missing actor_id ({actor_id}) or peer_id ({peer_id}) for permission check"
                )
                return self._permission_denied_response()

            # Determine the target based on the permission type and handler context
            target = self._get_permission_target(permission_type, *args, **kwargs)
            if not target:
                logger.warning(
                    f"Could not determine permission target for {permission_type}"
                )
                return self._permission_denied_response()

            # Check permission
            evaluator = get_permission_evaluator(self.config)
            result = evaluator.evaluate_permission(
                actor_id, peer_id, permission_type, target, operation
            )

            if result != PermissionResult.ALLOWED:
                logger.info(
                    f"Permission denied: {actor_id} -> {peer_id} -> {permission_type.value}:{target}:{operation}"
                )
                return self._permission_denied_response()

            # Permission granted - execute the original handler
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


class PermissionAwareHandlerMixin:
    """
    Mixin for ActingWeb handlers that adds automatic permission checking.

    Handler classes should inherit from this mixin to get automatic permission
    checking without needing to write explicit permission check code.
    """

    def _get_peer_id(self) -> str | None:
        """
        Extract peer ID from the request context.

        This method should be overridden by specific handler implementations
        to extract the peer ID from the appropriate source (OAuth token,
        trust relationship, request headers, etc.).
        """
        # Try common sources for peer ID

        # 1. From OAuth/MCP token validation (if available)
        if hasattr(self, "validated_token_data"):
            return self.validated_token_data.get("peer_id")  # type: ignore[attr-defined]

        # 2. From request headers
        if hasattr(self.request, "headers"):  # type: ignore[attr-defined]
            peer_id = self.request.headers.get("X-Peer-ID")  # type: ignore[attr-defined]
            if peer_id:
                return peer_id

        # 3. From trust relationship lookup (based on authentication)
        # This would require looking up the trust relationship based on
        # the authenticated identity (to be implemented based on auth method)

        logger.debug("Could not determine peer_id from request context")
        return None

    def _get_permission_target(
        self, permission_type: PermissionType, *args, **kwargs
    ) -> str | None:
        """
        Determine the permission target based on permission type and handler context.

        This method extracts the target (property path, method name, etc.) from
        the handler arguments based on the permission type being checked.
        """
        if permission_type == PermissionType.PROPERTIES:
            # For property handlers, target is the property path
            return args[0] if args else kwargs.get("property_path")

        elif permission_type == PermissionType.METHODS:
            # For method handlers, target is the method name
            return args[0] if args else kwargs.get("method_name")

        elif permission_type == PermissionType.ACTIONS:
            # For action handlers, target is the action name
            return args[0] if args else kwargs.get("action_name")

        elif permission_type == PermissionType.TOOLS:
            # For MCP tool handlers, target is the tool name
            return args[0] if args else kwargs.get("tool_name")

        elif permission_type == PermissionType.RESOURCES:
            # For MCP resource handlers, target is the resource path
            return args[0] if args else kwargs.get("resource_path")

        elif permission_type == PermissionType.PROMPTS:
            # For MCP prompt handlers, target is the prompt name
            return args[0] if args else kwargs.get("prompt_name")

        return None

    def _permission_denied_response(self):
        """
        Generate a permission denied response.

        This method should be overridden by specific handler implementations
        to return an appropriate response format (JSON, HTTP status, etc.).
        """
        if hasattr(self.response, "set_status"):  # type: ignore[attr-defined]
            self.response.set_status(403)  # type: ignore[attr-defined]

        return {"error": "Access denied"}


def register_permission_hooks(app, config: config_class.Config):
    """
    Register automatic permission checking hooks with an ActingWeb application.

    This function integrates permission checking into the existing ActingWeb hook system,
    making permission checks completely transparent to application developers.

    Args:
        app: ActingWeb application instance with hook support
        config: ActingWeb configuration
    """
    evaluator = get_permission_evaluator(config)

    def check_property_permission(
        actor, operation: str, value: Any, path: list[str]
    ) -> bool:
        """Hook to check property access permissions."""
        peer_id = _extract_peer_from_context()
        if not peer_id:
            return True  # Allow if no peer context (internal operations)

        property_path = "/".join(path)
        result = evaluator.evaluate_property_access(
            actor.id, peer_id, property_path, operation
        )

        if result != PermissionResult.ALLOWED:
            logger.info(
                f"Property access denied: {actor.id} -> {peer_id} -> {property_path} ({operation})"
            )
            return False

        return True

    def check_method_permission(
        actor, method_name: str, params: dict[str, Any]
    ) -> bool:
        """Hook to check method call permissions."""
        peer_id = _extract_peer_from_context()
        if not peer_id:
            return True  # Allow if no peer context

        result = evaluator.evaluate_method_access(actor.id, peer_id, method_name)

        if result != PermissionResult.ALLOWED:
            logger.info(
                f"Method access denied: {actor.id} -> {peer_id} -> {method_name}"
            )
            return False

        return True

    def check_action_permission(
        actor, action_name: str, params: dict[str, Any]
    ) -> bool:
        """Hook to check action execution permissions."""
        peer_id = _extract_peer_from_context()
        if not peer_id:
            return True  # Allow if no peer context

        result = evaluator.evaluate_action_access(actor.id, peer_id, action_name)

        if result != PermissionResult.ALLOWED:
            logger.info(
                f"Action access denied: {actor.id} -> {peer_id} -> {action_name}"
            )
            return False

        return True

    def check_tool_permission(actor, tool_name: str, params: dict[str, Any]) -> bool:
        """Hook to check MCP tool access permissions."""
        peer_id = _extract_peer_from_context()
        if not peer_id:
            return True  # Allow if no peer context

        result = evaluator.evaluate_tool_access(actor.id, peer_id, tool_name)

        if result != PermissionResult.ALLOWED:
            logger.info(f"Tool access denied: {actor.id} -> {peer_id} -> {tool_name}")
            return False

        return True

    def check_prompt_permission(
        actor, prompt_name: str, params: dict[str, Any]
    ) -> bool:
        """Hook to check MCP prompt access permissions."""
        peer_id = _extract_peer_from_context()
        if not peer_id:
            return True  # Allow if no peer context

        result = evaluator.evaluate_prompt_access(actor.id, peer_id, prompt_name)

        if result != PermissionResult.ALLOWED:
            logger.info(
                f"Prompt access denied: {actor.id} -> {peer_id} -> {prompt_name}"
            )
            return False

        return True

    # Register hooks with the application
    # Note: This assumes the ActingWeb app has a hook registration system
    # The exact API would depend on how hooks are implemented in ActingWeb

    if hasattr(app, "register_property_hook"):
        app.register_property_hook("before_access", check_property_permission)

    if hasattr(app, "register_method_hook"):
        app.register_method_hook("before_call", check_method_permission)

    if hasattr(app, "register_action_hook"):
        app.register_action_hook("before_execute", check_action_permission)

    if hasattr(app, "register_tool_hook"):
        app.register_tool_hook("before_use", check_tool_permission)

    if hasattr(app, "register_prompt_hook"):
        app.register_prompt_hook("before_invoke", check_prompt_permission)


def _extract_peer_from_context() -> str | None:
    """
    Extract peer ID from the current request context.

    This is a placeholder implementation that would need to be adapted
    based on how ActingWeb tracks request context and authentication.
    """
    # This would need to be implemented based on ActingWeb's context management
    # For example, it might look up the current request context and extract
    # the peer ID from OAuth tokens, trust relationships, or other auth mechanisms
    return None


# Simplified configuration for 3rd party developers
class AccessControlConfig:
    """
    Simplified configuration interface for 3rd party developers.

    This provides a simple way to configure access control without needing
    to understand the underlying permission system complexity.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self.custom_trust_types = []
        self._oauth2_trust_types = None  # OAuth2-specific trust type filtering

    def add_trust_type(
        self,
        name: str,
        display_name: str,
        permissions: dict[str, Any],
        description: str = "",
        oauth_scope: str | None = None,
        acl_rules: list[tuple[str, str, str]] | None = None,
    ):
        """
        Add a custom trust type with simplified permission specification.

        Args:
            name: Unique trust type identifier
            display_name: Human-readable name
            permissions: Simplified permissions dict for high-level access control
                        (properties, methods, tools, resources, prompts)
            description: Optional description
            oauth_scope: Optional OAuth2 scope mapping
            acl_rules: Optional list of HTTP endpoint ACL rules. Each rule is a tuple
                      of (path, methods, access) where:
                      - path: HTTP path pattern (e.g., "subscriptions/<id>", "properties")
                      - methods: HTTP methods ("GET", "POST", "PUT", "DELETE", or "" for all)
                      - access: "a" for allow, "r" for reject

        Example:
            # Basic trust type with high-level permissions only
            config.add_trust_type(
                name="api_client",
                display_name="API Client",
                permissions={
                    "properties": ["public/*", "api/*"],
                    "methods": ["get_*", "list_*"],
                    "tools": []  # No tools allowed
                },
                oauth_scope="myapp.api_client"
            )

            # Trust type with ACL rules for HTTP endpoint access
            config.add_trust_type(
                name="subscriber",
                display_name="Subscriber",
                permissions={
                    "properties": {"patterns": ["memory_*"], "operations": ["read"]},
                },
                acl_rules=[
                    ("subscriptions/<id>", "POST", "a"),  # Allow creating subscriptions
                    ("properties", "GET", "a"),          # Allow reading properties
                ],
            )
        """
        from .trust_type_registry import TrustType, get_registry

        # Convert simplified permissions to full format
        base_permissions = self._convert_simple_permissions(permissions)

        trust_type = TrustType(
            name=name,
            display_name=display_name,
            description=description,
            base_permissions=base_permissions,
            oauth_scope=oauth_scope,
            acl_rules=acl_rules,
        )

        self.custom_trust_types.append(trust_type)

        # Register immediately
        registry = get_registry(self.config)
        registry.register_type(trust_type)

        # Add ACL rules to config.access if provided
        if acl_rules:
            self._add_acl_rules_to_config(name, acl_rules)

    def _add_acl_rules_to_config(
        self, trust_type_name: str, acl_rules: list[tuple[str, str, str]]
    ) -> None:
        """
        Add ACL rules for a trust type to config.access.

        This method inserts ACL rules at the beginning of config.access to ensure
        they are evaluated before more general rules. Each rule is converted to
        the format: (role, path, methods, access).

        Args:
            trust_type_name: The name of the trust type (used as the role)
            acl_rules: List of (path, methods, access) tuples
        """
        for path, methods, access in acl_rules:
            # ACL format: (role, path, methods, access)
            acl_entry = (trust_type_name, path, methods, access)

            # Check if rule already exists to avoid duplicates
            if acl_entry not in self.config.access:
                # Insert at beginning for priority (custom rules should override defaults)
                self.config.access.insert(0, acl_entry)
                logger.debug(
                    f"Added ACL rule for trust type '{trust_type_name}': {acl_entry}"
                )

    def _convert_simple_permissions(
        self, simple_perms: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert simplified permission format to full format."""
        base_permissions = {}

        for category, rules in simple_perms.items():
            if category == "properties":
                if isinstance(rules, list):
                    # Simple list of patterns
                    base_permissions[category] = {
                        "patterns": rules,
                        "operations": ["read", "write"],  # Default operations
                    }
                else:
                    # More complex specification
                    base_permissions[category] = rules

            elif category in ["methods", "actions", "tools", "prompts"]:
                if isinstance(rules, list):
                    # Simple list of allowed items
                    base_permissions[category] = {"allowed": rules}
                else:
                    # More complex specification
                    base_permissions[category] = rules

            elif category == "resources":
                if isinstance(rules, list):
                    # Simple list of resource patterns
                    base_permissions[category] = {
                        "patterns": rules,
                        "operations": ["read"],  # Default operations
                    }
                else:
                    # More complex specification
                    base_permissions[category] = rules

        return base_permissions

    def configure_oauth2_trust_types(
        self,
        allowed_trust_types: list[str] | None = None,
        default_trust_type: str | None = None,
    ):
        """
        Configure which trust types are available during OAuth2 authorization flows.

        This allows applications to control which trust relationship types
        users can select during MCP OAuth2 authentication.

        IMPORTANT: The application is responsible for configuring trust types.
        If not configured, all trust types from the registry will be available,
        with the first one as default.

        Args:
            allowed_trust_types: List of trust type names to allow in OAuth2 flows.
                                If None, all registered trust types are available.
            default_trust_type: Default trust type to pre-select in OAuth2 forms.
                               If None, the first allowed trust type will be used.

        Example:
            # Only allow specific trust types for OAuth2
            access_control.configure_oauth2_trust_types(
                allowed_trust_types=["mcp_client", "api_client"],
                default_trust_type="mcp_client"
            )

            # Allow all trust types from registry (default behavior)
            access_control.configure_oauth2_trust_types()
        """
        self._oauth2_trust_types = {
            "allowed": allowed_trust_types,  # None means all are allowed
            "default": default_trust_type,  # None means use first available
        }

        # Store in config for access by OAuth2 handlers
        if not hasattr(self.config, "_oauth2_trust_types"):
            self.config._oauth2_trust_types = self._oauth2_trust_types  # type: ignore[attr-defined]
        else:
            self.config._oauth2_trust_types.update(self._oauth2_trust_types)  # type: ignore[attr-defined]

        logger.info(
            f"OAuth2 trust types configured: allowed={allowed_trust_types}, default={default_trust_type}"
        )

    def get_oauth2_trust_types(self) -> dict[str, Any]:
        """
        Get the configured OAuth2 trust type settings.

        Returns:
            Dict with 'allowed' and 'default' trust type configuration.
            If not configured, returns None values (no hardcoded defaults).
        """
        return self._oauth2_trust_types or {"allowed": None, "default": None}
