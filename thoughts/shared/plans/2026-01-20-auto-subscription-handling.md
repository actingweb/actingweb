# Automatic Subscription Handling Implementation Plan

## Overview

Implement automatic subscription processing support in the actingweb library, enabling applications to receive and process subscription callbacks with sequencing, deduplication, automatic storage, and cleanup. This reduces ~500+ lines of boilerplate callback handling code to ~30 lines of application-specific logic.

**Branch**: `feature/auto_subscription_handling`

**Research Document**: `thoughts/shared/research/2026-01-18-library-extraction-candidates-from-actingweb-mcp.md`

## Current State Analysis

### What Exists Now

| Component | Location | Current State |
|-----------|----------|---------------|
| Callback handler | `actingweb/handlers/callbacks.py:114` | Basic callback routing via hooks |
| Hook system | `actingweb/interface/hooks.py:304` | `HookRegistry` with `@callback_hook("subscription")` |
| Trust model (DynamoDB) | `actingweb/db/dynamodb/trust.py:63` | 18 fields, no capability tracking |
| Trust model (PostgreSQL) | `actingweb/db/postgresql/schema.py:78` | Same fields as DynamoDB |
| AttributeListStore | `actingweb/attribute_list_store.py:16` | List storage in buckets |
| ActingWebApp | `actingweb/interface/app.py:18` | Fluent API with `with_*` methods |

### What's Missing

1. **Peer Capability Discovery** - No way to query/cache what features a peer supports
2. **Callback Sequencing** - Apps must implement their own sequence tracking
3. **Remote Peer Storage** - No standard pattern for storing peer data
4. **Automatic List Operations** - Apps must manually apply list diffs
5. **Fan-out Optimization** - Sequential callback delivery, no circuit breakers
6. **Integration API** - No `.with_subscription_processing()` convenience method

## Desired End State

After implementation, applications can enable full subscription support with minimal code:

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_subscription_processing(
        auto_sequence=True,         # Enable CallbackProcessor
        auto_storage=True,          # Enable RemotePeerStore with list operations
        auto_cleanup=True,          # Clean up when trust deleted
        gap_timeout_seconds=5.0,    # Time before triggering resync
        max_pending=100             # Back-pressure limit
    )
)

@app.subscription_data_hook("properties")
def on_property_change(
    actor: ActorInterface,
    peer_id: str,
    target: str,
    data: dict,
    sequence: int,
    callback_type: str  # "diff" or "resync"
) -> None:
    """Called with already-sequenced, deduplicated, stored data."""
    # App-specific logic only - library handled everything else
    logger.info(f"Received {callback_type} from {peer_id}")
```

### Verification Criteria

1. **Unit Tests**: All new components have >90% test coverage
2. **Integration Tests**: Multi-actor subscription flow works end-to-end
3. **Type Checking**: `poetry run pyright actingweb tests` passes with 0 errors
4. **Linting**: `poetry run ruff check actingweb tests` passes
5. **All Tests**: `make test-all-parallel` passes (900+ tests)

## What We're NOT Doing

1. **Breaking changes to existing APIs** - All new functionality is additive
2. **Mandatory migration** - Existing apps using raw `@callback_hook("subscription")` continue to work
3. **External message queues** - Storage uses existing attribute system, not Redis/SQS
4. **Automatic subscription creation** - Apps still explicitly subscribe via existing APIs
5. **Protocol spec changes** - Spec v1.4 changes are already complete

---

## Implementation Status Summary

**Last Updated**: 2026-01-20

| Phase | Component | Status | Unit Tests | Integration Tests |
|-------|-----------|--------|------------|-------------------|
| 0 | Peer Capability Discovery | COMPLETE | 28 tests | Deferred |
| 1 | Subscription Suspension & Resync | COMPLETE | Tests in suspension module | Deferred |
| 2 | CallbackProcessor | COMPLETE | 20 tests | Deferred |
| 3 | RemotePeerStore | COMPLETE | 34 tests | Deferred |
| 4 | FanOutManager | COMPLETE | 32 tests | Deferred |
| 5 | Integration Layer | COMPLETE | 27 tests | Deferred |

**Total New Unit Tests**: 113 tests (all passing)

### Files Created

| File | Description |
|------|-------------|
| `actingweb/peer_capabilities.py` | Query/cache peer ActingWeb capabilities |
| `actingweb/callback_processor.py` | Sequencing, deduplication, resync handling |
| `actingweb/remote_storage.py` | RemotePeerStore for peer data with list operations |
| `actingweb/fanout.py` | FanOutManager with circuit breakers |
| `actingweb/subscription_config.py` | SubscriptionProcessingConfig dataclass |
| `actingweb/db/dynamodb/subscription_suspension.py` | DynamoDB suspension storage |
| `actingweb/db/postgresql/subscription_suspension.py` | PostgreSQL suspension storage |
| `tests/test_peer_capabilities.py` | Peer capabilities unit tests |
| `tests/test_callback_processor.py` | CallbackProcessor unit tests |
| `tests/test_remote_storage.py` | RemotePeerStore unit tests |
| `tests/test_fanout.py` | FanOutManager unit tests |
| `tests/test_subscription_processing.py` | Integration layer unit tests |

### Files Modified

| File | Changes |
|------|---------|
| `actingweb/interface/app.py` | Added `.with_subscription_processing()` and `@subscription_data_hook` |
| `actingweb/interface/__init__.py` | Added exports for new components |
| `actingweb/db/dynamodb/trust.py` | Added capability fields (`aw_supported`, `aw_version`, `capabilities_fetched_at`) |
| `actingweb/db/postgresql/trust.py` | Added capability fields |
| `actingweb/db/__init__.py` | Added suspension DB factory function |
| `actingweb/callback_processor.py` | New - Callback sequencing, deduplication, resync handling |
| `actingweb/remote_storage.py` | New - Remote peer data storage with list operations |
| `actingweb/fanout.py` | New - Fan-out delivery manager with circuit breakers |
| `actingweb/peer_capabilities.py` | New - Peer capability discovery API |
| `actingweb/subscription_config.py` | New - Configuration dataclass |
| `docs/guides/subscriptions.rst` | Expanded documentation for subscription processing |
| `docs/contributing/testing.rst` | Added parallel test isolation patterns |
| `Makefile` | Changed `--dist loadscope` to `--dist loadgroup` |
| `tests/test_callback_processor.py` | New unit tests + xdist_group marker |
| `tests/test_remote_storage.py` | New unit tests + xdist_group marker |
| `tests/test_fanout.py` | New unit tests + xdist_group marker |
| `tests/test_peer_capabilities.py` | New unit tests |
| `tests/test_subscription_processing.py` | New unit tests |
| `tests/integration/test_devtest.py` | Added xdist_group marker |
| `tests/integration/test_spa_api.py` | Added xdist_group markers |
| `tests/integration/test_www_templates.py` | Added xdist_group markers |
| `tests/integration/test_actor_root_redirect.py` | Added xdist_group marker |
| `tests/integration/test_peer_capabilities_integration.py` | Fixed auth bug (creator vs actor_id) |
| `tests/integration/test_oauth2_security.py` | Added xdist_group markers |

### Remaining Work

1. **Integration Tests**: The plan includes extensive integration tests for multi-actor subscription flows. These have been deferred pending a broader integration test infrastructure review.
2. **End-to-End Testing**: Real-world testing with actual DynamoDB/PostgreSQL backends would validate the full flow.

### Completed Work

1. **Documentation**: User-facing documentation added to `docs/guides/subscriptions.rst` with comprehensive coverage of:
   - Quick start guide for `.with_subscription_processing()`
   - Configuration options reference
   - `@subscription_data_hook` decorator usage
   - Callback types (diff vs resync)
   - Peer capability discovery API
   - Remote peer storage API
   - List operations
   - Subscription suspension
   - Fan-out manager with circuit breakers
   - Component-level usage examples
   - Migration guide from raw hooks

2. **Quality Gates**: All pyright errors and warnings fixed (0 errors, 0 warnings)

3. **Unit Tests**: 145+ tests passing for new subscription processing components

4. **Parallel Test Isolation**: Fixed parallel test execution issues:
   - Added `pytestmark = pytest.mark.xdist_group(name="attribute_patching")` to `test_callback_processor.py` and `test_remote_storage.py` (both patch `actingweb.attribute.Attributes`)
   - Added `pytestmark = pytest.mark.xdist_group(name="fanout_tests")` to `test_fanout.py`
   - Changed Makefile from `--dist loadscope` to `--dist loadgroup` to respect xdist_group markers
   - Added xdist_group markers to integration tests missing them:
     - `test_devtest.py` - `devtest_TestDevTestEndpoints`
     - `test_spa_api.py` - 4 test classes
     - `test_www_templates.py` - 4 test classes
     - `test_actor_root_redirect.py` - `actor_root_redirect_TestActorRootContentNegotiation`
     - `test_oauth2_security.py` - 2 test classes
   - Fixed auth bug in `test_peer_capabilities_integration.py` (was using actor_id instead of creator email)

5. **Testing Documentation**: Added "Parallel Test Isolation Patterns" section to `docs/contributing/testing.rst`:
   - xdist_group marker usage patterns
   - Module patching guidance
   - Distribution mode comparison table

6. **Test Results**: **All tests pass** - 1378 passed, 14 skipped, 0 failures

---

## Phase 0: Peer Capability Discovery

### Overview
Extend the trust model to track peer capabilities (`aw_supported`, `aw_version`) and provide a query API. This is a prerequisite for using optional protocol features like batch subscriptions and compression.

### Changes Required

#### 1. DynamoDB Trust Model
**File**: `actingweb/db/dynamodb/trust.py`

Add three new attributes to the `Trust` model:

```python
# After line 107 (oauth_client_id), add:
    # Peer capability tracking
    aw_supported = UnicodeAttribute(null=True)  # Comma-separated option tags
    aw_version = UnicodeAttribute(null=True)    # Protocol version (e.g., "1.4")
    capabilities_fetched_at = UTCDateTimeAttribute(null=True)
```

Update `DbTrust.get()` method (around line 142) to include these fields:

```python
        # Add peer capability fields if they exist
        if hasattr(t, "aw_supported") and t.aw_supported:
            result["aw_supported"] = t.aw_supported
        if hasattr(t, "aw_version") and t.aw_version:
            result["aw_version"] = t.aw_version
        if hasattr(t, "capabilities_fetched_at") and t.capabilities_fetched_at:
            result["capabilities_fetched_at"] = ensure_timezone_aware_iso(
                t.capabilities_fetched_at
            )
```

Update `DbTrust.modify()` signature and body to handle these fields.

Update `DbTrust.create()` signature and body to handle these fields.

Update `DbTrustList.fetch()` to include these fields in the result dict.

#### 2. PostgreSQL Schema
**File**: `actingweb/db/postgresql/schema.py`

Add columns to the `Trust` class (after line 113):

```python
    # Peer capability tracking
    aw_supported = Column(Text)  # Comma-separated option tags
    aw_version = Column(String(50))  # Protocol version
    capabilities_fetched_at = Column(DateTime)
```

#### 3. PostgreSQL Migration
**File**: `actingweb/db/postgresql/migrations/versions/XXXX_add_peer_capabilities.py` (new file)

```python
"""Add peer capability tracking fields to trusts table.

Revision ID: [auto-generated]
Revises: 70d60420526
Create Date: 2026-01-20
"""
from alembic import op
import sqlalchemy as sa

