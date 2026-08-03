"""Tests for the shared tools/call result formatter.

``structuredContent`` is **opt-in**: it is emitted only when a hook sets that
key explicitly, and only when it is a JSON object. Extra top-level keys are
never promoted.

Covers:
- extra top-level keys are NOT promoted into structuredContent.
- explicit structuredContent pass-through, and its object-only requirement.
- structuredContent omitted for older negotiated versions, even when explicit.
- _meta preservation.
- legacy text wrapping for non-content results.
- sync (MCPHandler) / async (AsyncMCPHandler) parity.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import (
    MCPHandler,
    _output_schema_warned,
    format_call_tool_result,
)
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.mcp import mcp_tool
from actingweb.permission_evaluator import PermissionResult
from actingweb.runtime_context import RuntimeContext
from tests.mcp_helpers import make_mcp_config, make_mcp_webobj


class TestFormatCallToolResult:
    """Unit tests on the pure formatter."""

    def test_content_with_extras_does_not_promote_structured_content(self) -> None:
        """Extras are dropped, never swept into structuredContent."""
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "success": True,
            "memory_type": "note",
        }
        out = format_call_tool_result(result, "2025-06-18")
        # The text payload must survive byte-for-byte...
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False
        # ...and the non-empty extras must NOT appear anywhere.
        assert "structuredContent" not in out
        assert "success" not in out
        assert "memory_type" not in out

    def test_latest_version_does_not_promote_structured_content(self) -> None:
        """Even on the newest revision, extras are not promoted."""
        result = {"content": [{"type": "text", "text": "ok"}], "count": 3}
        out = format_call_tool_result(result, "2025-11-25")
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]

    def test_extras_alongside_explicit_structured_content(self) -> None:
        """Only the explicit key is emitted; extras are never merged in.

        Guards the deleted promotion branch from returning: if extras were
        swept, ``sibling`` would appear in the output.
        """
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"explicit": 1},
            "sibling": "should-not-appear",
        }
        out = format_call_tool_result(result, "2025-11-25")
        assert out["structuredContent"] == {"explicit": 1}
        assert "sibling" not in out["structuredContent"]

    @pytest.mark.parametrize(
        "bad_value",
        [
            [{"item": 1}],
            "a string",
            42,
        ],
        ids=["list", "str", "int"],
    )
    def test_non_dict_structured_content_dropped_with_warning(
        self, bad_value: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        """MCP requires structuredContent to be an object; anything else warns."""
        caplog.set_level(logging.WARNING, logger="actingweb.handlers.mcp")
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": bad_value,
            "extra": 1,
        }
        out = format_call_tool_result(result, "2025-11-25")
        # Dropped, and the extras are NOT promoted in its place.
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert "MCP requires a JSON object" in caplog.text
        assert type(bad_value).__name__ in caplog.text

    def test_explicit_none_structured_content_is_absent_and_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``structuredContent: None`` means "nothing structured", not an error.

        Unlike a list or string, ``None`` carries no payload, so nothing is
        lost by dropping it, and ``{"structuredContent": x or None}`` is a
        legitimate way to express an absent value. Both reference clients read
        a null ``structuredContent`` as absent. Warning here would be a false
        positive, so this is deliberate — but the key must be omitted entirely
        rather than emitted as ``null``, because some clients discard text
        blocks whenever the key is present at all.
        """
        caplog.set_level(logging.WARNING, logger="actingweb.handlers.mcp")
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": None,
            "extra": 1,
        }
        out = format_call_tool_result(result, "2025-11-25")
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert caplog.text == ""

    def test_explicit_structured_content_suppressed_on_old_version(self) -> None:
        """The version gate suppresses even an explicitly-set structuredContent."""
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"explicit": 1},
        }
        out = format_call_tool_result(result, "2025-03-26")
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]

    def test_old_version_omits_structured_content(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "success": True,
        }
        out = format_call_tool_result(result, "2024-11-05")
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False

    def test_explicit_structured_content_passthrough(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"explicit": 1},
            "ignored_extra": "x",
        }
        out = format_call_tool_result(result, "2025-06-18")
        # Explicit structuredContent wins; extras are NOT merged in.
        assert out["structuredContent"] == {"explicit": 1}

    def test_meta_is_preserved_not_swept(self) -> None:
        """_meta is forwarded as its own field, never folded into structuredContent."""
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "_meta": {"trace": "abc"},
            "structuredContent": {"explicit": 1},
        }
        out = format_call_tool_result(result, "2025-06-18")
        assert out["_meta"] == {"trace": "abc"}
        # _meta must not appear inside structuredContent.
        assert out["structuredContent"] == {"explicit": 1}
        assert "_meta" not in out["structuredContent"]

    def test_isError_true_preserved(self) -> None:
        result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
        out = format_call_tool_result(result, "2025-06-18")
        assert out["isError"] is True
        assert "structuredContent" not in out

    def test_content_only_no_structured_content(self) -> None:
        result = {"content": [{"type": "text", "text": "ok"}]}
        out = format_call_tool_result(result, "2025-11-25")
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False
        assert "structuredContent" not in out
        assert "_meta" not in out

    def test_plain_dict_legacy_text_wrap(self) -> None:
        out = format_call_tool_result({"status": "deleted"}, "2025-11-25")
        assert out["content"][0]["type"] == "text"
        assert "deleted" in out["content"][0]["text"]
        assert "structuredContent" not in out

    def test_bare_value_legacy_text_wrap(self) -> None:
        out = format_call_tool_result("hello", "2025-11-25")
        assert out["content"][0]["type"] == "text"
        assert "hello" in out["content"][0]["text"]


