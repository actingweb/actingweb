"""Callbacks nothing handles, ``/www`` paths nothing handles, and anonymous
webhooks (specification 1.5, ``thoughts/plans/2026-11-06-spec-1-5.md``
Phase 2).

In process on both integrations (Flask's test client and FastAPI's
``TestClient``) against the suite's database.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

SEEN: list[tuple[str, dict[str, Any]]] = []


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _aw_app(*, with_www: bool, with_wildcard: bool) -> ActingWebApp:
    app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:webhooks",
            database=DATABASE_BACKEND,
            fqdn="webhooks.example.com",
            proto="http://",
        )
        .with_unique_creator(False)
        .with_web_ui(enable=True)
    )

    @app.callback_hook("returns_none")
    def returns_none(actor: Any, name: str, data: Any) -> Any:
        SEEN.append((name, data))
        return None

    @app.callback_hook("returns_false")
    def returns_false(actor: Any, name: str, data: Any) -> Any:
        SEEN.append((name, data))
        return False

    @app.callback_hook("handled")
    def handled(actor: Any, name: str, data: Any) -> Any:
        SEEN.append((name, data))
        return {"ok": True}

    @app.callback_hook("incoming", allow_anonymous=True)
    def incoming(actor: Any, name: str, data: Any) -> Any:
        SEEN.append((name, data))
        return {"received": True}

    @app.callback_hook("refusing", allow_anonymous=True)
    def refusing(actor: Any, name: str, data: Any) -> Any:
        SEEN.append((name, data))
        return False

    if with_wildcard:

        @app.callback_hook("*")
        def wildcard(actor: Any, name: str, data: Any) -> Any:
            SEEN.append(("*" + name, data))
            return None

    if with_www:

        @app.callback_hook("www")
        def www(actor: Any, name: str, data: Any) -> Any:
            if data.get("path") == "known":
                return {"page": "known"}
            if data.get("path") == "nothing":
                return None
            return False

    return app


class _Client:
    def __init__(self, kind: str, *, with_www: bool, with_wildcard: bool) -> None:
        self.kind = kind
        aw = _aw_app(with_www=with_www, with_wildcard=with_wildcard)
        if kind == "flask":
            from flask import Flask

            flask_app = Flask(__name__)
            flask_app.config["TESTING"] = True
            aw.integrate_flask(flask_app)
            self._c: Any = flask_app.test_client()
        else:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            fastapi_app = FastAPI()
            aw.integrate_fastapi(fastapi_app)
            self._c = TestClient(fastapi_app, raise_server_exceptions=False)
        self.auth: dict[str, str] = {}
        self.actor_id = ""

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if "json" in kwargs:
            kwargs["data"] = json.dumps(kwargs.pop("json"))
            headers.setdefault("Content-Type", "application/json")
        if self.kind == "flask":
            return self._c.open(path, method=method, headers=headers, **kwargs)
        if "data" in kwargs:
            kwargs["content"] = kwargs.pop("data")
        return self._c.request(method, path, headers=headers, **kwargs)

    @staticmethod
    def text(r: Any) -> str:
        return r.get_data(as_text=True) if hasattr(r, "get_data") else r.text


def _make(
    kind: str, worker_info: dict, *, with_www: bool = False, with_wildcard: bool = False
) -> _Client:
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
    SEEN.clear()
    c = _Client(kind, with_www=with_www, with_wildcard=with_wildcard)
    r = c.request(
        "POST", "/", json={"creator": f"hooks-{uuid.uuid4().hex[:8]}@example.com"}
    )
    assert r.status_code == 201, c.text(r)
    data = json.loads(c.text(r))
    c.actor_id = data["id"]
    c.auth = _basic(data["creator"], data["passphrase"])
    return c


@pytest.fixture(params=["flask", "fastapi"])
def client(request: pytest.FixtureRequest, worker_info: dict) -> Iterator[_Client]:
    c = _make(request.param, worker_info)
    yield c
    c.request("DELETE", f"/{c.actor_id}", headers=c.auth)


@pytest.fixture(params=["flask", "fastapi"])
def wild(request: pytest.FixtureRequest, worker_info: dict) -> Iterator[_Client]:
    c = _make(request.param, worker_info, with_wildcard=True)
    yield c
    c.request("DELETE", f"/{c.actor_id}", headers=c.auth)


@pytest.fixture(params=["flask", "fastapi"])
def www(request: pytest.FixtureRequest, worker_info: dict) -> Iterator[_Client]:
    c = _make(request.param, worker_info, with_www=True)
    yield c
    c.request("DELETE", f"/{c.actor_id}", headers=c.auth)


def _cb(c: _Client, name: str) -> str:
    return f"/{c.actor_id}/callbacks/{name}"


# ---------------------------------------------------------------------------
# A callback name nothing handles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_an_authenticated_callback_with_no_hook_is_403(
    client: _Client, method: str
) -> None:
    r = client.request(method, _cb(client, "nothing_here"), headers=client.auth)
    assert r.status_code == 403


@pytest.mark.parametrize("name", ["returns_none", "returns_false"])
def test_a_hook_that_returns_a_falsy_value_keeps_todays_answer(
    client: _Client, name: str
) -> None:
    r = client.request("POST", _cb(client, name), json={"k": 1}, headers=client.auth)
    assert r.status_code == 200
    assert json.loads(client.text(r)) is False
    assert SEEN[-1][0] == name


def test_a_handled_callback_answers_its_result(client: _Client) -> None:
    r = client.request("POST", _cb(client, "handled"), json={}, headers=client.auth)
    assert r.status_code == 200
    assert json.loads(client.text(r)) == {"ok": True}
    assert SEEN[-1][1]["anonymous"] is False


def test_an_authenticated_body_that_is_not_an_object_is_not_a_500(
    client: _Client,
) -> None:
    r = client.request("POST", _cb(client, "handled"), json=[1, 2], headers=client.auth)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /www paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_an_unknown_www_path_with_no_hook_is_404(client: _Client, method: str) -> None:
    headers = {**client.auth, "Sec-Fetch-Site": "same-origin"}
    r = client.request(method, f"/{client.actor_id}/www/nowhere", headers=headers)
    assert r.status_code == 404


def test_a_www_hook_keeps_its_answers(www: _Client) -> None:
    headers = {**www.auth, "Sec-Fetch-Site": "same-origin"}
    r = www.request("GET", f"/{www.actor_id}/www/known", headers=headers)
    assert r.status_code == 200
    assert json.loads(www.text(r)) == {"page": "known"}


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("path", ["other", "nothing"])
def test_a_www_path_the_hook_does_not_handle_is_404(
    www: _Client, method: str, path: str
) -> None:
    """Owner 2026-11-16 (verification M7): a ``www`` hook's ``False`` or
    ``None`` is "not handled" and answers 404, not 200 with ``False``."""
    headers = {**www.auth, "Sec-Fetch-Site": "same-origin"}
    r = www.request(method, f"/{www.actor_id}/www/{path}", headers=headers)
    assert r.status_code == 404
    assert "False" not in www.text(r)


# ---------------------------------------------------------------------------
# Anonymous webhooks
# ---------------------------------------------------------------------------


def test_an_anonymous_post_runs_the_flagged_hook(client: _Client) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        json={"event": "x"},
        headers={"X-Signature": "abc"},
    )
    assert r.status_code == 200, client.text(r)
    name, data = SEEN[-1]
    assert name == "incoming"
    assert data["anonymous"] is True
    assert data["event"] == "x"
    assert json.loads(data["raw_body"]) == {"event": "x"}
    assert {k.lower(): v for k, v in data["headers"].items()}["x-signature"] == "abc"


def test_an_authenticated_caller_cannot_choose_headers_or_raw_body(
    client: _Client,
) -> None:
    """Verification 2026-11-16 (M1): the authenticated path took ``headers``
    and ``raw_body`` from the caller's JSON, so a hook that verifies a
    signature over ``raw_body`` checked what the caller chose."""
    forged = {"event": "paid", "headers": {"X-Signature": "forged"}, "raw_body": "x"}
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        json=forged,
        headers={**client.auth, "X-Signature": "real"},
    )
    assert r.status_code == 200, client.text(r)
    _name, data = SEEN[-1]
    assert data["anonymous"] is False
    assert json.loads(data["raw_body"]) == forged  # the bytes that arrived
    seen = {k.lower(): v for k, v in data["headers"].items()}
    assert seen["x-signature"] == "real"
    # Credentials are not handed to the hook, on either path.
    assert "authorization" not in seen and "cookie" not in seen


def test_an_anonymous_hook_is_not_given_cookies(client: _Client) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        json={"event": "x"},
        headers={"Cookie": "session=secret"},
    )
    assert r.status_code == 200, client.text(r)
    _name, data = SEEN[-1]
    assert "cookie" not in {k.lower() for k in data["headers"]}


def test_the_wildcard_hook_does_not_run_anonymously(wild: _Client) -> None:
    r = wild.request("POST", _cb(wild, "incoming"), json={"event": "x"})
    assert r.status_code == 200
    assert [n for n, _ in SEEN] == ["incoming"]


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_an_anonymous_request_other_than_post_is_401(
    client: _Client, method: str
) -> None:
    r = client.request(method, _cb(client, "incoming"))
    assert r.status_code == 401
    assert SEEN == []


def test_a_method_override_never_admits_anonymously(client: _Client) -> None:
    r = client.request(
        "GET",
        _cb(client, "incoming") + "?_method=POST",
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code in (401, 403)
    r = client.request("POST", _cb(client, "incoming") + "?_method=PUT", json={})
    assert r.status_code == 401
    assert SEEN == []


def test_an_anonymous_hook_that_refuses_answers_403(client: _Client) -> None:
    r = client.request("POST", _cb(client, "refusing"), json={})
    assert r.status_code == 403
    assert [n for n, _ in SEEN] == ["refusing"]


def test_a_method_override_in_a_form_body_never_admits_anonymously(
    client: _Client,
) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        data="_method=PUT&a=1",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401
    assert SEEN == []


def test_a_signed_form_body_reaches_the_hook_byte_for_byte(client: _Client) -> None:
    body = "b=2&a=1&a=3&text=caf%C3%A9+%26+more"
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    raw = SEEN[-1][1]["raw_body"]
    assert (raw.decode() if isinstance(raw, bytes) else raw) == body


@pytest.mark.parametrize(
    "name", ["handled", "subscriptions/peer/sub", "permissions/peer", "nothing_here"]
)
def test_an_anonymous_post_to_an_unflagged_path_is_401(
    client: _Client, name: str
) -> None:
    r = client.request("POST", _cb(client, name), json={})
    assert r.status_code == 401
    assert SEEN == []


def test_a_bearer_that_matches_nobody_is_still_403(client: _Client) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        json={},
        headers={"Authorization": "Bearer nobody"},
    )
    assert r.status_code == 403
    assert SEEN == []


def test_a_form_body_and_a_json_array_reach_the_hook_raw(client: _Client) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        data="a=1&b=2",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    data = SEEN[-1][1]
    raw = data["raw_body"]
    assert (raw.decode() if isinstance(raw, bytes) else raw) == "a=1&b=2"
    r = client.request("POST", _cb(client, "incoming"), json=[1, 2])
    assert r.status_code == 200
    raw = SEEN[-1][1]["raw_body"]
    assert json.loads(raw) == [1, 2]


def test_a_body_over_the_cap_is_413(client: _Client) -> None:
    r = client.request(
        "POST",
        _cb(client, "incoming"),
        data="x" * (1024 * 1024 + 1),
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 413
    assert SEEN == []


def test_an_unknown_actor_answers_as_today(client: _Client) -> None:
    r = client.request("POST", "/no-such-actor/callbacks/incoming", json={})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["*", "subscriptions", "permissions", "www", "subscription", "resource_x"]
)
def test_the_flag_is_refused_for_the_wildcard_and_reserved_names(name: str) -> None:
    from actingweb.interface.hooks import HookRegistry

    app = ActingWebApp(aw_type="urn:actingweb:test:flag", fqdn="x.example.com")
    with pytest.raises(ValueError):
        app.callback_hook(name, allow_anonymous=True)(lambda a, n, d: True)
    with pytest.raises(ValueError):
        HookRegistry().register_callback_hook(
            name, lambda a, n, d: True, allow_anonymous=True
        )
