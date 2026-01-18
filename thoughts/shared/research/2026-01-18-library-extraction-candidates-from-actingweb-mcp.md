---
date: 2026-01-18T12:00:00Z
researcher: Claude
git_commit: 5a081b9cc54bf4090cbb94fb11d114b33669d677
branch: master
repository: actingweb
reference_app: actingweb_mcp
topic: "Library Extraction Candidates from actingweb_mcp Reference Implementation"
tags: [research, library-design, extraction, patterns, distributed-systems, peer-sync]
status: complete
last_updated: 2026-01-18
last_updated_by: Claude
---

# Research: Library Extraction Candidates from actingweb_mcp Reference Implementation

**Date**: 2026-01-18T12:00:00Z
**Researcher**: Claude
**Git Commit**: 5a081b9cc54bf4090cbb94fb11d114b33669d677
**Branch**: master
**Repository**: actingweb
**Reference Application**: actingweb_mcp

## Research Question

What functionality in actingweb_mcp represents generic patterns that should be extracted into the actingweb library to benefit all ActingWeb application developers?

## Summary

After thorough analysis of the actingweb_mcp codebase (~6,000 lines across hooks, helpers, and repositories), I identified **10 candidates** for extraction. The three highest-value candidates are:

1. **Distributed Callback Sequencing** - Solves the out-of-order subscription callback problem inherent to serverless/Lambda deployments. Any ActingWeb app using subscriptions in distributed environments needs this.

2. **Remote Peer Storage Abstraction** - A bucket-per-peer pattern for storing synced peer data in internal attributes. Essential for any app that synchronizes data from peer actors.

3. **Peer Metadata Utilities** - Profile fetching with graceful error handling, existence verification, and connection search. Common needs for any multi-peer application.

**Total extractable code**: ~900 lines (approximately 55% of hooks/helpers code)
**Estimated implementation effort**: 4-6 days

## Detailed Findings

### Candidate 1: Distributed Callback Sequencing (HIGH PRIORITY)

**Source**: `actingweb_mcp/hooks/actingweb/callback_hooks.py` (lines 1-250)

**Problem it solves**: In serverless environments (AWS Lambda, Google Cloud Functions), subscription callbacks may arrive out-of-order due to concurrent function executions. Without proper sequencing, data corruption or loss can occur.

**Current implementation**:
```
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

**Complexity assessment**: MEDIUM
- Requires careful handling of edge cases (concurrent writes, version conflicts)
- Needs configurable timeout (currently 5 seconds via environment variable)
- Must handle the post-resync baseline establishment correctly

**Value assessment**: HIGH
- Enables reliable subscription processing in distributed environments
- Prevents data corruption from out-of-order callbacks
- Eliminates significant development effort for app developers

**Suggested library API**:
```python
# actingweb/distributed_state.py

class CallbackSequencer:
    """Handles out-of-order callback processing in distributed environments."""

    def __init__(
        self,
        state_store: CallbackStateStore,
        timeout_seconds: int = 5,
        max_retries: int = 3
    ):
        """
        Args:
            state_store: Persistent storage for callback state
            timeout_seconds: Time before triggering resync
            max_retries: Attempts for optimistic locking
        """

    def should_process(self, peer_id: str, subscription_id: str, seq: int) -> bool:
        """Check if callback should be processed (not duplicate, in-order or pending)."""

    def mark_processed(self, peer_id: str, subscription_id: str, seq: int) -> None:
        """Mark callback as successfully processed."""

    def add_pending(self, peer_id: str, subscription_id: str, seq: int, data: dict) -> None:
        """Store out-of-order callback for later processing."""

    def get_ready_callbacks(self, peer_id: str, subscription_id: str) -> list[tuple[int, dict]]:
        """Get pending callbacks that are now ready (in-order)."""

    def should_trigger_resync(self, peer_id: str, subscription_id: str) -> bool:
        """Check if pending callbacks have exceeded timeout."""

    def reset_for_resync(self, peer_id: str, subscription_id: str) -> None:
        """Reset state after full resync (sets marker for new baseline)."""


class CallbackStateStore(Protocol):
    """Protocol for callback state persistence."""

    def get_state(self, peer_id: str, subscription_id: str) -> dict: ...
    def set_state(self, peer_id: str, subscription_id: str, state: dict) -> None: ...
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
- Thin wrapper around existing actingweb classes
- No complex state management
- Clear, straightforward API

**Value assessment**: HIGH
- Every peer-syncing app needs this
- Prevents common mistakes (exposing internal data via HTTP)
- Standardizes bucket naming convention

