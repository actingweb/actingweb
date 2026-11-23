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
- A peer's hook runs only where its grant allows the operation (the same
  decision as the route). On a denial ``execute_property_hooks`` returns
  ``actingweb.access_decision.PERMISSION_DENIED`` for every operation and
  the handlers answer 403; ``None`` keeps its meaning. An error in the check
  denies. ``path`` is passed as it was before 4.0 (on some routes it starts
  with the property name); a hook that reads a name from it keeps working.
- In a bulk ``POST /properties`` every name is authorised before any hook
  runs; a hook that rejects a later name does not undo earlier ones.

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

Decorator: ``app.callback_hook(name: str = "*", *, allow_anonymous: bool = False)``

Signature: ``func(actor, name: str, data: dict) -> bool | dict``

- Return ``True`` when processed; optionally return a ``dict`` as response payload
- Used for custom endpoints registered by the framework (e.g., ``bot``, ``www``)
- ``/callbacks/<name>`` requests are authenticated (4.0): without
  credentials they answer 401, and any authenticated caller reaches the
  hook. The library's own names (``permissions``, ``subscription``,
  ``subscriptions``, ``www`` and any ``resource_*``) answer 403 on a direct
  ``/callbacks/<name>`` request, so their hooks only receive data the
  library built (the web UI still dispatches ``www``)
- An authenticated request to a name **no hook is registered for** (and no
  ``"*"`` hook) answers 403 (4.0; it answered 200 with ``false``). A hook
  that ran and returned ``False`` or ``None`` keeps its answer (200 with
  ``false``): only "nothing registered" changed
