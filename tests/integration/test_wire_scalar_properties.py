"""Wire rows: scalar property writes and what the subscriber holds.

``thoughts/plans/2026-11-06-subscription-wire-baseline.md``, Phase 1 (rows
``WS1`` to ``WS9``). Each row records today's behaviour, right or wrong;
``wire/rows.toml`` says what is known to be wrong and which later plan phase
may change the recording.

Unless a row says otherwise: granularity ``high``, a ``friend`` pair with a
grant of ``*``, writes over REST. Setup before the first step (seeding the
publisher, B's first copy) is not recorded.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ._wire import Scenario, WireActor, check
from .test_wire_peer_paths import _put

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]
LEVELS = ["target", "subtarget", "resource"]


def _delete(actor: WireActor, path: str) -> requests.Response:
    return requests.delete(f"{actor.url}/properties/{path}", auth=actor.basic)


def _seed(s: Scenario, values: dict[str, Any]) -> None:
    """Write ``values`` at A before the first step (not recorded)."""
    for name, value in values.items():
        response = _put(s.publisher, name, value)
        assert response.status_code in (200, 201, 204), response.text


def _stored_at_a(s: Scenario, name: str) -> None:
    """Snapshot A's own stored value of ``name`` after each step as well."""
    a = s.publisher
    s.extra_snapshot = lambda: {f"A.{name}": a.interface().properties.get(name)}


