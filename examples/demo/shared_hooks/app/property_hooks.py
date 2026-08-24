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
- email: Special handling for email property (hidden, validated, protected)
- *: Wildcard hook for all properties (JSON parsing, protection rules)

Property Protection Levels:
- PROP_HIDE: Properties hidden from GET requests (email, auth_token)
- PROP_PROTECT: Properties protected from modification/deletion

Return Values:
- Return the (possibly transformed) value to allow the operation
- Return None to block the operation
"""

import json
import logging
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Properties that should be hidden from external access
PROP_HIDE = ["email", "auth_token"]

# Properties protected from modification and deletion
PROP_PROTECT = PROP_HIDE + ["created_at", "actor_type"]


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

    @app.property_hook("*")
    def handle_all_properties(
        actor: ActorInterface, operation: str, value: Any, path: list[str]
    ) -> Any | None:
        """
        Handle all properties with general validation and protection.

        Triggered: On any property operation (after specific hooks like 'email')

        Behaviors:
        - Protects PROP_PROTECT properties from deletion
        - Blocks PUT/POST on PROP_HIDE properties
        - Parses JSON strings into objects for PUT/POST

        Parameters:
            actor: The ActorInterface instance
            operation: "get", "put", "post", or "delete"
            value: The value being operated on
            path: Property path as list

        Returns:
            Transformed value to allow, None to block
        """
        if not path:
            return value

        property_name = path[0] if path else ""

        # Apply protection rules
        if property_name in PROP_PROTECT:
            if operation == "delete":
                logger.warning(
                    f"Blocked deletion of protected property '{property_name}' for actor {actor.id}"
                )
                return None
            elif operation in ["put", "post"] and property_name in PROP_HIDE:
                logger.warning(
                    f"Blocked modification of hidden property '{property_name}' for actor {actor.id}"
                )
                return None

        # Handle JSON string conversion for PUT/POST
        if operation in ["put", "post"]:
            if isinstance(value, str):
                try:
                    # Try to parse JSON strings into objects
                    parsed = json.loads(value)
                    return parsed
                except (json.JSONDecodeError, TypeError):
                    # Not valid JSON, return as-is
                    return value

        return value
