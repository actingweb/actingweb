"""
ActingWeb permission system initialization utility.

This module provides explicit initialization for the unified access control system
at application startup, avoiding lazy loading during request processing.
"""

import logging

from . import config as config_class

logger = logging.getLogger(__name__)


def initialize_permission_system(config: config_class.Config) -> None:
    """
    Initialize optional ActingWeb permission system at application startup.

    This initializes the unified access control system components (trust types,
    permissions, and evaluator) if available. Should be called once during
    application initialization to avoid performance issues during OAuth2 flows.

    Note: This function handles missing components gracefully - applications
    will continue working with basic functionality if the permission system is unavailable.

    Args:
        config: ActingWeb configuration object

    Raises:
        RuntimeError: If any critical permission system component fails to initialize
    """
    initialization_errors: list[str] = []

    logger.debug("Initializing ActingWeb permission system...")

    # 1. Trust Type Registry (required for trust management)
    try:
        from .trust_type_registry import initialize_registry

        initialize_registry(config)
    except Exception as e:
        error_msg = f"Failed to initialize trust type registry: {e}"
        logger.warning(f"Permission system component unavailable - {error_msg}")
        # Don't add to initialization_errors - this is optional

    # 2. Trust Permission Store (required for permission overrides) - must be before evaluator
    try:
        from .trust_permissions import initialize_trust_permission_store

        initialize_trust_permission_store(config)
    except Exception as e:
        error_msg = f"Failed to initialize trust permission store: {e}"
        logger.warning(f"Permission system component unavailable - {error_msg}")
        # Don't add to initialization_errors - this is optional

    # 3. Permission Evaluator (required for access control) - depends on trust permission store
    try:
        from .permission_evaluator import initialize_permission_evaluator

        initialize_permission_evaluator(config)
    except Exception as e:
        error_msg = f"Failed to initialize permission evaluator: {e}"
        logger.warning(f"Permission system component unavailable - {error_msg}")
        # Don't add to initialization_errors - this is optional

    if initialization_errors:
        error_summary = "; ".join(initialization_errors)
        raise RuntimeError(
            f"ActingWeb permission system initialization failed: {error_summary}"
        )

    logger.debug("ActingWeb permission system initialized successfully")


def is_permission_component_ready(component_name: str) -> bool:
    """
    Check if a specific permission system component is ready for use.

    Args:
        component_name: Name of component to check ('registry', 'evaluator', 'store')

    Returns:
        True if component is initialized and ready
    """
    try:
        if component_name == "registry":
            from .trust_type_registry import _registry

            return _registry is not None
        elif component_name == "evaluator":
            from .permission_evaluator import _permission_evaluator

            return _permission_evaluator is not None
        elif component_name == "store":
            from .trust_permissions import _permission_store

            return _permission_store is not None
        else:
            return False
    except Exception:
        return False
