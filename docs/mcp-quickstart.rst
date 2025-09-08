=================
MCP Quickstart
=================

This quickstart gets a minimal MCP-enabled ActingWeb server running with FastAPI, adds one MCP tool and one MCP prompt using the correct decorators, and shows how to test with simple JSON‑RPC calls.

Requirements
------------

- Python 3.11+
- Install extras for FastAPI and MCP:

.. code-block:: bash

   # pip
   pip install 'actingweb[fastapi,mcp]'

   # or with Poetry
   poetry add actingweb -E fastapi -E mcp

Minimal App
-----------

.. code-block:: python

   # app_mcp.py
   import os
   from datetime import datetime
   from fastapi import FastAPI
   from actingweb.interface import ActingWebApp, ActorInterface
   from actingweb.mcp import mcp_tool, mcp_prompt

   api = FastAPI(title="My MCP Server")

   # Configure ActingWeb
   aw = (
       ActingWebApp(
           aw_type="urn:actingweb:example.com:mcp",
           database="dynamodb",
           fqdn=os.getenv("APP_HOST_FQDN", "localhost:5000"),
       )
       .with_web_ui(True)
       # Configure OAuth2 for real auth in production (example only)
       # .with_oauth(client_id=os.getenv("OAUTH_CLIENT_ID"), client_secret=os.getenv("OAUTH_CLIENT_SECRET"))
   )

   # Lifecycle example
   @aw.lifecycle_hook("actor_created")
   def init_actor(actor: ActorInterface, **kwargs):
       actor.properties.email = actor.creator
       actor.properties.created_at = datetime.now().isoformat()

   # MCP tool: attach to an action hook and expose with @mcp_tool
   @aw.action_hook("create_note")
   @mcp_tool(description="Create a new note for this actor")
   def create_note_tool(actor: ActorInterface, action_name: str, data: dict):
       title = data.get("title", "Untitled")
       content = data.get("content", "")
       key = f"note_{datetime.now().isoformat()}"
       actor.properties[key] = {"title": title, "content": content}
       return {"status": "ok", "note": key}

   # MCP prompt: attach to a method hook and expose with @mcp_prompt
   @aw.method_hook("analyze_notes")
   @mcp_prompt(description="Summarize notes for this actor")
   def analyze_notes_prompt(actor: ActorInterface, method_name: str, params: dict):
       notes = [v for k, v in actor.properties.items() if k.startswith("note_")]
       return f"Found {len(notes)} notes. Titles: " + ", ".join(n.get("title", "Untitled") for n in notes)

   # Integrate all ActingWeb routes on FastAPI app
   aw.integrate_fastapi(api)

   # Run: uvicorn app_mcp:api --reload --port 5000

Testing with JSON‑RPC
---------------------

Call initialize (no auth required):

.. code-block:: bash

   curl -s http://localhost:5000/mcp \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"curl"}}}'

List tools and prompts (requires auth in production; open in dev):

.. code-block:: bash

   curl -s http://localhost:5000/mcp -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

   curl -s http://localhost:5000/mcp -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":3,"method":"prompts/list"}'

Call the tool:

.. code-block:: bash

   curl -s http://localhost:5000/mcp -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"create_note","arguments":{"title":"Hello","content":"World"}}}'

Recommendations
---------------

- For production, enable OAuth2 with Google/GitHub and ensure `/mcp` returns 401 with a proper `WWW-Authenticate` header for unauthenticated clients.
- Use the unified access control to filter tools/prompts per trust relationship.

