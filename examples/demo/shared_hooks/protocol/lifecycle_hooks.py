"""
Shared lifecycle hooks for ActingWeb demo applications.

Lifecycle hooks handle actor lifecycle events. These are automatically triggered
by the framework at specific points in an actor's lifecycle - they cannot be
called directly via API endpoints.

Available Lifecycle Events:
- actor_created: Called when a new actor is created
- actor_deleted: Called before an actor is deleted
- oauth_success: Called after successful OAuth authentication

These hooks are useful for:
- Setting initial actor properties
- Performing cleanup on deletion
- Recording authentication events
- Integrating with external systems on actor state changes
"""

import logging
from datetime import datetime
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_lifecycle_hooks(app):
    """Register all lifecycle hooks with the ActingWeb application."""

    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs: Any) -> None:
        """
        Handle actor creation event.

        Triggered: Automatically when a new actor is created via POST /

        This hook sets initial properties for the new actor including:
        - demo_version: Version of the demo application
        - interface_version: Which ActingWeb interface is being used
        - created_at: Timestamp of actor creation

        Parameters:
            actor: The newly created ActorInterface instance
            **kwargs: Additional context (may include creator info, request data)
        """
        logger.info(f"New actor created: {actor.id} for {actor.creator}")

        # Set initial properties
        if actor.properties is not None:
            actor.properties.demo_version = "2.3"
            actor.properties.interface_version = "modern"
            actor.properties.created_at = datetime.now().isoformat()

    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor: ActorInterface, **kwargs: Any) -> None:
        """
        Handle actor deletion event.

        Triggered: Automatically before an actor is deleted via DELETE /{actor_id}

        This hook allows for custom cleanup operations before the actor
        is removed. The framework handles standard cleanup (properties,
        trust relationships, subscriptions) automatically.

        Use cases:
        - Notify external systems of actor removal
        - Archive actor data before deletion
        - Clean up external resources

        Parameters:
            actor: The ActorInterface instance being deleted
            **kwargs: Additional context
        """
        logger.info(f"Actor {actor.id} is being deleted")

        # Custom cleanup could be performed here
        # The framework handles standard cleanup automatically

    @app.lifecycle_hook("oauth_success")
    def on_oauth_success(actor: ActorInterface, **kwargs: Any) -> bool:
        """
        Handle successful OAuth authentication event.

        Triggered: Automatically after successful OAuth callback

        This hook is called when a user successfully completes OAuth
        authentication. It's useful for:
        - Recording authentication timestamps
        - Triggering post-authentication workflows
        - Updating user preferences from OAuth provider data

        Parameters:
            actor: The ActorInterface for the authenticated user
            **kwargs: May include OAuth provider data, tokens, etc.

        Returns:
            True to allow the OAuth flow to continue
            False to reject the authentication (not common)
        """
        logger.info(f"OAuth successful for actor {actor.id}")

        # Store OAuth success timestamp
        if actor.properties is not None:
            actor.properties.oauth_success_at = datetime.now().isoformat()
            actor.properties.last_login = datetime.now().isoformat()

        return True
