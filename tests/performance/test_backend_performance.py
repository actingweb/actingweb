"""
Performance benchmarks comparing DynamoDB and PostgreSQL backends.

These tests measure and compare performance characteristics of both backends
to help with capacity planning and optimization decisions.

Run with:
    # Test PostgreSQL performance
    DATABASE_BACKEND=postgresql pytest tests/performance/ -v

    # Test DynamoDB performance
    DATABASE_BACKEND=dynamodb pytest tests/performance/ -v

    # Compare both (run twice with different backends)
    DATABASE_BACKEND=postgresql pytest tests/performance/ --benchmark-json=pg_results.json
    DATABASE_BACKEND=dynamodb pytest tests/performance/ --benchmark-json=db_results.json
"""

import os
import time
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(scope="module")
def backend_name() -> str:
    """Get current backend name from environment."""
    return os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def sample_actor_id() -> Iterator[str]:
    """Create a sample actor for testing."""
    from actingweb.config import Config

    config = Config()
    actor_id = f"perf_test_actor_{int(time.time() * 1000)}"

    # Create actor
    db_actor = config.DbActor.DbActor()  # type: ignore[misc]
    db_actor.create(actor_id=actor_id, creator="perf@test.com", passphrase="test123")

    yield actor_id

    # Cleanup
    db_actor.get(actor_id=actor_id)
    if db_actor.handle:
        db_actor.delete()


@pytest.mark.benchmark
class TestActorPerformance:
    """Benchmark actor operations."""

    def test_actor_create_performance(self, benchmark: Any, backend_name: str) -> None:
        """Measure actor creation time."""
        from actingweb.config import Config

        config = Config()

        def create_actor() -> bool:
            actor_id = f"perf_create_{int(time.time() * 1000000)}"
            db_actor = config.DbActor.DbActor()  # type: ignore[misc]
            result = db_actor.create(
                actor_id=actor_id, creator="perf@test.com", passphrase="test123"
            )

            # Cleanup
            db_actor.get(actor_id=actor_id)
            if db_actor.handle:
                db_actor.delete()

            return result

        result = benchmark(create_actor)
        assert result is True

        # Print summary (only in non-parallel mode)
        if benchmark.stats:
            print(
                f"\n{backend_name} actor create: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_actor_read_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure actor read time."""
        from actingweb.config import Config

        config = Config()

        def read_actor() -> dict[str, Any] | None:
            db_actor = config.DbActor.DbActor()  # type: ignore[misc]
            return db_actor.get(actor_id=sample_actor_id)

        result = benchmark(read_actor)
        assert result is not None
        assert result["id"] == sample_actor_id

        if benchmark.stats:
            print(
                f"\n{backend_name} actor read: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_actor_update_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure actor update time."""
        from actingweb.config import Config

        config = Config()

        def update_actor() -> bool:
            db_actor = config.DbActor.DbActor()  # type: ignore[misc]
            db_actor.get(actor_id=sample_actor_id)
            return db_actor.modify(creator="updated@test.com")

        result = benchmark(update_actor)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} actor update: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_actor_delete_performance(self, benchmark: Any, backend_name: str) -> None:
        """Measure actor deletion time."""
        from actingweb.config import Config

        config = Config()

        def delete_actor() -> bool:
            # Create actor
            actor_id = f"perf_delete_{int(time.time() * 1000000)}"
            db_actor = config.DbActor.DbActor()  # type: ignore[misc]
            db_actor.create(
                actor_id=actor_id, creator="perf@test.com", passphrase="test123"
            )

            # Delete actor
            db_actor.get(actor_id=actor_id)
            return db_actor.delete()

        result = benchmark(delete_actor)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} actor delete: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )


