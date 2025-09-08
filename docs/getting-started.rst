Getting Started
===============

This is a longer, step‑by‑step tutorial that builds on the short Quickstart. If you’re new to ActingWeb, do the Quickstart first (minimal Flask/FastAPI app, create an actor), then come back here for deeper patterns, hooks, and integration details.

The easiest way to get started is to use the modern ActingWeb interface that provides a clean, fluent API for building ActingWeb applications. For a complete example, see the actingwebdemo mini-application at `http://acting-web-demo.readthedocs.io/ <http://acting-web-demo.readthedocs.io/>`_.

Quick Start
-----------

Create a basic ActingWeb application:

.. code-block:: python

    from actingweb.interface import ActingWebApp, ActorInterface

    # Create app with fluent configuration
    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    ).with_web_ui().with_devtest()

    # Initialize actors after creation
    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor: ActorInterface, **kwargs):
        # Set the creator email as a property
        actor.properties.email = actor.creator

    # Add property hooks
    @app.property_hook("email")
    def handle_email(actor, operation, value, path):
        if operation == "put":
            return value.lower() if "@" in value else None
        return value

    # Run the application
    app.run(port=5000)

Flask Integration
-----------------

For production applications, integrate with Flask:

.. code-block:: python

    from flask import Flask
    from actingweb.interface import ActingWebApp

    # Create Flask app
    flask_app = Flask(__name__)

    # Create ActingWeb app
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com"
    ).with_oauth(
        client_id="your-client-id",
        client_secret="your-client-secret"
    ).with_web_ui()

    # Integrate with Flask (auto-generates all routes)
    aw_app.integrate_flask(flask_app)

    if __name__ == "__main__":
        flask_app.run()

FastAPI Integration (non‑MCP)
-----------------------------

If you prefer FastAPI and do not need MCP features:

.. code-block:: python

    from fastapi import FastAPI
    from actingweb.interface import ActingWebApp

    app = FastAPI()

    aw = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
    ).with_web_ui(enable=True)

    # Explicitly disable MCP exposure for this app
    aw.with_mcp(enable=False)

    # Auto-generate all ActingWeb routes under the FastAPI app
    aw.integrate_fastapi(app, templates_dir="templates")

    # Run with: uvicorn main:app --reload

How it works
------------

An ActingWeb mini-application exposes an endpoint to create a new actor representing one instance on behalf of one person or entity. This could for example be the location of a mobile phone, and the app is thus a location app. The ActingWeb actor representing one mobile phone's location can be reached on https://app-url.a-domain.io/actor-id and all the ActingWeb endpoints to get the location, subscribe to location updates and so on can be found below this actor root URL.

The modern interface automatically generates all the necessary routes and handles request/response transformation. You no longer need to manually define routes or handle complex request parsing.

Actor Management
----------------

Creating and managing actors is straightforward:

.. code-block:: python

    # Create a new actor
    actor = ActorInterface.create(creator="user@example.com", config=config)

    # Access properties
    actor.properties.email = "user@example.com"
    actor.properties.status = "active"

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

    # Notify subscribers of changes
    actor.subscriptions.notify_subscribers(
        target="properties",
        data={"status": "active"}
    )

Configuration
-------------

The modern interface uses a fluent configuration API that's much simpler than the old approach:

.. code-block:: python

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )

    # Chain configuration methods
    app.with_oauth(
        client_id="your-client-id",
        client_secret="your-client-secret",
        scope="read write"
    ).with_web_ui(enable=True
    ).with_devtest(enable=True
    ).with_bot(
        token="bot-token",
        email="bot@example.com"
    ).with_unique_creator(enable=True
    ).add_actor_type("myself", relationship="friend")

All Configuration Options
--------------------------

The ``ActingWebApp`` constructor accepts these parameters:

- ``aw_type``: The ActingWeb type URI (required)
- ``database``: Database backend ("dynamodb", default)
- ``fqdn``: Fully qualified domain name (required)
- ``proto``: Protocol ("https://", default)

Configuration methods:

- ``.with_oauth(client_id, client_secret, scope, ...)`` - Configure OAuth authentication
- ``.with_web_ui(enable=True)`` - Enable/disable web UI at /www
- ``.with_devtest(enable=True)`` - Enable/disable development endpoints (MUST be False in production)
- ``.with_bot(token, email, secret, admin_room)`` - Configure bot integration
- ``.with_unique_creator(enable=True)`` - Enforce unique creator field
- ``.with_email_as_creator(enable=True)`` - Use email property as creator
- ``.add_actor_type(name, factory, relationship)`` - Add known actor type

Customizing Behavior with Hooks
--------------------------------

The modern interface uses a hook system instead of the old ``OnAWBase`` class. Hooks are focused functions that handle specific events:

Property Hooks
~~~~~~~~~~~~~~

Handle property access and validation:

.. code-block:: python

    @app.property_hook("email")
    def handle_email_property(actor, operation, value, path):
        if operation == "get":
            # Control who can see the email
            return value if actor.is_owner() else None
        elif operation == "put":
            # Validate email format
            return value.lower() if "@" in value else None
        return value

    @app.property_hook("settings")
    def handle_settings_property(actor, operation, value, path):
        if operation == "put" or operation == "post":
            # Ensure settings is always a dict
            if isinstance(value, str):
                import json
                try:
                    return json.loads(value)
                except:
                    return None
            return value if isinstance(value, dict) else {}
        return value

