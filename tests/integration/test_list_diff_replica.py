"""A subscriber's replica follows the publisher's list after every list edit
over HTTP, the web UI and the SDK, at target and subtarget level
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 4). Not a wire
row: the replica is compared, not the wire."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import requests

from ._wire import Scenario, wait_for_quiet
from .test_wire_list_properties import _www_delete, _www_post
from .test_wire_peer_paths import _replica, _replica_settles

pytestmark = [pytest.mark.xdist_group(name="wire_peer_paths")]

LIST = "notes"
STRAY = {"index", "value", "list", "operation", LIST}


def _lst(s: Scenario, name: str = LIST) -> Any:
    return getattr(s.publisher.interface().property_lists, name)


def _items(s: Scenario, body: dict[str, Any]) -> requests.Response:
    a = s.publisher
    return requests.post(f"{a.url}/properties/{LIST}/items", json=body, auth=a.basic)


def _follows(s: Scenario, name: str = LIST) -> None:
    """Wait until B's replica of ``name`` equals A's list (or both lack it)."""
    wait_for_quiet()
    lists = s.publisher.interface().property_lists
    expected = getattr(lists, name).to_list() if lists.exists(name) else None

    def same(replica: dict[str, Any]) -> bool:
        return replica["lists"].get(name) == expected

    try:
        _replica_settles(s, same)()
    except TimeoutError:
        pass
    replica = _replica(s)
    assert replica["lists"].get(name) == expected, (name, replica)
    assert not STRAY & set(replica["scalars"]), replica["scalars"]


@pytest.mark.parametrize("level", ["target", "subtarget"])
def test_every_list_edit_reaches_the_replica(wire_pair, level) -> None:
    s = wire_pair(
        "same_host", grant=["*"], subtarget=LIST if level == "subtarget" else ""
    )
    a = s.publisher
    _lst(s).extend([{"n": 0}, {"n": 1}])
    _follows(s)

    edits: list[tuple[str, Callable[[], Any]]] = [
        ("append", lambda: _items(s, {"action": "add", "item_value": {"n": 2}})),
        (
            "update",
            lambda: _items(
                s, {"action": "update", "item_index": 0, "item_value": {"n": "u"}}
            ),
        ),
        ("delete", lambda: _items(s, {"action": "delete", "item_index": 1})),
        (
            "put index",
            lambda: requests.put(
                f"{a.url}/properties/{LIST}",
                params={"index": "0"},
                json={"n": "p"},
                auth=a.basic,
            ),
        ),
        ("insert at front", lambda: _lst(s).insert(0, {"n": "front"})),
        ("pop", lambda: _lst(s).pop()),
        ("remove", lambda: _lst(s).remove({"n": "front"})),
        (
            "www add",
            lambda: _www_post(
                a, f"properties/{LIST}/items", {"action": "add", "item_value": '"w"'}
            ),
        ),
        (
            "www update",
            lambda: _www_post(
                a,
                f"properties/{LIST}/items",
                {"action": "update", "item_index": "0", "item_value": '"w0"'},
            ),
        ),
        (
            "www delete",
            lambda: _www_post(
                a, f"properties/{LIST}/items", {"action": "delete", "item_index": "0"}
            ),
        ),
        (
            "bulk 10",
            lambda: requests.post(
                f"{a.url}/properties",
                json={
                    LIST: {
                        "items": [
                            {"index": i, "n": f"b{i}"}
                            for i in range(len(_lst(s).to_list()) + 8)
                        ][:10]
                    }
                },
                auth=a.basic,
            ),
        ),
        (
            "bulk 30",
            lambda: requests.post(
                f"{a.url}/properties",
                json={
                    LIST: {
                        "items": [
                            {"index": i, "n": f"c{i}"}
                            for i in range(len(_lst(s).to_list()) + 30)
                        ][:30]
                    }
                },
                auth=a.basic,
            ),
        ),
        ("clear", lambda: _lst(s).clear()),
    ]
    for label, edit in edits:
        response = edit()
        if isinstance(response, requests.Response):
            assert response.status_code < 400, (label, response.status_code)
        _follows(s)

    if level == "target":
        create = requests.post(
            f"{a.url}/properties", json={"fresh": {"_type": "list"}}, auth=a.basic
        )
        assert create.status_code == 201
        _follows(s, "fresh")
        assert _replica(s)["lists"].get("fresh") == []
        www_create = _www_post(
            a, "properties", {"property_name": "fresh2", "property_type": "list"}
        )
        assert www_create.status_code < 400
        _follows(s, "fresh2")
        assert _www_delete(a, "fresh2").status_code < 400
        _follows(s, "fresh2")

    deleted = requests.delete(f"{a.url}/properties/{LIST}", auth=a.basic)
    assert deleted.status_code == 204
    _follows(s)
