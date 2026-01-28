==========================================
Logging and Request Correlation
==========================================

ActingWeb provides comprehensive logging capabilities with automatic request correlation, making it easy to trace requests across distributed actor-to-actor communication.

.. contents:: Table of Contents
   :local:
   :depth: 2

Overview
========

ActingWeb's logging system automatically adds context to every log statement:

- **Request ID**: Unique identifier for each request
- **Actor ID**: The actor handling the request
- **Peer ID**: The peer making the request (when authenticated)

This context appears in every log line, enabling easy grepping and request tracing.

Quick Start
===========

Basic Configuration
-------------------

.. code-block:: python

    from actingweb.logging_config import configure_actingweb_logging
    import logging

    # Development: verbose logging
    configure_actingweb_logging(logging.DEBUG)

    # Production: minimal logging
    configure_actingweb_logging(logging.WARNING, db_level=logging.ERROR)

With Context Filter (Recommended)
----------------------------------

.. code-block:: python

    from actingweb.logging_config import (
        configure_actingweb_logging,
        enable_request_context_filter
    )
    import logging

    # Configure base logging
    configure_actingweb_logging(logging.INFO)

    # Enable automatic context injection
    enable_request_context_filter()

After enabling the context filter, all log statements automatically include request context:

.. code-block:: python

    import logging
    logger = logging.getLogger(__name__)

    # This simple log statement...
    logger.info("Property updated")

    # ...produces this output:
    # 2024-01-15 10:23:45,123 [a1b2c3d4:actor123:peer456] myapp.handlers:INFO: Property updated

Log Format
==========

Default Format
--------------

When the context filter is enabled, logs use this format::

    %(asctime)s %(context)s %(name)s:%(levelname)s: %(message)s

Example output::

    2024-01-15 10:23:45,123 [a1b2c3d4:actor123:peer456] actingweb.handlers.properties:INFO: Property 'email' updated
    2024-01-15 10:23:45,456 [a1b2c3d4:actor123:peer456] actingweb.auth:DEBUG: Checking authentication

Context Format
--------------

The ``%(context)s`` field shows::

    [short_request_id:actor_id:short_peer_id]

Where:

- **short_request_id**: Last 8 characters of the request UUID (sufficient for correlation)
- **actor_id**: Full actor identifier
- **short_peer_id**: Last segment after final colon in peer ID
- **-**: Used when a field is not available

Examples::

    [a1b2c3d4:actor123:peer456]    # Authenticated peer request
    [a1b2c3d4:actor123:-]          # Creator/trustee request (no peer)
    [-:actor123:-]                 # No request context set

Request Correlation
===================

How It Works
------------

ActingWeb automatically tracks requests through multiple layers:

1. **Incoming Requests**: Extract or generate request ID from ``X-Request-ID`` header
2. **Request Context**: Store request ID, actor ID, and peer ID in thread-local context
3. **Logging**: Automatically inject context into every log statement
4. **Outgoing Requests**: Propagate request IDs to peer actors with parent tracking

Request Flow Example
--------------------

When Actor A calls Actor B, which then calls Actor C:

.. code-block:: text

    Client → Actor A (request_id: UUID-A)
      ├─ Actor A logs: [UUID-A:actorA:-]
      └─ Actor A → Actor B
           ├─ Headers: X-Request-ID: UUID-B, X-Parent-Request-ID: UUID-A
           ├─ Actor B logs: [UUID-B:actorB:actorA]
           └─ Actor B → Actor C
                ├─ Headers: X-Request-ID: UUID-C, X-Parent-Request-ID: UUID-B
                └─ Actor C logs: [UUID-C:actorC:actorB]

This creates a traceable chain: UUID-A → UUID-B → UUID-C

Peer-to-Peer Correlation
-------------------------

When actors communicate, ActingWeb automatically:

1. Generates a new request ID for the outgoing request
2. Includes the current request ID as the parent
3. Logs the correlation for debugging

Example from ``actingweb.aw_proxy``::

    DEBUG actingweb.aw_proxy:aw_proxy.py:113 Peer request correlation: new_id=fa5959b7... parent_id=a1b2c3d4...

Grepping Logs
=============

The context format makes it easy to filter logs using standard tools.

Find All Logs for a Request
----------------------------

.. code-block:: bash

    # Find all logs for request ID starting with "a1b2c3d4"
    grep "a1b2c3d4" application.log

