"""
Hook system for ActingWeb applications.

Provides a clean decorator-based system for registering hooks that respond
to various ActingWeb events.
"""

import asyncio
import inspect
import logging
import types
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

# Import permission system for transparent permission checking
try:
    from ..permission_evaluator import PermissionResult, get_permission_evaluator

    PERMISSION_SYSTEM_AVAILABLE = True
except ImportError:
    # Fallback definitions for when permission system is not available
    get_permission_evaluator = None
    PermissionResult = None
    PERMISSION_SYSTEM_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]


def _python_type_to_json_schema(python_type: Any) -> dict[str, Any]:
    """Convert a Python type annotation to JSON schema.

    Args:
        python_type: A Python type or type annotation (int, str, list, TypedDict,
                    Union types, etc.)

    Returns:
        JSON schema dict representing the type
    """
    # Handle None type
    if python_type is type(None):
        return {"type": "null"}

    # Handle basic types
    type_mapping: dict[type, dict[str, Any]] = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }

    if python_type in type_mapping:
        return type_mapping[python_type]

    # Handle generic types (list[str], dict[str, int], etc.)
    origin = get_origin(python_type)
    args = get_args(python_type)

    # Handle Union types (including X | None for Optional)
    # Note: types.UnionType is used for X | Y syntax in Python 3.10+
    if origin is Union or isinstance(python_type, types.UnionType):
        # Check if it's Optional (Union with None)
        non_none_types = [t for t in args if t is not type(None)]
        has_none = len(non_none_types) < len(args)

        if len(non_none_types) == 1:
            # Simple Optional[X] case
            schema = _python_type_to_json_schema(non_none_types[0])
            if has_none:
                # Make nullable
                if "type" in schema:
                    current_type = schema["type"]
                    if isinstance(current_type, list):
                        if "null" not in current_type:
                            schema["type"] = current_type + ["null"]
                    else:
                        schema["type"] = [current_type, "null"]
            return schema
        else:
            # Multiple types - use anyOf
            schemas = [_python_type_to_json_schema(t) for t in args]
            return {"anyOf": schemas}

    # Handle list[X]
    if origin is list:
        schema: dict[str, Any] = {"type": "array"}
        if args:
            schema["items"] = _python_type_to_json_schema(args[0])
        return schema

    # Handle dict[K, V]
    if origin is dict:
        schema = {"type": "object"}
        if len(args) >= 2:
            schema["additionalProperties"] = _python_type_to_json_schema(args[1])
        return schema

    # Handle TypedDict
    if is_typeddict(python_type):
        return _typeddict_to_json_schema(python_type)

    # Default fallback
    return {"type": "object"}


