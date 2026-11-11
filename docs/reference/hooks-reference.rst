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
        return value  # allow reads / transform here

.. warning::

   Property hooks fire for **every** access to the property, regardless of who
   is making the request — they cannot by themselves distinguish the owner from
   a peer or an OAuth2/MCP client. Do **not** use ``actor.is_owner()`` as an
   access guard: it is a placeholder that currently always returns ``True``. To
   restrict what a peer or client may read or write, use the permission system
   and the permission-enforcing authenticated views (:doc:`../sdk/authenticated-views`,
   ``actor.as_peer()`` / ``actor.as_client()``), which evaluate per-accessor
   permissions before the property hook runs.

Callback Hooks
==============

Decorator: ``app.callback_hook(name: str = "*")``

Signature: ``func(actor, name: str, data: dict) -> bool | dict``

- Return ``True`` when processed; optionally return a ``dict`` as response payload
- Used for custom endpoints registered by the framework (e.g., ``bot``, ``www``)
- ``/callbacks/<name>`` requests are authenticated (3.16): without
  credentials they answer 401, and any authenticated caller reaches the
  hook. The library's own names (``permissions``, ``subscription``,
  ``subscriptions``, ``www`` and any ``resource_*``) answer 403 on a direct
  ``/callbacks/<name>`` request, so their hooks only receive data the
  library built (the web UI still dispatches ``www``)

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
- Fires only on the **legacy fallback path**: when
  ``.with_subscription_processing()`` has not been called, or was called with
  ``auto_sequence=False``. If auto-sequencing is enabled, use
  ``app.subscription_data_hook`` instead — see below.

Subscription Data Hooks
========================

Decorator: ``app.subscription_data_hook(target: str = "*")``

Signature: ``func(actor, peer_id: str, target: str, data: dict, sequence: int, callback_type: str) -> None``

- Requires ``.with_subscription_processing()`` (``auto_sequence=True``, the
  default). The library handles sequencing, gap detection, deduplication and
  storage before invoking this hook, so ``data`` has already been validated
  and ordered.
- ``target``: matches the ``target`` argument, or ``"*"`` to receive every
  target
- See :doc:`../guides/subscriptions` for the full auto-processing
  configuration.

Lifecycle Hooks
================

Decorator: ``app.lifecycle_hook(event: str)``

Signature: ``func(actor, **kwargs) -> Any``

- Common events: ``actor_created``, ``actor_deleted``, ``actor_deleted_complete``, ``actor_adopted``, ``oauth_success``, ``trust_initiated``, ``trust_request_received``, ``trust_fully_approved_local``, ``trust_fully_approved_remote``, ``trust_deleted``, ``subscription_deleted``, ``email_verification_required``, ``email_sign_in_code_required``, ``email_verified``

Event Details
~~~~~~~~~~~~~

