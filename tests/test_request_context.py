"""Unit tests for request_context module."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from actingweb import request_context


class TestRequestIdGeneration:
    """Tests for request ID generation."""

    def test_generate_request_id(self) -> None:
        """Test that generated request IDs are valid UUIDs."""
        request_id = request_context.generate_request_id()

        # Should be a valid UUID4 format
        assert len(request_id) == 36
        assert request_id.count("-") == 4

    def test_generate_unique_request_ids(self) -> None:
        """Test that multiple calls generate unique IDs."""
        ids = [request_context.generate_request_id() for _ in range(100)]

        # All IDs should be unique
        assert len(set(ids)) == 100


class TestRequestIdContext:
    """Tests for request ID context management."""

    def test_set_and_get_request_id(self) -> None:
        """Test setting and getting request ID."""
        test_id = "550e8400-e29b-41d4-a716-446655440000"

        request_context.set_request_id(test_id)
        assert request_context.get_request_id() == test_id

        request_context.clear_request_context()

    def test_get_request_id_default(self) -> None:
        """Test that get_request_id returns None when not set."""
        request_context.clear_request_context()
        assert request_context.get_request_id() is None

    def test_get_short_request_id(self) -> None:
        """Test short request ID extraction."""
        test_id = "550e8400-e29b-41d4-a716-446655440000"

        request_context.set_request_id(test_id)
        short_id = request_context.get_short_request_id()

        # Should be last 8 chars without hyphens
        assert len(short_id) == 8
        assert short_id == "55440000"

        request_context.clear_request_context()

    def test_get_short_request_id_default(self) -> None:
        """Test that short request ID returns '-' when not set."""
        request_context.clear_request_context()
        assert request_context.get_short_request_id() == "-"


class TestActorIdContext:
    """Tests for actor ID context management."""

    def test_set_and_get_actor_id(self) -> None:
        """Test setting and getting actor ID."""
        request_context.set_actor_id("actor123")
        assert request_context.get_actor_id() == "actor123"

        request_context.clear_request_context()

    def test_get_actor_id_default(self) -> None:
        """Test that get_actor_id returns None when not set."""
        request_context.clear_request_context()
        assert request_context.get_actor_id() is None


class TestPeerIdContext:
    """Tests for peer ID context management."""

    def test_set_and_get_peer_id(self) -> None:
        """Test setting and getting peer ID."""
        request_context.set_peer_id("peer456")
        assert request_context.get_peer_id() == "peer456"

        request_context.clear_request_context()

    def test_get_peer_id_default(self) -> None:
        """Test that get_peer_id returns None when not set."""
        request_context.clear_request_context()
        assert request_context.get_peer_id() is None

    def test_get_short_peer_id_with_urn(self) -> None:
        """Test short peer ID extraction from URN format."""
        peer_id = "urn:actingweb:example.com:actor123"

        request_context.set_peer_id(peer_id)
        short_peer = request_context.get_short_peer_id()

        # Should extract last segment
        assert short_peer == "actor123"

        request_context.clear_request_context()

    def test_get_short_peer_id_simple(self) -> None:
        """Test short peer ID with simple ID (no colons)."""
        request_context.set_peer_id("simple_peer")
        assert request_context.get_short_peer_id() == "simple_peer"

        request_context.clear_request_context()

    def test_get_short_peer_id_default(self) -> None:
        """Test that short peer ID returns '-' when not set."""
        request_context.clear_request_context()
        assert request_context.get_short_peer_id() == "-"


class TestSetRequestContext:
    """Tests for set_request_context() function."""

    def test_set_all_context_values(self) -> None:
        """Test setting all context values at once."""
        test_id = "550e8400-e29b-41d4-a716-446655440000"

        returned_id = request_context.set_request_context(
            request_id=test_id, actor_id="actor123", peer_id="peer456"
        )

        assert returned_id == test_id
        assert request_context.get_request_id() == test_id
        assert request_context.get_actor_id() == "actor123"
        assert request_context.get_peer_id() == "peer456"

        request_context.clear_request_context()

    def test_set_request_context_generates_id(self) -> None:
        """Test that set_request_context generates ID when not provided."""
        returned_id = request_context.set_request_context(
            actor_id="actor123", generate_id=True
        )

        assert returned_id  # Should have generated an ID
        assert request_context.get_request_id() == returned_id
        assert len(returned_id) == 36  # Valid UUID format

        request_context.clear_request_context()

    def test_set_request_context_no_generate(self) -> None:
        """Test that set_request_context respects generate_id=False."""
        returned_id = request_context.set_request_context(
            actor_id="actor123", generate_id=False
        )

        assert returned_id == ""
        assert request_context.get_request_id() is None

        request_context.clear_request_context()


class TestClearRequestContext:
    """Tests for clear_request_context() function."""

    def test_clear_all_context(self) -> None:
        """Test that clear clears all context values."""
        request_context.set_request_context(
            request_id="test-id", actor_id="actor123", peer_id="peer456"
        )

        request_context.clear_request_context()

        assert request_context.get_request_id() is None
        assert request_context.get_actor_id() is None
        assert request_context.get_peer_id() is None


class TestGetContextDict:
    """Tests for get_context_dict() function."""

    def test_get_context_dict_with_values(self) -> None:
        """Test getting context as dictionary with values set."""
        test_id = "550e8400-e29b-41d4-a716-446655440000"

        request_context.set_request_context(
            request_id=test_id, actor_id="actor123", peer_id="peer456"
        )

        context = request_context.get_context_dict()

        assert context == {
            "request_id": test_id,
            "actor_id": "actor123",
            "peer_id": "peer456",
        }

        request_context.clear_request_context()

    def test_get_context_dict_empty(self) -> None:
        """Test getting context as dictionary with no values set."""
        request_context.clear_request_context()

        context = request_context.get_context_dict()

        assert context == {
            "request_id": None,
            "actor_id": None,
            "peer_id": None,
        }


class TestFormatContextCompact:
    """Tests for format_context_compact() function."""

    def test_format_with_all_values(self) -> None:
        """Test formatting with all context values set."""
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="urn:actingweb:example.com:peer456",
        )

        formatted = request_context.format_context_compact()

        # Should be [short_req:actor:short_peer]
        assert formatted == "[55440000:actor123:peer456]"

        request_context.clear_request_context()

    def test_format_with_no_values(self) -> None:
        """Test formatting with no context values set."""
        request_context.clear_request_context()

        formatted = request_context.format_context_compact()

        assert formatted == "[-:-:-]"

    def test_format_with_partial_values(self) -> None:
        """Test formatting with only some context values set."""
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000", actor_id="actor123"
        )

        formatted = request_context.format_context_compact()

        assert formatted == "[55440000:actor123:-]"

        request_context.clear_request_context()


class TestContextIsolation:
    """Tests for context isolation between threads and async tasks."""

    def test_thread_isolation(self) -> None:
        """Test that context is isolated between threads."""

        def set_and_check_context(actor_id: str) -> str | None:
            request_context.set_actor_id(actor_id)
            # Small delay to ensure threads overlap
            import time

            time.sleep(0.01)
            return request_context.get_actor_id()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(set_and_check_context, f"actor{i}") for i in range(3)
            ]
            results = [f.result() for f in futures]

        # Each thread should see its own actor_id
        assert "actor0" in results
        assert "actor1" in results
        assert "actor2" in results

    @pytest.mark.asyncio
    async def test_async_isolation(self) -> None:
        """Test that context is isolated between async tasks."""

        async def set_and_check_context(actor_id: str) -> str | None:
            request_context.set_actor_id(actor_id)
            # Small delay to ensure tasks overlap
            await asyncio.sleep(0.01)
            return request_context.get_actor_id()

        # Run multiple tasks concurrently
        results = await asyncio.gather(
            set_and_check_context("actor0"),
            set_and_check_context("actor1"),
            set_and_check_context("actor2"),
        )

        # Each task should see its own actor_id
        assert results == ["actor0", "actor1", "actor2"]

    @pytest.mark.asyncio
    async def test_async_context_propagation(self) -> None:
        """Test that context propagates through async/await boundaries."""

        async def inner_function() -> str | None:
            # Should see context set in outer function
            await asyncio.sleep(0.001)
            return request_context.get_actor_id()

        async def outer_function(actor_id: str) -> str | None:
            request_context.set_actor_id(actor_id)
            return await inner_function()

        result = await outer_function("actor123")

        assert result == "actor123"

        request_context.clear_request_context()


class TestPerformance:
    """Performance tests to ensure minimal overhead."""

    def test_get_performance(self) -> None:
        """Test that getting context is fast."""
        import time

        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="peer456",
        )

        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            request_context.get_actor_id()

        elapsed = time.perf_counter() - start
        per_call = (elapsed / iterations) * 1_000_000  # Convert to microseconds

        # Should be under 5 microseconds per call (relaxed for CI variability)
        assert per_call < 5.0, (
            f"get_actor_id() took {per_call:.2f}µs per call (expected <5µs)"
        )

        request_context.clear_request_context()

    def test_set_performance(self) -> None:
        """Test that setting context is fast."""
        import time

        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            request_context.set_request_context(
                request_id="550e8400-e29b-41d4-a716-446655440000",
                actor_id="actor123",
                generate_id=False,
            )

        elapsed = time.perf_counter() - start
        per_call = (elapsed / iterations) * 1_000_000  # Convert to microseconds

        # Should be under 10 microseconds per call (relaxed for CI variability)
        assert per_call < 10.0, (
            f"set_request_context() took {per_call:.2f}µs per call (expected <10µs)"
        )

        request_context.clear_request_context()

    def test_format_performance(self) -> None:
        """Test that formatting context is fast."""
        import time

        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="urn:actingweb:example.com:peer456",
        )

        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            request_context.format_context_compact()

        elapsed = time.perf_counter() - start
        per_call = (elapsed / iterations) * 1_000_000  # Convert to microseconds

        # Should be under 15 microseconds per call (relaxed for CI variability)
        assert per_call < 15.0, (
            f"format_context_compact() took {per_call:.2f}µs per call (expected <15µs)"
        )

        request_context.clear_request_context()
