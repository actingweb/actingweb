"""Outbound subscription callbacks: one sender for every subscriber of a write
(3.16, ``thoughts/plans/2026-11-06-spec-1-5.md`` Phase 4).

``Actor.register_diffs`` and the resync path prepare each subscriber's
callbacks (sequence, stored diff, permission filter, body) and hand them here
as *units*: the ordered sends one subscriber is owed for this write. The
sender delivers them:

- **Concurrently, with a bound per write.** Remote subscribers are sent at
  most ``max_concurrent_callbacks`` at a time (default 4).
- **Own-host subscribers one at a time** (``serialize_own_host_callbacks``,
  default on): a subscriber served by the publisher's own process needs one
  of its handler threads to answer, and a low-granularity one a second for
  its fetch back. The two groups run alongside each other.
- **A unit's sends in order**: the clear and the full state of the fallback
  for a peer without resync arrive in sequence.
- **Off the event loop, or with ``with_sync_callbacks``,** the call returns
  when every send has answered, timed out, or been cut by the delivery
  budget. **On a running loop without it,** the sends are tasks kept in a
  module-level set until done and not awaited, as before.
- **The budget** (``callback_delivery_budget_seconds``, off by default): the
  connect and read timeouts of each send are clipped to what is left, and a
  send that would start with nothing left is not made. Every diff was stored
  and numbered before any send, so a skipped subscriber sees the gap at its
  next callback or polls.

Callback sends do not write ``Actor.last_response_code`` (3.16).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_CALLBACKS = 4
# (connect, read) for a diff callback and for a resync callback.
DIFF_TIMEOUT = (5.0, 10.0)
RESYNC_TIMEOUT = (5.0, 30.0)

# Tasks scheduled on a running loop, kept until done so none is collected.
_TASKS: set[asyncio.Task[Any]] = set()


@dataclass
class PreparedSend:
    """One HTTP POST of a callback, ready to send."""

    url: str
    body: bytes
    headers: dict[str, str]
    sequence: Any = None
    peer_id: str = ""
    timeout: tuple[float, float] = DIFF_TIMEOUT


@dataclass
class Unit:
    """The ordered sends one subscriber is owed for a write, and what to do
    with the outcome (``on_result(delivered)``, called once)."""

    sends: list[PreparedSend]
    own_host: bool = False
    on_result: Callable[[bool], None] | None = None
    delivered: bool | None = field(default=None, init=False)


def origin(url: str) -> tuple[str, str, int] | None:
    """A URL's origin: scheme, lower-cased host and port with the scheme's
    default filled in; None for one that does not parse."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if not scheme or not host:
        return None
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme, 0)
    return scheme, host, port


def is_own_host(base_uri: str, publisher_root: str) -> bool:
    """Whether a subscriber's base URI is on the publisher's own origin."""
    theirs = origin(base_uri)
    return theirs is not None and theirs == origin(publisher_root)


@dataclass
class Settings:
    bound: int = DEFAULT_MAX_CONCURRENT_CALLBACKS
    budget: float | None = None
    serialize_own_host: bool = True


def settings_for(config: Any) -> Settings:
    """The sender's settings from a ``Config`` (its subscription processing
    configuration, when set)."""
    sub = getattr(config, "_subscription_config", None)
    bound = getattr(sub, "max_concurrent_callbacks", None)
    if not isinstance(bound, int) or isinstance(bound, bool) or bound < 1:
        bound = DEFAULT_MAX_CONCURRENT_CALLBACKS
    budget = getattr(sub, "callback_delivery_budget_seconds", None)
    if not isinstance(budget, int | float) or isinstance(budget, bool) or budget <= 0:
        budget = None
    serialize = getattr(sub, "serialize_own_host_callbacks", True)
    return Settings(
        bound=bound,
        budget=float(budget) if budget else None,
        serialize_own_host=bool(serialize),
    )


class _Deadline:
    def __init__(self, budget: float | None, end: float | None = None) -> None:
        if end is not None:
            self.end: float | None = end
        else:
            self.end = None if budget is None else time.monotonic() + budget

    @classmethod
    def for_request(cls, budget: float | None) -> _Deadline:
        """One deadline per request: every diff a write registers shares it
        (a request id is set by the integrations); outside a request, per
        call."""
        if budget is None:
            return cls(None)
        from . import request_context

        if request_context.get_request_id() is None:
            return cls(budget)
        end = request_context.get_delivery_deadline()
        if end is None:
            end = time.monotonic() + budget
            request_context.set_delivery_deadline(end)
        return cls(budget, end)

    def remaining(self) -> float | None:
        if self.end is None:
            return None
        return self.end - time.monotonic()

    def clip(self, timeout: tuple[float, float]) -> tuple[float, float] | None:
        """The timeouts a send may use, or None when none is left."""
        left = self.remaining()
        if left is None:
            return timeout
        if left <= 0:
            return None
        # ``requests`` applies the connect and the read timeout one after the
        # other: half of what is left each, so a send ends within it (a read
        # timeout restarts per chunk; callback answers are small).
        return (min(timeout[0], left / 2), min(timeout[1], left / 2))


