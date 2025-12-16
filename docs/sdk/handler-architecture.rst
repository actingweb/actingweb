======================
Handler Architecture
======================

**Audience**: SDK developers who want to understand how ActingWeb handlers work internally.

This document explains the architecture of ActingWeb's HTTP handlers and how they interact with the developer API.

Overview
========

ActingWeb handlers are the bridge between HTTP requests and business logic. They:

1. Parse incoming HTTP requests
2. Authenticate the caller
3. Validate permissions
4. Delegate to the developer API (ActorInterface, PropertyStore, etc.)
5. Format and return responses

Handler Hierarchy
=================

All handlers inherit from ``BaseHandler``:

.. code-block::

    BaseHandler (base_handler.py)
    ├── PropertiesHandler (properties.py)
    ├── TrustHandler (trust.py)
    ├── SubscriptionHandler (subscription.py)
    ├── CallbacksHandler (callbacks.py)
    ├── MethodsHandler (methods.py)
    ├── ActionsHandler (actions.py)
    ├── FactoryHandler (factory.py)
    ├── OAuthHandler (oauth.py)
    ├── OAuth2CallbackHandler (oauth2_callback.py)
    ├── MetaHandler (meta.py)
    ├── WwwHandler (www.py)
    └── DevtestHandler (devtest.py)

BaseHandler
-----------

``BaseHandler`` provides common functionality:

.. code-block:: python

    class BaseHandler:
        def __init__(self, webobj, config, hooks=None):
            self.webobj = webobj      # AWWebObj instance
            self.config = config      # ActingWeb configuration
            self.hooks = hooks        # Hook registry

        # Authentication helpers
        def _authenticate(self) -> AuthResult: ...
        def _basic_auth(self) -> Optional[Tuple[str, str]]: ...
        def _bearer_auth(self) -> Optional[str]: ...

        # Response helpers
        def _json_response(self, data, status=200): ...
        def _error_response(self, message, status=400): ...
        def _not_found(self): ...
        def _forbidden(self, message=""): ...
        def _unauthorized(self, message=""): ...

        # Actor helpers
        def _get_actor(self, actor_id) -> Optional[Actor]: ...
        def _get_actor_interface(self, actor) -> ActorInterface: ...
        def _get_authenticated_view(self, actor, auth_result): ...

Handler Lifecycle
=================

Each HTTP request follows this lifecycle:

.. code-block::

    1. Framework routes request to handler
    2. Handler.__init__() with webobj, config, hooks
    3. Handler.method() called (get, post, put, delete)
       a. Parse request parameters
       b. Authenticate caller
       c. Load actor
       d. Check permissions
       e. Execute business logic via developer API
       f. Format response
    4. Framework sends response

Example: Properties GET
-----------------------

.. code-block:: python

    class PropertiesHandler(BaseHandler):
        def get(self, actor_id: str, path: str = ""):
            # 1. Load actor
            actor = self._get_actor(actor_id)
            if not actor:
                return self._not_found()

            # 2. Authenticate
            auth_result = self._authenticate()

            # 3. Get authenticated view
            actor_interface = self._get_actor_interface(actor)
            auth_view = self._get_authenticated_view(actor_interface, auth_result)

            # 4. Access properties (permissions enforced if auth_view)
            if auth_view:
                props = auth_view.properties
            else:
                props = actor_interface.properties

            # 5. Return response
            if path:
                value = props.get(path)
                if value is None:
                    return self._not_found()
                return self._json_response({path: value})
            else:
                return self._json_response(props.to_dict())

Handler Responsibilities
========================

Each handler has specific responsibilities:

PropertiesHandler
-----------------

- GET/PUT/DELETE single properties
- POST bulk property updates
- Property list operations (items, metadata)
- register_diffs for subscription notifications

TrustHandler
------------

- Trust relationship CRUD
- Verification protocol (handshake)
- Permission management
- Lifecycle hooks (trust_approved, trust_deleted)

