---
date: 2026-01-18T12:00:00Z
researcher: Claude
git_commit: 5a081b9cc54bf4090cbb94fb11d114b33669d677
branch: master
repository: actingweb
reference_app: actingweb_mcp
topic: "Library Extraction Candidates from actingweb_mcp Reference Implementation"
tags: [research, library-design, extraction, patterns, distributed-systems, peer-sync, protocol-design]
status: revised
last_updated: 2026-01-20
last_updated_by: Claude
revision_history:
  - date: 2026-01-18
    author: Claude
    summary: Initial research and candidate identification
  - date: 2026-01-20
    author: Claude
    summary: Added critical analysis, scalability concerns, and protocol improvement recommendations
  - date: 2026-01-20
    author: Claude
    summary: Protocol improvements incorporated into spec v1.4; clarified protocol vs library separation
  - date: 2026-01-20
    author: Claude
    summary: Added Part 5 with resolved design decisions; fixed coherence issues (API duplication, priority labels, orphaned references)
  - date: 2026-01-20
    author: Claude
    summary: Added Developer API section with three usage levels (Automatic, Component-Level, Raw); added Integration Layer to implementation phases
  - date: 2026-01-20
    author: Claude
    summary: Added list operation handling to RemotePeerStore; added actingweb_mcp real-world example showing ~500 to ~30 line reduction
  - date: 2026-01-20
    author: Claude
    summary: Protocol engineering review; added wire protocol alignment notes to CallbackProcessor and FanOutManager; added Appendix A with verification
---

# Research: Library Extraction Candidates from actingweb_mcp Reference Implementation

**Date**: 2026-01-18T12:00:00Z (revised 2026-01-20)
**Researcher**: Claude
**Git Commit**: 5a081b9cc54bf4090cbb94fb11d114b33669d677
**Branch**: master
**Repository**: actingweb
**Reference Application**: actingweb_mcp

## Research Question

What functionality in actingweb_mcp represents generic patterns that should be extracted into the actingweb library to benefit all ActingWeb application developers?

## Executive Summary

After thorough analysis of the actingweb_mcp codebase (~6,000 lines across hooks, helpers, and repositories), I identified **10 candidates** for extraction. Critical review led to **protocol improvements** (now incorporated into spec v1.4) and **library implementation patterns** (detailed below).

### Protocol vs Library Separation

**Key Principle**: The ActingWeb protocol spec defines the **wire format** (endpoints, request/response shapes, semantics). The actingweb library implements **robust handling** of the protocol (storage, algorithms, error recovery). Storage patterns like "store remote data in attributes" are library implementation details, NOT protocol concerns.

| Concern | Where It Belongs | Examples |
|---------|-----------------|----------|
| **Protocol** | `docs/protocol/actingweb-spec.rst` | Callback format, granularity options, 429/503 responses, endpoint URLs |
| **Library** | `actingweb/` Python code | Callback state storage, pending queue algorithms, attribute bucket naming |

### Key Findings

1. **Protocol improvements incorporated into spec v1.4**: Granularity guidelines, delivery semantics, payload limits, back-pressure, batch subscriptions, health endpoints, compression
2. **Library extraction candidates refined**: Focus on implementation patterns, not protocol features
3. **Scalability concerns addressed**: Protocol now supports granularity downgrade, back-pressure; library implements the mechanisms

### Revised Library Extraction Recommendations

| Priority | Candidate | Scope | Notes |
|----------|-----------|-------|-------|
| **CRITICAL** | Peer Capability Discovery | Query peer's `aw_supported` options | **PREREQUISITE** for using optional features |
| **CRITICAL** | Integration Layer | `.with_subscription_processing()` + `@subscription_data_hook` | Enables "just works" subscription support |
| HIGH | Callback Processor | Sequencing, dedup, resync handling | Implements protocol's sequence/resync semantics |
| HIGH | Remote Peer Storage | Attribute-based storage for peer data | Library pattern, NOT in protocol |
| HIGH | Fan-Out Manager | Parallel delivery, circuit breakers | Implements protocol's back-pressure responses |
| MEDIUM | Peer Metadata Utilities | Profile caching, existence checks | Convenience utilities |
| LOW | Permission Cache | Grant/revoke caching | App-specific but useful pattern |

**Developer Experience Goal**: With the Integration Layer, apps can get full subscription support by:
1. Calling `.with_subscription_processing()` on `ActingWebApp`
2. Registering a `@subscription_data_hook` handler
3. Using existing trust and subscription APIs

Advanced users retain full control via raw `@callback_hook("subscription")` or component-level usage.

---

## Part 1: Original Extraction Candidates

### Candidate 1: Distributed Callback Sequencing (HIGH PRIORITY - NEEDS REVISION)

**Source**: `actingweb_mcp/hooks/actingweb/callback_hooks.py` (lines 1-250)

**Problem it solves**: In serverless environments (AWS Lambda, Google Cloud Functions), subscription callbacks may arrive out-of-order due to concurrent function executions. Without proper sequencing, data corruption or loss can occur.

**Current implementation**:
```text
Algorithm (Hybrid approach):
1. Callback arrives with seq=N
2. Read callback_state from persistent storage
3. If N <= last_processed_seq → duplicate, skip
4. If N == last_processed_seq + 1 → apply, process any pending in order
5. If N > last_processed_seq + 1 (gap):
   - Store in pending_callbacks with timestamp
   - If oldest_pending > timeout → trigger full resync
   - Otherwise, store and return (future callback will process)
```

**Key components to extract**:

| Component | Lines | Description |
|-----------|-------|-------------|
| `_atomic_update_callback_state()` | ~60 | Optimistic locking with version-based conflict detection |
| Pending callback queue | ~80 | Timestamped storage and retrieval |
| Resync trigger logic | ~40 | Timeout detection and baseline establishment |
| Post-resync handling | ~30 | Marker state (-1) for accepting new baseline |

**Rationale for extraction**:
- This is a **fundamental distributed systems problem**, not specific to memory apps
- Any ActingWeb app using subscriptions in serverless faces this exact challenge
- The algorithm is well-documented and battle-tested
- Currently forces every app developer to solve the same problem independently

**Complexity assessment**: MEDIUM → **REVISED: HIGH**
- Requires careful handling of edge cases (concurrent writes, version conflicts)
- Needs configurable timeout (currently 5 seconds via environment variable)
- Must handle the post-resync baseline establishment correctly
- **NEW**: Must integrate with protocol's `type: "resync"` callbacks
- **NEW**: Must handle granularity differences (high vs low)

**Value assessment**: HIGH

**CRITICAL ISSUES IDENTIFIED** (see Part 2 for details):
- Does not account for `granularity` setting
- Assumes full data in callbacks (breaks with `granularity="low"`)
- Does not integrate with protocol's `subscriptionresync` option
- 5-second timeout is arbitrary and not configurable per-subscription

**Revised suggested library API** (Initial proposal - see Part 4 Component 1 for refined API):
```python
# actingweb/subscription_processing.py

from enum import Enum
from typing import Protocol, Callable, Awaitable

class CallbackType(Enum):
    DIFF = "diff"
    RESYNC = "resync"

class ProcessResult(Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    PENDING = "pending"
    RESYNC_REQUIRED = "resync_required"

class InboundCallback:
    """Represents a received subscription callback."""
    peer_id: str
    subscription_id: str
    sequence: int
    granularity: str  # "high", "low", "none"
    callback_type: CallbackType  # "diff" or "resync"
    data: dict | None  # Present for granularity="high"
    url: str | None    # Present for granularity="low" or type="resync"
    timestamp: str

class CallbackProcessor:
    """Handles subscription callbacks with sequencing, deduplication, and resync."""

    def __init__(
        self,
        state_store: CallbackStateStore,
        default_timeout_seconds: int = 5,
        max_pending_callbacks: int = 100,  # Back-pressure limit
        max_retries: int = 3
    ):
        pass

    async def process_callback(
        self,
        callback: InboundCallback,
        handler: Callable[[InboundCallback], Awaitable[None]],
        fetch_data: Callable[[str], Awaitable[dict]] | None = None,  # For granularity="low"
    ) -> ProcessResult:
        """
        Process a callback with automatic sequencing.

        Args:
            callback: The inbound callback to process
            handler: Application handler to invoke for valid callbacks
            fetch_data: Optional fetcher for granularity="low" (fetches from URL)

        Returns:
            ProcessResult indicating what happened

        Raises:
            ResyncRequired: When gap timeout exceeded, includes resync URL
            BackPressureExceeded: When pending queue is full
        """

    async def handle_resync_callback(
        self,
        callback: InboundCallback,
        resync_handler: Callable[[str, dict], Awaitable[None]]
    ) -> None:
        """
        Handle a type="resync" callback from the protocol.

        Fetches full state from callback.url and invokes resync_handler.
        Resets sequence tracking after successful resync.
        """

    def configure_subscription(
        self,
        peer_id: str,
        subscription_id: str,
        timeout_seconds: int | None = None,
        max_pending: int | None = None
    ) -> None:
        """Configure per-subscription settings."""


class CallbackStateStore(Protocol):
    """Protocol for callback state persistence."""

    async def get_state(self, peer_id: str, subscription_id: str) -> dict | None: ...
    async def set_state(self, peer_id: str, subscription_id: str, state: dict, expected_version: int | None = None) -> bool: ...
    async def get_pending(self, peer_id: str, subscription_id: str) -> list[dict]: ...
    async def add_pending(self, peer_id: str, subscription_id: str, callback: dict) -> bool: ...
    async def remove_pending(self, peer_id: str, subscription_id: str, sequence: int) -> None: ...
    async def clear_pending(self, peer_id: str, subscription_id: str) -> None: ...
```

