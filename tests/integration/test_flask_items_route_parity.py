"""
Flask route parity: /<actor_id>/properties/<name>/items must exist on the
Flask integration too, not just FastAPI (Phase 3 of
thoughts/plans/2026-08-08-property-list-index-integrity.md). Uses Flask's
in-process test client (no server thread needed) against the live
dynamodb-test/postgres-test containers the session fixtures in
conftest.py already start.
"""

import base64
import os

import pytest
from flask import Flask

from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def client(worker_info):  # noqa: ARG001 -- ensures docker_services/setup_database ran
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:flask_items_parity",
        database=DATABASE_BACKEND,
        fqdn="flask-parity-test.example.com",
        proto="http://",
    ).with_web_ui(enable=False)

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    aw_app.integrate_flask(flask_app)

    return flask_app.test_client()


class TestFlaskItemsRoute:
    def test_items_get_returns_indexed_shape(self, client):
        response = client.post("/", json={"creator": "flask-parity@example.com"})
        assert response.status_code == 201
        actor_data = response.get_json()
        actor_id = actor_data["id"]
        auth_headers = _basic_auth_header(
            actor_data["creator"], actor_data["passphrase"]
        )

        try:
            response = client.post(
                f"/{actor_id}/properties",
                json={"notes": {"_type": "list"}},
                headers=auth_headers,
            )
            assert response.status_code == 201

            for item in ["a", "b"]:
                response = client.post(
                    f"/{actor_id}/properties/notes/items",
                    json={"action": "add", "item_value": item},
                    headers=auth_headers,
                )
                assert response.status_code == 201

            response = client.get(
                f"/{actor_id}/properties/notes/items", headers=auth_headers
            )
            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 2
            assert data["items"] == [
                {"index": 0, "item": "a"},
                {"index": 1, "item": "b"},
            ]
        finally:
            client.delete(f"/{actor_id}", headers=auth_headers)