revision = '[auto-generated]'
down_revision = '70d60420526'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trusts', sa.Column('aw_supported', sa.Text(), nullable=True))
    op.add_column('trusts', sa.Column('aw_version', sa.String(50), nullable=True))
    op.add_column('trusts', sa.Column('capabilities_fetched_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('trusts', 'capabilities_fetched_at')
    op.drop_column('trusts', 'aw_version')
    op.drop_column('trusts', 'aw_supported')
```

#### 4. PostgreSQL Trust Operations
**File**: `actingweb/db/postgresql/trust.py`

Update `DbTrust` class methods to handle the new fields (similar pattern to DynamoDB).

#### 5. PeerCapabilities Class
**File**: `actingweb/peer_capabilities.py` (new file)

```python
"""
Peer capability discovery and caching.

Provides an API to query what ActingWeb protocol features a peer supports.
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Cache TTL for capabilities (24 hours)
CAPABILITIES_TTL_HOURS = 24


class PeerCapabilities:
    """Query and cache peer's supported ActingWeb options.

    Usage:
        caps = PeerCapabilities(actor, peer_id)
        if caps.supports_batch_subscriptions():
            # Use batch endpoint
        else:
            # Fall back to individual requests
    """

    def __init__(self, actor: "ActorInterface", peer_id: str) -> None:
        self._actor = actor
        self._peer_id = peer_id
        self._trust: dict[str, Any] | None = None
        self._supported: set[str] = set()
        self._loaded = False

    def _load_trust(self) -> None:
        """Load trust data and parse supported options."""
        if self._loaded:
            return

        self._trust = self._actor.trust.get_trust(self._peer_id)
        if self._trust:
            aw_supported = self._trust.get("aw_supported") or ""
            self._supported = set(
                opt.strip() for opt in aw_supported.split(",") if opt.strip()
            )
        self._loaded = True

    def _is_cache_valid(self) -> bool:
        """Check if cached capabilities are still valid."""
        self._load_trust()
        if not self._trust:
            return False

        fetched_at = self._trust.get("capabilities_fetched_at")
        if not fetched_at:
            return False

        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))

        ttl = timedelta(hours=CAPABILITIES_TTL_HOURS)
        return datetime.utcnow() - fetched_at.replace(tzinfo=None) < ttl

    def supports(self, option: str) -> bool:
        """Check if peer supports a specific option tag.

        Args:
            option: Option tag (e.g., "subscriptionbatch", "callbackcompression")

        Returns:
            True if peer supports the option
        """
        self._load_trust()
        return option in self._supported

    def supports_batch_subscriptions(self) -> bool:
        """Check if peer supports batch subscription creation."""
        return self.supports("subscriptionbatch")

    def supports_compression(self) -> bool:
        """Check if peer supports callback compression."""
        return self.supports("callbackcompression")

    def supports_health_endpoint(self) -> bool:
        """Check if peer supports subscription health endpoint."""
        return self.supports("subscriptionhealth")

    def supports_resync_callbacks(self) -> bool:
        """Check if peer supports resync callback type."""
        return self.supports("subscriptionresync")

    def supports_stats_endpoint(self) -> bool:
        """Check if peer supports subscription stats endpoint."""
        return self.supports("subscriptionstats")

    def get_version(self) -> str | None:
        """Get peer's ActingWeb protocol version."""
        self._load_trust()
        if self._trust:
            return self._trust.get("aw_version")
        return None

    def get_all_supported(self) -> set[str]:
        """Get all supported option tags."""
        self._load_trust()
        return self._supported.copy()

    async def refresh_async(self) -> bool:
        """Re-fetch capabilities from peer.

        Returns:
            True if capabilities were successfully fetched
        """
        self._load_trust()
        if not self._trust:
            logger.warning(f"Cannot refresh capabilities: no trust for peer {self._peer_id}")
            return False

        baseuri = self._trust.get("baseuri", "")
        if not baseuri:
            logger.warning(f"Cannot refresh capabilities: no baseuri for peer {self._peer_id}")
            return False

        try:
            url = f"{baseuri}/meta/actingweb/supported"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                supported = response.text.strip()
                version = None

                # Also fetch version
                version_url = f"{baseuri}/meta/actingweb/version"
                try:
                    version_response = requests.get(version_url, timeout=5)
                    if version_response.status_code == 200:
                        version = version_response.text.strip()
                except Exception:
                    pass  # Version is optional

                # Update trust with capabilities
                self._actor.trust.modify_trust(
                    self._peer_id,
                    aw_supported=supported,
                    aw_version=version,
                    capabilities_fetched_at=datetime.utcnow().isoformat() + "Z"
                )

                # Reload cache
                self._loaded = False
                self._load_trust()

                logger.debug(f"Refreshed capabilities for peer {self._peer_id}: {supported}")
                return True
            else:
                logger.warning(
                    f"Failed to fetch capabilities from {self._peer_id}: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.warning(f"Error fetching capabilities from {self._peer_id}: {e}")
            return False

    def refresh(self) -> bool:
        """Synchronous wrapper for refresh_async."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - use thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self.refresh_async())
                return future.result()
        except RuntimeError:
            # No running loop - safe to create one
            return asyncio.run(self.refresh_async())

    def ensure_loaded(self) -> None:
        """Ensure capabilities are loaded, fetching if necessary.

        This is called lazily when capabilities are first accessed.
        Uses lazy fetch strategy to avoid blocking trust establishment.
        """
        if self._is_cache_valid():
            return

        # Capabilities not cached or expired - fetch them
        self.refresh()
```

#### 6. Trust Manager Extension
**File**: `actingweb/interface/trust_manager.py`

Add method to modify trust with capability fields:

```python
    def modify_trust(
        self,
        peer_id: str,
        # ... existing parameters ...
        aw_supported: str | None = None,
        aw_version: str | None = None,
        capabilities_fetched_at: str | None = None,
    ) -> bool:
        """Modify an existing trust relationship."""
        # Implementation to call DbTrust.modify() with new fields
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/peer_capabilities.py actingweb/db/dynamodb/trust.py actingweb/db/postgresql/trust.py`
- [x] Linting passes: `poetry run ruff check actingweb/peer_capabilities.py`
- [x] PostgreSQL migration applies: `cd actingweb/db/postgresql && alembic upgrade head`
- [x] Unit tests pass for PeerCapabilities class: `poetry run pytest tests/test_peer_capabilities.py -v` (28 tests)
- [x] Existing trust tests still pass: `poetry run pytest tests/test_trust*.py -v` (98 tests)
- [x] Trust flow integration tests pass: `poetry run pytest tests/integration/test_trust_flow.py -v` (33 tests)
- [ ] Full integration tests for capabilities (test_060-063): Deferred to broader subscription processing test suite

**Phase 0 Status: COMPLETE**

---

## Phase 1: Subscription Suspension & Resync Triggering

### Overview
Implement publisher-side subscription suspension and resync callback generation. This allows applications to temporarily suspend diff registration during bulk operations (e.g., imports, migrations) and trigger resync callbacks when resuming, telling subscribers to do a full GET.

**Key insight**: Multiple subscriptions can exist on the same property/subtarget. Suspension must be at the **property level** (target/subtarget), not per-subscription. When suspension is lifted, ALL affected subscriptions receive a resync callback.

**Reference**: Protocol spec v1.4 includes the `subscriptionresync` option tag and resync callback format.

### Changes Required

#### 1. Suspension State Protocol
**File**: `actingweb/db/protocols.py`

Add protocol for suspension state storage (append to file):

```python
class SubscriptionSuspensionProtocol(Protocol):
    """Protocol for subscription suspension state persistence."""

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended."""
        ...

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        Returns True if newly suspended, False if already suspended.
        """
        ...

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration for a target/subtarget.

        Returns True if was suspended and now resumed, False if wasn't suspended.
        """
        ...

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs."""
        ...
```

#### 2. DynamoDB Suspension Model
**File**: `actingweb/db/dynamodb/subscription_suspension.py` (new file)

```python
"""
DynamoDB model for subscription suspension state.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pynamodb.attributes import UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.models import Model

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


class SubscriptionSuspension(Model):
    """Tracks suspended subscription targets for an actor."""

    class Meta:
        table_name = "subscription_suspensions"
        region = "us-west-2"  # Overridden at runtime

    id = UnicodeAttribute(hash_key=True)  # actor_id
    target_key = UnicodeAttribute(range_key=True)  # "target" or "target:subtarget"
    target = UnicodeAttribute()
    subtarget = UnicodeAttribute(null=True)
    suspended_at = UTCDateTimeAttribute()


def _make_target_key(target: str, subtarget: str | None) -> str:
    """Create composite key for target/subtarget."""
    if subtarget:
        return f"{target}:{subtarget}"
    return target


class DbSubscriptionSuspension:
    """Database operations for subscription suspension state."""

    def __init__(self, actor_id: str, config: "Config") -> None:
        self._actor_id = actor_id
        self._config = config
        self._init_table()

    def _init_table(self) -> None:
        """Initialize table with correct settings."""
        SubscriptionSuspension.Meta.region = self._config.database.get("region", "us-west-2")
        SubscriptionSuspension.Meta.host = self._config.database.get("host")
        if self._config.database.get("table_prefix"):
            SubscriptionSuspension.Meta.table_name = (
                f"{self._config.database['table_prefix']}subscription_suspensions"
            )

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended."""
        target_key = _make_target_key(target, subtarget)
        try:
            SubscriptionSuspension.get(self._actor_id, target_key)
            return True
        except SubscriptionSuspension.DoesNotExist:
            return False

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration. Returns True if newly suspended."""
        if self.is_suspended(target, subtarget):
            return False

        target_key = _make_target_key(target, subtarget)
        suspension = SubscriptionSuspension(
            id=self._actor_id,
            target_key=target_key,
            target=target,
            subtarget=subtarget,
            suspended_at=datetime.now(timezone.utc),
        )
        suspension.save()
        logger.info(f"Suspended subscriptions for {self._actor_id}/{target}/{subtarget}")
        return True

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration. Returns True if was suspended."""
        target_key = _make_target_key(target, subtarget)
        try:
            suspension = SubscriptionSuspension.get(self._actor_id, target_key)
            suspension.delete()
            logger.info(f"Resumed subscriptions for {self._actor_id}/{target}/{subtarget}")
            return True
        except SubscriptionSuspension.DoesNotExist:
            return False

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs."""
        results: list[tuple[str, str | None]] = []
        for item in SubscriptionSuspension.query(self._actor_id):
            results.append((item.target, item.subtarget))
        return results
```

#### 3. PostgreSQL Suspension Schema
**File**: `actingweb/db/postgresql/schema.py`

Add the suspension table class (after existing tables):

```python
class SubscriptionSuspension(Base):
    """Tracks suspended subscription targets for an actor."""

    __tablename__ = "subscription_suspensions"

    id = Column(String(255), primary_key=True)  # actor_id
    target = Column(String(255), primary_key=True)
    subtarget = Column(String(255), primary_key=True, default="")
    suspended_at = Column(DateTime, nullable=False)
```

#### 4. PostgreSQL Migration
**File**: `actingweb/db/postgresql/migrations/versions/XXXX_add_subscription_suspensions.py` (new file)

```python
"""Add subscription_suspensions table.

Revision ID: [auto-generated]
Revises: [previous-migration]
Create Date: 2026-01-20
"""
from alembic import op
import sqlalchemy as sa

revision = '[auto-generated]'
down_revision = '[previous-migration]'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'subscription_suspensions',
        sa.Column('id', sa.String(255), nullable=False),
        sa.Column('target', sa.String(255), nullable=False),
        sa.Column('subtarget', sa.String(255), nullable=False, server_default=''),
        sa.Column('suspended_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', 'target', 'subtarget')
    )


def downgrade() -> None:
    op.drop_table('subscription_suspensions')
```

#### 5. PostgreSQL Suspension Operations
**File**: `actingweb/db/postgresql/subscription_suspension.py` (new file)

```python
"""
PostgreSQL operations for subscription suspension state.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, select

from .schema import SubscriptionSuspension

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


class DbSubscriptionSuspension:
    """Database operations for subscription suspension state."""

    def __init__(self, actor_id: str, config: "Config") -> None:
        self._actor_id = actor_id
        self._config = config

    def _get_session(self):
        """Get database session."""
        from .connection import get_session
        return get_session(self._config)

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended."""
        with self._get_session() as session:
            stmt = select(SubscriptionSuspension).where(
                and_(
                    SubscriptionSuspension.id == self._actor_id,
                    SubscriptionSuspension.target == target,
                    SubscriptionSuspension.subtarget == (subtarget or ""),
                )
            )
            result = session.execute(stmt).scalar_one_or_none()
            return result is not None

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration. Returns True if newly suspended."""
        if self.is_suspended(target, subtarget):
            return False

        with self._get_session() as session:
            suspension = SubscriptionSuspension(
                id=self._actor_id,
                target=target,
                subtarget=subtarget or "",
                suspended_at=datetime.now(timezone.utc),
            )
            session.add(suspension)
            session.commit()
            logger.info(f"Suspended subscriptions for {self._actor_id}/{target}/{subtarget}")
            return True

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration. Returns True if was suspended."""
        with self._get_session() as session:
            stmt = delete(SubscriptionSuspension).where(
                and_(
                    SubscriptionSuspension.id == self._actor_id,
                    SubscriptionSuspension.target == target,
                    SubscriptionSuspension.subtarget == (subtarget or ""),
                )
            )
            result = session.execute(stmt)
            session.commit()
            if result.rowcount > 0:
                logger.info(f"Resumed subscriptions for {self._actor_id}/{target}/{subtarget}")
                return True
            return False

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs."""
        with self._get_session() as session:
            stmt = select(SubscriptionSuspension).where(
                SubscriptionSuspension.id == self._actor_id
            )
            results: list[tuple[str, str | None]] = []
            for row in session.execute(stmt).scalars():
                subtarget = row.subtarget if row.subtarget else None
                results.append((row.target, subtarget))
            return results
```

#### 6. Core Actor Modifications
**File**: `actingweb/actor.py`

Add methods for suspension management and modify diff registration:

```python
# Add to Actor class:

def is_subscription_suspended(self, target: str, subtarget: str | None = None) -> bool:
    """Check if diff registration is suspended for a target/subtarget."""
    from .db import get_suspension_db
    db = get_suspension_db(self.id, self.config)
    return db.is_suspended(target, subtarget)

def suspend_subscriptions(self, target: str, subtarget: str | None = None) -> bool:
    """Suspend diff registration for a target/subtarget.

    While suspended, property changes will NOT register diffs or trigger callbacks.
    Call resume_subscriptions() to lift suspension and send resync callbacks.

    Returns True if newly suspended, False if already suspended.
    """
    from .db import get_suspension_db
    db = get_suspension_db(self.id, self.config)
    return db.suspend(target, subtarget)

def resume_subscriptions(self, target: str, subtarget: str | None = None) -> int:
    """Resume diff registration and send resync callbacks.

    Sends a resync callback to ALL subscriptions on this target/subtarget,
    telling them to do a full GET to re-sync their state.

    Returns the number of resync callbacks sent.
    """
    from .db import get_suspension_db
    db = get_suspension_db(self.id, self.config)

    if not db.resume(target, subtarget):
        return 0  # Wasn't suspended

    # Find all affected subscriptions and send resync callbacks
    return self._send_resync_callbacks(target, subtarget)

def _send_resync_callbacks(self, target: str, subtarget: str | None) -> int:
    """Send resync callbacks to all subscriptions on target/subtarget."""
    from .subscription import Subscriptions

    subs = Subscriptions(actor_id=self.id, config=self.config)
    all_subs = subs.get_subscriptions()

    count = 0
    for sub in all_subs:
        sub_target = sub.get("target", "")
        sub_subtarget = sub.get("subtarget")

        # Match target (and subtarget if specified)
        if sub_target != target:
            continue
        if subtarget is not None and sub_subtarget != subtarget:
            continue

        # Send resync callback
        if self._callback_subscription_resync(sub):
            count += 1

    return count

def _callback_subscription_resync(self, subscription: dict) -> bool:
    """Send a resync callback to a single subscription.

    Checks peer capability before sending resync. If peer doesn't support
    the subscriptionresync option, falls back to low-granularity callback.
    """
    import logging
    from datetime import datetime, timezone

    logger = logging.getLogger(__name__)

    peer_id = subscription.get("peerid", "")
    sub_id = subscription.get("subscriptionid", "")
    callback_url = subscription.get("callback", "")
    target = subscription.get("target", "")
    subtarget = subscription.get("subtarget")

    if not callback_url:
        logger.warning(f"No callback URL for subscription {sub_id}")
        return False

    # Check if peer supports resync callbacks
    from .peer_capabilities import PeerCapabilities
    from .interface.actor_interface import ActorInterface

    actor_interface = ActorInterface(actor_id=self.id, config=self.config)
    caps = PeerCapabilities(actor_interface, peer_id)
    supports_resync = caps.supports_resync_callbacks()

    # Increment sequence number
    new_seq = self._increment_subscription_sequence(sub_id)

    # Build resource URL for resync
    resource_url = f"{self.config.proto}{self.config.fqdn}/{self.id}/{target}"
    if subtarget:
        resource_url += f"/{subtarget}"

    # Build callback payload - use resync type only if peer supports it
    if supports_resync:
        # Resync callback per protocol spec v1.4
        payload = {
            "id": self.id,
            "subscriptionid": sub_id,
            "target": target,
            "subtarget": subtarget,
            "sequence": new_seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "granularity": subscription.get("granularity", "high"),
            "type": "resync",
            "url": resource_url,
        }
        logger.debug(f"Sending resync callback to peer {peer_id} (supports resync)")
    else:
        # Fallback: low-granularity callback with URL only
        # Peer should fetch full state from the URL
        payload = {
            "id": self.id,
            "subscriptionid": sub_id,
            "target": target,
            "subtarget": subtarget,
            "sequence": new_seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "granularity": "low",
            "url": resource_url,
        }
        logger.info(
            f"Peer {peer_id} does not support resync callbacks, "
            f"sending low-granularity callback instead"
        )

    # Get trust secret for authentication
    from .trust import Trust
    trust = Trust(actor_id=self.id, config=self.config)
    trust_data = trust.get_trust(peer_id)

    if not trust_data:
        logger.warning(f"No trust found for peer {peer_id}")
        return False

    secret = trust_data.get("secret", "")

    # Send callback
    import requests
    try:
        response = requests.post(
            callback_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {secret}",
            },
            timeout=30,
        )

        if response.status_code in (200, 204):
            logger.info(f"Sent resync callback to {peer_id} for subscription {sub_id}")
            return True
        else:
            logger.warning(
                f"Resync callback to {peer_id} failed: {response.status_code}"
            )
            return False

    except Exception as e:
        logger.error(f"Error sending resync callback to {peer_id}: {e}")
        return False

def _increment_subscription_sequence(self, subscription_id: str) -> int:
    """Increment and return the new sequence number for a subscription."""
    from .subscription import Subscriptions

    subs = Subscriptions(actor_id=self.id, config=self.config)
    sub = subs.get_subscription(subscription_id)

    if not sub:
        return 1

    current_seq = sub.get("sequence", 0)
    new_seq = current_seq + 1

    subs.modify_subscription(subscription_id, sequence=new_seq)
    return new_seq
```

#### 7. Modify register_diffs() to Check Suspension
**File**: `actingweb/actor.py`

Update the existing `register_diffs()` method to skip registration when suspended:

```python
def register_diffs(
    self,
    target: str,
    subtarget: str | None = None,
    # ... existing parameters ...
) -> bool:
    """Register diffs for subscription callbacks.

    Skips registration if the target/subtarget is currently suspended.
    """
    # Check suspension BEFORE registering diffs
    if self.is_subscription_suspended(target, subtarget):
        logger.debug(
            f"Skipping diff registration for {target}/{subtarget}: suspended"
        )
        return False

    # ... existing implementation continues ...
```

#### 8. Subscription Manager Extension
**File**: `actingweb/interface/subscription_manager.py`

Add suspend/resume methods to the developer-facing API:

```python
# Add to SubscriptionManager class:

def suspend(self, target: str, subtarget: str | None = None) -> bool:
    """Suspend diff registration for a target/subtarget.

    While suspended:
    - Property changes will NOT register diffs
    - No subscription callbacks will be sent
    - Use resume() to lift suspension and trigger resync

    Args:
        target: Target resource (e.g., "properties")
        subtarget: Optional subtarget (e.g., property name)

    Returns:
        True if newly suspended, False if already suspended

    Example:
        actor.subscriptions.suspend(target="properties", subtarget="memory_travel")
        # ... perform bulk operations ...
        actor.subscriptions.resume(target="properties", subtarget="memory_travel")
    """
    return self._actor.suspend_subscriptions(target, subtarget)

def resume(self, target: str, subtarget: str | None = None) -> int:
    """Resume diff registration and send resync callbacks.

    Sends a resync callback to ALL subscriptions matching the target/subtarget,
    telling subscribers to perform a full GET to re-sync their state.

    Args:
        target: Target resource (e.g., "properties")
        subtarget: Optional subtarget (e.g., property name)

    Returns:
        Number of resync callbacks sent

    Example:
        count = actor.subscriptions.resume(target="properties", subtarget="memory_travel")
        print(f"Sent {count} resync callbacks")
    """
    return self._actor.resume_subscriptions(target, subtarget)

def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
    """Check if diff registration is suspended for a target/subtarget.

    Args:
        target: Target resource (e.g., "properties")
        subtarget: Optional subtarget (e.g., property name)

    Returns:
        True if suspended, False otherwise
    """
    return self._actor.is_subscription_suspended(target, subtarget)

def get_all_suspended(self) -> list[tuple[str, str | None]]:
    """Get all currently suspended target/subtarget pairs.

    Returns:
        List of (target, subtarget) tuples that are currently suspended
    """
    from ..db import get_suspension_db
    db = get_suspension_db(self._actor.id, self._actor._config)
    return db.get_all_suspended()
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/db/dynamodb/subscription_suspension.py actingweb/db/postgresql/subscription_suspension.py`
- [x] Linting passes: `poetry run ruff check actingweb/db/*/subscription_suspension.py`
- [x] PostgreSQL migration applies: `cd actingweb/db/postgresql/migrations && alembic upgrade head`
- [x] Unit tests pass: `poetry run pytest tests/test_subscription_suspension.py -v`
  - Suspend/resume state tracking
  - `is_suspended()` with various scopes
  - `register_diffs()` skip behavior when suspended
  - Resync callback payload format
- [ ] Integration tests for suspension (test_100-109): Deferred to broader integration test suite
- [x] Existing subscription tests still pass: `poetry run pytest tests/test_subscription*.py -v`

**Phase 1 Status: COMPLETE**

---

## Phase 2: Core Callback Handling (CallbackProcessor)

### Overview
Implement callback sequencing, deduplication, and resync handling. This component ensures callbacks are processed in order even in serverless environments where concurrent Lambda instances may receive callbacks out of order.

### Changes Required

#### 1. Callback State Storage Protocol
**File**: `actingweb/db/protocols.py`

Add protocol for callback state storage (append to file):

```python
class CallbackStateProtocol(Protocol):
    """Protocol for callback state persistence."""

    def get_state(self, peer_id: str, subscription_id: str) -> dict[str, Any] | None:
        """Get callback state for a subscription."""
        ...

    def set_state(
        self,
        peer_id: str,
        subscription_id: str,
        state: dict[str, Any],
        expected_version: int | None = None
    ) -> bool:
        """Set callback state with optional optimistic locking.

        Returns False if version conflict (another process updated).
        """
        ...

    def get_pending(self, peer_id: str, subscription_id: str) -> list[dict[str, Any]]:
        """Get pending (out-of-order) callbacks."""
        ...

    def add_pending(
        self,
        peer_id: str,
        subscription_id: str,
        callback: dict[str, Any]
    ) -> bool:
        """Add callback to pending queue."""
        ...

    def remove_pending(self, peer_id: str, subscription_id: str, sequence: int) -> None:
        """Remove callback from pending queue by sequence number."""
        ...

    def clear_pending(self, peer_id: str, subscription_id: str) -> None:
        """Clear all pending callbacks for a subscription."""
        ...
```

#### 2. CallbackProcessor Implementation
**File**: `actingweb/callback_processor.py` (new file)

```python
"""
Callback processor for subscription callbacks.

Handles sequencing, deduplication, and resync per ActingWeb protocol v1.4.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


class ProcessResult(Enum):
    """Result of processing a callback."""
    PROCESSED = "processed"      # Callback was processed successfully
    DUPLICATE = "duplicate"      # Callback was a duplicate (already processed)
    PENDING = "pending"          # Callback stored in pending queue (gap detected)
    RESYNC_TRIGGERED = "resync_triggered"  # Gap timeout exceeded, resync needed
    REJECTED = "rejected"        # Callback rejected (back-pressure)


class CallbackType(Enum):
    """Type of callback."""
    DIFF = "diff"
    RESYNC = "resync"


@dataclass
class ProcessedCallback:
    """Represents a processed callback ready for the handler."""
    peer_id: str
    subscription_id: str
    sequence: int
    callback_type: CallbackType
    data: dict[str, Any]
    timestamp: str


class CallbackProcessor:
    """
    Processes inbound subscription callbacks per ActingWeb protocol v1.4.

    Handles:
    - Sequence tracking and gap detection
    - Duplicate filtering
    - Resync callback processing
    - Back-pressure via pending queue limits

    Storage: Uses actor's internal attributes (bucket: _callback_state).
    """

    def __init__(
        self,
        actor: "ActorInterface",
        gap_timeout_seconds: float = 5.0,
        max_pending: int = 100,
        max_retries: int = 3,
        retry_backoff_base: float = 0.5,
    ) -> None:
        """
        Initialize callback processor.

        Args:
            actor: The actor receiving callbacks
            gap_timeout_seconds: Time before triggering resync on sequence gap
            max_pending: Max pending callbacks before rejecting (back-pressure)
            max_retries: Max retries for optimistic locking conflicts
            retry_backoff_base: Base delay for exponential backoff
        """
        self._actor = actor
        self._gap_timeout = gap_timeout_seconds
        self._max_pending = max_pending
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_base
        self._state_bucket = "_callback_state"

    def _get_state_key(self, peer_id: str, subscription_id: str) -> str:
        """Get attribute key for callback state."""
        return f"state:{peer_id}:{subscription_id}"

    def _get_pending_key(self, peer_id: str, subscription_id: str) -> str:
        """Get attribute key for pending callbacks."""
        return f"pending:{peer_id}:{subscription_id}"

    def _get_state(self, peer_id: str, subscription_id: str) -> dict[str, Any]:
        """Get callback state from storage."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )
        state = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
        return state or {"last_seq": 0, "version": 0, "resync_pending": False}

    def _set_state(
        self,
        peer_id: str,
        subscription_id: str,
        state: dict[str, Any],
        expected_version: int | None = None
    ) -> bool:
        """Set callback state with optimistic locking."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )

        if expected_version is not None:
            # Check current version
            current = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
            current_version = (current or {}).get("version", 0)
            if current_version != expected_version:
                return False  # Version conflict

        # Increment version
        state["version"] = state.get("version", 0) + 1

        db.set_attr(
            name=self._get_state_key(peer_id, subscription_id),
            data=state
        )
        return True

    def _get_pending(self, peer_id: str, subscription_id: str) -> list[dict[str, Any]]:
        """Get pending callbacks from storage."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )
        pending = db.get_attr(name=self._get_pending_key(peer_id, subscription_id))
        return pending.get("callbacks", []) if pending else []

    def _set_pending(
        self,
        peer_id: str,
        subscription_id: str,
        callbacks: list[dict[str, Any]]
    ) -> None:
        """Set pending callbacks in storage."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )
        db.set_attr(
            name=self._get_pending_key(peer_id, subscription_id),
            data={"callbacks": callbacks}
        )

    def _add_pending(
        self,
        peer_id: str,
        subscription_id: str,
        callback: dict[str, Any]
    ) -> bool:
        """Add callback to pending queue. Returns False if queue full."""
        pending = self._get_pending(peer_id, subscription_id)

        if len(pending) >= self._max_pending:
            return False  # Back-pressure

        # Add with timestamp for gap timeout detection
        callback["_received_at"] = time.time()
        pending.append(callback)
        pending.sort(key=lambda c: c.get("sequence", 0))

        self._set_pending(peer_id, subscription_id, pending)
        return True

    def _remove_pending(self, peer_id: str, subscription_id: str, sequence: int) -> None:
        """Remove callback from pending by sequence."""
        pending = self._get_pending(peer_id, subscription_id)
        pending = [c for c in pending if c.get("sequence") != sequence]
        self._set_pending(peer_id, subscription_id, pending)

    def _clear_pending(self, peer_id: str, subscription_id: str) -> None:
        """Clear all pending callbacks."""
        self._set_pending(peer_id, subscription_id, [])

    def _check_gap_timeout(self, pending: list[dict[str, Any]]) -> bool:
        """Check if oldest pending callback has exceeded gap timeout."""
        if not pending:
            return False

        oldest = min(c.get("_received_at", time.time()) for c in pending)
        return (time.time() - oldest) > self._gap_timeout

    async def process_callback(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        callback_type: str = "diff",
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None = None,
    ) -> ProcessResult:
        """
        Process a callback with automatic sequencing.

        Args:
            peer_id: ID of the peer sending the callback
            subscription_id: Subscription identifier
            sequence: Sequence number from callback
            data: Callback data payload
            callback_type: "diff" or "resync"
            handler: Optional async handler to invoke for valid callbacks

        Returns:
            ProcessResult indicating what happened
        """
        # Handle resync callbacks specially
        if callback_type == "resync":
            return await self._handle_resync(
                peer_id, subscription_id, sequence, data, handler
            )

        # Retry loop for optimistic locking
        for attempt in range(self._max_retries):
            state = self._get_state(peer_id, subscription_id)
            last_seq = state.get("last_seq", 0)
            version = state.get("version", 0)

            # Check for duplicate
            if sequence <= last_seq:
                logger.debug(
                    f"Duplicate callback: seq={sequence} <= last_seq={last_seq}"
                )
                return ProcessResult.DUPLICATE

            # Check for gap
            if sequence > last_seq + 1:
                # Gap detected - add to pending
                pending = self._get_pending(peer_id, subscription_id)

                # Check gap timeout on existing pending
                if self._check_gap_timeout(pending):
                    logger.warning(
                        f"Gap timeout exceeded for {peer_id}:{subscription_id}, "
                        f"triggering resync"
                    )
                    # Mark resync pending and clear queue
                    state["resync_pending"] = True
                    state["last_seq"] = -1  # Reset to accept any sequence
                    self._set_state(peer_id, subscription_id, state, version)
                    self._clear_pending(peer_id, subscription_id)
                    return ProcessResult.RESYNC_TRIGGERED

                # Add to pending queue
                callback_data = {
                    "sequence": sequence,
                    "data": data,
                    "callback_type": callback_type,
                }
                if not self._add_pending(peer_id, subscription_id, callback_data):
                    logger.warning(
                        f"Pending queue full for {peer_id}:{subscription_id}"
                    )
                    return ProcessResult.REJECTED

                logger.debug(
                    f"Gap detected: seq={sequence}, last_seq={last_seq}, added to pending"
                )
                return ProcessResult.PENDING

            # Sequence is correct (last_seq + 1)
            # Process this callback and any consecutive pending
            callbacks_to_process = [
                ProcessedCallback(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=sequence,
                    callback_type=CallbackType.DIFF,
                    data=data,
                    timestamp=data.get("timestamp", ""),
                )
            ]

            # Check pending for consecutive sequences
            pending = self._get_pending(peer_id, subscription_id)
            next_seq = sequence + 1
            while pending:
                next_callback = next(
                    (c for c in pending if c.get("sequence") == next_seq), None
                )
                if not next_callback:
                    break
                callbacks_to_process.append(
                    ProcessedCallback(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        sequence=next_seq,
                        callback_type=CallbackType.DIFF,
                        data=next_callback["data"],
                        timestamp=next_callback["data"].get("timestamp", ""),
                    )
                )
                self._remove_pending(peer_id, subscription_id, next_seq)
                pending = self._get_pending(peer_id, subscription_id)
                next_seq += 1

            # Update state with new last_seq
            new_last_seq = callbacks_to_process[-1].sequence
            state["last_seq"] = new_last_seq
            state["resync_pending"] = False

            if not self._set_state(peer_id, subscription_id, state, version):
                # Version conflict - retry
                logger.debug(f"Version conflict, retrying (attempt {attempt + 1})")
                time.sleep(self._retry_backoff * (2 ** attempt))
                continue

            # Invoke handler for all callbacks in order
            if handler:
                for cb in callbacks_to_process:
                    try:
                        await handler(cb)
                    except Exception as e:
                        logger.error(f"Handler error for seq={cb.sequence}: {e}")
                        # Continue processing - at-most-once semantics

            return ProcessResult.PROCESSED

        # Exhausted retries
        logger.error(
            f"Failed to process callback after {self._max_retries} retries"
        )
        return ProcessResult.REJECTED

    async def _handle_resync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None,
    ) -> ProcessResult:
        """Handle a resync callback from the protocol."""
        logger.info(f"Processing resync callback for {peer_id}:{subscription_id}")

        # Clear pending queue
        self._clear_pending(peer_id, subscription_id)

        # Reset state with new sequence
        state = {
            "last_seq": sequence,
            "version": 0,
            "resync_pending": False,
        }
        self._set_state(peer_id, subscription_id, state, expected_version=None)

        # Invoke handler with resync data
        if handler:
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=sequence,
                callback_type=CallbackType.RESYNC,
                data=data,
                timestamp=data.get("timestamp", ""),
            )
            try:
                await handler(callback)
            except Exception as e:
                logger.error(f"Resync handler error: {e}")

        return ProcessResult.PROCESSED

    def get_state_info(self, peer_id: str, subscription_id: str) -> dict[str, Any]:
        """Get current state information for debugging."""
        state = self._get_state(peer_id, subscription_id)
        pending = self._get_pending(peer_id, subscription_id)
        return {
            "last_seq": state.get("last_seq", 0),
            "version": state.get("version", 0),
            "resync_pending": state.get("resync_pending", False),
            "pending_count": len(pending),
            "pending_sequences": [c.get("sequence") for c in pending],
        }

    def clear_state(self, peer_id: str, subscription_id: str) -> None:
        """Clear all state for a subscription (e.g., when trust deleted)."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )
        db.delete_attr(name=self._get_state_key(peer_id, subscription_id))
        db.delete_attr(name=self._get_pending_key(peer_id, subscription_id))

    def clear_all_state_for_peer(self, peer_id: str) -> None:
        """Clear all callback state for a peer (when trust deleted)."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor._config
        )

        # Get all attributes in bucket and delete those for this peer
        all_attrs = db.get_bucket() or {}
        for attr_name in list(all_attrs.keys()):
            if f":{peer_id}:" in attr_name:
                db.delete_attr(name=attr_name)
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/callback_processor.py`
- [x] Linting passes: `poetry run ruff check actingweb/callback_processor.py`
- [x] Unit tests pass: `poetry run pytest tests/test_callback_processor.py -v` (20 tests)
  - Sequence tracking (in-order, gap, duplicate)
  - Pending queue (add, remove, timeout)
  - Resync handling
  - Optimistic locking conflicts
- [ ] Integration tests for sequencing (test_010-014): Deferred to broader integration test suite
- [ ] Integration tests for resync (test_020-022): Deferred to broader integration test suite
- [ ] Integration tests for back-pressure (test_040-041): Deferred to broader integration test suite

**Phase 2 Status: COMPLETE**

---

## Phase 3: Storage Abstraction (RemotePeerStore)

### Overview
Implement storage for data received from peer actors, using the bucket pattern (`remote:{peer_id}`) with automatic list operation handling.

### Changes Required

#### 1. RemotePeerStore Implementation
**File**: `actingweb/remote_storage.py` (new file)

```python
"""
Remote peer data storage.

Provides storage abstraction for data received from peer actors,
using internal attributes (not exposed via HTTP).
"""

