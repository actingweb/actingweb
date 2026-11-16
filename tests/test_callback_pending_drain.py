"""A callback that arrives while the previous one is being processed is
processed too, without waiting for later traffic (3.16).

Callback N+1 that meets N's live claim is queued. N's delivery read the queue
before it claimed, so nothing took N+1 until a later callback outlived the
gap timeout or a poll ran. Now the delivery that recorded N takes what was
queued behind it, and the delivery that queued N+1 looks once more after its
write (N may have finished in between).

Two processors on one subscriber, against the real store of the run's
backend. No timing: one delivery runs inside a hook of the other, at the
point the interleaving needs.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from actingweb.actor import Actor
from actingweb.callback_processor import (
    CallbackProcessor,
    ProcessedCallback,
    ProcessResult,
)
from actingweb.db.exceptions import DbError
from actingweb.interface.actor_interface import ActorInterface
from actingweb.subscription import Subscription
from tests._adoption_helpers import make_config

BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


class _Sub:
    """One subscriber-side subscription and as many deliveries as a test
    needs, each with its own processor (as each request has)."""

    def __init__(self) -> None:
        config = make_config(database=BACKEND)
        actor = Actor(config=config)
        assert actor.create(
            url="https://test.example.com/",
            creator=f"{uuid.uuid4().hex[:12]}@example.com",
            passphrase="pw",
        )
        self.interface = ActorInterface(actor)
        self.peer, self.sub = uuid.uuid4().hex, uuid.uuid4().hex
        assert Subscription(
            actor_id=actor.id,
            peerid=self.peer,
            subid=self.sub,
            callback=True,
            config=config,
        ).create(target="properties", granularity="high")
        self.ran: list[int] = []

    def processor(self) -> CallbackProcessor:
        return CallbackProcessor(self.interface, max_retries=3, retry_backoff_base=0)

    def record(self, cb: ProcessedCallback) -> None:
        self.ran.append(cb.sequence)

    def deliver(
        self,
        processor: CallbackProcessor,
        sequence: int,
        handler: Callable[[ProcessedCallback], None] | None = None,
    ) -> ProcessResult:
        return processor.process_callback_sync(
            peer_id=self.peer,
            subscription_id=self.sub,
            sequence=sequence,
            data={"v": sequence},
            handler=handler or self.record,
        )

    def sequence(self) -> int:
        return self.processor()._get_last_seq(self.peer, self.sub)  # noqa: SLF001

    def queued(self) -> list[int]:
        return [
            c["sequence"]
            for c in self.processor()._get_pending(self.peer, self.sub)  # noqa: SLF001
        ]


def _during_first(sub: _Sub, other: Callable[[], Any]) -> Callable[..., None]:
    """A handler that records, and runs ``other`` while callback 1 is being
    processed (its claim is live, its sequence not yet recorded)."""

    def handler(cb: ProcessedCallback) -> None:
        sub.record(cb)
        if cb.sequence == 1:
            other()

    return handler


def _before_queue_write(processor: CallbackProcessor, other: Callable[[], Any]) -> None:
    """Run ``other`` between the delivery's decision to queue and its write
    to the queue."""
    real = processor._add_pending  # noqa: SLF001

    def add(*args: Any, **kwargs: Any) -> bool:
        other()
        return real(*args, **kwargs)

    processor._add_pending = add  # type: ignore[method-assign]  # noqa: SLF001


@pytest.mark.parametrize("queued", ["before the sequence write", "after it"])
def test_a_callback_queued_behind_a_live_claim_is_processed_sync(queued: str) -> None:
    s = _Sub()
    a, b = s.processor(), s.processor()
    answers: dict[str, ProcessResult] = {}
    if queued == "before the sequence write":
        # B meets A's live claim, queues 2 and answers; A then records 1.
        handler = _during_first(s, lambda: answers.update(b=s.deliver(b, 2)))
        answers["a"] = s.deliver(a, 1, handler)
        assert answers["b"] == ProcessResult.PENDING
    else:
        # B has decided to queue 2 (it read sequence 0); A's whole delivery
        # of 1 runs before B's write, so A's look at the queue finds nothing.
        _before_queue_write(b, lambda: answers.update(a=s.deliver(a, 1)))
        answers["b"] = s.deliver(b, 2)
        assert answers["b"] == ProcessResult.PROCESSED
    assert answers["a"] == ProcessResult.PROCESSED
    assert s.ran == [1, 2]
    assert s.sequence() == 2
    assert s.queued() == []


@pytest.mark.parametrize("queued", ["before the sequence write", "after it"])
def test_a_callback_queued_behind_a_live_claim_is_processed_async(queued: str) -> None:
    s = _Sub()
    a, b = s.processor(), s.processor()
    answers: dict[str, ProcessResult] = {}

    async def record(cb: ProcessedCallback) -> None:
        s.record(cb)

    async def deliver(
        processor: CallbackProcessor, sequence: int, handler: Any = record
    ) -> ProcessResult:
        return await processor.process_callback(
            peer_id=s.peer,
            subscription_id=s.sub,
            sequence=sequence,
            data={"v": sequence},
            handler=handler,
        )

    async def run() -> None:
        if queued == "before the sequence write":

            async def handler(cb: ProcessedCallback) -> None:
                s.record(cb)
                if cb.sequence == 1:
                    answers["b"] = await deliver(b, 2)

            answers["a"] = await deliver(a, 1, handler)
            assert answers["b"] == ProcessResult.PENDING
        else:

            def other() -> None:
                # A's delivery on a loop of its own (the hook is not a
                # coroutine); joined before B's write, so the order is fixed.
                done = threading.Thread(
                    target=lambda: answers.update(a=asyncio.run(deliver(a, 1)))
                )
                done.start()
                done.join(timeout=30)

            _before_queue_write(b, other)
            answers["b"] = await deliver(b, 2)
            assert answers["b"] == ProcessResult.PROCESSED

    asyncio.run(run())
    assert answers["a"] == ProcessResult.PROCESSED
    assert s.ran == [1, 2]
    assert s.sequence() == 2
    assert s.queued() == []


def test_a_queue_write_during_a_prune_is_kept() -> None:
    """The queue row is read, changed and written: a write that lands between
    a prune's read and its write must survive the prune."""
    s = _Sub()
    a, b = s.processor(), s.processor()
    assert a._add_pending(s.peer, s.sub, {"sequence": 1, "data": {}})  # noqa: SLF001
    real = a._read_pending_row  # noqa: SLF001
    first = {"done": False}

    def read(*args: Any, **kwargs: Any) -> Any:
        row = real(*args, **kwargs)
        if not first["done"]:
            first["done"] = True
            assert b._add_pending(s.peer, s.sub, {"sequence": 2, "data": {}})  # noqa: SLF001
        return row

    a._read_pending_row = read  # type: ignore[method-assign]  # noqa: SLF001
    a._prune_pending(s.peer, s.sub, 1)  # noqa: SLF001
    assert s.queued() == [2]


