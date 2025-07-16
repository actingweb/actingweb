============================
ActingWeb Developer Interface
============================

This document describes the modern developer interface for the ActingWeb library. It replaces the complex ``OnAWBase`` callback system with a clean, fluent API and decorator-based hooks.

Key Features
============

- **Fluent Configuration API**: Chain configuration methods for easy setup
- **Decorator-Based Hooks**: Simple, focused functions for handling events
- **Automatic Route Generation**: Web framework integration with auto-generated routes
- **Intuitive Actor Interface**: Clean, object-oriented actor management
- **Type Safety**: Better type hints and IDE support
- **Backward Compatibility**: Works with existing ActingWeb applications

Quick Start
===========

Basic Application
-----------------

.. code-block:: python

    from actingweb.interface import ActingWebApp, ActorInterface

    # Create app with fluent configuration
    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    ).with_oauth(
        client_id="your-client-id",
        client_secret="your-client-secret"
    ).with_web_ui().with_devtest()

    # Define actor factory
    @app.actor_factory
    def create_actor(creator: str, **kwargs) -> ActorInterface:
        actor = ActorInterface.create(creator=creator, config=app.get_config())
        actor.properties.email = creator
        return actor

    # Add hooks
    @app.property_hook("email")
    def handle_email(actor, operation, value, path):
        if operation == "get":
            return value if actor.is_owner() else None
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

    # Run the application
    app.run(port=5000)

Flask Integration
-----------------

.. code-block:: python

    from flask import Flask
    from actingweb.interface import ActingWebApp

    # Create Flask app
    flask_app = Flask(__name__)

    # Create ActingWeb app
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb"
    ).with_web_ui()

    # Integrate with Flask (auto-generates all routes)
    aw_app.integrate_flask(flask_app)

    # Run Flask app
    flask_app.run()

Core Components
===============

ActingWebApp
------------

The main application class that provides fluent configuration:

.. code-block:: python

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    )

    # Configuration methods
    app.with_oauth(client_id="...", client_secret="...")
    app.with_web_ui(enable=True)
    app.with_devtest(enable=True)
    app.with_bot(token="...", email="...")
    app.with_unique_creator(enable=True)
    app.add_actor_type("myself", relationship="friend")

Configuration Methods
~~~~~~~~~~~~~~~~~~~~~

.. py:method:: with_oauth(client_id, client_secret, scope="", auth_uri="", token_uri="", **kwargs)

    Configure OAuth authentication.

    :param client_id: OAuth client ID
    :param client_secret: OAuth client secret
    :param scope: OAuth scope (optional)
    :param auth_uri: Authorization URI (optional)
    :param token_uri: Token URI (optional)
    :param kwargs: Additional OAuth parameters
    :return: ActingWebApp instance for chaining

.. py:method:: with_web_ui(enable=True)

    Enable or disable the web UI.

    :param enable: Whether to enable web UI
    :return: ActingWebApp instance for chaining

.. py:method:: with_devtest(enable=True)

    Enable or disable development/testing endpoints.

    :param enable: Whether to enable devtest endpoints
    :return: ActingWebApp instance for chaining

.. py:method:: with_bot(token="", email="", secret="", admin_room="")

    Configure bot integration.

    :param token: Bot token
    :param email: Bot email
    :param secret: Bot secret
    :param admin_room: Admin room ID
    :return: ActingWebApp instance for chaining

ActorInterface
--------------

Clean interface for working with actors:

.. code-block:: python

    # Create actor
    actor = ActorInterface.create(creator="user@example.com", config=config)

    # Access properties
    actor.properties.email = "user@example.com"
    actor.properties["settings"] = {"theme": "dark"}

    # Manage trust relationships
    peer = actor.trust.create_relationship(
        peer_url="https://peer.example.com/actor123",
        relationship="friend"
    )

    # Handle subscriptions
    actor.subscriptions.subscribe_to_peer(
        peer_id="peer123",
        target="properties"
    )

    # Notify subscribers
    actor.subscriptions.notify_subscribers(
        target="properties",
        data={"status": "active"}
    )

