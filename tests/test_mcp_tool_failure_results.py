"""A tool that fails answers the model (4.0.0rc3).

A ``tools/call`` whose hook raises is a result with ``isError: true`` and a
fixed text, never a JSON-RPC error: MCP keeps protocol errors for a request
that could not be dispatched. The text is fixed by the failure's class and
never carries the exception's own text, which can name an actor.

Every test runs the sync and the async handler.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import Mock, patch

import pytest

from actingweb.db.exceptions import (
    AttributeKeyCollision,
    CreatorTaken,
    DbError,
    DbErrorAfterWrite,
    DeletionInProgress,
)
from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.list_core import ListItemNewerFormatError
from actingweb.mcp import ToolError, mcp_prompt, mcp_resource, mcp_tool
from actingweb.oauth2_server.token_manager import TokenStoreUnavailable
from actingweb.permission_evaluator import PermissionResult
from actingweb.runtime_context import RuntimeContext
from actingweb.single_use import StoreFault
from tests.mcp_helpers import make_mcp_config, make_mcp_webobj

RETRYABLE = "The service is temporarily unavailable. Try again shortly."
STORED = (
    "A change was saved, but the tool did not finish. "
    "Check the current state before calling it again."
)
PERMANENT = "The request could not be stored. Trying again will not help."
CONFLICT = "That address already belongs to another account. Use a different one."
FAILED = "The tool failed. The error was logged."

# Placed in every raised exception: it must never reach the response.
SECRET = "actor-9f3c-secret-marker"

HEADERS = {"MCP-Protocol-Version": "2025-11-25"}


class _ActorObj:
    id = "actor_tool_failure"
    creator = "test@example.com"
    properties: dict[str, Any] = {}


class _BackendError(Exception):
    """Stands in for a PynamoDB error with a response code."""

    def __init__(self, code: str) -> None:
        super().__init__(f"backend said {code} about {SECRET}")
        self.cause_response_code = code


def _permanent() -> DbError:
    try:
        raise _BackendError("ValidationException")
    except _BackendError as cause:
        try:
            raise DbError("property write", SECRET) from cause
        except DbError as fault:
            return fault


def _stored_with_a_permanent_cause() -> DbError:
    """``after_write`` raises the stored fault from whatever faulted; a
    permanent cause must not turn it into "trying again will not help"."""
    try:
        raise _permanent()
    except DbError as cause:
        try:
            raise DbErrorAfterWrite("diff registration", SECRET) from cause
        except DbError as fault:
            return fault


def _app(name: str, exc: BaseException) -> ActingWebApp:
    app = ActingWebApp(
        aw_type=f"urn:actingweb:test:{name}",
        database="dynamodb",
        fqdn="test.example.com",
    ).with_devtest(enable=True)

    @app.action_hook("failing")
    @mcp_tool(description="A tool that raises")
    def failing(actor: Any, action_name: str, data: Any) -> Any:
        raise exc

    @app.action_hook("failing_async")
    @mcp_tool(description="An async tool that raises")
    async def failing_async(actor: Any, action_name: str, data: Any) -> Any:
        raise exc

    return app


async def _call(
    app: ActingWebApp,
    tool: str = "failing",
    *,
    evaluator: Any = None,
    method: str = "tools/call",
    params: dict[str, Any] | None = None,
    sync: bool = True,
) -> list[tuple[dict[str, Any], Any]]:
    """One request through the sync and the async handler: the JSON-RPC
    envelope and the handler's response object for each."""
    actor = ActorInterface(_ActorObj())  # type: ignore[arg-type]
    RuntimeContext(actor).set_mcp_context(
        client_id="test-client", trust_relationship=None, peer_id="test-peer"
    )
    if evaluator is None:
        evaluator = Mock()
        evaluator.evaluate_permission = Mock(return_value=PermissionResult.ALLOWED)
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": method,
        "params": params if params is not None else {"name": tool, "arguments": {}},
    }
    out: list[tuple[dict[str, Any], Any]] = []
    with patch(
        "actingweb.permission_evaluator.get_permission_evaluator",
        return_value=evaluator,
    ):
        if sync:
            handler = MCPHandler(
                make_mcp_webobj(HEADERS), make_mcp_config(), hooks=app.hooks
            )
            handler.authenticate_and_get_actor_cached = lambda: actor  # type: ignore[method-assign]
            out.append((handler.post(request), handler.response))

        asyn = AsyncMCPHandler(
            make_mcp_webobj(HEADERS), make_mcp_config(), hooks=app.hooks
        )
        asyn.authenticate_and_get_actor_cached = lambda: actor  # type: ignore[method-assign]
        out.append((await asyn.post_async(request), asyn.response))
    return out