``actor_created``
    Triggered when a new actor is created. Fires exactly once, from inside
    ``Actor.create()`` itself, before an OAuth handler stores tokens or
    provider metadata on the actor — so at hook time, fields like
    ``oauth_token``, ``oauth_provider``, ``created_at``, ``email`` and
    ``email_verified`` are **not yet set**. ``auth_method`` is the exception
    (3.16): ``Actor.create()`` writes it before the hook fires, so the hook can
    tell a factory-created actor from an OAuth one. ``oauth_success`` (below)
    is the hook that carries the tokens and provider info.

    The OAuth path writes ``created_at``, ``oauth_provider`` and ``email``
    after the hook. If one of those writes faults, the actor exists, vouched
    and announced, without them; the next sign-in writes a missing
    ``email`` (the creator when it is an address, else the provider's) and
    does not fire ``actor_created`` again. When a sign-in replaces a
    ``factory`` actor with ``with_unique_creator()`` on (the default), the
    successor's ``actor_created`` fires before the squatter's
    ``actor_deleted``; with it off, the squatter is removed first.

    **Signature**: ``func(actor: ActorInterface) -> None``

    .. note::

       Before 3.14.5, every OAuth-created actor fired ``actor_created``
       twice — once from a handler-level call after tokens/metadata were
       stored, once from inside ``Actor.create()``. The single remaining
       call is the earlier (pre-metadata) one; a hook that read those
       fields (other than ``auth_method``, which has been written since
       3.16) on the second call now sees them absent.

``actor_deleted``
    Triggered when an actor is deleted, **before any data is removed**. The
    actor is still fully readable, so this is where to *read* whatever external
    cleanup will need.

    **Signature**: ``func(actor: ActorInterface, **kwargs) -> None``

    Accept ``**kwargs``: the library passes keyword arguments on some
    deletions (below), and a hook that does not accept them raises
    ``TypeError``, which is logged and skipped, so its cleanup never runs.

    .. warning::

       Do not make external API calls here. The actor keeps resolving for the
       whole of the wipe, so a provider callback triggered from this hook lands
       while the actor still appears live and writes rows that outlive it. Act
       in ``actor_deleted_complete`` instead. See
       :doc:`actor-deletion`.

    Also fires (3.16) when a sign-in **replaces** an unvouched,
    factory-created actor (see ``actor_adopted``), with the keyword arguments
    ``reason="replaced_at_adoption"`` and ``replaced_by_identifier=<creator>``,
    so a hook that mails "your account was deleted" or cancels billing can tell
    it apart from a user-initiated delete. A deletion that stops part-way is
    resumed (see `Faults and hooks`_): this hook runs at least once per
    registered hook, and again only when one of them raised ``DbError``, so
    write it to be idempotent.

``actor_adopted``
    Triggered once per adoption, on the **surviving** actor, after a sign-in
    that proved the creator address (a provider login or the emailed
    verification link) replaced or cleaned an actor nobody vouched for. May
    fire more than once for one actor: two concurrent first sign-ins both run
    the rule.

    **Signature**: ``func(actor: ActorInterface, previous_auth_method: str,
    previous_actor_id: str | None, provider: str | None, mode: str,
    removed_trusts: list[dict], removed_subscription_peers: list[str],
    tokens_revoked: int, removed_client_ids: list[str],
    property_names: list[str], removed_sibling_ids: list[str]) -> None``

    - ``previous_auth_method``: the marker the actor had, ``"legacy"`` when it
      had none.
    - ``previous_actor_id``: the replaced actor's id, ``None`` when it was
      cleaned in place.
    - ``provider``: the provider's base name (``google-mobile`` reports
      ``google``), ``None`` for the emailed verification link.
    - ``mode``: ``"replaced"`` or ``"cleaned"``.
    - ``removed_trusts``: ``peerid``, ``relationship``, ``approved`` and
      ``established_via`` of each removed trust; **never** the ``secret``.
      ``None`` (unknown, not "none") when the lists could not be read, as are
      ``removed_subscription_peers``, ``tokens_revoked`` and
      ``property_names`` then; the adoption itself went through.
    - ``removed_client_ids``: the OAuth2 clients registered under the actor,
      deleted with it.
    - ``property_names``: the properties that survive a clean-in-place, so the
      application can inspect what a squatter may have prefilled; empty for a
      replacement.
    - ``removed_sibling_ids``: the ``factory`` actors with the same creator
      that the sign-in deleted (each also fired ``actor_deleted``). For a
      clean-in-place it is empty, unless the sign-in first resolved to a
      factory actor and then cleaned the owner's own actor instead: that
      factory actor is listed here.

    A replacement whose successor's create raised is announced later, by
    the next verified sign-in for the creator: the one that creates the
    actor, one that cleans the actor the email form created meanwhile (an
    unverified create announces nothing), or one that replaces a
    ``factory`` actor created meanwhile, or any later sign-in to the
    creator's vouched actor. That event has ``mode="replaced"``, the old id
    and every count ``None``, and fires once per earlier replacement,
    before the sign-in's own event. Like ``actor_deleted`` it is not
    exactly once, so make the handler idempotent: a concurrent sign-in for
    the same creator can announce a replacement twice, a crash between the
    claim and the hook loses it, and a record nobody announces expires
    after seven days. The siblings a failed replacement swept are not
    carried into the later event.

