========================
Actor Deletion Semantics
========================

**Audience**: Applications that do external cleanup when an account is deleted —
cancelling a payment subscription, revoking an IdP grant, deleting remote files.

This page states the contract you may rely on: what deletion does, in what
order, what ``get_by_id()`` reports while it happens, and how to write a guard
that suppresses late writes for an actor that is gone.

.. contents:: On this page
   :local:
   :depth: 2

The short version
=================

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Question
     - Answer
   * - Does ``get_by_id()`` return ``None`` during deletion?
     - **No.** The actor row is removed last, so it resolves throughout.
   * - Does ``get_by_id()`` return ``None`` on a failed read?
     - **Yes** — indistinguishable from "does not exist".
   * - How do I check "was this actor deleted?"
     - :meth:`~actingweb.interface.ActorInterface.get_deletion_status`
   * - Where do I put external cleanup?
     - The ``actor_deleted_complete`` hook, not ``actor_deleted``.
   * - Do attribute/property writes check the actor exists?
     - **No.** See :ref:`no-referential-integrity`.

Do not write a guard of the form ``if ActorInterface.get_by_id(actor_id,
config) is None: return``. The two rows above explain why: it fails open during
the window it exists for, and closed on an unrelated infrastructure fault.

.. _deletion-ordering:

What deletion does, in order
============================

``DELETE /<actor_id>`` (and :meth:`actingweb.interface.ActorInterface.delete`)
runs these steps in this order:

#. **Write a deletion tombstone.** On the HTTP path this happens *before the*
   ``actor_deleted`` *hook runs* — so an external call made from that hook, and
   any provider callback racing it, already sees ``DELETED``.
#. Run the ``actor_deleted`` lifecycle hook (HTTP path only).
#. Delete peer-trustee relationships.
#. Delete properties and property lists.
#. Delete subscriptions.
#. Delete trust relationships, including reciprocal ones on peers.
#. Delete all attribute buckets.
#. **Delete the actor row** — last.
#. Run the ``actor_deleted_complete`` lifecycle hook (HTTP path only).

Two consequences follow from the row going last, and both are contract:

- The actor **remains resolvable for the whole of steps 1–7**.
  ``ActorInterface.get_by_id()`` returns an actor, and reading its properties
  returns progressively less data as the wipe proceeds.
- Deletion is **retriable**. If a step fails, the actor row is still there and
  ``DELETE`` can be issued again. Removing the row first would strand the
  remaining rows with nothing pointing at them.

The window is not narrow, and it is not hypothetical: it is seconds wide for an
actor with a real property set, and the documented cleanup pattern *enters it
deliberately*. ``actor_deleted`` is where an application cancels an external
subscription; cancelling triggers an asynchronous provider webhook that arrives
back into the window and writes rows that outlive the actor.

Checking whether an actor is gone
=================================

.. code-block:: python

    from actingweb.interface import ActorInterface, DeletionStatus

    def on_provider_webhook(actor_id, payload):
        status = ActorInterface.get_deletion_status(actor_id, config)
        if status == DeletionStatus.DELETED:
            return  # account is gone; drop this late callback
        # NOT_DELETED and UNKNOWN both proceed
        write_entitlement(actor_id, payload)

:meth:`~actingweb.interface.ActorInterface.get_deletion_status` reads a
tombstone written before the wipe begins, and answers with three values:

``DeletionStatus.DELETED``
   A tombstone was found. The actor has been deleted. Suppress the write.

``DeletionStatus.NOT_DELETED``
   The store was read and holds no tombstone. Proceed.

``DeletionStatus.UNKNOWN``
   The store could not be read (throttle, timeout, missing table, credentials).
   **Proceed.**

Cost is one strongly-consistent point read: a single DynamoDB ``GetItem``, or one
primary-key ``SELECT`` on PostgreSQL. Cheap enough for a webhook path.

Why ``UNKNOWN`` means proceed
-----------------------------

This is the part worth internalising, because it is what makes the check
correct rather than merely available.

