"""
Shared property hooks for ActingWeb demo applications.

Property hooks intercept property operations (get, put, post, delete) and allow
for access control, validation, and transformation of property values.

Property hooks are triggered automatically when:
- GET /{actor_id}/properties/{property_name} - Reading a property
- PUT /{actor_id}/properties/{property_name} - Updating a property
- POST /{actor_id}/properties - Creating a new property
- DELETE /{actor_id}/properties/{property_name} - Deleting a property

Available Property Hooks:
- email: hidden from GET, validated and normalized on PUT/POST, protected
  from deletion
- auth_token: hidden from GET, blocked from PUT/POST/DELETE entirely
- created_at, actor_type: protected from deletion only
- *: wildcard hook for all other properties (JSON string coercion on
  PUT/POST only -- see the comment on handle_all_properties for why it
  cannot also enforce protection: the wildcard hook is never given the
  top-level property name)

Return Values:
- Return the (possibly transformed) value to allow the operation
- Return None to block the operation
"""

import json
import logging
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_property_hooks(app):
    """Register all property hooks with the ActingWeb application."""

    @app.property_hook("email")
    def handle_email_property(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """
        Handle email property with special access control.

        Triggered: On any operation on the 'email' property

        Behaviors:
        - GET: Returns None (hides email from external access)
        - PUT/POST: Validates email format, normalizes to lowercase
        - DELETE: Returns None (prevents deletion)

        Parameters:
            actor: The ActorInterface instance
            operation: "get", "put", "post", or "delete"
            value: The value being set (for put/post) or current value (for get)
            path: Property path as list (e.g., ["email"])

        Returns:
            Transformed value to allow, None to block
        """
        if operation == "get":
            # Hide email from external access
            return None
        elif operation in ["put", "post"]:
            # Validate email format
            if isinstance(value, str) and "@" in value:
                logger.info(f"Actor {actor.id} email changed to {value.lower()}")
                return value.lower()
            logger.warning(f"Invalid email format rejected for actor {actor.id}")
            return None
        elif operation == "delete":
            # Protect email from deletion
            logger.warning(
                f"Attempted to delete protected email property for actor {actor.id}"
            )
            return None
        return value

    @app.property_hook("auth_token")
    def handle_auth_token_property(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """
        Hide and protect auth_token. Registered by exact name rather than
        relying on the "*" wildcard hook below: the wildcard hook is only
        ever called with (actor, operation, value, path) -- path is the
        nested-subkey remainder, never the top-level property name (see
        HookRegistry.execute_property_hooks in actingweb/interface/hooks.py)
        -- so a wildcard hook has no way to identify "this is auth_token"
        for an ordinary top-level access, where path is always []. A prior
        version of this file tried to check path[0] for that purpose, which
        only ever matched a nested subkey name, never the property itself,
        and so silently never fired.
        """
        if operation in ("get", "put", "post", "delete"):
            logger.warning(
                f"Blocked {operation} on hidden property 'auth_token' for actor {actor.id}"
            )
            return None
        return value

    @app.property_hook("created_at")
    def handle_created_at_property(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """Protect created_at from deletion only -- see handle_auth_token_property."""
        if operation == "delete":
            logger.warning(
                f"Blocked deletion of protected property 'created_at' for actor {actor.id}"
            )
            return None
        return value

    @app.property_hook("actor_type")
    def handle_actor_type_property(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """Protect actor_type from deletion only -- see handle_auth_token_property."""
        if operation == "delete":
            logger.warning(
                f"Blocked deletion of protected property 'actor_type' for actor {actor.id}"
            )
            return None
        return value

    @app.property_hook("*")
    def handle_all_properties(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """
        Handle all properties with general validation.

        Triggered: On any property operation (after specific hooks like
        'email', 'auth_token', 'created_at', 'actor_type' above).

        This hook cannot enforce per-property hiding/protection itself: the
        wildcard "*" hook is called with (actor, operation, value, path),
        where `path` is only the nested-subkey remainder, never the
        top-level property name -- see the comment on
        handle_auth_token_property above. Protection for specific
        properties is registered by exact name instead.

        Behaviors:
        - Parses JSON strings into objects for PUT/POST

        Parameters:
            actor: The ActorInterface instance
            operation: "get", "put", "post", or "delete"
            value: The value being operated on
            path: Property path as list

        Returns:
            Transformed value to allow, None to block
        """
        # Handle JSON string conversion for PUT/POST
        if operation in ["put", "post"]:
            if isinstance(value, str):
                try:
                    # Try to parse JSON strings into objects. Note this
                    # silently coerces e.g. "123" -> 123 or "true" -> True --
                    # a plain string that happens to look like JSON does not
                    # stay a string.
                    parsed = json.loads(value)
                    return parsed
                except (json.JSONDecodeError, TypeError):
                    # Not valid JSON, return as-is
                    return value

        return value
