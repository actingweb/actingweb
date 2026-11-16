"""Callback delivery in the two deployment shapes (spec-1-5 Phase 4), on the
wire apps without recordings.

- One request per function instance: the own-host switch off and a delivery
  budget set; a subscriber that never answers does not hold the write past
  the budget, and the others hold the change.
- A long-running server: two simultaneous writes, each with four
  low-granularity subscribers that fetch back from the publisher through
  another origin of the same process, both complete.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import pytest
import requests

from ._wire import wait_until
from .test_wire_peer_paths import _put

pytestmark = [pytest.mark.wire, pytest.mark.xdist_group(name="wire_peer_paths")]


class _BlackHole:
    """A TCP server that accepts and never answers."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.conns: list[socket.socket] = []
        self.stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        self.sock.settimeout(0.2)
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
                self.conns.append(conn)
            except OSError:
                continue

    def close(self) -> None:
        self.stop = True
        for c in self.conns:
            c.close()
        self.sock.close()


def _held(sub: Any, publisher: Any, name: str) -> Any:
    from actingweb.remote_storage import RemotePeerStore

    store = RemotePeerStore(
        actor=sub.interface(), peer_id=publisher.id, validate_peer_id=False
    )
    return store.get_value(name)


def test_the_function_shape_answers_inside_the_budget(wire_pair: Any) -> None:
    from actingweb.trust import Trust

    s = wire_pair("same_host", grant=["*"])
    a = s.publisher
    others = [s.subscribers[0]]
    for name in ("C", "D"):
        others.append(wire_pair.add_subscriber(s, name, grant=["*"]))
    hang = wire_pair.add_subscriber(s, "H", grant=["*"])
    hole = _BlackHole()
    trust = Trust(actor_id=a.id, peerid=hang.id, config=a.host.config)
    assert trust.modify(baseuri=f"http://127.0.0.1:{hole.port}/{hang.id}")
    sub_config = a.host.config._subscription_config
    saved = (
        sub_config.serialize_own_host_callbacks,
        sub_config.callback_delivery_budget_seconds,
    )
    sub_config.serialize_own_host_callbacks = False
    sub_config.callback_delivery_budget_seconds = 2.0
    try:
        start = time.monotonic()
        assert _put(a, "x", {"v": 1}).status_code == 204
        elapsed = time.monotonic() - start
        assert elapsed < 4.0, elapsed
        for sub in others:
            wait_until(lambda sub=sub: _held(sub, a, "x") == {"v": 1}, timeout=15)
    finally:
        (
            sub_config.serialize_own_host_callbacks,
            sub_config.callback_delivery_budget_seconds,
        ) = saved
        hole.close()


def _two_writes(wire_pair: Any) -> tuple[Any, list[Any], list[int]]:
    s = wire_pair("two_hosts", grant=["*"], granularity="low")
    a = s.publisher
    subs = [s.subscribers[0]] + [
        wire_pair.add_subscriber(s, name, host="peer", grant=["*"], granularity="low")
        for name in ("C", "D", "E")
    ]
    results: list[int] = []

    def write(name: str) -> None:
        results.append(_put(a, name, {"v": name}).status_code)

    threads = [threading.Thread(target=write, args=(n,)) for n in ("x", "y")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return a, subs, results


def test_two_simultaneous_writes_with_fetching_subscribers_complete(
    wire_pair: Any,
) -> None:
    """Both writes are answered while every subscriber fetches back from the
    publisher through another origin of the same process: the handler pool
    does not fill (the plan's check on the default bound)."""
    a, _subs, results = _two_writes(wire_pair)
    assert results == [204, 204]
    assert requests.get(f"{a.url}/meta/id").status_code == 200


@pytest.mark.xfail(
    # Not strict: the race is timing-dependent and passes now and then
    # (it XPASSed on CI, Python 3.11 with DynamoDB, PR #178).
    strict=False,
    reason=(
        "Pre-existing, not the sender's: two concurrent low-granularity "
        "writes leave one subscriber without one of them until its next "
        "callback or poll (fails with the serial sender of Phase 3 too). "
        "thoughts/todo/low-granularity-concurrent-writes-replica.md"
    ),
)
def test_two_simultaneous_low_granularity_writes_reach_every_replica(
    wire_pair: Any,
) -> None:
    a, subs, _results = _two_writes(wire_pair)

    def all_hold() -> bool:
        return all(
            _held(sub, a, "x") == {"v": "x"} and _held(sub, a, "y") == {"v": "y"}
            for sub in subs
        )

    wait_until(all_hold, timeout=20)
