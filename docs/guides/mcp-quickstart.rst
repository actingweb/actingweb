=================
MCP Quickstart
=================

This quickstart gets a minimal MCP-enabled ActingWeb server running with FastAPI, adds one MCP tool and one MCP prompt using the correct decorators, and shows how to test with simple JSON‑RPC calls.

.. note::

   **This is a two-stage recipe.** Stage 1 (below) gets the server
   responding to ``initialize`` with no authentication. Every other MCP
   method — ``tools/list``, ``tools/call``, ``prompts/list``, etc. —
   **requires an OAuth2 bearer token**; there is no dev bypass. Stage 2 is
   configuring real OAuth2 credentials and obtaining a token — see
   :ref:`mcp-quickstart-stage-2` below. Do not expect ``tools/list`` to
   return anything but 401 until you've done both stages.

Requirements
------------

- Python 3.11+
- A database. For local development, start DynamoDB Local:

  .. code-block:: bash

     docker compose -f docker-compose.test.yml up dynamodb-test

  See :doc:`../quickstart/overview` for PostgreSQL and other backend
  options. Without a running database, actor creation and every actor-scoped
  MCP call fail.

- Install extras for FastAPI and MCP:

.. code-block:: bash

   # pip
   pip install 'actingweb[fastapi]'

   # or with Poetry
   poetry add actingweb -E fastapi

Minimal App
-----------

The full application code below is
:download:`examples/mcp_quickstart.py <../../examples/mcp_quickstart.py>`,
included directly by this page (not copied), so what you read here is
exactly what runs.

.. literalinclude:: ../../examples/mcp_quickstart.py
   :language: python
   :start-after: start: app-setup
   :end-before: end: app-setup

Wire it up and run it:

.. code-block:: python

   # examples/mcp_quickstart.py's __main__ block does this:
   from fastapi import FastAPI

   api = FastAPI(title="My MCP Server")
   aw.integrate_fastapi(api)
   # then: uvicorn.run(api, host="0.0.0.0", port=5000)

.. code-block:: bash

   python examples/mcp_quickstart.py
   # or: uvicorn myapp:api --reload --port 5000, against your own app module

.. note::
   **Async Hook Support**: MCP tools and prompts can be async functions for optimal performance.
   FastAPI automatically uses ``AsyncMCPHandler`` which executes async hooks natively in the
   event loop without thread pool overhead. This enables true concurrent execution and significantly
   better performance for I/O-bound operations (database queries, API calls, etc.).

   .. code-block:: python

      # Async MCP tool - optimal for I/O operations
      @aw.action_hook("fetch_external_data")
      @mcp_tool(description="Fetch data from external API")
      async def fetch_data_tool(actor: ActorInterface, action_name: str, data: dict):
          async with aiohttp.ClientSession() as session:
              async with session.get(f"https://api.example.com/data/{data['id']}") as resp:
                  result = await resp.json()
          return {"content": [{"type": "text", "text": str(result)}]}

Stage 1: Testing with JSON‑RPC
-------------------------------

Call initialize (no auth required):

.. code-block:: bash

   curl -s http://localhost:5000/mcp \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"curl"}}}'

Every other method — ``tools/list``, ``prompts/list``, ``tools/call``, etc. —
**requires an OAuth2 bearer token** (only ``initialize`` and
``notifications/initialized`` are unauthenticated). There is **no dev bypass**;
``with_devtest(True)`` does not open the MCP endpoint. Sending these without a
token returns HTTP 401 with a ``WWW-Authenticate: Bearer`` header:

.. code-block:: bash

   # 401 without a bearer token — see Stage 2 below to obtain one, then:
   curl -s http://localhost:5000/mcp \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <token>' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

   # Send MCP-Protocol-Version, or the request negotiates 2025-03-26 and the
   # response carries no structuredContent even when your hook sets it.
   curl -s http://localhost:5000/mcp \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <token>' \
     -H 'MCP-Protocol-Version: 2025-06-18' \
     -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"create_note","arguments":{"title":"Hello","content":"World"}}}'

A bearer token that authenticates but does not resolve to a trust
relationship now returns an **empty** ``tools/list`` (not an error) and a
``-32003`` on ``tools/call``/``prompts/get``/``resources/read`` — see
:doc:`troubleshooting` if that happens unexpectedly after upgrading.