def test_a_gap_in_the_queue_is_not_skipped() -> None:
    """3 arrives while 1 is processed and 2 never does: 3 stays queued."""
    s = _Sub()
    a, b = s.processor(), s.processor()
    answers: dict[str, ProcessResult] = {}
    handler = _during_first(s, lambda: answers.update(b=s.deliver(b, 3)))
    assert s.deliver(a, 1, handler) == ProcessResult.PROCESSED
    assert answers["b"] == ProcessResult.PENDING
    assert s.ran == [1]
    assert s.sequence() == 1
    assert s.queued() == [3]


def test_a_queued_callback_whose_handler_fails_leaves_the_first_answer() -> None:
    """An ordinary handler error is logged and the sequence moves on, as for
    a callback that was not queued."""
    s = _Sub()
    a, b = s.processor(), s.processor()

    def handler(cb: ProcessedCallback) -> None:
        s.record(cb)
        if cb.sequence == 1:
            s.deliver(b, 2)
        else:
            raise ValueError("the application's hook failed")

    assert s.deliver(a, 1, handler) == ProcessResult.PROCESSED
    assert s.ran == [1, 2]
    assert s.sequence() == 2
    assert s.queued() == []


def test_a_queued_callback_that_meets_a_store_fault_stays_queued() -> None:
    """The first callback was processed and is answered so; the queued one
    keeps its place and its claim is handed back."""
    s = _Sub()
    a, b = s.processor(), s.processor()

    def handler(cb: ProcessedCallback) -> None:
        s.record(cb)
        if cb.sequence == 1:
            s.deliver(b, 2)
        else:
            raise DbError("replica write", s.interface.id)

    assert s.deliver(a, 1, handler) == ProcessResult.PROCESSED
    assert s.ran == [1, 2]
    assert s.sequence() == 1
    assert s.queued() == [2]
    assert s.processor().precheck(s.peer, s.sub, 2) is None  # no live claim