Class Methods
~~~~~~~~~~~~~

.. py:classmethod:: create(creator, config, actor_id=None, passphrase=None, delete_existing=False)

    Create a new actor.

    :param creator: Creator identifier (usually email)
    :param config: ActingWeb Config object
    :param actor_id: Optional custom actor ID
    :param passphrase: Optional custom passphrase
    :param delete_existing: Whether to delete existing actor with same creator
    :return: New ActorInterface instance

.. py:classmethod:: get_by_id(actor_id, config)

    Get an existing actor by ID.

    :param actor_id: Actor ID
    :param config: ActingWeb Config object
    :return: ActorInterface instance or None if not found

.. py:classmethod:: get_by_creator(creator, config)

    Get an existing actor by creator.

    :param creator: Creator identifier
    :param config: ActingWeb Config object
    :return: ActorInterface instance or None if not found

Properties
~~~~~~~~~~

.. py:attribute:: id

    Actor ID (read-only)

.. py:attribute:: creator

    Actor creator (read-only)

.. py:attribute:: url

    Actor URL (read-only)

.. py:attribute:: properties

    PropertyStore instance for property management

.. py:attribute:: trust

    TrustManager instance for trust relationship management

.. py:attribute:: subscriptions

    SubscriptionManager instance for subscription management

PropertyStore
-------------

Dictionary-like interface for actor properties:

.. code-block:: python

    # Set properties
    actor.properties.email = "user@example.com"
    actor.properties["config"] = {"theme": "dark"}

    # Get properties
    email = actor.properties.email
    config = actor.properties.get("config", {})

    # Check existence
    if "email" in actor.properties:
        print("Email is set")

    # Iterate
    for key, value in actor.properties.items():
        print(f"{key}: {value}")

Methods
~~~~~~~

.. py:method:: get(key, default=None)

    Get property value with default.

    :param key: Property key
    :param default: Default value if property doesn't exist
    :return: Property value or default

.. py:method:: set(key, value)

    Set property value.

    :param key: Property key
    :param value: Property value

.. py:method:: delete(key)

    Delete property.

    :param key: Property key
    :return: True if property existed and was deleted

.. py:method:: update(other)

    Update properties from dictionary.

    :param other: Dictionary of properties to update

.. py:method:: to_dict()

    Convert to dictionary.

    :return: Dictionary representation of all properties

TrustManager
------------

Simplified trust relationship management:

.. code-block:: python

    # Create relationship
    relationship = actor.trust.create_relationship(
        peer_url="https://peer.example.com/actor123",
        relationship="friend"
    )

    # List relationships
    for rel in actor.trust.relationships:
        print(f"Trust with {rel.peer_id}: {rel.relationship}")

    # Find specific relationship
    friend = actor.trust.find_relationship(relationship="friend")

    # Approve relationship
    actor.trust.approve_relationship(peer_id="peer123")

    # Check if peer is trusted
    if actor.trust.is_trusted_peer("peer123"):
        print("Peer is trusted")

Properties
~~~~~~~~~~

.. py:attribute:: relationships

    List of all trust relationships

.. py:attribute:: active_relationships

    List of active (approved and verified) relationships

.. py:attribute:: pending_relationships

    List of pending relationships

Methods
~~~~~~~

.. py:method:: create_relationship(peer_url, relationship="friend", secret="", description="")

    Create a new trust relationship with another actor.

    :param peer_url: URL of the peer actor
    :param relationship: Type of relationship (friend, partner, etc.)
    :param secret: Shared secret (auto-generated if not provided)
    :param description: Description of the relationship
    :return: TrustRelationship instance or None if failed

.. py:method:: get_relationship(peer_id)

    Get relationship with specific peer.

    :param peer_id: Peer actor ID
    :return: TrustRelationship instance or None if not found

.. py:method:: approve_relationship(peer_id)

    Approve a trust relationship.

    :param peer_id: Peer actor ID
    :return: True if successful

