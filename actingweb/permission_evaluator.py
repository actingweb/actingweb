"""
Permission Evaluation System for ActingWeb Unified Access Control.

This module provides the core permission evaluation logic that combines:
1. Base permissions from trust types
2. Individual trust relationship overrides
3. Pattern matching and permission resolution
4. Unified permission checking API

The evaluator supports checking permissions for:
- Properties (read/write/delete operations on property paths)
- Methods (ActingWeb method calls)
- Actions (ActingWeb action calls)
- Tools (MCP tool access)
- Resources (MCP resource access)
- Prompts (MCP prompt access)
"""

import logging
import re
from enum import Enum
from typing import Any

from . import config as config_class
from .trust_permissions import get_trust_permission_store, merge_permissions
from .trust_type_registry import get_registry as get_trust_type_registry

logger = logging.getLogger(__name__)


class PermissionResult(Enum):
    """Permission evaluation results."""

    ALLOWED = "allowed"
    DENIED = "denied"
    NOT_FOUND = "not_found"  # No matching rule found


class PermissionType(Enum):
    """Types of permissions that can be evaluated."""

    PROPERTIES = "properties"
    METHODS = "methods"
    ACTIONS = "actions"
    TOOLS = "tools"
    RESOURCES = "resources"
    PROMPTS = "prompts"


