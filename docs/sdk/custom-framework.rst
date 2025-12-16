============================
Custom Framework Integration
============================

**Audience**: SDK developers who want to use ActingWeb with frameworks other than Flask or FastAPI.

ActingWeb can be integrated with any Python web framework. This guide explains the handler architecture and how to create custom integrations.

Overview
========

ActingWeb's handlers are framework-agnostic. They operate on a ``AWWebObj`` abstraction that encapsulates request/response handling. To integrate with a new framework, you need to:

1. Create an ``AWWebObj`` adapter for your framework's request/response
2. Invoke the appropriate handlers based on URL routing
3. Convert handler responses back to your framework's format

AWWebObj Interface
==================

The ``AWWebObj`` class provides a unified interface for HTTP request/response handling:

.. code-block:: python

    class AWWebObj:
        """Framework-agnostic request/response wrapper."""

        def __init__(self, request, response):
            self.request = request    # Request adapter
            self.response = response  # Response adapter

Request Adapter
---------------

Your request adapter must provide:

.. code-block:: python

    class RequestAdapter:
        @property
        def body(self) -> Union[str, bytes, None]:
            """Request body content."""
            pass

        @property
        def headers(self) -> Dict[str, str]:
            """Request headers dictionary."""
            pass

        @property
        def method(self) -> str:
            """HTTP method (GET, POST, etc.)."""
            pass

        @property
        def path(self) -> str:
            """Request path."""
            pass

        def get(self, param: str, default: str = "") -> str:
            """Get query parameter."""
            pass

Response Adapter
----------------

Your response adapter must provide:

.. code-block:: python

    class ResponseAdapter:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
            self._body = ""

        def set_status(self, code: int) -> None:
            """Set HTTP status code."""
            self.status_code = code

        def write(self, content: str) -> None:
            """Write content to response body."""
            self._body += content

        def set_header(self, name: str, value: str) -> None:
            """Set response header."""
            self.headers[name] = value

Handler Invocation
==================

ActingWeb handlers follow a consistent pattern:

.. code-block:: python

    from actingweb.handlers import (
        PropertiesHandler,
        TrustHandler,
        SubscriptionHandler,
        CallbacksHandler,
        MethodsHandler,
        ActionsHandler,
        FactoryHandler,
        OAuthHandler,
        OAuth2CallbackHandler,
        MetaHandler,
        WwwHandler,
        DevtestHandler,
    )

    def invoke_handler(handler_class, method: str, webobj: AWWebObj,
                       actor_id: str, config, hooks, **kwargs):
        """Invoke an ActingWeb handler."""

        # Create handler instance
        handler = handler_class(
            webobj=webobj,
            config=config,
            hooks=hooks
        )

        # Get the method function
        method_func = getattr(handler, method.lower(), None)
        if not method_func:
            webobj.response.set_status(405)
            return

        # Invoke with appropriate arguments
        method_func(actor_id=actor_id, **kwargs)

URL Routing
===========

Map URLs to handlers following this pattern:

.. code-block:: python

    ROUTE_HANDLERS = {
        # Actor-specific routes
        "/<actor_id>/properties": PropertiesHandler,
        "/<actor_id>/properties/<path>": PropertiesHandler,
        "/<actor_id>/trust": TrustHandler,
        "/<actor_id>/trust/<relationship>": TrustHandler,
        "/<actor_id>/trust/<relationship>/<peer_id>": TrustHandler,
        "/<actor_id>/subscriptions": SubscriptionHandler,
        "/<actor_id>/subscriptions/<peer_id>": SubscriptionHandler,
        "/<actor_id>/callbacks/<name>": CallbacksHandler,
        "/<actor_id>/methods/<name>": MethodsHandler,
        "/<actor_id>/actions/<name>": ActionsHandler,
        "/<actor_id>/meta": MetaHandler,
        "/<actor_id>/www": WwwHandler,

        # Application routes
        "/": FactoryHandler,
        "/oauth": OAuthHandler,
        "/oauth/callback": OAuth2CallbackHandler,
    }

Django Integration Example
==========================

Here's an example integration with Django:

.. code-block:: python

    # django_adapter.py
    from django.http import HttpRequest, HttpResponse
    from actingweb.aw_web_obj import AWWebObj

    class DjangoRequestAdapter:
        def __init__(self, request: HttpRequest):
            self._request = request

        @property
        def body(self):
            return self._request.body

        @property
        def headers(self):
            return dict(self._request.headers)

        @property
        def method(self):
            return self._request.method

        @property
        def path(self):
            return self._request.path

        def get(self, param, default=""):
            return self._request.GET.get(param, default)

    class DjangoResponseAdapter:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
            self._body = ""

        def set_status(self, code):
            self.status_code = code

        def write(self, content):
            self._body += content

        def set_header(self, name, value):
            self.headers[name] = value

        def to_django_response(self):
            response = HttpResponse(
                self._body,
                status=self.status_code
            )
            for name, value in self.headers.items():
                response[name] = value
            return response

    def create_webobj(request: HttpRequest) -> AWWebObj:
        return AWWebObj(
            request=DjangoRequestAdapter(request),
            response=DjangoResponseAdapter()
        )

    # views.py
    from django.urls import path
    from actingweb.handlers import PropertiesHandler

    def properties_view(request, actor_id, path=""):
        webobj = create_webobj(request)

        handler = PropertiesHandler(
            webobj=webobj,
            config=aw_config,
            hooks=aw_hooks
        )

        method = request.method.lower()
        getattr(handler, method)(actor_id=actor_id, path=path)

        return webobj.response.to_django_response()

    urlpatterns = [
        path('<str:actor_id>/properties/', properties_view),
        path('<str:actor_id>/properties/<path:path>', properties_view),
    ]

Starlette Integration Example
=============================

For async frameworks like Starlette:

.. code-block:: python

    # starlette_adapter.py
    from starlette.requests import Request
    from starlette.responses import Response
    import asyncio

    class StarletteRequestAdapter:
        def __init__(self, request: Request, body: bytes):
            self._request = request
            self._body = body

        @property
        def body(self):
            return self._body

        @property
        def headers(self):
            return dict(self._request.headers)

        @property
        def method(self):
            return self._request.method

        @property
        def path(self):
            return self._request.url.path

        def get(self, param, default=""):
            return self._request.query_params.get(param, default)

    class StarletteResponseAdapter:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
            self._body = ""

        def set_status(self, code):
            self.status_code = code

        def write(self, content):
            self._body += content

        def set_header(self, name, value):
            self.headers[name] = value

        def to_starlette_response(self):
            return Response(
                content=self._body,
                status_code=self.status_code,
                headers=self.headers
            )

    # routes.py
    from starlette.routing import Route

    async def properties_handler(request: Request):
        body = await request.body()
        webobj = AWWebObj(
            request=StarletteRequestAdapter(request, body),
            response=StarletteResponseAdapter()
        )

        actor_id = request.path_params["actor_id"]
        path = request.path_params.get("path", "")

        # Run sync handler in thread pool
        handler = PropertiesHandler(webobj=webobj, config=config, hooks=hooks)
        await asyncio.to_thread(
            getattr(handler, request.method.lower()),
            actor_id=actor_id,
            path=path
        )

        return webobj.response.to_starlette_response()

    routes = [
        Route("/{actor_id}/properties", properties_handler, methods=["GET", "POST", "PUT", "DELETE"]),
        Route("/{actor_id}/properties/{path:path}", properties_handler, methods=["GET", "POST", "PUT", "DELETE"]),
    ]

BaseActingWebIntegration
========================

For comprehensive integrations, extend the ``BaseActingWebIntegration`` class:

.. code-block:: python

    from actingweb.interface.integrations.base_integration import BaseActingWebIntegration

    class MyFrameworkIntegration(BaseActingWebIntegration):
        """Custom framework integration."""

        def __init__(self, app: ActingWebApp, framework_app):
            super().__init__(app)
            self.framework_app = framework_app

        def get_handler_class(self, endpoint: str):
            """Get handler class for endpoint."""
            return super().get_handler_class(endpoint)

        def register_routes(self):
            """Register all ActingWeb routes with framework."""
            # Implementation specific to your framework
            pass

Handler Arguments
=================

Different handlers require different arguments:

.. code-block:: python

    # PropertiesHandler
    handler.get(actor_id="...", path="property/path")
    handler.put(actor_id="...", path="property/path")
    handler.post(actor_id="...")
    handler.delete(actor_id="...", path="property/path")

    # TrustHandler
    handler.get(actor_id="...", relationship="friend", peerid="peer123")
    handler.post(actor_id="...", relationship="friend")
    handler.put(actor_id="...", relationship="friend", peerid="peer123")
    handler.delete(actor_id="...", relationship="friend", peerid="peer123")

    # SubscriptionHandler
    handler.get(actor_id="...", peerid="peer123")
    handler.post(actor_id="...")
    handler.delete(actor_id="...", peerid="peer123")

    # CallbacksHandler
    handler.post(actor_id="...", name="callback_name")
    handler.delete(actor_id="...", name="callback_name")

    # MethodsHandler / ActionsHandler
    handler.get(actor_id="...", name="method_name")
    handler.post(actor_id="...", name="method_name")

    # FactoryHandler (no actor_id)
    handler.get()
    handler.post()

    # MetaHandler
    handler.get(actor_id="...")

See Also
========

- :doc:`handler-architecture` - Deep dive into handler internals
- :doc:`developer-api` - Core developer interfaces
- :doc:`async-operations` - Async handler patterns
