====================
Subscription Manager
====================

Overview
--------

Subscribe to peer updates and notify subscribers of changes.

Usage
-----

.. code-block:: python

   # Outbound subscription
   actor.subscriptions.subscribe_to_peer(
       peer_id="peer123", target="properties", granularity="high"
   )

   # Notify subscribers
   actor.subscriptions.notify_subscribers(
       target="properties", data={"status": "active"}
   )

   # Introspection
   for sub in actor.subscriptions.all_subscriptions:
       print(sub.peer_id, sub.target)

   # Unsubscribe
   actor.subscriptions.unsubscribe(peer_id="peer123", subscription_id="sub123")

Properties
----------

- ``all_subscriptions``: all inbound/outbound
- ``outbound_subscriptions``: to other actors
- ``inbound_subscriptions``: from other actors

Callback Modes
--------------

By default, subscription callbacks are sent asynchronously (fire-and-forget) to avoid blocking the caller. This works well for traditional server deployments but can cause issues in serverless environments.

**Synchronous Callbacks (Lambda/Serverless)**

In Lambda/serverless environments, async tasks may be lost when the function freezes after returning a response. Enable synchronous callbacks to ensure delivery:

.. code-block:: python

   from actingweb.interface import ActingWebApp

   app = ActingWebApp(...).with_sync_callbacks(enable=True)

This makes callbacks use blocking HTTP requests, guaranteeing delivery at the cost of slightly longer response times.

**When to Use Each Mode:**

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Environment
     - Callback Mode
     - Reason
   * - Traditional Server (Flask/FastAPI)
     - Async (default)
     - Background tasks persist after response
   * - AWS Lambda
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Google Cloud Functions
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Azure Functions
     - Sync (``with_sync_callbacks()``)
     - Function freezes after response
   * - Kubernetes/Docker
     - Async (default)
     - Background tasks persist after response
