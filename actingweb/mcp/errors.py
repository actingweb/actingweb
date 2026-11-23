"""Errors an MCP tool raises on purpose."""

from __future__ import annotations


class ToolError(Exception):
    """A tool failure whose text the model should read.

    Raise it from a tool hook to answer ``tools/call`` with a result whose
    ``isError`` is true and whose text is this exception's message::

        @app.action_hook("create_note")
        @mcp_tool(description="Create a note")
        def create_note(actor, action_name, data):
            if not data.get("title"):
                raise ToolError("A note needs a title.")
            ...

    Every other exception a tool raises answers a fixed text and is logged:
    its message can carry what a client must not see. The message of a
    ``ToolError`` is sent as written, so the author vouches for it: no
    exception text, identifier or stored value that the caller may not read.
    """