@pytest.mark.benchmark
class TestPropertyPerformance:
    """Benchmark property operations."""

    def test_property_write_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure property write time."""
        from actingweb.config import Config

        config = Config()

        prop_counter = [0]

        def write_property() -> bool:
            prop_name = f"perf_prop_{prop_counter[0]}"
            prop_counter[0] += 1

            db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
            return db_property.set(
                actor_id=sample_actor_id, name=prop_name, value="test_value"
            )

        result = benchmark(write_property)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} property write: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_property_read_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure property read time."""
        from actingweb.config import Config

        config = Config()

        # Create test property
        prop_name = f"perf_read_prop_{int(time.time())}"
        db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
        db_property.set(actor_id=sample_actor_id, name=prop_name, value="test_value")

        def read_property() -> str | None:
            db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
            return db_property.get(actor_id=sample_actor_id, name=prop_name)

        result = benchmark(read_property)
        assert result == "test_value"

        if benchmark.stats:
            print(
                f"\n{backend_name} property read: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_property_list_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure property list time."""
        from actingweb.config import Config

        config = Config()

        # Create 10 test properties
        for i in range(10):
            db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
            db_property.set(
                actor_id=sample_actor_id, name=f"list_prop_{i}", value=f"value_{i}"
            )

        def list_properties() -> dict[str, Any]:
            db_property_list = config.DbProperty.DbPropertyList()  # type: ignore[misc]
            result = db_property_list.fetch(actor_id=sample_actor_id)
            return result if result else {}

        result = benchmark(list_properties)
        assert len(result) >= 10

        if benchmark.stats:
            print(
                f"\n{backend_name} property list: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )


@pytest.mark.benchmark
class TestTrustPerformance:
    """Benchmark trust operations."""

    def test_trust_create_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure trust creation time."""
        from actingweb.config import Config

        config = Config()
        trust_counter = [0]

        def create_trust() -> bool:
            peerid = f"peer_{trust_counter[0]}"
            trust_counter[0] += 1

            db_trust = config.DbTrust.DbTrust()  # type: ignore[misc]
            return db_trust.create(
                actor_id=sample_actor_id,
                peerid=peerid,
                baseuri="https://peer.example.com",
                peer_type="inbox",
                relationship="friend",
                secret=f"secret_{trust_counter[0]}",
            )

        result = benchmark(create_trust)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} trust create: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_trust_read_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure trust read time."""
        from actingweb.config import Config

        config = Config()

        # Create test trust
        peerid = f"peer_read_{int(time.time())}"
        db_trust = config.DbTrust.DbTrust()  # type: ignore[misc]
        db_trust.create(
            actor_id=sample_actor_id,
            peerid=peerid,
            baseuri="https://peer.example.com",
            peer_type="inbox",
            relationship="friend",
            secret=f"secret_{peerid}",
        )

        def read_trust() -> dict[str, Any] | None:
            db_trust = config.DbTrust.DbTrust()  # type: ignore[misc]
            return db_trust.get(actor_id=sample_actor_id, peerid=peerid)

        result = benchmark(read_trust)
        assert result is not None
        assert result["peerid"] == peerid

        if benchmark.stats:
            print(
                f"\n{backend_name} trust read: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_trust_list_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure trust list time."""
        from actingweb.config import Config

        config = Config()

        # Create 5 test trusts
        for i in range(5):
            db_trust = config.DbTrust.DbTrust()  # type: ignore[misc]
            db_trust.create(
                actor_id=sample_actor_id,
                peerid=f"list_peer_{i}",
                baseuri=f"https://peer{i}.example.com",
                peer_type="inbox",
                relationship="friend",
                secret=f"secret_list_{i}",
            )

        def list_trusts() -> list[dict[str, Any]]:
            db_trust_list = config.DbTrust.DbTrustList()  # type: ignore[misc]
            return db_trust_list.fetch(actor_id=sample_actor_id)

        result = benchmark(list_trusts)
        assert len(result) >= 5

        if benchmark.stats:
            print(
                f"\n{backend_name} trust list: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )


@pytest.mark.benchmark
class TestSubscriptionPerformance:
    """Benchmark subscription operations."""

    def test_subscription_create_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure subscription creation time."""
        from actingweb.config import Config

        config = Config()
        sub_counter = [0]

        def create_subscription() -> bool:
            peerid = f"subpeer_{sub_counter[0]}"
            subid = f"sub_{sub_counter[0]}"
            sub_counter[0] += 1

            db_subscription = config.DbSubscription.DbSubscription()  # type: ignore[misc]
            return db_subscription.create(
                actor_id=sample_actor_id,
                peerid=peerid,
                subid=subid,
                granularity="default",
                callback="https://callback.example.com",
            )

        result = benchmark(create_subscription)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} subscription create: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_subscription_read_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure subscription read time."""
        from actingweb.config import Config

        config = Config()

        # Create test subscription
        peerid = f"subpeer_read_{int(time.time())}"
        subid = f"sub_read_{int(time.time())}"
        db_subscription = config.DbSubscription.DbSubscription()  # type: ignore[misc]
        db_subscription.create(
            actor_id=sample_actor_id,
            peerid=peerid,
            subid=subid,
            granularity="default",
            callback="https://callback.example.com",
        )

        def read_subscription() -> dict[str, Any] | None:
            db_subscription = config.DbSubscription.DbSubscription()  # type: ignore[misc]
            return db_subscription.get(
                actor_id=sample_actor_id, peerid=peerid, subid=subid
            )

        result = benchmark(read_subscription)
        assert result is not None
        assert result["subscriptionid"] == subid

        if benchmark.stats:
            print(
                f"\n{backend_name} subscription read: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )


@pytest.mark.benchmark
class TestAttributePerformance:
    """Benchmark attribute operations (internal storage)."""

    def test_attribute_write_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure attribute write time."""
        from actingweb.config import Config

        config = Config()
        attr_counter = [0]

        def write_attribute() -> bool:
            attr_name = f"attr_{attr_counter[0]}"
            attr_counter[0] += 1

            return config.DbAttribute.DbAttribute.set_attr(  # type: ignore[misc]
                actor_id=sample_actor_id,
                bucket="test_bucket",
                name=attr_name,
                data={"key": "value", "number": 123},
            )

        result = benchmark(write_attribute)
        assert result is True

        if benchmark.stats:
            print(
                f"\n{backend_name} attribute write: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )

    def test_attribute_read_performance(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure attribute read time."""
        from actingweb.config import Config

        config = Config()

        # Create test attribute
        attr_name = f"attr_read_{int(time.time())}"
        config.DbAttribute.DbAttribute.set_attr(  # type: ignore[misc]
            actor_id=sample_actor_id,
            bucket="test_bucket",
            name=attr_name,
            data={"key": "value", "number": 123},
        )

        def read_attribute() -> dict[str, Any] | None:
            return config.DbAttribute.DbAttribute.get_attr(  # type: ignore[misc]
                actor_id=sample_actor_id, bucket="test_bucket", name=attr_name
            )

        result = benchmark(read_attribute)
        assert result is not None
        assert result["data"]["key"] == "value"

        if benchmark.stats:
            print(
                f"\n{backend_name} attribute read: {benchmark.stats.stats.mean * 1000:.2f}ms avg"
            )


@pytest.mark.benchmark
class TestBulkOperations:
    """Benchmark bulk operations."""

    def test_bulk_property_write(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure bulk property writes (100 properties)."""
        from actingweb.config import Config

        config = Config()

        def bulk_write_properties() -> int:
            count = 0
            for i in range(100):
                db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
                if db_property.set(
                    actor_id=sample_actor_id, name=f"bulk_{i}", value=f"value_{i}"
                ):
                    count += 1
            return count

        result = benchmark(bulk_write_properties)
        assert result == 100

        if benchmark.stats:
            total_time = benchmark.stats.stats.mean
            per_write = total_time / 100
            print(
                f"\n{backend_name} bulk write (100 props): {total_time * 1000:.2f}ms total, {per_write * 1000:.2f}ms per write"
            )

    def test_bulk_property_read(
        self, benchmark: Any, backend_name: str, sample_actor_id: str
    ) -> None:
        """Measure bulk property reads (100 properties)."""
        from actingweb.config import Config

        config = Config()

        # Create test properties
        for i in range(100):
            db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
            db_property.set(
                actor_id=sample_actor_id, name=f"bulk_read_{i}", value=f"value_{i}"
            )

        def bulk_read_properties() -> int:
            count = 0
            for i in range(100):
                db_property = config.DbProperty.DbProperty()  # type: ignore[misc]
                value = db_property.get(actor_id=sample_actor_id, name=f"bulk_read_{i}")
                if value:
                    count += 1
            return count

        result = benchmark(bulk_read_properties)
        assert result == 100

        if benchmark.stats:
            total_time = benchmark.stats.stats.mean
            per_read = total_time / 100
            print(
                f"\n{backend_name} bulk read (100 props): {total_time * 1000:.2f}ms total, {per_read * 1000:.2f}ms per read"
            )


# Performance comparison summary
@pytest.mark.benchmark
def test_performance_summary(backend_name: str) -> None:
    """
    Print performance summary for the current backend.

    To compare backends:
        1. Run with DATABASE_BACKEND=postgresql
        2. Run with DATABASE_BACKEND=dynamodb
        3. Compare output
    """
    print(f"\n{'=' * 60}")
    print(f"Performance benchmarks for {backend_name} backend")
    print(f"{'=' * 60}")
    print("\nRun pytest with -v flag to see detailed timing for each test")
    print("\nFor JSON output with statistics:")
    print(
        f"  DATABASE_BACKEND={backend_name} pytest tests/performance/ --benchmark-json={backend_name}_results.json"
    )
    print("\nFor side-by-side comparison:")
    print("  poetry add pytest-benchmark")
    print("  pytest tests/performance/ --benchmark-compare")
    print(f"{'=' * 60}\n")