---

### Candidate 2: Remote Peer Storage Abstraction (HIGH PRIORITY)

**Source**: `actingweb_mcp/repositories/remote_attribute_store.py` (~575 lines)

**Problem it solves**: When synchronizing data from peer actors, applications need a consistent way to store that data locally without exposing it via HTTP. This requires:
- Bucket-per-peer organization
- Distinction between list and scalar data
- Cleanup when trust relationships end

**Current implementation**:
- Uses bucket pattern: `remote:{peer_id}`
- Wraps `AttributeListStore` for list data (lazily loaded)
- Wraps `Attributes` for scalar data
- All data stored in internal attributes (not HTTP-exposed)

**Key components to extract**:

| Component | Description |
|-----------|-------------|
| Bucket naming | `get_remote_bucket(peer_id)` → `remote:{peer_id}` |
| List store wrapper | Lazy-loaded `AttributeListStore` access |
| Scalar attribute wrapper | `Attributes` access for single values |
| Cleanup operations | `delete_all()` for removing all peer data |

**Rationale for extraction**:
- **Every app that syncs peer data needs this pattern**
- Clean separation between internal and HTTP-exposed data
- Reduces boilerplate significantly
- Consistent cleanup semantics across apps

**Complexity assessment**: LOW
**Value assessment**: HIGH

**Minor issues identified**:
- Bucket naming `remote:{peer_id}` assumes peer IDs don't contain colons
- No validation of peer ID format
- Should document storage growth patterns

**Actor ID Format** (verified from spec and implementation):

The ActingWeb spec (lines 544-546) states:
> The id MUST be globally unique. It is RECOMMENDED that a version 5 (SHA-1) UUID
> (RFC 4122) is used with the base URI of the location of actor as name input.

The actingweb library implementation (`config.py:305-306`) uses:
```python
def new_uuid(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, str(seed)).hex  # 32 lowercase hex chars
```

**Key points**:
- Spec says RECOMMENDED (not MUST), so other formats are technically valid
- The actingweb library uses UUID v5 `.hex` format: **32 lowercase hex characters (no hyphens)**
- Other implementations might use standard UUID format (36 chars with hyphens) or UUID v4
- Validation should be configurable or clearly documented as implementation-specific

**Suggested library API** (updated with configurable validation):
```python
# actingweb/remote_storage.py

import re
from typing import Pattern

# Default pattern matches actingweb library's UUID v5 .hex format
# Other implementations might use different formats (e.g., UUID with hyphens)
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

    Note:
        The default pattern matches the actingweb library's UUID v5 .hex format
        (32 lowercase hex characters). The spec only RECOMMENDS this format,
        so other ActingWeb implementations may use different ID formats.
    """
    if validate:
        pat = pattern or DEFAULT_PEER_ID_PATTERN
        if not pat.match(peer_id):
            raise ValueError(
                f"Invalid peer_id format: {peer_id}. "
                f"Expected pattern: {pat.pattern}"
            )
    return f"remote:{peer_id}"


class RemotePeerStore:
    """Storage abstraction for remote peer data.

    Provides a clean interface for storing data received from peer actors
    in internal attributes (not exposed via HTTP).

    Storage characteristics:
    - Each peer gets isolated storage in bucket "remote:{peer_id}"
    - Lists use AttributeListStore (efficient for append/update operations)
    - Scalars use Attributes (simple key-value)
    - All data is internal (not exposed via /properties HTTP endpoint)

    Scaling considerations:
    - Storage grows linearly with number of peers
    - Each peer's data is independent (no cross-peer queries)
    - Call delete_all() when trust relationship ends to reclaim storage
    """

    def __init__(self, actor: ActorInterface, peer_id: str):
        self.actor = actor
        self.peer_id = peer_id
        self.bucket = get_remote_bucket(peer_id)

    # List operations
    def get_list(self, name: str) -> list[dict]: ...
    def set_list(self, name: str, items: list[dict], metadata: dict | None = None) -> None: ...
    def delete_list(self, name: str) -> None: ...
    def list_all_lists(self, prefix: str | None = None) -> list[str]: ...

    # Scalar operations
    def get_value(self, name: str) -> dict | None: ...
    def set_value(self, name: str, value: dict) -> None: ...
    def delete_value(self, name: str) -> None: ...

    # Cleanup
    def delete_all(self) -> None:
        """Delete all data for this peer (call when trust ends)."""

    # Storage metrics (new)
    def get_storage_stats(self) -> dict:
        """Get storage statistics for this peer.

        Returns:
            Dict with keys: list_count, scalar_count, estimated_bytes
        """
```

---

### Candidate 3: Peer Metadata Utilities (MEDIUM PRIORITY)

**Source**:
- `actingweb_mcp/hooks/actingweb/trust.py` (profile fetching)
- `actingweb_mcp/helpers/trust_utils.py` (connection search)

**Problem it solves**: Applications working with peer actors commonly need to:
1. Fetch and cache peer metadata (displayname, email, etc.)
2. Verify whether a peer actor still exists
3. Search through trust relationships by keywords

**Current implementations**:

**Profile Fetching** (~100 lines):
- Fetches peer properties via HTTP
- Handles 403/404 gracefully (not all peers expose profile)
- Caches results to prevent repeated failed fetches
- Provides both sync and async variants

**Existence Verification** (~30 lines):
- Uses `/meta` endpoint to check if peer exists
- Distinguishes "deleted actor" (404) from "access revoked" (403)
- Important for cleanup decisions

**Connection Search** (~50 lines):
- Searches trust relationships by keywords
- Case-insensitive matching across fields
- Matches: description, displayname, email, peer_identifier, client_name, peerid
- Requires ALL keywords to match (AND logic)

**Rationale for extraction**:
- **Common patterns** across any multi-peer application
- Graceful error handling is subtle and easy to get wrong
- Profile caching prevents unnecessary HTTP calls
- Search functionality needed for any peer management UI

**Complexity assessment**: LOW
**Value assessment**: MEDIUM

**Suggested library API**:
```python
# actingweb/peer_utils.py

class PeerMetadataFetcher:
    """Fetches and caches metadata from peer actors."""

    def __init__(self, properties: list[str] = ['displayname', 'email']):
        """
        Args:
            properties: List of property names to fetch from peers
        """

    async def fetch_async(
        self,
        actor: ActorInterface,
        peer_id: str,
        force_refresh: bool = False
    ) -> dict:
        """Fetch peer metadata, using cache if available."""

    def fetch(self, actor: ActorInterface, peer_id: str) -> dict:
        """Synchronous wrapper around fetch_async."""

    def get_cached(self, actor: ActorInterface, peer_id: str) -> dict | None:
        """Get cached metadata without making HTTP request."""


async def verify_peer_exists(actor: ActorInterface, peer_id: str) -> tuple[bool, str]:
    """Check if a peer actor still exists.

    Returns:
        Tuple of (exists: bool, reason: str)
        - (True, "exists") - Peer is accessible
        - (False, "deleted") - Peer actor was deleted (404)
        - (False, "revoked") - Access was revoked (403)
    """


def find_matching_connections(
    actor: ActorInterface,
    keywords: str | list[str],
    include_cached_metadata: bool = True
) -> list[str]:
    """Search trust relationships by keywords.

    Searches across: description, displayname, email,
    peer_identifier, client_name, peerid

    All keywords must match (AND logic), case-insensitive.

    Returns:
        List of matching peer IDs
    """
```

---

### Candidates 4-7: Lower Priority (Deprioritized)

The following candidates were identified but deprioritized in favor of the core subscription/callback functionality:

