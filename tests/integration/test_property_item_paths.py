"""List items addressed by path, the append, collisions and content types
(specification 1.5, ``thoughts/plans/2026-11-06-spec-1-5.md`` Phase 1).

Each case runs in process on both integrations (Flask's test client and
FastAPI's ``TestClient``) against the suite's database, with property hooks
that record what they are given and refuse on demand. The peer cases (a
grant that excludes the list, a read-only grant) run over HTTP on the
shared test app.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest
import requests

from actingweb.interface import ActingWebApp

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

# What the hooks saw: (property, operation, path). A name in REFUSE makes
# the hook for that operation return None.
EVENTS: list[tuple[str, str, list[str]]] = []
REFUSE: set[str] = set()


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _aw_app(kind: str) -> ActingWebApp:
    app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:item_paths",
            database=DATABASE_BACKEND,
            fqdn="item-paths.example.com",
            proto="http://",
        )
        .with_unique_creator(False)
        .with_web_ui(enable=False)
    )

    @app.property_hook("notes")
    def notes_hook(actor: Any, operation: str, value: Any, path: list[str]) -> Any:
        EVENTS.append(("notes", operation, list(path)))
        if operation in REFUSE:
            return None
        return value

    return app


class _Client:
    """One interface over Flask's and FastAPI's in-process clients."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        aw = _aw_app(kind)
        self.aw = aw
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
        self.headers: dict[str, str] = {}
        self.actor_id = ""

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        if "json" in kwargs:
            kwargs["data"] = json.dumps(kwargs.pop("json"))
            headers["Content-Type"] = "application/json"
        if self.kind == "flask":
            return self._c.open(path, method=method, headers=headers, **kwargs)
        if "data" in kwargs:
            kwargs["content"] = kwargs.pop("data")
        return self._c.request(method, path, headers=headers, **kwargs)

    @staticmethod
    def status(r: Any) -> int:
        return int(r.status_code)

    @staticmethod
    def text(r: Any) -> str:
        return r.get_data(as_text=True) if hasattr(r, "get_data") else r.text

    def body(self, r: Any) -> Any:
        return json.loads(self.text(r))


@pytest.fixture(params=["flask", "fastapi"])
def client(request: pytest.FixtureRequest, worker_info: dict) -> Iterator[_Client]:
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
    EVENTS.clear()
    REFUSE.clear()
    c = _Client(request.param)
    r = c.request(
        "POST", "/", json={"creator": f"items-{uuid.uuid4().hex[:8]}@example.com"}
    )
    assert c.status(r) == 201, c.text(r)
    data = c.body(r)
    c.actor_id = data["id"]
    c.headers = _basic(data["creator"], data["passphrase"])
    r = c.request(
        "POST", f"/{c.actor_id}/properties", json={"notes": {"_type": "list"}}
    )
    assert c.status(r) == 201, c.text(r)
    for text in ("a", "b", "c"):
        r = c.request(
            "POST",
            f"/{c.actor_id}/properties/notes/items",
            json={"action": "add", "item_value": {"t": text}},
        )
        assert c.status(r) == 201, c.text(r)
    EVENTS.clear()
    yield c
    c.request("DELETE", f"/{c.actor_id}")


def _p(c: _Client, tail: str = "") -> str:
    return f"/{c.actor_id}/properties{tail}"


def _items(c: _Client) -> list[Any]:
    r = c.request("GET", _p(c, "/notes"))
    assert c.status(r) == 200, c.text(r)
    return c.body(r)


@pytest.fixture
def all_diffs() -> Iterator[list[dict[str, Any]]]:
    """Every ``register_diffs`` call while the test runs (its keywords)."""
    from actingweb.actor import Actor

    seen: list[dict[str, Any]] = []
    real = Actor.register_diffs

    def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(dict(kwargs))
        return real(self, *args, **kwargs)

    with mock.patch.object(Actor, "register_diffs", spy):
        yield seen


@pytest.fixture
def diffs() -> Iterator[list[tuple[str, str, dict[str, Any]]]]:
    """The list diffs registered while the test runs: (name, operation, fields)."""
    from actingweb.handlers import properties as handler_module

    seen: list[tuple[str, str, dict[str, Any]]] = []
    real = handler_module.register_list_diff

    def spy(myself: Any, config: Any, name: str, operation: str, **fields: Any) -> None:
        seen.append((name, operation, fields))
        real(myself, config, name, operation, **fields)

    with mock.patch.object(handler_module, "register_list_diff", spy):
        yield seen


# ---------------------------------------------------------------------------
# The path forms
# ---------------------------------------------------------------------------


def test_get_an_item_by_path(client: _Client) -> None:
    r = client.request("GET", _p(client, "/notes/1"))
    assert client.status(r) == 200
    assert client.body(r) == {"t": "b"}
    assert ("notes", "get", ["1"]) in EVENTS


