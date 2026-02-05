================
Hooks Reference
================

This page summarizes hook types, signatures, and behaviors exposed by the modern interface. Prefer the decorators on ``ActingWebApp`` (``app.property_hook(...)`` etc.).

Overview
========

Hook execution applies unified access control when enabled. For property hooks, returning ``None`` during write operations (PUT/POST/DELETE) rejects the change; returning ``None`` during GET hides the value from the caller and from the web UI.

Property Hooks
==============

Decorator: ``app.property_hook(name: str = "*")``

Signature: ``func(actor, operation: str, value: Any, path: List[str]) -> Optional[Any]``

- ``operation``: ``get|put|post|delete``
- ``path``: Subkeys for nested access (e.g., ``["settings", "theme"]``)
- Return new value to allow/transform, or ``None`` to hide/deny
- Matching: exact name first, then wildcard ``"*"`` handlers

Example:

.. code-block:: python

    @app.property_hook("email")
    def email_guard(actor, operation, value, path):
        if operation in ("put", "post", "delete"):
            return None  # read-only
        return value if actor.is_owner() else None  # hide from non-owner

Callback Hooks
==============

Decorator: ``app.callback_hook(name: str = "*")``

Signature: ``func(actor, name: str, data: dict) -> bool | dict``

- Return ``True`` when processed; optionally return a ``dict`` as response payload
- Used for custom endpoints registered by the framework (e.g., ``bot``, ``www``)

Template Rendering for WWW Hooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The special ``www`` callback hook can render custom templates by returning a dict with ``template`` key:

.. code-block:: python

    @app.callback_hook("www")
    def handle_www_paths(actor, name, data):
        path = data.get("path", "")

        if path == "custom":
            return {
                "template": "aw-actor-www-custom.html",
                "data": {
                    "custom_message": "Hello from hook!",
                },
            }

        return False  # Fall through to default handling

The template will receive:

- Standard values: ``id``, ``url``, ``actor_root``, ``actor_www``
- Custom data from the ``data`` dict in the return value

This allows applications to add custom web UI pages without modifying the core library.

Application Callback Hooks
==========================

Decorator: ``app.app_callback_hook(name: str)``

Signature: ``func(data: dict) -> bool | dict``

- Like callback hooks but without actor context (application-level)

Subscription Hooks
==================

Decorator: ``app.subscription_hook``

Signature: ``func(actor, subscription: dict, peer_id: str, data: dict) -> bool``

- Return ``True`` when the subscription callback was handled

Lifecycle Hooks
================

Decorator: ``app.lifecycle_hook(event: str)``

Signature: ``func(actor, **kwargs) -> Any``

- Common events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_initiated``, ``trust_request_received``, ``trust_fully_approved_local``, ``trust_fully_approved_remote``, ``trust_deleted``, ``subscription_deleted``, ``email_verification_required``, ``email_verified``

Event Details
~~~~~~~~~~~~~

``actor_created``
    Triggered when a new actor is created.

    **Signature**: ``func(actor: ActorInterface) -> None``

``actor_deleted``
    Triggered when an actor is deleted.

    **Signature**: ``func(actor: ActorInterface) -> None``

``oauth_success``
    Triggered after successful OAuth2 authentication.

    **Signature**: ``func(actor: ActorInterface, email: str, access_token: str, token_data: dict) -> Optional[bool]``

    **Returns**: ``False`` to reject authentication, ``True`` or ``None`` to accept