SubscriptionHandler
-------------------

- Subscription CRUD
- Diff retrieval and clearing
- Remote subscription management

CallbacksHandler
----------------

- Receive callbacks from peers
- Route to appropriate subscription
- Execute callback hooks

MethodsHandler / ActionsHandler
-------------------------------

- Route to registered hooks
- Execute custom business logic
- Return hook results

FactoryHandler
--------------

- Create new actors
- Handle OAuth2 redirect for web creation
- Content negotiation (JSON vs HTML)

Developer API Integration
=========================

Handlers use the developer API exclusively for business logic:

Before Refactoring (Direct Actor Access)
----------------------------------------

.. code-block:: python

    # OLD: Direct actor method calls
    def post(self, actor_id):
        actor = self._get_actor(actor_id)
        actor.create_subscription(peer_id, ...)  # Direct call

After Refactoring (Developer API)
---------------------------------

.. code-block:: python

    # NEW: Via developer API
    def post(self, actor_id):
        actor = self._get_actor(actor_id)
        actor_interface = self._get_actor_interface(actor)
        actor_interface.subscriptions.create_local_subscription(...)  # Developer API

Benefits
--------

1. **Consistent interface** - Same API in handlers and hooks
2. **Permission enforcement** - AuthenticatedActorView integration
3. **Lifecycle hooks** - Automatic hook execution
4. **Change notifications** - Automatic diff generation
5. **Testability** - Easy to mock developer API

Hook Execution
==============

Handlers delegate to hooks for custom business logic:

.. code-block:: python

    class MethodsHandler(BaseHandler):
        def post(self, actor_id: str, name: str):
            actor = self._get_actor(actor_id)
            actor_interface = self._get_actor_interface(actor)

            # Parse request body
            data = self._parse_json_body()

            # Execute method hook
            result = self.hooks.execute_method_hooks(
                actor_interface,
                name,
                data
            )

            if result is None:
                return self._not_found()

            return self._json_response(result)

Authentication Flow
===================

Handlers support multiple authentication methods:

.. code-block:: python

    def _authenticate(self) -> AuthResult:
        """Authenticate the request."""

        # Try bearer token (OAuth2)
        token = self._bearer_auth()
        if token:
            return self._validate_oauth2_token(token)

        # Try basic auth
        credentials = self._basic_auth()
        if credentials:
            return self._validate_basic_auth(credentials)

        # Try passphrase (query param)
        passphrase = self.webobj.request.get("passphrase")
        if passphrase:
            return self._validate_passphrase(passphrase)

        # No authentication
        return AuthResult(authenticated=False)

Error Handling
==============

Handlers use consistent error responses:

.. code-block:: python

    # 400 Bad Request
    self._error_response("Invalid JSON", 400)

    # 401 Unauthorized
    self._unauthorized("Authentication required")

    # 403 Forbidden
    self._forbidden("Not authorized for this resource")

    # 404 Not Found
    self._not_found()

    # 405 Method Not Allowed
    self._method_not_allowed()

    # 500 Internal Server Error
    self._server_error("Unexpected error")

Testing Handlers
================

Handlers can be tested by mocking the webobj:

.. code-block:: python

    def test_properties_get():
        # Create mock webobj
        webobj = MockWebObj()
        webobj.request.method = "GET"

        # Create handler
        handler = PropertiesHandler(
            webobj=webobj,
            config=test_config,
            hooks=test_hooks
        )

        # Execute
        handler.get(actor_id="test123", path="status")

        # Assert
        assert webobj.response.status_code == 200
        assert "status" in json.loads(webobj.response._body)

See Also
========

- :doc:`developer-api` - Developer API reference
- :doc:`custom-framework` - Custom framework integration
- :doc:`authenticated-views` - Permission enforcement
- :doc:`../guides/hooks` - Hook implementation