def _typeddict_to_json_schema(typed_dict_class: type) -> dict[str, Any]:
    """Convert a TypedDict class to JSON schema.

    Args:
        typed_dict_class: A TypedDict class

    Returns:
        JSON schema dict representing the TypedDict structure
    """
    try:
        hints = get_type_hints(typed_dict_class)
    except Exception:
        return {"type": "object"}

    properties: dict[str, Any] = {}
    required: list[str] = []

    # Get required keys - TypedDict has __required_keys__ and __optional_keys__
    required_keys = getattr(typed_dict_class, "__required_keys__", frozenset())
    optional_keys = getattr(typed_dict_class, "__optional_keys__", frozenset())

    for field_name, field_type in hints.items():
        properties[field_name] = _python_type_to_json_schema(field_type)

        # Determine if field is required
        if required_keys and field_name in required_keys:
            required.append(field_name)
        elif not optional_keys or field_name not in optional_keys:
            # If no explicit optional/required info, assume required (total=True default)
            if not optional_keys and not required_keys:
                required.append(field_name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return schema


def _get_auto_schemas(
    func: Callable[..., Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Extract input and output schemas from function type hints.

    Inspects the function's type hints to auto-generate JSON schemas:
    - input_schema: From the 'data' parameter if it's a TypedDict
    - output_schema: From the return type if it's a TypedDict

    Args:
        func: The hook function to inspect

    Returns:
        Tuple of (input_schema, output_schema), either may be None
    """
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    try:
        hints = get_type_hints(func)
    except Exception:
        # Type hints may fail to resolve in some cases
        return None, None

    # Check the 'data' parameter for input schema
    # Hook signature is: func(actor, method_name, data) or func(actor, action_name, data)
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    # The data parameter is typically the 3rd parameter
    if len(params) >= 3:
        data_param = params[2]  # Usually 'data'
        if data_param in hints:
            data_type = hints[data_param]
            if is_typeddict(data_type):
                input_schema = _typeddict_to_json_schema(data_type)

    # Check return type for output schema
    if "return" in hints:
        return_type = hints["return"]
        if is_typeddict(return_type):
            output_schema = _typeddict_to_json_schema(return_type)

    return input_schema, output_schema


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


@dataclass
class HookMetadata:
    """Metadata for method/action hooks.

    This metadata is used to describe hooks for API discovery via
    GET /<actor_id>/methods and GET /<actor_id>/actions endpoints.

    Attributes:
        description: Human-readable description of what the hook does
        input_schema: JSON schema describing expected input parameters
        output_schema: JSON schema describing the expected return value
        annotations: Safety/behavior hints (e.g., readOnlyHint, destructiveHint)
    """

    description: str = ""
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


def get_hook_metadata(func: Callable[..., Any]) -> HookMetadata:
    """Get hook metadata from a decorated function.

    Priority order:
    1. Explicit _hook_metadata (from decorator parameters)
    2. MCP metadata (_mcp_metadata from @mcp_tool decorator)
    3. Auto-generated schemas from TypedDict type hints

    For each source, if input_schema or output_schema is not provided,
    attempts to auto-generate from function type hints (TypedDict only).

    Args:
        func: The hook function to get metadata from

    Returns:
        HookMetadata instance with the function's metadata
    """
    # Get auto-generated schemas from type hints (used as fallback)
    auto_input, auto_output = _get_auto_schemas(func)

    # Check for explicit hook metadata
    if hasattr(func, "_hook_metadata"):
        metadata: HookMetadata = getattr(func, "_hook_metadata")  # noqa: B009
        # Fill in auto-generated schemas if not explicitly provided
        return HookMetadata(
            description=metadata.description,
            input_schema=metadata.input_schema
            if metadata.input_schema is not None
            else auto_input,
            output_schema=metadata.output_schema
            if metadata.output_schema is not None
            else auto_output,
            annotations=metadata.annotations,
        )

    # Fall back to MCP metadata if available
    if hasattr(func, "_mcp_metadata"):
        mcp_meta = getattr(func, "_mcp_metadata")  # noqa: B009
        return HookMetadata(
            description=mcp_meta.get("description", "") or "",
            input_schema=mcp_meta.get("input_schema") or auto_input,
            output_schema=mcp_meta.get("output_schema") or auto_output,
            annotations=mcp_meta.get("annotations"),
        )

    # Return defaults with auto-generated schemas
    return HookMetadata(
        input_schema=auto_input,
        output_schema=auto_output,
    )


logger = logging.getLogger(__name__)


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
                logger.warning("Cannot determine actor ID for permission check")
                return True  # Allow if we can't determine actor

            peer_id = auth_context.get("peer_id", "")
            config = auth_context.get("config")

            if not peer_id or not config:
                return True  # No peer relationship or config

            # Get permission evaluator and check access
            if PERMISSION_SYSTEM_AVAILABLE:
                evaluator = get_permission_evaluator(config)  # type: ignore
            else:
                logger.warning(
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
                logger.warning(f"Unknown hook type for permission check: {hook_type}")
                return True

            if result == PermissionResult.ALLOWED:  # type: ignore
                return True
            elif result == PermissionResult.DENIED:  # type: ignore
                logger.info(
                    f"Hook access denied: {hook_type}:{resource_name} for {actor_id} -> {peer_id}"
                )
                return False
            else:  # NOT_FOUND
                # No specific permission rule - allow for backward compatibility
                return True

        except Exception as e:
            logger.error(f"Error in hook permission check: {e}")
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

    def _execute_hook_in_sync_context(
        self, hook: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute a hook in sync context, handling both sync and async hooks.

        For use in sync contexts only. In async contexts, use the _async methods.

        - Sync hooks: Called directly
        - Async hooks: Executed via asyncio.run() if no event loop exists,
                       or via thread pool if already in an async context

        Args:
            hook: The hook function to execute
            *args: Positional arguments to pass to the hook
            **kwargs: Keyword arguments to pass to the hook

        Returns:
            Result from the hook execution
        """
        if inspect.iscoroutinefunction(hook):
            try:
                # Check if we're already in an async context
                asyncio.get_running_loop()
                # We're in an async context - caller should use _async variant
                logger.warning(
                    f"Async hook {hook.__name__} called from sync method in async context. "
                    "Consider using execute_*_hooks_async() for better performance."
                )
                # Run in a thread pool to avoid event loop conflicts
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, hook(*args, **kwargs))
                    return future.result()
            except RuntimeError:
                # No running loop - safe to create one
                return asyncio.run(hook(*args, **kwargs))
        else:
            return hook(*args, **kwargs)

    def execute_property_hooks(
        self,
        property_name: str,
        operation: str,
        actor: Any,
        value: Any,
        path: list[str] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute property hooks with transparent permission checking.

        Note: If you have async hooks and are in an async context,
        use execute_property_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        path = path or []

        # Check permission before executing hooks
        if auth_context:
            auth_context["operation"] = operation  # Add operation to context

        property_path = "/".join([property_name] + (path or []))
        if not self._check_hook_permission(
            "property", property_path, actor, auth_context
        ):
            logger.debug(f"Property hook permission denied for {property_path}")
            return None if operation in ["put", "post"] else value

        # Execute hooks for specific property
        if property_name in self._property_hooks:
            hooks = self._property_hooks[property_name].get(operation, [])
            for hook in hooks:
                try:
                    value = self._execute_hook_in_sync_context(
                        hook, actor, operation, value, path
                    )
                    if value is None and operation in ["put", "post"]:
                        # Hook rejected the operation
                        return None
                except Exception as e:
                    logger.error(f"Error in property hook for {property_name}: {e}")
                    if operation in ["put", "post"]:
                        return None

        # Execute hooks for all properties
        if "*" in self._property_hooks:
            hooks = self._property_hooks["*"].get(operation, [])
            for hook in hooks:
                try:
                    value = self._execute_hook_in_sync_context(
                        hook, actor, operation, value, path
                    )
                    if value is None and operation in ["put", "post"]:
                        return None
                except Exception as e:
                    logger.error(f"Error in wildcard property hook: {e}")
                    if operation in ["put", "post"]:
                        return None

        return value

    def execute_callback_hooks(
        self, callback_name: str, actor: Any, data: Any
    ) -> bool | dict[str, Any]:
        """Execute callback hooks and return whether callback was processed or result data.

        Note: If you have async hooks and are in an async context,
        use execute_callback_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._callback_hooks:
            for hook in self._callback_hooks[callback_name]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, callback_name, data
                    )
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in callback hook for {callback_name}: {e}")

        # Execute hooks for all callbacks
        if "*" in self._callback_hooks:
            for hook in self._callback_hooks["*"]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, callback_name, data
                    )
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in wildcard callback hook: {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    def execute_app_callback_hooks(
        self, callback_name: str, data: Any
    ) -> bool | dict[str, Any]:
        """Execute application-level callback hooks (no actor context).

        Note: If you have async hooks and are in an async context,
        use execute_app_callback_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._app_callback_hooks:
            for hook in self._app_callback_hooks[callback_name]:
                try:
                    hook_result = self._execute_hook_in_sync_context(hook, data)
                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in app callback hook '{callback_name}': {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    def execute_subscription_hooks(
        self, actor: Any, subscription: dict[str, Any], peer_id: str, data: Any
    ) -> bool:
        """Execute subscription hooks and return whether subscription was processed.

        Note: If you have async hooks and are in an async context,
        use execute_subscription_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        processed = False

        for hook in self._subscription_hooks:
            try:
                hook_result = self._execute_hook_in_sync_context(
                    hook, actor, subscription, peer_id, data
                )
                if hook_result:
                    processed = True
            except Exception as e:
                logger.error(f"Error in subscription hook: {e}")

        return processed

    def execute_lifecycle_hooks(self, event: str, actor: Any, **kwargs: Any) -> Any:
        """Execute lifecycle hooks.

        Note: If you have async hooks and are in an async context,
        use execute_lifecycle_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        result = None

        if event in self._lifecycle_hooks:
            for hook in self._lifecycle_hooks[event]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, **kwargs
                    )
                    if hook_result is not None:
                        result = hook_result
                except Exception as e:
                    logger.error(f"Error in lifecycle hook for {event}: {e}")

        return result

    def execute_method_hooks(
        self,
        method_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute method hooks with transparent permission checking.

        Note: If you have async hooks and are in an async context,
        use execute_method_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        # Check permission before executing hooks
        if not self._check_hook_permission("method", method_name, actor, auth_context):
            logger.debug(f"Method hook permission denied for {method_name}")
            return None

        result = None

        # Execute hooks for specific method
        if method_name in self._method_hooks:
            for hook in self._method_hooks[method_name]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, method_name, data
                    )
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in method hook for {method_name}: {e}")

        # Execute hooks for all methods if no specific hook handled it
        if result is None and "*" in self._method_hooks:
            for hook in self._method_hooks["*"]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, method_name, data
                    )
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in wildcard method hook: {e}")

        return result

    def execute_action_hooks(
        self,
        action_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute action hooks with transparent permission checking.

        Note: If you have async hooks and are in an async context,
        use execute_action_hooks_async() instead for proper async execution.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop.
        """
        # Check permission before executing hooks
        if not self._check_hook_permission("action", action_name, actor, auth_context):
            logger.debug(f"Action hook permission denied for {action_name}")
            return None

        result = None

        # Execute hooks for specific action
        if action_name in self._action_hooks:
            for hook in self._action_hooks[action_name]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, action_name, data
                    )
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in action hook for {action_name}: {e}")

        # Execute hooks for all actions if no specific hook handled it
        if result is None and "*" in self._action_hooks:
            for hook in self._action_hooks["*"]:
                try:
                    hook_result = self._execute_hook_in_sync_context(
                        hook, actor, action_name, data
                    )
                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in wildcard action hook: {e}")

        return result

    # Async execution methods for native async/await support

    async def execute_method_hooks_async(
        self,
        method_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute method hooks with native async support.

        Use this method when calling from an async context (FastAPI handlers).
        Supports both sync and async hooks:
        - Async hooks are awaited directly
        - Sync hooks are called directly (sync-compatible)

        Args:
            method_name: Name of the method hook to execute
            actor: ActorInterface instance
            data: Request data/parameters
            auth_context: Optional authentication context

        Returns:
            Result from the first successful hook, or None
        """
        # Permission check (sync - fast operation)
        if not self._check_hook_permission("method", method_name, actor, auth_context):
            logger.debug(f"Method hook permission denied for {method_name}")
            return None

        result = None

        # Execute hooks for specific method
        if method_name in self._method_hooks:
            for hook in self._method_hooks[method_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, method_name, data)
                    else:
                        hook_result = hook(actor, method_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in method hook for {method_name}: {e}")

        # Execute wildcard hooks if no specific hook handled it
        if result is None and "*" in self._method_hooks:
            for hook in self._method_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, method_name, data)
                    else:
                        hook_result = hook(actor, method_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in wildcard method hook: {e}")

        return result

    async def execute_action_hooks_async(
        self,
        action_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute action hooks with native async support.

        See execute_method_hooks_async for details.

        Args:
            action_name: Name of the action hook to execute
            actor: ActorInterface instance
            data: Request data/parameters
            auth_context: Optional authentication context

        Returns:
            Result from the first successful hook, or None
        """
        if not self._check_hook_permission("action", action_name, actor, auth_context):
            logger.debug(f"Action hook permission denied for {action_name}")
            return None

        result = None

        if action_name in self._action_hooks:
            for hook in self._action_hooks[action_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, action_name, data)
                    else:
                        hook_result = hook(actor, action_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in action hook for {action_name}: {e}")

        if result is None and "*" in self._action_hooks:
            for hook in self._action_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, action_name, data)
                    else:
                        hook_result = hook(actor, action_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in wildcard action hook: {e}")

        return result

    async def execute_property_hooks_async(
        self,
        property_name: str,
        operation: str,
        actor: Any,
        value: Any,
        path: list[str] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute property hooks asynchronously with transparent permission checking.

        Args:
            property_name: Name of the property
            operation: Operation being performed (get, put, post, delete)
            actor: ActorInterface instance
            value: Property value
            path: Optional path components for nested properties
            auth_context: Optional authentication context

        Returns:
            Modified property value or None if operation was rejected
        """
        path = path or []

        # Check permission before executing hooks
        if auth_context:
            auth_context["operation"] = operation  # Add operation to context

        property_path = "/".join([property_name] + (path or []))
        if not self._check_hook_permission(
            "property", property_path, actor, auth_context
        ):
            logger.debug(f"Property hook permission denied for {property_path}")
            return None if operation in ["put", "post"] else value

        # Execute hooks for specific property
        if property_name in self._property_hooks:
            hooks = self._property_hooks[property_name].get(operation, [])
            for hook in hooks:
                try:
                    if inspect.iscoroutinefunction(hook):
                        value = await hook(actor, operation, value, path)
                    else:
                        value = hook(actor, operation, value, path)

                    if value is None and operation in ["put", "post"]:
                        # Hook rejected the operation
                        return None
                except Exception as e:
                    logger.error(f"Error in property hook for {property_name}: {e}")
                    if operation in ["put", "post"]:
                        return None

        # Execute hooks for all properties
        if "*" in self._property_hooks:
            hooks = self._property_hooks["*"].get(operation, [])
            for hook in hooks:
                try:
                    if inspect.iscoroutinefunction(hook):
                        value = await hook(actor, operation, value, path)
                    else:
                        value = hook(actor, operation, value, path)

                    if value is None and operation in ["put", "post"]:
                        return None
                except Exception as e:
                    logger.error(f"Error in wildcard property hook: {e}")
                    if operation in ["put", "post"]:
                        return None

        return value

    async def execute_callback_hooks_async(
        self, callback_name: str, actor: Any, data: Any
    ) -> bool | dict[str, Any]:
        """Execute callback hooks asynchronously.

        Args:
            callback_name: Name of the callback
            actor: ActorInterface instance
            data: Callback data

        Returns:
            True if processed, or result data dict
        """
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._callback_hooks:
            for hook in self._callback_hooks[callback_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, callback_name, data)
                    else:
                        hook_result = hook(actor, callback_name, data)

                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in callback hook for {callback_name}: {e}")

        # Execute hooks for all callbacks
        if "*" in self._callback_hooks:
            for hook in self._callback_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, callback_name, data)
                    else:
                        hook_result = hook(actor, callback_name, data)

                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in wildcard callback hook: {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    async def execute_app_callback_hooks_async(
        self, callback_name: str, data: Any
    ) -> bool | dict[str, Any]:
        """Execute application-level callback hooks asynchronously (no actor context).

        Args:
            callback_name: Name of the callback
            data: Callback data

        Returns:
            True if processed, or result data dict
        """
        processed = False
        result_data: dict[str, Any] | None = None

        # Execute hooks for specific callback
        if callback_name in self._app_callback_hooks:
            for hook in self._app_callback_hooks[callback_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(data)
                    else:
                        hook_result = hook(data)

                    if hook_result:
                        processed = True
                        if isinstance(hook_result, dict):
                            result_data = hook_result
                except Exception as e:
                    logger.error(f"Error in app callback hook '{callback_name}': {e}")

        # Return result data if available, otherwise return processed status
        if result_data is not None:
            return result_data
        return processed

    async def execute_subscription_hooks_async(
        self, actor: Any, subscription: dict[str, Any], peer_id: str, data: Any
    ) -> bool:
        """Execute subscription hooks asynchronously.

        Args:
            actor: ActorInterface instance
            subscription: Subscription information
            peer_id: ID of the peer sending the subscription event
            data: Event data

        Returns:
            True if subscription was processed
        """
        processed = False

        for hook in self._subscription_hooks:
            try:
                if inspect.iscoroutinefunction(hook):
                    if await hook(actor, subscription, peer_id, data):
                        processed = True
                else:
                    if hook(actor, subscription, peer_id, data):
                        processed = True
            except Exception as e:
                logger.error(f"Error in subscription hook: {e}")

        return processed

    async def execute_lifecycle_hooks_async(
        self, event: str, actor: Any, **kwargs: Any
    ) -> Any:
        """Execute lifecycle hooks asynchronously.

        Args:
            event: Lifecycle event name
            actor: ActorInterface instance
            **kwargs: Additional event-specific arguments

        Returns:
            Result from the last hook, or None
        """
        result = None

        if event in self._lifecycle_hooks:
            for hook in self._lifecycle_hooks[event]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, **kwargs)
                    else:
                        hook_result = hook(actor, **kwargs)

                    if hook_result is not None:
                        result = hook_result
                except Exception as e:
                    logger.error(f"Error in lifecycle hook for {event}: {e}")

        return result

    def get_method_metadata_list(self) -> list[dict[str, Any]]:
        """Get list of all registered methods with their metadata.

        Returns a list of dictionaries containing name and metadata for each method.
        Wildcard (*) hooks are excluded from listing.

        Returns:
            List of dicts with name, description, input_schema, output_schema, annotations
        """
        result = []
        for method_name, hook_list in self._method_hooks.items():
            if method_name == "*":
                continue  # Don't list wildcard hooks

            # Get metadata from first hook (primary hook)
            if hook_list:
                metadata = get_hook_metadata(hook_list[0])
                result.append(
                    {
                        "name": method_name,
                        "description": metadata.description,
                        "input_schema": metadata.input_schema,
                        "output_schema": metadata.output_schema,
                        "annotations": metadata.annotations,
                    }
                )
        return result

    def get_action_metadata_list(self) -> list[dict[str, Any]]:
        """Get list of all registered actions with their metadata.

        Returns a list of dictionaries containing name and metadata for each action.
        Wildcard (*) hooks are excluded from listing.

        Returns:
            List of dicts with name, description, input_schema, output_schema, annotations
        """
        result = []
        for action_name, hook_list in self._action_hooks.items():
            if action_name == "*":
                continue  # Don't list wildcard hooks

            # Get metadata from first hook (primary hook)
            if hook_list:
                metadata = get_hook_metadata(hook_list[0])
                result.append(
                    {
                        "name": action_name,
                        "description": metadata.description,
                        "input_schema": metadata.input_schema,
                        "output_schema": metadata.output_schema,
                        "annotations": metadata.annotations,
                    }
                )
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


def method_hook(
    method_name: str = "*",
    description: str = "",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    """
    Decorator for registering method hooks with optional metadata.

    Args:
        method_name: Name of method to hook ("*" for all methods)
        description: Human-readable description of what the method does
        input_schema: JSON schema describing expected input parameters
        output_schema: JSON schema describing the expected return value
        annotations: Safety/behavior hints (e.g., readOnlyHint, idempotentHint)

    Example:
        .. code-block:: python

            @method_hook(
                "calculate",
                description="Perform a mathematical calculation",
                input_schema={
                    "type": "object",
                    "properties": {"x": {"type": "number"}},
                    "required": ["x"]
                },
                annotations={"readOnlyHint": True}
            )
            def handle_calculate_method(actor, method_name, data):
                # Execute RPC-style method
                result = perform_calculation(data)
                return {"result": result}
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        # Store metadata on function
        metadata = HookMetadata(
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            annotations=annotations,
        )
        setattr(func, "_hook_metadata", metadata)  # noqa: B010

        _hook_registry.register_method_hook(method_name, func)
        return func

    return decorator


def action_hook(
    action_name: str = "*",
    description: str = "",
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    """
    Decorator for registering action hooks with optional metadata.

    Args:
        action_name: Name of action to hook ("*" for all actions)
        description: Human-readable description of what the action does
        input_schema: JSON schema describing expected input parameters
        output_schema: JSON schema describing the expected return value
        annotations: Safety/behavior hints (e.g., destructiveHint, readOnlyHint)

    Example:
        .. code-block:: python

            @action_hook(
                "delete_record",
                description="Permanently delete a record",
                input_schema={
                    "type": "object",
                    "properties": {"record_id": {"type": "string"}},
                    "required": ["record_id"]
                },
                annotations={"destructiveHint": True, "readOnlyHint": False}
            )
            def handle_delete(actor, action_name, data):
                # Execute trigger-based action
                delete_record(data.get("record_id"))
                return {"status": "deleted"}
    """

    def decorator(func: Callable[..., Any]) -> Callable:
        # Store metadata on function
        metadata = HookMetadata(
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            annotations=annotations,
        )
        setattr(func, "_hook_metadata", metadata)  # noqa: B010

        _hook_registry.register_action_hook(action_name, func)
        return func

    return decorator


def get_hook_registry() -> HookRegistry:
    """Get the global hook registry."""
    return _hook_registry