def test_a_rebuild_a_queued_callback_calls_for_reaches_the_caller() -> None:
    s = _Sub()
    a, b = s.processor(), s.processor()

    def handler(cb: ProcessedCallback) -> None:
        s.record(cb)
        if cb.sequence == 1:
            s.deliver(b, 2)
        else:
            cb.out_of_step = {"list": "notes", "operation": "insert"}

    assert s.deliver(a, 1, handler) == ProcessResult.REBUILD
    assert s.ran == [1, 2]
    assert s.sequence() == 2
    assert s.processor().rebuild_state(s.peer, s.sub)["lists"] == ["notes"]


def test_a_delivery_takes_no_more_from_the_queue_than_its_bound() -> None:
    s = _Sub()
    a, b = s.processor(), s.processor()
    a.DRAIN_MAX_CALLBACKS = 2  # type: ignore[misc]

    def others() -> None:
        for sequence in (2, 3, 4, 5):
            assert s.deliver(b, sequence) == ProcessResult.PENDING

    assert s.deliver(a, 1, _during_first(s, others)) == ProcessResult.PROCESSED
    assert s.ran == [1, 2, 3]
    assert s.sequence() == 3
    assert s.queued() == [4, 5]
    # The next delivery, itself out of order, takes the rest and then itself.
    assert s.deliver(s.processor(), 6) == ProcessResult.PROCESSED
    assert s.ran == [1, 2, 3, 4, 5, 6]
    assert s.sequence() == 6
    assert s.queued() == []


def test_a_queued_callback_another_delivery_processed_is_not_run_again() -> None:
    """A read the queue (2 is there); before it claims, a redelivery of 2
    processes it. A's claim is on a fresh row and sequence, so 2 runs once."""
    s = _Sub()
    a, b, c = s.processor(), s.processor(), s.processor()
    recorded = {"done": False, "raced": False}
    real_write = a._update_last_seq  # noqa: SLF001
    real_read = a._get_pending  # noqa: SLF001

    def write(*args: Any, **kwargs: Any) -> bool:
        result = real_write(*args, **kwargs)
        recorded["done"] = True
        return result

    def read(*args: Any, **kwargs: Any) -> Any:
        pending = real_read(*args, **kwargs)
        if recorded["done"] and not recorded["raced"]:
            recorded["raced"] = True
            assert s.deliver(c, 2) == ProcessResult.PROCESSED
        return pending

    a._update_last_seq = write  # type: ignore[method-assign]  # noqa: SLF001
    a._get_pending = read  # type: ignore[method-assign]  # noqa: SLF001
    handler = _during_first(s, lambda: s.deliver(b, 2))
    assert s.deliver(a, 1, handler) == ProcessResult.PROCESSED
    assert recorded["raced"]
    assert s.ran == [1, 2]
    assert s.sequence() == 2