The two error directions are not symmetric. Treating an unreadable store as
"deleted" **drops real work**: for a payment webhook that is a customer who
paid, an HTTP 200 back to the provider so it never retries, no entitlement, and
nothing logged. Treating it as "proceed" costs at most **one orphan row**, which
an operator sweep can find and remove later.

A tombstone is *positive* evidence, so it has a safe failure direction. An
absence check has none — that asymmetry is precisely what it cannot express, and
why a guard built on ``get_by_id() is None`` cannot be made correct.

Retention
---------

Tombstones live for 30 days
(:data:`actingweb.constants.DELETION_TOMBSTONE_TTL`), comfortably past every
provider's webhook retry window — Stripe retries a failed webhook for up to 3
days, and others are comparable. A tombstone that expired in an hour would
reopen the hole it exists to close.

They are stored under a reserved id that is never itself an actor, so no
deletion can destroy them. A marker kept inside the deleted actor's own
attribute bucket does not survive the wipe it is meant to describe.

On DynamoDB, expiry is native TTL on ``ttl_timestamp``; on PostgreSQL, rows are
reclaimed by an explicit ``delete_expired()`` sweep (see
:doc:`../guides/database-maintenance`), so tombstones accumulate there until one
runs. Either way an expired tombstone is filtered at read time, so TTL means the
same thing on both backends and stale rows never keep suppressing writes.

.. note::

   Re-creating an actor clears its tombstone. Generated actor ids are never
   reused, but ``create(actor_id=...)`` accepts a caller-supplied id.

What ``get_by_id()`` returning ``None`` actually means
======================================================

.. warning::

   ``ActorInterface.get_by_id()`` returns ``None`` for **both** "no such actor"
   and "the read failed". A throttled DynamoDB read, an expired credential and a
   missing table all present as a non-existent actor.

This is deliberate for backward compatibility: raising instead would turn every
transient throttle across authentication, OAuth2 and MCP into an HTTP 500. It is
documented here rather than changed.

What did change: the DynamoDB backend now **logs the swallowed exception at
ERROR** (``Failed to read actor <id> ...``) where it previously returned ``None``
with no log line at any level. That ERROR is your only signal that an existence
check answered "no" for an infrastructure reason — alert on it. A genuine
absence logs nothing.

If you need the distinction programmatically, use ``get_deletion_status()``,
which reports ``UNKNOWN`` rather than guessing.

Lifecycle hooks
===============

Two hooks bracket the wipe, and which one you use matters.

``actor_deleted`` — before, with data
-------------------------------------

Fires **before any data is removed**. The actor is fully readable, so this is
where you *read* what you will need. It receives an ``ActorInterface``.

``actor_deleted_complete`` — after, without
-------------------------------------------

Fires **after the wipe completes**. Receives ``actor=None`` and
``actor_id=<id>``: there is deliberately no ``ActorInterface``, because the
actor no longer exists. This is where external side effects belong.

.. code-block:: python

    @app.lifecycle_hook("actor_deleted")
    def read_what_we_need(actor, **kwargs):
        # Only place the data is still readable.
        _pending[actor.id] = actor.properties.stripe_subscription_id

    @app.lifecycle_hook("actor_deleted_complete")
    def do_external_cleanup(actor, actor_id=None, **kwargs):
        # The actor is definitely gone. A provider callback triggered from
        # here cannot race the wipe.
        subscription_id = _pending.pop(actor_id, None)
        if subscription_id:
            stripe.Subscription.delete(subscription_id)

Splitting the work this way removes the race at its source: the callback arrives
after the wipe rather than during it, and the tombstone is there to suppress it.

Both hooks are fire-and-forget — an exception is logged and ``DELETE`` still
returns 204. Neither fires for
:meth:`actingweb.interface.ActorInterface.delete`; only the HTTP path runs
lifecycle hooks, so an application deleting an actor programmatically owns its
own cleanup. A tombstone is written on both paths.