def _assert_tool_failure(envelope: dict[str, Any], response: Any, text: str) -> None:
    assert "error" not in envelope, envelope
    assert envelope["id"] == 7
    result = envelope["result"]
    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": text}]
    assert "structuredContent" not in result
    assert SECRET not in repr(envelope)
    # No status and no Retry-After: the answer is an ordinary 200.
    assert response.status_code == 200
    assert "Retry-After" not in response.headers


CASES: list[tuple[str, BaseException, str]] = [
    ("transient", DbError("property read", SECRET), RETRYABLE),
    ("deleting", DeletionInProgress(SECRET, 12), RETRYABLE),
    ("stored", DbErrorAfterWrite("diff registration", SECRET), STORED),
    ("stored_permanent_cause", _stored_with_a_permanent_cause(), STORED),
    ("permanent", _permanent(), PERMANENT),
    ("collision", AttributeKeyCollision("a", "b:c", SECRET), PERMANENT),
    ("conflict", CreatorTaken(f"creator taken by {SECRET}"), CONFLICT),
    ("other", ValueError(f"bad value for {SECRET}"), FAILED),
    ("other_base", RuntimeError(SECRET), FAILED),
    # Store faults that are not a DbError: the token store and a single-use
    # consume that could not be confirmed.
    ("token_store", TokenStoreUnavailable(f"token store down for {SECRET}"), RETRYABLE),
    ("single_use", StoreFault(f"could not confirm {SECRET}"), RETRYABLE),
    # Data a later library version stored is not a store fault: a retry
    # cannot help and nothing was "not stored", so it takes the plain text.
    ("newer_format", ListItemNewerFormatError(SECRET), FAILED),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "exc", "text"), CASES, ids=[case[0] for case in CASES]
)
@pytest.mark.parametrize("tool", ["failing", "failing_async"])
async def test_a_failing_tool_is_a_tool_result(
    name: str, exc: BaseException, text: str, tool: str
) -> None:
    """AC-1 to AC-5: each failure class has its fixed text; nothing of the
    exception reaches the wire."""
    app = _app(f"tool_failure_{name}", exc)
    # The sync handler cannot await an async hook; the async tool goes
    # through the async handler only.
    results = await _call(app, tool, sync=tool == "failing")
    assert results
    for envelope, response in results:
        _assert_tool_failure(envelope, response, text)


@pytest.mark.asyncio
async def test_a_wrapped_store_fault_is_still_classified() -> None:
    """A hook that wraps the fault in its own exception with ``raise ...
    from`` gets the fault's text, as the integrations find it."""
    try:
        raise DbError("property read", SECRET)
    except DbError as fault:
        try:
            raise RuntimeError("could not load notes") from fault
        except RuntimeError as wrapped:
            exc = wrapped
    for envelope, response in await _call(_app("tool_failure_wrapped", exc)):
        _assert_tool_failure(envelope, response, RETRYABLE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "exc", "level", "needle"),
    [
        ("other", ValueError(f"bad {SECRET}"), logging.ERROR, SECRET),
        ("transient", DbError("property read", SECRET), logging.ERROR, SECRET),
        ("permanent", _permanent(), logging.ERROR, "ValidationException"),
        ("stored", DbErrorAfterWrite("diff", SECRET), logging.ERROR, "stored"),
        # A wait and a conflict are answers, not outages.
        ("deleting", DeletionInProgress(SECRET, 12), logging.WARNING, SECRET),
        ("conflict", CreatorTaken(SECRET), logging.WARNING, "conflict"),
        ("tool_error", ToolError("A note needs a title."), logging.INFO, "title"),
    ],
    ids=lambda v: v if isinstance(v, str) and " " not in v else None,
)
async def test_each_failure_is_logged_once_with_its_cause(
    caplog: pytest.LogCaptureFixture,
    name: str,
    exc: Exception,
    level: int,
    needle: str,
) -> None:
    """AC-8: one line per failure names the tool and what was raised, where
    the wire does not; no line names an HTTP status that was not sent."""
    caplog.set_level(logging.DEBUG)
    await _call(_app(f"tool_failure_log_{name}", exc), sync=False)
    lines = [r for r in caplog.records if r.name.startswith("actingweb.handlers")]
    lines = [r for r in lines if "Tool 'failing'" in r.getMessage()]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    assert lines[0].levelno == level
    assert needle in lines[0].getMessage()
    assert "503" not in lines[0].getMessage()


