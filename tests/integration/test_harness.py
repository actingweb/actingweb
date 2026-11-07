"""
Minimal ActingWeb test harness.

This is a standalone FastAPI application using the ActingWeb library,
designed for integration testing. It's completely independent of
actingwebdemo and actingweb_mcp.

Note: Switched from Flask to FastAPI to support MCP endpoints which
require async/await functionality.
"""

import logging
import os

from fastapi import FastAPI

from actingweb.interface import ActingWebApp

# Suppress uvicorn access logs for cleaner test output
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_test_app(
    fqdn: str = "localhost:5555",
    proto: str = "http://",
    enable_oauth: bool = False,
    enable_mcp: bool = False,
    enable_devtest: bool = True,
    enable_subscription_processing: bool = False,
    subscription_config: dict | None = None,
    open_factory: bool = True,
    unique_creator: bool = False,
    *,
    sync_callbacks: bool = False,
    peer_capabilities: bool = False,
    peer_permissions: bool = False,
    peer_profile: bool = False,
    record: str | None = None,
) -> tuple[FastAPI, ActingWebApp]:
    """
    Create a minimal ActingWeb test harness.

    Args:
        fqdn: Fully qualified domain name for the test app
        proto: Protocol (http:// or https://)
        enable_oauth: Enable OAuth2 configuration
        enable_mcp: Enable MCP endpoints
        enable_devtest: Enable devtest endpoints (for proxy tests)
        enable_subscription_processing: Enable automatic subscription processing
        subscription_config: Optional config dict for subscription processing
        open_factory: Whether the actor factory (POST /) accepts requests
        unique_creator: ``with_unique_creator()``; the store must be enabled
            first (the ``unique_creator_app`` fixture does it)
        sync_callbacks, peer_capabilities, peer_permissions, peer_profile:
            the consumer's options, all off by default (the wire apps turn
            them on)
        record: when set, the name of this app in the wire recorder: every
            request it serves and every hook it runs is recorded
            (``tests/integration/_wire.py``)

    Returns:
        Tuple of (fastapi_app, actingweb_app)
    """
    # Create ActingWeb app with minimal configuration
    # Note: database=None lets DATABASE_BACKEND env var take precedence
    aw_app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:integration",
            database=None,  # Use DATABASE_BACKEND env var (set by conftest.py)
            fqdn=fqdn,
            proto=proto,
        )
        .with_unique_creator(False)
        .with_web_ui(enable=True)
        .with_devtest(enable=enable_devtest)
        # Explicit: the shared test_w0_ tables hold deliberate duplicate
        # creators (the adoption and squat tests), so the harness opts out
        # unless a test asks for uniqueness on its isolated store.
        .with_unique_creator(enable=unique_creator)
        .with_email_as_creator(enable=False)
        .with_open_factory(enable=open_factory)
        # Explicit for both backends: PostgreSQL never spans and has no item
        # ceiling at its defaults, so without this the PostgreSQL CI run
        # would not exercise the span and 413 paths DynamoDB takes.
        .with_list_item_limits(span_threshold=390_000, max_bytes=4 * 2**20)
    )

    # Optional: Add OAuth2 configuration for OAuth tests
    if enable_oauth:
        aw_app = aw_app.with_oauth(
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="openid email profile",
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            redirect_uri=f"{proto}{fqdn}/oauth/callback",
        )

    # Optional: Enable MCP for MCP tests
    if enable_mcp:
        aw_app = aw_app.with_mcp(enable=True)

    # The consumer's peer options (its application.py builder chain).
    if sync_callbacks:
        aw_app = aw_app.with_sync_callbacks(enable=True)
    if peer_profile:
        aw_app = aw_app.with_peer_profile(attributes=["displayname", "email"])
    if peer_capabilities:
        aw_app = aw_app.with_peer_capabilities(enable=True)
    if peer_permissions:
        aw_app = aw_app.with_peer_permissions(enable=True)

    # Optional: Enable subscription processing for subscription tests
    if enable_subscription_processing:
        config = subscription_config or {}
        aw_app = aw_app.with_subscription_processing(
            auto_sequence=config.get("auto_sequence", True),
            auto_storage=config.get("auto_storage", True),
            auto_cleanup=config.get("auto_cleanup", True),
            gap_timeout_seconds=config.get("gap_timeout_seconds", 5.0),
            max_pending=config.get("max_pending", 100),
        )

    # Register callback hook for custom www path template rendering test
    @aw_app.callback_hook("www")
    def handle_www_paths(actor, name, data):
        """
        Handle custom www paths to test template rendering from callback hooks.

        When a callback hook returns {"template": "...", "data": {...}},
        the integration should render that template with the provided data.
        """
        path = data.get("path", "")

        if path == "custom":
            # Test custom template rendering
            return {
                "template": "aw-actor-www-custom.html",
                "data": {
                    "custom_message": "Hello from callback hook!",
                },
            }

        return False

    # Register the legacy @app.subscription_hook decorator so tests can verify
    # it actually fires on the callbacks handler's legacy fallback path (used
    # when .with_subscription_processing() is not enabled). Regression guard
    # for actingweb/handlers/callbacks.py's legacy branch, which previously
    # accepted registrations here but never invoked them.
    @aw_app.subscription_hook
    def handle_raw_subscription_callback(actor, subscription, peer_id, data):
        actor.properties["subscription_hook_fired"] = {
            "peer_id": peer_id,
            "target": subscription.get("target"),
            "data": data,
        }
        # Only claim to have handled callbacks that carry inline data. A
        # low-granularity callback (URL only, no "data") can't be processed by
        # this simple probe -- claiming it anyway would make the legacy
        # fallback branch report success (204) for callbacks other
        # low-granularity-fetch integration tests expect to see rejected or
        # handled via the auto-sequencing path instead.
        return bool(data)

    if record:
        _add_recording_hooks(aw_app)
        _add_subscriber_trust_type(aw_app)

    # Create FastAPI app
    fastapi_app = FastAPI(title="ActingWeb Test Harness")

    # Get templates directory for FastAPI
    template_dir = os.path.join(os.path.dirname(__file__), "templates")

    # Integrate with FastAPI (this will automatically initialize system actors)
    aw_app.integrate_fastapi(fastapi_app, templates_dir=template_dir)

    if record:
        from ._wire import RecordingMiddleware, register_wire_host

        # Outermost: Starlette builds user middleware around the routes, so
        # this one sees every request, including one a handler fails on.
        fastapi_app.add_middleware(RecordingMiddleware, host=record)
        register_wire_host(fqdn, record)

    return fastapi_app, aw_app


