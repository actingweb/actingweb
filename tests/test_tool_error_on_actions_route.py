"""``ToolError`` on the REST ``/actions`` route (4.0.0rc3).

An action hook exposed as an MCP tool is the same hook ``/<actor>/actions/
<name>`` runs. Over MCP a ``ToolError`` is the text of an ``isError``
result. Over REST every exception from a hook was logged and dropped: the
wildcard hook ran next, and the answer was 400 with no body. A hook written
as the MCP guide teaches lost its message there, and a refusal by the named
hook handed the request to the wildcard hook.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest import mock

import pytest

from actingweb.interface.hooks import HookRegistry
from actingweb.mcp import ToolError


def _registry(calls: list[str], exc: Exception) -> HookRegistry:
    registry = HookRegistry()

    def named(actor: Any, action_name: str, data: Any) -> Any:
        calls.append("named")
        raise exc

    def wildcard(actor: Any, action_name: str, data: Any) -> Any:
        calls.append("wildcard")
        return {"handled_by": "wildcard"}

    registry.register_action_hook("create_note", named)
    registry.register_action_hook("*", wildcard)
    return registry


def _run(registry: HookRegistry, async_twin: bool) -> Any:
    with mock.patch.object(registry, "_check_hook_permission", return_value=True):
        if async_twin:
            return asyncio.run(
                registry.execute_action_hooks_async("create_note", mock.Mock(), {})
            )
        return registry.execute_action_hooks("create_note", mock.Mock(), {})


@pytest.mark.parametrize("async_twin", [False, True])
def test_a_tool_error_leaves_the_hook_runner(async_twin: bool) -> None:
    """It propagates, and the wildcard hook does not act on what the named
    hook refused."""
    calls: list[str] = []
    registry = _registry(calls, ToolError("A note needs a title."))
    with pytest.raises(ToolError, match="A note needs a title."):
        _run(registry, async_twin)
    assert calls == ["named"]


@pytest.mark.parametrize("async_twin", [False, True])
def test_any_other_exception_is_still_logged_and_dropped(async_twin: bool) -> None:
    """Unchanged: the wildcard hook answers."""
    calls: list[str] = []
    registry = _registry(calls, ValueError("a bug"))
    assert _run(registry, async_twin) == {"handled_by": "wildcard"}
    assert calls == ["named", "wildcard"]


def _handler(cls: Any, exc: Exception) -> Any:
    from actingweb import aw_web_request

    webobj = aw_web_request.AWWebObj(
        url="https://test.example.com/a1/actions/create_note",
        params={},
        body="{}",
        headers={},
        cookies={},
    )
    hooks = mock.Mock()
    hooks.execute_action_hooks = mock.Mock(side_effect=exc)
    hooks.execute_action_hooks_async = mock.AsyncMock(side_effect=exc)
    handler = cls(webobj, mock.Mock(), hooks=hooks)
    return handler


@pytest.mark.parametrize("async_twin", [False, True])
@pytest.mark.parametrize("verb", ["get", "post", "put", "delete"])
def test_the_actions_route_answers_400_with_the_message(
    async_twin: bool, verb: str
) -> None:
    from actingweb.handlers.actions import ActionsHandler
    from actingweb.handlers.async_actions import AsyncActionsHandler

    cls = AsyncActionsHandler if async_twin else ActionsHandler
    handler = _handler(cls, ToolError("A note needs a title."))
    auth_obj = mock.Mock(response={"code": 200})
    result = mock.Mock(success=True, actor=mock.Mock(), auth_obj=auth_obj)
    with (
        mock.patch.object(handler, "authenticate_actor", return_value=result),
        mock.patch.object(handler, "_authenticate_dual_context", return_value=result),
        mock.patch.object(handler, "_check_action_permission", return_value=True),
        mock.patch.object(handler, "_get_actor_interface", return_value=mock.Mock()),
        mock.patch.object(handler, "_create_auth_context", return_value={}),
    ):
        if async_twin:
            asyncio.run(getattr(handler, f"{verb}_async")("a1", "create_note"))
        else:
            getattr(handler, verb)("a1", "create_note")
    assert handler.response.status_code == 400
    assert handler.response.headers["Content-Type"] == "application/json"
    assert json.loads(handler.response.body) == {"error": "A note needs a title."}