.. py:method:: delete_relationship(peer_id)

    Delete a trust relationship.

    :param peer_id: Peer actor ID
    :return: True if successful

.. py:method:: is_trusted_peer(peer_id)

    Check if peer is trusted (has active relationship).

    :param peer_id: Peer actor ID
    :return: True if peer is trusted

SubscriptionManager
-------------------

Easy subscription handling:

.. code-block:: python

    # Subscribe to peer
    subscription_url = actor.subscriptions.subscribe_to_peer(
        peer_id="peer123",
        target="properties",
        granularity="high"
    )

    # List subscriptions
    for sub in actor.subscriptions.all_subscriptions:
        print(f"Subscription to {sub.peer_id}: {sub.target}")

    # Notify subscribers
    actor.subscriptions.notify_subscribers(
        target="properties",
        data={"status": "active"}
    )

    # Unsubscribe
    actor.subscriptions.unsubscribe(
        peer_id="peer123",
        subscription_id="sub123"
    )

Properties
~~~~~~~~~~

.. py:attribute:: all_subscriptions

    List of all subscriptions (both inbound and outbound)

.. py:attribute:: outbound_subscriptions

    List of subscriptions to other actors

.. py:attribute:: inbound_subscriptions

    List of subscriptions from other actors

Methods
~~~~~~~

.. py:method:: subscribe_to_peer(peer_id, target, subtarget="", resource="", granularity="high")

    Subscribe to another actor's data.

    :param peer_id: Peer actor ID
    :param target: Target to subscribe to
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)
    :param granularity: Notification granularity (high, low, none)
    :return: Subscription URL if successful, None otherwise

.. py:method:: unsubscribe(peer_id, subscription_id)

    Unsubscribe from a peer's data.

    :param peer_id: Peer actor ID
    :param subscription_id: Subscription ID
    :return: True if successful

.. py:method:: notify_subscribers(target, data, subtarget="", resource="")

    Notify all subscribers of changes to the specified target.

    :param target: Target that changed
    :param data: Change data
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)

.. py:method:: has_subscribers_for(target, subtarget="", resource="")

    Check if there are any subscribers for the given target.

    :param target: Target to check
    :param subtarget: Subtarget (optional)
    :param resource: Resource (optional)
    :return: True if there are subscribers

Hook System
===========

Property Hooks
--------------

Handle property operations:

.. code-block:: python

    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        if operation == "get":
            return value if actor.is_owner() else None
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

    # Hook specific operations
    @app.property_hook("settings", operations=["put", "post"])
    def handle_settings_property(actor, operation, value, path):
        if isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except:
                return None
        return value

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: property_hook_function(actor, operation, value, path)

    Property hook function signature.

    :param actor: ActorInterface instance
    :param operation: Operation type ("get", "put", "post", "delete")
    :param value: Property value
    :param path: Property path as list
    :return: Transformed value or None to reject operation

Callback Hooks
--------------

Handle callback requests at both application and actor levels:

.. code-block:: python

    # Application-level callbacks (no actor context)
    @app.app_callback_hook("bot")
    def handle_bot_callback(data):
        if data.get("method") == "POST":
            # Process bot webhook (no actor context)
            return True
        return False

    # Actor-level callbacks (with actor context)
    @app.callback_hook("ping")
    def handle_ping_callback(actor, name, data):
        if data.get("method") == "GET":
            return {"status": "pong", "actor_id": actor.id}
        return False

    @app.callback_hook("status")
    def handle_status_callback(actor, name, data):
        return {"status": "active", "actor_id": actor.id}

Application-Level vs Actor-Level Callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Application-level callbacks** (``@app.app_callback_hook``):
- Used for endpoints like ``/bot``, ``/oauth``
- No actor context - these are application-wide endpoints
- Function signature: ``def callback(data) -> bool``

**Actor-level callbacks** (``@app.callback_hook``):
- Used for endpoints like ``/<actor_id>/callbacks/<name>``
- Have actor context - these are specific to individual actors
- Function signature: ``def callback(actor, name, data) -> bool``

