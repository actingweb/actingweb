"""A peer's grant holds at every level of a property (3.16).

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 1, over
HTTP on the test app (both backends by the suite's parametrisation): reads
lose excluded parts at any depth, a write or delete that would touch one is
403, a path under a list is decided by the list's grant, and a bulk POST is
validated and authorised whole before anything is applied.
"""

from __future__ import annotations

import json
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


def test_a_peer_cannot_probe_for_a_list_it_may_not_write(world: World) -> None:
    """Verification 2026-11-10: ``PUT ?index=`` answered 404 for a missing
    list before the permission check, and the bulk pre-pass 400 "not a list
    property": a peer told a list it may not write from one that is not
    there. Both are 403 now, whether the list exists or not."""
    grant = {**F_GRANT, "excluded_patterns": [*F_GRANT["excluded_patterns"], "ghost"]}
    r = requests.put(
        f"{world.a['url']}/trust/friend/{world.f['id']}/permissions",
        json={"properties": grant},
        auth=world.owner,
    )
    assert r.status_code in (200, 201, 204), r.text
    for name in ("ghost", "memory_personal"):  # missing, existing
        r = world.as_f("PUT", f"/{name}/x", params={"index": "0"}, json={"t": 1})
        assert r.status_code == 403, name
        r = world.as_f("POST", "", json={name: {"items": [{"index": 0, "text": "x"}]}})
        assert r.status_code == 403, name
    # The owner still learns that a list does not exist.
    r = requests.put(
        f"{world.a['url']}/properties/ghost/x",
        params={"index": "0"},
        json={"t": 1},
        auth=world.owner,
    )
    assert r.status_code == 404


@pytest.mark.parametrize("body", [[1, 2], "text", 3, None])
def test_a_json_body_that_is_not_an_object_is_400(world: World, body: Any) -> None:
    """Verification 2026-11-10: it was a 500 (the apply pass indexed it)."""
    r = requests.post(
        f"{world.a['url']}/properties",
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
        auth=world.owner,
    )
    assert r.status_code == 400


def test_an_admin_peer_deletes_a_parent_holding_an_excluded_part(world: World) -> None:
    """Verification 2026-11-10 (Phase 1's list): the admin exemption on
    DELETE, beside the PUT one."""
    assert world.as_d("DELETE", "/settings").status_code in (200, 204)
    assert (
        requests.get(
            f"{world.a['url']}/properties/settings", auth=world.owner
        ).status_code
        == 404
    )


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {"leaf": 1}
    for _ in range(depth):
        value = {"a": value}
    return value


def test_a_value_too_deep_to_filter_is_withheld_not_null(world: World) -> None:
    """Re-run 2 of the grant-enforcement verification (Issue 2): a value
    nested beyond the filter's depth was answered ``null`` (a read) and
    listed as ``null``. A peer whose grant excludes something gets 403 for
    it and does not see it listed; a peer whose grant excludes nothing (the
    admin) and the owner read it whole; a peer's write of one is 403."""
    deep = _nested(150)
    world.put_owner("deep", deep)
    assert world.as_f("GET", "/deep").status_code == 403
    listing = world.as_f("GET", "").json()
    assert "deep" not in listing and listing["color"] == "blue"
    assert world.as_d("GET", "/deep").json() == deep
    assert world.stored("deep") == deep
    assert world.as_f("PUT", "/color", json=deep).status_code == 403


def test_text_beyond_the_parser_never_reaches_a_peer(world: World) -> None:
    """Re-run 3 of the grant-enforcement verification (Issues 1, 3): text
    nested beyond the JSON parser (stored by the application as text; no
    REST write can store it) skipped the sub-path walk and the read hooks
    and was sent whole to a peer whose grant excluded nothing. It never
    reaches a peer, on any path; the owner reads it as stored, as plain text
    is read; a peer may replace it when its grant excludes nothing."""
    from actingweb.actor import Actor

    from .conftest import TEST_APP_CONFIG

    deep = "[" * 200_000 + "]" * 200_000
    core = Actor(world.a["id"], config=TEST_APP_CONFIG["config"])
    assert core.property is not None
    core.property["deep"] = deep
    for who in (world.as_f, world.as_d):  # excludes something / nothing
        assert who("GET", "/deep").status_code == 403
        assert who("GET", "/deep/x").status_code == 403
        assert "deep" not in who("GET", "").json()
    owner = requests.get(f"{world.a['url']}/properties/deep", auth=world.owner)
    assert owner.status_code == 200 and owner.text == deep
    # The friend's grant excludes parts: it may not replace the value.
    assert world.as_f("PUT", "/deep", json={"x": 1}).status_code == 403


def test_writes_over_text_beyond_the_parser(world: World) -> None:
    """Re-run 4 (Issues 1, 4): a sub-path PUT into such a value merged
    nothing and wrote the part over the whole property (204, data lost); a
    body nested beyond the parser answered 500. Every built-in type excludes
    something, so a peer is refused before either (the unit test
    ``test_touches_excluded_beyond_the_parser`` holds a grant with no
    exclusion); the owner reaches both."""
    from actingweb.actor import Actor

    from .conftest import TEST_APP_CONFIG

    deep = "[" * 200_000 + "]" * 200_000
    core = Actor(world.a["id"], config=TEST_APP_CONFIG["config"])
    assert core.property is not None
    core.property["deep"] = deep

    def owner_put(path: str, **kw: Any) -> requests.Response:
        return requests.put(
            f"{world.a['url']}/properties{path}", auth=world.owner, **kw
        )

    assert owner_put("/deep/x", json=1).status_code == 409
    owner = requests.get(f"{world.a['url']}/properties/deep", auth=world.owner)
    assert owner.text == deep  # nothing lost
    assert world.as_f("PUT", "/deep/x", json=1).status_code == 403
    body_put = owner_put(
        "/color", data=deep, headers={"Content-Type": "application/json"}
    )
    assert body_put.status_code == 400
    assert owner_put("/deep", json={"x": 1}).status_code in (200, 204)
    assert world.stored("deep") == {"x": 1}
    # Re-run 6 (Issue 5): plain text, and a JSON list or scalar, have no
    # parts either: nothing is replaced.
    core.property["text"] = "plain"
    core.property["a_list"] = "[1, 2]"
    assert owner_put("/text/x", json=1).status_code == 409
    assert owner_put("/a_list/x", json=1).status_code == 409
    text = requests.get(f"{world.a['url']}/properties/text", auth=world.owner)
    assert text.text == "plain"
    # Re-run 7 (Issue 4): a sub-path DELETE on a list or scalar was a 500.
    core.property["n"] = "5"
    for name in ("n", "a_list"):
        r = requests.delete(f"{world.a['url']}/properties/{name}/x", auth=world.owner)
        assert r.status_code == 404