def test_get_an_item_out_of_range_is_404(client: _Client) -> None:
    assert client.status(client.request("GET", _p(client, "/notes/3"))) == 404


def test_put_an_item_by_path_replaces_it(client: _Client, diffs: list) -> None:
    r = client.request("PUT", _p(client, "/notes/0"), json={"t": "A"})
    assert client.status(r) == 204, client.text(r)
    assert _items(client) == [{"t": "A"}, {"t": "b"}, {"t": "c"}]
    assert ("notes", "put", ["notes", "0"]) in EVENTS
    assert [(n, op) for n, op, _ in diffs] == [("notes", "update")]
    assert diffs[0][2]["index"] == 0


def test_put_at_the_length_appends(client: _Client, diffs: list) -> None:
    r = client.request("PUT", _p(client, "/notes/3"), json={"t": "d"})
    assert client.status(r) == 204, client.text(r)
    assert _items(client)[-1] == {"t": "d"}
    assert [(n, op) for n, op, _ in diffs] == [("notes", "append")]


def test_put_beyond_the_length_is_404(client: _Client, diffs: list) -> None:
    r = client.request("PUT", _p(client, "/notes/4"), json={"t": "x"})
    assert client.status(r) == 404
    assert len(_items(client)) == 3
    assert diffs == []


def test_delete_an_item_by_path_closes_up(client: _Client, diffs: list) -> None:
    r = client.request("DELETE", _p(client, "/notes/1"))
    assert client.status(r) == 204, client.text(r)
    assert _items(client) == [{"t": "a"}, {"t": "c"}]
    assert ("notes", "delete", ["notes", "1"]) in EVENTS
    assert [(n, op) for n, op, _ in diffs] == [("notes", "delete")]
    assert diffs[0][2]["index"] == 1


def test_delete_out_of_range_is_404(client: _Client, diffs: list) -> None:
    assert client.status(client.request("DELETE", _p(client, "/notes/3"))) == 404
    assert len(_items(client)) == 3
    assert diffs == []


def test_post_appends_with_location(client: _Client, diffs: list) -> None:
    r = client.request("POST", _p(client, "/notes"), json={"t": "d"})
    assert client.status(r) == 201, client.text(r)
    assert r.headers["Location"].endswith(f"/{client.actor_id}/properties/notes/3")
    assert _items(client)[-1] == {"t": "d"}
    assert ("notes", "put", ["notes", "3"]) in EVENTS
    assert [(n, op) for n, op, _ in diffs] == [("notes", "append")]
    assert diffs[0][2]["index"] == 3


def test_post_to_a_name_that_is_not_a_list_is_still_400(client: _Client) -> None:
    client.request("PUT", _p(client, "/plain"), json={"k": 1})
    assert (
        client.status(client.request("POST", _p(client, "/plain"), json={"x": 1}))
        == 400
    )
    assert (
        client.status(client.request("POST", _p(client, "/nothing"), json={"x": 1}))
        == 400
    )


@pytest.mark.parametrize("operation", ["get", "put", "delete"])
def test_a_refusing_hook_stops_each_form(
    client: _Client, diffs: list, operation: str
) -> None:
    REFUSE.add(operation)
    if operation == "get":
        assert client.status(client.request("GET", _p(client, "/notes/0"))) == 404
    elif operation == "put":
        r = client.request("PUT", _p(client, "/notes/0"), json={"t": "X"})
        assert client.status(r) == 400
        r = client.request("POST", _p(client, "/notes"), json={"t": "X"})
        assert client.status(r) == 400
    else:
        assert client.status(client.request("DELETE", _p(client, "/notes/0"))) == 403
    REFUSE.clear()
    assert _items(client) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]
    assert diffs == []


@pytest.mark.parametrize("segment", ["-1", "01", "word"])
def test_a_segment_that_is_not_a_canonical_index_is_not_an_item(
    client: _Client, segment: str
) -> None:
    """Characterisation, unchanged: not an item path, so a read answers
    the list as it does today."""
    r = client.request("GET", _p(client, f"/notes/{segment}"))
    assert client.status(r) == 200
    assert client.body(r) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]


def test_an_empty_list_has_no_item_zero(client: _Client) -> None:
    client.request("POST", _p(client), json={"empty": {"_type": "list"}})
    assert client.status(client.request("GET", _p(client, "/empty/0"))) == 404
    assert client.status(client.request("DELETE", _p(client, "/empty/0"))) == 404


