"""Errors an MCP tool raises on purpose."""

from __future__ import annotations

import logging

from actingweb.db.exceptions import CreatorTaken, DeletionInProgress
from actingweb.faults import Fault, classify_fault


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

    The same hook serves ``POST /<actor_id>/actions/<name>``; there it
    answers 400 with ``{"error": "<message>"}`` and no other hook runs.

    Every other exception a tool raises answers a fixed text and is logged:
    its message can carry what a client must not see. The message of a
    ``ToolError`` is sent as written, so the author vouches for it: no
    exception text, identifier or stored value that the caller may not read.
    """


def fault_behind(exc: ToolError) -> Fault | None:
    """The store fault a ``ToolError`` was raised for, if any.

    An author who catches a fault and raises ``ToolError`` to say what was
    done must not hide the outage from the log. The fault is found on
    ``__cause__`` (``raise ToolError(...) from e``) and, because the author
    may not have written ``from``, on ``__context__`` (raised inside the
    ``except`` block). ``raise ... from None`` says the fault is not the
    cause, and is taken at its word.
    """
    fault = classify_fault(exc)
    if fault is None and exc.__context__ is not None and not exc.__suppress_context__:
        fault = classify_fault(exc.__context__)
    return fault


def fault_log_level(fault: Fault) -> int:
    """ERROR for an outage; WARNING for a wait for a deletion and a creator
    conflict, which are answers a caller can trigger at will."""
    if isinstance(fault.error, (CreatorTaken, DeletionInProgress)):
        return logging.WARNING
    return logging.ERROR