- **Candidate 4**: Permission Cache Framework (MEDIUM) - Caches grant/revoke decisions for repeated permission checks. Useful but app-specific.
- **Candidate 5**: Property List Accessor (LOW) - Simplified access to list properties. Already well-supported by existing `AttributeListStore`.
- **Candidate 6**: Property Access Control Hooks (LOW) - Fine-grained property-level access control. Most apps use trust-level permissions.
- **Candidate 7**: ID Generator (VERY LOW) - Centralized ID generation. Current `config.new_uuid()` is sufficient.

These may be reconsidered after the core subscription handling components are implemented.

---

## Part 2: Critical Analysis - Issues and Gaps

### Issue 1: Ignoring Granularity Options for Large Properties (CRITICAL)

**The Problem**: The protocol spec defines three granularity levels:
- **high**: Full data payload in callback
- **low**: URL only, peer must GET data separately
- **none**: No callbacks, polling only

The proposal's `CallbackSequencer` assumes `granularity="high"` with full data payloads. This is **problematic for properties that can be hundreds of KB**.

**From the spec** (line 2176-2183):
> The "granularity" attribute controls how the subscribing actor wants to be notified. "high" sends a callback with full application/json body, "low" sends a notification with a URL where the full body can be retrieved...

**What's missing**: The library should:
1. Support `granularity="low"` as the recommended default for large properties
2. Implement automatic granularity switching based on payload size
3. Consider a configurable `max_high_granularity_size` threshold (e.g., 64KB)

**Recommendation**: Add `GranularityManager` component:
```python
class GranularityManager:
    """Manages granularity decisions for subscriptions."""

    def __init__(
        self,
        max_high_granularity_bytes: int = 65536,  # 64KB
        max_subscribers_for_high: int = 10
    ):
        pass

    def recommend_granularity(
        self,
        payload_size: int,
        subscriber_count: int
    ) -> str:
        """Recommend granularity based on payload and subscriber count."""
```

---

### Issue 2: Fan-Out Scalability with Hundreds of Subscribers (CRITICAL)

**The Problem**: With "hundreds of subscribers", the current implementation has critical scalability issues.

**From actingweb `actor.py:1941-2106`**:
```python
for sub in subs:
    # ... sequential processing
    self.callback_subscription(...)  # Called for EACH subscriber
```

Callbacks are sent **sequentially**. With 200 subscribers and 100KB payloads:
- **20MB total data transferred** per property change
- **Sequential network I/O** blocks the caller
- **No backpressure** - can overwhelm downstream peers

**What's missing from the proposal**:
1. No discussion of fan-out batching strategies
2. No consideration of parallel callback delivery
3. No mention of `granularity="low"` to reduce bandwidth
4. No rate limiting or circuit breaker patterns

**Recommendation**: Add `FanOutManager` component:
```python
class FanOutManager:
    """Manages callback delivery to multiple subscribers at scale."""

    def __init__(
        self,
        max_concurrent_callbacks: int = 10,
        max_payload_bytes_per_second: int = 1_000_000,  # 1MB/s
        circuit_breaker_threshold: int = 5  # failures before circuit opens
    ):
        pass

    async def deliver_to_subscribers(
        self,
        subscribers: list[Subscription],
        payload: dict,
        payload_size: int
    ) -> FanOutResult:
        """
        Deliver callbacks with:
        - Bounded concurrency
        - Rate limiting
        - Circuit breaker per peer
        - Automatic granularity downgrade for large payloads
        """
```

---

### Issue 3: Properties vs List Properties - Critical Distinction (HIGH)

**The Problem**: The research conflates regular properties and list properties, but they have **fundamentally different callback semantics**.

**Regular Properties** (spec line 788-822):
- Callbacks contain the **entire new value**
- No incremental updates
- Size scales with property value

**List Properties** (spec line 2417-2500):
- Callbacks contain **structured diffs**: operation, item, index
- Support incremental operations: append, insert, update, delete, extend
- Size scales with **change delta**, not total list size

**From spec (line 2427-2449)**:
```
List property diff payload MUST include:
- list: property name
- operation: append|insert|update|delete|pop|extend|clear|remove|delete_all
- length: current length after operation
- item/items: affected data
- index: affected position
```

**What's missing**:
1. The `CallbackSequencer` doesn't distinguish between property types
2. No consideration that list property callbacks are already incremental
3. The `RemotePeerStore` conflates lists and scalars

**Recommendation**: Separate handling for:
- **Scalar properties**: Consider `granularity="low"` for large values
- **List properties**: Already efficient with incremental diffs, prefer `granularity="high"`

---

### Issue 4: Protocol's Resync Mechanism Not Integrated (MEDIUM)

**The Problem**: The protocol spec v1.4 added `subscriptionresync` with `type: "resync"` callbacks (spec lines 2673-2711). The proposal's custom resync logic **duplicates and potentially conflicts** with this protocol feature.

**From spec (line 2684-2698)**:
```json
{
  "type": "resync",
  "url": "https://example.com/actor123/properties/memory_travel"
}
```

**Protocol behavior**:
1. Sender decides when resync is needed (e.g., after bulk operations)
2. Sends `type: "resync"` callback with URL
3. Receiver does full GET, discards cached state

**Proposal's approach**:
1. Receiver detects sequence gaps (5-second timeout)
2. Receiver triggers resync by fetching subscription diffs or full properties
3. Different mechanism, different triggers

**Conflict**: The proposal implements a receiver-side resync triggered by sequence gaps, while the protocol has a sender-side resync triggered by the data owner. **These should be complementary, not separate**.

**Recommendation**:
1. Support the protocol's `type: "resync"` callbacks as primary mechanism
2. Use proposal's gap detection as a **fallback** when sender doesn't use resync callbacks
3. Allow configurable behavior for how to handle `type: "resync"` vs gap detection

---

### Issue 5: Callback State Storage Overhead (MEDIUM)

**The Problem**: The proposal stores callback state and pending callbacks per (peer_id, subscription_id) combination.

**With 100 peers, each with 5 subscriptions**:
- 500 callback_state records
- 500 pending_callbacks lists
- All in the `remote:{peer_id}` bucket

**What's missing**:
1. No analysis of storage growth patterns
2. No garbage collection for stale pending callbacks
3. No consideration of DynamoDB's 400KB item limit

**Recommendation**:
- Add TTL-based cleanup for pending callbacks
- Consider separate storage for callback state (not in attribute buckets)
- Document storage requirements and scaling characteristics

---

### Issue 6: Arbitrary Timeout Configuration (LOW)

**The Problem**: The hardcoded 5-second gap timeout is:
1. Too aggressive for slow networks or high-latency deployments
2. Too slow for real-time applications
3. Not tunable per-subscription or per-peer

**Recommendation**:
- Make timeout configurable per-subscription (with global default)
- Consider adaptive timeout based on callback frequency
- Add exponential backoff before triggering resync

---

### Issue 7: Callback Acknowledgment Race Condition (MEDIUM)

**The Problem**: The protocol spec is clear about callback acknowledgment (spec line 2593-2601):

> Any 2xx response from the actor will indicate that the update has been received, and it MUST be cleared.

**The proposal's `CallbackSequencer`**:
- Returns `should_process()` BEFORE processing
- Has `mark_processed()` AFTER processing
- But what if processing fails between these calls?

**Recommendation**:
- Implement transactional processing pattern
- Consider a `process_callback(callback, handler)` approach that handles state atomically

---

### Issue 8: No Back-Pressure Mechanism (HIGH)

**The Problem**: Distributed systems need back-pressure when receivers can't keep up.

**Scenario**:
- Peer A sends 1000 rapid callbacks
- Lambda instances spin up to handle them
- Out-of-order processing causes massive pending queue
- Resync triggered repeatedly
- System degrades into constant resync loops

**Recommendation**:
- Add max pending callbacks limit (reject if exceeded, rely on polling)
- Implement adaptive rate limiting
- Consider using `granularity="none"` as degraded mode

---

### Issue Summary Table

| Issue | Severity | Resolution |
|-------|----------|------------|
| 1. Ignoring granularity for large properties | **CRITICAL** | ✅ **Protocol**: Granularity guidelines added to spec v1.4 |
| 2. Sequential fan-out scalability | **CRITICAL** | 📚 **Library**: FanOutManager with parallel delivery |
| 3. Properties vs list properties conflation | **HIGH** | 📚 **Library**: CallbackProcessor handles both types |
| 4. Resync mechanism duplication | **MEDIUM** | ✅ **Protocol**: Library should use protocol's `type: "resync"` |
| 5. Storage overhead | **MEDIUM** | 📚 **Library**: Document patterns, add TTL cleanup |
| 6. Arbitrary timeout | **LOW** | 📚 **Library**: Make configurable per-subscription |
| 7. Callback acknowledgment race | **MEDIUM** | 📚 **Library**: Transactional processing pattern |
| 8. No back-pressure | **HIGH** | ✅ **Protocol**: 429/503 handling added to spec v1.4 |