def _level(level: str, subtarget: str, resource: str) -> dict[str, str]:
    if level == "target":
        return {}
    if level == "subtarget":
        return {"subtarget": subtarget}
    return {"subtarget": subtarget, "resource": resource}


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws1_subtarget(wire_pair, topology):
    """WS1.subtarget: ``PUT /properties/color`` with an object, a string and
    ``""``, under a subscription to the subtarget ``color``."""
    s = wire_pair(topology, grant=["*"], subtarget="color")
    a = s.publisher
    s.step("put object", lambda: _put(a, "color", {"shade": "red", "hex": "#f00"}))
    s.step("put string", lambda: _put(a, "color", "blue"))
    s.step("put empty", lambda: _put(a, "color", ""))
    check("WS1.subtarget", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws2_subtarget(wire_pair, topology):
    """WS2.subtarget: WS1's steps in a pair whose trust type reads exactly
    ``color`` (``wire_named``), so the filter judges the object's keys."""
    s = wire_pair(topology, relationship="wire_named", subtarget="color")
    a = s.publisher
    s.step("put object", lambda: _put(a, "color", {"shade": "red", "hex": "#f00"}))
    s.step("put string", lambda: _put(a, "color", "blue"))
    s.step("put empty", lambda: _put(a, "color", ""))
    check("WS2.subtarget", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_ws3(wire_pair, level, topology):
    """WS3: ``PUT /properties/p/k``, then ``PUT /properties/p/k/j``, with
    ``p`` an object B already holds. Subscribed to the target, the
    subtarget ``p`` or the resource ``p/k``."""
    s = wire_pair(topology, grant=["*"], **_level(level, "p", "k"))
    a = s.publisher
    _seed(s, {"p": {"k": {"j": 0, "i": 1}, "keep": 2}})
    s.step(
        "put p/k",
        lambda: requests.put(
            f"{a.url}/properties/p/k", json={"j": 5, "new": 6}, auth=a.basic
        ),
    )
    s.step(
        "put p/k/j",
        lambda: requests.put(f"{a.url}/properties/p/k/j", json=7, auth=a.basic),
    )
    check(f"WS3.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws4_target(wire_pair, topology):
    """WS4.target: ``POST /properties`` with two names at once."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step(
        "post two properties",
        lambda: requests.post(
            f"{a.url}/properties",
            json={"first": {"v": 1}, "second": "two"},
            auth=a.basic,
        ),
    )
    check("WS4.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
@pytest.mark.parametrize("level", LEVELS)
def test_ws5(wire_pair, level, topology):
    """WS5: ``DELETE /properties/p``, then ``DELETE /properties/q/k``.
    Subscribed to the target, the subtarget ``p`` (target and subtarget
    variants) or the resource ``q/k``."""
    subtarget = "q" if level == "resource" else "p"
    s = wire_pair(topology, grant=["*"], **_level(level, subtarget, "k"))
    a = s.publisher
    _seed(s, {"p": {"v": 1}, "q": {"k": {"v": 2}, "m": 3}})
    s.step("delete p", lambda: _delete(a, "p"))
    s.step("delete q/k", lambda: _delete(a, "q/k"))
    check(f"WS5.{level}", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws6_target(wire_pair, topology):
    """WS6.target: ``DELETE /properties`` with three properties at A."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    _seed(s, {"one": {"v": 1}, "two": "2", "three": {"v": 3}})
    s.step(
        "delete all properties",
        lambda: requests.delete(f"{a.url}/properties", auth=a.basic),
    )
    check("WS6.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws7_target(wire_pair, topology):
    """WS7.target: ``PUT /properties/transformed`` with a string the
    property hook upper-cases: what the diff carries."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    _stored_at_a(s, "transformed")
    s.step("put transformed", lambda: _put(a, "transformed", "blue"))
    check("WS7.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws8_subtarget(wire_pair, topology):
    """WS8.subtarget: a write to a property outside the subtarget."""
    s = wire_pair(topology, grant=["*"], subtarget="color")
    a = s.publisher
    s.step("put other", lambda: _put(a, "other", {"v": 1}))
    check("WS8.subtarget", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws9_subtarget(wire_pair, topology):
    """WS9.subtarget: through the SDK, ``properties["transformed"]`` set
    (the hook upper-cases it), then deleted."""
    s = wire_pair(topology, grant=["*"], subtarget="transformed")
    a = s.publisher
    _stored_at_a(s, "transformed")

    def set_value() -> None:
        a.interface().properties["transformed"] = "blue"

    def delete_value() -> None:
        del a.interface().properties["transformed"]

    s.step("set (SDK)", set_value)
    s.step("delete (SDK)", delete_value)
    check("WS9.subtarget", s.recording(), variant=topology)


# ---------------------------------------------------------------------------
# spec-1-5, Phase 3: the clear, a failed resync fetch, the resync sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws10_clear_with_a_list(wire_pair, topology):
    """WS10.target: ``DELETE /properties`` with two properties and a list at
    A: one diff naming the two properties; the list stays, at A and at B."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    _seed(s, {"one": {"v": 1}, "two": "2"})
    r = requests.post(
        f"{a.url}/properties", json={"notes": {"_type": "list"}}, auth=a.basic
    )
    assert r.status_code == 201, r.text
    r = requests.post(
        f"{a.url}/properties/notes/items",
        json={"action": "add", "item_value": "kept"},
        auth=a.basic,
    )
    assert r.status_code == 201, r.text
    s.step(
        "delete all properties",
        lambda: requests.delete(f"{a.url}/properties", auth=a.basic),
    )
    check("WS10.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws11_resync_fetch_fails(wire_pair, topology):
    """WS11.target: a resync whose baseline fetch fails at B: 503, B's
    sequence unmoved and the rebuild owed; A's next write makes B rebuild,
    and B holds both writes."""
    from unittest import mock

    from actingweb.interface.subscription_manager import SubscriptionManager

    from .test_wire_peer_paths import _replica_settles

    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    s.step("suspend", lambda: a.interface().subscriptions.suspend("properties"))
    s.step("put x", lambda: _put(a, "x", {"v": 1}))
    real = SubscriptionManager._fetch_and_transform_baseline
    failed: list[int] = []

    def fail_once(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not failed:
            failed.append(1)
            return None
        return real(self, *args, **kwargs)

    with mock.patch.object(
        SubscriptionManager, "_fetch_and_transform_baseline", fail_once
    ):
        s.step("resume", lambda: a.interface().subscriptions.resume("properties"))
        s.step(
            "put y",
            lambda: _put(a, "y", {"v": 2}),
            settle=_replica_settles(
                s,
                lambda r: (
                    r["scalars"].get("x") == {"v": 1}
                    and r["scalars"].get("y") == {"v": 2}
                ),
            ),
        )
    assert failed == [1]
    check("WS11.target", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_ws12_resync_sweeps(wire_pair, topology):
    """WS12.target: B holds x; A deletes it while suspended (no diff), then
    resumes: B's resync baseline lacks x, and the sweep removes it."""
    from .test_wire_peer_paths import _replica_settles

    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    _seed(s, {"x": {"v": 1}, "y": {"v": 2}})
    s.step("suspend", lambda: a.interface().subscriptions.suspend("properties"))
    s.step("delete x", lambda: _delete(a, "x"))
    s.step(
        "resume",
        lambda: a.interface().subscriptions.resume("properties"),
        settle=_replica_settles(
            s, lambda r: "x" not in r["scalars"] and r["scalars"].get("y") == {"v": 2}
        ),
    )
    check("WS12.target", s.recording(), variant=topology)