def _ok(status: Any) -> bool:
    return isinstance(status, int) and 200 <= status <= 299


def send_sync(send: PreparedSend, deadline: _Deadline | None = None) -> int:
    """POST one callback with ``requests``; the status, 0 when the peer did
    not answer, -1 when the budget left no time to start it."""
    timeout = (deadline or _Deadline(None)).clip(send.timeout)
    if timeout is None:
        logger.warning(
            f"Callback seq={send.sequence} to {send.peer_id} not sent: the "
            "delivery budget ran out"
        )
        return -1
    try:
        response = requests.post(
            url=send.url, data=send.body, headers=send.headers, timeout=timeout
        )
    except (requests.RequestException, ConnectionError) as e:
        logger.warning(
            f"Callback seq={send.sequence} to {send.peer_id} failed - peer did "
            f"not respond: {e}"
        )
        return 0
    if response.status_code == 204:
        logger.info(f"Callback seq={send.sequence} delivered successfully (204)")
    else:
        body = getattr(response, "text", "")
        text = body[:200] if isinstance(body, str) and body else "no message"
        logger.warning(
            f"Callback seq={send.sequence} to {send.peer_id} returned "
            f"{response.status_code}: {text}"
        )
    return response.status_code


async def send_async(send: PreparedSend) -> int:
    """POST one callback with ``httpx`` (a task on a running loop). No
    delivery budget: the write has answered already, so there is no response
    for a budget to protect."""
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(send.timeout[1], connect=send.timeout[0])
        ) as client:
            response = await client.post(
                send.url, content=send.body, headers=send.headers
            )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(
            f"Callback seq={send.sequence} to {send.peer_id} failed - peer did "
            f"not respond: {e}"
        )
        return 0
    if not _ok(response.status_code):
        logger.warning(
            f"Callback seq={send.sequence} to {send.peer_id} returned "
            f"{response.status_code}"
        )
    return response.status_code


def _run_unit_sync(unit: Unit, deadline: _Deadline) -> bool:
    """A unit's sends in order; delivered when every one answered 2xx. The
    first that did not stops the unit: a full state is not sent after its
    clear failed."""
    delivered = True
    for send in unit.sends:
        try:
            status = send_sync(send, deadline)
        except Exception as e:  # folds DbError: one send's failure, logged
            logger.error(f"Callback to {send.peer_id} raised: {e}")
            status = 0
        if not _ok(status):
            delivered = False
            break
    unit.delivered = delivered
    if unit.on_result is not None:
        try:
            unit.on_result(delivered)
        except Exception as e:  # folds DbError: best effort, logged
            logger.error(f"Recording a callback's outcome failed: {e}")
    return delivered


async def _run_unit_async(unit: Unit, gate: asyncio.Semaphore) -> None:
    async with gate:
        delivered = True
        for send in unit.sends:
            if not _ok(await send_async(send)):
                delivered = False
                break
        unit.delivered = delivered
        if unit.on_result is not None:
            try:
                # A database write: off the loop, so it does not block it.
                await asyncio.to_thread(unit.on_result, delivered)
            except Exception as e:  # folds DbError: best effort, logged
                logger.error(f"Recording a callback's outcome failed: {e}")


def _task_done(task: asyncio.Task[Any]) -> None:
    _TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error(f"A callback task failed: {task.exception()}")


def deliver(units: list[Unit], config: Any, *, wait: bool) -> bool:
    """Deliver ``units``. ``wait`` (off the loop, or ``with_sync_callbacks``):
    return when every send has answered, timed out or been cut by the budget,
    and True. Otherwise, on a running loop, schedule the sends as kept tasks
    and return False (nothing is known yet); with no running loop, wait."""
    if not units:
        return True
    settings = settings_for(config)
    running: asyncio.AbstractEventLoop | None
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None and not wait:
        remote_gate = asyncio.Semaphore(settings.bound)
        own_gate = asyncio.Semaphore(1) if settings.serialize_own_host else remote_gate
        for unit in units:
            gate = own_gate if unit.own_host else remote_gate
            task = running.create_task(_run_unit_async(unit, gate))
            _TASKS.add(task)
            task.add_done_callback(_task_done)
        return False

    deadline = _Deadline.for_request(settings.budget)
    # Partitioned by the unit's flag, not by membership: units are
    # dataclasses, and two equal ones must not be taken for each other.
    own = [u for u in units if u.own_host and settings.serialize_own_host]
    remote = [u for u in units if not (u.own_host and settings.serialize_own_host)]
    if not remote or (len(remote) == 1 and not own):
        # Nothing to overlap with: on the calling thread, as before.
        for unit in remote:
            _run_unit_sync(unit, deadline)
        for unit in own:
            _run_unit_sync(unit, deadline)
        return True
    workers = min(settings.bound, len(remote))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="aw-callback"
    ) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, _run_unit_sync, unit, deadline)
            for unit in remote
        ]
        # The own-host sends, one at a time, alongside the pool.
        for unit in own:
            _run_unit_sync(unit, deadline)
        for future in futures:
            future.result()
    return True