``actor_deleted_complete``
    Triggered **after** the wipe completes. Receives ``actor=None`` and
    ``actor_id`` — there is deliberately no ``ActorInterface``, because the
    actor no longer exists. External side effects belong here.

    **Signature**: ``func(actor: None, actor_id: str, **kwargs) -> None``

    Fires on the HTTP ``DELETE /<actor_id>`` path and (3.16) when a sign-in
    replaces an unvouched actor, with the same ``reason`` and
    ``replaced_by_identifier`` keyword arguments as ``actor_deleted``. See
    :doc:`actor-deletion` for the full contract.

Faults and hooks
~~~~~~~~~~~~~~~~

An actor's wipe can stop part-way and is then resumed (3.16). Which hook
runs on which path:

.. list-table::
   :header-rows: 1

   * - Path
     - ``actor_deleted``
     - ``actor_deleted_complete``
   * - First ``DELETE /<id>``
     - before the wipe
     - after it
   * - ``DELETE /<id>`` repeated after a stall
     - only if it raised ``DbError`` the first time
     - once, by the request that finishes (a crash between recording the
       finish and the hook loses it; a later request finds the deletion
       done and fires nothing)
   * - Either, while another request holds the deletion's lease
     - no (503 with ``Retry-After``)
     - no
   * - A sign-in that finishes a stalled deletion
     - as for a repeated ``DELETE``
     - once
   * - A sign-in's replacement or factory sweep
     - with ``reason="replaced_at_adoption"``
     - once, same kwargs
   * - ``Actor.delete()`` / ``ActorInterface.delete()``
     - no
     - no
   * - ``actingweb-deletions resume``
     - no
     - no (the command prints the ids it finished)

A resumed ``actor_deleted`` gets the kwargs the first attempt recorded. When
one of several registered hooks raises ``DbError``, the retry runs all of
them again; a hook that raised anything else counts as having run. Write
deletion hooks to be idempotent.

Two other folds are deliberate. A subscription callback's handlers run at
most once: once they have run, a fault recording the sequence is logged and
the callback answers as processed. The owner's sign-in removes the
``factory`` actors beside it as a best-effort sweep; a fault there is logged
and the next sign-in retries.

``oauth_success``
    Triggered after successful OAuth2 authentication.

    **Signature**: ``func(actor: ActorInterface, email: str, access_token: str, token_data: dict, user_info: dict) -> Optional[bool]``

    **Returns**: ``False`` to reject authentication, ``True`` or ``None`` to accept

    **Normalized ``user_info``**: regardless of provider, ``user_info`` is
    normalized before the hook fires so you can read one shape:

    - ``display_name`` — derived, or GitHub ``name``
    - ``given_name`` — Apple ``firstName`` / Google ``given_name``
    - ``family_name`` — Apple ``lastName`` / Google ``family_name``
    - ``email`` — the email claim, only when the provider verified it (3.16);
      an unverified one is in ``unverified_email`` instead (Apple's
      first-sign-in ``user`` payload address is always there, it is not
      signed)
    - ``sub`` — provider subject claim (plus other provider fields passthrough)

    .. note::

       Apple returns the user's name **only on the very first sign-in**. Persist
       ``given_name`` / ``family_name`` on first contact — they are not available
       on subsequent sign-ins. See :doc:`../guides/apple-sign-in`.

    .. note::

       Also fires on the free-text email-entry path
       (``POST /oauth/email``, when the OAuth provider returned no verified
       email), not only from ``/oauth/callback``. There: ``email`` is the
       address the user typed (normalised — stripped and lowercased), not a
       value the provider vouched for; ``user_info["email"]`` is absent
       (the provider returned none); and at hook time
       ``actor.store.email_verified == "false"`` until the user clicks the
       verification link. A hook returning a falsy value here answers the
       request with 403 and writes no verification token or index row.

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

    **Note**: Fires when this actor's approval completes the mutual trust (peer had already approved): an approval through ``PUT /trust/<rel>/<peer>`` or the web UI, and (3.16) creating the trust toward a peer whose verified request was waiting (``POST /trust``, the web form, ``TrustManager.create_relationship``). ``TrustManager.approve_relationship`` fires ``trust_approved`` instead; the trustee path (``create_peer_trustee``) fires neither. A pending request replaced by a request that verifies, or by the owner's own, fires no ``trust_deleted``.

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
                from actingweb.trust_permissions import get_trust_permission_store
                store = get_trust_permission_store(actor.config)
                store.update_permissions(actor.id, peer_id, {"properties": []})
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

