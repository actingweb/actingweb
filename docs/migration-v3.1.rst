===============================
ActingWeb v3.1 Migration Guide
===============================

This guide helps you migrate from the legacy OnAWBase interface (removed in v3.1) to the modern ActingWebApp interface.

Overview of Changes
===================

Version 3.1 represents a major architectural change:

- **Removed**: Legacy ``OnAWBase`` interface completely
- **Removed**: ``actingweb.on_aw`` module and ``OnAWBase`` class  
- **Removed**: ``ActingWebBridge`` compatibility layer
- **Changed**: Handler constructors now accept ``hooks: HookRegistry`` instead of ``on_aw: OnAWBase``
- **Required**: Applications must now use the modern ``ActingWebApp`` interface exclusively

Migration Steps
===============

Step 1: Replace OnAWBase Class
-------------------------------

**Before (Legacy - NO LONGER SUPPORTED):**

.. code-block:: python

    from actingweb.on_aw import OnAWBase
    
    class MyApp(OnAWBase):
        def get_properties(self, path, data):
            # Hide sensitive properties
            if path and path[0] == "email":
                return None
            return data
        
        def post_callbacks(self, name):
            if name == "webhook":
                # Handle webhook
                return True
            return False

**After (Modern Interface - REQUIRED):**

.. code-block:: python

    from actingweb.interface import ActingWebApp
    
    app = ActingWebApp("my-app", "dynamodb", "myapp.com")
    
    @app.property_hook("email")
    def hide_email_property(actor, operation, value, path):
        if operation == "get":
            return None  # Hide email from external access
        return value
    
    @app.callback_hook("webhook")
    def handle_webhook(actor, name, data):
        # Handle webhook
        return {"status": "processed"}

Step 2: Update Handler Instantiation
------------------------------------

**Before:**

.. code-block:: python

    from myapp import MyApp
    
    my_onaw = MyApp()
    handler = SomeHandler(webobj, config, on_aw=my_onaw)

**After:**

.. code-block:: python

    # Use the same app instance created above
    handler = SomeHandler(webobj, config, hooks=app.hooks)

Step 3: Update Flask Integration
-------------------------------

**Before:**

.. code-block:: python

    from flask import Flask
    from actingweb.interface.integrations.flask_integration import FlaskIntegration
    from actingweb.interface.bridge import ActingWebBridge
    
    flask_app = Flask(__name__)
    aw_app = ActingWebApp(...)
    bridge = ActingWebBridge(aw_app)
    integration = FlaskIntegration(aw_app, flask_app)

**After:**

.. code-block:: python

    from flask import Flask
    
    flask_app = Flask(__name__)
    aw_app = ActingWebApp(...)
    integration = aw_app.integrate_flask(flask_app)

Hook Type Mapping
=================

The new interface uses focused hook functions instead of monolithic class methods:

OnAWBase Method Mapping
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Legacy OnAWBase Method
     - Modern Hook Equivalent
   * - ``get_properties(path, data)``
     - ``@app.property_hook("prop_name")``
   * - ``put_properties(path, old, new)``
     - ``@app.property_hook("prop_name")``
   * - ``post_properties(prop, data)``
     - ``@app.property_hook("prop_name")``
   * - ``delete_properties(path, old, new)``
     - ``@app.property_hook("prop_name")``
   * - ``get_callbacks(name)``
     - ``@app.callback_hook("callback_name")``
   * - ``post_callbacks(name)``
     - ``@app.callback_hook("callback_name")``  
   * - ``delete_callbacks(name)``
     - ``@app.callback_hook("callback_name")``
   * - ``bot_post(path)``
     - ``@app.app_callback_hook("bot")``
   * - ``post_subscriptions(sub, peerid, data)``
     - ``@app.subscription_hook``
   * - ``delete_actor()``
     - ``@app.lifecycle_hook("actor_deleted")``
   * - ``actions_on_oauth_success()``
     - ``@app.lifecycle_hook("oauth_success")``
   * - ``get_methods(name)``
     - ``@app.method_hook("method_name")``
   * - ``post_methods(name, data)``
     - ``@app.method_hook("method_name")``
   * - ``get_actions(name)``
     - ``@app.action_hook("action_name")``
   * - ``post_actions(name, data)``
     - ``@app.action_hook("action_name")``

