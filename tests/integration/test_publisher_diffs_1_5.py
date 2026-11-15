"""What a subscriber is told (specification 1.5, spec-1-5 Phase 3): one
delete representation at every level, a resource that went with its
parent, a clear as one diff, and the value stored after the hooks.

In process on both integrations against the suite's database. The
subscriptions are made directly on the publisher for a peer it has no
trust with, so the diffs are stored (and numbered) and nothing is sent.
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
from actingweb.subscription import Subscription

DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")
PEER = "f" * 32


def _aw_app() -> ActingWebApp:
    app = (
        ActingWebApp(
            aw_type="urn:actingweb:test:publisher_diffs",
            database=DATABASE_BACKEND,
            fqdn="publisher-diffs.example.com",
            proto="http://",
        )
        .with_unique_creator(False)
        .with_web_ui(enable=False)
    )

    @app.property_hook("shout")
    def shout(actor: Any, operation: str, value: Any, path: list[str]) -> Any:
        if operation != "put":
            return value
        if isinstance(value, str):
            return value.upper()
        if isinstance(value, dict) and isinstance(value.get("k"), dict):
            # A nested write is given the whole merged value.
            return {**value, "k": {**value["k"], "hooked": True}}
        return value

    return app


class _Pub:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.aw = _aw_app()
        if kind == "flask":
            from flask import Flask

            flask_app = Flask(__name__)
            flask_app.config["TESTING"] = True
            self.aw.integrate_flask(flask_app)
            self._c: Any = flask_app.test_client()
        else:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            fastapi_app = FastAPI()
            self.aw.integrate_fastapi(fastapi_app)
            self._c = TestClient(fastapi_app, raise_server_exceptions=False)
        self.auth: dict[str, str] = {}
        self.actor_id = ""
        self.subs: dict[str, str] = {}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self.auth, **kwargs.pop("headers", {})}
        if "json" in kwargs:
            kwargs["data"] = json.dumps(kwargs.pop("json"))
            headers["Content-Type"] = "application/json"
        if self.kind == "flask":
            return self._c.open(path, method=method, headers=headers, **kwargs)
        if "data" in kwargs:
            kwargs["content"] = kwargs.pop("data")
        return self._c.request(method, path, headers=headers, **kwargs)

    def put(self, name: str, value: Any) -> None:
        r = self.request("PUT", f"/{self.actor_id}/properties/{name}", json=value)
        assert r.status_code == 204, r.status_code

    def subscribe(self, key: str, subtarget: str = "", resource: str = "") -> None:
        subid = uuid.uuid4().hex
        assert Subscription(
            actor_id=self.actor_id,
            peerid=PEER,
            subid=subid,
            callback=False,
            config=self.aw.get_config(),
        ).create(
            target="properties",
            subtarget=subtarget,
            resource=resource,
            granularity="high",
        )
        self.subs[key] = subid

    def diffs(self, key: str) -> list[Any]:
        """The data of each diff stored for one subscription, in order."""
        rows = Subscription(
            actor_id=self.actor_id,
            peerid=PEER,
            subid=self.subs[key],
            callback=False,
            config=self.aw.get_config(),
        ).get_diffs()
        rows = sorted(rows or [], key=lambda d: d["sequence"])
        return [json.loads(d["diff"]) for d in rows]


@pytest.fixture(params=["flask", "fastapi"])
def pub(request: pytest.FixtureRequest, worker_info: dict) -> Iterator[_Pub]:
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
    p = _Pub(request.param)
    r = p.request(
        "POST", "/", json={"creator": f"pd-{uuid.uuid4().hex[:8]}@example.com"}
    )
    assert r.status_code == 201
    data = json.loads(r.get_data(as_text=True) if hasattr(r, "get_data") else r.text)
    p.actor_id = data["id"]
    token = base64.b64encode(f"{data['creator']}:{data['passphrase']}".encode())
    p.auth = {"Authorization": f"Basic {token.decode()}"}
    p.put("x", {"r": 1, "s": 2})
    p.put("y", "plain")
    p.subscribe("target")
    p.subscribe("subtarget", subtarget="x")
    p.subscribe("resource", subtarget="x", resource="r")
    yield p
    p.request("DELETE", f"/{p.actor_id}")


def test_a_rest_delete_reaches_every_level(pub: _Pub) -> None:
    r = pub.request("DELETE", f"/{pub.actor_id}/properties/x")
    assert r.status_code == 204
    assert pub.diffs("target") == [{"x": ""}]
    assert pub.diffs("subtarget") == [""]
    assert pub.diffs("resource") == [""]


def test_a_nested_delete_reaches_the_resource(pub: _Pub) -> None:
    r = pub.request("DELETE", f"/{pub.actor_id}/properties/x/r")
    assert r.status_code == 204
    assert pub.diffs("resource") == [""]
    # Above the resource: the parent's whole stored value (3.16).
    assert pub.diffs("subtarget") == [{"s": 2}]
    assert pub.diffs("target") == [{"x": {"s": 2}}]


def test_an_empty_put_is_a_delete_at_every_level(pub: _Pub) -> None:
    r = pub.request(
        "PUT",
        f"/{pub.actor_id}/properties/x",
        data="",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 204
    assert pub.diffs("subtarget") == [""]
    assert pub.diffs("target") == [{"x": ""}]


def test_an_overwrite_without_the_resource_tells_its_subscriber(pub: _Pub) -> None:
    pub.put("x", {"s": 3})
    assert pub.diffs("resource") == [""]
    assert pub.diffs("subtarget") == [{"s": 3}]


def test_an_overwrite_that_never_had_the_resource_sends_it_nothing(
    pub: _Pub,
) -> None:
    pub.request("DELETE", f"/{pub.actor_id}/properties/x")
    before = len(pub.diffs("resource"))
    pub.put("x", {"s": 3})
    assert len(pub.diffs("resource")) == before


def test_a_write_with_no_resource_subscriber_reads_no_previous_value(
    pub: _Pub,
) -> None:
    from actingweb.actor import Actor

    calls: list[Any] = []
    real = Actor.previous_for_resource_subscribers

    def spy(self: Any, target: str, subtarget: Any, read: Any) -> Any:
        def counted() -> Any:
            calls.append(subtarget)
            return read()

        return real(self, target, subtarget, counted)

    from unittest import mock

    with mock.patch.object(Actor, "previous_for_resource_subscribers", spy):
        pub.put("y", "again")
        assert calls == []
        pub.put("x", {"r": 5})
        assert calls == ["x"]


def test_a_clear_is_one_diff_and_leaves_lists(pub: _Pub) -> None:
    r = pub.request(
        "POST", f"/{pub.actor_id}/properties", json={"notes": {"_type": "list"}}
    )
    assert r.status_code == 201
    r = pub.request(
        "POST",
        f"/{pub.actor_id}/properties/notes/items",
        json={"action": "add", "item_value": "one"},
    )
    assert r.status_code == 201
    before = len(pub.diffs("target"))
    r = pub.request("DELETE", f"/{pub.actor_id}/properties")
    assert r.status_code == 204
    target = pub.diffs("target")[before:]
    assert target == [{"x": "", "y": ""}]
    assert pub.diffs("subtarget")[-1] == ""
    assert pub.diffs("resource")[-1] == ""
    r = pub.request("GET", f"/{pub.actor_id}/properties/notes")
    assert r.status_code == 200


def test_the_interface_layer_sends_the_same_bytes(pub: _Pub) -> None:
    from actingweb.interface.actor_interface import ActorInterface

    actor = ActorInterface.get_by_id(pub.actor_id, pub.aw.get_config())
    assert actor is not None
    del actor.properties["x"]
    assert pub.diffs("target") == [{"x": ""}]
    assert pub.diffs("subtarget") == [""]
    assert pub.diffs("resource") == [""]


def test_the_interface_clear_registers_once(pub: _Pub) -> None:
    from actingweb.interface.actor_interface import ActorInterface

    actor = ActorInterface.get_by_id(pub.actor_id, pub.aw.get_config())
    assert actor is not None
    actor.properties.clear()
    assert pub.diffs("target") == [{"x": "", "y": ""}]


@pytest.mark.parametrize(
    ("path", "body", "level", "expected"),
    [
        ("shout", "quiet", "t", {"shout": "QUIET"}),
        ("shout/k", {"v": 1}, "t", {"shout": {"k": {"v": 1, "hooked": True}}}),
    ],
)
def test_a_transforming_hook_is_what_the_diff_carries(
    pub: _Pub, path: str, body: Any, level: str, expected: Any
) -> None:
    if "/" in path:
        pub.put("shout", {})
        start = len(pub.diffs("target"))
    else:
        start = 0
    pub.put(path, body)
    assert pub.diffs("target")[start:][-1] == expected


@pytest.mark.parametrize(("excluded", "status"), [(["notes"], 204), (["keep"], 403)])
def test_a_peer_clear_needs_delete_rights_on_the_properties_only(
    actor_factory: Any, trust_helper: Any, excluded: list[str], status: int
) -> None:
    import requests

    a = actor_factory.create("clear-owner@example.com")
    f = actor_factory.create("clear-friend@example.com")
    secret = trust_helper.establish(f, a, "friend")["secret"]
    owner = (a["creator"], a["passphrase"])
    r = requests.put(
        f"{a['url']}/trust/friend/{f['id']}/permissions",
        json={
            "properties": {
                "patterns": ["*"],
                "operations": ["read", "write", "delete"],
                "excluded_patterns": excluded,
            }
        },
        auth=owner,
    )
    assert r.status_code in (200, 201, 204), r.text
    requests.put(f"{a['url']}/properties/keep", json="v", auth=owner)
    r = requests.post(
        f"{a['url']}/properties", json={"notes": {"_type": "list"}}, auth=owner
    )
    assert r.status_code == 201
    r = requests.delete(
        f"{a['url']}/properties", headers={"Authorization": f"Bearer {secret}"}
    )
    assert r.status_code == status, r.text
    assert requests.get(f"{a['url']}/properties/notes", auth=owner).status_code == 200


def test_an_sdk_write_of_json_text_holding_the_resource_sends_no_delete(
    pub: _Pub,
) -> None:
    from actingweb.interface.actor_interface import ActorInterface

    actor = ActorInterface.get_by_id(pub.actor_id, pub.aw.get_config())
    assert actor is not None
    actor.properties["x"] = json.dumps({"r": 9, "s": 2})
    assert "" not in pub.diffs("resource")


def test_an_sdk_none_is_a_delete_every_level_receives(pub: _Pub) -> None:
    from actingweb.interface.actor_interface import ActorInterface

    actor = ActorInterface.get_by_id(pub.actor_id, pub.aw.get_config())
    assert actor is not None
    actor.properties["x"] = None
    assert pub.diffs("subtarget") == [""]
    assert pub.diffs("target") == [{"x": ""}]
