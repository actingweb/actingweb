"""The outbound callback sender (spec-1-5 Phase 4): the bound per write, own-host
subscribers one at a time, ordered units, the budget, tasks on a running loop,
and the origin rule."""

from __future__ import annotations

import asyncio
import gc
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import requests

from actingweb import callback_sender as cs


class _Counter:
    """A fake ``requests.post`` that counts requests in flight."""

    def __init__(self, delay: float = 0.05, hang: set[str] | None = None) -> None:
        self.delay = delay
        self.hang = hang or set()
        self.lock = threading.Lock()
        self.now = 0
        self.peak = 0
        self.urls: list[str] = []
        self.per_group: dict[str, int] = {}
        self.peak_group: dict[str, int] = {}

    def __call__(self, url: str, data: Any, headers: Any, timeout: Any) -> Any:
        group = url.split("//", 1)[1].split("/", 1)[0]
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.per_group[group] = self.per_group.get(group, 0) + 1
            self.peak_group[group] = max(
                self.peak_group.get(group, 0), self.per_group[group]
            )
            self.urls.append(url)
        try:
            if url in self.hang:
                # A peer that accepts slowly and never answers: the connect
                # and the read timeout, one after the other.
                time.sleep(min(timeout[0] + timeout[1], 5))
                raise requests.Timeout("read timed out")
            time.sleep(self.delay)
            return SimpleNamespace(status_code=204, text="")
        finally:
            with self.lock:
                self.now -= 1
                self.per_group[group] -= 1


def _config(**sub: Any) -> Any:
    return SimpleNamespace(_subscription_config=SimpleNamespace(**sub))


def _unit(url: str, own: bool = False, results: list[Any] | None = None) -> cs.Unit:
    return cs.Unit(
        sends=[cs.PreparedSend(url=url, body=b"{}", headers={})],
        own_host=own,
        on_result=(lambda ok, url=url: results.append((url, ok)))
        if results is not None
        else None,
    )


@pytest.mark.parametrize(("bound", "peak"), [(None, 4), (5, 5), (1, 1)])
def test_remote_subscribers_peak_at_the_bound(bound: Any, peak: int) -> None:
    fake = _Counter()
    sub: dict[str, Any] = {} if bound is None else {"max_concurrent_callbacks": bound}
    units = [_unit(f"http://peer{i}.example/cb") for i in range(5)]
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(units, _config(**sub), wait=True)
    assert fake.peak == peak
    assert all(u.delivered for u in units)


def test_a_subscriber_that_hangs_does_not_delay_the_others() -> None:
    hang = "http://slow.example/cb"
    fake = _Counter(hang={hang})
    units = [_unit(hang)] + [_unit(f"http://peer{i}.example/cb") for i in range(3)]
    finished: dict[str, float] = {}
    start = time.monotonic()

    def record(unit: cs.Unit) -> Any:
        url = unit.sends[0].url
        return lambda ok: finished.setdefault(url, time.monotonic() - start)

    for unit in units:
        unit.on_result = record(unit)
    with (
        mock.patch.object(cs.requests, "post", fake),
        mock.patch.object(cs, "DIFF_TIMEOUT", (0.2, 0.5)),
    ):
        for unit in units:
            unit.sends[0].timeout = (0.2, 0.5)
        cs.deliver(units, _config(), wait=True)
    assert units[0].delivered is False
    assert all(finished[f"http://peer{i}.example/cb"] < 0.4 for i in range(3))


def test_own_host_subscribers_are_sent_one_at_a_time() -> None:
    fake = _Counter()
    units = [_unit(f"http://self.example/a{i}/cb", own=True) for i in range(3)] + [
        _unit(f"http://peer{i}.example/cb") for i in range(3)
    ]
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(units, _config(), wait=True)
    assert fake.peak_group["self.example"] == 1
    assert fake.peak >= 2  # the remote ones overlapped


def test_the_own_host_switch_puts_them_under_the_bound() -> None:
    fake = _Counter()
    units = [_unit(f"http://self.example/a{i}/cb", own=True) for i in range(5)]
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(units, _config(serialize_own_host_callbacks=False), wait=True)
    assert fake.peak_group["self.example"] == 4


def test_a_units_sends_arrive_in_order_while_others_run() -> None:
    fake = _Counter()
    ordered = cs.Unit(
        sends=[
            cs.PreparedSend(url="http://two.example/clear", body=b"{}", headers={}),
            cs.PreparedSend(url="http://two.example/full", body=b"{}", headers={}),
        ]
    )
    units = [ordered] + [_unit(f"http://peer{i}.example/cb") for i in range(3)]
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(units, _config(), wait=True)
    mine = [u for u in fake.urls if u.startswith("http://two.example")]
    assert mine == ["http://two.example/clear", "http://two.example/full"]


def test_the_budget_ends_delivery_and_skips_what_was_not_started() -> None:
    hang = {f"http://peer{i}.example/cb" for i in range(6)}
    fake = _Counter(hang=hang)
    units = [_unit(url) for url in sorted(hang)]
    start = time.monotonic()
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(
            units,
            _config(max_concurrent_callbacks=4, callback_delivery_budget_seconds=1.0),
            wait=True,
        )
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, elapsed
    assert len(fake.urls) == 4  # the two not started were never connected to
    assert all(u.delivered is False for u in units)


def test_no_budget_keeps_the_timeouts() -> None:
    assert cs._Deadline(None).clip((5.0, 10.0)) == (5.0, 10.0)  # noqa: SLF001
    assert cs._Deadline(2.0).clip((5.0, 10.0))[1] <= 2.0  # type: ignore[index]  # noqa: SLF001