Hook Function Signatures
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: app_callback_hook_function(data)

    Application-level callback hook function signature.

    :param data: Request data including method and body
    :return: True if processed, False otherwise, or dict for response data

.. py:function:: callback_hook_function(actor, name, data)

    Actor-level callback hook function signature.

    :param actor: ActorInterface instance
    :param name: Callback name
    :param data: Request data including method and body
    :return: True if processed, False otherwise, or dict for response data

Method Hooks
------------

Handle RPC-style method calls with JSON-RPC support:

.. code-block:: python

    # Simple method hook
    @app.method_hook("calculate")
    def handle_calculate(actor, method_name, data):
        a = data.get("a", 0)
        b = data.get("b", 0)
        operation = data.get("operation", "add")
        
        if operation == "add":
            result = a + b
        elif operation == "multiply":
            result = a * b
        else:
            return None  # Method not supported
            
        return {"result": result}

    # JSON-RPC method hook
    @app.method_hook("greet")
    def handle_greet(actor, method_name, data):
        name = data.get("name", "World")
        return {"greeting": f"Hello, {name}!"}

Method Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: method_hook_function(actor, method_name, data)

    Method hook function signature.

    :param actor: ActorInterface instance
    :param method_name: Method name being called
    :param data: Method parameters (for JSON-RPC, this is the "params" field)
    :return: Method result (will be wrapped in JSON-RPC response if applicable)

Action Hooks
------------

Handle trigger-based actions that execute external events:

.. code-block:: python

    # Action hook for notifications
    @app.action_hook("send_notification")
    def handle_send_notification(actor, action_name, data):
        message = data.get("message", "")
        recipient = data.get("recipient", "")
        
        # Execute external action (e.g., send email, trigger webhook)
        success = send_notification_email(recipient, message)
        
        return {
            "status": "sent" if success else "failed",
            "timestamp": datetime.now().isoformat()
        }

    # Action hook for device control
    @app.action_hook("toggle_light")
    def handle_toggle_light(actor, action_name, data):
        device_id = data.get("device_id")
        state = data.get("state", "on")
        
        # Control physical device
        result = control_iot_device(device_id, state)
        
        return {
            "device_id": device_id,
            "state": state,
            "success": result
        }

Action Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: action_hook_function(actor, action_name, data)

    Action hook function signature.

    :param actor: ActorInterface instance
    :param action_name: Action name being executed
    :param data: Action parameters
    :return: Action result (status information, execution results, etc.)

Subscription Hooks
------------------

Handle subscription callbacks:

.. code-block:: python

    @app.subscription_hook
    def handle_subscription_callback(actor, subscription, peer_id, data):
        print(f"Received data from {peer_id}: {data}")
        
        # Process the subscription data
        if subscription.get("target") == "properties":
            # Handle property changes from peer
            pass
            
        return True

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: subscription_hook_function(actor, subscription, peer_id, data)

    Subscription hook function signature.

    :param actor: ActorInterface instance
    :param subscription: Subscription information dict
    :param peer_id: Peer actor ID
    :param data: Subscription data
    :return: True if processed, False otherwise

Lifecycle Hooks
---------------

Handle actor lifecycle events:

.. code-block:: python

    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor, **kwargs):
        # Initialize new actor
        actor.properties.created_at = str(datetime.now())

    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor, **kwargs):
        # Cleanup before deletion
        print(f"Actor {actor.id} is being deleted")

    @app.lifecycle_hook("oauth_success")
    def on_oauth_success(actor, **kwargs):
        token = kwargs.get("token")
        if token:
            actor.properties.oauth_token = token

Available Lifecycle Events
~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``actor_created``: Called when a new actor is created
- ``actor_deleted``: Called when an actor is deleted
- ``oauth_success``: Called when OAuth authentication succeeds
- ``trust_approved``: Called when a trust relationship is approved
- ``trust_deleted``: Called when a trust relationship is deleted