# The consumer's ``subscriber`` access rows, verbatim
# (``../actingweb_mcp/application.py:811-869``): GET only on
# ``subscriptions/<id>/<subid>``.
SUBSCRIBER_ACL_RULES: list[tuple[str, str, str]] = [
    ("subscriptions/<id>", "POST", "a"),
    ("subscriptions/<id>/<subid>", "GET", "a"),
    ("properties", "GET", "a"),
    ("callbacks", "", "a"),
    ("trust/<type>/<id>", "GET", "a"),
    ("methods", "POST", "a"),
    ("permissions/<id>", "GET", "a"),
]

# The two rows the consumer adds when it adopts 3.16 (the security plan's
# migration step): PUT and DELETE on the path the GET row covers.
SUBSCRIBER_ADOPTION_ROWS: list[tuple[str, str, str]] = [
    ("subscriptions/<id>/<subid>", "PUT", "a"),
    ("subscriptions/<id>/<subid>", "DELETE", "a"),
]


def _add_subscriber_trust_type(aw_app: ActingWebApp) -> None:
    """The consumer's ``subscriber`` trust type, rows verbatim, and the same
    type with its adoption rows as ``subscriber_adopted``.

    ``../actingweb_mcp/application.py:811-869``: explicit grants, read-only,
    and access rows that grant GET only on ``subscriptions/<id>/<subid>``.
    A wire pair made with ``relationship="subscriber"`` exercises them;
    ``relationship="subscriber_adopted"`` adds ``SUBSCRIBER_ADOPTION_ROWS``
    (a row whose method does not match falls through to the next, so the
    order between the GET row and the two added rows does not matter).
    """
    from actingweb.permission_integration import AccessControlConfig

    access = AccessControlConfig(aw_app.get_config())
    for name, rules in (
        ("subscriber", SUBSCRIBER_ACL_RULES),
        ("subscriber_adopted", SUBSCRIBER_ACL_RULES + SUBSCRIBER_ADOPTION_ROWS),
    ):
        access.add_trust_type(
            name=name,
            display_name="Actor Subscription",
            description="The consumer's subscriber type (wire harness copy).",
            permissions={
                "properties": {
                    "patterns": ["displayname", "email"],
                    "operations": ["read"],
                    "excluded_patterns": [],
                },
                "methods": [],
                "tools": [],
                "resources": [],
                "prompts": [],
            },
            oauth_scope=None,
            acl_rules=list(rules),
        )


