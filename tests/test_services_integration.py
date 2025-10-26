"""Integration tests for service registry propagation and hooks."""

from types import SimpleNamespace
from unittest.mock import Mock

from actingweb.handlers.services import ServicesHandler
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp


def _create_app_with_service() -> ActingWebApp:
    """Helper to build an app with a demo service registered."""
    app = ActingWebApp(
        aw_type="urn:actingweb:test:service",
        fqdn="test.local",
    )
    app.add_service(
        name="crm_service",
        client_id="client",
        client_secret="secret",
        scopes=["crm.read"],
        auth_uri="https://auth.example.com/authorize",
        token_uri="https://auth.example.com/token",
    )
    return app


def test_action_hook_receives_service_client():
    app = _create_app_with_service()
    registry = app.get_service_registry()

    mock_client = Mock(name="crm_client")
    registry.get_service_client = Mock(return_value=mock_client)

    core_actor = SimpleNamespace(
        config=app.get_config(),
        id="actor-123",
        property=Mock(),
        store=Mock(),
    )
    actor_interface = ActorInterface(core_actor)  # type: ignore[arg-type]

    captured = {}

    @app.action_hook("sync_contacts")
    def sync_contacts(actor, action_name, data):  # pyright: ignore[reportUnusedFunction]
        captured["client"] = actor.services.get("crm_service")
        return {"status": "ok"}

    result = app.hooks.execute_action_hooks("sync_contacts", actor_interface, {}, None)

    assert result == {"status": "ok"}
    assert captured["client"] is mock_client
    registry.get_service_client.assert_called_once_with("crm_service", actor_interface)


def test_services_handler_callback_uses_registry():
    app = _create_app_with_service()
    registry = app.get_service_registry()

    mock_client = Mock()
    mock_client.handle_callback.return_value = True
    registry.get_service_client = Mock(return_value=mock_client)

    config = app.get_config()
    request = SimpleNamespace(cookies={}, headers={})
    response = Mock()
    webobj = SimpleNamespace(request=request, response=response)

    handler = ServicesHandler(webobj, config, hooks=app.hooks)  # type: ignore[arg-type]

    actor_core = SimpleNamespace(
        id="actor-123",
        config=config,
        property=Mock(),
        store=Mock(),
    )
    handler.require_authenticated_actor = Mock(return_value=actor_core)

    result = handler.get("actor-123", "crm_service", code="auth-code", state="opaque-state")

    assert result == {
        "success": True,
        "message": "Successfully connected to crm_service",
        "service": "crm_service",
    }

    registry.get_service_client.assert_called_once()
    name_arg, actor_interface_arg = registry.get_service_client.call_args[0]
    assert name_arg == "crm_service"
    assert isinstance(actor_interface_arg, ActorInterface)
    assert actor_interface_arg._service_registry is registry

    mock_client.handle_callback.assert_called_once_with("auth-code", "opaque-state")
