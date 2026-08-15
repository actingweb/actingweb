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

from actingweb.handlers import mcp as mcp_module
from actingweb.handlers.mcp import MCPHandler
from actingweb.mcp.protocol import SUPPORTED_PROTOCOL_VERSIONS
from tests.mcp_helpers import make_mcp_handler


@pytest.fixture(autouse=True)
def _clean_rejection_telemetry() -> None:
    """Per-origin counters are module-global; don't let tests see each other."""
    mcp_module._reset_unsupported_version_telemetry()


# The MCP-reserved JSON-RPC error range. A code inside it identifies a modern
# server to a dual-era client; a code outside it identifies a legacy one.
MCP_RESERVED_RANGE = range(-32099, -32019)

# A revision newer than anything this server speaks. Deliberately not the real
# 2026-07-28 string: the point is any unknown future version, and pinning the
# real one would make this test look like it tracks that revision's support.
FUTURE_VERSION = "2099-01-01"


def _reject(
    version: str = FUTURE_VERSION, *, user_agent: str | None = None
) -> tuple[MCPHandler, dict]:
    """POST a `ping` carrying an unsupported version header."""
    headers = {"MCP-Protocol-Version": version}
    if user_agent is not None:
        headers["User-Agent"] = user_agent
    handler = make_mcp_handler(headers=headers)
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
    """One rejection is a healthy handshake; a stream of them is the trigger.

    The level grading is the point. The rejection is answered on an
    *unauthenticated* path, so logging every one at WARNING would hand any
    anonymous caller a log-volume and alert-noise lever — and it would also
    bury the actionable case among the healthy ones. Both were raised in review
    on PR #129.
    """

    def test_a_single_rejection_is_info_not_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One rejection per origin *is* the normal legacy handshake."""
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            _reject(user_agent="some-client/1.0")

        records = [
            r for r in caplog.records if "MCP-Protocol-Version" in r.getMessage()
        ]
        assert records, "the rejection produced no log record at all"
        assert all(r.levelno == logging.INFO for r in records), (
            "a lone rejection is the healthy handshake and must not alert"
        )

    def test_a_sustained_stream_escalates_to_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The documented trigger for taking on dual-era support.

        A client retrying instead of falling back is modern-only. Until this
        escalation existed the trigger could only surface as a user report.
        """
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            for _ in range(mcp_module._UNSUPPORTED_VERSION_ESCALATE_AT):
                _reject(user_agent="modern-only-client/2.0")

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, (
            "expected exactly one escalation, not one per request"
        )
        assert "modern-only-client/2.0" in warnings[0].getMessage()

    def test_escalation_fires_once_per_window_not_once_per_request(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Bounding the volume is what makes WARNING safe on a pre-auth path."""
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            for _ in range(mcp_module._UNSUPPORTED_VERSION_ESCALATE_AT * 4):
                _reject(user_agent="noisy-client/1.0")

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1

    def test_distinct_origins_do_not_escalate_each_other(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """N clients each handshaking once is healthy and must stay quiet.

        This is the distinction the origin exists for: without it, N one-off
        rejections and one client retrying N times are the same log.
        """
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            for i in range(mcp_module._UNSUPPORTED_VERSION_ESCALATE_AT * 2):
                _reject(user_agent=f"legacy-client-{i}/1.0")

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_the_origin_is_named_in_the_log_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            _reject(user_agent="claude-desktop/9.9")

        assert any("claude-desktop/9.9" in r.getMessage() for r in caplog.records)

    def test_a_session_id_wins_over_the_user_agent_as_origin(self) -> None:
        """`Mcp-Session-Id` is per-connection, so it is the more specific key."""
        handler = make_mcp_handler(
            headers={"Mcp-Session-Id": "abc123", "User-Agent": "some-client/1.0"}
        )
        assert handler._rejection_origin() == "session:abc123"

    def test_no_identifying_headers_still_yields_a_key(self) -> None:
        handler = make_mcp_handler(headers={})
        assert handler._rejection_origin() == "unidentified"

    def test_supported_versions_are_in_the_log_line_too(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """So an operator reading the log knows what the client should send."""
        with caplog.at_level(logging.INFO, logger="actingweb.handlers.mcp"):
            _reject(user_agent="some-client/1.0")

        logged = " ".join(r.getMessage() for r in caplog.records)
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            assert version in logged


class TestOriginTrackingIsBounded:
    """The origin key comes from client-supplied headers on a pre-auth path.

    An anonymous caller can therefore mint unlimited distinct origins. Without
    a cap the counter dict would be a memory lever — a worse bug than the
    log-volume one it was added to fix.
    """

    def test_tracked_origins_are_capped(self) -> None:
        cap = mcp_module._UNSUPPORTED_VERSION_MAX_ORIGINS
        for i in range(cap + 50):
            mcp_module._record_unsupported_version_rejection(f"ua:attacker-{i}")

        assert len(mcp_module._unsupported_version_origins) <= cap

    def test_counting_is_per_origin(self) -> None:
        assert mcp_module._record_unsupported_version_rejection("ua:a") == (1, False)
        assert mcp_module._record_unsupported_version_rejection("ua:b") == (1, False)
        assert mcp_module._record_unsupported_version_rejection("ua:a")[0] == 2


class TestSupportedVersionsStillNegotiateNormally:
    """The guard above must not turn into "reject everything"."""

    @pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
    def test_a_supported_version_is_accepted(self, version: str) -> None:
        handler = make_mcp_handler(headers={"MCP-Protocol-Version": version})
        result = handler.post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert "result" in result
        assert handler._negotiated_version == version
