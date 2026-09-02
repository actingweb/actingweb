"""``GET /mcp/info`` on both integrations (3.14.4).

Reachable without authentication on both frameworks -- pinned so a later
change to that is deliberate -- and served from the one builder in
``handlers.mcp``, so the document reflects this app's configuration rather
than the demo's literals. Lives under tests/integration/ because the FastAPI
request path touches the database tables the session fixtures provision.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")
REMOVED_KEYS = ("tools_count", "prompts_count", "actor_lookup", "version")
AW_TYPE = "urn:actingweb:test:mcp_info_route"


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
        fqdn="mcp-info-route.example.com",
        proto="https://",
    ).with_mcp(server_name="emm")


def _check(body: dict) -> None:
    assert body["server_name"] == "emm"
    assert body["mcp_enabled"] is True
    assert body["description"] == f"ActingWeb app: {AW_TYPE}"
    assert body["supported_features"] == []
    assert body["authentication"]["resource_discovery_url"] == (
        "https://mcp-info-route.example.com/.well-known/oauth-protected-resource"
    )
    for key in REMOVED_KEYS:
        assert key not in body


class TestMcpInfoRoute:
    def test_flask(self, aw_app):
        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        aw_app.integrate_flask(flask_app)
        resp = flask_app.test_client().get("/mcp/info")
        assert resp.status_code == 200
        _check(resp.get_json())

    def test_fastapi(self, aw_app):
        fastapi_app = FastAPI()
        aw_app.integrate_fastapi(fastapi_app)
        resp = TestClient(fastapi_app).get("/mcp/info")
        assert resp.status_code == 200
        _check(resp.json())