**Suggested library API**:
```python
# actingweb/remote_storage.py

def get_remote_bucket(peer_id: str) -> str:
    """Get the standard bucket name for a remote peer's data."""
    return f"remote:{peer_id}"


class RemotePeerStore:
    """Storage abstraction for remote peer data.

    Provides a clean interface for storing data received from peer actors
    in internal attributes (not exposed via HTTP).
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
- Straightforward HTTP calls with caching
- Simple string matching for search
- Clear error handling patterns

**Value assessment**: MEDIUM
- Useful for many apps but not all
- Reduces development effort for common scenarios
- Standardizes error handling patterns

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

### Candidate 4: Permission Cache Framework (MEDIUM PRIORITY)

**Source**: `actingweb_mcp/helpers/permission_cache.py` (~177 lines)

**Problem it solves**: When peers grant permissions, the local actor needs to cache what's been granted to avoid repeated HTTP queries. This requires:
- Reading/writing cache atomically
- Handling grant/revoke updates
- Initial population from HTTP response
- Cleanup when relationship ends

**Key operations**:
- `get_permission_cache()` - Read what peer has granted
- `update_permission_cache()` - Update on permission change
- `delete_permission_cache()` - Clear on relationship end
- `populate_permission_cache_from_http()` - Initial sync

**Rationale for extraction**:
- Generic caching pattern (only data structure is app-specific)
- Could be parameterized for different permission models
- Clean separation of cache management vs permission checking

**Complexity assessment**: LOW
**Value assessment**: MEDIUM

**Note**: The specific permission model (memory types) is app-specific, but the caching framework is generic. Would need to parameterize the cache data structure.

---

### Candidate 5: Property List Accessor (LOW PRIORITY)

**Source**: `actingweb_mcp/repositories/property_list_accessor.py` (~220 lines)

**What it provides**:
- Wraps `PropertyListStore` with consistent error handling
- Custom exceptions (`PropertyListNotFoundError`)
- Helper methods: `exists()`, `get_list()`, `to_items()`, `append()`, `update_at_index()`, `delete_at_index()`, `find_item_index()`, `list_all()`

**Rationale**: Convenience wrapper that reduces boilerplate. Nice to have but not essential.

**Complexity**: LOW
**Value**: LOW-MEDIUM

---

### Candidate 6: Property Access Control Hooks (LOW PRIORITY)

**Source**: `actingweb_mcp/hooks/actingweb/property_hooks.py` (~82 lines)

**What it provides**:
- Protected property definitions (read-only, hidden)
- Power-user bypass for administrative access
- Hook registration patterns

**Rationale**: ~90% generic, only property names are app-specific. Could be parameterized.

**Complexity**: LOW
**Value**: LOW-MEDIUM

---

### Candidate 7: ID Generator (VERY LOW PRIORITY)

**Source**: `actingweb_mcp/repositories/id_generator.py` (~50 lines)

**What it provides**: Sequential ID generation: `max(existing_ids) + 1`

**Rationale**: Fully generic but trivial to implement. Low extraction value.

**Complexity**: VERY LOW
**Value**: VERY LOW

---

## Recommended Library Modules

Based on this analysis, I recommend creating the following new modules in actingweb:

### Module 1: `actingweb/distributed_state.py` (High Priority)

**Contents**:
- `CallbackSequencer` - Out-of-order callback handling
- `CallbackStateStore` - Protocol for state persistence
- `OptimisticLock` - Version-based conflict detection helper

**Benefits**:
- Enables reliable subscription processing in serverless
- Eliminates 200+ lines of complex code from each app

### Module 2: `actingweb/remote_storage.py` (High Priority)

**Contents**:
- `RemotePeerStore` - Bucket-per-peer abstraction
- `get_remote_bucket()` - Standard bucket naming

**Benefits**:
- Standardizes peer data storage patterns
- Prevents accidental HTTP exposure of internal data

### Module 3: `actingweb/peer_utils.py` (Medium Priority)

**Contents**:
- `PeerMetadataFetcher` - Profile caching
- `verify_peer_exists()` - Existence verification
- `find_matching_connections()` - Keyword search

**Benefits**:
- Common utilities for multi-peer applications
- Consistent error handling patterns

---

## Implementation Recommendations

### Phase 1: Extract with Minimal Changes
1. Copy code to actingweb library preserving current behavior
2. Update actingweb_mcp to import from library
3. Ensure all tests pass

### Phase 2: Generalize APIs
1. Remove app-specific naming (e.g., "memory" → generic terms)
2. Add configuration points (timeout values, property names)
3. Document extension patterns

### Phase 3: Add Library Tests
1. Port relevant tests from actingweb_mcp
2. Add generic test cases
3. Document usage patterns with examples

---

## Design Questions for Discussion

1. **Async-first or sync-first?**
   - Current actingweb uses sync APIs primarily
   - actingweb_mcp has moved toward async for HTTP operations
   - Recommendation: Async-first with sync wrappers for backward compatibility

2. **State storage abstraction**
   - CallbackSequencer needs persistent state storage
   - Should use Protocol/abstract base class for flexibility
   - Default implementation using existing Attributes

3. **Configuration approach**
   - Environment variables (current actingweb_mcp approach)
   - Constructor parameters (more explicit)
   - Config objects (more structured)
   - Recommendation: Constructor parameters with environment variable fallbacks

4. **Backward compatibility**
   - Apps already using these patterns directly
   - Should library provide migration helpers?
   - Recommendation: Document migration path, no automatic helpers

---

## Metrics Summary

| Candidate | Lines | Complexity | Value | Priority |
|-----------|-------|------------|-------|----------|
| Distributed Callback Sequencing | ~250 | MEDIUM | HIGH | HIGH |
| Remote Peer Storage | ~400 | LOW | HIGH | HIGH |
| Peer Metadata Utilities | ~180 | LOW | MEDIUM | MEDIUM |
| Permission Cache Framework | ~180 | LOW | MEDIUM | MEDIUM |
| Property List Accessor | ~220 | LOW | LOW-MEDIUM | LOW |
| Property Access Control Hooks | ~80 | LOW | LOW-MEDIUM | LOW |
| ID Generator | ~50 | VERY LOW | VERY LOW | VERY LOW |

**Total high-priority extractable code**: ~650 lines
**Total all candidates**: ~1,360 lines

---

## Conclusion

The actingweb_mcp implementation reveals several patterns that would benefit all ActingWeb application developers. The distributed callback sequencing is particularly valuable as it solves a fundamental problem for any app deploying to serverless environments with subscriptions.

The recommended approach is to extract the three highest-value candidates (distributed state, remote storage, peer utilities) in the first phase, then evaluate whether the medium-priority candidates warrant extraction based on community feedback.