Callback Hooks
~~~~~~~~~~~~~~

Handle custom endpoints and bot integration:

.. code-block:: python

    @app.callback_hook("bot")
    def handle_bot_callback(actor, name, data):
        if data.get("method") == "POST":
            # Process bot request
            body = data.get("body", {})
            # Handle bot integration logic
            return True
        return False

    @app.callback_hook("status")
    def handle_status_callback(actor, name, data):
        if data.get("method") == "GET":
            return {
                "status": "active",
                "actor_id": actor.id,
                "last_seen": str(datetime.now())
            }
        return False

Subscription Hooks
~~~~~~~~~~~~~~~~~~

Handle subscription callbacks from other actors:

.. code-block:: python

    @app.subscription_hook
    def handle_subscription_callback(actor, subscription, peer_id, data):
        print(f"Received subscription callback from {peer_id}: {data}")
        
        # Process the subscription data
        if subscription.get("target") == "properties":
            # Handle property changes from peer
            if "status" in data:
                actor.properties[f"peer_{peer_id}_status"] = data["status"]
                
        return True

Lifecycle Hooks
~~~~~~~~~~~~~~~

Handle actor lifecycle events:

.. code-block:: python

    @app.lifecycle_hook("actor_created")
    def on_actor_created(actor, **kwargs):
        # Initialize new actor
        actor.properties.created_at = str(datetime.now())
        actor.properties.version = "1.0"

    @app.lifecycle_hook("actor_deleted")
    def on_actor_deleted(actor, **kwargs):
        # Cleanup before deletion
        print(f"Actor {actor.id} is being deleted")

    @app.lifecycle_hook("oauth_success")
    def on_oauth_success(actor, **kwargs):
        token = kwargs.get("token")
        if token:
            actor.properties.oauth_token = token

Migration from Legacy Interface
---------------------------------

.. warning::
   **Breaking Change in v3.1**: The legacy ``OnAWBase`` interface has been completely removed.
   
   If you're migrating from the old interface, all code using ``OnAWBase`` must be updated 
   to use the modern hook system. See :doc:`migration-v3.1` for detailed migration instructions.

The modern hook system provides better organization, type safety, and testing capabilities compared to the legacy interface.

Database Configuration
-----------------------

ActingWeb currently supports DynamoDB as the database backend. For local development, you can use DynamoDB Local:

.. code-block:: python

    app = ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="localhost:5000"
    )

For production, ensure your AWS credentials are properly configured and DynamoDB tables are created with the appropriate permissions.

For DynamoDB Local, set the following environment variables before running your app:

.. code-block:: bash

    export AWS_ACCESS_KEY_ID=local
    export AWS_SECRET_ACCESS_KEY=local
    export AWS_DEFAULT_REGION=us-east-1
    export AWS_DB_HOST=http://localhost:8000

Testing
-------

The modern interface makes testing much easier:

.. code-block:: python

    import unittest
    from actingweb.interface import ActingWebApp, ActorInterface

    class TestMyApp(unittest.TestCase):
        def setUp(self):
            self.app = ActingWebApp(
                aw_type="urn:test:example.com:test",
                database="dynamodb"
            )

        def test_actor_creation(self):
            actor = ActorInterface.create(
                creator="test@example.com", 
                config=self.app.get_config()
            )
            self.assertIsNotNone(actor.id)
            self.assertEqual(actor.creator, "test@example.com")

        def test_property_hook(self):
            @self.app.property_hook("email")
            def handle_email(actor, operation, value, path):
                return value.lower() if operation == "put" else value

            # Test hook directly
            actor = ActorInterface.create(
                creator="test@example.com", 
                config=self.app.get_config()
            )
            result = handle_email(actor, "put", "TEST@EXAMPLE.COM", [])
            self.assertEqual(result, "test@example.com")

Deployment
----------

For production deployment, use standard Python deployment practices:

**Docker:**

.. code-block:: dockerfile

    FROM python:3.11-slim
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install -r requirements.txt
    COPY . .
    CMD ["python", "app.py"]

**AWS Lambda (Serverless):**

.. code-block:: python

    import serverless_wsgi
    from flask import Flask
    from actingweb.interface import ActingWebApp

    flask_app = Flask(__name__)
    aw_app = ActingWebApp(...).with_web_ui()
    aw_app.integrate_flask(flask_app)

    def handler(event, context):
        return serverless_wsgi.handle_request(flask_app, event, context)

**Kubernetes:**

.. code-block:: yaml

    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: actingweb-app
    spec:
      replicas: 3
      selector:
        matchLabels:
          app: actingweb-app
      template:
        metadata:
          labels:
            app: actingweb-app
        spec:
          containers:
          - name: actingweb-app
            image: myapp:latest
            ports:
            - containerPort: 5000

Next Steps
----------

1. See the :doc:`developers` guide for detailed API documentation
2. Check out the actingwebdemo application for a complete working example
3. Read the ActingWeb specification for protocol details
4. Join the ActingWeb community for support and discussion

The modern ActingWeb interface makes it easy to build distributed, actor-based applications with minimal boilerplate code while maintaining full compatibility with the ActingWeb protocol.
