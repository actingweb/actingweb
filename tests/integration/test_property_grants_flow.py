"""A peer's grant holds at every level of a property (3.16).

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 1, over
HTTP on the test app (both backends by the suite's parametrisation): reads
lose excluded parts at any depth, a write or delete that would touch one is
403, a path under a list is decided by the list's grant, and a bulk POST is
validated and authorised whole before anything is applied.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

pytestmark = pytest.mark.xdist_group(name="property_grants_flow")

SETTINGS = {"theme": "x", "private": "s", "deep": {"private": "d", "ok": 1}}
F_GRANT = {
    "patterns": ["*"],
    "operations": ["read", "write", "delete"],
    "excluded_patterns": ["settings/private", "memory_personal", "*/deep/private"],
}


class World:
    def __init__(self, actor_factory, trust_helper):
        self.a = actor_factory.create("grants-owner@example.com")
        self.f = actor_factory.create("grants-friend@example.com")
        self.d = actor_factory.create("grants-admin@example.com")
        self.f_secret = trust_helper.establish(self.f, self.a, "friend")["secret"]
        self.d_secret = trust_helper.establish(self.d, self.a, "admin")["secret"]
        r = requests.put(
            f"{self.a['url']}/trust/friend/{self.f['id']}/permissions",
            json={"properties": F_GRANT},
            auth=self.owner,
        )
        assert r.status_code in (200, 201, 204), r.text
        self.put_owner("settings", SETTINGS)
        self.put_owner("color", "blue")
        self.put_owner("obj", {"0": "zero", "1": "one"})
        r = requests.post(
            f"{self.a['url']}/properties",
            json={"memory_personal": {"_type": "list"}, "notes": {"_type": "list"}},
            auth=self.owner,
        )
        assert r.status_code == 201, r.text
        for name in ("memory_personal", "notes"):
            r = requests.post(
                f"{self.a['url']}/properties/{name}/items",
                json={"action": "add", "item_value": {"text": f"{name}-1"}},
                auth=self.owner,
            )
            assert r.status_code in (200, 201), r.text

    @property
    def owner(self) -> tuple[str, str]:
        return (self.a["creator"], self.a["passphrase"])

    def put_owner(self, name: str, value: Any) -> None:
        r = requests.put(
            f"{self.a['url']}/properties/{name}", json=value, auth=self.owner
        )
        assert r.status_code in (200, 201, 204), r.text

    def as_f(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return requests.request(
            method,
            f"{self.a['url']}/properties{path}",
            headers={"Authorization": f"Bearer {self.f_secret}"},
            **kwargs,
        )

    def as_d(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return requests.request(
            method,
            f"{self.a['url']}/properties{path}",
            headers={"Authorization": f"Bearer {self.d_secret}"},
            **kwargs,
        )

    def stored(self, name: str) -> Any:
        return requests.get(
            f"{self.a['url']}/properties/{name}", auth=self.owner
        ).json()


@pytest.fixture
def world(actor_factory, trust_helper) -> World:
    return World(actor_factory, trust_helper)


def test_a_parent_read_drops_excluded_parts_at_every_depth(world: World) -> None:
    r = world.as_f("GET", "/settings")
    assert r.status_code == 200
    assert r.json() == {"theme": "x", "deep": {"ok": 1}}
    assert world.as_f("GET", "/settings/deep").json() == {"ok": 1}
    assert world.as_f("GET", "/settings/private").status_code == 403
    assert world.as_f("GET", "/settings/deep/private").status_code == 403
    listing = world.as_f("GET", "").json()
    assert listing["settings"] == {"theme": "x", "deep": {"ok": 1}}
    assert "memory_personal" not in listing
    metadata = world.as_f("GET", "", params={"metadata": "true"}).json()
    assert set(metadata["simple"]["properties"]) == {"color", "obj", "settings"}
    assert set(metadata["lists"]) == {"notes"}


def test_a_refusal_says_little(world: World) -> None:
    r = world.as_f("GET", "/settings/private")
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden"}


def test_writes_and_deletes_that_touch_an_excluded_part(world: World) -> None:
    assert world.as_f("PUT", "/settings", json={"theme": "y"}).status_code == 403
    assert world.as_f("DELETE", "/settings").status_code == 403
    assert world.as_f("PUT", "/settings/deep", json={"ok": 2}).status_code == 403
    assert world.stored("settings") == SETTINGS
    # The admin peer manages the actor (spec: admin).
    assert world.as_d("PUT", "/settings", json={"theme": "y"}).status_code == 204
    assert world.stored("settings") == {"theme": "y"}
    # Nothing excluded inside: allowed.
    assert world.as_f("PUT", "/color", json="red").status_code == 204
    assert world.as_f("DELETE", "/color").status_code == 204


def test_root_delete_by_a_peer_needs_every_name(world: World) -> None:
    assert world.as_f("DELETE", "").status_code == 403
    assert world.stored("settings") == SETTINGS


def test_a_path_under_a_list_is_the_lists(world: World) -> None:
    assert world.as_f("GET", "/memory_personal").status_code == 403
    assert world.as_f("GET", "/memory_personal/x").status_code == 403
    r = world.as_f("PUT", "/memory_personal/x", params={"index": "0"}, json={"t": 1})
    assert r.status_code == 403
    assert world.stored("memory_personal") == [{"text": "memory_personal-1"}]
    # A name that is not a list keeps its sub-paths.
    assert world.as_f("GET", "/obj/0").json() == "zero"
    assert world.as_f("GET", "/notes").status_code == 200


@pytest.mark.parametrize("shape", ["json", "form"])
def test_a_mixed_bulk_post_changes_nothing(world: World, shape: str) -> None:
    body = {"mood": "ok", "settings": "flat"}
    r = (
        world.as_f("POST", "", json=body)
        if shape == "json"
        else world.as_f("POST", "", data=body)
    )
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden", "refused": ["settings"]}
    assert world.as_f("GET", "/mood").status_code == 404
    assert world.stored("settings") == SETTINGS


def test_the_form_with_property_is_decided_too(world: World) -> None:
    r = world.as_f(
        "POST", "", data={"property": "memory_personal", "property_type": "list"}
    )
    assert r.status_code == 403
    assert r.json()["refused"] == ["memory_personal"]


def test_a_bulk_post_that_refuses_list_items_applies_none(world: World) -> None:
    r = world.as_f(
        "POST",
        "",
        json={"memory_personal": {"items": [{"index": 0, "text": "x"}]}, "mood": "a"},
    )
    assert r.status_code == 403
    assert world.stored("memory_personal") == [{"text": "memory_personal-1"}]
    assert world.as_f("GET", "/mood").status_code == 404


def test_an_allowed_bulk_post_applies(world: World) -> None:
    r = world.as_f("POST", "", json={"mood": "ok", "color": "green"})
    assert r.status_code == 201
    assert world.as_f("GET", "/mood").text == "ok"  # stored as posted, raw


def test_a_400_in_the_last_key_leaves_the_first_unapplied(world: World) -> None:
    r = requests.post(
        f"{world.a['url']}/properties",
        json={"mood": "first", "notes": {"items": "not a list"}},
        auth=world.owner,
    )
    assert r.status_code == 400
    assert (
        requests.get(f"{world.a['url']}/properties/mood", auth=world.owner).status_code
        == 404
    )


def test_post_with_a_name_is_400_and_changes_nothing(world: World) -> None:
    r = requests.post(
        f"{world.a['url']}/properties/mood", json={"mood": "x"}, auth=world.owner
    )
    assert r.status_code == 400
    assert (
        requests.get(f"{world.a['url']}/properties/mood", auth=world.owner).status_code
        == 404
    )