Hook Function Signature
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: lifecycle_hook_function(actor, **kwargs)

    Lifecycle hook function signature.

    :param actor: ActorInterface instance
    :param kwargs: Event-specific parameters
    :return: Event-specific return value

Migration from OnAWBase
=======================

The new interface provides a clean migration path from the old ``OnAWBase`` system:

Before (OnAWBase)
-----------------

.. code-block:: python

    class OnAWDemo(on_aw.OnAWBase):
        def get_properties(self, path: list[str], data: dict) -> Optional[dict]:
            if not path:
                for k, v in data.copy().items():
                    if k in PROP_HIDE:
                        del data[k]
            elif len(path) > 0 and path[0] in PROP_HIDE:
                return None
            return data
        
        def put_properties(self, path: list[str], old: dict, new: Union[dict, str]) -> Optional[dict | str]:
            if not path:
                return None
            elif len(path) > 0 and path[0] in PROP_PROTECT:
                return None
            return new

After (New Interface)
---------------------

.. code-block:: python

    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        if operation == "get":
            return None if not actor.is_owner() else value
        elif operation == "put":
            return value.lower() if "@" in value else None
        return value

Benefits
========

1. **Reduced Boilerplate**: No more manual route definitions or complex handler setup
2. **Better Organization**: Hooks are focused on specific functionality
3. **Improved Readability**: Code is easier to understand and maintain
4. **Type Safety**: Better IDE support and error detection
5. **Flexibility**: Easy to add new hooks without modifying core classes
6. **Testing**: Hooks can be tested independently

Backward Compatibility
======================

The new interface is fully backward compatible with existing ActingWeb applications. You can:

1. Continue using the old ``OnAWBase`` system
2. Gradually migrate to the new interface
3. Mix both approaches during transition

The new interface uses a bridge pattern to translate between the hook system and the existing ``OnAWBase`` callbacks, ensuring seamless operation.

Advanced Usage
==============

Accessing Core Components
-------------------------

If you need access to the underlying ActingWeb components:

.. code-block:: python

    # Access core actor
    core_actor = actor.core_actor

    # Access core property store
    core_properties = actor.properties.core_store

    # Access configuration
    config = app.get_config()

Custom Web Framework Integration
--------------------------------

You can extend the integration system for other web frameworks:

.. code-block:: python

    from actingweb.interface.integrations import FlaskIntegration
    
    class FastAPIIntegration:
        def __init__(self, aw_app, fastapi_app):
            self.aw_app = aw_app
            self.fastapi_app = fastapi_app
            
        def setup_routes(self):
            # Implement FastAPI route setup
            pass

Error Handling
--------------

The new interface provides better error handling:

.. code-block:: python

    try:
        actor = ActorInterface.create(creator="user@example.com", config=config)
    except RuntimeError as e:
        print(f"Failed to create actor: {e}")
        
    # Hook error handling
    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        try:
            if operation == "put" and "@" not in value:
                return None  # Reject invalid email
            return value.lower() if operation == "put" else value
        except Exception as e:
            # Log error and reject operation
            print(f"Error in email hook: {e}")
            return None

Testing
=======

The new interface makes testing much easier:

.. code-block:: python

    import unittest
    from actingweb.interface import ActingWebApp, ActorInterface
    
    class TestActingWebApp(unittest.TestCase):
        def setUp(self):
            self.app = ActingWebApp(
                aw_type="urn:test:example.com:test",
                database="dynamodb"
            )
            
        def test_property_hook(self):
            @self.app.property_hook("email")
            def handle_email(actor, operation, value, path):
                return value.lower() if operation == "put" else value
                
            # Test the hook directly
            actor = ActorInterface.create(creator="test@example.com", config=self.app.get_config())
            result = handle_email(actor, "put", "TEST@EXAMPLE.COM", [])
            self.assertEqual(result, "test@example.com")
            
        def test_actor_creation(self):
            actor = ActorInterface.create(creator="test@example.com", config=self.app.get_config())
            self.assertIsNotNone(actor.id)
            self.assertEqual(actor.creator, "test@example.com")