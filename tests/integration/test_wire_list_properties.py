"""Wire rows: list properties, over REST, the web UI and the SDK.

``thoughts/plans/2026-11-06-subscription-wire-baseline.md``, Phase 1 (rows
``WL1`` to ``WL17``; ``WL11.target`` is the security plan's). Each row
records today's behaviour, right or wrong; ``wire/rows.toml`` says what is
known to be wrong and which later plan phase may change the recording.

The REST list routes, one row each: ``WL1`` ``POST …/items`` add, ``WL2``
update, ``WL3`` delete, ``WL4`` ``PUT /properties/<l>?index=N``, ``WL5``
``PUT …/metadata``. Unless a row says otherwise: a ``friend`` pair with a
grant of ``*``, granularity ``high``, both topologies, and a list ``notes``
of two items that B already holds (written through the SDK before the first
step, not recorded). ``.subtarget`` subscribes to the list's name.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import requests

from ._wire import Scenario, WireActor, check
from .test_wire_peer_paths import _put

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]
LEVELS = ["target", "subtarget"]
LIST = "notes"
SEED = [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}]


def _pair(wire_pair, topology: str, level: str, **kwargs: Any) -> Scenario:
    subtarget = LIST if level == "subtarget" else ""
    return wire_pair(topology, grant=["*"], subtarget=subtarget, **kwargs)


def _seed_list(s: Scenario, items: list[Any] = SEED) -> None:
    """``notes`` at A with ``items``, delivered to B before the first step."""
    lst = getattr(s.publisher.interface().property_lists, LIST)
    for item in items:
        lst.append(item)


def _items(a: WireActor, body: dict[str, Any]) -> requests.Response:
    return requests.post(f"{a.url}/properties/{LIST}/items", json=body, auth=a.basic)


def _www(a: WireActor) -> dict[str, str]:
    """What a browser on the actor's own pages sends with a form."""
    return {"Sec-Fetch-Site": "same-origin", "Origin": a.host.url}


def _www_post(a: WireActor, path: str, form: dict[str, Any]) -> requests.Response:
    return requests.post(
        f"{a.url}/www/{path}",
        data=form,
        auth=a.basic,
        headers=_www(a),
        allow_redirects=False,
    )


def _www_delete(a: WireActor, name: str) -> requests.Response:
    return requests.get(
        f"{a.url}/www/properties/{name}",
        params={"_method": "DELETE"},
        auth=a.basic,
        headers=_www(a),
        allow_redirects=False,
    )


def _listing(a: WireActor) -> Any:
    """A's own ``GET /properties?format=full`` (outside the recorder)."""
    return requests.get(
        f"{a.url}/properties", params={"format": "full"}, auth=a.basic
    ).json()


def _lst(a: WireActor) -> Any:
    return getattr(a.interface().property_lists, LIST)