@pytest.mark.asyncio
async def test_a_tool_error_reaches_the_model_as_written() -> None:
    """``ToolError`` is the supported way to tell the model what is wrong:
    its text is the result, and the answer is still a tool result."""
    app = _app("tool_failure_tool_error", ToolError("A note needs a title."))
    for tool, sync in (("failing", True), ("failing_async", False)):
        for envelope, response in await _call(app, tool, sync=sync):
            assert envelope["result"] == {
                "content": [{"type": "text", "text": "A note needs a title."}],
                "isError": True,
            }
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_tool_error_without_a_message_takes_the_fixed_text() -> None:
    for envelope, _ in await _call(_app("tool_failure_tool_error_empty", ToolError())):
        assert envelope["result"]["content"][0]["text"] == FAILED


@pytest.mark.asyncio
async def test_a_hooks_own_is_error_result_is_untouched() -> None:
    """AC-7: a result the hook built itself passes through unchanged."""
    own = {
        "content": [{"type": "text", "text": "Nothing matched 'x'."}],
        "isError": True,
        "_meta": {"example/attempt": 2},
    }
    app = _app("tool_failure_own_result", ValueError("never raised"))

    @app.action_hook("own_error")
    @mcp_tool(description="A tool that returns its own error")
    def own_error(actor: Any, action_name: str, data: Any) -> Any:
        return dict(own)

    for envelope, response in await _call(app, "own_error"):
        assert envelope["result"] == own
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_fault_in_the_permission_check_keeps_the_protocol_error() -> None:
    """AC-6: the hook did not run, so this is not a tool failure."""
    evaluator = Mock()
    evaluator.evaluate_permission = Mock(side_effect=DbError("trust read", SECRET))
    app = _app("tool_failure_permission", ValueError("never raised"))
    for envelope, response in await _call(app, evaluator=evaluator):
        assert "result" not in envelope
        assert envelope["error"]["code"] == -32603
        assert SECRET not in repr(envelope)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"


@pytest.mark.asyncio
async def test_a_fault_in_another_method_keeps_the_protocol_error() -> None:
    """AC-6: ``prompts/get`` has no ``isError`` result; its fault stays a
    JSON-RPC error with the mapped status."""
    app = _app("tool_failure_prompt", ValueError("never raised"))

    @app.method_hook("faulting_prompt")
    @mcp_prompt(description="A prompt whose hook faults")
    def faulting_prompt(actor: Any, method_name: str, data: Any) -> Any:
        raise DbError("property read", SECRET)

    results = await _call(
        app, method="prompts/get", params={"name": "faulting_prompt", "arguments": {}}
    )
    for envelope, response in results:
        assert "result" not in envelope
        assert envelope["error"]["code"] == -32603
        assert response.status_code == 503


def _wrapped_fault() -> RuntimeError:
    try:
        raise DbError("property read", SECRET)
    except DbError as fault:
        try:
            raise RuntimeError(f"could not load {SECRET}") from fault
        except RuntimeError as wrapped:
            return wrapped


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "message", "status"),
    [
        (ValueError(f"bad value for {SECRET}"), None, 200),
        (_wrapped_fault(), "Service temporarily unavailable", 503),
    ],
    ids=["other", "wrapped_fault"],
)
@pytest.mark.parametrize("method", ["prompts/get", "resources/read"])
async def test_a_failing_prompt_or_resource_hook_answers_fixed_text(
    exc: Exception, message: str | None, status: int, method: str
) -> None:
    """The exception's text was on the wire in 4.0.0rc2 ("Prompt generation
    failed: ..."). The answer stays a JSON-RPC error; its message is fixed,
    and a hook that wrapped a store fault gets the fault's answer."""
    app = _app("tool_failure_other_hooks", ValueError("never raised"))

    @app.method_hook("raising_prompt")
    @mcp_prompt(description="A prompt whose hook raises")
    def raising_prompt(actor: Any, method_name: str, data: Any) -> Any:
        raise exc

    @app.method_hook("raising_resource")
    @mcp_resource(uri_template="test://raising", description="A raising resource")
    def raising_resource(actor: Any, method_name: str, data: Any) -> Any:
        raise exc

    if method == "prompts/get":
        params: dict[str, Any] = {"name": "raising_prompt", "arguments": {}}
        expected = "Prompt generation failed"
    else:
        params = {"uri": "test://raising"}
        expected = "Resource read failed"
    for envelope, response in await _call(app, method=method, params=params):
        assert "result" not in envelope, envelope
        assert envelope["error"]["code"] == -32603
        assert envelope["error"]["message"] == (message or expected)
        assert SECRET not in repr(envelope)
        assert response.status_code == status


@pytest.mark.asyncio
async def test_an_unknown_tool_is_still_a_protocol_error() -> None:
    app = _app("tool_failure_unknown", ValueError("never raised"))
    for envelope, _ in await _call(app, "no_such_tool"):
        assert envelope["error"]["code"] == -32601
