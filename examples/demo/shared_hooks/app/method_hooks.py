"""
Shared method hooks for ActingWeb demo applications.

Method hooks handle RPC-style function calls that are read-only operations.
Unlike actions, methods should NOT modify state - they compute and return results.

Methods are invoked via: POST /{actor_id}/methods/{method_name}
with JSON body containing the method parameters.

Available Methods:
- calculate: Perform arithmetic operations (add/subtract/multiply/divide)
- greet: Return a personalized greeting with actor info
- get_status: Return comprehensive actor status summary
- echo: Echo back input data (useful for testing)
- search: Search actor properties by keyword
- schedule_task: Schedule a task for the robot to execute at a specific time

Example usage with curl:
    curl -X POST https://host/{actor_id}/methods/calculate \\
         -H "Content-Type: application/json" \\
         -d '{"a": 10, "b": 5, "operation": "multiply"}'

    curl -X POST https://host/{actor_id}/methods/greet \\
         -H "Content-Type: application/json" \\
         -d '{"name": "Alice"}'

    curl -X POST https://host/{actor_id}/methods/search \\
         -H "Content-Type: application/json" \\
         -d '{"query": "*", "limit": 10}'
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Properties to exclude from search results (sensitive data)
SEARCH_EXCLUDED_PROPERTIES = [
    "email",
    "auth_token",
    "oauth_token",
    "access_token",
    "refresh_token",
]


def register_method_hooks(app):
    """Register all method hooks with the ActingWeb application."""

    @app.method_hook(
        "calculate",
        description="Perform arithmetic operations (add, subtract, multiply, divide) on two numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "a": {
                    "type": "number",
                    "description": "First operand",
                    "default": 0,
                },
                "b": {
                    "type": "number",
                    "description": "Second operand",
                    "default": 0,
                },
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "Arithmetic operation to perform",
                    "default": "add",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "number", "description": "Calculation result"},
                "operation": {"type": "string", "description": "Operation performed"},
                "a": {"type": "number", "description": "First operand used"},
                "b": {"type": "number", "description": "Second operand used"},
                "error": {
                    "type": "string",
                    "description": "Error message if operation failed",
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_calculate_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Perform arithmetic operations.

        Endpoint: POST /{actor_id}/methods/calculate

        Parameters:
            a (number): First operand (default: 0)
            b (number): Second operand (default: 0)
            operation (str): Operation - "add", "subtract", "multiply", "divide" (default: "add")

        Returns:
            {result, operation} on success
            None on error (division by zero, unsupported operation)

        Example:
            {"a": 10, "b": 5, "operation": "multiply"} -> {"result": 50, "operation": "multiply"}
        """
        try:
            a = data.get("a", 0)
            b = data.get("b", 0)
            operation = data.get("operation", "add")

            if operation == "add":
                result = a + b
            elif operation == "subtract":
                result = a - b
            elif operation == "multiply":
                result = a * b
            elif operation == "divide":
                if b == 0:
                    return {"error": "Division by zero", "operation": operation}
                result = a / b
            else:
                return {
                    "error": f"Unsupported operation: {operation}",
                    "operation": operation,
                }

            return {"result": result, "operation": operation, "a": a, "b": b}
        except (TypeError, ValueError) as e:
            return {"error": str(e)}

    @app.method_hook(
        "greet",
        description="Return a personalized greeting message with actor information.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet",
                    "default": "World",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "greeting": {
                    "type": "string",
                    "description": "The personalized greeting message",
                },
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the greeting was generated",
                },
                "integration": {
                    "type": "string",
                    "description": "Framework integration type",
                },
                "actor_id": {
                    "type": "string",
                    "description": "ID of the actor generating the greeting",
                },
            },
            "required": ["greeting", "timestamp", "integration", "actor_id"],
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_greet_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Return a personalized greeting with actor information.

        Endpoint: POST /{actor_id}/methods/greet

        Parameters:
            name (str): Name to greet (default: "World")

        Returns:
            {greeting, timestamp, integration}

        Example:
            {"name": "Alice"} -> {"greeting": "Hello, Alice! This is actor abc123 via Flask.", ...}
        """
        name = data.get("name", "World")
        actor_id = actor.id if actor else "unknown"

        # Determine which framework is being used based on app context
        integration = "Flask"  # Default for this demo

        return {
            "greeting": f"Hello, {name}! This is actor {actor_id} via {integration}.",
            "timestamp": datetime.now().isoformat(),
            "integration": integration,
            "actor_id": actor_id,
        }

    @app.method_hook(
        "get_status",
        description="Return comprehensive actor status summary including property counts and relationship statistics.",
        input_schema={
            "type": "object",
            "properties": {},
            "description": "No parameters required",
        },
        output_schema={
            "type": "object",
            "properties": {
                "actor_id": {"type": "string", "description": "Actor identifier"},
                "creator": {"type": "string", "description": "Creator of the actor"},
                "status": {"type": "string", "description": "Current actor status"},
                "properties_count": {
                    "type": "integer",
                    "description": "Number of properties stored",
                },
                "trust_relationships": {
                    "type": "integer",
                    "description": "Number of trust relationships",
                },
                "subscriptions": {
                    "type": "integer",
                    "description": "Number of active subscriptions",
                },
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the status was retrieved",
                },
                "error": {
                    "type": "string",
                    "description": "Error message if actor not found",
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_get_status_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Return comprehensive actor status summary.

        Endpoint: POST /{actor_id}/methods/get_status

        Parameters:
            None required

        Returns:
            {actor_id, creator, status, properties_count, trust_relationships, subscriptions}

        This method provides a quick overview of the actor's current state
        including property counts and relationship statistics.
        """
        if not actor:
            return {"error": "Actor not found"}

        return {
            "actor_id": actor.id,
            "creator": actor.creator,
            "status": "active",
            "properties_count": len(actor.properties.to_dict())
            if actor.properties is not None
            else 0,
            "trust_relationships": len(actor.trust.relationships),
            "subscriptions": len(actor.subscriptions.all_subscriptions),
            "timestamp": datetime.now().isoformat(),
        }

    @app.method_hook(
        "echo",
        description="Echo back the input data unchanged (useful for testing connectivity and serialization).",
        input_schema={
            "type": "object",
            "additionalProperties": True,
            "description": "Any JSON data to echo back",
        },
        output_schema={
            "type": "object",
            "properties": {
                "echo": {"description": "The input data echoed back unchanged"},
                "actor_id": {"type": "string", "description": "ID of the actor"},
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the echo was generated",
                },
            },
            "required": ["echo", "actor_id", "timestamp"],
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_echo_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Echo back the input data (useful for testing).

        Endpoint: POST /{actor_id}/methods/echo

        Parameters:
            Any JSON data

        Returns:
            {echo: <input_data>, actor_id, timestamp}
        """
        return {
            "echo": data,
            "actor_id": actor.id if actor else "unknown",
            "timestamp": datetime.now().isoformat(),
        }

    @app.method_hook(
        "search",
        description=(
            "Search across this actor's properties by keyword. "
            "Returns matching property names and values. "
            "Use '*' to list all properties. "
            "Sensitive properties like tokens and email are excluded from results."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - matches against property names and values. Use '*' to list all.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20)",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query used"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "property": {
                                "type": "string",
                                "description": "Property name",
                            },
                            "value": {"description": "Property value"},
                            "match_type": {
                                "type": "string",
                                "enum": ["name", "value", "all"],
                                "description": "How the match was found",
                            },
                        },
                    },
                    "description": "Matching properties",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results returned",
                },
                "truncated": {
                    "type": "boolean",
                    "description": "Whether results were truncated due to limit",
                },
                "error": {
                    "type": "string",
                    "description": "Error message if search failed",
                },
            },
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def handle_search_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Search across actor properties by keyword.

        Endpoint: POST /{actor_id}/methods/search

        Parameters:
            query (str): Search query - use '*' to list all properties
            limit (int): Maximum results to return (default: 20)

        Returns:
            {query, results: [{property, value, match_type}], count, truncated}

        Note: Sensitive properties (email, tokens) are automatically excluded.
        """
        query = data.get("query", "").strip().lower()
        limit = data.get("limit", 20)

        if not query:
            return {"error": "Query parameter is required", "results": []}

        # Treat '*' as "list all"
        list_all = query == "*"

        logger.info(
            f"Search for actor {actor.id}: query='{query}', limit={limit}, list_all={list_all}"
        )

        results: list[dict[str, Any]] = []

        try:
            # Get all properties using to_dict()
            all_props = (
                actor.properties.to_dict() if actor.properties is not None else {}
            )

            if all_props is None:
                all_props = {}

            for prop_name, prop_value in all_props.items():
                # Skip excluded/sensitive properties
                if prop_name in SEARCH_EXCLUDED_PROPERTIES:
                    continue
                if prop_name.startswith("_"):  # Skip internal properties
                    continue

                # Convert value to string for searching
                value_str = str(prop_value) if prop_value is not None else ""

                # Match all if '*', otherwise check if query matches property name or value
                if list_all or query in prop_name.lower() or query in value_str.lower():
                    results.append(
                        {
                            "property": prop_name,
                            "value": prop_value,
                            "match_type": "all"
                            if list_all
                            else ("name" if query in prop_name.lower() else "value"),
                        }
                    )

                    if len(results) >= limit:
                        break

            logger.info(f"Search found {len(results)} results for '{query}'")

            return {
                "query": query,
                "results": results,
                "count": len(results),
                "truncated": len(results) >= limit,
            }

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"error": f"Search failed: {str(e)}", "results": []}

    # 1X NEO Robot Task Scheduling

    @app.method_hook(
        "schedule_task",
        description="Schedule a task for the 1X NEO humanoid robot to execute at a specific time.",
        input_schema={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Human-readable description of the task for reference purposes.",
                },
                "instructions": {
                    "type": "string",
                    "description": "Detailed instructions for what the robot should do when the task executes.",
                },
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "ISO 8601 timestamp for when the task should be executed.",
                },
                "context": {
                    "type": "string",
                    "description": "Any relevant information, materials, or context needed to execute the instructions.",
                },
            },
            "required": ["description", "instructions", "timestamp"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "reference_id": {
                    "type": "string",
                    "description": "Unique identifier for the scheduled task.",
                },
                "status": {
                    "type": "string",
                    "enum": ["scheduled", "error"],
                    "description": "Status of the scheduling request.",
                },
                "message": {
                    "type": "string",
                    "description": "Human-readable status message.",
                },
                "scheduled_for": {
                    "type": "string",
                    "format": "date-time",
                    "description": "The timestamp when the task will execute.",
                },
                "error": {
                    "type": "string",
                    "description": "Error message if scheduling failed.",
                },
            },
            "required": ["reference_id", "status", "message"],
        },
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def handle_schedule_task_method(
        actor: ActorInterface, method_name: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Schedule a task for the 1X NEO humanoid robot.

        Endpoint: POST /{actor_id}/methods/schedule_task

        This method allows you to schedule tasks for the robot to execute
        at a specific time. The robot will use the provided instructions
        and context to perform the task.

        Parameters:
            description (str): Human-readable task description (required)
            instructions (str): What the robot should do (required)
            timestamp (str): ISO 8601 datetime for execution (required)
            context (str): Additional information for the task (optional)

        Returns:
            {reference_id, status, message, scheduled_for}

        Example:
            {
                "description": "Morning coffee preparation",
                "instructions": "Go to the kitchen, prepare a cup of coffee using the espresso machine, and bring it to the home office.",
                "timestamp": "2024-01-15T07:30:00Z",
                "context": "User prefers a double espresso with no sugar. Coffee beans are in the left cabinet."
            }
        """
        description = data.get("description", "")
        instructions = data.get("instructions", "")
        timestamp_str = data.get("timestamp", "")
        context = data.get("context", "")

        # Validate required fields
        if not description:
            return {
                "reference_id": "",
                "status": "error",
                "message": "Task description is required.",
                "error": "Missing required field: description",
            }

        if not instructions:
            return {
                "reference_id": "",
                "status": "error",
                "message": "Task instructions are required.",
                "error": "Missing required field: instructions",
            }

        if not timestamp_str:
            return {
                "reference_id": "",
                "status": "error",
                "message": "Execution timestamp is required.",
                "error": "Missing required field: timestamp",
            }

        # Validate timestamp format
        try:
            _ = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError as e:
            return {
                "reference_id": "",
                "status": "error",
                "message": "Invalid timestamp format. Please use ISO 8601 format.",
                "error": f"Timestamp parsing error: {str(e)}",
            }

        # Generate unique reference ID
        reference_id = f"task-{uuid.uuid4().hex[:12]}"

        # Store the scheduled task in actor properties
        if actor.properties is not None:
            scheduled_tasks = actor.properties.get("scheduled_tasks", [])
            if not isinstance(scheduled_tasks, list):
                scheduled_tasks = []

            scheduled_tasks.append(
                {
                    "reference_id": reference_id,
                    "description": description,
                    "instructions": instructions,
                    "timestamp": timestamp_str,
                    "context": context,
                    "created_at": datetime.now().isoformat(),
                    "status": "pending",
                }
            )

            actor.properties.scheduled_tasks = scheduled_tasks

        logger.info(
            f"Scheduled task {reference_id} for actor {actor.id}: "
            f"'{description}' at {timestamp_str}"
        )

        return {
            "reference_id": reference_id,
            "status": "scheduled",
            "message": f"Task '{description}' has been scheduled successfully.",
            "scheduled_for": timestamp_str,
        }