- For an application's own name, ``data`` on ``POST`` and ``PUT`` holds the
  JSON object the body carried (an empty dict for any other body; a JSON
  array raised before 4.0), then what the library sets from the request,
  which a body cannot override: ``method`` (``"POST"`` or ``"PUT"``),
  ``anonymous`` (``False`` for an authenticated request), ``headers`` (the
  request's headers without ``Authorization`` and ``Cookie``) and
  ``raw_body`` (the body as ``bytes``: remove it before serialising ``data``
  as JSON). On ``GET`` and ``DELETE``, ``data`` is ``{"method": "GET"}`` or
  ``{"method": "DELETE"}`` and nothing else
- A hook registered for ``permissions`` is run by the library's permission
  callback, with the callback's body plus ``granting_actor_id``, ``method``
  and ``permission_changes``. It runs only for a callback the store accepted
  (4.0): not for one older than the sender's last stored callback, and not
  for one refused (400, 403) or answered 503. It still runs when the accepted
  callback changed nothing

Anonymous webhooks (``allow_anonymous``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A third party's webhook (a payment or SMS provider) cannot send an actor's
credentials. Registering the hook with ``allow_anonymous=True`` (4.0) lets a
``POST /<actor_id>/callbacks/<name>`` without credentials reach it:

- **Admitted:** a ``POST`` that arrived as a ``POST`` (no ``_method``
  override on either side), with no ``Authorization`` header, to exactly the
  name the hook was registered under. Only the hooks registered for that
  name with the flag run, never the ``"*"`` hooks, and no access row is
  consulted (there is no caller to authorise). An unknown actor answers 404,
  as before.
- **Refused:** ``GET``, ``PUT`` and ``DELETE`` without credentials, a
  ``_method`` override, an unflagged name, and the subscription and
  permission callback paths all answer 401 as before. A request that carries
  credentials is authenticated as today (a bearer that matches nobody is
  403) and its hook is given ``anonymous: False``. Registering the flag for
  ``"*"`` or a library name raises ``ValueError``.
- **What the hook is given:** ``data["anonymous"]`` is ``True``,
  ``data["headers"]`` the request's headers, ``data["raw_body"]`` the body's
  bytes, and the parsed JSON object when the body is one (a form-encoded
  body leaves the parsed part empty; ``raw_body`` is the bytes as sent on
  both integrations). A body over 1 MB answers 413 before the hook runs (by
  its ``Content-Length`` first); the integration has read the body by then,
  so a deployment that must bound memory sets a request size limit in front
  of the application as well.
- **The answer:** the hook's result as JSON with 200 when it returns a
  truthy value; 403 when it returns ``False`` or ``None`` or raises (the
  registry logs the exception), so a provider that retries on a non-2xx
  retries, and a forger learns nothing.
- **The hook authenticates its caller, on every request.** There is no peer
  and no creator behind an anonymous request, and an authenticated request
  may come from a peer of any relationship (the ``any`` row admits
  ``/callbacks``), so a hook that acts on a provider's event verifies the
  provider's signature over ``raw_body`` or a shared secret in a header, in
  constant time, whatever ``data["anonymous"]`` says, and returns ``False``
  otherwise. ``headers`` and ``raw_body`` always come from the request
  itself, on both paths, so a body cannot supply its own; ``headers``
  leaves out the caller's ``Authorization`` and ``Cookie``.
- **A provider that sends its own ``Authorization`` header** (Basic
  credentials in the webhook URL, a bearer token) is authenticated as an
  actor caller, and refused (403), so it cannot use the flag: point it at
  an application route.

.. code-block:: python

    import hashlib
    import hmac
    import os

    @app.callback_hook("payment_webhook", allow_anonymous=True)
    def payment_webhook(actor, name, data):
        secret = os.environ["PAYMENT_WEBHOOK_SECRET"].encode()
        headers = {k.lower(): v for k, v in (data.get("headers") or {}).items()}
        expected = hmac.new(secret, data.get("raw_body") or b"", hashlib.sha256).hexdigest()
        if not hmac.compare_digest(headers.get("x-signature", ""), expected):
            return False  # 403
        # ... act on the verified event ...
        return {"status": "processed"}

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

        return False  # Not handled: the page answers 404 (4.0)

The template will receive:

- Standard values: ``id``, ``url``, ``actor_root``, ``actor_www``
- Custom data from the ``data`` dict in the return value

This allows applications to add custom web UI pages without modifying the core library.

A template dict renders on a ``GET`` only; on a ``POST``, and without
``template``, a dict is answered as JSON. ``False`` or ``None`` answers 404
(4.0). Any other result, a string included, is answered as the text
``True``: return a template dict to show a page.

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
- ``data`` is the callback's data as the publisher sent it, after the
  library applied it to the replica (with ``auto_storage``). A list edit (4.0: from the SDK, REST
  and the web UI alike) is a list diff, ``{"list", "operation", "length"}``
  plus ``item``, ``index``, ``old_item`` or ``items`` as the operation needs
  (``append``, ``extend``, ``insert``, ``update``, ``delete``, ``pop``,
  ``remove``, ``clear``, ``delete_all``, ``metadata``). For a subscription to
  the whole target it is keyed by the list's name,
  ``{"notes": {"list": "notes", "operation": "append", "length": 3,
  "index": 2, "item": "x"}}``; for a subscription to the list's subtarget it
  is the bare diff. A diff too large to send carries ``"spanned": true`` and
  ``"bytes"`` instead of its values. Recognise a list diff by its ``list``
  equalling the key it arrived under (or the subscription's subtarget), not
  by ``"list" in value``: a property's value may carry those keys. The
  legacy ``callback_hook("subscription")`` receives the same diff in its
  ``data["data"]``.
- A delete (4.0, specification 1.5) is ``""`` at the subscribed level:
  ``{"name": ""}`` for a whole-target subscription, ``""`` for one to the
  name or to a resource that went with its parent. A clear is one call with
  every deleted name. A nested write gives a subscription above the resource
  the parent's whole value. Treat ``""`` as absent.
- The hook also runs for each change the library's poll applies (the gap
  resync's poll included, 4.0; it ran for none), once per sequence, with
  ``callback_type`` ``"diff"`` or ``"resync"``. ``data`` never carries a
  ``timestamp`` key the publisher did not send.
- **A rebuild tells its baseline** (4.0). A subscriber rebuilds from the
  publisher's baseline when a rebuild is owed (a resync whose fetch failed,
  a list diff the replica could not apply, a rebuild that did not settle),
  a resync marker is polled, or a poll was behind the publisher with
  nothing to fetch. A poll whose diffs were all applied already refreshes
  the replica from the baseline instead (with ``auto_storage``; no rebuild
  is reserved) and tells it the same way. A rebuild that
  settled calls the hook once with the baseline, the sequence recorded and
  ``"resync"``, also after a list diff it was told first (the diffs after
  that one were never run, and the baseline is how it hears them). Not
  told: a baseline another subscription's replica covers (that
  subscription's callbacks tell the same change), and a rebuild that did
  not settle (it stays owed and tells when it runs again).
- **Who runs it.** A rebuild has work when there is a replica
  (``auto_storage``) or a hook that hears it: a data hook for the
  subscription's target or ``"*"``, or, on the callback path, the legacy
  ``subscription`` callback hook (a ``"*"`` callback hook counts). Only
  then is one owed or run; a callback that finds a debt nobody hears drops
  it. The next callback after the one-minute interval runs an owed
  rebuild and tells both kinds of hook; a poll runs it too and tells the
  data hooks only. A poll cannot see the legacy hook, so with no replica
  and no data hook it leaves an owed rebuild for the next callback. A gap
  resync runs a poll on the callback path, and like any poll it tells
  data hooks only. **The legacy ``subscription`` callback hook hears the
  callbacks it processes and the rebuilds the callback path runs; what a
  poll does does not reach it** (nor a queued callback a gap resync
  clears: its poll brings that change to data hooks only). An application that must hear every change uses
  ``subscription_data_hook``. A resync
  marker is only polled by a subscriber that gets no callbacks; with no
  replica and no data hook it is applied as an empty diff and tells
  nobody. A poll called without a configuration uses the application's
  (``with_subscription_processing()``), for its diffs and its baseline. The public
  ``rebuild_subscription()`` tells no hook: its caller does.
- **Quiet and behind polls.** A quiet poll, with nothing to fetch and the
  recorded sequence level with the publisher's, refreshes the replica
  without calling the hook: that is the state it already heard about. With
  nothing to fetch but the subscriber behind (after a gap resync discarded
  queued callbacks, say; with ``auto_sequence``), the poll runs a rebuild,
  an empty baseline included. A rebuild that failed is attempted again
  after a minute; a poll inside that minute fails with ``error_code`` 429.
  A coroutine hook of the async poll is scheduled on the caller's loop.
- After a resync the replica no longer holds what the baseline lacks; the
  hook gets the baseline, not the names removed.
- **Answers.** A callback that ran an owed rebuild in place of its diff
  answers 503 when the rebuild does not settle, and its change is told by
  the rebuild that later settles. A callback whose own change was applied,
  or is queued, answers 204 even when a rebuild after it does not settle;
  that rebuild stays owed. This library's publisher does not resend a
  callback answered 503: the change returns through a poll or a gap
  resync. Reserving or settling a rebuild uses the callback state store,
  also without ``auto_storage``: a fault there answers 503, also after the
  callback's own change was applied.
- See :doc:`../guides/subscriptions` for the full auto-processing
  configuration and the operation table.

Lifecycle Hooks
================

Decorator: ``app.lifecycle_hook(event: str)``

Signature: ``func(actor, **kwargs) -> Any``

``oauth2_trust_requested`` (4.0): an OAuth2/MCP client is about to get a
trust on ``actor``. Keyword arguments: ``trust_type``, ``client_id``,
``client_name``, ``redirect_uri``, ``provider``, ``email``, ``confirmed``
(the user approved on the confirmation page). Return ``None`` to accept, a
type name to use it instead, or ``False`` to decline. A type other than the
one the user chose is shown to the user on the confirmation page and
granted only on Approve; at Approve (``confirmed=True``) and from
``complete_client_authorization`` a different answer declines. Unlike the
other lifecycle hooks it fails closed: any ``False``, an exception, two hooks
naming different types, or a type the client list (or the client's own
``allowed_trust_types``) does not offer declines.

It is asked on every path that creates such a trust: the library's own
authorisation routes, the OAuth2 server's entry points called without
``decide_trust`` (``complete_client_authorization``,
``handle_confirmation``, ``handle_oauth_callback``), and a sign-in whose
state names ``trust_type`` (4.0). On that sign-in there is no confirmation
page (``confirmed=False``, ``client_id`` and ``client_name`` are ``None``),
so a type other than the requested one declines, as at Approve; a decline
means no trust is created, and the user is still signed in.

- Common events: ``actor_created``, ``actor_deleted``, ``actor_deleted_complete``, ``actor_adopted``, ``oauth_success``, ``trust_initiated``, ``trust_request_received``, ``trust_fully_approved_local``, ``trust_fully_approved_remote``, ``trust_deleted``, ``subscription_deleted``, ``email_verification_required``, ``email_sign_in_code_required``, ``email_verified``

Event Details
~~~~~~~~~~~~~

``actor_created``
    Triggered when a new actor is created. Fires exactly once, from inside
    ``Actor.create()`` itself, before an OAuth handler stores tokens or
    provider metadata on the actor — so at hook time, fields like
    ``oauth_token``, ``oauth_provider``, ``created_at``, ``email`` and
    ``email_verified`` are **not yet set**. ``auth_method`` is the exception
    (4.0): ``Actor.create()`` writes it before the hook fires, so the hook can
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
       4.0) on the second call now sees them absent.

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

    Also fires (4.0) when a sign-in **replaces** an unvouched,
    factory-created actor (see ``actor_adopted``), with the keyword arguments
    ``reason="replaced_at_adoption"`` and ``replaced_by_identifier=<creator>``,
    so a hook that mails "your account was deleted" or cancels billing can tell
    it apart from a user-initiated delete. A deletion that stops part-way is
    resumed (see `Faults and hooks`_): this hook runs at least once per
    registered hook, and again only when one of them raised ``DbError``, so
    write it to be idempotent.

    **Reading** ``actor.store`` **here.** ``actor.store.<name>`` never
    raises: when its bucket could not be read, every name reads as ``None``.
    A hook that acts on an absent value (nothing to revoke, nothing to
    cancel) must tell "not set" from "could not read" with
    ``actor.store.loaded``, which is ``False`` after a failed read:

    .. code-block:: python

        from actingweb.db.exceptions import DbError

        @app.lifecycle_hook("actor_deleted")
        def remember_what_to_revoke(actor, **kwargs):
            token = actor.store.provider_refresh_token
            if not actor.store.loaded:
                # Not "no token": the store did not answer. Raising DbError
                # stops the deletion here; it is resumed and this hook runs
                # again.
                raise DbError("provider token read", actor.id)
            if token:
                queue_revocation(actor.id, token)

``actor_adopted``
    Triggered once per adoption, on the **surviving** actor, after a sign-in
    that proved the creator address (a provider login or the emailed
    verification link) replaced or cleaned an actor nobody vouched for. May
    fire more than once for one actor: two concurrent first sign-ins both run
    the rule. Whether or not the hook is registered, each adoption also logs
    one WARNING line an operator can grep, with ids and markers only (never
    the creator or an email address): ``ACTOR_ADOPTED: actor=<id>
    mode=<cleaned|replaced> previous_auth_method=<marker>
    previous_actor=<id|-> provider=<name>``, followed by the counts; an
    adoption announced by a later sign-in carries ``announced_later=true``.

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

    Fires on the HTTP ``DELETE /<actor_id>`` path and (4.0) when a sign-in
    replaces an unvouched actor, with the same ``reason`` and
    ``replaced_by_identifier`` keyword arguments as ``actor_deleted``. See
    :doc:`actor-deletion` for the full contract.

Faults and hooks
~~~~~~~~~~~~~~~~

An actor's wipe can stop part-way and is then resumed (4.0). Which hook
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

    **Returns**: ``False`` to reject authentication, ``True`` or ``None`` to accept.
    The provider's access and refresh tokens are written onto the actor only
    once the hook accepts (4.0; they were stored before it ran, so a rejected
    sign-in kept them): a hook reads this sign-in's tokens from its
    ``access_token`` and ``token_data`` arguments, not from the store.

    **Normalized ``user_info``**: regardless of provider, ``user_info`` is
    normalized before the hook fires so you can read one shape:

    - ``display_name`` — derived, or GitHub ``name``
    - ``given_name`` — Apple ``firstName`` / Google ``given_name``
    - ``family_name`` — Apple ``lastName`` / Google ``family_name``
    - ``email`` — the email claim, only when the provider verified it (4.0);
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
       ``actor.store.email_verified == "false"`` until the user confirms the
       emailed link (opening it shows a Confirm page and changes nothing,
       4.0). A hook returning a falsy value here answers the
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
    - ``trust_data``: A copy of the trust relationship as written (4.0). The
      answer to the request and its status (201 or 202) are fixed before the
      hook runs, so changing ``trust_data`` changes neither; approve or
      change the row through the trust API. A hook that approves the row
      still answers 202: the requester learns of the approval from the
      approval notification.

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

    **Note**: Fires once, when this actor's approval completes the mutual trust (the peer had already approved), on every approving route: ``PUT /trust/<rel>/<peer>`` and the web UI, ``TrustManager.approve_relationship`` and ``approve_relationship_async``, and creating the trust toward a peer whose verified request was waiting (``POST /trust``, the web form, ``TrustManager.create_relationship``). A repeat approval of a trust already approved fires nothing (4.0). ``trust_data`` is the row as approved. The trustee path (``Actor.get_peer_trustee``) fires nothing. A pending request replaced by a request that verifies, or by the owner's own, fires no ``trust_deleted``.

    **Built-in Behavior**: none on this hook. With ``with_peer_profile()`` the peer's profile is fetched and cached by the first sync (``sync_peer``) or ``refresh_peer_profile()``, not when this hook fires.

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

    **Built-in Behavior**: none on this hook (the peer profile, as above, is cached by the first sync).

``trust_approved`` (deprecated)
    The pre-4.0 name of ``trust_fully_approved_local``. It runs in its place, with the same arguments, only when no ``trust_fully_approved_local`` hook is registered; registering it logs a deprecation warning (once per process). With both registered only ``trust_fully_approved_local`` runs. Rename the hook.

``trust_deleted``
    Triggered before a trust relationship's local data is deleted, on every route that deletes one: ``DELETE /trust/<rel>/<peer>`` (by the owner or the peer), ``TrustManager.delete_relationship`` and its async twin, and a peer's revocation found by ``sync_peer``. On the REST route and in ``sync_peer`` it fires after the delete has found the row (and, on REST, checked it is still the row the request was authorised against): a delete that loses to a re-pair, or that finds no row, fires nothing. ``sync_peer_async`` fires it the same way, from the delete's own read of the row: a coroutine hook is awaited on the caller's event loop (given up after 120 seconds), a sync hook runs in the delete's worker thread.

    **Signature**: ``func(actor: ActorInterface, peer_id: str, relationship: str, trust_data: dict, initiated_by_peer: bool, **kwargs) -> None``

    **Parameters**:

    - ``actor``: The ActorInterface for the current actor
    - ``peer_id``: The ID of the peer in the trust relationship
    - ``relationship``: The type of trust relationship (e.g., "friend", "partner")
    - ``trust_data``: The trust row as it was before the delete (4.0: on every route)
    - ``initiated_by_peer``: True when the peer deleted the trust (its ``DELETE``, or its revocation found by a sync)

    A hook must accept ``**kwargs``: one that names only some arguments raises ``TypeError``, which is logged (the hook named at ERROR once per process) and does not stop the delete.

    **Built-in Behavior**: the hook runs before the row and its data are removed, so it can still read the cached peer profile (``actor.trust.get_peer_profile(peer_id)``); the delete then removes the profile, the subscriptions, the peer's stored data and the grant.

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
    Triggered (4.0) when a user whose provider has no verified address types,
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