class PermissionEvaluator:
    """
    Core permission evaluation engine.

    This class combines trust type base permissions with individual trust
    relationship overrides to make authorization decisions.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        self.trust_type_registry = get_trust_type_registry(config)
        self.permission_store = get_trust_permission_store(config)

        # Cache for compiled regex patterns
        self._pattern_cache: dict[str, re.Pattern] = {}

    def evaluate_permission(
        self,
        actor_id: str,
        peer_id: str,
        permission_type: PermissionType,
        target: str,
        operation: str = "access",
    ) -> PermissionResult:
        """
        Evaluate a specific permission request.

        Args:
            actor_id: The actor being accessed
            peer_id: The peer requesting access
            permission_type: Type of permission to check
            target: The target being accessed (property path, method name, etc.)
            operation: The operation being performed (read, write, delete, etc.)

        Returns:
            PermissionResult indicating whether access is allowed
        """
        try:
            # Get the effective permissions for this trust relationship
            effective_perms = self._get_effective_permissions(actor_id, peer_id)
            if not effective_perms:
                logger.warning(
                    f"No effective permissions found for {actor_id}:{peer_id}"
                )
                return PermissionResult.NOT_FOUND

            # Get the permission rules for this type
            permission_rules = effective_perms.get(permission_type.value)
            if not permission_rules:
                logger.debug(
                    f"No {permission_type.value} permissions defined for {actor_id}:{peer_id}"
                )
                return PermissionResult.NOT_FOUND

            # Evaluate the permission rules
            result = self._evaluate_rules(permission_rules, target, operation)

            # Only log denials for security monitoring
            if result == PermissionResult.DENIED:
                logger.warning(
                    f"Permission denied: {actor_id}:{peer_id} -> {permission_type.value}:{target}:{operation}"
                )
            return result

        except Exception as e:
            logger.error(
                f"Error evaluating permission for {actor_id}:{peer_id} -> {permission_type.value}:{target}: {e}"
            )
            return PermissionResult.DENIED

    def evaluate_property_access(
        self, actor_id: str, peer_id: str, property_path: str, operation: str
    ) -> PermissionResult:
        """
        Evaluate property access permissions.

        Args:
            actor_id: The actor owning the property
            peer_id: The peer requesting access
            property_path: The property path (e.g., "public/profile", "notes/work/project1")
            operation: Operation type ("read", "write", "delete")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.PROPERTIES,
            target=property_path,
            operation=operation,
        )

    def evaluate_method_access(
        self, actor_id: str, peer_id: str, method_name: str
    ) -> PermissionResult:
        """
        Evaluate method access permissions.

        Args:
            actor_id: The actor owning the method
            peer_id: The peer requesting access
            method_name: The method name (e.g., "get_profile", "list_notes")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.METHODS,
            target=method_name,
            operation="call",
        )

    def evaluate_action_access(
        self, actor_id: str, peer_id: str, action_name: str
    ) -> PermissionResult:
        """
        Evaluate action access permissions.

        Args:
            actor_id: The actor owning the action
            peer_id: The peer requesting access
            action_name: The action name (e.g., "create_note", "send_message")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.ACTIONS,
            target=action_name,
            operation="execute",
        )

    def evaluate_tool_access(
        self, actor_id: str, peer_id: str, tool_name: str
    ) -> PermissionResult:
        """
        Evaluate MCP tool access permissions.

        Args:
            actor_id: The actor providing the tool
            peer_id: The MCP client requesting access
            tool_name: The tool name (e.g., "search", "fetch", "create_note")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.TOOLS,
            target=tool_name,
            operation="use",
        )

    def evaluate_resource_access(
        self, actor_id: str, peer_id: str, resource_path: str, operation: str = "read"
    ) -> PermissionResult:
        """
        Evaluate MCP resource access permissions.

        Args:
            actor_id: The actor owning the resource
            peer_id: The MCP client requesting access
            resource_path: The resource path (e.g., "notes://", "usage://")
            operation: Operation type ("read", "write", "subscribe")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.RESOURCES,
            target=resource_path,
            operation=operation,
        )

    def evaluate_prompt_access(
        self, actor_id: str, peer_id: str, prompt_name: str
    ) -> PermissionResult:
        """
        Evaluate MCP prompt access permissions.

        Args:
            actor_id: The actor providing the prompt
            peer_id: The MCP client requesting access
            prompt_name: The prompt name (e.g., "analyze_notes", "create_summary")

        Returns:
            PermissionResult
        """
        return self.evaluate_permission(
            actor_id=actor_id,
            peer_id=peer_id,
            permission_type=PermissionType.PROMPTS,
            target=prompt_name,
            operation="invoke",
        )

    def get_allowed_items(
        self,
        actor_id: str,
        peer_id: str,
        permission_type: PermissionType,
        operation: str = "access",
    ) -> list[str]:
        """
        Get list of explicitly allowed items for a permission type.

        This returns the 'allowed' patterns/items from the permission rules,
        which can be used for capabilities discovery (e.g., listing available tools).

        Args:
            actor_id: The actor being accessed
            peer_id: The peer requesting access
            permission_type: Type of permission to check
            operation: The operation being performed

        Returns:
            List of allowed patterns/items
        """
        try:
            effective_perms = self._get_effective_permissions(actor_id, peer_id)
            if not effective_perms:
                return []

            permission_rules = effective_perms.get(permission_type.value, {})

            # Extract allowed patterns/items
            allowed_items = []

            # Check for direct 'allowed' list
            if "allowed" in permission_rules:
                allowed = permission_rules["allowed"]
                if isinstance(allowed, list):
                    allowed_items.extend(allowed)

            # Check for 'patterns' with matching operations
            if "patterns" in permission_rules and "operations" in permission_rules:
                operations = permission_rules["operations"]
                if isinstance(operations, list) and operation in operations:
                    patterns = permission_rules["patterns"]
                    if isinstance(patterns, list):
                        allowed_items.extend(patterns)

            return allowed_items

        except Exception as e:
            logger.error(
                f"Error getting allowed items for {actor_id}:{peer_id} -> {permission_type.value}: {e}"
            )
            return []

    def _get_effective_permissions(
        self, actor_id: str, peer_id: str
    ) -> dict[str, Any] | None:
        """
        Get the effective permissions for a trust relationship.

        This combines base trust type permissions with individual overrides.
        """
        # First, determine the trust type for this relationship
        trust_type_name = None

        # Check for permission overrides first (higher priority)
        permission_override = self.permission_store.get_permissions(actor_id, peer_id)
        if permission_override:
            trust_type_name = permission_override.trust_type
        else:
            # Look up trust relationship from database
            trust_type_name = self._lookup_trust_type_from_database(actor_id, peer_id)

        if not trust_type_name:
            logger.debug(f"No trust relationship found for {actor_id}:{peer_id}")
            return None

        logger.debug(f"Found trust type '{trust_type_name}' for {actor_id}:{peer_id}")

        # Get base permissions from trust type
        trust_type = self.trust_type_registry.get_type(trust_type_name)
        if not trust_type:
            logger.error(f"Unknown trust type: {trust_type_name}")
            return None

        base_permissions = trust_type.base_permissions
        logger.debug(f"Base permissions for '{trust_type_name}': {base_permissions}")

        # If we have permission overrides, merge them
        if permission_override:
            override_dict = {}

            # Extract non-None override fields
            for field in [
                "properties",
                "methods",
                "actions",
                "tools",
                "resources",
                "prompts",
            ]:
                override_value = getattr(permission_override, field, None)
                if override_value is not None:
                    override_dict[field] = override_value

            # Merge base permissions with overrides
            effective_permissions = merge_permissions(base_permissions, override_dict)
        else:
            effective_permissions = base_permissions

        return effective_permissions

    def _lookup_trust_type_from_database(
        self, actor_id: str, peer_id: str
    ) -> str | None:
        """
        Look up trust type (relationship) from the database.

        Args:
            actor_id: The actor ID
            peer_id: The peer ID

        Returns:
            Trust type name (relationship) or None if not found
        """
        try:
            from .db_dynamodb.db_trust import DbTrust

            db_trust = DbTrust()
            trust_record = db_trust.get(actor_id=actor_id, peerid=peer_id)

            # DbTrust.get() returns a dict; support both dicts and objects defensively
            if isinstance(trust_record, dict):
                relationship = trust_record.get("relationship")
                if relationship:
                    return str(relationship)
            elif trust_record is not None and hasattr(trust_record, "relationship"):
                return str(trust_record.relationship)

            return None

        except Exception as e:
            logger.error(
                f"Error looking up trust relationship {actor_id}:{peer_id}: {e}"
            )
            return None

    def _evaluate_rules(
        self, permission_rules: dict[str, Any], target: str, operation: str
    ) -> PermissionResult:
        """
        Evaluate permission rules against a specific target and operation.

        Permission rules can have different formats:

        1. Simple allowed/denied lists:
           {"allowed": ["pattern1", "pattern2"], "denied": ["pattern3"]}

        2. Pattern-based with operations:
           {"patterns": ["pattern1"], "operations": ["read", "write"], "excluded_patterns": ["pattern2"]}

        3. Mixed format (combines both approaches)
        """
        logger.debug(f"Evaluating rules: target='{target}', operation='{operation}', rules={permission_rules}")

        # Check explicit denied patterns first (highest priority)
        if "denied" in permission_rules:
            denied_patterns = permission_rules["denied"]
            if self._matches_any_pattern(target, denied_patterns):
                logger.debug(f"Target '{target}' matched denied pattern")
                return PermissionResult.DENIED

        # Check allowed patterns
        if "allowed" in permission_rules:
            allowed_patterns = permission_rules["allowed"]
            if self._matches_any_pattern(target, allowed_patterns):
                logger.debug(f"Target '{target}' matched allowed pattern")
                return PermissionResult.ALLOWED

        # Check pattern-based permissions with operations
        if "patterns" in permission_rules and "operations" in permission_rules:
            patterns = permission_rules["patterns"]
            operations = permission_rules["operations"]

            logger.debug(f"Pattern-based check: patterns={patterns}, operations={operations}")

            # Check if operation is allowed
            if operation not in operations:
                logger.debug(f"Operation '{operation}' not in allowed operations {operations}")
                return PermissionResult.DENIED

            # Check if target matches allowed patterns
            if self._matches_any_pattern(target, patterns):
                # Check excluded patterns
                excluded = permission_rules.get("excluded_patterns", [])
                if excluded and self._matches_any_pattern(target, excluded):
                    logger.debug(f"Target '{target}' matched excluded pattern")
                    return PermissionResult.DENIED
                logger.debug(f"Target '{target}' matched pattern, operation '{operation}' allowed")
                return PermissionResult.ALLOWED
            else:
                # When patterns are explicitly defined, non-match means DENIED
                # EXCEPT: empty target (listing requests) should return NOT_FOUND to allow
                # the listing endpoint to proceed - individual properties are filtered there
                if target == "":
                    logger.debug(
                        f"Empty target with patterns {patterns} - allowing listing (filter at response level)"
                    )
                    return PermissionResult.NOT_FOUND
                logger.debug(f"Target '{target}' did not match any patterns {patterns} - denying access")
                return PermissionResult.DENIED

        # No matching rule found (no patterns/operations configured at all)
        logger.debug(f"No matching rule found for target='{target}', operation='{operation}'")
        return PermissionResult.NOT_FOUND

    def _matches_any_pattern(self, target: str, patterns: list[str]) -> bool:
        """
        Check if target matches any of the given patterns.

        Supports glob-style patterns with * and ? wildcards.
        """
        if not patterns:
            return False

        for pattern in patterns:
            if self._matches_pattern(target, pattern):
                return True
        return False

    def _matches_pattern(self, target: str, pattern: str) -> bool:
        """
        Check if target matches a single pattern.

        Supports:
        - Exact matches
        - Glob-style patterns with * (any characters) and ? (single character)
        - Special case: "*" matches everything
        - Prefix matching: "notes://" matches "notes://work/projects"
        """
        if pattern == "*":
            return True

        if pattern == target:
            return True

        # Special handling for URI-like patterns that should match prefixes
        if pattern.endswith("://") and target.startswith(pattern):
            return True

        # Use cached compiled regex if available
        if pattern in self._pattern_cache:
            regex = self._pattern_cache[pattern]
        else:
            # Convert glob pattern to regex
            regex_pattern = self._glob_to_regex(pattern)
            regex = re.compile(regex_pattern)
            self._pattern_cache[pattern] = regex

        return bool(regex.match(target))

    def _glob_to_regex(self, pattern: str) -> str:
        """Convert glob pattern to regex pattern."""
        # Escape special regex characters except * and ?
        escaped = re.escape(pattern)

        # Replace escaped glob wildcards with regex equivalents
        escaped = escaped.replace(r"\*", ".*")  # * matches any characters
        escaped = escaped.replace(r"\?", ".")  # ? matches single character

        # Anchor the pattern to match the entire string
        return f"^{escaped}$"


