"""AC-33: ``resources/templates/list`` returns the resources declared with a
URI template, under the permissions ``resources/list`` applies; the answer
of ``resources/list`` itself does not change (it keeps listing templated
resources for a client that never calls the templates method).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.config import Config
from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_resource
from actingweb.permission_evaluator import PermissionResult


class _Actor:
    id = "actor-1"


def _hooks() -> HookRegistry:
    hooks = HookRegistry()

    @mcp_resource(uri_template="notes://{id}", name="Note", mime_type="text/plain")
    def note(actor: Any, method_name: str, params: Any) -> Any:
        return {}

    @mcp_resource(uri_template="config://settings", name="Settings")
    def settings(actor: Any, method_name: str, params: Any) -> Any:
        return {}

    @mcp_resource(uri_template="secret://{key}", name="Secret")
    def secret(actor: Any, method_name: str, params: Any) -> Any:
        return {}

    @mcp_resource(name="Files")
    def files(actor: Any, method_name: str, params: Any) -> Any:
        return {}

    # Declared by a regex only: in resources/list, never a template.
    files._mcp_metadata["uri_pattern"] = r"files://.+"  # type: ignore[attr-defined]

    for name, hook in (
        ("note", note),
        ("settings", settings),
        ("secret", secret),
        ("files", files),
    ):
        hooks.register_method_hook(name, hook)
    return hooks


def _evaluator() -> Mock:
    evaluator = Mock()

    def decide(actor_id: str, peer_id: str, ptype: Any, target: str, **kw: Any) -> Any:
        return (
            PermissionResult.DENIED
            if target.startswith("secret://")
            else PermissionResult.ALLOWED
        )

    evaluator.evaluate_permission.side_effect = decide
    return evaluator


def _call(kind: str, method: str, *, peer_id: str | None = "peer-1") -> dict[str, Any]:
    cls = AsyncMCPHandler if kind == "async" else MCPHandler
    handler = cls(config=Config(mcp=True, unique_creator=False))
    handler.hooks = _hooks()
    body = {"jsonrpc": "2.0", "id": "1", "method": method, "params": {}}
    with (
        patch.object(
            MCPHandler, "authenticate_and_get_actor_cached", return_value=_Actor()
        ),
        patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        patch(
            "actingweb.permission_evaluator.get_permission_evaluator",
            return_value=_evaluator(),
        ),
    ):
        ctx = Mock()
        ctx.peer_id = peer_id
        ctx.client_info = None
        mock_rc.return_value.get_mcp_context.return_value = ctx
        if isinstance(handler, AsyncMCPHandler):
            return asyncio.run(handler.post_async(body))
        return handler.post(body)


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_templates_are_listed_with_uri_template(kind: str) -> None:
    out = _call(kind, "resources/templates/list")
    templates = out["result"]["resourceTemplates"]
    assert [t["uriTemplate"] for t in templates] == ["notes://{id}"]
    assert templates[0]["name"] == "Note"
    assert templates[0]["mimeType"] == "text/plain"
    assert all("uri" not in t for t in templates)


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_resources_list_is_unchanged(kind: str) -> None:
    out = _call(kind, "resources/list")
    uris = [r["uri"] for r in out["result"]["resources"]]
    # Templated resources stay in resources/list (decision, 2026-11-19).
    assert "notes://{id}" in uris and "config://settings" in uris
    assert not any(u.startswith("secret://") for u in uris)


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_a_denied_template_is_left_out(kind: str) -> None:
    out = _call(kind, "resources/templates/list")
    assert all(
        not t["uriTemplate"].startswith("secret://")
        for t in out["result"]["resourceTemplates"]
    )


@pytest.mark.parametrize("kind", ["sync", "async"])
def test_no_trust_row_is_an_empty_list(kind: str) -> None:
    out = _call(kind, "resources/templates/list", peer_id=None)
    assert out["result"]["resourceTemplates"] == []