Example output::

    2024-01-15 10:23:45,123 [a1b2c3d4:actor123:peer456] actingweb.handlers:INFO: Request received
    2024-01-15 10:23:45,234 [a1b2c3d4:actor123:peer456] actingweb.auth:DEBUG: Authentication successful
    2024-01-15 10:23:45,345 [a1b2c3d4:actor123:peer456] actingweb.handlers:INFO: Property updated

Find All Logs for an Actor
---------------------------

.. code-block:: bash

    # Find all logs for a specific actor
    grep ":actor123:" application.log

Find All Logs for Actor-Peer Interaction
-----------------------------------------

.. code-block:: bash

    # Find logs for specific actor-peer combination
    grep ":actor123:peer456" application.log

Trace Request Chains
--------------------

To trace a complete request chain across actors:

.. code-block:: bash

    # Step 1: Find logs for the parent request
    grep "a1b2c3d4" application.log

    # Step 2: Look for child requests in peer logs
    grep "parent_id=a1b2c3d4" application.log

    # Step 3: Find the child request ID and repeat
    grep "new_id=fa5959b7" application.log

Advanced Filtering
------------------

Combine grep patterns for precise filtering:

.. code-block:: bash

    # Find ERROR logs for a specific request
    grep "a1b2c3d4" application.log | grep "ERROR"

    # Find all property operations for an actor
    grep ":actor123:" application.log | grep "properties"

    # Find authentication logs for peer requests
    grep "peer456" application.log | grep "auth"

Configuration Options
=====================

Convenience Functions
---------------------

ActingWeb provides pre-configured logging setups:

.. code-block:: python

    from actingweb.logging_config import (
        configure_production_logging,
        configure_development_logging,
        configure_testing_logging
    )

    # Production: WARNING level, minimal output
    configure_production_logging()

    # Development: DEBUG level, verbose output
    configure_development_logging()

    # Testing: WARNING level, suppress most output
    configure_testing_logging()

Per-Logger Configuration
------------------------

Control logging levels for specific components:

.. code-block:: python

    configure_actingweb_logging(
        level=logging.INFO,            # Default level
        db_level=logging.WARNING,      # Database operations
        auth_level=logging.INFO,       # Authentication
        handlers_level=logging.INFO,   # Request handlers
        proxy_level=logging.DEBUG      # Peer communication
    )

Environment Variables
---------------------

Configure logging via environment variables:

.. code-block:: bash

    # Set default log level
    export ACTINGWEB_LOG_LEVEL=INFO

    # Set database log level
    export ACTINGWEB_DB_LOG_LEVEL=WARNING

Performance Considerations
--------------------------

Context injection has minimal overhead:

- Setting context: ~1-2 microseconds per request
- Getting context: ~0.5 microseconds per log statement
- Filter processing: ~2-3 microseconds per log statement

**Total impact: <1% for typical INFO-level logging**

Best Practices for Production
------------------------------

1. **Use WARNING level** for default logging:

   .. code-block:: python

       configure_actingweb_logging(logging.WARNING)

2. **Suppress verbose loggers**:

   .. code-block:: python

       configure_actingweb_logging(
           level=logging.INFO,
           db_level=logging.ERROR,      # Database very verbose
           auth_level=logging.WARNING,   # Auth moderately verbose
           proxy_level=logging.WARNING   # Proxy moderately verbose
       )

3. **Enable context filter** for easier debugging:

   .. code-block:: python

       enable_request_context_filter()

Integration with Frameworks
============================

Flask Integration
-----------------

ActingWeb's Flask integration automatically manages request context:

.. code-block:: python

    from actingweb.interface import ActingWebApp
    from actingweb.interface.integrations.flask_integration import FlaskIntegration
    from flask import Flask

    flask_app = Flask(__name__)
    aw_app = ActingWebApp(...)

    # Context is automatically managed
    integration = FlaskIntegration(aw_app, flask_app)

Context lifecycle:

1. **Before request**: Extract/generate request ID, extract actor ID from URL
2. **During request**: Context available in all log statements
3. **After request**: Add ``X-Request-ID`` to response headers, clear context

FastAPI Integration
-------------------

ActingWeb's FastAPI integration uses middleware for async context:

.. code-block:: python

    from actingweb.interface import ActingWebApp
    from actingweb.interface.integrations.fastapi_integration import FastAPIIntegration
    from fastapi import FastAPI

    fastapi_app = FastAPI()
    aw_app = ActingWebApp(...)

    # Context automatically managed via middleware
    integration = FastAPIIntegration(aw_app, fastapi_app)

Context is automatically propagated across ``await`` boundaries.

Manual Context Management
--------------------------

