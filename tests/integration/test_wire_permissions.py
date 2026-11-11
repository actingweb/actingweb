"""Wire rows: what a publisher grants, and what the subscriber holds of it.

``thoughts/plans/2026-11-06-subscription-wire-baseline.md``, Phase 1 (rows
``WP2`` to ``WP6``; ``WP1`` is the security plan's, and ``WP5`` is recorded
by ``WD20``). Each row records today's behaviour, right or wrong;
``wire/rows.toml`` says what is known to be wrong and which later plan phase
may change the recording.

Unless a row says otherwise: a ``friend`` pair, granularity ``high``, a
target-level subscription, both topologies.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ._wire import Scenario, check, wait_until
from .test_wire_peer_paths import _put, _stored_permissions

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

TOPOLOGIES = ["same_host", "two_hosts"]


def _excluding(*names: str) -> dict[str, Any]:
    return {"patterns": ["*"], "operations": ["read"], "excluded_patterns": list(names)}


def _grant(s: Scenario, properties: Any) -> requests.Response:
    a, b = s.publisher, s.subscribers[0]
    return requests.put(
        f"{a.url}/trust/{s.relationship}/{b.id}/permissions",
        json={"properties": properties},
        auth=a.basic,
    )


def _stored_holds(s: Scenario, text: str) -> Any:
    """A settle: B's stored copy of the grant mentions ``text`` (the
    permission callback is sent off the request)."""
    return lambda: wait_until(lambda: text in _stored_permissions(s))


def _find(entries: list[dict[str, Any]], fragment: str) -> dict[str, Any] | None:
    for entry in entries:
        if fragment in entry.get("path", ""):
            return entry
        found = _find(entry.get("children", []), fragment)
        if found:
            return found
    return None


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wp2_grant_shrunk(wire_pair, topology):
    """WP2: B holds the list ``notes``; A's grant then excludes it."""
    s = wire_pair(topology, grant=["*"])
    a = s.publisher
    a.interface().property_lists.notes.append({"id": "a"})
    s.step(
        "A excludes notes",
        lambda: _grant(s, _excluding("notes")),
        settle=_stored_holds(s, "notes"),
    )
    check("WP2", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wp3_grant_deleted(wire_pair, topology):
    """WP3: A's grant to B carries an exclusion; then
    ``DELETE /<A>/trust/<rel>/<B>/permissions``."""
    s = wire_pair(topology, grant=_excluding("hidden"))
    a, b = s.publisher, s.subscribers[0]
    wait_until(lambda: "hidden" in _stored_permissions(s))
    s.step(
        "A deletes its grant",
        lambda: requests.delete(
            f"{a.url}/trust/{s.relationship}/{b.id}/permissions", auth=a.basic
        ),
    )
    check("WP3", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wp4_older_permission_callback(wire_pair, topology):
    """WP4: two grant changes, then the first one's permission callback
    posted to B again with A's bearer (older than what B holds)."""
    s = wire_pair(topology, grant=["*"])
    b = s.subscribers[0]
    s.step(
        "A excludes first",
        lambda: _grant(s, _excluding("first")),
        settle=_stored_holds(s, "first"),
    )
    callback = _find(s.steps[-1]["wire"], "/callbacks/permissions/")
    assert callback is not None, s.steps[-1]["wire"]
    s.step(
        "A excludes second",
        lambda: _grant(s, _excluding("second")),
        settle=_stored_holds(s, "second"),
    )
    s.step(
        "the first callback posted again",
        lambda: requests.post(
            f"{b.host.url}{callback['path']}",
            json=callback["request"],
            headers={"Authorization": callback["auth"]},
        ),
    )
    check("WP4", s.recording(), variant=topology)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_wp6_baseline_under_an_exclusion(wire_pair, topology):
    """WP6: A holds ``shown`` and ``hidden`` and excludes ``hidden``; B's
    creator subscribes (the baseline fetch)."""
    s = wire_pair(topology, grant=_excluding("hidden"), subscribe=False)
    a, b = s.publisher, s.subscribers[0]
    wait_until(lambda: "hidden" in _stored_permissions(s))
    assert _put(a, "shown", {"v": 1}).status_code == 204
    assert _put(a, "hidden", {"v": 2}).status_code == 204
    s.step(
        "B's creator subscribes",
        lambda: requests.post(
            f"{b.url}/subscriptions",
            json={"peerid": a.id, "target": "properties", "granularity": "high"},
            auth=b.basic,
        ),
    )
    check("WP6", s.recording(), variant=topology)
