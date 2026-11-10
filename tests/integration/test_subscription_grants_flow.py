"""What a subscriber is pushed and pulls follows its grant at every level.

``thoughts/plans/2026-11-10-grant-enforcement-per-route.md``, Phase 1: a
write three levels down is diffed as its whole resource (it was the bare
value at the second level), and the filter drops the parts the grant
excludes at their true paths; a subscription to an excluded list delivers
nothing, whatever its resource.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

pytestmark = pytest.mark.xdist_group(name="subscription_grants_flow")

F_GRANT = {
    "patterns": ["*"],
    "operations": ["read", "write"],
    "excluded_patterns": ["memory_personal", "*/deep/private"],
}


class World:
    def __init__(self, actor_factory, trust_helper):
        self.a = actor_factory.create("subgrants-owner@example.com")
        self.f = actor_factory.create("subgrants-friend@example.com")
        self.secret = trust_helper.establish(self.f, self.a, "friend")["secret"]
        r = requests.put(
            f"{self.a['url']}/trust/friend/{self.f['id']}/permissions",
            json={"properties": F_GRANT},
            auth=self.owner,
        )
        assert r.status_code in (200, 201, 204), r.text

    @property
    def owner(self) -> tuple[str, str]:
        return (self.a["creator"], self.a["passphrase"])

    def owner_put(self, path: str, value: Any) -> None:
        r = requests.put(
            f"{self.a['url']}/properties/{path}", json=value, auth=self.owner
        )
        assert r.status_code in (200, 201, 204), r.text

    def owner_delete(self, path: str) -> None:
        r = requests.delete(f"{self.a['url']}/properties/{path}", auth=self.owner)
        assert r.status_code == 204, r.text

    def subscribe(self, **body: Any) -> str:
        r = requests.post(
            f"{self.a['url']}/subscriptions/{self.f['id']}",
            json={"target": "properties", "granularity": "low", **body},
            headers={"Authorization": f"Bearer {self.secret}"},
        )
        assert r.status_code == 201, r.text
        return r.json()["subscriptionid"]

    def pull(self, subid: str) -> list[Any]:
        r = requests.get(
            f"{self.a['url']}/subscriptions/{self.f['id']}/{subid}",
            headers={"Authorization": f"Bearer {self.secret}"},
        )
        assert r.status_code == 200, r.text
        return [d["data"] for d in r.json()["data"]]


@pytest.fixture
def world(actor_factory, trust_helper) -> World:
    return World(actor_factory, trust_helper)


def test_a_depth_three_write_is_its_whole_resource_filtered(world: World) -> None:
    world.owner_put("settings", {"theme": "x", "deep": {"ok": 1, "private": "d"}})
    whole = world.subscribe()
    under = world.subscribe(subtarget="settings")
    world.owner_put("settings/deep/private", "d2")
    world.owner_put("settings/deep/ok", 2)
    assert world.pull(whole) == [
        {"settings": {"deep": {"ok": 1}}},
        {"settings": {"deep": {"ok": 2}}},
    ]
    assert world.pull(under) == [{"deep": {"ok": 1}}, {"deep": {"ok": 2}}]


def test_a_depth_three_delete_is_the_remaining_resource(world: World) -> None:
    world.owner_put("settings", {"deep": {"ok": 1, "gone": 2}})
    whole = world.subscribe()
    world.owner_delete("settings/deep/gone")
    assert world.pull(whole) == [{"settings": {"deep": {"ok": 1}}}]


def test_a_two_segment_write_keeps_its_shape(world: World) -> None:
    world.owner_put("settings", {"theme": "x"})
    whole = world.subscribe()
    world.owner_put("settings/theme", "y")
    assert world.pull(whole) == [{"settings": {"theme": "y"}}]


@pytest.mark.parametrize(
    "resource", ["", "item", "items", "value", "old_item", "index", "action"]
)
def test_an_old_subscription_to_a_now_excluded_list_delivers_nothing(
    world: World, resource: str
) -> None:
    """Made while the list was readable, then the list was excluded."""
    readable = {**F_GRANT, "excluded_patterns": ["*/deep/private"]}
    r = requests.put(
        f"{world.a['url']}/trust/friend/{world.f['id']}/permissions",
        json={"properties": readable},
        auth=world.owner,
    )
    assert r.status_code in (200, 201, 204), r.text
    r = requests.post(
        f"{world.a['url']}/properties",
        json={"memory_personal": {"_type": "list"}},
        auth=world.owner,
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = {"subtarget": "memory_personal"}
    if resource:
        body["resource"] = resource
    subid = world.subscribe(**body)
    r = requests.put(
        f"{world.a['url']}/trust/friend/{world.f['id']}/permissions",
        json={"properties": F_GRANT},
        auth=world.owner,
    )
    assert r.status_code in (200, 201, 204), r.text
    r = requests.post(
        f"{world.a['url']}/properties/memory_personal/items",
        json={"action": "add", "item_value": {"text": "secret"}},
        auth=world.owner,
    )
    assert r.status_code in (200, 201), r.text
    assert all(data == {} for data in world.pull(subid))


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"subtarget": "memory_personal"}, 403),
        ({"subtarget": "memory_personal", "resource": "item"}, 403),
        ({"subtarget": "settings", "resource": "deep/private"}, 403),
        ({"subtarget": "settings"}, 201),
        ({}, 201),
    ],
)
def test_creation_needs_read_access(world: World, body: dict[str, Any], status: int):
    """Spec: subscription creation validates read access to the path."""
    r = requests.post(
        f"{world.a['url']}/subscriptions/{world.f['id']}",
        json={"target": "properties", "granularity": "low", **body},
        headers={"Authorization": f"Bearer {world.secret}"},
    )
    assert r.status_code == status, r.text
    if status == 403:
        assert r.json() == {"error": "forbidden"}
