"""End-to-end wire-shape tests for ``tools/call`` responses.

These drive a real ``tools/call`` dispatch through **both** the sync
(``MCPHandler.post``) and async (``AsyncMCPHandler.post_async``) handlers and
assert on the JSON that actually leaves the handler — not on
``format_call_tool_result`` in isolation.

That distinction is the point of this module. The ``structuredContent``
promotion defect reached two stable releases partly because no test asserted the
wire shape: the formatter tests call the function directly, and the documented
way to test a tool (``app.hooks.execute_action_hooks(...)``) bypasses the
formatter entirely, so a hook's wire output can regress with the suite green.

``CANONICAL_WEATHER_PAYLOAD`` / ``canonical_weather_hook`` below pin the shape
documented in ``docs/guides/mcp-applications.rst``: an explicit
``structuredContent`` **plus** the same object serialized into a text ``content``
block, per the spec's backwards-compatibility guidance. The doc example is a copy
of this hook, so this module is what proves the documented shape really produces
``structuredContent`` on the wire.
"""

import json
import logging
from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler, _output_schema_warned
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.mcp import mcp_tool
from actingweb.permission_evaluator import PermissionResult
from actingweb.runtime_context import RuntimeContext
from tests.mcp_helpers import make_mcp_config, make_mcp_webobj

# The object a well-written data tool returns, in both representations.
CANONICAL_WEATHER_PAYLOAD = {
    "temperature": 22.5,
    "conditions": "Partly cloudy",
    "humidity": 65,
}

CANONICAL_WEATHER_SCHEMA = {
    "type": "object",
    "properties": {
        "temperature": {"type": "number"},
        "conditions": {"type": "string"},
        "humidity": {"type": "integer"},
    },
    "required": ["temperature", "conditions", "humidity"],
}


def canonical_weather_hook(actor: Any, action_name: str, data: Any) -> dict[str, Any]:
    """The shape ``docs/guides/mcp-applications.rst`` documents, verbatim.

    Structured data is named explicitly, and the same object is serialized into
    a text block so clients that ignore ``structuredContent`` still see it.
    """
    payload = dict(CANONICAL_WEATHER_PAYLOAD)
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "structuredContent": payload,
        "isError": False,
    }


class MockActorObj:
    id = "actor_wire_shape"
    creator = "test@example.com"
    properties: dict = {}


