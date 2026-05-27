"""Tests for MCP protocol version negotiation (Phase 1).

Covers:
- ``initialize`` echoes the client's requested protocolVersion when supported,
  otherwise returns the server's latest supported version.
- The ``MCP-Protocol-Version`` request header is resolved per request, defaults
  when absent, and yields HTTP 400 when present-but-unsupported.
- GET discovery reports the full supported-version set.
"""

import pytest

from actingweb import aw_web_request, config
from actingweb.handlers.mcp import MCPHandler
from actingweb.mcp.protocol import (
    DEFAULT_NEGOTIATED_VERSION,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    negotiate_protocol_version,
    supports_structured_content,
)


def _make_config() -> config.Config:
    cfg = config.Config()
    cfg.fqdn = "test.example.com"
    cfg.proto = "https://"
    cfg.aw_type = "urn:actingweb:test:mcp_version"
    cfg.devtest = True
    return cfg


def _make_handler(headers: dict[str, str] | None = None) -> MCPHandler:
    webobj = aw_web_request.AWWebObj(
        url="https://test.example.com/mcp",
        params={},
        body="",
        headers=headers or {},
        cookies={},
    )
    return MCPHandler(webobj, _make_config(), hooks=None)


def _initialize(handler: MCPHandler, protocol_version: str | None) -> dict:
    params: dict = {"clientInfo": {"name": "test-client", "version": "1.0"}}
    if protocol_version is not None:
        params["protocolVersion"] = protocol_version
    return handler.post(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}
    )


class TestNegotiationHelpers:
    """Pure-function checks on the negotiation helpers."""

    @pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
    def test_supported_versions_echo(self, version: str) -> None:
        assert negotiate_protocol_version(version) == version

    def test_unsupported_returns_latest(self) -> None:
        assert negotiate_protocol_version("2099-01-01") == LATEST_PROTOCOL_VERSION

    def test_none_returns_latest(self) -> None:
        assert negotiate_protocol_version(None) == LATEST_PROTOCOL_VERSION

    def test_structured_content_gate(self) -> None:
        # Introduced in 2025-06-18; older revisions must not advertise it.
        assert supports_structured_content("2025-06-18") is True
        assert supports_structured_content("2025-11-25") is True
        assert supports_structured_content("2025-03-26") is False
        assert supports_structured_content("2024-11-05") is False
        assert supports_structured_content(None) is False
        assert supports_structured_content("not-a-version") is False


class TestInitializeNegotiation:
    """initialize must follow the MCP lifecycle version-negotiation rules."""

    @pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
    def test_initialize_echoes_supported_version(self, version: str) -> None:
        handler = _make_handler()
        result = _initialize(handler, version)
        assert result["result"]["protocolVersion"] == version
        # Negotiated value is recorded for the rest of the request.
        assert handler._negotiated_version == version

    def test_initialize_unsupported_returns_latest(self) -> None:
        handler = _make_handler()
        result = _initialize(handler, "2099-01-01")
        assert result["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION

    def test_initialize_missing_version_returns_latest(self) -> None:
        handler = _make_handler()
        result = _initialize(handler, None)
        assert result["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION

    def test_initialize_legacy_2024_client_still_supported(self) -> None:
        # Backward compatibility: a 2024-11-05-only client gets 2024-11-05 back.
        handler = _make_handler()
        result = _initialize(handler, "2024-11-05")
        assert result["result"]["protocolVersion"] == "2024-11-05"


class TestProtocolVersionHeader:
    """The MCP-Protocol-Version header is resolved/validated per request."""

    def _ping(self, handler: MCPHandler) -> dict:
        return handler.post({"jsonrpc": "2.0", "id": 2, "method": "ping"})

    def test_header_absent_uses_default(self) -> None:
        handler = _make_handler(headers={})
        result = self._ping(handler)
        assert "result" in result
        assert handler._negotiated_version == DEFAULT_NEGOTIATED_VERSION

    def test_header_supported_is_recorded(self) -> None:
        handler = _make_handler(headers={"MCP-Protocol-Version": "2025-06-18"})
        result = self._ping(handler)
        assert "result" in result
        assert handler._negotiated_version == "2025-06-18"

    def test_header_lowercase_is_recorded(self) -> None:
        handler = _make_handler(headers={"mcp-protocol-version": "2025-11-25"})
        self._ping(handler)
        assert handler._negotiated_version == "2025-11-25"

    def test_header_unsupported_returns_400(self) -> None:
        handler = _make_handler(headers={"MCP-Protocol-Version": "2099-01-01"})
        result = self._ping(handler)
        assert "error" in result
        assert result["error"]["code"] == -32600
        assert handler.response.status_code == 400


class TestGetDiscovery:
    """GET discovery should advertise the full supported-version set."""

    def test_get_reports_supported_versions(self) -> None:
        handler = _make_handler()
        result = handler.get()
        assert result["version"] == LATEST_PROTOCOL_VERSION
        assert result["transport"]["supported_versions"] == list(
            SUPPORTED_PROTOCOL_VERSIONS
        )
