"""
Minimal MCP-enabled ActingWeb server.

One MCP tool (attached to an action hook) and one MCP prompt (attached to a
method hook), using the correct decorators. Narrated in
docs/guides/mcp-quickstart.rst, which literalinclude's the section below by
its "start:"/"end:" marker comments. Also imported directly by
tests/test_mcp_quickstart.py, so the document and the test exercise the same
code.

Run with: python examples/mcp_quickstart.py

First run on a fresh database: creator uniqueness is on by default, and the
first start on a store with no actors enables it itself. On DynamoDB set
``AWS_DB_PREFIX`` explicitly; without it the start is refused and names
``actingweb-unique-creators enable --apply``. (Add
``.with_unique_creator(False)`` to the app to opt out.)
"""

import os
from datetime import datetime

from actingweb.interface import ActingWebApp, ActorInterface
from actingweb.mcp import mcp_prompt, mcp_tool

# start: app-setup
aw = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:mcp",
        database="dynamodb",
        fqdn=os.getenv("APP_HOST_FQDN", "localhost:5000"),
        # Defaults to http:// for local development, matching the uvicorn
        # server started below (plain HTTP, no TLS). ActingWebApp defaults
        # to https:// -- left as that default here, the actor URLs and the
        # OAuth2 redirect_uri generated for Stage 2 would point at
        # https://localhost:..., which nothing on this server answers on.
        # Set APP_HOST_PROTO=https:// in production, matching your real proto.
        proto=os.getenv("APP_HOST_PROTO", "http://"),
    )
    .with_web_ui(True)
    # MCP is on by default. Optionally set the server name announced in
    # the initialise handshake -- some clients use this as the default
    # tool prefix (e.g. "myapp:create_note").
    .with_mcp(server_name="myapp")
    # Every MCP method beyond initialize requires an OAuth2 bearer token --
    # see the "Two Stages" note in docs/guides/mcp-quickstart.rst before
    # expecting tools/list or tools/call to work. Set these to test past
    # stage 1.
    .with_oauth(
        client_id=os.getenv("OAUTH_CLIENT_ID", ""),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET", ""),
    )
)


@aw.lifecycle_hook("actor_created")
def init_actor(actor: ActorInterface, **kwargs):
    actor.properties.email = actor.creator
    actor.properties.created_at = datetime.now().isoformat()


# MCP tool: attach to an action hook and expose with @mcp_tool
@aw.action_hook("create_note")
@mcp_tool(
    description="Create a new note for this actor",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The note's title"},
            "content": {"type": "string", "description": "The note's text"},
        },
        "required": ["title"],
    },
)
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
    return f"Found {len(notes)} notes. Titles: " + ", ".join(
        n.get("title", "Untitled") for n in notes
    )


# end: app-setup


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    # Building the FastAPI app and integrating routes touches the database
    # (table existence checks), so it happens here rather than at import
    # time -- importing this module (as tests/test_mcp_quickstart.py does)
    # stays side-effect-free.
    api = FastAPI(title="My MCP Server")
    aw.integrate_fastapi(api)

    # PORT, else the port in APP_HOST_FQDN, else 5000. Behind a tunnel or a
    # proxy (APP_HOST_FQDN=your.public.host, no port) set PORT to the local
    # port it forwards to. HOST is 127.0.0.1 unless you set it: 0.0.0.0
    # would serve every network this machine is on.
    _fqdn = os.getenv("APP_HOST_FQDN", "localhost:5000")
    _fqdn_port = _fqdn.rsplit(":", 1)[-1] if ":" in _fqdn else ""
    _port = int(os.getenv("PORT") or _fqdn_port or 5000)
    uvicorn.run(api, host=os.getenv("HOST", "127.0.0.1"), port=_port)