def test_a_numeric_key_under_a_name_that_is_not_a_list_is_nested(
    client: _Client,
) -> None:
    """Characterisation: unchanged."""
    client.request("PUT", _p(client, "/obj"), json={"0": "zero", "1": "one"})
    r = client.request("GET", _p(client, "/obj/1"))
    assert client.status(r) == 200
    assert client.body(r) == "one"
    assert (
        client.status(client.request("PUT", _p(client, "/obj/0"), json="ZERO")) == 204
    )
    r = client.request("GET", _p(client, "/obj"))
    assert client.body(r) == {"0": "ZERO", "1": "one"}


def test_items_and_metadata_segments_are_unchanged(client: _Client) -> None:
    r = client.request("GET", _p(client, "/notes/items"))
    assert client.status(r) == 200
    assert client.body(r)["count"] == 3
    r = client.request("GET", _p(client, "/notes/metadata"))
    assert client.status(r) == 200


def test_two_concurrent_appends_get_two_locations(client: _Client) -> None:
    if client.kind == "flask":
        pytest.skip("Flask's test client is not thread safe; FastAPI covers it")
    locations: list[str] = []
    errors: list[str] = []

    def append(text: str) -> None:
        r = client.request("POST", _p(client, "/notes"), json={"t": text})
        if client.status(r) != 201:
            errors.append(client.text(r))
            return
        locations.append(r.headers["Location"])

    threads = [threading.Thread(target=append, args=(t,)) for t in ("x", "y")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(set(locations)) == 2
    assert len(_items(client)) == 5


# ---------------------------------------------------------------------------
# Collisions, text values, a nameless PUT, /meta
# ---------------------------------------------------------------------------


def test_every_collision_route_answers_409(client: _Client) -> None:
    client.request("PUT", _p(client, "/scalar"), json={"k": 1})
    cases = [
        ("PUT", "/notes", {"json": {"k": 2}}),
        ("PUT", "/notes/sub", {"json": {"k": 2}}),
        ("POST", "", {"json": {"notes": "x"}}),
        (
            "POST",
            "",
            {
                "data": "notes=x",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            },
        ),
        (
            "POST",
            "",
            {
                "data": "property=notes&value=x",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            },
        ),
        ("POST", "", {"json": {"scalar": {"_type": "list"}}}),
        (
            "POST",
            "",
            {
                "data": "property=scalar&property_type=list",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            },
        ),
    ]
    for method, tail, kwargs in cases:
        r = client.request(method, _p(client, tail), **kwargs)
        assert client.status(r) == 409, (
            method,
            tail,
            kwargs,
            client.status(r),
            client.text(r),
        )
    assert len(_items(client)) == 3
    r = client.request("GET", _p(client, "/scalar"))
    assert client.body(r) == {"k": 1}


def test_a_text_value_is_text_plain(client: _Client) -> None:
    client.request(
        "PUT",
        _p(client, "/greeting"),
        data="hello there",
        headers={"Content-Type": "text/plain"},
    )
    r = client.request("GET", _p(client, "/greeting"))
    assert client.status(r) == 200
    assert client.text(r) == "hello there"
    assert r.headers["Content-Type"].startswith("text/plain")
    client.request("PUT", _p(client, "/obj"), json={"k": 1})
    r = client.request("GET", _p(client, "/obj"))
    assert r.headers["Content-Type"].startswith("application/json")


def test_a_nameless_put_is_405(client: _Client) -> None:
    r = client.request("PUT", _p(client), json={"k": 1})
    assert client.status(r) == 405


@pytest.mark.parametrize(
    "path",
    [
        "id",
        "type",
        "version",
        "desc",
        "info",
        "trustee_root",
        "specification",
        "actingweb/version",
        "actingweb/supported",
        "actingweb/formats",
    ],
)
def test_scalar_meta_paths_are_text_plain(client: _Client, path: str) -> None:
    r = client.request("GET", f"/{client.actor_id}/meta/{path}")
    assert client.status(r) == 200
    assert r.headers.get("Content-Type", "").startswith("text/plain"), (
        client.kind,
        r.headers.get("Content-Type"),
    )


def test_the_meta_object_is_json(client: _Client) -> None:
    r = client.request("GET", f"/{client.actor_id}/meta")
    assert r.headers["Content-Type"].startswith("application/json")


# ---------------------------------------------------------------------------
# A peer: access is on the list name
# ---------------------------------------------------------------------------


class _Peer:
    def __init__(self, actor_factory: Any, trust_helper: Any, grant: dict[str, Any]):
        self.a = actor_factory.create(f"items-owner-{uuid.uuid4().hex[:6]}@example.com")
        self.f = actor_factory.create(
            f"items-friend-{uuid.uuid4().hex[:6]}@example.com"
        )
        self.secret = trust_helper.establish(self.f, self.a, "friend")["secret"]
        owner = (self.a["creator"], self.a["passphrase"])
        r = requests.put(
            f"{self.a['url']}/trust/friend/{self.f['id']}/permissions",
            json={"properties": grant},
            auth=owner,
        )
        assert r.status_code in (200, 201, 204), r.text
        for name in ("shared", "secret"):
            r = requests.post(
                f"{self.a['url']}/properties",
                json={name: {"_type": "list"}},
                auth=owner,
            )
            assert r.status_code == 201, r.text
            r = requests.post(
                f"{self.a['url']}/properties/{name}/items",
                json={"action": "add", "item_value": "one"},
                auth=owner,
            )
            assert r.status_code == 201, r.text
        r = requests.put(f"{self.a['url']}/properties/plain", json="v", auth=owner)
        assert r.status_code == 204, r.text

    def __call__(self, method: str, tail: str, **kwargs: Any) -> requests.Response:
        return requests.request(
            method,
            f"{self.a['url']}/properties{tail}",
            headers={"Authorization": f"Bearer {self.secret}"},
            **kwargs,
        )


def test_a_grant_that_excludes_the_list_refuses_every_form(
    actor_factory: Any, trust_helper: Any
) -> None:
    peer = _Peer(
        actor_factory,
        trust_helper,
        {"excluded_patterns": ["secret"], "operations": ["read", "write", "delete"]},
    )
    assert peer("GET", "/shared/0").status_code == 200
    for method, tail, body in [
        ("GET", "/secret/0", None),
        ("PUT", "/secret/0", "x"),
        ("DELETE", "/secret/0", None),
        ("POST", "/secret", "x"),
    ]:
        r = peer(method, tail, json=body) if body is not None else peer(method, tail)
        assert r.status_code == 403, (method, tail, r.status_code, r.text)


def test_a_read_only_grant_refuses_writes_by_path(
    actor_factory: Any, trust_helper: Any
) -> None:
    peer = _Peer(
        actor_factory,
        trust_helper,
        {"patterns": ["*"], "operations": ["read"]},
    )
    assert peer("GET", "/shared/0").status_code == 200
    assert peer("PUT", "/shared/0", json="x").status_code == 403
    assert peer("DELETE", "/shared/0").status_code == 403
    # The same 403 for a list and for a name that is not one.
    r_list = peer("POST", "/shared", json="x")
    r_plain = peer("POST", "/plain", json="x")
    r_none = peer("POST", "/nothing", json="x")
    assert (r_list.status_code, r_plain.status_code, r_none.status_code) == (
        403,
        403,
        403,
    )
    assert r_list.text == r_plain.text == r_none.text


# ---------------------------------------------------------------------------
# After the review of Phase 1
# ---------------------------------------------------------------------------


def test_a_form_post_over_a_list_announces_nothing(
    client: _Client, all_diffs: list
) -> None:
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    for data in ("property=notes&value=x", "notes=x"):
        r = client.request("POST", _p(client), data=data, headers=form)
        assert client.status(r) == 409
    assert all_diffs == []


def test_the_path_names_the_item_on_put_as_on_get(client: _Client) -> None:
    r = client.request("PUT", _p(client, "/notes/0?index=2"), json={"t": "A"})
    assert client.status(r) == 204
    assert _items(client) == [{"t": "A"}, {"t": "b"}, {"t": "c"}]


def test_the_location_of_a_name_outside_ascii_is_encoded(client: _Client) -> None:
    client.request("POST", _p(client), json={"dagbok 日記": {"_type": "list"}})
    r = client.request("POST", _p(client, "/dagbok%20%E6%97%A5%E8%A8%98"), json="x")
    assert client.status(r) == 201, client.text(r)
    assert r.headers["Location"].endswith("/properties/dagbok%20%E6%97%A5%E8%A8%98/0")


def test_an_append_whose_index_cannot_be_read_is_201_without_location(
    client: _Client, diffs: list
) -> None:
    from actingweb.actor import Actor
    from actingweb.property_list import ListProperty

    real = ListProperty.append_indexed

    def unlocated(self: Any, item: Any, **kwargs: Any) -> None:
        real(self, item, **kwargs)
        return None

    with (
        mock.patch.object(ListProperty, "append_indexed", unlocated),
        mock.patch.object(Actor, "request_resync") as resync,
    ):
        r = client.request("POST", _p(client, "/notes"), json={"t": "d"})
    assert client.status(r) == 201
    assert "Location" not in r.headers
    assert diffs == []
    resync.assert_called_once_with("properties", "notes")
    assert _items(client)[-1] == {"t": "d"}


def test_an_attribute_list_reports_where_an_append_landed(client: _Client) -> None:
    from actingweb.interface.actor_interface import ActorInterface

    actor = ActorInterface.get_by_id(client.actor_id, client.aw.get_config())
    assert actor is not None
    lst = actor.attribute_lists("app_state").get("queue")
    assert lst.append_indexed("a") == 0
    assert lst.append_indexed("b") == 1
    assert lst.to_list() == ["a", "b"]
