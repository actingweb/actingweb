"""MCP authorization discovery: the 401 challenge and the advertised scopes.

Both are pure metadata, and both are load-bearing for whether a client ever
starts the OAuth flow at all — a live Codex session (2026-08-28) configured
the server, restarted, and was never prompted to sign in, reporting the
protected-resource metadata as malformed.
"""

from actingweb.aw_web_request import AWResponse
from actingweb.config import Config
from actingweb.handlers.mcp import mcp_www_authenticate
from actingweb.handlers.oauth2_endpoints import OAuth2EndpointsHandler
from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server


def _config() -> Config:
    return Config(proto="https://", fqdn="example.com")


def _endpoints_handler() -> OAuth2EndpointsHandler:
    """A handler with just the attributes the discovery methods touch."""
    handler = OAuth2EndpointsHandler.__new__(OAuth2EndpointsHandler)
    handler.config = _config()
    handler.response = AWResponse()
    return handler


def test_challenge_points_at_the_protected_resource_metadata():
    """RFC 9728 section 5.1 / MCP auth spec: the challenge must carry the
    discovery pointer. Without it a conformant client has to guess the
    well-known location, and at least one reports the metadata as malformed
    and never opens the sign-in window."""
    header = mcp_www_authenticate("https://example.com")

    assert (
        'resource_metadata="https://example.com/.well-known/oauth-protected-resource/mcp"'
        in header
    )


def test_challenge_keeps_the_token_invalidation_and_legacy_hints():
    header = mcp_www_authenticate("https://example.com")

    # RFC 6750 section 3.1 - makes clients drop a cached, now-invalid token.
    assert 'error="invalid_token"' in header
    assert header.startswith('Bearer realm="ActingWeb MCP"')
    # Non-standard, but clients already key off it - removing it is a break.
    assert 'authorization_uri="https://example.com/oauth/authorize"' in header


def test_every_mcp_401_site_uses_the_shared_challenge():
    """Three call sites emit this header, and the async handler is the one
    the FastAPI integration actually serves — the first fix missed it and the
    live endpoint still shipped a challenge with no discovery pointer."""
    import inspect

    from actingweb.handlers import async_mcp, mcp

    for module in (mcp, async_mcp):
        source = inspect.getsource(module)
        # The helper's own definition is the only place the literal may live.
        hand_rolled = source.count('error_description="Authentication required"')
        expected = 1 if module is mcp else 0
        assert hand_rolled == expected, (
            f"{module.__name__} hand-rolls the MCP 401 challenge instead of "
            "calling mcp_www_authenticate()"
        )


def test_authorization_server_metadata_advertises_offline_access():
    """Every authorization-code token response already carries a refresh
    token; advertising the scope stops clients that gate long-lived sessions
    on it from re-prompting."""
    server = ActingWebOAuth2Server(_config())

    metadata = server.handle_discovery_request()

    assert "offline_access" in metadata["scopes_supported"]
    assert "mcp" in metadata["scopes_supported"]
    assert "refresh_token" in metadata["grant_types_supported"]


def test_both_protected_resource_variants_advertise_offline_access():
    handler = _endpoints_handler()

    for metadata in (
        handler._handle_protected_resource_discovery(),
        handler._handle_protected_resource_mcp_discovery(),
    ):
        assert metadata["scopes_supported"] == ["mcp", "offline_access"]
        assert metadata["resource"] == "https://example.com/mcp"
