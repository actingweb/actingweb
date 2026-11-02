"""Two concurrent deliveries of one in-order callback run the handler once
(3.16, owner-decided plan D13), against the real store on either backend.

Each delivery runs in its own thread with its own event loop. A barrier holds
both after they read the state row and the sequence, so both see the same
version and the same next sequence before either writes; one claim wins, the
other is retried, reads the live claim and answers IN_PROGRESS (which the
callback handler turns into a 503, so the publisher keeps the diff).
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any

import pytest

from actingweb.actor import Actor
from actingweb.callback_processor import (
    CallbackProcessor,
    ProcessedCallback,
    ProcessResult,
)
from actingweb.interface.actor_interface import ActorInterface
from actingweb.subscription import Subscription
from tests._adoption_helpers import make_config

pytestmark = pytest.mark.xdist_group(name="callback_processor_cas")


def _subscriber() -> tuple[ActorInterface, str, str]:
    config = make_config()
    actor = Actor(config=config)
    assert actor.create(
        url="https://test.example.com/",
        creator=f"{uuid.uuid4().hex[:12]}@example.com",
        passphrase="pw",
    )
    peer_id, sub_id = uuid.uuid4().hex, uuid.uuid4().hex
    assert Subscription(
        actor_id=actor.id, peerid=peer_id, subid=sub_id, callback=True, config=config
    ).create(target="properties", granularity="high")
    return ActorInterface(actor), peer_id, sub_id


def test_two_concurrent_deliveries_run_the_handler_once() -> None:
    interface, peer_id, sub_id = _subscriber()
    barrier = threading.Barrier(2, timeout=10)
    runs: list[int] = []
    lock = threading.Lock()
    results: list[ProcessResult] = []
    errors: list[BaseException] = []

    def deliver() -> None:
        processor = CallbackProcessor(interface, max_retries=3, retry_backoff_base=0)
        real_last_seq = processor._get_last_seq  # pyright: ignore[reportPrivateUsage]
        first = {"done": False}

        def last_seq(*a: Any, **k: Any) -> int:
            value = real_last_seq(*a, **k)
            if not first["done"]:
                first["done"] = True
                barrier.wait()  # both have read the state and the sequence
            return value

        processor._get_last_seq = last_seq  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]

        async def handler(cb: ProcessedCallback) -> None:
            with lock:
                runs.append(cb.sequence)
            time.sleep(0.2)  # the loser retries while this runs

        try:
            results.append(
                asyncio.run(
                    processor.process_callback(
                        peer_id=peer_id,
                        subscription_id=sub_id,
                        sequence=1,
                        data={"value": "x"},
                        handler=handler,
                    )
                )
            )
        except BaseException as e:  # noqa: BLE001 - re-raised in the test thread
            errors.append(e)

    threads = [threading.Thread(target=deliver) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert runs == [1]
    assert sorted(r.value for r in results) == sorted(
        [ProcessResult.PROCESSED.value, ProcessResult.IN_PROGRESS.value]
    )
