"""Tests for MCP handler session-key derivation.

The ``_get_session_key()`` method is the cache key used to store
``client_info`` from ``initialize`` and look it up on every subsequent
request. Two clients sharing one OAuth2 credential must not collide on
this key — otherwise the second client's ``initialize`` overwrites the
first client's cached identity (eval round-11 Finding X).

The fix: prefer the MCP HTTP-streamable ``Mcp-Session-Id`` header, with
the legacy IP+UA hash retained as a fallback only when the header is
genuinely absent.
"""

from tests.mcp_helpers import make_mcp_handler


class TestSessionKeyPrefersMcpSessionIdHeader:
    """``Mcp-Session-Id`` header is the canonical per-connection id."""

    def test_distinct_session_ids_produce_distinct_keys(self) -> None:
        a = make_mcp_handler({"Mcp-Session-Id": "session-A"})
        b = make_mcp_handler({"Mcp-Session-Id": "session-B"})
        key_a = a._get_session_key()
        key_b = b._get_session_key()
        assert key_a != key_b
        assert key_a and "session-A" in key_a
        assert key_b and "session-B" in key_b

    def test_header_lookup_is_case_insensitive(self) -> None:
        h_upper = make_mcp_handler({"Mcp-Session-Id": "abc"})
        h_lower = make_mcp_handler({"mcp-session-id": "abc"})
        assert h_upper._get_session_key() == h_lower._get_session_key()

    def test_header_takes_precedence_over_ipua_fallback(self) -> None:
        """Same IP+UA, different Mcp-Session-Id → distinct keys.

        This is the Finding X regression case: two clients on one
        credential go through the same proxy (same IP) with similar
        UAs but get unique ``Mcp-Session-Id`` values per connection.
        Before the fix they collided; after the fix they're distinct.
        """
        common = {"User-Agent": "Mozilla/5.0 shared-proxy-ua-prefix-string"}
        a = make_mcp_handler({**common, "Mcp-Session-Id": "session-A"})
        b = make_mcp_handler({**common, "Mcp-Session-Id": "session-B"})
        assert a._get_session_key() != b._get_session_key()


class TestSessionKeyFallback:
    """Without the header there is no session key.

    The old fallback, ``remote_addr + hash(User-Agent[:50])``, was shared by
    every client with the same User-Agent prefix (nothing sets
    ``remote_addr``), so one client's unauthenticated ``initialize`` could
    name another user's connection. An authenticated request without the
    header is keyed by its bearer token instead.
    """

    def test_no_header_has_no_session_key(self) -> None:
        h = make_mcp_handler({"User-Agent": "ua-1"})
        assert h._get_session_key() is None

    def test_same_user_agent_never_shares_a_key(self) -> None:
        a = make_mcp_handler({"User-Agent": "ua-1"})
        b = make_mcp_handler({"User-Agent": "ua-1"})
        assert a._get_session_key() is None
        assert b._get_session_key() is None


class TestClientInfoCacheIsolation:
    """End-to-end: storing under one session must not affect another."""

    def test_distinct_sessions_get_independent_cache_entries(self) -> None:
        from actingweb.handlers import mcp as mcp_module

        # Two handlers, two distinct session ids, same IP+UA otherwise.
        common = {"User-Agent": "shared-ua"}
        h_a = make_mcp_handler({**common, "Mcp-Session-Id": "sess-A"})
        h_b = make_mcp_handler({**common, "Mcp-Session-Id": "sess-B"})

        # Reset the in-process cache for a clean assertion.
        mcp_module._mcp_client_info_cache.clear()

        h_a._store_mcp_client_info_temporarily({"name": "Anthropic/ClaudeAI"})
        h_b._store_mcp_client_info_temporarily({"name": "claude-code"})

        info_a = h_a._resolve_live_client_info()
        info_b = h_b._resolve_live_client_info()

        assert info_a == {"name": "Anthropic/ClaudeAI"}
        assert info_b == {"name": "claude-code"}

    def test_second_initialize_does_not_overwrite_first_session(self) -> None:
        """The exact Finding X regression: second client's initialize
        must not overwrite the first client's cached client_info when
        they share IP + UA but have distinct session ids."""
        from actingweb.handlers import mcp as mcp_module

        common = {"User-Agent": "Anthropic-proxy-ua-50-chars-XXXXXXXXXXXXXXXXXXX"}
        first = make_mcp_handler({**common, "Mcp-Session-Id": "claude-ai-sess"})
        second = make_mcp_handler({**common, "Mcp-Session-Id": "claude-code-sess"})

        mcp_module._mcp_client_info_cache.clear()

        first._store_mcp_client_info_temporarily({"name": "Anthropic/ClaudeAI"})
        second._store_mcp_client_info_temporarily({"name": "claude-code"})

        # The first session's cached identity must still be intact.
        info_first = first._resolve_live_client_info()
        assert info_first is not None
        assert info_first["name"] == "Anthropic/ClaudeAI"


class TestTransportSessionIdNoSynthFallback:
    """``_resolve_transport_session_id`` is the *public* per-connection id
    surfaced to MCP tool callers (via ``MCPContext.transport_session_id``) and
    is distinct from ``_get_session_key`` which is an internal cache key. The
    cache key falls back to ``<ip>:<hash(UA)>`` when the ``Mcp-Session-Id``
    header is absent; the public id must NOT. Earlier revisions did fall back,
    and on transports lacking the header, ``remote_addr`` AND ``User-Agent``
    (observed for Claude.ai web sessions) the synthetic id degenerated to the
    string ``"unknown:0"``.
    """

    def test_returns_header_value_when_present(self) -> None:
        h = make_mcp_handler({"Mcp-Session-Id": "session-xyz"})
        assert h._resolve_transport_session_id() == "session-xyz"

    def test_returns_none_when_header_absent(self) -> None:
        """No header → ``None``, NOT the synthetic IP+UA fallback."""
        h = make_mcp_handler({"User-Agent": "ua-1"})
        result = h._resolve_transport_session_id()
        assert result is None
        # Guard against regression to the synthetic ``<ip>:<hash>`` form.
        assert not (isinstance(result, str) and ":" in result)

    def test_returns_none_when_request_is_minimal(self) -> None:
        """The exact Claude.ai-web case: no header, no UA, no remote_addr.
        Previously yielded ``"unknown:0"``; now returns ``None`` so
        callers can detect "this transport has no per-connection id."""
        h = make_mcp_handler({})
        result = h._resolve_transport_session_id()
        assert result is None
        assert result != "unknown:0"

    def test_header_lookup_is_case_insensitive(self) -> None:
        h_upper = make_mcp_handler({"Mcp-Session-Id": "abc"})
        h_lower = make_mcp_handler({"mcp-session-id": "abc"})
        assert (
            h_upper._resolve_transport_session_id()
            == h_lower._resolve_transport_session_id()
            == "abc"
        )