**Legend**: ✅ Protocol = addressed in spec v1.4 | 📚 Library = implementation detail

---

## Part 3: Protocol Improvements (Now in Spec v1.4)

The following protocol improvements identified during this research have been **incorporated into ActingWeb Specification v1.4**. See `docs/protocol/actingweb-spec.rst` for full details.

### Summary of Protocol Additions

| Feature | Spec Section | Option Tag |
|---------|--------------|------------|
| Granularity Selection Guidelines | Subscriptions | - |
| Callback Delivery Semantics | Subscriptions | - |
| Callback Payload Limits (256KB recommended) | Subscriptions | - |
| Callback Back-Pressure (429/503) | Subscriptions | - |
| Callback Compression | Subscriptions | `callbackcompression` |
| Batch Subscription Creation | Subscriptions | `subscriptionbatch` |
| Subscription Statistics Endpoint | Subscriptions | `subscriptionstats` |
| Subscription Health Endpoint | Subscriptions | `subscriptionhealth` |
| Subscription Scope and Overlap | Subscriptions | - |

### What Stays in the Protocol

The protocol defines **wire-level concerns**:
- Callback JSON format and required fields
- HTTP endpoints and their request/response shapes
- Granularity options (`high`, `low`, `none`) and their semantics
- Back-pressure response codes (429, 503) and headers
- Sequence numbering requirements
- Resync callback format (`type: "resync"`)

### What Stays OUT of the Protocol (Library Implementation)

The following are **implementation details** that belong in the actingweb library, NOT the protocol spec:

| Implementation Detail | Why NOT Protocol |
|----------------------|------------------|
| Storing remote peer data in attributes | Storage mechanism is library-specific |
| Bucket naming pattern (`remote:{peer_id}`) | Internal organization, not visible on wire |
| Callback state persistence format | How library tracks state internally |
| Pending callback queue algorithm | Implementation of sequence gap handling |
| Optimistic locking with version numbers | Concurrency control is internal |
| Circuit breaker state machine | How library implements back-pressure |
| Attribute-based metadata caching | Storage optimization, not protocol |

**Rationale**: The protocol should be implementable in any language/framework. Storage details like "use DynamoDB attributes" or "bucket naming conventions" would couple the protocol to specific implementations.

---

## Part 4: Library Implementation Recommendations

The actingweb library should provide robust implementations of the protocol's subscription and callback mechanisms. The following components implement protocol features using library-specific storage and algorithms.

### Component 1: CallbackProcessor (HIGH PRIORITY)

**Purpose**: Implement the protocol's callback handling with proper sequencing, deduplication, and resync support.

**Protocol features it implements**:
- Sequence number tracking (protocol requires monotonic sequence, starting at 1)
- `type: "resync"` callback handling (protocol v1.4) - NOTE: `type` field may be absent for normal diffs (backward compatible, defaults to `"diff"`)
- Granularity handling (`high` with `data` field, `low` with `url` field)
- Back-pressure responses (429/503 per protocol v1.4)

**Wire protocol alignment notes**:

1. **Callback structure**: Callbacks arrive with wrapper containing `id`, `target`, `sequence`, `timestamp`, `granularity`, `subscriptionid`, and `data` (or `url` for low granularity). The diff content is in `callback["data"]`, not at the top level.

2. **Type field handling**: The `type` field is OPTIONAL and defaults to `"diff"` when absent:
   ```python
   callback_type = callback.get("type", "diff")  # Backward compatible
   ```

3. **HTTP response codes for back-pressure**:
   - Return `429 Too Many Requests` with `Retry-After` header when pending queue is full
   - Return `503 Service Unavailable` when circuit breaker is open

**Library-specific implementation details** (NOT in protocol):
- Callback state stored in actor attributes
- Pending callback queue using `AttributeListStore`
- Optimistic locking with version field for concurrent Lambda handling
- Configurable gap timeout (default 5 seconds)

```python
# actingweb/callback_processor.py

class CallbackProcessor:
    """
    Processes inbound subscription callbacks per ActingWeb protocol v1.4.

    Handles:
    - Sequence tracking and gap detection
    - Duplicate filtering
    - Resync callback processing
    - Granularity-aware data handling

    Storage: Uses actor's internal attributes (implementation detail).
    """

    def __init__(
        self,
        actor: ActorInterface,
        gap_timeout_seconds: float = 5.0,
        max_pending: int = 100
    ):
        """
        Args:
            actor: The actor receiving callbacks
            gap_timeout_seconds: Time before triggering resync on sequence gap
            max_pending: Max pending callbacks before rejecting (back-pressure)
        """
```

### Component 2: RemotePeerStore (HIGH PRIORITY)

**Purpose**: Store data received from peer actors in a structured way.

**Why this is library-only** (NOT protocol):
- The protocol defines how data is *transmitted* (callbacks, GET responses)
- The protocol does NOT define how receivers *store* that data
- Storage in attributes with bucket naming is an actingweb library pattern

**Implementation**:
- Bucket pattern: `remote:{peer_id}` for isolation
- Lists stored via `AttributeListStore`
- Scalars stored via `Attributes`
- **List operation handling** for incremental updates (see below)
- Automatic cleanup when trust relationship ends

**List Property Operations** (required for `auto_storage=True`):

When a subscription callback contains list operations, `RemotePeerStore` must apply them correctly:

```python
# Callback data format for list operations:
{
    "list:memory_personal": {
        "list": "memory_personal",
        "operation": "append",    # or update, insert, extend, delete, pop, clear, delete_all
        "item": {...},            # for append, update, insert
        "items": [...],           # for extend
        "index": 5,               # for update, insert, delete, pop
        "length": 10              # informational
    }
}
```

**Supported operations**:

| Operation | Parameters | Action |
| --------- | ---------- | ------ |
| `append` | `item` | Add item to end of list |
| `insert` | `item`, `index` | Insert item at index |
| `update` | `item`, `index` | Replace item at index |
| `extend` | `items` | Add multiple items to end |
| `delete` | `index` | Remove item at index |
| `pop` | `index` | Remove and return item at index |
| `clear` | - | Remove all items |
| `delete_all` | - | Delete the entire list |
| `metadata` | - | Ignored (description change only) |

```python
# actingweb/remote_storage.py

class RemotePeerStore:
    """
    Storage abstraction for data received from peer actors.

    This is a LIBRARY IMPLEMENTATION PATTERN, not a protocol requirement.
    Other ActingWeb implementations may store peer data differently.

    The actingweb library uses internal attributes for storage because:
    - Attributes are already available (no new storage backend needed)
    - Internal attributes aren't exposed via HTTP (privacy)
    - Per-peer buckets provide natural isolation
    """

    def apply_callback_data(self, data: dict) -> dict[str, Any]:
        """Apply callback data to storage, handling list operations.

        Args:
            data: Callback data dict from subscription callback

        Returns:
            Dict of {property_name: operation_result} for each processed property
        """
        results = {}
        for key, value in data.items():
            if key.startswith("list:") and isinstance(value, dict):
                list_name = value.get("list", key[5:])
                operation = value.get("operation", "unknown")
                results[list_name] = self._apply_list_operation(list_name, operation, value)
            else:
                # Scalar property
                self.set_value(key, value)
                results[key] = {"stored": True}
        return results

    def _apply_list_operation(
        self, list_name: str, operation: str, data: dict
    ) -> dict[str, Any]:
        """Apply a single list operation."""
        list_prop = self.get_list_property(list_name)

        if operation == "append" and "item" in data:
            list_prop.append(data["item"])
            return {"operation": "append", "success": True}

        elif operation == "insert" and "item" in data and "index" in data:
            list_prop.insert(data["index"], data["item"])
            return {"operation": "insert", "index": data["index"], "success": True}

        elif operation == "update" and "item" in data and "index" in data:
            if data["index"] < len(list_prop):
                list_prop[data["index"]] = data["item"]
                return {"operation": "update", "index": data["index"], "success": True}
            return {"operation": "update", "error": "index out of range"}

        elif operation == "extend" and "items" in data:
            list_prop.extend(data["items"])
            return {"operation": "extend", "count": len(data["items"]), "success": True}

        elif operation == "delete" and "index" in data:
            if data["index"] < len(list_prop):
                del list_prop[data["index"]]
                return {"operation": "delete", "index": data["index"], "success": True}
            return {"operation": "delete", "error": "index out of range"}

        elif operation == "pop" and "index" in data:
            if data["index"] < len(list_prop):
                list_prop.pop(data["index"])
                return {"operation": "pop", "index": data["index"], "success": True}
            return {"operation": "pop", "error": "index out of range"}

        elif operation == "clear":
            list_prop.clear()
            return {"operation": "clear", "success": True}

        elif operation == "delete_all":
            list_prop.delete()
            return {"operation": "delete_all", "success": True}

        elif operation == "metadata":
            # Metadata-only change, no storage action needed
            return {"operation": "metadata", "ignored": True}

        return {"operation": operation, "error": "unknown operation"}
```

