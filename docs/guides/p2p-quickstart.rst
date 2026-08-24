====================
P2P Quickstart
====================

This quickstart gets two actors talking peer-to-peer: actor A publishes a
property change, and actor B -- who has established trust with actor A and
subscribed to its ``"properties"`` target -- receives that change through a
subscription data hook. Both actors are served by the same ActingWeb app;
the trust handshake between them is a real HTTP call regardless of whether
the two actors happen to share a process.

The full application code below is
:download:`examples/p2p_quickstart.py <../../examples/p2p_quickstart.py>`,
included directly by this page (not copied), so what you read here is
exactly what runs.

Install
-------

.. code-block:: bash

   # pip
   pip install 'actingweb[fastapi]'

   # or with Poetry
   poetry add actingweb -E fastapi

You also need a database. For local development, start DynamoDB Local:

.. code-block:: bash

   docker compose -f docker-compose.test.yml up dynamodb-test

See :doc:`../quickstart/overview` for PostgreSQL and other backend options.

Both Sides in One App
----------------------

Peer-to-peer subscriptions require ``.with_subscription_processing()`` --
without it, ``@app.subscription_data_hook`` never fires (only the raw
``@app.subscription_hook`` does; see :doc:`../reference/hooks-reference`).
``auto_sequence=True`` is what makes the receiving hook below get already-
sequenced, deduplicated, stored data instead of raw callback payloads.

The ``trust_request_received`` lifecycle hook auto-approves an incoming
trust request. It has to: ``create_relationship()`` (below) only approves
the relationship on the side that initiates it -- the peer's side stays
unapproved until the peer approves it too, and a subscription request is
rejected with ``403`` unless *both* sides are approved. This is demo-only
auto-approval; see the Security Note near the bottom of this page before
using this pattern for real trust requests.

.. literalinclude:: ../../examples/p2p_quickstart.py
   :language: python
   :start-after: start: app-setup
   :end-before: end: app-setup

Actor A -- Publish
-------------------

Create actor A the same way :doc:`../quickstart/getting-started` does --
passing ``hooks=app.hooks`` so lifecycle hooks fire on creation -- then write
a property. Any subscriber to ``"properties"`` sees this change.

.. code-block:: python

   config = app.get_config()
   actor_a = ActorInterface.create(creator="a@example.com", config=config, hooks=app.hooks)

.. literalinclude:: ../../examples/p2p_quickstart.py
   :language: python
   :start-after: start: publish
   :end-before: end: publish

.. code-block:: python

   publish_status(actor_a, "active")

Actor B -- Establish Trust and Subscribe
------------------------------------------

Actor B initiates trust with actor A's URL, approves the relationship, then
subscribes. ``create_relationship()`` returns ``None`` on failure -- check it
before reading ``.peer_id`` off the result, unlike the magic-string
``peer_id="peer123"`` you may see in older examples.

.. literalinclude:: ../../examples/p2p_quickstart.py
   :language: python
   :start-after: start: subscribe
   :end-before: end: subscribe

.. code-block:: python

   actor_b = ActorInterface.create(creator="b@example.com", config=config, hooks=app.hooks)
   rel = establish_trust_and_subscribe(actor_b, publisher_url=f"http://localhost:5000/{actor_a.id}")

Actor B -- Receive
-------------------

The receiving hook is already registered above, in the same ``app-setup``
block:

.. code-block:: python

   @app.subscription_data_hook("properties")
   def on_properties_changed(actor, peer_id, target, data, sequence, callback_type):
       print(f"[{actor.id}] update from {peer_id} ({callback_type} #{sequence}): {data}")

Run It
------

.. code-block:: bash

   # examples/p2p_quickstart.py runs a FastAPI server directly:
   APP_HOST_FQDN=localhost:5000 python examples/p2p_quickstart.py

   # or with uvicorn against your own app module:
   uvicorn myapp:api --reload --port 5000

