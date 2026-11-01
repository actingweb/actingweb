"""``POST /mcp`` with a body that is not JSON, or is empty, is ``-32700``.

Before authentication, in the branch that already answers ``-32600`` for a
body that is JSON but not an object. A well-formed request without
credentials still gets the 401 challenge.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import UNPARSEABLE_BODY
from actingweb.interface import ActingWebApp
from tests.mcp_helpers import make_mcp_config, make_mcp_handler, make_mcp_webobj


def test_the_sentinel_is_answered_with_a_parse_error() -> None:
    handler = make_mcp_handler()
    result = handler.post(UNPARSEABLE_BODY)
    assert handler.response.status_code == 400
    assert result["error"]["code"] == -32700
    assert result["error"]["message"] == "Parse error"
    assert result["id"] is None
    assert "WWW-Authenticate" not in handler.response.headers


def test_the_async_handler_answers_the_same() -> None:
    handler = AsyncMCPHandler(make_mcp_webobj(), make_mcp_config())
    result = asyncio.run(handler.post_async(UNPARSEABLE_BODY))
    assert handler.response.status_code == 400
    assert result["error"]["code"] == -32700


def test_a_json_array_is_still_invalid_request() -> None:
    handler = make_mcp_handler()
    result = handler.post([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert handler.response.status_code == 400
    assert result["error"]["code"] == -32600


def test_the_log_line_names_the_kind_not_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = make_mcp_handler()
    with caplog.at_level("INFO", logger="actingweb.handlers.mcp"):
        handler.post(UNPARSEABLE_BODY)
    assert any("empty or not JSON" in r.message for r in caplog.records)


def _app() -> ActingWebApp:
    return (
        ActingWebApp(
            aw_type="urn:actingweb:test:parse-error",
            database="dynamodb",
            fqdn="test.example.com",
            proto="https://",
        )
        .with_unique_creator(False)
        .with_mcp(True)
    )


class _FastAPIClient:
    def __init__(self) -> None:
        app = FastAPI()
        _app().integrate_fastapi(app)
        self._client = TestClient(app)

    def post(self, **kwargs: object) -> tuple[int, dict]:
        resp = self._client.post("/mcp", **kwargs)  # type: ignore[arg-type]
        self.headers = resp.headers
        return resp.status_code, resp.json()

    def post_raw(self, path: str, **kwargs: object) -> tuple[int, str]:
        resp = self._client.post(path, **kwargs)  # type: ignore[arg-type]
        return resp.status_code, resp.text


class _FlaskClient:
    def __init__(self) -> None:
        app = Flask(__name__)
        _app().integrate_flask(app)
        self._client = app.test_client()

    def post(self, **kwargs: object) -> tuple[int, dict]:
        resp = self._client.post("/mcp", **kwargs)
        self.headers = resp.headers
        return resp.status_code, resp.get_json()

    def post_raw(self, path: str, **kwargs: object) -> tuple[int, str]:
        resp = self._client.post(path, **kwargs)
        return resp.status_code, resp.get_data(as_text=True)


CLIENTS = [
    pytest.param(_FastAPIClient, id="fastapi"),
    pytest.param(_FlaskClient, id="flask"),
]


@pytest.mark.parametrize("make_client", CLIENTS)
@pytest.mark.parametrize("body", ["not json", "{'a': 1}", ""])
def test_unparseable_bodies_are_32700_before_auth(make_client: type, body: str) -> None:
    client = make_client()
    status, payload = client.post(
        data=body, headers={"Content-Type": "application/json"}
    )
    assert status == 400
    assert payload["error"]["code"] == -32700
    assert payload["id"] is None
    assert "WWW-Authenticate" not in client.headers  # no challenge for junk


@pytest.mark.parametrize("make_client", CLIENTS)
def test_an_unparseable_body_with_credentials_is_still_32700(
    make_client: type,
) -> None:
    status, payload = make_client().post(
        data="not json",
        headers={"Content-Type": "application/json", "Authorization": "Bearer abc"},
    )
    assert status == 400
    assert payload["error"]["code"] == -32700


@pytest.mark.parametrize("make_client", CLIENTS)
def test_a_form_body_on_a_non_mcp_route_is_not_a_json_rpc_error(
    make_client: type,
) -> None:
    status, text = make_client().post_raw(
        "/no-such-actor/properties",
        data="name=value",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status != 400
    assert "-32700" not in text


@pytest.mark.parametrize("make_client", CLIENTS)
def test_a_json_array_is_still_32600(make_client: type) -> None:
    status, payload = make_client().post(
        data=json.dumps([{"jsonrpc": "2.0", "id": 1}]),
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    assert payload["error"]["code"] == -32600


@pytest.mark.parametrize("make_client", CLIENTS)
def test_a_well_formed_unauthenticated_request_still_gets_the_challenge(
    make_client: type,
) -> None:
    status, _ = make_client().post(
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        headers={"Content-Type": "application/json"},
    )
    assert status == 401