### Component 3: FanOutManager (HIGH PRIORITY)

**Purpose**: Deliver callbacks to multiple subscribers efficiently.

**Protocol features it implements**:
- Granularity downgrade for large payloads (protocol v1.4 guideline)
- Back-pressure handling (protocol's 429/503 responses)
- Callback compression (protocol's `callbackcompression` option)

**Library-specific implementation details**:
- Bounded concurrent HTTP requests
- Per-peer circuit breaker state machine
- Rate limiting algorithms

**Wire protocol alignment notes**:

1. **Callback wrapper format** (per spec lines 2544-2556): All callbacks MUST include:
   ```json
   {
       "id": "actor_id",
       "target": "properties",
       "sequence": 6,
       "timestamp": "2026-01-20T12:00:00.000000Z",
       "granularity": "high",
       "subscriptionid": "sub_id",
       "data": { ... }
   }
   ```

2. **List property diffs MUST include `length`** (per spec line 2466): The `length` field is REQUIRED in all list property diff payloads.

3. **Granularity downgrade header** (per spec lines 2765-2767): When downgrading from `high` to `low` due to payload size, include:
   ```
   X-ActingWeb-Granularity-Downgraded: true
   ```

4. **Resync callback format** (per spec lines 2712-2724): When sending resync, include `type: "resync"` and `url`:
   ```json
   {
       "type": "resync",
       "url": "https://example.com/actor/properties/target"
   }
   ```

5. **Sequence numbers in GET responses** (per spec lines 2568-2571): GET on subscription endpoint MUST include top-level `sequence` field showing current sequence number.

```python
# actingweb/fanout.py

class FanOutManager:
    """
    Manages callback delivery to multiple subscribers.

    Implements protocol v1.4 features:
    - Automatic granularity downgrade when payload > threshold
    - Circuit breaker pattern for handling 429/503 responses
    - Optional compression for large payloads
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        max_payload_for_high_granularity: int = 65536,  # 64KB
        circuit_breaker_threshold: int = 5
    ):
        pass
```

### Component 4: Peer Utilities (MEDIUM PRIORITY)

**Purpose**: Common utilities for working with peer actors.

**Implementation**:
- Profile fetching with caching
- Peer existence verification
- Connection search by keywords

These are convenience utilities, not protocol requirements.

### Component 5: Peer Capability Discovery (CRITICAL PRIORITY - NEW)

**Problem Identified**: The new spec v1.4 features (batch subscriptions, compression, health endpoints) are OPTIONAL. Before using them, the library must know which features a peer supports. Currently, **there is no mechanism to discover or cache peer capabilities**.

**Current State in Protocol**:

The protocol already defines capability discovery via `/meta/actingweb/supported`:
```
GET /{peer_id}/meta/actingweb/supported
200 OK
Content-Type: text/plain

trust,subscriptions,listproperties,subscriptionresync,subscriptionbatch,callbackcompression
```

**Current State in Library**:

The trust model (`actingweb/db/dynamodb/trust.py`) stores:
- `baseuri` - peer's base URL
- `type` - peer's URN type (e.g., `urn:actingweb:example.com:app`)

**Missing**:
- `aw_supported` - peer's supported option tags
- `aw_version` - peer's ActingWeb protocol version
- No mechanism to fetch/cache these during trust establishment

**Why This Matters**:

Without capability discovery, the library cannot:
1. Use batch subscription creation (requires `subscriptionbatch` option)
2. Send compressed callbacks (requires `callbackcompression` option)
3. Query subscription health (requires `subscriptionhealth` option)
4. Make informed granularity decisions based on peer support

**Proposed Solution**:

1. **Extend Trust Model** - Add fields to store peer capabilities:
```python
# In trust database model
aw_supported = UnicodeAttribute(null=True)  # Comma-separated option tags
aw_version = UnicodeAttribute(null=True)    # e.g., "1.4"
capabilities_fetched_at = UTCDateTimeAttribute(null=True)
```

2. **Fetch During Trust Establishment** - When trust is created/verified:
```python
# After trust handshake, fetch peer capabilities
response = requests.get(f"{peer_baseuri}/meta/actingweb/supported")
if response.status_code == 200:
    trust.aw_supported = response.text.strip()
```

3. **Provide Query API** - Easy way to check capabilities:
```python
class PeerCapabilities:
    """Query peer's supported ActingWeb options."""

    def __init__(self, actor: ActorInterface, peer_id: str):
        self.trust = actor.get_trust(peer_id)
        self._supported = set(
            (self.trust.get("aw_supported") or "").split(",")
        )

    def supports(self, option: str) -> bool:
        """Check if peer supports a specific option tag."""
        return option in self._supported

    def supports_batch_subscriptions(self) -> bool:
        return self.supports("subscriptionbatch")

    def supports_compression(self) -> bool:
        return self.supports("callbackcompression")

    def supports_health_endpoint(self) -> bool:
        return self.supports("subscriptionhealth")

    def supports_resync_callbacks(self) -> bool:
        return self.supports("subscriptionresync")

    async def refresh(self) -> None:
        """Re-fetch capabilities from peer (e.g., after peer upgrade)."""
```

4. **Integration with FanOutManager**:
```python
class FanOutManager:
    async def deliver_callback(self, peer_id: str, payload: dict) -> None:
        caps = PeerCapabilities(self.actor, peer_id)

        # Use compression if peer supports it and payload is large
        if caps.supports_compression() and len(payload) > 1024:
            headers["Content-Encoding"] = "gzip"
            payload = gzip.compress(payload)
```

5. **Integration with Subscription Creation**:
```python
async def create_subscriptions(self, peer_id: str, targets: list) -> None:
    caps = PeerCapabilities(self.actor, peer_id)

    if caps.supports_batch_subscriptions() and len(targets) > 1:
        # Use batch endpoint
        await self._create_batch_subscriptions(peer_id, targets)
    else:
        # Fall back to individual requests
        for target in targets:
            await self._create_single_subscription(peer_id, target)
```

**Implementation Priority**: HIGH - This is a prerequisite for properly implementing the other spec v1.4 features.

### Implementation Phases

**Phase 0: Peer Capability Discovery (PREREQUISITE)**
- Extend trust model with `aw_supported`, `aw_version`, `capabilities_fetched_at` fields
- Fetch capabilities during trust establishment
- Add `PeerCapabilities` query class
- **Migration strategy**: Lazy fetch on first access (not bulk migration) - spreads load, handles deleted peers gracefully
- PostgreSQL: Alembic migration adds nullable columns; DynamoDB: add nullable attributes (schemaless)

**Phase 1: Core Callback Handling**
- `CallbackProcessor` with sequence tracking
- Integration with existing `register_diffs()` flow
- Tests for out-of-order scenarios
- Use `PeerCapabilities` to check for `subscriptionresync` support

**Phase 2: Storage Abstraction**
- `RemotePeerStore` extraction from actingweb_mcp
- Documentation of storage patterns
- Migration guide for existing apps

**Phase 3: Scale Features**
- `FanOutManager` with parallel delivery
- Circuit breaker implementation
- Compression support (check `callbackcompression` capability)
- Automatic granularity downgrade

**Phase 4: Protocol Endpoints**
- Implement optional endpoints: `/subscriptions/stats`, `/subscriptions/.../health`
- Implement batch subscription creation (use when peer has `subscriptionbatch`)

**Phase 5: Integration Layer**
- Add `.with_subscription_processing()` configuration method
- Add `@app.subscription_data_hook()` decorator
- Wire automatic callback routing through `CallbackProcessor`
- Auto-register cleanup hooks

---

### Developer API: Usage Patterns

The library components can be used at three levels of abstraction, depending on application needs.

#### Level 1: Automatic Mode (Recommended)

For most applications, enable automatic subscription processing. The library handles sequencing, storage, and cleanup automatically.

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
        auto_storage=True,          # Enable RemotePeerStore
        auto_cleanup=True,          # Clean up when trust deleted
        gap_timeout_seconds=5.0,    # Time before triggering resync
        max_pending=100             # Back-pressure limit
    )
)

# Register handler for sequenced, validated callback data
@app.subscription_data_hook("properties")
def on_property_change(
    actor: ActorInterface,
    peer_id: str,
    target: str,
    data: dict,
    sequence: int,
    callback_type: str  # "diff" or "resync"
) -> None:
    """Called with already-sequenced, deduplicated data.

    The library has already:
    - Verified sequence order (or triggered resync)
    - Filtered duplicates
    - Fetched data for granularity="low" callbacks
    - Stored data in RemotePeerStore (if auto_storage=True)
    """
    # Just do app-specific logic
    logger.info(f"Received {callback_type} from {peer_id}: {data.keys()}")

    # Optional: app-specific processing beyond storage
    if "memory_personal" in data:
        notify_user_of_update(actor, peer_id)

