"""
Hook system for ActingWeb applications.

Provides a clean decorator-based system for registering hooks that respond
to various ActingWeb events.
"""

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

# Import permission system for transparent permission checking
try:
    from ..permission_evaluator import PermissionResult, get_permission_evaluator

    PERMISSION_SYSTEM_AVAILABLE = True
except ImportError:
    # Fallback definitions for when permission system is not available
    get_permission_evaluator = None
    PermissionResult = None
    PERMISSION_SYSTEM_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]


class HookType(Enum):
    """Types of hooks available."""

    PROPERTY = "property"
    CALLBACK = "callback"
    SUBSCRIPTION = "subscription"
    LIFECYCLE = "lifecycle"
    METHOD = "method"
    ACTION = "action"


class PropertyOperation(Enum):
    """Property operations that can be hooked."""

    GET = "get"
    PUT = "put"
    POST = "post"
    DELETE = "delete"


class LifecycleEvent(Enum):
    """Lifecycle events that can be hooked."""

    ACTOR_CREATED = "actor_created"
    ACTOR_DELETED = "actor_deleted"
    OAUTH_SUCCESS = "oauth_success"
    TRUST_APPROVED = "trust_approved"
    TRUST_DELETED = "trust_deleted"


class HookRegistry:
    """
    Registry for managing application hooks.

    Hooks allow applications to customize ActingWeb behavior at key points
    without modifying the core library.
    """

    def __init__(self) -> None:
        self._property_hooks: dict[str, dict[str, list[Callable[..., Any]]]] = {}
        self._callback_hooks: dict[str, list[Callable[..., Any]]] = {}
        self._app_callback_hooks: dict[
            str, list[Callable[..., Any]]
        ] = {}  # New: for application-level callbacks
        self._subscription_hooks: list[Callable[..., Any]] = []
        self._lifecycle_hooks: dict[str, list[Callable[..., Any]]] = {}
        self._method_hooks: dict[
            str, list[Callable[..., Any]]
        ] = {}  # New: for method hooks
        self._action_hooks: dict[
            str, list[Callable[..., Any]]
        ] = {}  # New: for action hooks

    def _check_hook_permission(
        self,
        hook_type: str,
        resource_name: str,
        actor: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Check if hook execution is permitted based on unified access control.

        This provides transparent permission checking for hooks, so developers
        don't need to add explicit permission checks in their hook functions.

        Args:
            hook_type: Type of hook ('property', 'method', 'action')
            resource_name: Name of resource being accessed
            actor: Actor instance
            auth_context: Authentication context with peer information

        Returns:
            True if access is permitted, False otherwise
        """
        if not PERMISSION_SYSTEM_AVAILABLE:
            # Permission system not available - allow access
            return True

        if not auth_context or not auth_context.get("peer_id"):
            # No peer context - this is likely basic/oauth auth, allow access
            return True

        try:
            # Extract context
            actor_id = getattr(actor, "id", None) or getattr(actor, "actor_id", None)
            if not actor_id:
                logging.warning("Cannot determine actor ID for permission check")
                return True  # Allow if we can't determine actor

            peer_id = auth_context.get("peer_id", "")
            config = auth_context.get("config")

            if not peer_id or not config:
                return True  # No peer relationship or config

            # Get permission evaluator and check access
            if PERMISSION_SYSTEM_AVAILABLE:
                evaluator = get_permission_evaluator(config)  # type: ignore
            else:
                logging.warning(
                    "Permission system is not available due to failed import."
                )
                return True

            if hook_type == "property":
                hook_operation = auth_context.get("operation", "get")
                # Map hook operations to permission operations
                operation_map = {
                    "get": "read",
                    "put": "write",
                    "post": "write",
                    "delete": "delete",
                }
                permission_operation = operation_map.get(hook_operation, "read")
                result = evaluator.evaluate_property_access(
                    actor_id, peer_id, resource_name, permission_operation
                )
            elif hook_type == "method":
                result = evaluator.evaluate_method_access(
                    actor_id, peer_id, resource_name
                )
            elif hook_type == "action":
                result = evaluator.evaluate_action_access(
                    actor_id, peer_id, resource_name
                )
            else:
                logging.warning(f"Unknown hook type for permission check: {hook_type}")
                return True

            if result == PermissionResult.ALLOWED:  # type: ignore
                return True
            elif result == PermissionResult.DENIED:  # type: ignore
                logging.info(
                    f"Hook access denied: {hook_type}:{resource_name} for {actor_id} -> {peer_id}"
                )
                return False
            else:  # NOT_FOUND
                # No specific permission rule - allow for backward compatibility
                return True

        except Exception as e:
            logging.error(f"Error in hook permission check: {e}")
            return True  # Allow on errors to maintain compatibility

    def register_property_hook(
        self, property_name: str, func: Callable[..., Any]
    ) -> None:
        """
        Register a property hook function.

        Args:
            property_name: Name of property to hook ("*" for all properties)
            func: Function with signature (actor, operation, value, path) -> Any
        """
        if property_name not in self._property_hooks:
            self._property_hooks[property_name] = {
                "get": [],
                "put": [],
                "post": [],
                "delete": [],
            }

        # Register for all operations unless function specifies otherwise
        operations = getattr(func, "_operations", ["get", "put", "post", "delete"])
        for op in operations:
            if op in self._property_hooks[property_name]:
                self._property_hooks[property_name][op].append(func)

    def register_callback_hook(
        self, callback_name: str, func: Callable[..., Any]
    ) -> None:
        """
        Register a callback hook function.

        Args:
            callback_name: Name of callback to hook ("*" for all callbacks)
            func: Function with signature (actor, name, data) -> bool
        """
        if callback_name not in self._callback_hooks:
            self._callback_hooks[callback_name] = []
        self._callback_hooks[callback_name].append(func)

    def register_app_callback_hook(
        self, callback_name: str, func: Callable[..., Any]
    ) -> None:
        """
        Register an application-level callback hook function.

        Args:
            callback_name: Name of callback to hook (e.g., "bot", "oauth")
            func: Function with signature (data) -> Any (no actor parameter)
        """
        if callback_name not in self._app_callback_hooks:
            self._app_callback_hooks[callback_name] = []
        self._app_callback_hooks[callback_name].append(func)

    def register_subscription_hook(self, func: Callable[..., Any]) -> None:
        """
        Register a subscription hook function.

        Args:
            func: Function with signature (actor, subscription, peer_id, data) -> bool
        """
        self._subscription_hooks.append(func)

    def register_lifecycle_hook(self, event: str, func: Callable[..., Any]) -> None:
        """
        Register a lifecycle hook function.

        Args:
            event: Lifecycle event name
            func: Function with signature ``(actor, **kwargs) -> Any``
        """
        if event not in self._lifecycle_hooks:
            self._lifecycle_hooks[event] = []
        self._lifecycle_hooks[event].append(func)

    def register_method_hook(self, method_name: str, func: Callable[..., Any]) -> None:
        """
        Register a method hook function.

        Args:
            method_name: Name of method to hook ("*" for all methods)
            func: Function with signature (actor, method_name, data) -> Any
        """
        if method_name not in self._method_hooks:
            self._method_hooks[method_name] = []
        self._method_hooks[method_name].append(func)

    def register_action_hook(self, action_name: str, func: Callable[..., Any]) -> None:
        """
        Register an action hook function.

        Args:
            action_name: Name of action to hook ("*" for all actions)
            func: Function with signature (actor, action_name, data) -> Any
        """
        if action_name not in self._action_hooks:
            self._action_hooks[action_name] = []
        self._action_hooks[action_name].append(func)

    def execute_property_hooks(
        self,
        property_name: str,
        operation: str,
        actor: Any,
        value: Any,
        path: list[str] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute property hooks with transparent permission checking."""
        path = path or []

        # Check permission before executing hooks
        if auth_context:
            auth_context["operation"] = operation  # Add operation to context

        property_path = "/".join([property_name] + (path or []))
        if not self._check_hook_permission(
            "property", property_path, actor, auth_context
        ):
            logging.debug(f"Property hook permission denied for {property_path}")
            return None if operation in ["put", "post"] else value

        # Execute hooks for specific property
        if property_name in self._property_hooks:
            hooks = self._property_hooks[property_name].get(operation, [])
            for hook in hooks:
                try:
                    value = hook(actor, operation, value, path)
                    if value is None and operation in ["put", "post"]:
                        # Hook rejected the operation
                        return None
                except Exception as e:
                    logging.error(f"Error in property hook for {property_name}: {e}")
                    if operation in ["put", "post"]:
                        return None

        # Execute hooks for all properties
        if "*" in self._property_hooks:
            hooks = self._property_hooks["*"].get(operation, [])
            for hook in hooks:
                try:
                    value = hook(actor, operation, value, path)
                    if value is None and operation in ["put", "post"]:
                        return None
                except Exception as e:
                    logging.error(f"Error in wildcard property hook: {e}")
                    if operation in ["put", "post"]:
                        return None

        return value

    def execute_callback_hooks(
        self, callback_name: str, actor: Any, data: Any
    ) -> bool | dict[str, Any]:
        """Execute callback hooks and return whether callback was processed or result data."""
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._callback_hooks:
            for hook in self._callback_hooks[callback_name]:
                try:
                    hook_result = hook(actor, callback_name, data)
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logging.error(f"Error in callback hook for {callback_name}: {e}")

        # Execute hooks for all callbacks
        if "*" in self._callback_hooks:
            for hook in self._callback_hooks["*"]:
                try:
                    hook_result = hook(actor, callback_name, data)
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logging.error(f"Error in wildcard callback hook: {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    def execute_app_callback_hooks(
        self, callback_name: str, data: Any
    ) -> bool | dict[str, Any]:
        """Execute application-level callback hooks (no actor context)."""
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._app_callback_hooks:
            for hook in self._app_callback_hooks[callback_name]:
                try:
                    hook_result = hook(data)
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logging.error(f"Error in app callback hook '{callback_name}': {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    def execute_subscription_hooks(
        self, actor: Any, subscription: dict[str, Any], peer_id: str, data: Any
    ) -> bool:
        """Execute subscription hooks and return whether subscription was processed."""
        processed = False

        for hook in self._subscription_hooks:
            try:
                if hook(actor, subscription, peer_id, data):
                    processed = True
            except Exception as e:
                logging.error(f"Error in subscription hook: {e}")

        return processed

    def execute_lifecycle_hooks(self, event: str, actor: Any, **kwargs) -> Any:
        """Execute lifecycle hooks."""
        result = None

        if event in self._lifecycle_hooks:
            for hook in self._lifecycle_hooks[event]:
                try:
                    hook_result = hook(actor, **kwargs)
                    if hook_result is not None:
                        result = hook_result
                except Exception as e:
                    logging.error(f"Error in lifecycle hook for {event}: {e}")

        return result

    def execute_method_hooks(
        self,
        method_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute method hooks with transparent permission checking."""
        # Check permission before executing hooks
        if not self._check_hook_permission("method", method_name, actor, auth_context):
            logging.debug(f"Method hook permission denied for {method_name}")
            return None

        result = None

        # Execute hooks for specific method
        if method_name in self._method_hooks:
            for hook in self._method_hooks[method_name]:
                try:
                    hook_result = hook(actor, method_name, data)
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logging.error(f"Error in method hook for {method_name}: {e}")

        # Execute hooks for all methods if no specific hook handled it
        if result is None and "*" in self._method_hooks:
            for hook in self._method_hooks["*"]:
                try:
                    hook_result = hook(actor, method_name, data)
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logging.error(f"Error in wildcard method hook: {e}")

        return result

    def execute_action_hooks(
        self,
        action_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute action hooks with transparent permission checking."""
        # Check permission before executing hooks
        if not self._check_hook_permission("action", action_name, actor, auth_context):
            logging.debug(f"Action hook permission denied for {action_name}")
            return None

        result = None

        # Execute hooks for specific action
        if action_name in self._action_hooks:
            for hook in self._action_hooks[action_name]:
                try:
                    hook_result = hook(actor, action_name, data)
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logging.error(f"Error in action hook for {action_name}: {e}")

        # Execute hooks for all actions if no specific hook handled it
        if result is None and "*" in self._action_hooks:
            for hook in self._action_hooks["*"]:
                try:
                    hook_result = hook(actor, action_name, data)
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logging.error(f"Error in wildcard action hook: {e}")

        return result


# Global hook registry instance
_hook_registry = HookRegistry()


def property_hook(
    property_name: str = "*", operations: list[str] | None = None
) -> Callable[..., Any]:
    """
    Decorator for registering property hooks.

    Args:
        property_name: Name of property to hook ("*" for all)
        operations: List of operations to hook (default: all)

    Example:
        .. code-block:: python

            @property_hook("email", ["get", "put"])
            def handle_email(actor, operation, value, path):
                if operation == "get":
                    return value if actor.is_owner() else None
                elif operation == "put":
                    return value.lower() if "@" in value else None
                return value
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        setattr(func, "_operations", operations or ["get", "put", "post", "delete"])  # noqa: B010
        _hook_registry.register_property_hook(property_name, func)
        return func

    return decorator


def callback_hook(callback_name: str = "*") -> Callable[..., Any]:
    """
    Decorator for registering actor-level callback hooks.

    Args:
        callback_name: Name of callback to hook ("*" for all)

    Example:
        .. code-block:: python

            @callback_hook("ping")
            def handle_ping_callback(actor, name, data):
                # Process actor-level callback
                return True
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        _hook_registry.register_callback_hook(callback_name, func)
        return func

    return decorator


def app_callback_hook(callback_name: str) -> Callable[..., Any]:
    """
    Decorator for registering application-level callback hooks (no actor context).

    Args:
        callback_name: Name of callback to hook (e.g., "bot", "oauth")

    Example:
        .. code-block:: python

            @app_callback_hook("bot")
            def handle_bot_callback(data):
                # Process bot callback (no actor context)
                return True
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        _hook_registry.register_app_callback_hook(callback_name, func)
        return func

    return decorator


def subscription_hook(func: Callable[..., Any]) -> Callable:
    """
    Decorator for registering subscription hooks.

    Example:
        .. code-block:: python

            @subscription_hook
            def handle_subscription(actor, subscription, peer_id, data):
                # Process subscription callback
                return True
    """
    _hook_registry.register_subscription_hook(func)
    return func


def lifecycle_hook(event: str) -> Callable[..., Any]:
    """
    Decorator for registering lifecycle hooks.

    Args:
        event: Lifecycle event name

    Example:
        .. code-block:: python

            @lifecycle_hook("actor_created")
            def on_actor_created(actor, **kwargs):
                # Initialize actor
                actor.properties.created_at = datetime.now()
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        _hook_registry.register_lifecycle_hook(event, func)
        return func

    return decorator


def method_hook(method_name: str = "*") -> Callable[..., Any]:
    """
    Decorator for registering method hooks.

    Args:
        method_name: Name of method to hook ("*" for all methods)

    Example:
        .. code-block:: python

            @method_hook("calculate")
            def handle_calculate_method(actor, method_name, data):
                # Execute RPC-style method
                result = perform_calculation(data)
                return {"result": result}
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        _hook_registry.register_method_hook(method_name, func)
        return func

    return decorator


def action_hook(action_name: str = "*") -> Callable[..., Any]:
    """
    Decorator for registering action hooks.

    Args:
        action_name: Name of action to hook ("*" for all actions)

    Example:
        .. code-block:: python

            @action_hook("send_notification")
            def handle_send_notification(actor, action_name, data):
                # Execute trigger-based action
                send_notification(data.get("message"))
                return {"status": "sent"}
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        _hook_registry.register_action_hook(action_name, func)
        return func

    return decorator


def get_hook_registry() -> HookRegistry:
    """Get the global hook registry."""
    return _hook_registry
