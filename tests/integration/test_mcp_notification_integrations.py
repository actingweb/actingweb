"""``POST /mcp`` answers on both integrations for messages that get no reply.

``test_mcp_basic.py::TestMCPNotifications`` pins the notification case through
``oauth2_client``, which serves FastAPI under uvicorn, so the Flask
integration's bodyless-202 branch had no test at all. This file drives both
frameworks through their in-process test clients, the same way
``test_mcp_info_route.py`` does.

The contract matters because a response body on a notification — even ``{}``
— is not a JSON-RPC message, and a strict client (the Codex CLI's ``rmcp``)
rejects it and tears the transport down. A client's JSON-RPC *response* is
given the same bodyless 202. Neither needs a token, but both still go through
``MCP-Protocol-Version`` validation: an unsupported version is a ``400``.

A body that is not one JSON object (a batch array) is rejected with ``400``
and a ``-32600`` error; it used to crash the handler and its error path with
an ``AttributeError``.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")
AW_TYPE = "urn:actingweb:test:mcp_notification_integrations"

NOTIFICATION = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
UNKNOWN_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/cancelled",
    "params": {},
}
CLIENT_RESPONSE = {"jsonrpc": "2.0", "id": 5, "result": {}}
CLIENT_ERROR_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 6,
    "error": {"code": -32601, "message": "Method not found"},
}
AS_A_REQUEST = {
    "jsonrpc": "2.0",
    "id": 7,
    "method": "notifications/initialized",
    "params": {},
}
BATCH = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, NOTIFICATION]

NO_REPLY_BODIES = [
    NOTIFICATION,
    UNKNOWN_NOTIFICATION,
    CLIENT_RESPONSE,
    CLIENT_ERROR_RESPONSE,
]
NO_REPLY_IDS = ["initialized", "unknown", "client-result", "client-error"]

# The transport requires 400 for any message carrying an unsupported version,
# notifications and client responses included.
UNSUPPORTED_VERSION = {"MCP-Protocol-Version": "1999-01-01"}


@pytest.fixture
def aw_app(worker_info):  # noqa: ARG001 -- ensures docker_services/setup_database ran
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type=AW_TYPE,
        database=DATABASE_BACKEND,
        fqdn="mcp-notification.example.com",
        proto="https://",
    ).with_mcp(server_name="emm")


@pytest.fixture
def flask_client(aw_app):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    aw_app.integrate_flask(flask_app)
    return flask_app.test_client()


@pytest.fixture
def fastapi_client(aw_app):
    fastapi_app = FastAPI()
    aw_app.integrate_fastapi(fastapi_app)
    return TestClient(fastapi_app)


class TestFlaskNotifications:
    @pytest.mark.parametrize("body", NO_REPLY_BODIES, ids=NO_REPLY_IDS)
    def test_message_is_accepted_with_no_body(self, flask_client, body):
        resp = flask_client.post("/mcp", json=body)

        assert resp.status_code == 202
        assert resp.data == b"", f"expected an empty body, got {resp.data!r}"
        assert "Content-Type" not in resp.headers, (
            "a bodyless 202 must not claim a content type, "
            f"got {resp.headers.get('Content-Type')!r}"
        )

    @pytest.mark.parametrize("body", NO_REPLY_BODIES, ids=NO_REPLY_IDS)
    def test_unsupported_protocol_version_is_refused(self, flask_client, body):
        resp = flask_client.post("/mcp", json=body, headers=UNSUPPORTED_VERSION)

        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_initialized_sent_as_a_request_still_gets_a_response(self, flask_client):
        resp = flask_client.post("/mcp", json=AS_A_REQUEST)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["id"] == 7
        assert body["result"] == {}

    def test_batch_is_rejected_not_crashed(self, flask_client):
        resp = flask_client.post("/mcp", json=BATCH)

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["id"] is None
        assert body["error"]["code"] == -32600


class TestFastAPINotifications:
    @pytest.mark.parametrize("body", NO_REPLY_BODIES, ids=NO_REPLY_IDS)
    def test_message_is_accepted_with_no_body(self, fastapi_client, body):
        resp = fastapi_client.post("/mcp", json=body)

        assert resp.status_code == 202
        assert resp.content == b"", f"expected an empty body, got {resp.content!r}"
        assert "content-type" not in resp.headers, (
            "a bodyless 202 must not claim a content type, "
            f"got {resp.headers.get('content-type')!r}"
        )

    @pytest.mark.parametrize("body", NO_REPLY_BODIES, ids=NO_REPLY_IDS)
    def test_unsupported_protocol_version_is_refused(self, fastapi_client, body):
        resp = fastapi_client.post("/mcp", json=body, headers=UNSUPPORTED_VERSION)

        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_initialized_sent_as_a_request_still_gets_a_response(self, fastapi_client):
        resp = fastapi_client.post("/mcp", json=AS_A_REQUEST)

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 7
        assert body["result"] == {}

    def test_batch_is_rejected_not_crashed(self, fastapi_client):
        resp = fastapi_client.post("/mcp", json=BATCH)

        assert resp.status_code == 400
        body = resp.json()
        assert body["id"] is None
        assert body["error"]["code"] == -32600
