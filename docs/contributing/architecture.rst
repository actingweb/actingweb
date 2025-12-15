======================
Codebase Architecture
======================

**Audience**: Contributors who want to understand the ActingWeb codebase structure.

This document provides an overview of the ActingWeb codebase architecture and module responsibilities.

Directory Structure
===================

.. code-block::

    actingweb/
    ├── __init__.py              # Package initialization
    ├── actor.py                 # Core Actor class
    ├── config.py                # Configuration management
    ├── property.py              # Property storage
    ├── trust.py                 # Trust relationships
    ├── subscription.py          # Event subscriptions
    ├── oauth.py                 # Legacy OAuth
    ├── oauth2.py                # OAuth2 implementation
    ├── aw_proxy.py              # Peer HTTP communication
    ├── aw_web_obj.py            # Web request/response abstraction
    ├── on_aw.py                 # Base hook class
    │
    ├── handlers/                # HTTP request handlers
    │   ├── base_handler.py      # Common handler functionality
    │   ├── properties.py        # Property endpoints
    │   ├── trust.py             # Trust endpoints
    │   ├── subscription.py      # Subscription endpoints
    │   ├── callbacks.py         # Callback endpoints
    │   ├── methods.py           # Method endpoints
    │   ├── actions.py           # Action endpoints
    │   ├── factory.py           # Actor creation
    │   ├── oauth.py             # OAuth endpoints
    │   ├── oauth2_callback.py   # OAuth2 callback
    │   ├── meta.py              # Actor metadata
    │   ├── www.py               # Web UI
    │   └── devtest.py           # Development/testing
    │
    ├── interface/               # Modern developer API
    │   ├── app.py               # ActingWebApp fluent API
    │   ├── actor_interface.py   # ActorInterface wrapper
    │   ├── property_store.py    # PropertyStore dict-like API
    │   ├── trust_manager.py     # TrustManager API
    │   ├── subscription_manager.py  # SubscriptionManager API
    │   ├── hook_registry.py     # Hook registration
    │   ├── authenticated_views.py   # Permission-enforced access
    │   └── integrations/        # Framework integrations
    │       ├── base_integration.py  # Shared integration logic
    │       ├── flask_integration.py # Flask support
    │       └── fastapi_integration.py # FastAPI support
    │
    └── db_dynamodb/             # DynamoDB backend
        ├── db_actor.py          # Actor storage
        ├── db_property.py       # Property storage
        ├── db_trust.py          # Trust storage
        └── db_subscription.py   # Subscription storage

Core Classes
============

Actor
-----

**File**: ``actingweb/actor.py``

The central class representing a user's instance. Responsibilities:

- Actor lifecycle (creation, deletion)
- Property storage access
- Trust relationship management
- Subscription management
- Peer communication

.. code-block:: python

    class Actor:
        id: str              # Unique actor ID
        config: Config       # Configuration
        property: Property   # Property storage

        def get_properties(self) -> Dict
        def set_property(self, name: str, value: Any)
        def get_trust_relationships(self) -> List[Dict]
        def create_trust(self, ...) -> Dict
        # ... async variants for peer communication

Config
------

**File**: ``actingweb/config.py``

Application-wide configuration. Responsibilities:

- Database configuration
- Authentication settings
- Feature toggles
- Actor type definitions

Property
--------

**File**: ``actingweb/property.py``

Low-level property storage. Responsibilities:

- CRUD operations on properties
- JSON serialization
- Database abstraction

Trust
-----

**File**: ``actingweb/trust.py``

Trust relationship storage. Responsibilities:

- Trust CRUD operations
- Permission storage
- Relationship type management

Subscription
------------

**File**: ``actingweb/subscription.py``

Event subscription storage. Responsibilities:

- Subscription CRUD
- Diff management
- Callback tracking

Developer API Layer
===================

The ``interface/`` module provides the modern developer API:

ActingWebApp
------------

**File**: ``actingweb/interface/app.py``

