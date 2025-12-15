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