class TestOutputSchemaWarning:
    """A declared output_schema with no structuredContent is an author error.

    Both reference clients reject such a result with
    ``Tool X has an output schema but did not return structured content``, so
    the library warns at call time — the only point where it can tell whether
    the hook actually produced structured output.
    """

    SCHEMA = {"type": "object", "properties": {"count": {"type": "integer"}}}

    @pytest.fixture(autouse=True)
    def _reset_warn_cache(self) -> None:
        """The once-per-tool guard is module state and outlives each test.

        Without this, whether a test sees its warning depends on which other
        test ran first — a real flake under parallel execution.
        """
        _output_schema_warned.clear()

    @pytest.fixture(autouse=True)
    def _capture_warnings(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger="actingweb.handlers.mcp")

    def test_declared_schema_without_structured_content_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = {"content": [{"type": "text", "text": "ok"}]}
        format_call_tool_result(
            result, "2025-06-18", output_schema=self.SCHEMA, tool_name="counter"
        )
        assert "declares an output_schema" in caplog.text
        assert "counter" in caplog.text

    def test_declared_schema_with_structured_content_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The false-positive guard that motivated call-time over tools/list."""
        result = {
            "content": [{"type": "text", "text": '{"count": 3}'}],
            "structuredContent": {"count": 3},
        }
        format_call_tool_result(
            result, "2025-06-18", output_schema=self.SCHEMA, tool_name="good_tool"
        )
        assert caplog.text == ""

    def test_error_result_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        """Clients skip output-schema validation on error results."""
        result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
        format_call_tool_result(
            result, "2025-06-18", output_schema=self.SCHEMA, tool_name="failing_tool"
        )
        assert caplog.text == ""

    def test_no_declared_schema_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = {"content": [{"type": "text", "text": "ok"}], "extra": 1}
        format_call_tool_result(result, "2025-06-18", tool_name="schemaless_tool")
        assert caplog.text == ""

    def test_warns_only_once_per_tool(self, caplog: pytest.LogCaptureFixture) -> None:
        result = {"content": [{"type": "text", "text": "ok"}]}
        for _ in range(3):
            format_call_tool_result(
                result, "2025-06-18", output_schema=self.SCHEMA, tool_name="repeated"
            )
        assert caplog.text.count("declares an output_schema") == 1

    def test_distinct_tools_each_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        result = {"content": [{"type": "text", "text": "ok"}]}
        for name in ("tool_a", "tool_b"):
            format_call_tool_result(
                result, "2025-06-18", output_schema=self.SCHEMA, tool_name=name
            )
        assert caplog.text.count("declares an output_schema") == 2

    def test_old_version_with_explicit_structured_content_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression guard for the version clause.

        The gate strips an explicit ``structuredContent`` below 2025-06-18.
        Without the version clause a correctly-written hook would warn on every
        single call from every old client.
        """
        result = {
            "content": [{"type": "text", "text": '{"count": 3}'}],
            "structuredContent": {"count": 3},
        }
        format_call_tool_result(
            result, "2025-03-26", output_schema=self.SCHEMA, tool_name="old_client_tool"
        )
        assert caplog.text == ""

    def test_old_version_without_structured_content_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing the author can fix, nothing the client will reject."""
        result = {"content": [{"type": "text", "text": "ok"}]}
        format_call_tool_result(
            result, "2025-03-26", output_schema=self.SCHEMA, tool_name="old_plain_tool"
        )
        assert caplog.text == ""

    def test_legacy_branch_with_declared_schema_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The legacy wrap never emits structuredContent, so it always warns."""
        format_call_tool_result(
            {"status": "ok"},
            "2025-06-18",
            output_schema=self.SCHEMA,
            tool_name="legacy_tool",
        )
        assert "legacy_tool" in caplog.text

    def test_legacy_error_with_declared_schema_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Phase 3's honoured isError also suppresses the warning here."""
        format_call_tool_result(
            {"isError": True, "error": "boom"},
            "2025-06-18",
            output_schema=self.SCHEMA,
            tool_name="legacy_error_tool",
        )
        assert caplog.text == ""

    def test_explicit_none_with_declared_schema_still_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The ``None`` exemption is scoped to the *non-object* warning only.

        ``structuredContent: None`` is silently treated as absent (see
        ``test_explicit_none_structured_content_is_absent_and_silent``) — but
        when the tool also *declares* an ``output_schema`` there is a real
        contract being violated, and a strict client will reject the result.
        This pins that the two warnings stay independent, so silencing one
        never silences the other.
        """
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": None,
        }
        format_call_tool_result(
            result, "2025-06-18", output_schema=self.SCHEMA, tool_name="null_schema"
        )
        assert "declares an output_schema" in caplog.text
        assert "null_schema" in caplog.text
        # The non-object warning must NOT have fired.
        assert "MCP requires a JSON object" not in caplog.text

    def test_two_argument_call_still_works(self) -> None:
        """Existing call sites that pass only two arguments are unaffected."""
        out = format_call_tool_result(
            {"content": [{"type": "text", "text": "ok"}]}, "2025-06-18"
        )
        assert out == {"content": [{"type": "text", "text": "ok"}], "isError": False}


class TestLegacyWrapIsError:
    """The legacy branch honours an explicit isError — and only an explicit one.

    Before this, a hook returning ``{"isError": True, ...}`` with no ``content``
    key reached the wire with no ``isError`` field at all, so a failure was
    reported to the client as a success.
    """

    def test_explicit_is_error_true_honoured(self) -> None:
        out = format_call_tool_result({"isError": True, "error": "boom"}, "2025-11-25")
        assert out["isError"] is True
        # Exact string: str(result) must stay byte-identical to prior releases,
        # so isError deliberately appears both in the text and as a field.
        assert out["content"] == [
            {"type": "text", "text": "{'isError': True, 'error': 'boom'}"}
        ]

    def test_explicit_is_error_false_honoured(self) -> None:
        out = format_call_tool_result({"isError": False, "status": "ok"}, "2025-11-25")
        assert out["isError"] is False

    def test_absent_is_error_stays_absent(self) -> None:
        """Existing hooks that never set isError see no wire change at all."""
        out = format_call_tool_result({"status": "deleted"}, "2025-11-25")
        assert "isError" not in out
        assert out["content"] == [{"type": "text", "text": "{'status': 'deleted'}"}]

    def test_error_key_alone_does_not_infer_is_error(self) -> None:
        """An ``error`` key is NOT a signal; isError is honoured, never inferred.

        The known consumer's ``MCPResponse.error()`` returns ``{"error": {...}}``
        on its normal error path — inferring here would silently flip the shape
        of every one of those.
        """
        out = format_call_tool_result({"error": "boom"}, "2025-11-25")
        assert "isError" not in out

    def test_bare_value_has_no_is_error(self) -> None:
        out = format_call_tool_result("hello", "2025-11-25")
        assert "isError" not in out
        assert out["content"] == [{"type": "text", "text": "{'result': 'hello'}"}]

    def test_truthy_non_bool_is_error_coerced(self) -> None:
        """Matches the content branch, which also runs the value through bool()."""
        out = format_call_tool_result({"isError": "yes"}, "2025-11-25")
        assert out["isError"] is True

    def test_falsy_non_bool_is_error_coerced(self) -> None:
        out = format_call_tool_result({"isError": 0}, "2025-11-25")
        assert out["isError"] is False

    def test_legacy_branch_does_not_preserve_meta(self) -> None:
        """Documented asymmetry with the content branch: _meta is not forwarded."""
        out = format_call_tool_result({"_meta": {"trace": "abc"}}, "2025-11-25")
        assert "_meta" not in out


class TestSyncAsyncParity:
    """The sync and async handlers must format identical results identically."""

    @pytest.mark.asyncio
    async def test_sync_async_parity_with_extras(self) -> None:
        app = ActingWebApp(
            aw_type="urn:actingweb:test:mcp_format",
            database="dynamodb",
            fqdn="test.example.com",
        ).with_devtest(enable=True)

        @app.action_hook("store")
        @mcp_tool(description="Store something")
        def store_hook(actor, action_name, data):
            return {
                "content": [{"type": "text", "text": "stored"}],
                "isError": False,
                "success": True,
                "memory_type": "note",
            }

        class MockActorObj:
            id = "actor_parity"
            creator = "test@example.com"
            properties: dict = {}

        mock_actor = ActorInterface(MockActorObj())  # type: ignore[arg-type]
        # A resolved peer id, since Phase 3 fail-closed authorization denies
        # tools/call outright with no trust relationship. This test is about
        # result-shape parity, not permissions, so pair it with an
        # allow-everything evaluator rather than a real trust relationship.
        RuntimeContext(mock_actor).set_mcp_context(
            client_id="test-client", trust_relationship=None, peer_id="test-peer"
        )
        evaluator = Mock()
        evaluator.evaluate_permission = Mock(return_value=PermissionResult.ALLOWED)

        # Negotiated version that supports structuredContent.
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        request_data = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "store", "arguments": {}},
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

        assert sync_result == async_result
        # The hook returns non-empty extras (success, memory_type) that are NOT
        # named structuredContent, so nothing structured reaches the wire and the
        # prose survives intact.
        assert "structuredContent" not in sync_result["result"]
        assert sync_result["result"]["content"] == [{"type": "text", "text": "stored"}]
