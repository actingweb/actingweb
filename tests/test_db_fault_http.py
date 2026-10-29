"""A database fault answers 503 over HTTP, in both integrations (3.16).

``DbError`` is an availability fault: the answer is ``503`` with
``Retry-After: 5`` and a fixed body that never carries the exception text (it
can name an actor id). ``CreatorTaken`` is a conflict and answers ``409``.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from actingweb.db import get_actor
from actingweb.db.exceptions import CreatorTaken, DbError
from actingweb.interface import ActingWebApp
from actingweb.interface.integrations._errors import (
    UNAVAILABLE_BODY,
    find_db_error,
    map_db_error,
)

ACTOR_ID = "f00dfeedf00dfeedf00dfeedf00dfeed"


def _aw_app() -> ActingWebApp:
    return ActingWebApp(
        aw_type="urn:actingweb:test:db-fault-http",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_web_ui(enable=False)


def _actor_reads_fault() -> Any:
    """Every actor read raises DbError naming the actor, as a real one does."""
    cls = type(get_actor(_aw_app().get_config()))

    def faulting(self: Any, actor_id: str | None = None, **_k: Any) -> Any:
        raise DbError("actor get", actor_id)

    return mock.patch.object(cls, "get", faulting)


def _assert_unavailable(status: int, headers: Any, body: Any, text: str) -> None:
    assert status == 503
    assert headers.get("Retry-After") == "5"
    assert body == UNAVAILABLE_BODY
    assert ACTOR_ID not in text
    assert "Traceback" not in text


class TestFlask:
    def _client(self) -> tuple[Flask, Any]:
        app = Flask(__name__)
        _aw_app().integrate_flask(app)
        return app, app.test_client()

    def test_library_route_answers_503(self) -> None:
        _app, client = self._client()
        with _actor_reads_fault():
            response = client.get(
                f"/{ACTOR_ID}/meta", headers={"Accept": "application/json"}
            )
        _assert_unavailable(
            response.status_code,
            response.headers,
            response.get_json(),
            response.get_data(as_text=True),
        )

    def test_consumer_route_answers_503(self) -> None:
        app, client = self._client()

        @app.route("/custom-fault")
        def custom_fault() -> str:  # pyright: ignore[reportUnusedFunction]
            raise DbError("custom read", ACTOR_ID)

        response = client.get("/custom-fault")
        _assert_unavailable(
            response.status_code,
            response.headers,
            response.get_json(),
            response.get_data(as_text=True),
        )

    def test_creator_taken_answers_409(self) -> None:
        app, client = self._client()

        @app.route("/custom-conflict")
        def custom_conflict() -> str:  # pyright: ignore[reportUnusedFunction]
            raise CreatorTaken("someone@example.com")

        response = client.get("/custom-conflict")
        assert response.status_code == 409
        assert "Retry-After" not in response.headers
        assert response.get_json()["error"] == "conflict"


class TestFastAPI:
    def _client(self, app: FastAPI | None = None) -> tuple[FastAPI, TestClient]:
        # Consumer routes go on the app before integration: the library's
        # /{actor_id} routes would otherwise match them first.
        app = app or FastAPI()
        _aw_app().integrate_fastapi(app)
        return app, TestClient(app, raise_server_exceptions=False)

    def test_library_route_answers_503(self) -> None:
        _app, client = self._client()
        with _actor_reads_fault():
            response = client.get(
                f"/{ACTOR_ID}/meta", headers={"Accept": "application/json"}
            )
        _assert_unavailable(
            response.status_code, response.headers, response.json(), response.text
        )

    def test_consumer_route_answers_503(self) -> None:
        app = FastAPI()

        @app.get("/custom-fault")
        async def custom_fault() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            raise DbError("custom read", ACTOR_ID)

        _app, client = self._client(app)
        response = client.get("/custom-fault")
        _assert_unavailable(
            response.status_code, response.headers, response.json(), response.text
        )

    def test_creator_taken_answers_409(self) -> None:
        app = FastAPI()

        @app.get("/custom-conflict")
        async def custom_conflict() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            raise CreatorTaken("someone@example.com")

        _app, client = self._client(app)
        response = client.get("/custom-conflict")
        assert response.status_code == 409
        assert response.json()["error"] == "conflict"


class TestMapping:
    def test_a_wrapped_fault_is_still_found(self) -> None:
        try:
            try:
                raise DbError("inner")
            except DbError as e:
                raise RuntimeError("handler wrapped it") from e
        except RuntimeError as outer:
            assert isinstance(find_db_error(outer), DbError)

    def test_an_unrelated_error_is_not_mapped(self) -> None:
        from actingweb.aw_web_request import AWResponse

        response = AWResponse()
        assert map_db_error(response, ValueError("bad input")) is False
        assert response.status_code == 200

    @pytest.mark.parametrize("exc,status", [(DbError("x"), 503), (CreatorTaken(), 409)])
    def test_creator_taken_is_tested_before_db_error(
        self, exc: Exception, status: int
    ) -> None:
        from actingweb.aw_web_request import AWResponse

        response = AWResponse()
        assert map_db_error(response, exc)
        assert response.status_code == status