For custom integrations, manage context manually:

.. code-block:: python

    from actingweb import request_context

    # Set up context at request start
    request_context.set_request_context(
        request_id="550e8400-e29b-41d4-a716-446655440000",
        actor_id="actor123"
    )

    # During authentication, add peer ID
    request_context.set_peer_id("peer456")

    # Clear context at request end
    request_context.clear_request_context()

Context API
-----------

Available context functions:

.. code-block:: python

    from actingweb import request_context

    # Set full context
    request_context.set_request_context(
        request_id="uuid",
        actor_id="actor123",
        peer_id="peer456"  # Optional
    )

    # Set individual fields
    request_context.set_request_id("uuid")
    request_context.set_actor_id("actor123")
    request_context.set_peer_id("peer456")

    # Get context
    request_id = request_context.get_request_id()
    actor_id = request_context.get_actor_id()
    peer_id = request_context.get_peer_id()

    # Generate new request ID
    new_id = request_context.generate_request_id()

    # Clear all context
    request_context.clear_request_context()

Troubleshooting
===============

No Context in Logs
------------------

**Problem**: Log statements don't show context information.

**Solution**: Enable the context filter:

.. code-block:: python

    from actingweb.logging_config import enable_request_context_filter
    enable_request_context_filter()

Context Shows Dashes
--------------------

**Problem**: Context shows ``[-:-:-]`` or similar.

**Explanation**: This means context fields are not set:

- ``[-:-:-]``: No context set at all
- ``[uuid:-:-]``: Request ID set, but no actor or peer
- ``[uuid:actor:-]``: No peer ID (normal for creator/trustee requests)

**Solution**: Ensure context is set at request start. For framework integrations, this happens automatically.

Context Not Cleared Between Requests
-------------------------------------

**Problem**: Context from previous request appears in new request.

**Solution**: Ensure ``clear_request_context()`` is called at request end. Framework integrations do this automatically in their cleanup hooks.

Missing Parent Request ID
--------------------------

**Problem**: Peer request logs don't show parent request ID.

**Explanation**: Parent request ID only appears when:

1. A request context exists (parent request)
2. That request makes a peer-to-peer call

**Solution**: Normal behavior. Requests without a parent context won't have a parent ID.

Examples
========

Complete Flask Application
--------------------------

.. code-block:: python

    from flask import Flask
    from actingweb.interface import ActingWebApp
    from actingweb.interface.integrations.flask_integration import FlaskIntegration
    from actingweb.logging_config import (
        configure_actingweb_logging,
        enable_request_context_filter
    )
    import logging

    # Configure logging
    configure_actingweb_logging(logging.INFO, db_level=logging.WARNING)
    enable_request_context_filter()

    # Set up Flask and ActingWeb
    flask_app = Flask(__name__)
    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:example.com:myapp",
            database="dynamodb",
            fqdn="myapp.example.com",
            proto="https://"
        )
        .with_oauth(client_id="...", client_secret="...")
        .with_web_ui(enable=True)
    )

    # Context is automatically managed
    integration = FlaskIntegration(aw_app, flask_app)

    if __name__ == "__main__":
        flask_app.run()

Custom Context in Request Handler
----------------------------------

.. code-block:: python

    import logging
    from actingweb import request_context

    logger = logging.getLogger(__name__)

    def my_handler(actor_id, data):
        # Context is already set by framework integration
        logger.info("Processing request")  # Shows context automatically

        # Make peer request (correlation automatic)
        from actingweb.aw_proxy import AwProxy
        proxy = AwProxy(peer_target={"id": actor_id, "peerid": "peer123"}, config=config)
        result = proxy.get_resource(path="resource")

        logger.info("Request completed")
        return result

Log Analysis Script
-------------------

.. code-block:: bash

    #!/bin/bash
    # analyze_request.sh - Trace a request through logs

    REQUEST_ID=$1

    echo "=== Request: $REQUEST_ID ==="
    echo ""

    echo "Main request logs:"
    grep "$REQUEST_ID" application.log

    echo ""
    echo "Child requests:"
    grep "parent_id=${REQUEST_ID:0:8}" application.log | \
        sed -n 's/.*new_id=\([a-f0-9]*\).*/\1/p' | \
        while read child_id; do
            echo "  Child: $child_id"
            grep "$child_id" application.log | head -3
        done

See Also
========

- :doc:`../quickstart/configuration` - General configuration guide
- :doc:`authentication` - Authentication and authorization
- :doc:`../reference/actingweb` - Full API reference including request_context and logging_config modules
