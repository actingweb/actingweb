"""The unsupported-version rejection is a dual-era protocol signal. Guard it.

**Read this before changing anything in
``MCPHandler._resolve_request_protocol_version``.**

ActingWeb speaks up to ``2025-11-25`` and is therefore a *legacy-era* MCP
server. The MCP revision published 2026-07-28 removes ``initialize`` and
protocol-level sessions, and defines how a **dual-era** client decides which
kind of server it is talking to: it sends a modern-shaped request first, and
reads the error code it gets back. Codes in the MCP-reserved
``-32020``–``-32099`` range identify a *modern* server; *"anything else
identifies a legacy server"*, and the client then falls back to ``initialize``
— which is exactly what works against us.

So the HTTP 400 + JSON-RPC ``-32600`` this server answers an unknown version
with is not merely spec-compliant error handling. **It is the fallback trigger
every dual-era client depends on**, and it was written without anyone intending
it as one.

The change that would break it looks like a correctness improvement: returning
the spec-shaped ``-32022`` (``UnsupportedProtocolVersion``) with a
``data.supported`` array. That identifies us as a modern server, so the client
stops falling back and instead retries a modern-shaped request declaring
``2025-11-25`` — a version that *requires* ``initialize``. A working fallback
becomes a retry loop, for every dual-era client at once, with nothing failing
loudly on our side.

These tests exist so that change fails CI instead of shipping. They assert the
*absence* of the structured payload, not just the presence of the code — the
absence is the load-bearing half, and no test asserted it before 2026-08-15.

See ``thoughts/todo/mcp-2026-07-28-dual-era-support.md``.
"""

import logging

import pytest

from actingweb.handlers.mcp import MCPHandler
from actingweb.mcp.protocol import SUPPORTED_PROTOCOL_VERSIONS
from tests.mcp_helpers import make_mcp_handler

# The MCP-reserved JSON-RPC error range. A code inside it identifies a modern
# server to a dual-era client; a code outside it identifies a legacy one.
MCP_RESERVED_RANGE = range(-32099, -32019)

# A revision newer than anything this server speaks. Deliberately not the real
# 2026-07-28 string: the point is any unknown future version, and pinning the
# real one would make this test look like it tracks that revision's support.
FUTURE_VERSION = "2099-01-01"


def _reject(version: str = FUTURE_VERSION) -> tuple[MCPHandler, dict]:
    """POST a `ping` carrying an unsupported version header."""
    handler = make_mcp_handler(headers={"MCP-Protocol-Version": version})
    return handler, handler.post({"jsonrpc": "2.0", "id": 1, "method": "ping"})


class TestLegacyEraSignalIsPreserved:
    """The three properties a dual-era client reads. All must hold together."""

    def test_status_is_400(self) -> None:
        handler, _ = _reject()
        assert handler.response.status_code == 400

    def test_error_code_is_32600(self) -> None:
        _, result = _reject()
        assert result["error"]["code"] == -32600

    def test_error_code_is_outside_the_mcp_reserved_range(self) -> None:
        """This is *why* -32600 works, stated so a future change can't miss it.

        Swapping in any code from the reserved range — -32022 being the
        tempting one — makes us look like a modern server to every dual-era
        client. Asserting the range, not just the constant, catches the whole
        class rather than one value.
        """
        _, result = _reject()
        assert result["error"]["code"] not in MCP_RESERVED_RANGE

    def test_error_carries_no_data_payload(self) -> None:
        """The load-bearing assertion.

        A ``data.supported`` array is the marker of a modern
        ``UnsupportedProtocolVersion`` response. Its absence is what keeps the
        fallback working, so its absence is what gets asserted.
        """
        _, result = _reject()
        assert "data" not in result["error"], (
            "The unsupported-version error must carry no `data` payload — see "
            "this module's docstring. Supported versions belong in `message`."
        )


class TestSupportedVersionsAreNamedInTheMessage:
    """Name the versions, but only where no client branches on them."""

    def test_message_names_every_supported_version(self) -> None:
        """A client that cannot fall forward can only surface this string.

        The spec makes this argument for the mirror-image case: a server SHOULD
        name its versions because "this message may be the only diagnostic they
        can surface to users."
        """
        _, result = _reject()
        message = result["error"]["message"]
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            assert version in message, f"{version} missing from {message!r}"

    def test_message_still_names_the_rejected_version(self) -> None:
        _, result = _reject("2098-12-31")
        assert "2098-12-31" in result["error"]["message"]


class TestRejectionIsVisibleInTelemetry:
    """One rejection is a healthy handshake; a stream of them is the trigger."""

    def test_rejection_logs_at_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """The documented trigger for taking on dual-era support is a
        *sustained* stream of these from one origin — a client retrying instead
        of falling back, i.e. modern-only. At debug level that trigger is
        invisible in ordinary telemetry and would first surface as a user
        report.
        """
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            _reject()

        rejections = [
            r
            for r in caplog.records
            if "Unsupported MCP-Protocol-Version" in r.getMessage()
            or "unsupported MCP-Protocol-Version" in r.getMessage()
        ]
        assert rejections, "the rejection produced no WARNING record"
        assert all(r.levelno >= logging.WARNING for r in rejections)

    def test_supported_versions_are_in_the_log_line_too(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """So an operator reading the log knows what the client should send."""
        with caplog.at_level(logging.WARNING, logger="actingweb.handlers.mcp"):
            _reject()

        logged = " ".join(r.getMessage() for r in caplog.records)
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            assert version in logged


class TestSupportedVersionsStillNegotiateNormally:
    """The guard above must not turn into "reject everything"."""

    @pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
    def test_a_supported_version_is_accepted(self, version: str) -> None:
        handler = make_mcp_handler(headers={"MCP-Protocol-Version": version})
        result = handler.post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert "result" in result
        assert handler._negotiated_version == version