.. _no-referential-integrity:

Actor-scoped writes have no referential integrity
=================================================

.. warning::

   Attribute and property writes do **not** validate that the actor exists. An
   unknown or deleted ``actor_id`` creates rows that nothing will ever clean up.

``actor_id`` is a key prefix, not a foreign key. This holds on both backends:
PostgreSQL declares ``ON DELETE CASCADE`` only on ``property_lookup``, so the
wipe steps in :ref:`deletion-ordering` are what actually removes an actor's
data — not the database.

Two ways this bites:

- **Test fixtures.** Generating ``test-actor-<n>`` ids without creating actors,
  then passing them to code that writes attributes, leaves permanent rows. This
  accumulates silently — one such fixture produced 228 orphan rows under 114
  ids, unnoticed for five months.
- **Late writes.** A webhook for an actor deleted an hour ago succeeds and
  creates rows, unless guarded as above.

If you write actor-scoped data from a path that is not already inside a
request for that actor, guard it. ``get_deletion_status()`` covers deleted
actors; ids that never existed need your own check.

Finding orphaned rows
=====================

``actingweb-verify-orphans`` (also ``python scripts/verify_orphans.py``,
:mod:`actingweb.maintenance.verify_orphans`) sweeps property, attribute and
trust rows across the WHOLE table — not one actor's partition — for rows
whose ``actor_id`` is absent from the actor table::

    poetry run python scripts/verify_orphans.py
    poetry run python scripts/verify_orphans.py --rps 200 \
        --checkpoint-file .verify_orphans.checkpoint.json

Run it under the SAME environment as the application (``DATABASE_BACKEND``
and its connection settings), but under an **operator credential**, not the
application's runtime role: the full-table scans need ``Scan``/``Query``
read permission on the actor, property, attribute and trust tables, which a
locked-down serving-path role deliberately lacks. It is a long-running,
checkpointed CLI for a persistent shell — do not invoke it from a
lambda-like runtime. It classifies orphans only; it does not replace
:doc:`../guides/database-maintenance` (TTL cleanup) or
``actingweb-verify-property-lists`` (per-actor list index integrity).

Four edge cases drove its design, and each is a way to delete live data if
gotten wrong:

#. **An empty or failed actor-table read must never be read as "zero
   orphans."** "Every row is orphaned" is the catastrophic misreading of an
   actor-table read that failed or came back empty — a clean-looking report
   from a broken read is worse than an error, because nothing about it looks
   wrong. The tool fails closed instead: it refuses to sweep and exits with
   status 2, which is deliberately distinct from "orphans found" (status 1)
   and "clean" (status 0).
#. **Exclude reserved ids unconditionally.** Ids prefixed ``_actingweb_`` hold
   live system data — some are real actors (``ACTINGWEB_SYSTEM_ACTOR``,
   ``OAUTH2_SYSTEM_ACTOR``), some (``DELETED_ACTORS_STORE``, a consumer's own
   registries) deliberately are not in the actors table at all. The tool
   matches on the prefix, not the closed list of known names, and reports
   them in a separate section — never as orphans.
#. **Use consistent reads.** An eventually-consistent scan can show a
   seconds-old actor as absent. Every read this tool issues — the actor-id
   enumeration and all three row sweeps — asks for a consistent read.
#. **Never automate it.** ``create()`` writes the actor row first and
   ``delete()`` removes it last, so an actor mid-create or mid-delete always
   still has its row — that ordering is what makes classification safe at all.
   It is still a point-in-time judgement about rows another process may be
   writing. There is no ``--delete`` flag and no code path in the tool
   deletes a row. Run it deliberately, review the output, then delete
   reviewed rows with your own tooling.

See also
========

- :doc:`hooks-reference` — all lifecycle events
- :doc:`../guides/hooks` — hook patterns
- :doc:`database-backends` — required tables and schema
- :doc:`../guides/database-maintenance` — TTL sweeps on PostgreSQL, and the
  orphan scan's operational envelope
