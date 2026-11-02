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
    assert body == {**UNAVAILABLE_BODY, "code": UNAVAILABLE_BODY["error"]}
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

    def test_a_bug_while_handling_a_fault_answers_500(self) -> None:
        # Raised inside ``except DbError`` without ``from``: the DbError is
        # only its __context__, so it is a bug, not an availability fault.
        app, client = self._client()

        @app.route("/custom-bug")
        def custom_bug() -> str:  # pyright: ignore[reportUnusedFunction]
            try:
                raise DbError("custom read", ACTOR_ID)
            except DbError:
                raise RuntimeError("bug in the fault handler")  # noqa: B904

        response = client.get("/custom-bug")
        assert response.status_code == 500
        assert "Retry-After" not in response.headers


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

    def test_a_bug_while_handling_a_fault_answers_500(self) -> None:
        app = FastAPI()

        @app.get("/custom-bug")
        async def custom_bug() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            try:
                raise DbError("custom read", ACTOR_ID)
            except Exception:
                raise RuntimeError("bug in the fault handler")  # noqa: B904

        _app, client = self._client(app)
        response = client.get("/custom-bug")
        assert response.status_code == 500
        assert "retry-after" not in response.headers


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

    def test_a_fault_reached_only_through_context_is_not_found(self) -> None:
        try:
            try:
                raise DbError("inner")
            except DbError:
                raise RuntimeError("unrelated bug")  # noqa: B904
        except RuntimeError as outer:
            assert outer.__context__ is not None
            assert find_db_error(outer) is None

    def test_permanence_ignores_a_backend_error_reached_only_through_context(
        self,
    ) -> None:
        import psycopg

        from actingweb.interface.integrations._errors import is_permanent

        try:
            try:
                raise psycopg.errors.DataError("bad value")
            except psycopg.errors.DataError:
                raise DbError("property write")  # noqa: B904
        except DbError as fault:
            assert fault.__cause__ is None
            assert is_permanent(fault) is False

        try:
            try:
                raise psycopg.errors.DataError("bad value")
            except psycopg.errors.DataError as e:
                raise DbError("property write") from e
        except DbError as fault:
            assert is_permanent(fault) is True


@pytest.mark.parametrize("broad", [False, True])
def test_a_bug_while_handling_a_fault_answers_500_in_both_forms(broad: bool) -> None:
    """``except DbError`` and a broad ``except Exception`` around a fault,
    each re-raising without ``from``, on Flask and FastAPI."""

    def bug() -> None:
        try:
            raise DbError("custom read", ACTOR_ID)
        except Exception if broad else DbError:  # noqa: B030
            raise RuntimeError("bug in the fault handler")  # noqa: B904

    flask_app = Flask(__name__)
    _aw_app().integrate_flask(flask_app)

    @flask_app.route("/both-forms")
    def flask_route() -> str:  # pyright: ignore[reportUnusedFunction]
        bug()
        return ""

    assert flask_app.test_client().get("/both-forms").status_code == 500

    fastapi_app = FastAPI()

    @fastapi_app.get("/both-forms")
    async def fastapi_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        bug()
        return {}

    _aw_app().integrate_fastapi(fastapi_app)
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    assert client.get("/both-forms").status_code == 500
