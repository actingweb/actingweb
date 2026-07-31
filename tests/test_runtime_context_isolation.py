"""Concurrency isolation tests for :mod:`actingweb.runtime_context`.

Phase 4 of the MCP trust-cache plan (thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md)
moved RuntimeContext storage from a mutable attribute on the (frequently
cached and reused) actor object to a ``contextvars.ContextVar`` keyed by
actor id. These tests are the deterministic reproduction the plan calls
for: they exercise the exact failure shapes from the research document's R2
script (asyncio task interleaving and threaded WSGI-style dispatch) against
the real ``RuntimeContext`` API, plus the two edges the plan calls out by
name -- the ``hooks.py`` executor hop and actor-id keying -- so a future
regression on any of them fails a test instead of only being reproducible
by hand.

Pure Python -- no docker, no database.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from actingweb.interface.hooks import HookRegistry
from actingweb.runtime_context import RuntimeContext, clear_all_context


class SharedActor:
    """Stands in for the cached ActorInterface the MCP handler hands to
    every request for a hot actor -- the same object, requests apart."""

    def __init__(self, actor_id: str = "actor-1") -> None:
        self.id = actor_id


class FakeTrust:
    def __init__(self, peer: str) -> None:
        self.peerid = peer
        self.client_name = peer


@pytest.fixture(autouse=True)
def _reset_runtime_context():
    """Every test starts and ends with an empty context map.

    RuntimeContext storage is thread-local under a plain thread and
    task-local under asyncio, but pytest reuses the *same* thread across
    many test functions, so writes from one test are otherwise visible to
    the next test on that worker thread.
    """
    clear_all_context()
    yield
    clear_all_context()


def _authenticate(actor: object, client_id: str) -> None:
    """What authenticate_and_get_actor_cached does after trust resolution."""
    RuntimeContext(actor).set_mcp_context(
        client_id=client_id,
        trust_relationship=FakeTrust(f"peer-{client_id}"),
        peer_id=f"peer-{client_id}",
    )


def _read_peer(actor: object) -> str | None:
    """What a permission check / hook does."""
    ctx = RuntimeContext(actor).get_mcp_context()
    return ctx.peer_id if ctx else None


class TestAsyncioIsolation:
    """Deterministic asyncio isolation (research script R2, asyncio arm)."""

    @pytest.mark.asyncio
    async def test_interleaved_tasks_never_cross(self):
        """Request A authenticates, yields at an await, request B
        authenticates and reads in its own task while A is still
        suspended; when A resumes it must still read its own peer id --
        not the value B set while A was parked."""
        shared = SharedActor()
        gate = asyncio.Event()

        async def request(client_id: str, wait_before_read: bool) -> tuple[str, str | None]:
            _authenticate(shared, client_id)
            if wait_before_read:
                await gate.wait()  # suspend with A's context set
            else:
                gate.set()
            await asyncio.sleep(0)
            return client_id, _read_peer(shared)

        task_a = asyncio.create_task(request("A", True))
        await asyncio.sleep(0)  # let A run up to gate.wait()
        task_b = asyncio.create_task(request("B", False))
        results = dict(await asyncio.gather(task_a, task_b))

        assert results["A"] == "peer-A"
        assert results["B"] == "peer-B"

    @pytest.mark.asyncio
    async def test_async_hook_reads_own_context_after_await(self):
        """An async MCP hook that awaits mid-execution (the real suspension
        point at async_mcp.py's tool/prompt/resource dispatch) must observe
        its own request's identity on the other side of the await, even
        when a sibling task's request runs to completion first."""
        shared = SharedActor()

        async def hook_like_dispatch(client_id: str) -> str | None:
            _authenticate(shared, client_id)
            await asyncio.sleep(0)
            return _read_peer(shared)

        slow, fast = await asyncio.gather(
            hook_like_dispatch("slow"),
            hook_like_dispatch("fast"),
        )
        # Both tasks interleave at the same await point; each must still
        # observe its own authentication, not whichever ran last.
        assert slow == "peer-slow"
        assert fast == "peer-fast"


class TestThreadedIsolation:
    """Deterministic threaded isolation (research script R2, thread arm) --
    models Flask/WSGI worker-thread dispatch."""

    def test_worker_threads_never_cross(self):
        shared = SharedActor()
        barrier = threading.Barrier(2)
        out: dict[str, str | None] = {}

        def request(client_id: str) -> None:
            _authenticate(shared, client_id)
            barrier.wait()  # both threads have authenticated; now both read
            out[client_id] = _read_peer(shared)
            clear_all_context()  # simulate the Flask teardown_request fix

        t1 = threading.Thread(target=request, args=("A",))
        t2 = threading.Thread(target=request, args=("B",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert out == {"A": "peer-A", "B": "peer-B"}

    def test_reused_worker_thread_does_not_see_prior_request(self):
        """A thread that handles request A, is torn down (as Flask's
        teardown_request now does), and is then reused for request B must
        not see A's context -- the scenario the missing teardown_request
        would have missed."""
        shared = SharedActor()
        seen_in_b: list[str | None] = []

        def worker() -> None:
            _authenticate(shared, "A")
            assert _read_peer(shared) == "peer-A"
            clear_all_context()  # the fix: teardown_request-equivalent

            # Same thread, second "request", no re-authentication this time.
            seen_in_b.append(_read_peer(shared))

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert seen_in_b == [None]


class TestTwoActorObjectsInOneRequest:
    def test_context_keyed_by_actor_id_not_object(self):
        """Two distinct actor ids never share context, even when handled
        in the same request/task."""
        actor_x = SharedActor("actor-x")
        actor_y = SharedActor("actor-y")

        RuntimeContext(actor_x).set_mcp_context(
            client_id="client-x", trust_relationship=None, peer_id="peer-x"
        )

        assert RuntimeContext(actor_x).get_mcp_context() is not None
        assert RuntimeContext(actor_y).get_mcp_context() is None

    def test_wrapper_and_wrapped_share_context_by_id(self):
        """Two distinct Python objects with the same actor id observe the
        same context -- fixes the pre-ContextVar asymmetry where setting on
        an ActorInterface and reading via its wrapped CoreActor (or vice
        versa) silently missed, because storage lived on whichever object
        was actually passed."""

        class Wrapper:
            def __init__(self, core: object) -> None:
                self.id = core.id  # type: ignore[attr-defined]

        core = SharedActor("actor-shared")
        wrapper = Wrapper(core)

        RuntimeContext(core).set_mcp_context(
            client_id="c", trust_relationship=None, peer_id="peer-shared"
        )

        ctx_via_wrapper = RuntimeContext(wrapper).get_mcp_context()
        assert ctx_via_wrapper is not None
        assert ctx_via_wrapper.peer_id == "peer-shared"


class TestExecutorHopIsolation:
    """actingweb/interface/hooks.py:562 -- an async hook dispatched through
    HookRegistry._execute_hook_in_sync_context's thread-pool branch must
    see the calling thread's RuntimeContext. Exercised via the real public
    entry point (execute_lifecycle_hooks), not a hand-rolled copy, so a
    regression in the fix shape (e.g. reverting to a bare
    executor.submit(asyncio.run, ...)) fails this test."""

    @pytest.mark.asyncio
    async def test_async_lifecycle_hook_sees_callers_context(self):
        shared = SharedActor()
        _authenticate(shared, "hop-client")

        registry = HookRegistry()
        seen: list[str | None] = []

        async def async_hook(actor: object, **kwargs: object) -> None:
            seen.append(_read_peer(actor))

        registry.register_lifecycle_hook("actor_created", async_hook)

        # Calling the *sync* dispatch method from inside a running event
        # loop forces the executor-hop branch in
        # _execute_hook_in_sync_context (mirrors a sync call site reached
        # from async code).
        registry.execute_lifecycle_hooks("actor_created", shared)

        assert seen == ["peer-hop-client"]