.. tip::

   To test tool/prompt *logic* without standing up an OAuth2 client, call the
   hooks directly in a unit test rather than over HTTP — e.g.
   ``app.hooks.execute_action_hooks("create_note", actor, {...})``. Real MCP
   clients (ChatGPT, Claude) perform the OAuth2 flow and send the bearer token
   automatically.

   Note that this checks your hook's **return value**, not the JSON the client
   receives: it bypasses ``format_call_tool_result``, so it cannot see whether
   ``structuredContent`` is emitted or suppressed. To assert on the wire shape,
   test the formatter as well — see
   :ref:`testing-the-wire-shape <testing-the-wire-shape>` in
   :doc:`mcp-applications`.

.. _mcp-quickstart-stage-2:

Stage 2: OAuth2 and a Bearer Token
------------------------------------

``tools/list``, ``tools/call``, and every other MCP method beyond
``initialize`` need a real bearer token. Getting one takes two steps:

1. **Configure a login provider.** ``examples/mcp_quickstart.py`` already
   calls ``.with_oauth(...)``, reading ``OAUTH_CLIENT_ID`` /
   ``OAUTH_CLIENT_SECRET`` from the environment — set these to real Google or
   GitHub OAuth2 app credentials. See :doc:`oauth2-setup` for creating one.
   Sign in through the web UI (``http://localhost:5000/``) once this is set,
   so an actor exists that an MCP client can be scoped to.
2. **Register an MCP client and obtain a token for it.** MCP clients
   (ChatGPT, Claude, or a script) authenticate as a specific actor via a
   *separate* OAuth2 client registration and authorization-code flow, not
   your own login credentials. See :doc:`mcp-applications`'s "OAuth2ClientManager
   Interface" and "Usage in AI Assistants" sections for the registration and
   token-exchange steps, and :doc:`oauth2-setup` for the underlying client
   storage model.

This is real infrastructure (a real OAuth2 provider, a running server
reachable at its redirect URI) — there is no local-only shortcut that
produces a valid bearer token without it.

Connecting a Real MCP Client
-------------------------------

Once you have a bearer token (or a client that can obtain one via OAuth2),
point an MCP client at ``http://localhost:5000/mcp`` (or your deployed URL).

**Clients with native remote-MCP support** (recent Claude.ai / Claude
Desktop custom connectors, ChatGPT custom connectors): add the server URL
directly in the client's connector settings. The client performs the OAuth2
authorization-code flow itself and attaches the resulting bearer token to
every request — you do not handle tokens manually.

**Clients that expect a local (stdio) MCP server** — most desktop MCP host
configurations, including older Claude Desktop versions — need a proxy that
speaks stdio on one side and Streamable HTTP + OAuth2 on the other. The
``mcp-remote`` npm package is the common choice:

.. code-block:: json

   {
     "mcpServers": {
       "myapp": {
         "command": "npx",
         "args": ["-y", "mcp-remote", "http://localhost:5000/mcp"]
       }
     }
   }

``mcp-remote`` opens a browser for the OAuth2 flow on first connection and
caches the resulting token. Check your specific client's documentation for
where this configuration file lives and whether it has since added native
remote support, since this changes quickly across MCP clients.

Tool Safety Annotations
-----------------------

**IMPORTANT**: For production MCP servers, always add safety annotations to your tools. ChatGPT and other MCP clients use these to evaluate server safety:

.. code-block:: python

   @aw.action_hook("search")
   @mcp_tool(
       description="Search your notes",
       annotations={
           "readOnlyHint": True,       # Only reads, never modifies
           "destructiveHint": False,   # Doesn't delete data
       }
   )
   def search(actor, action_name, data):
       pass

   @aw.action_hook("delete_note")
   @mcp_tool(
       description="Delete a note permanently",
       annotations={
           "destructiveHint": True,    # Destroys data - needs confirmation
           "readOnlyHint": False,
       }
   )
   def delete_note(actor, action_name, data):
       pass

**Key annotations:**

- ``destructiveHint: True`` - Tool can permanently delete/destroy data
- ``readOnlyHint: True`` - Tool only reads, never modifies data
- ``idempotentHint: True`` - Same input always gives same result
- ``openWorldHint: True`` - Tool accesses external services

See the `MCP Applications Guide <mcp-applications.html#tool-safety-annotations>`_ for complete documentation.

Recommendations
---------------

- For production, enable OAuth2 with Google/GitHub and ensure `/mcp` returns 401 with a proper `WWW-Authenticate` header for unauthenticated clients.
- Use :doc:`access-control-simple` (or the full :doc:`access-control` guide) to filter tools/prompts per trust relationship.

Where to Go Next
-----------------

- :doc:`mcp-applications` -- the broader guide this quickstart's tool safety
  annotations link into.
- :doc:`access-control` -- the full permission and trust-type system.
