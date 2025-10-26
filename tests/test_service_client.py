"""Tests for ServiceClient OAuth2 interactions."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from actingweb.interface.services.service_client import ServiceClient
from actingweb.interface.services.service_config import ServiceConfig


class _PropertyStore(dict):
    """Simple dict that always evaluates truthy for ServiceClient checks."""

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return True


@pytest.fixture()
def service_config() -> ServiceConfig:
    return ServiceConfig(
        name="demo",
        client_id="id",
        client_secret="secret",
        scopes=["scope"],
        auth_uri="https://auth",
        token_uri="https://token",
        base_api_url="https://api",
        revocation_uri="https://auth/revoke",
    )


@pytest.fixture()
def actor_interface():
    return SimpleNamespace(
        id="actor42",
        property=_PropertyStore(),
    )


@pytest.fixture()
def aw_config():
    return SimpleNamespace(proto="https://", fqdn="example.com")


def _make_response(status_code=200, json_data=None, text="OK"):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.content = b"" if json_data is None else b"{}"
    response.json.return_value = json_data or {}
    return response


def test_get_authorization_url(service_config, actor_interface, aw_config):
    client = ServiceClient(service_config, actor_interface, aw_config)
    url = client.get_authorization_url(state="abc")
    assert "https://auth" in url
    assert "state=" in url


def test_handle_callback_stores_tokens(service_config, actor_interface, aw_config):
    authenticator = Mock()
    authenticator.exchange_code_for_token.return_value = {
        "access_token": "token",
        "refresh_token": "refresh",
    }
    with patch("actingweb.interface.services.service_client.OAuth2Authenticator", return_value=authenticator):
        client = ServiceClient(service_config, actor_interface, aw_config)
        success = client.handle_callback("code", "state")

    assert success
    assert actor_interface.property["service_demo_access_token"] == "token"
    assert actor_interface.property["service_demo_refresh_token"] == "refresh"


def test_make_request_refreshes_token(service_config, actor_interface, aw_config):
    authenticator = Mock()
    authenticator.refresh_access_token.return_value = {
        "access_token": "new-token",
        "refresh_token": "new-refresh",
    }
    with patch("actingweb.interface.services.service_client.OAuth2Authenticator", return_value=authenticator):
        client = ServiceClient(service_config, actor_interface, aw_config)
        client._access_token = "expired"
        client._refresh_token = "refresh"

        ok_response = _make_response(json_data={"ok": True})
        expired_response = _make_response(status_code=401)

        with patch(
            "actingweb.interface.services.service_client.requests.request",
            side_effect=[expired_response, ok_response],
        ) as request_mock:
            result = client.get("/resource")

    assert result == {"ok": True}
    assert client._access_token == "new-token"
    _, kwargs = request_mock.call_args_list[-1]
    assert kwargs["headers"]["Authorization"] == "Bearer new-token"


def test_make_request_handles_failure(service_config, actor_interface, aw_config):
    with patch("actingweb.interface.services.service_client.OAuth2Authenticator"):
        client = ServiceClient(service_config, actor_interface, aw_config)
        client._access_token = "token"

        error_response = _make_response(status_code=500, text="error")
        with patch("actingweb.interface.services.service_client.requests.request", return_value=error_response):
            result = client.get("/resource")

    assert result is None


def test_revoke_tokens(service_config, actor_interface, aw_config):
    with patch("actingweb.interface.services.service_client.OAuth2Authenticator"):
        client = ServiceClient(service_config, actor_interface, aw_config)
        client._access_token = "token"
        client._refresh_token = "refresh"

    with patch("actingweb.interface.services.service_client.requests.post", return_value=_make_response()):
        success = client.revoke_tokens()

    assert success
    assert client._access_token is None
    assert client._refresh_token is None


def test_make_request_requires_base_url(actor_interface, aw_config):
    config = ServiceConfig(
        name="demo",
        client_id="id",
        client_secret="secret",
        scopes=["scope"],
        auth_uri="https://auth",
        token_uri="https://token",
    )
    with patch("actingweb.interface.services.service_client.OAuth2Authenticator"):
        client = ServiceClient(config, actor_interface, aw_config)
        client._access_token = "token"

        with pytest.raises(ValueError):
            client.get("relative")