# Convenience functions for common permission checks


def check_property_access(
    config: config_class.Config,
    actor_id: str,
    peer_id: str,
    property_path: str,
    operation: str,
) -> bool:
    """
    Quick property access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = PermissionEvaluator(config)
    result = evaluator.evaluate_property_access(
        actor_id, peer_id, property_path, operation
    )
    return result == PermissionResult.ALLOWED


def check_method_access(
    config: config_class.Config, actor_id: str, peer_id: str, method_name: str
) -> bool:
    """
    Quick method access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = PermissionEvaluator(config)
    result = evaluator.evaluate_method_access(actor_id, peer_id, method_name)
    return result == PermissionResult.ALLOWED


def check_tool_access(
    config: config_class.Config, actor_id: str, peer_id: str, tool_name: str
) -> bool:
    """
    Quick MCP tool access check.

    Returns:
        True if access is allowed, False otherwise
    """
    evaluator = PermissionEvaluator(config)
    result = evaluator.evaluate_tool_access(actor_id, peer_id, tool_name)
    return result == PermissionResult.ALLOWED


# Singleton instance
_permission_evaluator: PermissionEvaluator | None = None


def initialize_permission_evaluator(config: config_class.Config) -> None:
    """Initialize the permission evaluator at application startup."""
    global _permission_evaluator
    if _permission_evaluator is None:
        logger.info("Initializing permission evaluator...")
        _permission_evaluator = PermissionEvaluator(config)
        logger.info("Permission evaluator initialized")


def get_permission_evaluator(config: config_class.Config) -> PermissionEvaluator:
    """Get the singleton permission evaluator (must be initialized first).

    Falls back to lazy initialization with a warning if not initialized at startup.
    This prevents hard failures but may cause performance issues on first use.
    """
    global _permission_evaluator
    if _permission_evaluator is None:
        logger.warning(
            "Permission evaluator not initialized at startup - falling back to lazy initialization. "
            "This may cause performance issues (4+ minute delays in OAuth2 flows). "
            "Call initialize_permission_evaluator() at application startup to avoid this."
        )
        initialize_permission_evaluator(config)
    assert _permission_evaluator is not None, (
        "PermissionEvaluator should be initialized"
    )
    return _permission_evaluator