Verify
------

Create both actors, establish trust, subscribe, and publish -- all over the
REST API. Actor creation is unauthenticated, but every request after that
requires HTTP Basic auth (``creator:passphrase``) -- capture each actor's
``passphrase`` from its creation response rather than discarding it (this
needs ``jq``):

.. code-block:: bash

   # Create actor A -- capture id and passphrase, both needed below
   actor_a=$(curl -s -X POST http://localhost:5000/ -d '{"creator":"a@example.com"}' \
     -H 'Content-Type: application/json')
   actor_a_id=$(echo "$actor_a" | jq -r .id)
   actor_a_pass=$(echo "$actor_a" | jq -r .passphrase)

   # Create actor B
   actor_b=$(curl -s -X POST http://localhost:5000/ -d '{"creator":"b@example.com"}' \
     -H 'Content-Type: application/json')
   actor_b_id=$(echo "$actor_b" | jq -r .id)
   actor_b_pass=$(echo "$actor_b" | jq -r .passphrase)

   # Actor B initiates trust with actor A, authenticated as actor B's owner.
   # The running server's on_trust_request_received hook (see "Both Sides in
   # One App" above) auto-approves actor A's side as this request arrives --
   # no separate approval step needed.
   curl -s -u "b@example.com:$actor_b_pass" -X POST "http://localhost:5000/$actor_b_id/trust" \
     -H 'Content-Type: application/json' \
     -d "{\"url\": \"http://localhost:5000/$actor_a_id\", \"relationship\": \"friend\"}"

   # Actor B subscribes to actor A's properties, authenticated as actor B's owner
   curl -s -u "b@example.com:$actor_b_pass" -X POST "http://localhost:5000/$actor_b_id/subscriptions" \
     -H 'Content-Type: application/json' \
     -d "{\"peerid\": \"$actor_a_id\", \"target\": \"properties\", \"granularity\": \"high\"}"

   # Actor A publishes a change, authenticated as actor A's owner
   curl -s -u "a@example.com:$actor_a_pass" -X POST "http://localhost:5000/$actor_a_id/properties" \
     -H 'Content-Type: application/json' -d '{"name": "status", "value": "active"}'

Actor B's server log should show the ``on_properties_changed`` hook firing
with ``{"status": "active"}``.

Security Note
-------------

Approving a trust relationship grants the peer whatever the trust type
permits -- for the built-in ``"friend"`` type used above, that's broad
read/write access (see :doc:`access-control`). Do not auto-approve trust
requests from unverified peers in a real application; require an explicit
human or policy decision before calling ``approve_relationship()``.

If you use a **custom** trust type instead of a built-in one, note that
``acl_rules`` is a silent hard dependency for subscriptions and callbacks: a
custom trust type without ``acl_rules`` covering the ``subscriptions`` and
``callbacks/subscriptions`` HTTP paths will have its subscribe/callback
requests denied with no other symptom. See :doc:`access-control-simple` for
``add_trust_type(..., acl_rules=...)``.

Production Notes
-----------------

- On Lambda/serverless, call ``.with_sync_callbacks()`` so subscription
  callbacks complete before the function freezes -- async fire-and-forget
  callbacks can otherwise be lost. See ``docs/quickstart/deployment.rst``.
- For back-pressure, gap detection, circuit-breaker behavior, and fan-out
  tuning, see :doc:`subscriptions` -- this quickstart uses the library's
  defaults throughout.

Where to Go Next
-----------------

- See a complete application: ``examples/demo/`` in this repository wires up
  OAuth2 login and the full hook system -- including trust and subscription
  hooks -- in one worked example, version-locked to the release you have
  checked out.
- :doc:`trust-relationships` -- the full trust lifecycle, including
  per-relationship permission overrides
- :doc:`subscriptions` -- subscription processing configuration, gap
  handling, and resync
- :doc:`access-control` -- the full permission and trust-type system