``trust_initiated``
    Triggered when this actor initiates a trust request to another actor (outgoing request).

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor (initiator)
    - ``peer_id``: The ID of the peer being invited
    - ``relationship``: The type of trust relationship requested (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the trust relationship data

    **Use Cases**: Logging, analytics, UI updates showing "request sent"

``trust_request_received``
    Triggered when this actor receives a trust request from another actor (incoming request).

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor (recipient)
    - ``peer_id``: The ID of the peer who sent the request
    - ``relationship``: The type of trust relationship requested (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the trust relationship data

    **Use Cases**: Real-time notifications, UI popups, approval workflows

``trust_fully_approved_local``
    Triggered when THIS actor approves a trust relationship, completing mutual approval (both sides now approved).

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor (who just approved)
    - ``peer_id``: The ID of the peer in the trust relationship
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the full trust relationship data

    **Use Cases**: UI notification "You approved! Relationship established", analytics, triggering subscriptions

    **Note**: Fires when this actor's approval completes the mutual trust (peer had already approved).

    **Built-in Behavior**: If peer profile caching is enabled (``with_peer_profile()``), the peer's profile is automatically fetched and cached when this hook fires.

``trust_fully_approved_remote``
    Triggered when the PEER actor approves a trust relationship, completing mutual approval (both sides now approved).

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor (receiving notification)
    - ``peer_id``: The ID of the peer who just approved
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the full trust relationship data

    **Use Cases**: UI notification "They approved your request!", analytics, triggering subscriptions

    **Note**: Fires when the peer's approval completes the mutual trust (this actor had already approved).

    **Built-in Behavior**: If peer profile caching is enabled (``with_peer_profile()``), the peer's profile is automatically fetched and cached when this hook fires.

``trust_deleted``
    Triggered when a trust relationship is deleted.

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor
    - ``peer_id``: The ID of the peer in the trust relationship
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the trust relationship data (may be empty if trust was already deleted)

    **Built-in Behavior**: If peer profile caching is enabled (``with_peer_profile()``), the cached peer profile is automatically deleted when this hook fires.

``subscription_deleted``
    Triggered when a subscription is deleted (inbound subscriptions only).

    **Signature**: ``func(actor: ActorInterface, peer_id: str, subscription_id: str, subscription_data: dict, initiated_by_peer: bool) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor
    - ``peer_id``: The ID of the peer in the subscription
    - ``subscription_id``: The ID of the subscription that was deleted
    - ``subscription_data``: Dictionary containing the subscription data (may be empty if subscription was already deleted)
    - ``initiated_by_peer``: ``True`` if the peer initiated the deletion (unsubscribed from us), ``False`` if we revoked their subscription

    **Use Cases**: Revoke peer permissions, clean up cached data, send notifications when peers unsubscribe

    **Note**: Only triggered for inbound subscriptions (where peer subscribes to us) to prevent duplicate cleanup. Outbound subscription deletions (us unsubscribing from peer) do not trigger this hook.

    **Example**:

    .. code-block:: python

        @app.lifecycle_hook("subscription_deleted")
        def on_subscription_deleted(actor, peer_id, subscription_id, subscription_data, initiated_by_peer):
            if initiated_by_peer:
                # Peer unsubscribed from us - revoke their permissions
                actor.trust.update_permissions(peer_id, [])
                notify_user(actor, f"{peer_id} unsubscribed from your data")

``email_verification_required``
    Triggered when email verification is needed for OAuth2 actors.

    **Signature**: ``func(actor: ActorInterface, email: str, verification_url: str, token: str) -> None``

    **Purpose**: Send verification email to user

    **Required**: Must be implemented when using ``with_email_as_creator(enable=True)``

    **Example**:

    .. code-block:: python

        @app.lifecycle_hook("email_verification_required")
        def send_verification_email(actor, email, verification_url, token):
            # Send email with verification_url to the user
            send_email(
                to=email,
                subject="Verify your email",
                body=f"Click here to verify: {verification_url}"
            )

``email_verified``
    Triggered when email verification is successfully completed.

    **Signature**: ``func(actor: ActorInterface, email: str) -> None``

    **Purpose**: Handle post-verification actions (welcome email, grant access, etc.)

    **Optional**: Not required, but useful for tracking and analytics

    **Example**:

    .. code-block:: python

        @app.lifecycle_hook("email_verified")
        def handle_verification(actor, email):
            logger.info(f"Email verified: {email} for actor {actor.id}")
            # Optional: Send welcome email, enable features, etc.

Method Hooks
============

Decorator: ``app.method_hook(name, description="", input_schema=None, output_schema=None, annotations=None)``

Signature: ``func(actor, method_name: str, data: dict) -> Any``

- Implements RPC-style methods under ``/methods``; first non-None return wins
- Metadata is exposed via ``GET /<actor_id>/methods`` for API discovery

**Metadata Parameters**:

- ``description``: Human-readable description of what the method does
- ``input_schema``: JSON schema describing expected input parameters
- ``output_schema``: JSON schema describing the expected return value
- ``annotations``: Safety/behavior hints (e.g., ``readOnlyHint``, ``idempotentHint``)

**Example with Metadata**:

.. code-block:: python

    @app.method_hook(
        "calculate",
        description="Perform a mathematical calculation",
        input_schema={
            "type": "object",
            "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            "required": ["x", "y"]
        },
        output_schema={"type": "object", "properties": {"result": {"type": "number"}}},
        annotations={"readOnlyHint": True, "idempotentHint": True}
    )
    def handle_calculate(actor, method_name, data):
        return {"result": data["x"] + data["y"]}

**Auto-Generated Schemas from TypedDict**:

If you don't provide ``input_schema`` or ``output_schema`` explicitly, they can be
auto-generated from TypedDict type hints on your function:

.. code-block:: python

    from typing import TypedDict

    class CalculateInput(TypedDict):
        x: int
        y: int

    class CalculateOutput(TypedDict):
        result: int

    @app.method_hook("calculate", description="Add two numbers")
    def handle_calculate(actor, method_name, data: CalculateInput) -> CalculateOutput:
        return {"result": data["x"] + data["y"]}

The above automatically generates:

- ``input_schema`` from the ``data`` parameter's TypedDict annotation
- ``output_schema`` from the return type annotation

Explicit schemas always take precedence over auto-generated ones. Supported types
include ``str``, ``int``, ``float``, ``bool``, ``list``, ``dict``, ``None``,
``Optional[...]``, and nested TypedDict classes.

Action Hooks
============

Decorator: ``app.action_hook(name, description="", input_schema=None, output_schema=None, annotations=None)``

Signature: ``func(actor, action_name: str, data: dict) -> Any``

- Implements side-effecting operations under ``/actions``; first non-None return wins
- Metadata is exposed via ``GET /<actor_id>/actions`` for API discovery

**Metadata Parameters**:

- ``description``: Human-readable description of what the action does
- ``input_schema``: JSON schema describing expected input parameters
- ``output_schema``: JSON schema describing the expected return value
- ``annotations``: Safety/behavior hints (e.g., ``destructiveHint``, ``readOnlyHint``)

**Example with Metadata**:

.. code-block:: python

    @app.action_hook(
        "delete_record",
        description="Permanently delete a record from the database",
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"]
        },
        annotations={"destructiveHint": True, "readOnlyHint": False}
    )
    def handle_delete(actor, action_name, data):
        delete_from_database(data["record_id"])
        return {"status": "deleted"}

**Auto-Generated Schemas from TypedDict**:

Action hooks also support auto-schema generation from TypedDict type hints:

.. code-block:: python

    from typing import TypedDict

    class DeleteInput(TypedDict):
        record_id: str

    class DeleteOutput(TypedDict):
        status: str

    @app.action_hook("delete_record", description="Delete a record")
    def handle_delete(actor, action_name, data: DeleteInput) -> DeleteOutput:
        delete_from_database(data["record_id"])
        return {"status": "deleted"}

Async/Await Support
===================

**New in v3.9.0**: All ActingWeb hooks now support native async/await syntax. This enables efficient handling of I/O-bound operations without blocking the event loop in async frameworks like FastAPI.

When to Use Async Hooks
~~~~~~~~~~~~~~~~~~~~~~~

Use ``async def`` for hooks that need to call async services:

- **Async HTTP clients** (aiohttp, httpx)
- **Async database operations** (asyncpg, motor)
- **Async AWS services** (aioboto3, async AWS Bedrock)
- **Async AwProxy methods** (``send_message_async()``, ``fetch_property_async()``)
- **Any async I/O operations**

Performance Benefits
~~~~~~~~~~~~~~~~~~~~

**FastAPI**: Async hooks execute natively without thread pool overhead, allowing true concurrent execution.

**Flask**: Async hooks are executed via ``asyncio.run()``, providing compatibility with async libraries.

Async Method Hooks
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import aiohttp

    @app.method_hook("fetch_data")
    async def async_fetch(actor, method_name, data):
        """Async method hook using aiohttp."""
        async with aiohttp.ClientSession() as session:
            async with session.get(data["url"]) as response:
                content = await response.text()
        return {"content": content, "status": response.status}

Async Action Hooks
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from actingweb.interface import AwProxy

    @app.action_hook("send_notification")
    async def async_notify(actor, action_name, data):
        """Async action hook using AwProxy."""
        proxy = AwProxy(config)

        # Use async methods for peer communication
        result = await proxy.send_message_async(
            peer_url=data["peer_url"],
            message=data["message"],
            secret=actor.get_trust_secret(data["peer_id"])
        )

        return {"sent": result is not None}

Async Property Hooks
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import asyncpg

    @app.property_hook("user_profile")
    async def async_property(actor, operation, value, path):
        """Async property hook with database access."""
        if operation == "get":
            # Fetch from async database
            conn = await asyncpg.connect("postgresql://...")
            profile = await conn.fetchrow(
                "SELECT * FROM profiles WHERE actor_id = $1",
                actor.id
            )
            await conn.close()
            return dict(profile) if profile else None

        return value

Async Lifecycle Hooks
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @app.lifecycle_hook("actor_created")
    async def async_onCreate(actor, **kwargs):
        """Async lifecycle hook for actor creation."""
        # Initialize with async service
        async with aiohttp.ClientSession() as session:
            await session.post(
                "https://analytics.example.com/events",
                json={"event": "actor_created", "actor_id": actor.id}
            )

Mixed Sync and Async Hooks
~~~~~~~~~~~~~~~~~~~~~~~~~~

You can use both synchronous and asynchronous hooks in the same application:

.. code-block:: python

    @app.method_hook("quick_calc")
    def sync_method(actor, method_name, data):
        """Synchronous CPU-bound operation."""
        return {"result": data["x"] + data["y"]}

    @app.method_hook("fetch_data")
    async def async_method(actor, method_name, data):
        """Asynchronous I/O-bound operation."""
        async with aiohttp.ClientSession() as session:
            async with session.get(data["url"]) as resp:
                return {"data": await resp.text()}

The framework automatically detects whether a hook is sync or async and handles execution appropriately.

Framework-Specific Behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**FastAPI**:
  - Async hooks are executed natively without thread pool
  - Optimal for concurrent request handling
  - Uses ``AsyncMethodsHandler`` and ``AsyncActionsHandler`` automatically

**Flask**:
  - Async hooks are executed via ``asyncio.run()``
  - Compatible with async libraries but not truly concurrent
  - Falls back to standard ``MethodsHandler`` and ``ActionsHandler``

Best Practices
~~~~~~~~~~~~~~

1. **Use async for I/O**: Network requests, database queries, file operations
2. **Use sync for CPU**: Calculations, data transformations, quick operations
3. **Don't mix unnecessarily**: If all operations are sync, keep hooks sync
4. **Test both paths**: Ensure hooks work in both FastAPI and Flask contexts

Backward Compatibility
~~~~~~~~~~~~~~~~~~~~~~

All existing synchronous hooks continue to work without changes. The async support is opt-in via ``async def`` syntax.

API Discovery
=============

The ``GET /<actor_id>/methods`` and ``GET /<actor_id>/actions`` endpoints return
metadata for all registered hooks, enabling API discovery:

.. code-block:: text

    {
      "methods": [
        {
          "name": "calculate",
          "description": "Perform a mathematical calculation",
          "input_schema": {"type": "object", "properties": {...}},
          "output_schema": {"type": "object", "properties": {...}},
          "annotations": {"readOnlyHint": true}
        }
      ]
    }

Hooks without metadata return default values (empty description, null schemas).

Matching & Ordering
===================

- Specific-name hooks execute before wildcard hooks
- For methods/actions, the first hook returning a non-None value wins
- For properties, hooks can transform the value; ``None`` hides/denies

Path Semantics (Properties)
===========================

- ``path`` conveys nested segments. Example: GET ``/properties/settings/theme`` → ``path=["settings", "theme"]``
- Use path to enforce fine-grained access or type normalization

