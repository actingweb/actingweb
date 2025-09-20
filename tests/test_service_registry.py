"""Tests for service registry and actor services."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from actingweb.interface.app import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface


def test_register_and_get_service_client():
    app = ActingWebApp(aw_type="urn:actingweb:test", fqdn="example.com")
    registry = app.get_service_registry()

    service_config = registry.register_service_from_dict(
        "demo",
        {
            "client_id": "id",
            "client_secret": "secret",
            "scopes": ["scope"],
            "auth_uri": "https://auth",
            "token_uri": "https://token",
            "base_api_url": "https://api",
        },
    )

    assert registry.is_service_registered("demo")
    assert "demo" in registry.list_services()

    mock_client = Mock()
    registry.get_service_client = Mock(return_value=mock_client)

    core_actor = SimpleNamespace(
        config=app.get_config(),
        id="actor42",
        property=Mock(),
        store=Mock(),
    )
    actor_interface = ActorInterface(core_actor, service_registry=registry)

    client = actor_interface.services.get("demo")

    assert client is mock_client
    registry.get_service_client.assert_called_once_with("demo", actor_interface)


def test_actor_services_cache():
    app = ActingWebApp(aw_type="urn:actingweb:test", fqdn="example.com")
    registry = app.get_service_registry()
    registry.register_service_from_dict(
        "cached",
        {
            "client_id": "id",
            "client_secret": "secret",
            "scopes": ["scope"],
            "auth_uri": "https://auth",
            "token_uri": "https://token",
        },
    )

    core_actor = SimpleNamespace(
        config=app.get_config(),
        id="actor42",
        property=Mock(),
        store=Mock(),
    )
    actor_interface = ActorInterface(core_actor, service_registry=registry)

    mock_client = Mock(name="cached_client")
    registry.get_service_client = Mock(return_value=mock_client)

    first = actor_interface.services.get("cached")
    second = actor_interface.services.get("cached")

    assert first is second is mock_client
    registry.get_service_client.assert_called_once_with("cached", actor_interface)


def test_service_registry_templates():
    app = ActingWebApp(aw_type="urn:actingweb:test", fqdn="example.com")
    registry = app.get_service_registry()

    registry.register_dropbox("id", "secret")
    registry.register_github("id2", "secret2")

    services = registry.list_services()
    assert "dropbox" in services
    assert "github" in services

    dropbox = services["dropbox"]
    assert dropbox.client_id == "id"
    assert dropbox.token_uri


def test_actor_interface_services_raises_without_registry():
    app = ActingWebApp(aw_type="urn:actingweb:test", fqdn="example.com")
    core_actor = SimpleNamespace(config=None, id="actor", property=None, store=None)
    actor = ActorInterface(core_actor, service_registry=None)

    with pytest.raises(RuntimeError):
        _ = actor.services
