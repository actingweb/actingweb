"""``actingweb-peer-state`` on a live pair.

``thoughts/plans/2026-11-06-peer-authorisation-fixes.md``, Phase 4: stale
state planted through the library (a permission copy for a peer with no
trust, a future-dated copy for the live peer, a pending row for a
subscription never made) is removed by ``prune --apply`` (the live peer's
copy rebuilt by a query), and the pair's next callback and permission
update apply as before.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import requests

from actingweb.attribute import Attributes
from actingweb.constants import PEER_PERMISSIONS_BUCKET
from actingweb.maintenance import peer_state

from ._wire import wait_until

pytestmark = [pytest.mark.xdist_group(name="wire_peer_paths")]


def test_prune_removes_the_stale_and_the_pair_still_works(wire_pair, monkeypatch):
    s = wire_pair("same_host", grant=["*"])
    a, b = s.publisher, s.subscribers[0]
    config = b.host.config
    monkeypatch.setenv("DATABASE_BACKEND", config.database)
    gone = uuid.uuid4().hex
    perms = Attributes(actor_id=b.id, bucket=PEER_PERMISSIONS_BUCKET, config=config)
    ahead = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    live = perms.get_attr(name=f"{b.id}:{a.id}") or {}
    assert live, "the pair's grant stored no permission copy at B"
    raw = live.get("data") or {}
    data = dict(json.loads(raw) if isinstance(raw, str) else raw)
    data["fetched_at"] = ahead
    assert perms.set_attr(name=f"{b.id}:{a.id}", data=data)
    assert perms.set_attr(name=f"{b.id}:{gone}", data={"fetched_at": ahead})
    states = Attributes(actor_id=b.id, bucket="_callback_state", config=config)
    assert states.set_attr(name=f"pending:{gone}:forged", data=[1])

    assert peer_state.main(["prune", b.id, "--apply", "--rps", "0"]) == 1
    fresh = Attributes(actor_id=b.id, bucket=PEER_PERMISSIONS_BUCKET, config=config)
    # The live peer's future-dated copy is removed and rebuilt at once by a
    # query to A (reverify-2, Issue 5), stamped now; the copy for a peer with
    # no trust is gone.
    assert set(fresh.get_bucket() or {}) == {f"{b.id}:{a.id}"}
    rebuilt = fresh.get_attr(name=f"{b.id}:{a.id}") or {}
    raw = rebuilt.get("data") or {}
    rebuilt_at = dict(json.loads(raw) if isinstance(raw, str) else raw)["fetched_at"]
    assert datetime.fromisoformat(rebuilt_at) <= datetime.now(UTC)
    # The restart the command asks for: the wire apps run in this process,
    # and B's store still holds the copy it cached before the prune.
    from actingweb.peer_permissions import get_peer_permission_store

    get_peer_permission_store(config)._cache.clear()  # noqa: SLF001 - a restart
    fresh_states = Attributes(actor_id=b.id, bucket="_callback_state", config=config)
    assert f"pending:{gone}:forged" not in set(fresh_states.get_bucket() or {})

    # A's next write reaches B's replica.
    assert (
        requests.put(
            f"{a.url}/properties/after", json={"v": 1}, auth=a.basic
        ).status_code
        == 204
    )
    from actingweb.remote_storage import RemotePeerStore

    store = RemotePeerStore(actor=b.interface(), peer_id=a.id, validate_peer_id=False)
    wait_until(lambda: store.get_value("after") == {"v": 1})

    # A's next permission update is stored at B (it was blocked by the
    # future-dated copy before the prune).
    assert requests.put(
        f"{a.url}/trust/friend/{b.id}/permissions",
        json={
            "properties": {
                "patterns": ["*"],
                "operations": ["read"],
                "excluded_patterns": ["after-prune"],
            }
        },
        auth=a.basic,
    ).status_code in (200, 201, 204)

    def stored() -> bool:
        # A fresh object: an Attributes instance serves its rows from a cache.
        fresh = Attributes(actor_id=b.id, bucket=PEER_PERMISSIONS_BUCKET, config=config)
        row = fresh.get_attr(name=f"{b.id}:{a.id}") or {}
        return "after-prune" in str(row.get("data"))

    wait_until(stored)
