"""
Minimal MCP-enabled ActingWeb server.

One MCP tool (attached to an action hook) and one MCP prompt (attached to a
method hook), using the correct decorators. Narrated in
docs/guides/mcp-quickstart.rst, which literalinclude's the section below by
its "start:"/"end:" marker comments. Also imported directly by
tests/test_mcp_quickstart.py, so the document and the test exercise the same
code.

Run with: python examples/mcp_quickstart.py
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

    _port = int(os.getenv("APP_HOST_FQDN", "localhost:5000").rsplit(":", 1)[-1])
    uvicorn.run(api, host="0.0.0.0", port=_port)