# Trust and subscribe work as before
# After trust is approved:
actor.subscriptions.subscribe_to_peer(peer_id, "properties", granularity="high")

# That's it! The library handles:
# - Callback sequencing and deduplication
# - Resync detection and triggering
# - Data storage in RemotePeerStore
# - Cleanup when trust is deleted
```

**Configuration options for `.with_subscription_processing()`:**

| Option | Type | Default | Description |
| ------ | ---- | ------- | ----------- |
| `auto_sequence` | bool | True | Enable CallbackProcessor for sequence handling |
| `auto_storage` | bool | True | Automatically store received data in RemotePeerStore (includes list operations) |
| `auto_cleanup` | bool | True | Register hook to clean up when trust is deleted |
| `gap_timeout_seconds` | float | 5.0 | Time before triggering resync on sequence gap |
| `max_pending` | int | 100 | Maximum pending callbacks before back-pressure (429) |
| `storage_prefix` | str | "remote:" | Bucket prefix for RemotePeerStore |

**What `auto_storage=True` handles:**
- Scalar property changes (stored as attributes)
- List property operations: `append`, `insert`, `update`, `extend`, `delete`, `pop`, `clear`, `delete_all`
- Automatic sync metadata updates

---

#### Real-World Example: actingweb_mcp with Automatic Mode

The actingweb_mcp application can use `.with_subscription_processing()` with `auto_storage=True`, reducing ~500 lines of callback handling code to ~30 lines:

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:actingweb.io:actingweb-ai-memory",
        database="dynamodb",
        fqdn="memory.example.com",
        proto="https://"
    )
    .with_subscription_processing(
        auto_sequence=True,
        auto_storage=True,   # Library handles all list operations
        auto_cleanup=True
    )
)

@app.subscription_data_hook("properties")
def on_property_change(
    actor: ActorInterface,
    peer_id: str,
    target: str,
    data: dict,
    sequence: int,
    callback_type: str
) -> None:
    """Handle property changes - data already sequenced and stored."""

    # App-specific: Update last_accessed timestamp
    _update_last_accessed(actor, peer_id)

    # App-specific: Send WebSocket notifications for memory types only
    for key, value in data.items():
        if key.startswith("list:"):
            list_name = value.get("list", key[5:])
            if list_name.startswith("memory_"):
                notify_subscription_update(actor.id, peer_id, list_name, value)
```

**What the library handles automatically:**
- Callback sequencing and duplicate detection (~60 lines removed)
- Sequence gap detection and resync triggering (~40 lines removed)
- Pending callback queue management (~50 lines removed)
- List operation application (append, update, delete, etc.) (~80 lines removed)
- Storage in RemotePeerStore (~100 lines removed)
- Cleanup when trust is deleted (~20 lines removed)

**What remains app-specific:**
- `_update_last_accessed()` - Trust relationship metadata
- WebSocket notifications - Real-time frontend updates
- Memory-type filtering for notifications - Domain-specific logic

---

#### Level 2: Component-Level Control

For applications that need custom behavior, use the library components directly while still benefiting from their functionality.

```python
from actingweb.interface import ActingWebApp
from actingweb.callback_processor import CallbackProcessor
from actingweb.remote_storage import RemotePeerStore

app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb",
    fqdn="myapp.example.com",
    proto="https://"
)
# Note: NOT calling .with_subscription_processing()

# Use raw callback hook - you control the flow
@app.callback_hook("subscription")
def handle_subscription_callback(
    actor: ActorInterface,
    name: str,
    data: dict
) -> bool:
    """Handle raw subscription callbacks with manual component usage."""
    peer_id = data.get("peerid", "")
    subscription = data.get("subscription", {})
    subscription_id = subscription.get("subscriptionid", "")
    callback_data = data.get("data", {})
    sequence = data.get("sequence", 0)

    # Use CallbackProcessor for sequencing, but handle storage yourself
    processor = CallbackProcessor(
        actor,
        gap_timeout_seconds=10.0,  # Custom timeout
        max_pending=50
    )

    async def my_handler(validated_data: dict) -> None:
        # Custom storage logic - maybe filter or transform data
        if should_store(validated_data):
            store = RemotePeerStore(actor, peer_id)
            for key, value in validated_data.items():
                if key.startswith("memory_"):
                    store.set_list(key, value)
                else:
                    store.set_value(key, value)

        # Custom notification logic
        await notify_websocket_clients(actor.id, peer_id, validated_data)

    result = processor.process_callback(
        peer_id=peer_id,
        subscription_id=subscription_id,
        sequence=sequence,
        data=callback_data,
        handler=my_handler
    )

    return result != ProcessResult.REJECTED

# Manual cleanup when trust is deleted
@app.trust_deleted_hook
def on_trust_deleted(
    actor: ActorInterface,
    peer_id: str,
    relationship: str,
    trust_data: dict
) -> None:
    """Clean up remote data when trust ends."""
    store = RemotePeerStore(actor, peer_id)
    store.delete_all()
    logger.info(f"Cleaned up data for peer {peer_id}")
```

**When to use Level 2:**
- Custom storage filtering (only store certain property types)
- Custom storage transformation (process data before storing)
- Different timeout/pending limits per subscription type
- Integration with external systems (webhooks, message queues)
- Custom cleanup logic beyond simple deletion

---

#### Level 3: Raw Callback Handling

For applications with specialized requirements or gradual migration, use raw callbacks without the library components.

```python
from actingweb.interface import ActingWebApp

app = ActingWebApp(
    aw_type="urn:actingweb:example.com:myapp",
    database="dynamodb",
    fqdn="myapp.example.com",
    proto="https://"
)
# No .with_subscription_processing() - fully manual

@app.callback_hook("subscription")
def handle_subscription_callback(
    actor: ActorInterface,
    name: str,
    data: dict
) -> bool:
    """Handle subscription callbacks with full manual control.

    You are responsible for:
    - Sequence tracking and gap detection
    - Duplicate filtering
    - Resync coordination
    - Storage decisions
    - Cleanup when trust ends
    """
    peer_id = data.get("peerid", "")
    subscription = data.get("subscription", {})
    callback_data = data.get("data", {})
    sequence = data.get("sequence", 0)

    # Implement your own sequencing logic
    # (See actingweb_mcp/hooks/actingweb/callback_hooks.py for reference)

    # Example: Simple processing without sequencing (may miss/duplicate data)
    for key, value in callback_data.items():
        logger.info(f"Received {key} from {peer_id}")
        # Process as needed

    return True

# You must also handle cleanup manually
@app.trust_deleted_hook
def on_trust_deleted(actor, peer_id, relationship, trust_data):
    # Clean up any data you stored
    pass
```

**When to use Level 3:**
- Migrating existing applications gradually
- Applications with custom distributed state (e.g., Redis, external DB)
- Simple use cases where sequence ordering doesn't matter
- Testing and development

---

#### Mixing Levels: Selective Automation

Applications can enable some automatic features while handling others manually:

```python
app = (
    ActingWebApp(...)
    .with_subscription_processing(
        auto_sequence=True,   # Use CallbackProcessor
        auto_storage=False,   # Handle storage ourselves
        auto_cleanup=True     # But auto-cleanup is fine
    )
)

@app.subscription_data_hook("properties")
def on_property_change(actor, peer_id, target, data, sequence, callback_type):
    """Data is sequenced but not auto-stored."""
    # Custom storage to external database
    external_db.store(actor.id, peer_id, data)
```

---

#### API Summary

| Feature | Level 1 (Automatic) | Level 2 (Components) | Level 3 (Raw) |
| ------- | ------------------- | -------------------- | ------------- |
| Configuration | `.with_subscription_processing()` | None | None |
| Hook decorator | `@subscription_data_hook` | `@callback_hook("subscription")` | `@callback_hook("subscription")` |
| Sequencing | Automatic | Manual `CallbackProcessor` | Implement yourself |
| Storage | Automatic | Manual `RemotePeerStore` | Implement yourself |
| Cleanup | Automatic | Manual hook | Manual hook |
| Lines of code | ~10-20 | ~50-100 | ~300+ |
| Recommended for | Most apps | Custom behavior | Migration/special cases |

---

## Part 5: Resolved Questions and Design Decisions

This section documents the design decisions made after analyzing the protocol spec, existing codebase patterns, and implementation considerations.

### 5.1 Peer Capability Discovery Lifecycle