import logging
import re
from typing import TYPE_CHECKING, Any, Pattern

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Default pattern matches actingweb library's UUID v5 .hex format
DEFAULT_PEER_ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')

# More permissive pattern that accepts both formats
PERMISSIVE_PEER_ID_PATTERN = re.compile(
    r'^[a-f0-9]{32}$|^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
)


def get_remote_bucket(
    peer_id: str,
    validate: bool = True,
    pattern: Pattern[str] | None = None
) -> str:
    """Get the standard bucket name for a remote peer's data.

    Args:
        peer_id: The peer's actor ID
        validate: Whether to validate peer_id format (default: True)
        pattern: Custom regex pattern for validation (default: 32-char hex)

    Returns:
        Bucket name in format "remote:{peer_id}"

    Raises:
        ValueError: If validate=True and peer_id format is invalid
    """
    if validate:
        pat = pattern or PERMISSIVE_PEER_ID_PATTERN
        if not pat.match(peer_id):
            raise ValueError(
                f"Invalid peer_id format: {peer_id}. "
                f"Expected pattern: {pat.pattern}"
            )
    return f"remote:{peer_id}"


class RemotePeerStore:
    """
    Storage abstraction for data received from peer actors.

    Provides a clean interface for storing data in internal attributes
    (not exposed via HTTP). Each peer gets isolated storage in bucket
    "remote:{peer_id}".

    Supports automatic list operation handling for subscription callbacks.
    """

    def __init__(
        self,
        actor: "ActorInterface",
        peer_id: str,
        validate_peer_id: bool = True
    ) -> None:
        """
        Initialize remote peer store.

        Args:
            actor: The actor storing peer data
            peer_id: The peer's actor ID
            validate_peer_id: Whether to validate peer_id format
        """
        self._actor = actor
        self._peer_id = peer_id
        self._bucket = get_remote_bucket(peer_id, validate=validate_peer_id)
        self._list_store = None  # Lazy loaded

    @property
    def bucket(self) -> str:
        """Get the bucket name for this peer's data."""
        return self._bucket

    def _get_attributes(self):
        """Get Attributes instance for this bucket."""
        from .attribute import Attributes
        return Attributes(
            actor_id=self._actor.id,
            bucket=self._bucket,
            config=self._actor._config
        )

    def _get_list_store(self):
        """Get AttributeListStore for this bucket (lazy loaded)."""
        if self._list_store is None:
            from .attribute_list_store import AttributeListStore
            self._list_store = AttributeListStore(
                actor_id=self._actor.id,
                bucket=self._bucket,
                config=self._actor._config
            )
        return self._list_store

    # Scalar operations

    def get_value(self, name: str) -> dict[str, Any] | None:
        """Get a scalar value by name."""
        db = self._get_attributes()
        return db.get_attr(name=name)

    def set_value(self, name: str, value: dict[str, Any]) -> None:
        """Set a scalar value."""
        db = self._get_attributes()
        db.set_attr(name=name, data=value)

    def delete_value(self, name: str) -> None:
        """Delete a scalar value."""
        db = self._get_attributes()
        db.delete_attr(name=name)

    # List operations

    def get_list(self, name: str) -> list[dict[str, Any]]:
        """Get a list by name."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        return list(list_attr)

    def set_list(
        self,
        name: str,
        items: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None
    ) -> None:
        """Set a list (replaces all items)."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.clear()
        list_attr.extend(items)
        if metadata:
            list_attr.set_metadata(metadata)

    def delete_list(self, name: str) -> None:
        """Delete a list entirely."""
        store = self._get_list_store()
        list_attr = getattr(store, name)
        list_attr.delete()

    def list_all_lists(self) -> list[str]:
        """List all stored lists for this peer."""
        store = self._get_list_store()
        return store.list_all()

    # Cleanup

    def delete_all(self) -> None:
        """Delete all data for this peer.

        Call this when trust relationship ends.
        """
        db = self._get_attributes()
        db.delete_bucket()
        logger.info(f"Deleted all data for peer {self._peer_id}")

    # Storage statistics

    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics for this peer."""
        db = self._get_attributes()
        all_attrs = db.get_bucket() or {}

        list_count = 0
        scalar_count = 0
        for name in all_attrs.keys():
            if name.startswith("list:"):
                list_count += 1
            else:
                scalar_count += 1

        return {
            "peer_id": self._peer_id,
            "bucket": self._bucket,
            "list_count": list_count,
            "scalar_count": scalar_count,
            "total_attributes": len(all_attrs),
        }

    # Callback data application

    def apply_callback_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply callback data to storage, handling list operations.

        This is the main method for automatic storage mode. It:
        - Detects list operations (append, update, delete, etc.)
        - Applies them to the appropriate list
        - Stores scalar values directly

        Args:
            data: Callback data dict from subscription callback

        Returns:
            Dict of {property_name: operation_result} for each processed property
        """
        results: dict[str, Any] = {}

        for key, value in data.items():
            try:
                if key.startswith("list:") and isinstance(value, dict):
                    # List operation
                    list_name = value.get("list", key[5:])
                    operation = value.get("operation", "unknown")
                    results[list_name] = self._apply_list_operation(
                        list_name, operation, value
                    )
                else:
                    # Scalar value
                    if isinstance(value, dict):
                        self.set_value(key, value)
                        results[key] = {"stored": True, "type": "scalar"}
                    else:
                        # Wrap non-dict values
                        self.set_value(key, {"value": value})
                        results[key] = {"stored": True, "type": "scalar", "wrapped": True}
            except Exception as e:
                logger.error(f"Error applying callback data for {key}: {e}")
                results[key] = {"error": str(e)}

        return results

    def _apply_list_operation(
        self,
        list_name: str,
        operation: str,
        data: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply a single list operation."""
        store = self._get_list_store()
        list_attr = getattr(store, list_name)

        if operation == "append" and "item" in data:
            list_attr.append(data["item"])
            return {"operation": "append", "success": True}

        elif operation == "insert" and "item" in data and "index" in data:
            list_attr.insert(data["index"], data["item"])
            return {"operation": "insert", "index": data["index"], "success": True}

        elif operation == "update" and "item" in data and "index" in data:
            idx = data["index"]
            if 0 <= idx < len(list_attr):
                list_attr[idx] = data["item"]
                return {"operation": "update", "index": idx, "success": True}
            return {"operation": "update", "error": "index out of range"}

        elif operation == "extend" and "items" in data:
            list_attr.extend(data["items"])
            return {"operation": "extend", "count": len(data["items"]), "success": True}

        elif operation == "delete" and "index" in data:
            idx = data["index"]
            if 0 <= idx < len(list_attr):
                del list_attr[idx]
                return {"operation": "delete", "index": idx, "success": True}
            return {"operation": "delete", "error": "index out of range"}

        elif operation == "pop":
            idx = data.get("index", -1)
            if len(list_attr) > 0:
                if idx == -1:
                    idx = len(list_attr) - 1
                if 0 <= idx < len(list_attr):
                    list_attr.pop(idx)
                    return {"operation": "pop", "index": idx, "success": True}
            return {"operation": "pop", "error": "index out of range or empty list"}

        elif operation == "clear":
            list_attr.clear()
            return {"operation": "clear", "success": True}

        elif operation == "delete_all":
            list_attr.delete()
            return {"operation": "delete_all", "success": True}

        elif operation == "metadata":
            # Metadata-only change, no storage action needed
            return {"operation": "metadata", "ignored": True}

        elif operation == "remove" and "item" in data:
            # Remove by value - find and delete first matching item
            item_to_remove = data["item"]
            for i, existing in enumerate(list_attr):
                if existing == item_to_remove:
                    del list_attr[i]
                    return {"operation": "remove", "index": i, "success": True}
            return {"operation": "remove", "error": "item not found"}

        return {"operation": operation, "error": "unknown operation"}

    def apply_resync_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply full resync data, replacing all existing data.

        Args:
            data: Full state data from resync callback

        Returns:
            Dict of {property_name: operation_result}
        """
        results: dict[str, Any] = {}

        # Delete existing data first
        self.delete_all()

        # Apply all new data
        for key, value in data.items():
            try:
                if key.startswith("list:") and isinstance(value, list):
                    # Full list replacement
                    list_name = key[5:]
                    self.set_list(list_name, value)
                    results[list_name] = {
                        "operation": "resync",
                        "items": len(value),
                        "success": True
                    }
                elif isinstance(value, dict):
                    self.set_value(key, value)
                    results[key] = {"operation": "resync", "success": True}
                else:
                    self.set_value(key, {"value": value})
                    results[key] = {"operation": "resync", "success": True}
            except Exception as e:
                logger.error(f"Error applying resync data for {key}: {e}")
                results[key] = {"error": str(e)}

        return results
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/remote_storage.py`
- [x] Linting passes: `poetry run ruff check actingweb/remote_storage.py`
- [x] Unit tests pass: `poetry run pytest tests/test_remote_storage.py -v` (34 tests)
  - Scalar operations (get, set, delete)
  - All 10 list operations (append, insert, update, delete, extend, pop, clear, delete_all, remove, metadata)
  - `apply_callback_data()` with mixed operations
  - `apply_resync_data()` full state replacement
  - `delete_all()` cleanup
- [ ] Integration tests for list operations (test_030-036): Deferred to broader integration test suite
- [ ] Integration tests for cleanup (test_050-053): Deferred to broader integration test suite

**Phase 3 Status: COMPLETE**

---

## Phase 4: Scale Features (FanOutManager)

### Overview
Implement scalable callback delivery with parallel requests, circuit breakers, and automatic granularity downgrade for large payloads.

### Changes Required

#### 1. FanOutManager Implementation
**File**: `actingweb/fanout.py` (new file)

```python
"""
Fan-out manager for subscription callback delivery.

Provides scalable callback delivery with:
- Parallel HTTP requests with bounded concurrency
- Circuit breaker pattern for failing peers
- Automatic granularity downgrade for large payloads
"""

import asyncio
import gzip
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface
    from .peer_capabilities import PeerCapabilities

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker for a single peer."""
    peer_id: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0

    # Configuration
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0

    def record_success(self) -> None:
        """Record successful delivery."""
        self.failure_count = 0
        self.last_success_time = time.time()
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record failed delivery."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit breaker opened for peer {self.peer_id} "
                f"after {self.failure_count} failures"
            )
            self.state = CircuitState.OPEN

    def should_allow_request(self) -> bool:
        """Check if request should be allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown has passed
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.cooldown_seconds:
                logger.info(
                    f"Circuit breaker half-open for peer {self.peer_id}, "
                    f"testing recovery"
                )
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN - allow one test request
        return True


@dataclass
class DeliveryResult:
    """Result of delivering to a single subscriber."""
    peer_id: str
    subscription_id: str
    success: bool
    status_code: int | None = None
    error: str | None = None
    retry_after: int | None = None
    granularity_downgraded: bool = False


@dataclass
class FanOutResult:
    """Result of fan-out delivery to all subscribers."""
    total: int
    successful: int
    failed: int
    circuit_open: int
    results: list[DeliveryResult] = field(default_factory=list)


class FanOutManager:
    """
    Manages callback delivery to multiple subscribers at scale.

    Implements protocol v1.4 features:
    - Automatic granularity downgrade when payload > threshold
    - Circuit breaker pattern for handling 429/503 responses
    - Optional compression for large payloads
    """

    def __init__(
        self,
        actor: "ActorInterface",
        max_concurrent: int = 10,
        max_payload_for_high_granularity: int = 65536,  # 64KB
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
        request_timeout: float = 30.0,
        enable_compression: bool = True,
    ) -> None:
        """
        Initialize fan-out manager.

        Args:
            actor: The actor sending callbacks
            max_concurrent: Maximum concurrent HTTP requests
            max_payload_for_high_granularity: Payload size limit before downgrade
            circuit_breaker_threshold: Failures before opening circuit
            circuit_breaker_cooldown: Seconds before testing recovery
            request_timeout: HTTP request timeout in seconds
            enable_compression: Whether to use compression when supported
        """
        self._actor = actor
        self._max_concurrent = max_concurrent
        self._max_payload_size = max_payload_for_high_granularity
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        self._request_timeout = request_timeout
        self._enable_compression = enable_compression

        # Circuit breakers per peer
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _get_circuit_breaker(self, peer_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for peer."""
        if peer_id not in self._circuit_breakers:
            self._circuit_breakers[peer_id] = CircuitBreaker(
                peer_id=peer_id,
                failure_threshold=self._cb_threshold,
                cooldown_seconds=self._cb_cooldown,
            )
        return self._circuit_breakers[peer_id]

    async def deliver_to_subscribers(
        self,
        subscriptions: list[dict[str, Any]],
        payload: dict[str, Any],
        target: str,
        sequence: int,
    ) -> FanOutResult:
        """
        Deliver callbacks to multiple subscribers.

        Args:
            subscriptions: List of subscription dicts with callback URLs
            payload: The callback payload data
            target: Target resource (e.g., "properties")
            sequence: Sequence number for this callback

        Returns:
            FanOutResult with delivery statistics
        """
        if not subscriptions:
            return FanOutResult(total=0, successful=0, failed=0, circuit_open=0)

        # Prepare payload
        payload_json = json.dumps(payload)
        payload_size = len(payload_json.encode('utf-8'))
        needs_downgrade = payload_size > self._max_payload_size

        # Create semaphore for bounded concurrency
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def deliver_one(sub: dict[str, Any]) -> DeliveryResult:
            peer_id = sub.get("peerid", "")
            sub_id = sub.get("subid", "")
            callback_url = sub.get("callback_url", "")
            granularity = sub.get("granularity", "high")

            # Check circuit breaker
            cb = self._get_circuit_breaker(peer_id)
            if not cb.should_allow_request():
                return DeliveryResult(
                    peer_id=peer_id,
                    subscription_id=sub_id,
                    success=False,
                    error="circuit_open",
                )

            async with semaphore:
                return await self._deliver_single(
                    peer_id=peer_id,
                    subscription_id=sub_id,
                    callback_url=callback_url,
                    payload=payload,
                    payload_json=payload_json,
                    payload_size=payload_size,
                    target=target,
                    sequence=sequence,
                    granularity=granularity,
                    needs_downgrade=needs_downgrade,
                )

        # Execute deliveries concurrently
        results = await asyncio.gather(
            *[deliver_one(sub) for sub in subscriptions],
            return_exceptions=True
        )

        # Process results
        delivery_results: list[DeliveryResult] = []
        successful = 0
        failed = 0
        circuit_open = 0

        for result in results:
            if isinstance(result, Exception):
                delivery_results.append(DeliveryResult(
                    peer_id="unknown",
                    subscription_id="unknown",
                    success=False,
                    error=str(result),
                ))
                failed += 1
            elif result.success:
                successful += 1
                delivery_results.append(result)
            elif result.error == "circuit_open":
                circuit_open += 1
                delivery_results.append(result)
            else:
                failed += 1
                delivery_results.append(result)

        return FanOutResult(
            total=len(subscriptions),
            successful=successful,
            failed=failed,
            circuit_open=circuit_open,
            results=delivery_results,
        )

    async def _deliver_single(
        self,
        peer_id: str,
        subscription_id: str,
        callback_url: str,
        payload: dict[str, Any],
        payload_json: str,
        payload_size: int,
        target: str,
        sequence: int,
        granularity: str,
        needs_downgrade: bool,
    ) -> DeliveryResult:
        """Deliver callback to a single subscriber."""
        cb = self._get_circuit_breaker(peer_id)

        try:
            # Build callback wrapper per protocol spec
            callback_wrapper = {
                "id": self._actor.id,
                "target": target,
                "sequence": sequence,
                "timestamp": self._get_timestamp(),
                "granularity": granularity,
                "subscriptionid": subscription_id,
            }

            headers = {
                "Content-Type": "application/json",
            }

            # Handle granularity downgrade
            granularity_downgraded = False
            if needs_downgrade and granularity == "high":
                # Downgrade to low granularity - send URL instead of data
                callback_wrapper["granularity"] = "low"
                callback_wrapper["url"] = self._build_resource_url(target)
                headers["X-ActingWeb-Granularity-Downgraded"] = "true"
                granularity_downgraded = True
            else:
                callback_wrapper["data"] = payload

            body = json.dumps(callback_wrapper)
            body_bytes = body.encode('utf-8')

            # Compress if enabled and beneficial
            if self._enable_compression and len(body_bytes) > 1024:
                # Check if peer supports compression
                caps = self._get_peer_capabilities(peer_id)
                if caps and caps.supports_compression():
                    body_bytes = gzip.compress(body_bytes)
                    headers["Content-Encoding"] = "gzip"

            # Add auth token
            trust = self._actor.trust.get_trust(peer_id)
            if trust:
                headers["Authorization"] = f"Bearer {trust.get('secret', '')}"

            # Make HTTP request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    callback_url,
                    data=body_bytes,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._request_timeout),
                ) as response:
                    status = response.status

                    if status == 204 or status == 200:
                        cb.record_success()
                        return DeliveryResult(
                            peer_id=peer_id,
                            subscription_id=subscription_id,
                            success=True,
                            status_code=status,
                            granularity_downgraded=granularity_downgraded,
                        )
                    elif status == 429:
                        # Rate limited - respect Retry-After
                        retry_after = response.headers.get("Retry-After")
                        cb.record_failure()
                        return DeliveryResult(
                            peer_id=peer_id,
                            subscription_id=subscription_id,
                            success=False,
                            status_code=status,
                            error="rate_limited",
                            retry_after=int(retry_after) if retry_after else None,
                        )
                    elif status == 503:
                        cb.record_failure()
                        return DeliveryResult(
                            peer_id=peer_id,
                            subscription_id=subscription_id,
                            success=False,
                            status_code=status,
                            error="service_unavailable",
                        )
                    else:
                        cb.record_failure()
                        return DeliveryResult(
                            peer_id=peer_id,
                            subscription_id=subscription_id,
                            success=False,
                            status_code=status,
                            error=f"http_error_{status}",
                        )

        except asyncio.TimeoutError:
            cb.record_failure()
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error="timeout",
            )
        except Exception as e:
            cb.record_failure()
            logger.error(f"Error delivering to {peer_id}: {e}")
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error=str(e),
            )

    def _get_timestamp(self) -> str:
        """Get ISO timestamp for callback."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def _build_resource_url(self, target: str) -> str:
        """Build URL for low granularity callbacks."""
        return f"{self._actor._config.proto}{self._actor._config.fqdn}/{self._actor.id}/{target}"

    def _get_peer_capabilities(self, peer_id: str) -> "PeerCapabilities | None":
        """Get peer capabilities if available."""
        try:
            from .peer_capabilities import PeerCapabilities
            return PeerCapabilities(self._actor, peer_id)
        except Exception:
            return None

    def get_circuit_breaker_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            peer_id: {
                "state": cb.state.value,
                "failure_count": cb.failure_count,
                "last_failure_time": cb.last_failure_time,
                "last_success_time": cb.last_success_time,
            }
            for peer_id, cb in self._circuit_breakers.items()
        }

    def reset_circuit_breaker(self, peer_id: str) -> None:
        """Manually reset a circuit breaker."""
        if peer_id in self._circuit_breakers:
            self._circuit_breakers[peer_id] = CircuitBreaker(
                peer_id=peer_id,
                failure_threshold=self._cb_threshold,
                cooldown_seconds=self._cb_cooldown,
            )
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/fanout.py`
- [x] Linting passes: `poetry run ruff check actingweb/fanout.py`
- [x] Unit tests pass: `poetry run pytest tests/test_fanout.py -v` (32 tests)
  - Circuit breaker state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - Bounded concurrency (never exceeds max_concurrent)
  - Granularity downgrade for large payloads
  - Compression when peer supports it
- [ ] Integration tests for fan-out (test_070-074): Deferred to broader integration test suite
- [ ] Integration tests for circuit breaker (test_080-085): Deferred to broader integration test suite

**Phase 4 Status: COMPLETE**

---

## Phase 5: Integration Layer

### Overview
Implement the developer-facing API: `.with_subscription_processing()` configuration and `@subscription_data_hook` decorator.

### Changes Required

#### 1. SubscriptionProcessingConfig
**File**: `actingweb/subscription_config.py` (new file)

```python
"""
Configuration for automatic subscription processing.
"""

from dataclasses import dataclass


@dataclass
class SubscriptionProcessingConfig:
    """Configuration for automatic subscription processing."""

    enabled: bool = False
    auto_sequence: bool = True
    auto_storage: bool = True
    auto_cleanup: bool = True
    gap_timeout_seconds: float = 5.0
    max_pending: int = 100
    storage_prefix: str = "remote:"

    # Fan-out settings
    max_concurrent_callbacks: int = 10
    max_payload_for_high_granularity: int = 65536
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 60.0
```

#### 2. ActingWebApp Extension
**File**: `actingweb/interface/app.py`

Add `.with_subscription_processing()` method and `@subscription_data_hook` decorator:

```python
# Add import at top
from ..subscription_config import SubscriptionProcessingConfig

# Add to __init__:
self._subscription_config = SubscriptionProcessingConfig()
self._subscription_data_hooks: dict[str, list[Callable[..., Any]]] = {}

# Add method:
def with_subscription_processing(
    self,
    auto_sequence: bool = True,
    auto_storage: bool = True,
    auto_cleanup: bool = True,
    gap_timeout_seconds: float = 5.0,
    max_pending: int = 100,
    storage_prefix: str = "remote:",
    max_concurrent_callbacks: int = 10,
    max_payload_for_high_granularity: int = 65536,
    circuit_breaker_threshold: int = 5,
    circuit_breaker_cooldown: float = 60.0,
) -> "ActingWebApp":
    """Enable automatic subscription processing.

    When enabled, the library automatically handles:
    - Callback sequencing and deduplication
    - Gap detection and resync triggering
    - Data storage in RemotePeerStore (if auto_storage=True)
    - Cleanup when trust is deleted (if auto_cleanup=True)

    Args:
        auto_sequence: Enable CallbackProcessor for sequence handling
        auto_storage: Automatically store received data in RemotePeerStore
        auto_cleanup: Register hook to clean up when trust is deleted
        gap_timeout_seconds: Time before triggering resync on sequence gap
        max_pending: Maximum pending callbacks before back-pressure (429)
        storage_prefix: Bucket prefix for RemotePeerStore
        max_concurrent_callbacks: Max concurrent callback deliveries
        max_payload_for_high_granularity: Payload size before granularity downgrade
        circuit_breaker_threshold: Failures before opening circuit
        circuit_breaker_cooldown: Seconds before testing recovery

    Returns:
        Self for method chaining
    """
    self._subscription_config = SubscriptionProcessingConfig(
        enabled=True,
        auto_sequence=auto_sequence,
        auto_storage=auto_storage,
        auto_cleanup=auto_cleanup,
        gap_timeout_seconds=gap_timeout_seconds,
        max_pending=max_pending,
        storage_prefix=storage_prefix,
        max_concurrent_callbacks=max_concurrent_callbacks,
        max_payload_for_high_granularity=max_payload_for_high_granularity,
        circuit_breaker_threshold=circuit_breaker_threshold,
        circuit_breaker_cooldown=circuit_breaker_cooldown,
    )

    # Register internal callback hook to route through processor
    self._register_internal_subscription_handler()

    # Register cleanup hook if enabled
    if auto_cleanup:
        self._register_cleanup_hook()

    return self

def subscription_data_hook(self, target: str = "*") -> Callable[..., Any]:
    """Decorator to register subscription data hooks.

    Use with .with_subscription_processing() for automatic handling.
    The handler receives already-sequenced, deduplicated data.

    Args:
        target: Target to hook (e.g., "properties", "*" for all)

    Example:
        @app.subscription_data_hook("properties")
        def on_property_change(
            actor: ActorInterface,
            peer_id: str,
            target: str,
            data: dict,
            sequence: int,
            callback_type: str
        ) -> None:
            # Data is already sequenced and stored
            pass
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if target not in self._subscription_data_hooks:
            self._subscription_data_hooks[target] = []
        self._subscription_data_hooks[target].append(func)
        return func
    return decorator

def _register_internal_subscription_handler(self) -> None:
    """Register internal handler for subscription callbacks."""

    @self.callback_hook("subscription")
    def _internal_subscription_handler(
        actor: "ActorInterface",
        name: str,
        data: dict[str, Any]
    ) -> bool:
        """Internal handler that routes through CallbackProcessor."""
        return self._process_subscription_callback(actor, data)

def _process_subscription_callback(
    self,
    actor: "ActorInterface",
    data: dict[str, Any]
) -> bool:
    """Process subscription callback through the automatic pipeline."""
    import asyncio
    from .callback_processor import CallbackProcessor, ProcessResult
    from .remote_storage import RemotePeerStore

    config = self._subscription_config
    if not config.enabled:
        return False

    peer_id = data.get("peerid", "")
    subscription = data.get("subscription", {})
    subscription_id = subscription.get("subscriptionid", "")
    callback_data = data.get("data", {})
    sequence = data.get("sequence", 0)
    callback_type = data.get("type", "diff")
    target = subscription.get("target", "properties")

    async def process():
        # Create processor
        processor = CallbackProcessor(
            actor,
            gap_timeout_seconds=config.gap_timeout_seconds,
            max_pending=config.max_pending,
        )

        # Define handler for processed callbacks
        async def handler(cb):
            # Auto-storage
            if config.auto_storage:
                store = RemotePeerStore(actor, peer_id)
                if cb.callback_type.value == "resync":
                    store.apply_resync_data(cb.data)
                else:
                    store.apply_callback_data(cb.data)

            # Invoke user hooks
            self._invoke_subscription_data_hooks(
                actor=actor,
                peer_id=peer_id,
                target=target,
                data=cb.data,
                sequence=cb.sequence,
                callback_type=cb.callback_type.value,
            )

        # Process through CallbackProcessor
        result = await processor.process_callback(
            peer_id=peer_id,
            subscription_id=subscription_id,
            sequence=sequence,
            data=callback_data,
            callback_type=callback_type,
            handler=handler,
        )

        return result in (ProcessResult.PROCESSED, ProcessResult.DUPLICATE)

    # Run async processing
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, process())
            return future.result()
    except RuntimeError:
        return asyncio.run(process())

def _invoke_subscription_data_hooks(
    self,
    actor: "ActorInterface",
    peer_id: str,
    target: str,
    data: dict[str, Any],
    sequence: int,
    callback_type: str,
) -> None:
    """Invoke registered subscription data hooks."""
    import inspect

    # Invoke target-specific hooks
    if target in self._subscription_data_hooks:
        for hook in self._subscription_data_hooks[target]:
            try:
                if inspect.iscoroutinefunction(hook):
                    import asyncio
                    asyncio.run(hook(actor, peer_id, target, data, sequence, callback_type))
                else:
                    hook(actor, peer_id, target, data, sequence, callback_type)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    f"Error in subscription_data_hook for {target}: {e}"
                )

    # Invoke wildcard hooks
    if "*" in self._subscription_data_hooks:
        for hook in self._subscription_data_hooks["*"]:
            try:
                if inspect.iscoroutinefunction(hook):
                    import asyncio
                    asyncio.run(hook(actor, peer_id, target, data, sequence, callback_type))
                else:
                    hook(actor, peer_id, target, data, sequence, callback_type)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    f"Error in subscription_data_hook wildcard: {e}"
                )

def _register_cleanup_hook(self) -> None:
    """Register hook to clean up when trust is deleted."""

    @self.lifecycle_hook("trust_deleted")
    def _cleanup_peer_data(
        actor: "ActorInterface",
        peer_id: str = "",
        **kwargs
    ) -> None:
        """Clean up remote peer data when trust is deleted."""
        if not peer_id:
            return

        from .remote_storage import RemotePeerStore
        from .callback_processor import CallbackProcessor

        # Clean up stored data
        try:
            store = RemotePeerStore(actor, peer_id, validate_peer_id=False)
            store.delete_all()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Error cleaning up RemotePeerStore for {peer_id}: {e}"
            )

        # Clean up callback state
        try:
            processor = CallbackProcessor(actor)
            processor.clear_all_state_for_peer(peer_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Error cleaning up callback state for {peer_id}: {e}"
            )
```

#### 3. Module Exports
**File**: `actingweb/interface/__init__.py`

Add exports:

```python
from ..callback_processor import CallbackProcessor, ProcessResult, CallbackType
from ..remote_storage import RemotePeerStore, get_remote_bucket
from ..peer_capabilities import PeerCapabilities
from ..fanout import FanOutManager, FanOutResult
from ..subscription_config import SubscriptionProcessingConfig
```

### Success Criteria

#### Automated Verification:
- [x] Type checking passes: `poetry run pyright actingweb/interface/app.py actingweb/subscription_config.py`
- [x] Linting passes: `poetry run ruff check actingweb/`
- [x] Unit tests pass: `poetry run pytest tests/test_subscription_processing.py -v` (27 tests)
  - `.with_subscription_processing()` configuration
  - `@subscription_data_hook` registration and invocation
  - Internal routing through CallbackProcessor
  - Cleanup hook registration
- [ ] Integration tests for full pipeline (test_001-006): Deferred to broader integration test suite
- [x] All existing tests pass: Sequential tests pass (478 passed); parallel tests have known isolation issues

**Phase 5 Status: COMPLETE**

---

## Per-Phase Verification Checklist

Run these commands after completing each phase to ensure quality before proceeding.

### After Phase 0 (Peer Capabilities)

```bash
# Type checking
poetry run pyright actingweb/peer_capabilities.py actingweb/db/dynamodb/trust.py actingweb/db/postgresql/trust.py

# Linting
poetry run ruff check actingweb/peer_capabilities.py actingweb/db/dynamodb/trust.py actingweb/db/postgresql/trust.py
poetry run ruff format actingweb/peer_capabilities.py actingweb/db/dynamodb/trust.py actingweb/db/postgresql/trust.py

# PostgreSQL migration
cd actingweb/db/postgresql/migrations && alembic upgrade head && cd -

# Unit tests
poetry run pytest tests/test_peer_capabilities.py -v

# Existing tests still pass
poetry run pytest tests/test_trust*.py -v
```

### After Phase 1 (Subscription Suspension)

```bash
# Type checking
poetry run pyright actingweb/db/dynamodb/subscription_suspension.py actingweb/db/postgresql/subscription_suspension.py actingweb/interface/subscription_manager.py

# Linting
poetry run ruff check actingweb/db/*/subscription_suspension.py actingweb/interface/subscription_manager.py
poetry run ruff format actingweb/db/*/subscription_suspension.py actingweb/interface/subscription_manager.py

# PostgreSQL migration
cd actingweb/db/postgresql/migrations && alembic upgrade head && cd -

# Unit tests
poetry run pytest tests/test_subscription_suspension.py -v

# Existing tests still pass
poetry run pytest tests/test_subscription*.py -v
```

### After Phase 2 (CallbackProcessor)

```bash
# Type checking
poetry run pyright actingweb/callback_processor.py

# Linting
poetry run ruff check actingweb/callback_processor.py
poetry run ruff format actingweb/callback_processor.py

# Unit tests
poetry run pytest tests/test_callback_processor.py -v
```

### After Phase 3 (RemotePeerStore)

```bash
# Type checking
poetry run pyright actingweb/remote_storage.py

# Linting
poetry run ruff check actingweb/remote_storage.py
poetry run ruff format actingweb/remote_storage.py

# Unit tests
poetry run pytest tests/test_remote_storage.py -v
```

### After Phase 4 (FanOutManager)

```bash
# Type checking
poetry run pyright actingweb/fanout.py

# Linting
poetry run ruff check actingweb/fanout.py
poetry run ruff format actingweb/fanout.py

# Unit tests
poetry run pytest tests/test_fanout.py -v
```

### After Phase 5 (Integration Layer)

```bash
# Type checking for all new files
poetry run pyright actingweb/peer_capabilities.py actingweb/db/*/subscription_suspension.py actingweb/callback_processor.py actingweb/remote_storage.py actingweb/fanout.py actingweb/subscription_config.py actingweb/interface/app.py

# Full linting
poetry run ruff check actingweb/
poetry run ruff format actingweb/

# All unit tests for new components
poetry run pytest tests/test_peer_capabilities.py tests/test_subscription_suspension.py tests/test_callback_processor.py tests/test_remote_storage.py tests/test_fanout.py tests/test_subscription_processing.py -v

# Full integration tests
poetry run pytest tests/integration/test_subscription_processing_flow.py tests/integration/test_fanout_flow.py -v

# All tests (final validation)
make test-all-parallel
```

---

## Testing Strategy

All tests should be automated. Since we run DynamoDB and PostgreSQL locally via Docker and spin up FastAPI test servers, most scenarios can be tested end-to-end without manual intervention.

### Unit Tests

| Component | Test File | Key Test Cases |
| --------- | --------- | -------------- |
| PeerCapabilities | `tests/test_peer_capabilities.py` | Lazy fetch, TTL expiration, supports() methods, refresh() |
| SubscriptionSuspension | `tests/test_subscription_suspension.py` | Suspend/resume state, is_suspended() scoping, resync callback format |
| CallbackProcessor | `tests/test_callback_processor.py` | Sequencing, gaps, duplicates, resync, optimistic locking |
| RemotePeerStore | `tests/test_remote_storage.py` | All 10 list operations, scalar operations, cleanup |
| FanOutManager | `tests/test_fanout.py` | Circuit breaker states, concurrency limits, compression |
| SubscriptionProcessingConfig | `tests/test_subscription_config.py` | Configuration validation, defaults |

### Integration Tests

Integration tests use the existing test infrastructure:
- **Two test servers**: `test_app` (port 5555+offset) and `peer_app` (port 5556+offset)
- **Database backends**: Both DynamoDB and PostgreSQL via `DATABASE_BACKEND` env var
- **Fixtures**: `actor_factory`, `trust_helper`, `http_client`
- **Parallel execution**: Worker-specific DB prefixes and port offsets

#### Test File: `tests/integration/test_subscription_processing_flow.py`

```python
@pytest.mark.xdist_group(name="subscription_processing")
class TestSubscriptionProcessingFlow:
    """
    Sequential test flow for automatic subscription processing.

    Tests the full pipeline: callbacks → CallbackProcessor → RemotePeerStore → hooks
    """

    # Shared state
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None

    trust_secret: str | None = None
    subscription_id: str | None = None
```

#### Test Cases (Automated)

**1. Setup and Basic Flow**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_001_create_publisher_actor` | Create actor on test_app server | Status 201, returns id and passphrase |
| `test_002_create_subscriber_actor` | Create actor on peer_app server with `.with_subscription_processing()` | Status 201, returns id and passphrase |
| `test_003_establish_trust` | Publisher initiates trust to subscriber, both approve | Trust secret returned, both sides approved |
| `test_004_create_subscription` | Subscriber subscribes to publisher's properties | Subscription ID returned |
| `test_005_modify_property_triggers_callback` | Publisher sets property, verify callback received | Callback processed, sequence=1 stored |
| `test_006_verify_data_stored_in_remote_store` | Query subscriber's internal attributes | Data exists in `remote:{publisher_id}` bucket |

**2. Callback Sequencing**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_010_in_order_callbacks_processed` | Send callbacks seq=2,3,4 in order | All processed, last_seq=4 |
| `test_011_duplicate_callback_ignored` | Send callback with seq=3 again | Returns DUPLICATE, state unchanged |
| `test_012_out_of_order_callbacks_reordered` | Send seq=7, then seq=6, then seq=5 | seq=5,6,7 processed in order after seq=5 arrives |
| `test_013_gap_detected_pending_queue` | Send seq=10 (gap from 7) | Returns PENDING, stored in pending queue |
| `test_014_gap_filled_processes_pending` | Send seq=8, then seq=9 | seq=8,9,10 all processed |

**3. Resync Handling**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_020_gap_timeout_triggers_resync` | Send seq=20, wait >5s, send seq=22 | State shows resync_pending=True |
| `test_021_resync_callback_resets_state` | Send type="resync" callback with full data | State reset, new sequence baseline established |
| `test_022_resync_replaces_stored_data` | Verify RemotePeerStore after resync | Old data cleared, new data present |

**4. List Operations**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_030_list_append_operation` | Callback with `operation: "append"` | Item added to end of list |
| `test_031_list_insert_operation` | Callback with `operation: "insert", index: 0` | Item inserted at index 0 |
| `test_032_list_update_operation` | Callback with `operation: "update", index: 1` | Item at index 1 replaced |
| `test_033_list_delete_operation` | Callback with `operation: "delete", index: 0` | Item at index 0 removed |
| `test_034_list_extend_operation` | Callback with `operation: "extend", items: [...]` | Multiple items added |
| `test_035_list_clear_operation` | Callback with `operation: "clear"` | List emptied but exists |
| `test_036_list_delete_all_operation` | Callback with `operation: "delete_all"` | List completely removed |

**5. Back-Pressure**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_040_pending_queue_limit` | Send 100+ out-of-order callbacks | Returns 429 when max_pending exceeded |
| `test_041_back_pressure_response_headers` | Verify 429 response | Contains Retry-After header |

**6. Cleanup on Trust Deletion**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_050_verify_data_exists_before_cleanup` | Query subscriber's remote store | Data exists for publisher |
| `test_051_delete_trust_triggers_cleanup` | Delete trust relationship | Returns 204 |
| `test_052_verify_remote_data_cleaned_up` | Query subscriber's remote store | No data for publisher |
| `test_053_verify_callback_state_cleaned_up` | Query callback state | No state for publisher's subscriptions |

**7. Peer Capabilities**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_060_capabilities_not_cached_initially` | Check trust before capability fetch | aw_supported is null |
| `test_061_capabilities_lazy_loaded` | Access PeerCapabilities.supports() | Fetches from /meta/actingweb/supported |
| `test_062_capabilities_cached_after_fetch` | Check trust after capability access | aw_supported populated |
| `test_063_capabilities_ttl_expiration` | Set capabilities_fetched_at to old date, access | Re-fetches capabilities |

#### Test File: `tests/integration/test_fanout_flow.py`

```python
@pytest.mark.xdist_group(name="fanout")
class TestFanOutFlow:
    """
    Test FanOutManager with multiple subscribers.

    Creates one publisher with multiple subscribers to test parallel delivery.
    """
```

**8. Fan-Out Delivery**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_070_setup_publisher_with_multiple_subscribers` | Create 1 publisher, 5 subscribers with trust | All trusts established |
| `test_071_fanout_delivers_to_all_subscribers` | Modify publisher property | All 5 subscribers receive callback |
| `test_072_fanout_respects_concurrency_limit` | Monitor concurrent requests | Never exceeds max_concurrent (10) |
| `test_073_large_payload_triggers_granularity_downgrade` | Set 100KB property value | Callbacks sent with granularity="low" |
| `test_074_granularity_downgrade_header_present` | Check callback request headers | X-ActingWeb-Granularity-Downgraded: true |
| `test_075_compression_used_when_peer_supports` | Subscriber advertises `callbackcompression`, send large callback | Request has Content-Encoding: gzip |
| `test_076_no_compression_when_peer_unsupported` | Subscriber does NOT advertise `callbackcompression` | Request has no Content-Encoding header |

**9. Circuit Breaker**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_080_circuit_closed_initially` | Check circuit breaker state | State is CLOSED |
| `test_081_failures_increment_counter` | Mock subscriber to return 500, send callbacks | Failure count increases |
| `test_082_circuit_opens_after_threshold` | Send 5 failing callbacks | State changes to OPEN |
| `test_083_circuit_open_skips_delivery` | Try to deliver while open | Returns circuit_open error, no HTTP request |
| `test_084_circuit_half_open_after_cooldown` | Wait 60s (or mock time), try delivery | State is HALF_OPEN, one request allowed |
| `test_085_success_closes_circuit` | Subscriber recovers, callback succeeds | State returns to CLOSED |

#### Test File: `tests/integration/test_protocol_endpoints.py`

**10. Protocol Endpoints**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_090_subscription_stats_endpoint` | GET /{actor_id}/subscriptions/stats | Returns JSON with counts |
| `test_091_subscription_health_endpoint` | GET /{actor_id}/subscriptions/{subid}/health | Returns health status |
| `test_092_batch_subscription_creation` | POST /{actor_id}/subscriptions/batch | Creates multiple subscriptions |

#### Test File: `tests/integration/test_subscription_suspension_flow.py`

**11. Subscription Suspension (Publisher Side)**

| Test | Description | Assertions |
| ---- | ----------- | ---------- |
| `test_100_setup_publisher_subscriber_with_subscription` | Create publisher + subscriber, establish trust and subscription | Subscription active, initial callback received |
| `test_101_suspend_target` | Call `actor.subscriptions.suspend(target="properties")` | Returns True, is_suspended() returns True |
| `test_102_property_change_while_suspended_no_callback` | Modify property while suspended | No diff registered, no callback sent to subscriber |
| `test_103_multiple_changes_while_suspended` | Make 10 property changes while suspended | No callbacks sent, subscriber data unchanged |
| `test_104_resume_sends_resync_callback` | Call `actor.subscriptions.resume(target="properties")` | Returns 1, resync callback sent to subscriber |
| `test_105_resync_callback_format_correct` | Inspect received resync callback | Contains `type: "resync"`, `url` field, incremented sequence |
| `test_106_subscriber_receives_and_handles_resync` | Verify subscriber processed resync | CallbackProcessor handled resync, RemotePeerStore refreshed |
| `test_107_suspend_with_subtarget` | Suspend only `properties/specific_key` | Only that subtarget suspended, others still active |
| `test_108_resume_already_not_suspended` | Call resume() when not suspended | Returns 0, no resync sent |
| `test_109_get_all_suspended` | Suspend multiple targets, call get_all_suspended() | Returns list of all suspended (target, subtarget) pairs |
| `test_110_resync_checks_peer_capability` | Resume with peer that supports `subscriptionresync` | Callback contains `type: "resync"` |
| `test_111_resync_fallback_for_unsupported_peer` | Resume with peer that does NOT support `subscriptionresync` | Callback uses `granularity: "low"`, no `type` field |
| `test_112_mixed_peers_different_callbacks` | Resume with 2 subscribers: one supports resync, one doesn't | Each receives appropriate callback format |

### Test Harness Extension

The existing test harness (`tests/integration/test_harness.py`) needs to be extended to support `.with_subscription_processing()`:

```python
def create_test_app(
    fqdn: str = "localhost:5555",
    proto: str = "http://",
    enable_oauth: bool = False,
    enable_mcp: bool = False,
    enable_devtest: bool = True,
    enable_subscription_processing: bool = False,  # NEW
    subscription_config: dict | None = None,       # NEW
) -> tuple[FastAPI, ActingWebApp]:
    """Create a minimal ActingWeb test harness."""

    aw_app = (
        ActingWebApp(...)
        # ... existing config ...
    )

    # NEW: Enable subscription processing if requested
    if enable_subscription_processing:
        config = subscription_config or {}
        aw_app = aw_app.with_subscription_processing(
            auto_sequence=config.get("auto_sequence", True),
            auto_storage=config.get("auto_storage", True),
            auto_cleanup=config.get("auto_cleanup", True),
            gap_timeout_seconds=config.get("gap_timeout_seconds", 5.0),
            max_pending=config.get("max_pending", 100),
        )

    return fastapi_app, aw_app
```

### New Fixtures

Add to `tests/integration/conftest.py`:

```python
@pytest.fixture(scope="session")
def subscriber_app(docker_services, setup_database, worker_info):
    """
    Start a subscriber test app with subscription processing enabled.

    Uses a different port than test_app and peer_app.
    """
    subscriber_port = BASE_SUBSCRIBER_PORT + worker_info["port_offset"]
    subscriber_url = f"http://{TEST_APP_HOST}:{subscriber_port}"

    fastapi_app, aw_app = create_test_app(
        fqdn=f"{TEST_APP_HOST}:{subscriber_port}",
        proto="http://",
        enable_subscription_processing=True,
        subscription_config={
            "auto_sequence": True,
            "auto_storage": True,
            "auto_cleanup": True,
            "gap_timeout_seconds": 2.0,  # Shorter for testing
            "max_pending": 50,
        }
    )

    # Run in background thread
    thread = Thread(target=lambda: uvicorn.run(fastapi_app, host="0.0.0.0", port=subscriber_port, log_level="error"), daemon=True)
    thread.start()

    # Wait for ready
    _wait_for_server(subscriber_url)

    return subscriber_url


@pytest.fixture
def callback_sender(trust_helper):
    """
    Helper fixture for sending subscription callbacks.

    Handles callback wrapper format per protocol spec.
    """
    class CallbackSender:
        def send(
            self,
            to_actor: dict,
            from_actor_id: str,
            subscription_id: str,
            sequence: int,
            data: dict,
            trust_secret: str,
            callback_type: str = "diff",
        ) -> requests.Response:
            """Send a subscription callback."""
            callback_url = f"{to_actor['url']}/callbacks/subscriptions/{from_actor_id}/{subscription_id}"

            payload = {
                "id": from_actor_id,
                "target": "properties",
                "sequence": sequence,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "granularity": "high",
                "subscriptionid": subscription_id,
                "data": data,
            }

            if callback_type == "resync":
                payload["type"] = "resync"

            return requests.post(
                callback_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {trust_secret}",
                    "Content-Type": "application/json",
                },
            )

        def send_out_of_order(
            self,
            to_actor: dict,
            from_actor_id: str,
            subscription_id: str,
            sequences: list[int],
            trust_secret: str,
        ) -> list[requests.Response]:
            """Send multiple callbacks with specified sequence order."""
            responses = []
            for seq in sequences:
                resp = self.send(
                    to_actor=to_actor,
                    from_actor_id=from_actor_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data={"test_seq": seq},
                    trust_secret=trust_secret,
                )
                responses.append(resp)
            return responses

    return CallbackSender()


@pytest.fixture
def remote_store_verifier():
    """
    Helper fixture for verifying RemotePeerStore contents.
    """
    class RemoteStoreVerifier:
        def get_stored_data(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
        ) -> dict:
            """Get all data stored for a peer in the remote store."""
            # Access internal attributes via devtest endpoint
            bucket = f"remote:{peer_id}"
            response = requests.get(
                f"{actor_url}/devtest/attributes/{bucket}",
                auth=actor_auth,
            )
            if response.status_code == 200:
                return response.json()
            return {}

        def verify_list_exists(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
            list_name: str,
        ) -> bool:
            """Check if a list exists in the remote store."""
            data = self.get_stored_data(actor_url, actor_auth, peer_id)
            return f"list:{list_name}:meta" in data

        def get_callback_state(
            self,
            actor_url: str,
            actor_auth: tuple[str, str],
            peer_id: str,
            subscription_id: str,
        ) -> dict:
            """Get callback processor state for a subscription."""
            bucket = "_callback_state"
            key = f"state:{peer_id}:{subscription_id}"
            response = requests.get(
                f"{actor_url}/devtest/attributes/{bucket}/{key}",
                auth=actor_auth,
            )
            if response.status_code == 200:
                return response.json()
            return {}

    return RemoteStoreVerifier()
```

### Running Integration Tests

```bash
# Run with DynamoDB (default)
make test-integration

# Run with PostgreSQL
DATABASE_BACKEND=postgresql make test-integration

# Run specific test file
poetry run pytest tests/integration/test_subscription_processing_flow.py -v

# Run with parallel execution
make test-parallel

# Run all tests (unit + integration)
make test-all-parallel
```

### Test Coverage Requirements

| Component | Minimum Coverage | Notes |
| --------- | ---------------- | ----- |
| `peer_capabilities.py` | 90% | Critical for feature detection |
| `db/*/subscription_suspension.py` | 90% | Publisher-side suspension state |
| `callback_processor.py` | 95% | Core sequencing logic |
| `remote_storage.py` | 90% | All list operations |
| `fanout.py` | 85% | Circuit breaker edge cases |
| `subscription_config.py` | 80% | Simple dataclass |
| Integration tests | N/A | Must pass on both DynamoDB and PostgreSQL |

---

## Performance Considerations

1. **Lazy capability fetch**: Don't block trust establishment; fetch on first access
2. **Bounded concurrency**: FanOutManager limits concurrent HTTP requests
3. **Circuit breakers**: Prevent cascade failures from slow/failing peers
4. **Optimistic locking**: Efficient concurrent access without distributed locks
5. **Compression**: Reduce bandwidth for large payloads when supported

---

## Capability Checking Requirements

Per the ActingWeb protocol spec, optional features MUST check peer capabilities before use. The following table documents which features require capability checks:

| Feature | Option Tag | Check Method | Fallback Behavior |
|---------|------------|--------------|-------------------|
| **Resync callbacks** | `subscriptionresync` | `caps.supports_resync_callbacks()` | Send low-granularity callback with URL |
| **Callback compression** | `callbackcompression` | `caps.supports_compression()` | Send uncompressed |
| **Batch subscription creation** | `subscriptionbatch` | `caps.supports_batch_subscriptions()` | Create subscriptions individually |
| **Subscription health endpoint** | `subscriptionhealth` | `caps.supports_health_endpoint()` | Skip health checks |
| **Subscription stats endpoint** | `subscriptionstats` | `caps.supports_stats_endpoint()` | Skip stats collection |

### Implementation Checklist

When using optional features, always follow this pattern:

```python
from .peer_capabilities import PeerCapabilities

caps = PeerCapabilities(actor, peer_id)

# Check before using optional feature
if caps.supports_resync_callbacks():
    # Use resync callback format
    payload["type"] = "resync"
else:
    # Fallback to standard format
    payload["granularity"] = "low"
```

### Where Capability Checks Are Required

| Component | Location | Feature | Status |
|-----------|----------|---------|--------|
| `actor.py` | `_callback_subscription_resync()` | Resync callbacks | ✅ Implemented |
| `fanout.py` | `_deliver_single()` | Compression | ✅ Implemented |
| Future | Batch subscription helper | Batch creation | Not yet needed |
| Future | Health monitoring | Health endpoint | Not yet needed |
| Future | Stats collection | Stats endpoint | Not yet needed |

---

## Migration Notes

### For Existing Applications

Applications using raw `@callback_hook("subscription")` continue to work unchanged. To migrate:

1. Add `.with_subscription_processing()` to app configuration
2. Replace `@callback_hook("subscription")` with `@subscription_data_hook`
3. Remove manual sequencing/storage code
4. Remove manual cleanup hooks (auto_cleanup handles this)

### Database Migration

1. Run PostgreSQL migration: `alembic upgrade head`
2. DynamoDB: No migration needed (schemaless)
3. Existing trusts will have null capability fields (lazy populated on access)

---

## References

- Research document: `thoughts/shared/research/2026-01-18-library-extraction-candidates-from-actingweb-mcp.md`
- Subscription suspension design: `thoughts/shared/plans/TODO-2026-01-15-subscription-suspension-resync.md` (integrated into Phase 1)
- ActingWeb protocol spec v1.4: `docs/protocol/actingweb-spec.rst`
- Existing hook system: `actingweb/interface/hooks.py`
- Existing subscription handling: `actingweb/handlers/callbacks.py`
