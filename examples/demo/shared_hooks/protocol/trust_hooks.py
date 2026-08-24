"""
Shared trust hooks for ActingWeb demo applications.

Trust hooks handle trust relationship events in ActingWeb. These are triggered
when trust relationships are created, modified, or deleted.

Available Trust Lifecycle Events:
- trust_approved: Called after a trust relationship is approved by both parties
- trust_deleted: Called before a trust relationship is deleted

These hooks are useful for:
- Logging trust relationship changes
- Triggering workflows when new trust relationships are established
- Performing cleanup when trust relationships are removed
- Integrating with external systems for trust management
"""

import logging
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_trust_hooks(app):
    """Register all trust hooks with the ActingWeb application."""

    @app.lifecycle_hook("trust_approved")
    def on_trust_approved(
        actor: ActorInterface,
        peer_id: str = "",
        relationship: str = "",
        trust_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Handle trust approval event.

        Triggered: Automatically when a trust relationship is approved by both parties

        This hook is called when a trust relationship becomes fully established
        (both this actor and the peer have approved the relationship).

        Use cases:
        - Log trust relationship establishment
        - Notify external systems
        - Initialize resources for the trusted peer
        - Set up initial data sharing subscriptions

        Parameters:
            actor: The ActorInterface for this actor
            peer_id: ID of the peer actor in the trust relationship
            relationship: Type of relationship (e.g., "friend", "admin", "associate")
            trust_data: Dictionary containing full trust relationship details
            **kwargs: Additional context
        """
        logger.info(
            f"Trust relationship approved: {actor.id} <-> {peer_id} (relationship: {relationship})"
        )

        # Log trust relationship details
        if trust_data:
            logger.debug(f"Trust relationship details: {trust_data}")

        # You can add custom logic here, such as:
        # - Send welcome message to the peer
        # - Set up initial subscriptions
        # - Initialize shared resources
        # - Notify external systems

    @app.lifecycle_hook("trust_deleted")
    def on_trust_deleted(
        actor: ActorInterface,
        peer_id: str = "",
        relationship: str = "",
        **kwargs: Any,
    ) -> None:
        """
        Handle trust deletion event.

        Triggered: Automatically before a trust relationship is deleted

        This hook is called before a trust relationship is removed. Use it to
        perform cleanup operations before the trust is deleted.

        Use cases:
        - Log trust relationship removal
        - Clean up shared resources
        - Notify external systems
        - Archive relationship data

        Parameters:
            actor: The ActorInterface for this actor
            peer_id: ID of the peer actor whose trust is being removed
            relationship: Type of relationship being deleted
            **kwargs: Additional context
        """
        logger.info(
            f"Trust relationship deleted: {actor.id} <-> {peer_id} (relationship: {relationship})"
        )

        # Custom cleanup logic can be added here
