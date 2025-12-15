===============================
Attributes and Buckets (Global)
===============================

Overview
--------

Use the attribute/bucket system for application‑level or cross‑actor data such as configurations, registries, and indexes.

Buckets
-------

.. code-block:: python

   from actingweb import attribute

   # Per‑actor bucket
   prefs = attribute.Attributes(actor_id=actor.id, bucket="user_preferences", config=config)
   prefs.set_attr(name="theme", data="dark")
   theme_attr = prefs.get_attr(name="theme")

Global Storage
--------------

.. code-block:: python

   # Global settings
   global_config = attribute.Attributes(actor_id="_global_config", bucket="app_settings", config=config)
   global_config.set_attr(name="maintenance_mode", data=False)

Client Registry Example
-----------------------

.. code-block:: python

   class ClientRegistry:
       def __init__(self, config):
           self.config = config

       def register_client(self, actor_id: str, client_data: dict) -> None:
           bucket = attribute.Attributes(actor_id=actor_id, bucket="clients", config=self.config)
           bucket.set_attr(name=client_data["client_id"], data=client_data)
           index = attribute.Attributes(actor_id="_global_registry", bucket="client_index", config=self.config)
           index.set_attr(name=client_data["client_id"], data=actor_id)

       def find_client(self, client_id: str) -> dict | None:
           index = attribute.Attributes(actor_id="_global_registry", bucket="client_index", config=self.config)
           actor_id_attr = index.get_attr(name=client_id)
           if not actor_id_attr or "data" not in actor_id_attr:
               return None
           actor_id = actor_id_attr["data"]
           bucket = attribute.Attributes(actor_id=actor_id, bucket="clients", config=self.config)
           client_attr = bucket.get_attr(name=client_id)
           return client_attr.get("data") if client_attr else None

Best Practices
--------------

- JSON‑serializable data only
- Use attributes for sensitive/secret data instead of properties
- Keep bucket names stable; treat keys as logical IDs
