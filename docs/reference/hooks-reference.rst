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

- Common events: ``actor_created``, ``actor_deleted``, ``oauth_success``, ``trust_approved``, ``trust_deleted``, ``email_verification_required``, ``email_verified``

Event Details
-------------

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

``trust_approved``
    Triggered when a trust relationship is approved.

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor
    - ``peer_id``: The ID of the peer in the trust relationship
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the full trust relationship data

``trust_deleted``
    Triggered when a trust relationship is deleted.

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor
    - ``peer_id``: The ID of the peer in the trust relationship
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: Dictionary containing the trust relationship data (may be empty if trust was already deleted)

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

Decorator: ``app.method_hook(name: str = "*")``

Signature: ``func(actor, method_name: str, data: dict) -> Any``

- Implements RPC-style methods under ``/methods``; first non-None return wins

Action Hooks
============

Decorator: ``app.action_hook(name: str = "*")``

Signature: ``func(actor, action_name: str, data: dict) -> Any``

- Implements side-effecting operations under ``/actions``; first non-None return wins

Matching & Ordering
===================

- Specific-name hooks execute before wildcard hooks
- For methods/actions, the first hook returning a non-None value wins
- For properties, hooks can transform the value; ``None`` hides/denies

Path Semantics (Properties)
===========================

- ``path`` conveys nested segments. Example: GET ``/properties/settings/theme`` → ``path=["settings", "theme"]``
- Use path to enforce fine-grained access or type normalization

