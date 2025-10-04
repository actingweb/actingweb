===============
Advanced Topics
===============

Access Core Components
----------------------

.. code-block:: python

   core_actor = actor.core_actor
   core_props = actor.properties.core_store
   config = app.get_config()

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

See the full documentation in :doc:`../authentication-system` under "Custom Route Authentication".

Migration
---------

The legacy ``OnAWBase`` interface was removed in v3.1. Use the modern hook system and see :doc:`../migration-v3.1` for guidance.
