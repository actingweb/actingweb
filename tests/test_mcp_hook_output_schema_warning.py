"""`output_schema` on an action hook never reaches MCP. Say so at listing time.

A hook's output schema can be supplied three ways and only one of them reaches
`tools/list`:

===========================================  ========================
How the schema is supplied                   Advertised as outputSchema
===========================================  ========================
``@mcp_tool(output_schema=S)``               yes
``@app.action_hook(..., output_schema=S)``   **no**
``TypedDict`` return annotation (auto)       **no**
===========================================  ========================

``tools/list`` reads ``_mcp_metadata``, set only by ``@mcp_tool``.
``action_hook`` writes a separate ``HookMetadata`` to ``_hook_metadata``, and
the ``TypedDict`` derivation happens inside ``get_hook_metadata``. Nothing
bridges the two, so an author who declares a schema either of the latter two
ways reasonably believes their tool advertises it. It does not, and the rc4
missing-``structuredContent`` warning stays silent for them too, because it is
gated on the same metadata.

**Merging them is not the fix, and that is the point of warning instead.**
Merging would newly advertise ``outputSchema`` for every ``TypedDict``-annotated
tool, and each one that does not also return ``structuredContent`` would start
failing on spec-conforming clients — breaking a population that works today.
That decision is tied to the ``structuredContent`` research; the warning
forecloses none of it.

See ``thoughts/todo/action-hook-output-schema-not-visible-to-mcp.md``.
"""

import logging

import pytest

from actingweb.handlers import mcp as mcp_module


@pytest.fixture(autouse=True)
def _clear_warned_registry() -> None:
    """The warning is once-per-tool-per-process; don't let tests mask each other."""
    mcp_module._hook_output_schema_warned.clear()


def _hook_with_hook_only_schema():
    """A hook whose schema lives where MCP will not look."""
    from actingweb.interface.hooks import HookMetadata

    def my_tool(actor, action_name, params):  # pragma: no cover - never called
        return {}

    my_tool._hook_metadata = HookMetadata(  # type: ignore[attr-defined]
        description="a tool whose schema stops at the hook",
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )
    return my_tool


def _hook_with_no_schema_anywhere():
    def plain_tool(actor, action_name, params):  # pragma: no cover - never called
        return {}

    return plain_tool


class TestWarningFires:
    def test_a_hook_only_schema_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            mcp_module._warn_hook_output_schema_not_advertised_once(
                _hook_with_hook_only_schema(), "my_tool"
            )

        assert any("my_tool" in r.getMessage() for r in caplog.records)
        assert any("outputSchema" in r.getMessage() for r in caplog.records)

    def test_it_warns_once_per_tool_not_once_per_list(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`tools/list` runs per request; a per-call warning would be a flood."""
        hook = _hook_with_hook_only_schema()
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            for _ in range(5):
                mcp_module._warn_hook_output_schema_not_advertised_once(hook, "my_tool")

        assert len([r for r in caplog.records if "my_tool" in r.getMessage()]) == 1


class TestWarningCannotFalsePositive:
    """The condition is knowable at listing time and has no ambiguous case.

    This is what distinguishes it from the missing-``structuredContent``
    warning, which rc4 deliberately kept off ``tools/list``: that one depends on
    what a hook *returns*, which listing cannot know. This one depends only on
    which metadata slot the schema sits in.
    """

    def test_no_schema_anywhere_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            mcp_module._warn_hook_output_schema_not_advertised_once(
                _hook_with_no_schema_anywhere(), "plain_tool"
            )

        assert not [r for r in caplog.records if "plain_tool" in r.getMessage()]

    def test_a_bare_function_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            mcp_module._warn_hook_output_schema_not_advertised_once(
                lambda: None, "lambda_tool"
            )

        assert not [r for r in caplog.records if "lambda_tool" in r.getMessage()]

    def test_metadata_lookup_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A diagnostic must never break the listing it annotates."""
        import actingweb.interface.hooks as hooks_module

        def boom(func):
            raise RuntimeError("metadata subsystem unavailable")

        monkeypatch.setattr(hooks_module, "get_hook_metadata", boom)
        # No exception, and nothing recorded as warned.
        mcp_module._warn_hook_output_schema_not_advertised_once(
            _hook_with_hook_only_schema(), "my_tool"
        )
        assert "my_tool" not in mcp_module._hook_output_schema_warned
