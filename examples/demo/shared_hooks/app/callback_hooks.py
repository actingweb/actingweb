"""
Shared callback hooks for ActingWeb demo applications.

Callback hooks provide endpoints for EXTERNAL SYSTEMS to communicate with actors.
These are app-specific integrations - URLs you give to third-party services so
they can notify your actor of events.

Examples of app-specific callbacks:
- Email verification: Give a callback URL to email service, user clicks link
- SMS webhooks: Receive incoming SMS messages from Twilio/MessageBird
- Payment notifications: Stripe/PayPal webhook for payment status
- Bot integrations: Slack/Discord bot webhooks

Callbacks are invoked via: POST /{actor_id}/callbacks/{callback_name}
Application-level callbacks: POST /{callback_name} (no actor context)

For ActingWeb protocol-level subscription handling between trusted actors,
see subscription_hooks.py instead.

Example usage:
    # Give this URL to an external service:
    https://your-app.com/{actor_id}/callbacks/email_verify?token=abc123

    # The service calls your callback when the event occurs
"""

import logging
from datetime import datetime
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_callback_hooks(app):
    """Register callback hooks with the ActingWeb application."""

    @app.callback_hook("email_verify")
    def handle_email_verification(
        actor: ActorInterface, name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Handle email verification callbacks.

        Endpoint: GET/POST /{actor_id}/callbacks/email_verify

        Use case: When creating an actor, send a verification email with a link
        containing a token. When the user clicks the link, this callback is
        triggered to verify their email address.

        Parameters:
            token: Verification token from the email link
            method: HTTP method used (GET for link clicks, POST for API calls)

        Returns:
            Success/failure response with verification status

        Example flow:
            1. Actor created with email "user@example.com"
            2. App sends email with link: /callbacks/email_verify?token=abc123
            3. User clicks link, this callback validates the token
            4. Actor's email_verified property is set to true
        """
        token = data.get("token", "")

        logger.info(
            f"Email verification callback for actor {actor.id}: token={token[:8]}..."
        )

        if not token:
            return {"status": "error", "message": "Missing verification token"}

        # In a real implementation, you would:
        # 1. Validate the token against a stored value
        # 2. Check token expiration
        # 3. Mark the email as verified

        # Demo implementation - just check if token exists
        stored_token = actor.properties.get("email_verification_token", "")
        if token == stored_token:
            if actor.properties is not None:
                actor.properties.email_verified = True
                actor.properties.email_verified_at = datetime.now().isoformat()
            return {
                "status": "success",
                "message": "Email verified successfully",
                "actor_id": actor.id,
            }
        else:
            return {
                "status": "error",
                "message": "Invalid or expired verification token",
            }

    @app.callback_hook("sms_webhook")
    def handle_sms_webhook(
        actor: ActorInterface, name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Handle incoming SMS webhook from a provider (e.g., Twilio, MessageBird).

        Endpoint: POST /{actor_id}/callbacks/sms_webhook

        Use case: Register this callback URL with your SMS provider. When someone
        sends an SMS to your number, the provider POSTs the message here.

        Parameters (typical Twilio format):
            From: Sender phone number
            To: Your phone number
            Body: SMS message content
            MessageSid: Unique message identifier

        Returns:
            Acknowledgment response for the SMS provider

        Example:
            Register https://your-app.com/{actor_id}/callbacks/sms_webhook
            with Twilio. Incoming SMS to your number triggers this callback.
        """
        sender = data.get("From", data.get("from", "unknown"))
        body = data.get("Body", data.get("body", ""))
        message_id = data.get("MessageSid", data.get("message_id", ""))

        logger.info(
            f"SMS webhook for actor {actor.id}: from={sender}, body={body[:50]}..."
        )

        # Store the incoming message
        if actor.properties is not None:
            messages = actor.properties.get("sms_messages", [])
            if not isinstance(messages, list):
                messages = []
            messages.append(
                {
                    "from": sender,
                    "body": body,
                    "message_id": message_id,
                    "received_at": datetime.now().isoformat(),
                }
            )
            # Keep last 100 messages
            actor.properties.sms_messages = messages[-100:]

        return {
            "status": "received",
            "message_id": message_id,
            "actor_id": actor.id,
        }

    @app.callback_hook("payment_webhook")
    def handle_payment_webhook(
        actor: ActorInterface, name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Handle payment provider webhooks (e.g., Stripe, PayPal).

        Endpoint: POST /{actor_id}/callbacks/payment_webhook

        Use case: Register this callback with your payment provider. When a
        payment succeeds, fails, or is refunded, the provider notifies you here.

        Parameters (typical Stripe format):
            type: Event type (e.g., "payment_intent.succeeded")
            data: Event data containing payment details

        Returns:
            Acknowledgment response for the payment provider

        Security note: In production, verify webhook signatures!
        """
        event_type = data.get("type", "unknown")

        logger.info(f"Payment webhook for actor {actor.id}: type={event_type}")

        # Handle different payment events
        if event_type == "payment_intent.succeeded":
            if actor.properties is not None:
                actor.properties.payment_status = "paid"
                actor.properties.last_payment_at = datetime.now().isoformat()
            return {"status": "processed", "event": event_type}

        elif event_type == "payment_intent.payment_failed":
            if actor.properties is not None:
                actor.properties.payment_status = "failed"
            return {"status": "processed", "event": event_type}

        elif event_type == "charge.refunded":
            if actor.properties is not None:
                actor.properties.payment_status = "refunded"
            return {"status": "processed", "event": event_type}

        else:
            # Acknowledge unknown events (don't fail the webhook)
            logger.warning(f"Unhandled payment event type: {event_type}")
            return {"status": "ignored", "event": event_type}

    # Application-level callback hooks (no actor context)
    @app.app_callback_hook("bot")
    def handle_bot_callback(data: dict[str, Any]) -> bool:
        """
        Handle bot platform webhooks (application-level, no actor context).

        Endpoint: POST /bot

        Use case: Register this callback with Slack, Discord, or other bot
        platforms. Incoming messages and events are posted here.

        This is an APPLICATION-LEVEL callback - it's not associated with a
        specific actor. Use this when the bot needs to handle messages before
        determining which actor (if any) should process them.

        Parameters:
            method: HTTP method (only POST is processed)
            body: Bot platform webhook payload

        Returns:
            True to acknowledge successful processing
            False if bot is not configured or processing failed

        Configuration Required:
            APP_BOT_TOKEN environment variable must be set
        """
        if data.get("method") == "POST":
            # Safety valve - make sure bot is configured
            config = app.get_config()
            if (
                not config
                or not config.bot
                or not config.bot.get("token")
                or len(config.bot.get("token", "")) == 0
            ):
                logger.warning("Bot callback received but bot is not configured")
                return False

            # Process bot request
            logger.debug("Bot callback received")
            # In a real implementation, parse the bot payload and route to
            # the appropriate actor or handle the command
            return True
        return False
