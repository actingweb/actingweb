"""Unit tests for :mod:`actingweb.runtime_context`.

Pure-Python tests — no database, no docker. Covers the per-MCP-session
fields added to ``MCPContext`` so two concurrent sessions sharing one
OAuth2 credential can be told apart by tool handlers.
"""

from __future__ import annotations

from types import SimpleNamespace

from actingweb.runtime_context import (
    MCPContext,
    RuntimeContext,
    get_client_info_from_context,
)


class _Bag:
    """Plain stand-in for an actor — RuntimeContext only needs attr access."""


def test_mcp_context_defaults_for_new_fields():
    ctx = MCPContext(client_id="c", trust_relationship=None, peer_id="p")
    assert ctx.transport_session_id is None
    assert ctx.client_info is None


def test_set_mcp_context_round_trips_new_fields():
    actor = _Bag()
    rc = RuntimeContext(actor)
    rc.set_mcp_context(
        client_id="c",
        trust_relationship=None,
        peer_id="p",
        transport_session_id="sess-abc",
        client_info={"name": "claude-code", "version": "2.1.104"},
    )
    got = rc.get_mcp_context()
    assert got is not None
    assert got.transport_session_id == "sess-abc"
    assert got.client_info == {"name": "claude-code", "version": "2.1.104"}


def test_set_mcp_context_defaults_when_omitted():
    actor = _Bag()
    rc = RuntimeContext(actor)
    rc.set_mcp_context(client_id="c", trust_relationship=None, peer_id="p")
    got = rc.get_mcp_context()
    assert got is not None
    assert got.transport_session_id is None
    assert got.client_info is None


def test_get_client_info_prefers_live_over_trust_rel():
    """``client_info`` set per-session must win over the trust rel cache.

    The trust rel's ``client_name`` is shared across concurrent sessions
    on one OAuth2 credential, so reading it would surface another
    session's identity. The live ``client_info`` from the current
    ``initialize`` is the correct source.
    """
    actor = _Bag()
    rc = RuntimeContext(actor)
    stale_trust = SimpleNamespace(
        client_name="OtherClient",
        client_version="9.9.9",
        client_platform="other",
    )
    rc.set_mcp_context(
        client_id="c",
        trust_relationship=stale_trust,
        peer_id="p",
        client_info={"name": "claude-code", "version": "2.1.104"},
    )
    info = get_client_info_from_context(actor)
    assert info is not None
    assert info["name"] == "claude-code"
    assert info["version"] == "2.1.104"


def test_get_client_info_falls_back_to_trust_rel():
    """When no live client_info is set, fall back to the trust rel."""
    actor = _Bag()
    rc = RuntimeContext(actor)
    trust = SimpleNamespace(
        client_name="ClaudeAI",
        client_version="1.0.0",
        client_platform="web",
    )
    rc.set_mcp_context(
        client_id="c",
        trust_relationship=trust,
        peer_id="p",
    )
    info = get_client_info_from_context(actor)
    assert info is not None
    assert info["name"] == "ClaudeAI"
    assert info["version"] == "1.0.0"