def _add_recording_hooks(aw_app: ActingWebApp) -> None:
    """Hooks a wire app runs: each records what it was called with.

    Plus one method shaped like the consumer's memory import
    (``../actingweb_mcp/api/memory_import.py``): an asynchronous handler on the
    server's loop that suspends one subtarget, clears and refills a list
    through the interface, and resumes.
    """
    from ._wire import record_event

    @aw_app.subscription_data_hook("properties")
    def record_subscription_data(actor, peer_id, target, data, sequence, callback_type):
        record_event(
            "subscription_data",
            actor=actor.id,
            peer=peer_id,
            target=target,
            data=data,
            sequence=sequence,
            type=callback_type,
        )

    @aw_app.lifecycle_hook("subscription_deleted")
    def record_subscription_deleted(actor, **kwargs):
        record_event(
            "subscription_deleted",
            actor=actor.id,
            peer=kwargs.get("peer_id"),
            subscriptionid=kwargs.get("subscription_id"),
            initiated_by_peer=kwargs.get("initiated_by_peer"),
        )

    @aw_app.lifecycle_hook("trust_deleted")
    def record_trust_deleted(actor, **kwargs):
        record_event(
            "trust_deleted",
            actor=actor.id,
            peer=kwargs.get("peer_id"),
            relationship=kwargs.get("relationship"),
            initiated_by_peer=kwargs.get("initiated_by_peer"),
        )

    @aw_app.callback_hook("permissions")
    def record_permissions(actor, name, data):
        record_event(
            "permissions",
            actor=actor.id,
            granting_actor_id=data.get("granting_actor_id"),
            permission_changes=data.get("permission_changes"),
            data=data.get("data"),
        )
        return True

    @aw_app.callback_hook("wire_ping")
    def record_ping(actor, name, data):
        """An application callback on the generic branch (``/callbacks/wire_ping``)."""
        record_event("callback", actor=actor.id, name=name, method=data.get("method"))
        return {"pong": True}

    @aw_app.method_hook("wire_import")
    async def wire_import(actor, method_name, data):
        """Suspend one list's subtarget, clear and refill it, resume."""
        name = data["list"]
        items = data.get("items", [])
        actor.subscriptions.suspend(target="properties", subtarget=name)
        try:
            lst = getattr(actor.property_lists, name)
            if data.get("clear", True):
                lst.clear()
            for item in items:
                lst.append(item)
        finally:
            sent = actor.subscriptions.resume(target="properties", subtarget=name)
        return {
            "callbacks_sent": sent,
            "length": len(getattr(actor.property_lists, name)),
        }