| Question | Decision | Rationale |
|----------|----------|-----------|
| **When to refresh capabilities?** | TTL of 24 hours + refresh on 404/403 | Peers rarely change capabilities; 404 means peer may have been recreated |
| **Failure during trust establishment?** | Log warning, proceed with empty capabilities | Don't block trust creation; degrade gracefully |
| **Cache invalidation?** | Explicit `refresh()` method + automatic on 404 | Allow manual refresh after known peer upgrade |

**Storage fields**: `aw_supported`, `aw_version`, `capabilities_fetched_at` added to trust model.

**Backward compatibility**: Empty/null `aw_supported` means "assume no optional features" (safe default).

---

### 5.2 CallbackProcessor Concurrency

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Conflict handling** | Retry 3 times with exponential backoff (0.5s base) | Matches existing `get_peer_info()` pattern in codebase |
| **In-flight callbacks during resync** | Discard pending queue, accept resync as new baseline | Protocol's `type: "resync"` means "full state reset" |
| **Handler failure after state update** | Provide `process_callback(callback, handler)` that updates state AFTER handler succeeds | Atomic processing pattern |

**Transactional processing**: The library provides at-most-once delivery semantics (per protocol). State is updated AFTER the handler succeeds, not before.

**Handler requirement**: Handlers MUST be idempotent. The library provides sequence numbers for deduplication.

---

### 5.3 FanOutManager Specification

Protocol spec (lines 2878-2889) recommends circuit breaker with Closed → Open → Half-Open states.

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Circuit breaker transitions** | Open after 5 consecutive failures; Half-Open after 60s cooldown; Close on first success | Per protocol recommendation |
| **Failed delivery handling** | Diffs persist in subscription; available via polling | Matches existing pattern (non-204 keeps diff) |
| **Queue behavior when open** | Stop delivery attempts; diffs accumulate for polling | Protocol: "diffs accumulate and are available via polling" |
| **Granularity downgrade failure** | Return 503 to indicate service unavailable | Can't deliver if peer doesn't support URL fetch |

---

### 5.4 RemotePeerStore Cleanup

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Automatic cleanup** | Yes, via `on_trust_deleted` hook | Prevents orphaned data; follows existing hook patterns |
| **Partial deletion recovery** | Log error, mark peer as `cleanup_pending`, retry on next actor load | Eventually consistent cleanup |
| **Orphan detection** | Utility function `find_orphaned_peer_buckets()` for maintenance | Not automatic; manual/cron job |

---

### 5.5 Database Migration

| Question | Decision | Rationale |
|----------|----------|-----------|
| **How to populate existing trusts** | Lazy fetch on first access (not bulk migration) | Simpler; spreads load; handles peers that no longer exist |
| **Schema versioning** | PostgreSQL: Alembic migration; DynamoDB: add nullable attributes | DynamoDB is schemaless |
| **Backward compatibility** | Empty/null `aw_supported` means "assume no optional features" | Safe default |

---

### 5.6 Error Handling

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Delivery semantics** | At-most-once (per protocol) | Protocol specification requirement |
| **Retry policy** | Configurable per-component; defaults to 3 retries with exponential backoff (0.5s × 2^attempt) | Matches existing `get_peer_info()` pattern |
| **Idempotency** | Document that handlers MUST be idempotent; provide sequence for dedup | Matches existing subscription callback pattern |

---

### 5.7 Testing Strategy

Existing patterns found in codebase:
- Multi-server testing with separate FastAPI instances
- Mock layers: `responses` library, `unittest.mock`
- Sequential flow testing with class-level state
- Worker isolation with database prefixes

| Scenario | Testing Approach |
|----------|------------------|
| **Out-of-order callbacks** | Sequential flow test class with controlled callback injection |
| **Circuit breaker** | Unit tests with mocked HTTP; inject 5 failures → verify open state |
| **Resync** | Integration test: send callbacks with gap, verify resync triggered |
| **Peer mocking** | Use existing `responses` library pattern for HTTP mocking |

---

### 5.8 Observability

Existing pattern: Library uses Python `logging` with named loggers (`__name__`).

| Aspect | Decision |
|--------|----------|
| **Logging** | Named loggers per module; DEBUG for detailed callback flow, WARNING for errors |
| **Metrics** | NOT in library scope (app-specific); document recommended metrics |
| **Tracing** | NOT in library scope; document how apps can add correlation IDs |

---

### 5.9 Configuration

Existing pattern: `config.py` with environment variable overrides.

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Unified config** | Extend existing `Config` class with subscription settings | Don't create parallel config system |
| **Environment variables** | Follow pattern: `ACTINGWEB_<COMPONENT>_<SETTING>` | Consistent naming |
| **Per-subscription override** | Store in subscription attributes, fall back to global config | Flexibility |

**Proposed config additions**:
```python
# In config.py or via environment
callback_gap_timeout_seconds = 5.0     # ACTINGWEB_CALLBACK_GAP_TIMEOUT
callback_max_pending = 100             # ACTINGWEB_CALLBACK_MAX_PENDING
fanout_max_concurrent = 10             # ACTINGWEB_FANOUT_MAX_CONCURRENT
circuit_breaker_threshold = 5          # ACTINGWEB_CIRCUIT_BREAKER_THRESHOLD
circuit_breaker_cooldown = 60          # ACTINGWEB_CIRCUIT_BREAKER_COOLDOWN
```

---

### 5.10 Security

Protocol findings (lines 1108-1114): Callbacks MUST use shared secret as Bearer token.

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Callback authentication** | Already in protocol: Bearer token with shared secret | No additional work needed |
| **Rate limiting** | Per-peer limits in FanOutManager circuit breaker | Implicit via back-pressure |
| **Payload validation** | Validate callback structure matches protocol (sequence, target, etc.) | Defense in depth |

---

## Conclusion

This research identified both **protocol improvements** and **library extraction candidates**:

### Protocol (Now in Spec v1.4)
The following have been added to `docs/protocol/actingweb-spec.rst`:
- Granularity selection guidelines
- Callback delivery semantics (at-most-once)
- Payload limits (256KB recommended)
- Back-pressure mechanism (429/503)
- Batch subscriptions, health endpoints, compression
- Subscription scope and overlap rules

### Library (Implementation Patterns)
The following should be extracted into the actingweb library:
- **Integration Layer**: `.with_subscription_processing()` + `@subscription_data_hook` (CRITICAL)
- **PeerCapabilities**: Query peer's supported option tags (CRITICAL)
- **CallbackProcessor**: Robust callback handling with sequencing
- **RemotePeerStore**: Attribute-based storage for peer data
- **FanOutManager**: Scalable callback delivery
- **Peer utilities**: Profile caching, existence checks

**Key principle**: The protocol defines the wire format; the library implements robust handling. Storage patterns like "store in attributes" are library details, not protocol requirements.

### Developer Experience Goal Achieved

With the Integration Layer, **apps can now get full subscription support** by:

```python
app = ActingWebApp(...).with_subscription_processing()

@app.subscription_data_hook("properties")
def on_change(actor, peer_id, target, data, sequence, callback_type):
    # Already sequenced, deduplicated, stored
    pass

# Trust and subscribe as before
actor.subscriptions.subscribe_to_peer(peer_id, "properties")
```

**Three levels of control** are available:
1. **Automatic** (recommended): Full automation via `.with_subscription_processing()`
2. **Component-level**: Use `CallbackProcessor`/`RemotePeerStore` directly for custom behavior
3. **Raw**: Handle callbacks manually for specialized requirements

### Critical Prerequisites

**Peer Capability Discovery** must be implemented first:
1. Fetch capabilities during trust establishment
2. Store them in the trust model (`aw_supported`, `aw_version`)
3. Provide `PeerCapabilities` API to query peer support

This enables proper use of optional spec features like batch subscriptions, compression, or health endpoints.

**Recommended implementation order**:
1. **Phase 0**: Peer Capability Discovery (trust model extension)
2. **Phase 1**: Core components (CallbackProcessor, RemotePeerStore)
3. **Phase 2**: Integration Layer (`.with_subscription_processing()`, `@subscription_data_hook`)
4. **Phase 3**: Scale features (FanOutManager, circuit breakers)
5. **Phase 4**: Protocol endpoints (stats, health, batch)

---

## Appendix A: Protocol Engineering Review (2026-01-20)

This appendix documents the protocol engineering review comparing this research document against `docs/protocol/actingweb-spec.rst` v1.4.

### A.0.1 Review Summary

| Category | Status | Notes |
| -------- | ------ | ----- |
| Callback format consistency | ✅ Verified | Wire format matches spec |
| Sequence number semantics | ✅ Verified | Starts at 1, monotonic increment |
| List property diff format | ✅ Verified | `list:{name}` key, required fields present |
| Granularity handling | ✅ Verified | `high`/`low`/`none` supported |
| Resync callback support | ✅ Verified | `type: "resync"` with `url` field |
| Back-pressure responses | ✅ Verified | 429/503 codes documented |
| Circuit breaker defaults | ✅ Verified | 5 failures, 60s cooldown matches spec |