``email_sign_in_code_required``
    Triggered (3.16) when a user whose provider has no verified address types,
    in the email form, an address that already has a verified actor. Without
    this hook the form answers 409; with it the form asks for this code.

    **Signature**: ``func(actor: ActorInterface, email: str, code: str, expires_in: int) -> None``

    **Purpose**: Send ``code`` (six digits, valid for ``expires_in`` seconds,
    five tries) to ``email``. The page that asked posts it back with its
    ``code_challenge`` to ``POST /oauth/email`` and is signed in to ``actor``.
    A browser page is bound to its browser by the
    ``__Host-aw_sign_in_binding`` cookie (``Secure``, so served over HTTPS);
    a JSON client's challenge is redeemed by a JSON request. At most five
    codes are created per actor per hour; past that the form answers 429
    until the hour ends.

    **Raise to report a failed send.** When every registered handler
    raises, the library takes the code as not sent: the challenge is
    withdrawn and the form answers 503 ("The sign-in code could not be
    sent"). Its hourly slot stays used, so raise only for a send that
    failed: a handler that raises after the mail left still costs the user
    a code. Any exception before a handler has run without raising, a
    ``DbError`` from a write after your own send included, counts as not
    sent and withdraws the code (a ``DbError`` answers 503): send last, or
    catch your own bookkeeping faults. Once one handler has run without
    raising, a later handler's failure is logged and the code stays good. A handler that queues the
    mail and returns counts as sent. Unlike most lifecycle hooks, an
    exception here is not only logged.

    .. code-block:: python

        @app.lifecycle_hook("email_sign_in_code_required")
        def send_sign_in_code(actor, email, code, expires_in):
            send_email(
                to=email,
                subject="Your sign-in code",
                body=f"Your code is {code}. It expires in {expires_in // 60} minutes.",
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

.. note::

   Auto-generation feeds the ``/methods`` and ``/actions`` discovery surface
   only. It does **not** reach MCP: ``tools/list`` reads the ``@mcp_tool``
   metadata exclusively, so a TypedDict-derived ``output_schema`` is never
   advertised as ``outputSchema``. To declare an output schema for an MCP tool,
   pass it to ``@mcp_tool(output_schema=...)`` explicitly.

   Note also that an ``output_schema`` — however it is supplied — does not make
   a tool emit ``structuredContent``. Only a ``structuredContent`` key in the
   returned dict does that. See
   :ref:`Structured Tool Output <mcp-structured-tool-output>`.

Action Hooks
============

Decorator: ``app.action_hook(name, description="", input_schema=None, output_schema=None, annotations=None)``

Signature: ``func(actor, action_name: str, data: dict) -> Any``

- Implements side-effecting operations under ``/actions``; first non-None return wins
- Metadata is exposed via ``GET /<actor_id>/actions`` for API discovery

**Metadata Parameters**:

- ``description``: Human-readable description of what the action does
- ``input_schema``: JSON schema describing expected input parameters
- ``output_schema``: JSON schema describing the expected return value. This
  describes the ``/actions`` discovery surface only — it is **not** forwarded to
  MCP. A tool's ``outputSchema`` comes solely from
  ``@mcp_tool(output_schema=...)``; passing it to ``action_hook`` leaves MCP
  unaware of it. Neither one causes ``structuredContent`` to be emitted — see
  :ref:`Structured Tool Output <mcp-structured-tool-output>`.
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
- **Async AwProxy methods** (``get_resource_async()``, ``create_resource_async()``, ``change_resource_async()``, ``delete_resource_async()``)
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

    from actingweb.aw_proxy import AwProxy

    @app.action_hook("send_notification")
    async def async_notify(actor, action_name, data):
        """Async action hook using AwProxy."""
        proxy = AwProxy(
            peer_target={"id": actor.id, "peerid": data["peer_id"]},
            config=actor.config,
        )

        # Use async methods for peer communication
        result = await proxy.create_resource_async(
            path="callbacks/notification",
            data={"message": data["message"]},
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