Fluent configuration API. Responsibilities:

- Application configuration
- Framework integration
- Hook registration
- Trust type definitions

ActorInterface
--------------

**File**: ``actingweb/interface/actor_interface.py``

High-level actor wrapper. Responsibilities:

- Clean API for actor operations
- Access to PropertyStore, TrustManager, SubscriptionManager
- Authenticated view creation

PropertyStore
-------------

**File**: ``actingweb/interface/property_store.py``

Dictionary-like property access. Responsibilities:

- Pythonic property access (``actor.properties["key"]``)
- Automatic JSON serialization
- Change notification (register_diffs)
- Hook execution

TrustManager
------------

**File**: ``actingweb/interface/trust_manager.py``

Trust relationship operations. Responsibilities:

- Trust CRUD with lifecycle hooks
- Permission checking
- Async peer communication

SubscriptionManager
-------------------

**File**: ``actingweb/interface/subscription_manager.py``

Subscription operations. Responsibilities:

- Subscription CRUD
- Diff management with wrapper classes
- Async peer subscription

Handler Layer
=============

Handlers process HTTP requests and delegate to the developer API:

BaseHandler
-----------

**File**: ``actingweb/handlers/base_handler.py``

Common handler functionality:

- Authentication (basic, bearer, passphrase)
- Response formatting (JSON, HTML)
- Actor loading
- Error responses

Specialized Handlers
--------------------

Each handler type has specific responsibilities:

- **PropertiesHandler**: Property CRUD, lists, metadata
- **TrustHandler**: Trust CRUD, verification protocol
- **SubscriptionHandler**: Subscription CRUD, diffs
- **CallbacksHandler**: Incoming peer callbacks
- **MethodsHandler**: Custom method hooks
- **ActionsHandler**: Custom action hooks
- **FactoryHandler**: Actor creation
- **OAuthHandler**: OAuth flow
- **OAuth2CallbackHandler**: OAuth2 callback processing

Framework Integrations
======================

BaseActingWebIntegration
------------------------

**File**: ``actingweb/interface/integrations/base_integration.py``

Shared integration logic:

- Handler class selection
- Route mapping
- OAuth discovery metadata

FlaskActingWebIntegration
-------------------------

**File**: ``actingweb/interface/integrations/flask_integration.py``

Flask-specific integration:

- Route registration
- Request/response adaptation
- Template rendering

FastAPIActingWebIntegration
---------------------------

**File**: ``actingweb/interface/integrations/fastapi_integration.py``

FastAPI-specific integration:

- Async route handlers
- Pydantic models
- OpenAPI documentation

Data Flow
=========

Request Processing
------------------

.. code-block::

    HTTP Request
        │
        ▼
    Framework (Flask/FastAPI)
        │
        ▼
    Integration (builds AWWebObj)
        │
        ▼
    Handler (processes request)
        │
        ▼
    Developer API (ActorInterface, etc.)
        │
        ▼
    Core Classes (Actor, Property, etc.)
        │
        ▼
    Database (DynamoDB)

Hook Execution
--------------

.. code-block::

    Handler receives request
        │
        ▼
    Handler calls developer API method
        │
        ▼
    Developer API executes registered hooks
        │
        ▼
    Hook function receives ActorInterface
        │
        ▼
    Hook performs business logic
        │
        ▼
    Result returned through chain

Key Design Patterns
===================

1. **Layered Architecture**

   Core → Developer API → Handlers → Integrations

2. **Dependency Injection**

   Handlers receive webobj, config, hooks

3. **Adapter Pattern**

   AWWebObj adapts framework-specific requests

4. **Wrapper Pattern**

   ActorInterface wraps Actor with clean API

5. **Hook Pattern**

   Extensible business logic via decorators

See Also
========

- :doc:`../sdk/handler-architecture` - Handler internals
- :doc:`../sdk/developer-api` - Developer API guide
- :doc:`style-guide` - Code style conventions
- :doc:`testing` - Testing guide