### A.0.2 Wire Protocol Verification

**Callback Wrapper Format** (spec lines 2544-2556):
```json
{
    "id": "actor_id",
    "target": "properties",
    "sequence": 6,
    "timestamp": "2026-01-20T12:00:00.000000Z",
    "granularity": "high",
    "subscriptionid": "sub_id",
    "data": { "diff content here" }
}
```
- Library's `CallbackProcessor` expects this structure ✓
- Diff content is in `callback["data"]`, not top-level ✓

**List Property Diff Format** (spec lines 2457-2475):
```json
{
    "list:memory_personal": {
        "list": "memory_personal",
        "operation": "append",
        "length": 10,
        "item": { ... },
        "index": 9
    }
}
```
- Library's `RemotePeerStore` handles `key.startswith("list:")` ✓
- `length` field is REQUIRED when sending (FanOutManager) ✓
- `length` field not required for storage (RemotePeerStore can compute) ✓

**Resync Callback** (spec lines 2712-2729):
```json
{
    "type": "resync",
    "url": "https://example.com/actor/properties/target"
}
```
- `type` field defaults to `"diff"` when absent (backward compatible) ✓
- Library must use `callback.get("type", "diff")` ✓

### A.0.3 Issues Addressed

1. **Callback structure clarification**: Added note that diff content is in `callback["data"]`
2. **Type field handling**: Documented that `type` may be absent (defaults to `"diff"`)
3. **Length field requirement**: Added to FanOutManager wire protocol notes
4. **Granularity downgrade header**: Added `X-ActingWeb-Granularity-Downgraded` header requirement
5. **HTTP response codes**: Added 429/503 response requirements for back-pressure

### A.0.4 Conclusion

The research document is **consistent with protocol spec v1.4**. The wire protocol will work correctly when implemented according to this design.

---

## Appendix B: Verification Against actingweb_mcp (2026-01-20)

This appendix documents the verification of the proposed library design against the actingweb_mcp reference implementation.

### B.1 Files Analyzed

| File | Lines | Purpose |
| ---- | ----- | ------- |
| `hooks/actingweb/callback_hooks.py` | 651 | Callback sequencing, duplicate detection, resync handling |
| `repositories/remote_attribute_store.py` | 581 | Remote peer data storage (bucket pattern) |
| `hooks/actingweb/trust.py` | 887 | Profile fetching, peer verification, trust lifecycle |
| `helpers/trust_utils.py` | 130 | Connection search utilities |
| **Total** | **2,249** | |

### A.2 Verification Results

#### CallbackProcessor Coverage

The proposed `CallbackProcessor` covers all callback handling in `callback_hooks.py`:

| actingweb_mcp Code | Lines | Proposed Library Component | Covered? |
| ------------------ | ----- | -------------------------- | -------- |
| `_atomic_update_callback_state()` | ~60 | `CallbackProcessor.process_callback()` with optimistic locking | Yes |
| Sequence tracking in `handle_subscription_callback_hook()` | ~150 | `CallbackProcessor` internal state | Yes |
| Pending callback queue management | ~50 | `CallbackStateStore` protocol | Yes |
| Resync trigger logic (gap timeout) | ~40 | `CallbackProcessor.handle_resync_callback()` | Yes |
| Post-resync baseline establishment | ~30 | `CallbackProcessor` sequence reset | Yes |
| Fresh state detection (high seq on first callback) | ~40 | `CallbackProcessor` initial state handling | Yes |

**Estimated deletable code**: ~370 lines from `callback_hooks.py`

**Remaining app code**: `_process_subscription_callback()` (~150 lines) contains app-specific logic (memory list operations, WebSocket notifications) that stays in the application.

#### RemotePeerStore Coverage

The proposed `RemotePeerStore` covers all of `remote_attribute_store.py`:

| actingweb_mcp Code | Lines | Proposed Library Component | Covered? |
| ------------------ | ----- | -------------------------- | -------- |
| `get_remote_bucket()` | 15 | `get_remote_bucket()` function | Yes |
| Memory list operations | ~110 | `RemotePeerStore.get_list()`, `set_list()`, etc. | Yes |
| Profile operations | ~40 | `RemotePeerStore.get_value()`, `set_value()` | Yes |
| Permissions operations | ~50 | `RemotePeerStore.get_value()`, `set_value()` | Yes |
| Methods operations | ~80 | `RemotePeerStore.get_list()`, `set_list()` | Yes |
| Callback state operations | ~100 | `CallbackStateStore` protocol | Yes |
| Cleanup operations | ~20 | `RemotePeerStore.delete_all()` | Yes |

**Estimated deletable code**: ~575 lines (entire file replaceable)

#### PeerMetadataFetcher Coverage

The proposed `PeerMetadataFetcher` covers profile fetching in `trust.py`:

| actingweb_mcp Code | Lines | Proposed Library Component | Covered? |
| ------------------ | ----- | -------------------------- | -------- |
| `fetch_peer_profile()` | ~80 | `PeerMetadataFetcher.fetch()` | Yes |
| `fetch_peer_profile_async()` | ~90 | `PeerMetadataFetcher.fetch_async()` | Yes |
| `_cache_peer_profile()` | ~20 | Internal to `PeerMetadataFetcher` | Yes |
| `verify_peer_actor_exists()` | ~50 | `verify_peer_exists()` utility | Yes |

**Estimated deletable code**: ~240 lines from `trust.py`

**Remaining app code**: `_fetch_and_store_peer_properties_async()` (~250 lines) contains app-specific logic that uses the library's `RemotePeerStore` but has custom filtering and WebSocket notifications.

#### Connection Search Coverage

| actingweb_mcp Code | Lines | Proposed Library Component | Covered? |
| ------------------ | ----- | -------------------------- | -------- |
| `find_matching_connections()` | ~60 | `find_matching_connections()` utility | Yes |

**Estimated deletable code**: ~60 lines from `trust_utils.py`

**Remaining app code**: `is_remote_memory_subscription()` (~25 lines) is app-specific filtering logic.

### A.3 Summary: Code Reduction

| Component | Current (lines) | Deletable (lines) | Remaining (lines) |
| --------- | --------------- | ----------------- | ----------------- |
| Callback handling | 651 | ~370 | ~280 (app-specific) |
| Remote storage | 581 | ~575 | ~6 (imports) |
| Profile/peer utils | 887 | ~240 | ~650 (app-specific) |
| Trust utils | 130 | ~60 | ~70 (app-specific) |
| **Total** | **2,249** | **~1,245** | **~1,000** |

**Estimated code reduction**: ~55% of analyzed code can be replaced by library functionality.

### A.4 Verification Checklist

| Requirement | Status | Notes |
| ----------- | ------ | ----- |
| CallbackProcessor API covers callback sequencing | ✅ Verified | All sequence/resync logic covered |
| CallbackProcessor handles optimistic locking | ✅ Verified | Matches `_atomic_update_callback_state()` pattern |
| RemotePeerStore covers bucket naming | ✅ Verified | `get_remote_bucket()` extracted |
| RemotePeerStore covers list/scalar storage | ✅ Verified | Memory lists + scalar attributes |
| RemotePeerStore covers cleanup | ✅ Verified | `delete_all()` removes bucket |
| PeerMetadataFetcher covers profile caching | ✅ Verified | Both sync and async variants |
| `verify_peer_exists()` covers existence checks | ✅ Verified | 404 vs 403 distinction |
| `find_matching_connections()` covers search | ✅ Verified | AND logic, case-insensitive |

### A.5 Items NOT Extracted (App-Specific)

The following remain in the application as they contain domain-specific logic:

1. **`_process_subscription_callback()`** - Memory-specific property handling, WebSocket notifications
2. **`_fetch_and_store_peer_properties_async()`** - App-specific property filtering, permission cache updates
3. **`on_trust_approved_async()`** - App-specific subscription setup, method discovery
4. **`on_trust_deleted()`** - Calls library's `delete_all()` but has app-specific cleanup
5. **`is_remote_memory_subscription()`** - App-specific URN matching logic

### A.6 Conclusion

The proposed library design successfully covers actingweb_mcp's subscription and callback handling needs:

1. **CallbackProcessor** handles all callback sequencing with proper concurrency handling
2. **RemotePeerStore** provides the storage abstraction for peer data
3. **PeerMetadataFetcher** and utilities cover common peer operations
4. **~55% code reduction** achievable in the analyzed files
5. **App-specific logic remains** cleanly separated from library functionality

The library extraction will allow actingweb_mcp to delete ~1,245 lines of boilerplate code while retaining ~1,000 lines of app-specific business logic.