async def dispatch_both(
    app: ActingWebApp, tool_name: str, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one ``tools/call`` through the sync and async handlers.

    Returns ``(sync_result, async_result)`` — the full JSON-RPC envelopes.
    """
    mock_actor = ActorInterface(MockActorObj())  # type: ignore[arg-type]
    # A resolved peer id, since fail-closed authorization denies tools/call
    # outright with no trust relationship. These tests are about result shape,
    # so pair it with an allow-everything evaluator.
    RuntimeContext(mock_actor).set_mcp_context(
        client_id="test-client", trust_relationship=None, peer_id="test-peer"
    )
    evaluator = Mock()
    evaluator.evaluate_permission = Mock(return_value=PermissionResult.ALLOWED)

    request_data = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }

    with patch(
        "actingweb.permission_evaluator.get_permission_evaluator",
        return_value=evaluator,
    ):
        sync_handler = MCPHandler(
            make_mcp_webobj(headers), make_mcp_config(), hooks=app.hooks
        )
        sync_handler.authenticate_and_get_actor_cached = lambda: mock_actor
        sync_result = sync_handler.post(request_data)

        async_handler = AsyncMCPHandler(
            make_mcp_webobj(headers), make_mcp_config(), hooks=app.hooks
        )
        async_handler.authenticate_and_get_actor_cached = lambda: mock_actor
        async_result = await async_handler.post_async(request_data)

    return sync_result, async_result


def make_app(name: str) -> ActingWebApp:
    return ActingWebApp(
        aw_type=f"urn:actingweb:test:{name}",
        database="dynamodb",
        fqdn="test.example.com",
    ).with_devtest(enable=True)


class TestToolsCallWireShape:
    """What actually lands on the wire for a tools/call response."""

    @pytest.mark.asyncio
    async def test_prose_tool_with_extras_keeps_text_and_emits_nothing_structured(
        self,
    ) -> None:
        """A prose tool returning extras must not lose its text.

        This is the regression that motivated making ``structuredContent``
        opt-in: ``run_id`` below is a **non-empty** extra, so if promotion ever
        returns, ``structuredContent`` reappears here and this test fails by
        construction.
        """
        app = make_app("wire_prose")

        @app.action_hook("agent_run")
        @mcp_tool(description="Run the agent and report at length")
        def agent_run(actor, action_name, data):
            return {
                "content": [{"type": "text", "text": "A long prose report."}],
                "isError": False,
                "run_id": "run-123",
                "cycle": 4,
            }

        sync_result, async_result = await dispatch_both(
            app, "agent_run", {"MCP-Protocol-Version": "2025-11-25"}
        )

        assert sync_result == async_result
        assert sync_result == {
            "jsonrpc": "2.0",
            "id": 11,
            "result": {
                "content": [{"type": "text", "text": "A long prose report."}],
                "isError": False,
            },
        }
        # Named explicitly so a reinstated promotion cannot pass silently.
        assert "structuredContent" not in sync_result["result"]
        assert "run_id" not in sync_result["result"]
        assert "cycle" not in sync_result["result"]

    @pytest.mark.asyncio
    async def test_documented_shape_emits_structured_content_on_the_wire(self) -> None:
        """The shape shipped in the guide really does produce structuredContent."""
        app = make_app("wire_documented")

        app.action_hook("get_weather")(
            mcp_tool(
                description="Get current weather",
                output_schema=CANONICAL_WEATHER_SCHEMA,
            )(canonical_weather_hook)
        )

        sync_result, async_result = await dispatch_both(
            app, "get_weather", {"MCP-Protocol-Version": "2025-06-18"}
        )

        assert sync_result == async_result
        result = sync_result["result"]
        assert result["structuredContent"] == CANONICAL_WEATHER_PAYLOAD
        # Per the spec's backwards-compatibility guidance, the text block
        # carries the same object serialized.
        assert json.loads(result["content"][0]["text"]) == CANONICAL_WEATHER_PAYLOAD
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_missing_protocol_header_suppresses_explicit_structured_content(
        self,
    ) -> None:
        """No MCP-Protocol-Version header negotiates 2025-03-26 — gate closed.

        Even a hook that names ``structuredContent`` gets none, which is why the
        text block is the only payload that always arrives.
        """
        app = make_app("wire_noheader")

        app.action_hook("get_weather")(
            mcp_tool(
                description="Get current weather",
                output_schema=CANONICAL_WEATHER_SCHEMA,
            )(canonical_weather_hook)
        )

        sync_result, async_result = await dispatch_both(app, "get_weather", {})

        assert sync_result == async_result
        result = sync_result["result"]
        assert "structuredContent" not in result
        # The serialized text is still there, so the client is not left empty.
        assert json.loads(result["content"][0]["text"]) == CANONICAL_WEATHER_PAYLOAD

    @pytest.mark.asyncio
    async def test_legacy_shaped_error_hook_reports_is_error_on_the_wire(self) -> None:
        """A hook with no ``content`` key that sets isError is no longer a false success."""
        app = make_app("wire_legacy_error")

        @app.action_hook("legacy_fail")
        @mcp_tool(description="A hook that returns a bare dict on failure")
        def legacy_fail(actor, action_name, data):
            return {"isError": True, "error": "boom"}

        sync_result, async_result = await dispatch_both(
            app, "legacy_fail", {"MCP-Protocol-Version": "2025-11-25"}
        )

        assert sync_result == async_result
        assert sync_result["result"]["isError"] is True
        assert sync_result["result"]["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_legacy_hook_without_is_error_unchanged_on_the_wire(self) -> None:
        """Hooks that never set isError keep their exact pre-change wire shape."""
        app = make_app("wire_legacy_plain")

        @app.action_hook("legacy_ok")
        @mcp_tool(description="A hook that returns a bare dict on success")
        def legacy_ok(actor, action_name, data):
            return {"status": "deleted"}

        sync_result, async_result = await dispatch_both(
            app, "legacy_ok", {"MCP-Protocol-Version": "2025-11-25"}
        )

        assert sync_result == async_result
        assert sync_result["result"] == {
            "content": [{"type": "text", "text": "{'status': 'deleted'}"}]
        }

    @pytest.mark.asyncio
    async def test_output_schema_warning_reaches_formatter_through_dispatch(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Proves the metadata plumbing, not just the warning logic.

        The unit tests pass ``output_schema`` to the formatter explicitly, so
        they would still pass if the dispatch loop read the wrong metadata key
        (the decorator stores ``output_schema``; ``tools/list`` emits
        ``outputSchema``). Only a real dispatch catches that.
        """
        _output_schema_warned.clear()
        caplog.set_level(logging.WARNING, logger="actingweb.handlers.mcp")
        app = make_app("wire_schema_warn")

        @app.action_hook("schema_no_struct")
        @mcp_tool(
            description="Declares a schema but returns prose only",
            output_schema=CANONICAL_WEATHER_SCHEMA,
        )
        def schema_no_struct(actor, action_name, data):
            return {"content": [{"type": "text", "text": "prose only"}]}

        await dispatch_both(
            app, "schema_no_struct", {"MCP-Protocol-Version": "2025-06-18"}
        )

        assert "declares an output_schema" in caplog.text
        assert "schema_no_struct" in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_for_documented_shape_through_dispatch(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The shape the guide ships must not warn — the false-positive guard."""
        _output_schema_warned.clear()
        caplog.set_level(logging.WARNING, logger="actingweb.handlers.mcp")
        app = make_app("wire_schema_ok")

        app.action_hook("get_weather")(
            mcp_tool(
                description="Get current weather",
                output_schema=CANONICAL_WEATHER_SCHEMA,
            )(canonical_weather_hook)
        )

        await dispatch_both(app, "get_weather", {"MCP-Protocol-Version": "2025-06-18"})

        assert "declares an output_schema" not in caplog.text
