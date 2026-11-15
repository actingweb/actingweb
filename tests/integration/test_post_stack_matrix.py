"""The post-stack matrix (``thoughts/plans/2026-11-06-spec-1-5.md``, Phase 3,
owned here for ``grant-enforcement-per-route``): a scalar, a nested write, a
list and a delete, each by push, by pull and after a resync, at target,
subtarget and resource level, under a full grant and a grant with one
exclusion. After each round B's replica equals what B may read at A.

Uses the wire apps without recordings.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from ._wire import Scenario, wait_until
from .test_wire_peer_paths import _put, _replica

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]

LEVELS = {"target": ("", ""), "subtarget": ("doc", ""), "resource": ("doc", "pub")}
GRANTS = {
    "full": ["*"],
    "excluding": {
        "patterns": ["*"],
        "operations": ["read"],
        "excluded_patterns": ["doc/sec"],
    },
}


def _view(s: Scenario, subtarget: str, resource: str) -> Any:
    """What B may read at A, at its subscription's level (None: nothing)."""
    a = s.publisher
    path = "/".join(p for p in ("properties", subtarget, resource) if p)
    r = requests.get(
        f"{a.url}/{path}", headers={"Authorization": f"Bearer {s.trust_secret}"}
    )
    if r.status_code == 404:
        return None
    assert r.status_code == 200, (path, r.status_code, r.text)
    return r.json()


def _unwrap(value: Any) -> Any:
    """A replica scalar as the publisher serves it: text is stored as
    ``{"value": text}``."""
    if isinstance(value, dict) and set(value) == {"value"}:
        return value["value"]
    return value


def _held(s: Scenario, subtarget: str, resource: str) -> Any:
    """What B's replica holds at the same level (None: nothing)."""
    replica = _replica(s)
    replica = {
        "scalars": {k: _unwrap(v) for k, v in replica["scalars"].items()},
        "lists": replica["lists"],
    }
    if not subtarget:
        lists = {
            name: {"_list": True, "count": len(items)}
            for name, items in replica["lists"].items()
        }
        return {**replica["scalars"], **lists}
    value = replica["scalars"].get(subtarget)
    if subtarget in replica["lists"]:
        value = replica["lists"][subtarget]
    if not resource:
        return value
    if not isinstance(value, dict):
        return None
    return value.get(resource)


def _equal(s: Scenario, subtarget: str, resource: str) -> bool:
    try:
        return _held(s, subtarget, resource) == _view(s, subtarget, resource)
    except IndexError:  # a list read mid-rewrite
        return False


def _settle(s: Scenario, subtarget: str, resource: str, mode: str) -> None:
    a, b = s.publisher, s.subscribers[0]
    if mode == "pull":
        subs = b.interface().subscriptions.get_subscriptions_to_peer(a.id)
        assert (
            b.interface()
            .subscriptions.sync_subscription(a.id, subs[0].subscription_id)
            .success
        )
    try:
        wait_until(lambda: _equal(s, subtarget, resource), timeout=15)
    except TimeoutError:
        pass  # the assertion after it shows the difference


def _round(s: Scenario, mode: str, writes: Any) -> None:
    a = s.publisher
    if mode == "resync":
        a.interface().subscriptions.suspend("properties")
    writes()
    if mode == "resync":
        a.interface().subscriptions.resume("properties")


@pytest.mark.parametrize("mode", ["push", "pull", "resync"])
@pytest.mark.parametrize("grant", list(GRANTS))
@pytest.mark.parametrize("level", list(LEVELS))
def test_the_replica_equals_what_the_peer_may_read(
    wire_pair: Any, level: str, grant: str, mode: str, monkeypatch: Any
) -> None:
    subtarget, resource = LEVELS[level]
    if mode == "resync":
        # A resync inside the rebuild interval is applied without the sweep
        # and leaves the rebuild owed (one replica listing a minute): the
        # matrix checks the state after that interval.
        from actingweb.callback_processor import CallbackProcessor

        monkeypatch.setattr(CallbackProcessor, "REBUILD_INTERVAL_SECONDS", 0)
    s = wire_pair(
        "same_host",
        grant=GRANTS[grant],
        subtarget=subtarget,
        resource=resource,
        granularity="none" if mode == "pull" else "high",
    )
    a = s.publisher

    def writes() -> None:
        assert _put(a, "doc", {"pub": 1, "sec": 2, "other": 0}).status_code == 204
        assert _put(a, "doc/pub", {"deep": 3}).status_code == 204
        assert _put(a, "color", "blue").status_code == 204
        r = requests.post(
            f"{a.url}/properties", json={"notes": {"_type": "list"}}, auth=a.basic
        )
        assert r.status_code == 201, r.text
        r = requests.post(f"{a.url}/properties/notes", json="one", auth=a.basic)
        assert r.status_code == 201, r.text

    _round(s, mode, writes)
    _settle(s, subtarget, resource, mode)
    assert _held(s, subtarget, resource) == _view(s, subtarget, resource)

    def deletes() -> None:
        assert (
            requests.delete(f"{a.url}/properties/doc/pub", auth=a.basic).status_code
            == 204
        )
        assert (
            requests.delete(f"{a.url}/properties/color", auth=a.basic).status_code
            == 204
        )

    _round(s, mode, deletes)
    _settle(s, subtarget, resource, mode)
    assert _held(s, subtarget, resource) == _view(s, subtarget, resource)

    def delete_doc() -> None:
        assert (
            requests.delete(f"{a.url}/properties/doc", auth=a.basic).status_code == 204
        )

    _round(s, mode, delete_doc)
    _settle(s, subtarget, resource, mode)
    assert _held(s, subtarget, resource) == _view(s, subtarget, resource)
