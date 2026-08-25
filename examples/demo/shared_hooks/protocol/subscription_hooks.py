"""
Shared subscription hooks for ActingWeb demo applications.

Subscription hooks handle the ActingWeb subscription protocol - the mechanism
by which trusted actors can subscribe to changes in each other's data.

This is PROTOCOL-LEVEL functionality, not app-specific. When Actor A subscribes
to Actor B's properties, Actor B will send subscription callbacks to Actor A
whenever those properties change.

The subscription hook processes incoming subscription data from trusted peers
and determines how to handle the updates (store them, trigger actions, etc.).

For app-specific external webhooks (email verification, SMS, payment callbacks),
see callback_hooks.py instead.
"""

import logging
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_subscription_hooks(app):
    """Register subscription hooks with the ActingWeb application."""

    @app.subscription_hook
    def handle_subscription_data(
        actor: ActorInterface,
        subscription: dict[str, Any],
        peer_id: str,
        data: dict[str, Any],
    ) -> bool:
        """
        Handle incoming subscription data from trusted peers.

        Triggered: When a trusted peer sends subscription data updates

        This hook is called by the ActingWeb framework when an actor we've
        subscribed to sends us updated data. The subscription was established
        via the /subscriptions endpoint after a trust relationship was created.

        Parameters:
            actor: The local ActorInterface receiving the data
            subscription: Subscription metadata including:
                - subscriptionid: Unique identifier for this subscription
                - target: What we subscribed to (e.g., "properties")
                - subtarget: Optional sub-path within target
                - granularity: Level of detail in updates
            peer_id: ID of the peer actor sending the data
            data: The subscription payload (structure depends on target)

        Returns:
            True to acknowledge successful processing
            False to indicate processing failed (peer may retry)

        Example subscription flow:
            1. Actor A creates trust with Actor B
            2. Actor A subscribes to Actor B's properties
            3. Actor B updates a property
            4. Actor B sends the update to Actor A via this hook
            5. Actor A processes and stores the update
        """
        subscription_id = subscription.get("subscriptionid", "unknown")
        target = subscription.get("target", "unknown")

        logger.debug(
            f"Received subscription data: id={subscription_id}, "
            f"target={target}, peer={peer_id}, data={data}"
        )

        # Process subscription data based on target type
        if target == "properties":
            # Handle property changes from peer
            if isinstance(data, dict) and actor.properties is not None:
                for key, value in data.items():
                    # Store peer property updates with prefix to avoid conflicts
                    actor.properties[f"peer_{peer_id}_{key}"] = value
                logger.info(f"Stored {len(data)} property updates from peer {peer_id}")

        elif target == "trust":
            # Handle trust relationship changes
            logger.info(f"Trust update from peer {peer_id}: {data}")

        else:
            # Unknown target type - log but still acknowledge
            logger.warning(
                f"Unknown subscription target '{target}' from peer {peer_id}"
            )

        return True