# ---------------------------------------------------------------------------
# The REST list routes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl1(wire_pair, level, topology):
    """WL1: ``POST /properties/notes/items`` with ``action: add``."""
    s = _pair(wire_pair, topology, level)
    _seed_list(s)
    a = s.publisher
    s.step(
        "add",
        lambda: _items(a, {"action": "add", "item_value": {"id": "c", "text": "x"}}),
    )
    check(f"WL1.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl2(wire_pair, level, topology):
    """WL2: ``POST /properties/notes/items`` with ``action: update``."""
    s = _pair(wire_pair, topology, level)
    _seed_list(s)
    a = s.publisher
    s.step(
        "update index 0",
        lambda: _items(
            a,
            {"action": "update", "item_index": 0, "item_value": {"id": "a", "v": 2}},
        ),
    )
    check(f"WL2.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl3(wire_pair, level, topology):
    """WL3: ``POST /properties/notes/items`` with ``action: delete``."""
    s = _pair(wire_pair, topology, level)
    _seed_list(s)
    a = s.publisher
    s.step("delete index 0", lambda: _items(a, {"action": "delete", "item_index": 0}))
    check(f"WL3.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl4(wire_pair, level, topology):
    """WL4: ``PUT /properties/notes?index=0`` (replace), then ``?index=2``
    (the length: an append)."""
    s = _pair(wire_pair, topology, level)
    _seed_list(s)
    a = s.publisher
    for index, value in ((0, {"id": "a", "v": 3}), (2, {"id": "c", "v": 4})):
        s.step(
            f"put index {index}",
            lambda index=index, value=value: requests.put(
                f"{a.url}/properties/{LIST}",
                params={"index": index},
                json=value,
                auth=a.basic,
            ),
        )
    check(f"WL4.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl5(wire_pair, level, topology):
    """WL5: ``PUT /properties/notes/metadata``."""
    s = _pair(wire_pair, topology, level)
    _seed_list(s)
    a = s.publisher
    s.step(
        "put metadata",
        lambda: requests.put(
            f"{a.url}/properties/{LIST}/metadata",
            json={"description": "wire notes", "explanation": "why"},
            auth=a.basic,
        ),
    )
    check(f"WL5.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl6(wire_pair, level, topology):
    """WL6: an SDK ``append`` (B then holds the list), then
    ``DELETE /properties/notes``."""
    s = _pair(wire_pair, topology, level)
    a = s.publisher
    s.step("append (SDK)", lambda: _lst(a).append({"id": "a"}))
    s.step(
        "delete the list",
        lambda: requests.delete(f"{a.url}/properties/{LIST}", auth=a.basic),
    )
    check(f"WL6.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl7_target(wire_pair, topology):
    """WL7.target: ``POST /properties`` with ``items`` changing 2, 25 and 26
    items, and one body that mixes a list and a scalar."""
    s = _pair(wire_pair, topology, "target")
    _seed_list(s)
    a = s.publisher

    def bulk(count: int) -> requests.Response:
        items = [{"index": i, "n": count} for i in range(count)]
        return requests.post(
            f"{a.url}/properties", json={LIST: {"items": items}}, auth=a.basic
        )

    for count in (2, 25, 26):
        s.step(f"{count} item changes", lambda count=count: bulk(count))
    s.step(
        "a list and a scalar",
        lambda: requests.post(
            f"{a.url}/properties",
            json={LIST: {"items": [{"index": 0, "n": "mixed"}]}, "color": "red"},
            auth=a.basic,
        ),
    )
    check("WL7.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_wl8(wire_pair, level, topology):
    """WL8: ``POST /properties {"notes": {"_type": "list"}}`` (an empty list)."""
    s = _pair(wire_pair, topology, level)
    a = s.publisher
    s.step(
        "create an empty list",
        lambda: requests.post(
            f"{a.url}/properties",
            json={LIST: {"_type": "list", "description": "d"}},
            auth=a.basic,
        ),
    )
    check(f"WL8.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl9_target(wire_pair, topology):
    """WL9.target: ``POST /properties/notes`` with an object body."""
    s = _pair(wire_pair, topology, "target")
    _seed_list(s)
    a = s.publisher
    s.extra_snapshot = lambda: {
        "A.stray": a.interface().properties.get("stray"),
        "A.notes": _lst(a).to_list(),
    }
    s.step(
        "post an object to the list's path",
        lambda: requests.post(
            f"{a.url}/properties/{LIST}", json={"stray": 1}, auth=a.basic
        ),
    )
    check("WL9.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl10_target(wire_pair, topology):
    """WL10.target: the web UI's form routes, then its deletes."""
    s = _pair(wire_pair, topology, "target")
    _seed_list(s)
    a = s.publisher
    s.extra_snapshot = lambda: {"A.properties": _listing(a)}
    s.step(
        "form: item add",
        lambda: _www_post(
            a, f"properties/{LIST}/items", {"action": "add", "item_value": "three"}
        ),
    )
    s.step(
        "form: item update",
        lambda: _www_post(
            a,
            f"properties/{LIST}/items",
            {"action": "update", "item_index": "0", "item_value": "one, again"},
        ),
    )
    s.step(
        "form: item delete",
        lambda: _www_post(
            a, f"properties/{LIST}/items", {"action": "delete", "item_index": "1"}
        ),
    )
    s.step(
        "form: list create",
        lambda: _www_post(
            a, "properties", {"property_name": "fresh", "property_type": "list"}
        ),
    )
    s.step(
        "form: metadata edit",
        lambda: _www_post(
            a,
            f"properties/{LIST}/metadata",
            {"action": "update", "description": "d", "explanation": "e"},
        ),
    )
    s.step(
        "form: property create",
        lambda: _www_post(
            a, "properties", {"property_name": "color", "property_value": "red"}
        ),
    )
    s.step(
        "form: property update",
        lambda: _www_post(a, "properties/color", {"property_value": "blue"}),
    )
    s.step("www: delete the list", lambda: _www_delete(a, LIST))
    s.step("www: delete the property", lambda: _www_delete(a, "color"))
    check("WL10.target", s.recording(), variant=topology)


# ---------------------------------------------------------------------------
# The SDK
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl11_subtarget(wire_pair, topology):
    """WL11.subtarget: the operations of WL11.target, subscribed to the list."""
    s = _pair(wire_pair, topology, "subtarget")
    a = s.publisher

    def update_by_index() -> None:
        _lst(a)[0] = {"id": "b", "text": "two, again"}

    def delete_by_index() -> None:
        del _lst(a)[1]

    s.step("append", lambda: _lst(a).append({"id": "a", "text": "one"}))
    s.step("insert at the front", lambda: _lst(a).insert(0, {"id": "b"}))
    s.step("insert in the middle", lambda: _lst(a).insert(1, {"id": "c"}))
    s.step("update by index", update_by_index)
    s.step("update_where", lambda: _lst(a).update_where("id", "c", {"id": "c", "v": 2}))
    s.step("delete by index", delete_by_index)
    s.step("extend", lambda: _lst(a).extend([{"id": "d"}, {"id": "e"}, {"id": "f"}]))
    s.step("pop()", lambda: _lst(a).pop())
    s.step("pop(0)", lambda: _lst(a).pop(0))
    s.step("remove_where", lambda: _lst(a).remove_where("id", "d"))
    s.step("set_description", lambda: _lst(a).set_description("wire notes"))
    s.step("clear", lambda: _lst(a).clear())
    s.step("delete", lambda: _lst(a).delete())
    check("WL11.subtarget", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl12_target(wire_pair, topology):
    """WL12.target: SDK ``append`` of falsy items."""
    s = _pair(wire_pair, topology, "target")
    a = s.publisher
    for label, item in (
        ("0", 0),
        ('""', ""),
        ("False", False),
        ("None", None),
        ("[]", []),
        ("{}", {}),
    ):
        s.step(f"append {label}", lambda item=item: _lst(a).append(item))
    check("WL12.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl13_target(wire_pair, topology, caplog):
    """WL13.target: SDK ``append`` and update of an item over the wire apps'
    span threshold (390,000 bytes): a reference diff, which B logs and skips."""
    s = _pair(wire_pair, topology, "target")
    _seed_list(s, [{"id": "small"}])
    a = s.publisher
    big = {"id": "big", "body": "x" * 400_000}

    def update_big() -> None:
        _lst(a)[1] = {**big, "n": 1}

    with caplog.at_level(logging.WARNING, logger="actingweb.remote_storage"):
        s.step("append a spanned item", lambda: _lst(a).append(big))
        s.step("update it", update_big)
    skipped = [
        r.getMessage()
        for r in caplog.records
        if r.name == "actingweb.remote_storage"
        and "reference to values over the span threshold" in r.getMessage()
    ]
    assert len(skipped) == 2, skipped
    assert "'append'" in skipped[0] and "'update'" in skipped[1]
    check("WL13.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl14_target(wire_pair, topology):
    """WL14.target: three SDK ``append``s, then ``pop(-2)``."""
    s = _pair(wire_pair, topology, "target")
    a = s.publisher
    for n in (1, 2, 3):
        s.step(f"append {n}", lambda n=n: _lst(a).append({"n": n}))
    s.step("pop(-2)", lambda: _lst(a).pop(-2))
    check("WL14.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl15_target(wire_pair, topology):
    """WL15.target: a grant excluding ``x``; a scalar named ``list:x`` set
    over REST, then a scalar ``x``."""
    s = wire_pair(
        topology,
        grant={"patterns": ["*"], "operations": ["read"], "excluded_patterns": ["x"]},
    )
    a = s.publisher
    # A's own listing after each step (read outside the recorder's steps).
    s.extra_snapshot = lambda: {"A.properties": _listing(a)}
    s.step("put list:x", lambda: _put(a, "list:x", {"v": 1}))
    s.step("put x", lambda: _put(a, "x", {"v": 2}))
    check("WL15.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl16_subtarget(wire_pair, topology):
    """WL16.subtarget: ``POST /properties`` with two names, one of them the
    subtarget ``first``."""
    s = wire_pair(topology, grant=["*"], subtarget="first")
    a = s.publisher
    s.step(
        "post two properties",
        lambda: requests.post(
            f"{a.url}/properties",
            json={"first": {"v": 1}, "second": "two"},
            auth=a.basic,
        ),
    )
    check("WL16.subtarget", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wl17_target(wire_pair, topology):
    """WL17.target: SDK ``suspend("properties", "notes")``, the list deleted,
    ``resume``."""
    s = _pair(wire_pair, topology, "target")
    _seed_list(s)
    a = s.publisher
    s.step(
        "suspend notes",
        lambda: a.interface().subscriptions.suspend("properties", LIST),
    )
    s.step("delete the list (SDK)", lambda: _lst(a).delete())
    s.step(
        "resume notes",
        # From the test thread: the resync and B's fetch nest in the step.
        lambda: a.interface().subscriptions.resume("properties", LIST),
    )
    check("WL17.target", s.recording(), variant=topology)
