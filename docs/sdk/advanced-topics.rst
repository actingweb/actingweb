===============
Advanced Topics
===============

Access Core Components
----------------------

.. code-block:: python

   # Access underlying core implementations
   core_actor = actor.core_actor
   core_props = actor.properties.core_store

   # Access config (choose based on context)
   config = app.get_config()  # From app instance
   config = actor.config       # From actor instance (v3.8+, useful in hooks)

Custom Framework Integration
----------------------------

.. code-block:: python

   class MyIntegration:
       def __init__(self, aw_app, framework_app):
           self.aw_app = aw_app
           self.framework_app = framework_app
       def setup_routes(self):
           # map ActingWeb handlers to your framework
           pass

Error Handling
--------------

.. code-block:: python

   try:
       actor = ActorInterface.create(creator="user@example.com", config=app.get_config())
   except RuntimeError as e:
       print(f"Failed to create actor: {e}")

   @app.property_hook("email")
   def safe_email(actor, operation, value, path):
       try:
           if operation == "put" and "@" not in value:
               return None
           return value.lower() if operation == "put" else value
       except Exception:
           return None

Custom Route Authentication
---------------------------

For custom routes outside the standard ActingWeb handler system, use ``check_and_verify_auth()``:

.. code-block:: python

   from actingweb import auth
   from actingweb.aw_web_request import AWWebObj
   from actingweb.interface.actor_interface import ActorInterface

   @fastapi_app.get("/{actor_id}/custom/endpoint")
   async def custom_endpoint(actor_id: str, request: Request):
       # Convert framework request to ActingWeb format
       req_data = await normalize_request(request)
       webobj = AWWebObj(
           url=req_data["url"],
           params=req_data["values"],
           body=req_data["data"],
           headers=req_data["headers"],
           cookies=req_data["cookies"],
       )
       
       # Verify authentication
       auth_result = auth.check_and_verify_auth(
           appreq=webobj, 
           actor_id=actor_id, 
           config=app.get_config()
       )
       
       if not auth_result['authenticated']:
           # Handle auth failure (401, 302 redirect, etc.)
           return handle_auth_failure(auth_result)
       
       # Use authenticated actor
       actor = ActorInterface(auth_result['actor'])
       return {"message": f"Custom endpoint for {actor.id}"}

**Key Benefits:**

- **Same auth as built-in handlers**: Bearer tokens, OAuth2, Basic auth
- **Framework agnostic**: Works with FastAPI, Flask, Django, etc.
- **Proper error handling**: 401s, OAuth2 redirects, WWW-Authenticate headers
- **Security**: Validates users can only access their own actor data

See the full documentation in :doc:`../guides/authentication` under "Custom Route Authentication".

Async Peer Communication
------------------------

``AwProxy`` provides async methods for non-blocking HTTP calls to peer actors in FastAPI routes:

.. code-block:: python

   from actingweb.aw_proxy import AwProxy

   @fastapi_app.get("/{actor_id}/custom/peer-data")
   async def get_peer_data(actor_id: str, peer_id: str):
       config = app.get_config()
       proxy = AwProxy(
           peer_target={"id": actor_id, "peerid": peer_id},
           config=config
       )

       if not proxy.trust:
           raise HTTPException(status_code=404, detail="No trust relationship")

       # Non-blocking call to peer
       result = await proxy.get_resource_async(path="properties/public")

       if proxy.last_response_code != 200:
           raise HTTPException(status_code=502, detail="Failed to reach peer")

       return result

**Available async methods:**

- ``get_resource_async(path, params)`` - GET request
- ``create_resource_async(path, params)`` - POST request
- ``change_resource_async(path, params)`` - PUT request
- ``delete_resource_async(path)`` - DELETE request

Migration
---------

The legacy ``OnAWBase`` interface was removed in v3.1. Use the modern hook system and see :doc:`../migration/v3.1` for guidance.
