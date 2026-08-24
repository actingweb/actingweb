"""
Shared action hooks for ActingWeb demo applications.

Action hooks handle operations that produce external effects beyond state management.
Per the ActingWeb spec, actions are for "something that happens outside the actor"
such as sending notifications, controlling IoT devices, or triggering external systems.

Actions are invoked via: POST /{actor_id}/actions/{action_name}
with JSON body containing the action parameters.

Available Actions:
- log_message: Log a message at specified level (info/warning/error)
- send_notification: Simulate sending a notification (email/sms/push)

Note: For internal state modifications, use the /properties endpoint directly.
For read-only operations, use /methods instead -- except `search`, which is
registered as an action hook in method_hooks.py despite being read-only,
because MCP tools are discovered from action hooks only. See the comment
above its registration there.

Example usage with curl:
    curl -X POST https://host/{actor_id}/actions/log_message \\
         -H "Content-Type: application/json" \\
         -d '{"message": "Hello from action", "level": "info"}'

    curl -X POST https://host/{actor_id}/actions/send_notification \\
         -H "Content-Type: application/json" \\
         -d '{"recipient": "user@example.com", "message": "Hello!", "type": "email"}'
"""

import logging
from datetime import datetime
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_action_hooks(app):
    """Register all action hooks with the ActingWeb application."""

    @app.action_hook(
        "log_message",
        description="Log a message at the specified log level (info, warning, or error).",
        input_schema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to log",
                },
                "level": {
                    "type": "string",
                    "enum": ["info", "warning", "error"],
                    "description": "Log level",
                    "default": "info",
                },
            },
            "required": ["message"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Status of the operation"},
                "message": {"type": "string", "description": "The logged message"},
                "level": {"type": "string", "description": "Log level used"},
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the message was logged",
                },
            },
            "required": ["status", "message", "level", "timestamp"],
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_log_message_action(
        actor: ActorInterface, action_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Log a message at the specified level.

        Endpoint: POST /{actor_id}/actions/log_message

        Parameters:
            message (str): The message to log
            level (str): Log level - "info", "warning", or "error" (default: "info")

        Returns:
            {status, message, level, timestamp}
        """
        message = data.get("message", "")
        level = data.get("level", "info").upper()

        if level == "ERROR":
            logger.error(f"Actor {actor.id if actor else 'unknown'}: {message}")
        elif level == "WARNING":
            logger.warning(f"Actor {actor.id if actor else 'unknown'}: {message}")
        else:
            logger.info(f"Actor {actor.id if actor else 'unknown'}: {message}")

        return {
            "status": "logged",
            "message": message,
            "level": level,
            "timestamp": datetime.now().isoformat(),
        }

    @app.action_hook(
        "send_notification",
        description="Simulate sending a notification via email, SMS, or push (no actual notification sent).",
        input_schema={
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Notification recipient (email, phone number, or device ID)",
                },
                "message": {
                    "type": "string",
                    "description": "Notification message content",
                },
                "type": {
                    "type": "string",
                    "enum": ["email", "sms", "push"],
                    "description": "Notification type",
                    "default": "email",
                },
            },
            "required": ["recipient", "message"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["sent", "failed"],
                    "description": "Delivery status",
                },
                "recipient": {
                    "type": "string",
                    "description": "Notification recipient",
                },
                "message": {"type": "string", "description": "Notification message"},
                "type": {"type": "string", "description": "Notification type used"},
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the notification was sent",
                },
            },
            "required": ["status", "recipient", "message", "type", "timestamp"],
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def handle_send_notification_action(
        actor: ActorInterface, action_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Simulate sending a notification (email, SMS, or push).

        Endpoint: POST /{actor_id}/actions/send_notification

        Parameters:
            recipient (str): Notification recipient (required for success)
            message (str): Notification message (required for success)
            type (str): Notification type - "email", "sms", or "push" (default: "email")

        Returns:
            {status, recipient, message, type, timestamp}

        Note: This is a simulation - no actual notification is sent.
        """
        recipient = data.get("recipient", "")
        message = data.get("message", "")
        notification_type = data.get("type", "email")

        # Simulate sending notification
        success = bool(recipient and message)

        # Log the notification
        logger.info(
            f"Sending {notification_type} notification to {recipient}: {message}"
        )

        return {
            "status": "sent" if success else "failed",
            "recipient": recipient,
            "message": message,
            "type": notification_type,
            "timestamp": datetime.now().isoformat(),
        }