def test_on_a_running_loop_the_sends_are_kept_tasks() -> None:
    fake_status: list[str] = []

    async def fake_send(send: cs.PreparedSend) -> int:
        await asyncio.sleep(0.05)
        fake_status.append(send.url)
        return 204

    async def scenario() -> None:
        units = [_unit(f"http://peer{i}.example/cb") for i in range(5)]
        with mock.patch.object(cs, "send_async", fake_send):
            assert cs.deliver(units, _config(), wait=False) is False
            assert fake_status == []  # not awaited
            gc.collect()
            await asyncio.sleep(0.5)
        assert sorted(fake_status) == sorted(u.sends[0].url for u in units)
        assert not cs._TASKS  # noqa: SLF001

    asyncio.run(scenario())


def test_with_sync_callbacks_on_a_running_loop_the_call_waits() -> None:
    fake = _Counter()

    async def scenario() -> None:
        units = [_unit(f"http://peer{i}.example/cb") for i in range(3)]
        with mock.patch.object(cs.requests, "post", fake):
            assert cs.deliver(units, _config(), wait=True) is True
        assert all(u.delivered for u in units)

    asyncio.run(scenario())


def test_a_send_on_a_pool_thread_sees_the_callers_context() -> None:
    import contextvars

    marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="")
    seen: list[str] = []

    def post(url: str, data: Any, headers: Any, timeout: Any) -> Any:
        seen.append(marker.get())
        return SimpleNamespace(status_code=204, text="")

    marker.set("req-1")
    units = [_unit(f"http://peer{i}.example/cb") for i in range(3)]
    with mock.patch.object(cs.requests, "post", post):
        cs.deliver(units, _config(), wait=True)
    assert seen == ["req-1"] * 3


@pytest.mark.parametrize(
    ("base", "own"),
    [
        ("https://App.Example.com/a1", True),
        ("https://app.example.com:443/a1", True),
        ("http://app.example.com/a1", False),
        ("https://app.example.com:8443/a1", False),
        ("https://other.example.com/a1", False),
    ],
)
def test_own_host_is_decided_by_origin(base: str, own: bool) -> None:
    assert cs.is_own_host(base, "https://app.example.com/") is own


def test_two_writes_each_keep_their_own_bound() -> None:
    fake = _Counter()

    def write(n: int) -> None:
        cs.deliver(
            [_unit(f"http://w{n}p{i}.example/cb") for i in range(4)],
            _config(max_concurrent_callbacks=2),
            wait=True,
        )

    with mock.patch.object(cs.requests, "post", fake):
        threads = [threading.Thread(target=write, args=(n,)) for n in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert fake.peak <= 4
    assert len(fake.urls) == 8


def test_one_remote_and_the_own_host_ones_overlap() -> None:
    fake = _Counter(delay=0.2)
    units = [
        _unit("http://peer0.example/cb"),
        _unit("http://self.example/a/cb", own=True),
    ]
    start = time.monotonic()
    with mock.patch.object(cs.requests, "post", fake):
        cs.deliver(units, _config(), wait=True)
    assert time.monotonic() - start < 0.35  # the longer of them, not the sum
    assert fake.peak == 2


def test_a_unit_stops_at_its_first_failure() -> None:
    sent: list[str] = []

    def post(url: str, data: Any, headers: Any, timeout: Any) -> Any:
        sent.append(url)
        return SimpleNamespace(status_code=503, text="")

    unit = cs.Unit(
        sends=[
            cs.PreparedSend(url="http://two.example/clear", body=b"{}", headers={}),
            cs.PreparedSend(url="http://two.example/full", body=b"{}", headers={}),
        ]
    )
    with mock.patch.object(cs.requests, "post", post):
        cs.deliver([unit], _config(), wait=True)
    assert sent == ["http://two.example/clear"]
    assert unit.delivered is False


def test_a_send_that_raises_is_not_delivered_and_the_others_are() -> None:
    def post(url: str, data: Any, headers: Any, timeout: Any) -> Any:
        if "bad" in url:
            raise ValueError("unexpected")
        return SimpleNamespace(status_code=204, text="")

    units = [_unit("http://bad.example/cb"), _unit("http://good.example/cb")]
    with mock.patch.object(cs.requests, "post", post):
        cs.deliver(units, _config(), wait=True)
    assert [u.delivered for u in units] == [False, True]


def test_the_budget_is_shared_by_every_delivery_of_a_request() -> None:
    from actingweb import request_context

    hang = {"http://h1.example/cb", "http://h2.example/cb"}
    fake = _Counter(hang=hang)
    request_context.set_request_context(request_id="req-budget")
    try:
        start = time.monotonic()
        with mock.patch.object(cs.requests, "post", fake):
            for url in sorted(hang):
                cs.deliver(
                    [_unit(url)],
                    _config(callback_delivery_budget_seconds=1.0),
                    wait=True,
                )
        assert time.monotonic() - start < 1.6
    finally:
        request_context.clear_request_context()
    assert request_context.get_delivery_deadline() is None


def test_with_callback_delivery_does_not_turn_on_incoming_processing() -> None:
    from actingweb.interface import ActingWebApp

    app = ActingWebApp(aw_type="urn:actingweb:test:delivery", fqdn="x.example")
    app.with_callback_delivery(
        callback_delivery_budget_seconds=20, serialize_own_host_callbacks=False
    )
    sub = app.get_subscription_config()
    assert sub.enabled is False
    assert sub.callback_delivery_budget_seconds == 20
    app.with_subscription_processing()
    sub = app.get_subscription_config()
    assert sub.enabled is True
    assert sub.callback_delivery_budget_seconds == 20  # kept in either order
    assert sub.serialize_own_host_callbacks is False