Hook Function Signatures
=========================

Property Hooks
--------------

.. code-block:: python

    @app.property_hook("property_name")
    def handle_property(actor: ActorInterface, operation: str, value: Any, path: List[str]) -> Any:
        # operation is one of: "get", "put", "post", "delete"
        if operation == "get":
            return value  # Transform or return None to reject
        elif operation == "put":
            return value  # Transform or return None to reject
        # ... handle other operations
        return value

Callback Hooks
--------------

.. code-block:: python

    @app.callback_hook("callback_name")
    def handle_callback(actor: ActorInterface, name: str, data: Dict[str, Any]) -> Union[bool, Dict[str, Any]]:
        # Process callback
        return {"result": "processed"}  # or True/False

Application-Level Callback Hooks
--------------------------------

.. code-block:: python

    @app.app_callback_hook("bot")
    def handle_bot(data: Dict[str, Any]) -> Union[bool, Dict[str, Any]]:
        # No actor context - this is application-level
        return True

Method Hooks
-----------

.. code-block:: python

    @app.method_hook("method_name")
    def handle_method(actor: ActorInterface, name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Process method call
        return {"result": "success"}

Action Hooks
-----------

.. code-block:: python

    @app.action_hook("action_name")
    def handle_action(actor: ActorInterface, name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Process action
        return {"status": "executed"}

Lifecycle Hooks
---------------

.. code-block:: python

    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs) -> None:
        # Initialize new actor
        actor.properties.created_at = str(datetime.now())
    
    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor: ActorInterface, **kwargs) -> None:
        # Clean up before deletion
        pass

Subscription Hooks
-----------------

.. code-block:: python

    @app.subscription_hook
    def handle_subscription(actor: ActorInterface, subscription: Dict[str, Any], peer_id: str, data: Dict[str, Any]) -> bool:
        # Process subscription callback
        return True

Benefits of Migration
====================

The new interface provides significant advantages:

**Code Reduction**
    - 95% less boilerplate code
    - Focused, single-purpose functions instead of monolithic classes

**Better Developer Experience**
    - Better type safety and IDE support  
    - Easier testing and debugging
    - Self-documenting hook decorators

**Architecture Benefits**
    - Single source of truth for application logic
    - No more dual interface maintenance
    - Improved runtime performance without bridge layer overhead
    - Clean separation of concerns

**Maintainability**
    - Much simpler debugging without bridge layer abstraction
    - Direct hook execution in handlers
    - Eliminated potential for interface synchronization issues

Common Migration Issues
======================

Type Errors
----------

If you encounter type errors, ensure hook function signatures match exactly:

.. code-block:: python

    # Correct signature
    @app.property_hook("email")
    def handle_email(actor: ActorInterface, operation: str, value: Any, path: List[str]) -> Any:
        return value

Missing Imports
--------------

Update your imports:

.. code-block:: python

    # Remove these imports
    # from actingweb.on_aw import OnAWBase
    # from actingweb.interface.bridge import ActingWebBridge
    
    # Use these instead
    from actingweb.interface import ActingWebApp, ActorInterface

Handler Parameters
-----------------

Ensure all handler instantiations use the new parameter:

.. code-block:: python

    # Old: on_aw=my_onaw_instance  
    # New: hooks=app.hooks
    handler = MyHandler(webobj, config, hooks=app.hooks)

Need Help?
==========

If you encounter issues during migration:

1. Check that all hook function signatures match the documented patterns
2. Ensure you're using ``hooks=app.hooks`` in handler constructors
3. Verify that property hooks return appropriate values (``None`` to reject operations)
4. Review the ActingWeb demo application for complete examples

The migration is straightforward and results in much cleaner, more maintainable code!