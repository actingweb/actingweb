# Subscription Callback Flows and Failure Situations

## Overview

This document describes the subscription callback flows in ActingWeb, the failure situations discovered during testing, and the fixes implemented.

## Normal Callback Flow (No Gaps)

```
1. Publisher creates diff → sequence increments to N
2. Publisher sends POST callback with sequence=N, data={...}
3. Subscriber receives callback at /callbacks/subscriptions/{actor_id}/{sub_id}
4. CallbackProcessor checks: sequence N == last_seq + 1 → VALID
5. CallbackProcessor updates state (optimistic lock)
6. CallbackProcessor invokes handler:
   - RemotePeerStore applies callback data
   - subscription_data_hooks invoked with data
7. CallbackProcessor updates subscription sequence to N
8. Subscriber returns 204 No Content to publisher
9. Publisher receives 204 but DOES NOT delete diff (new behavior)
10. Later: Subscriber syncs → sends PUT {sequence: N} → Publisher clears diffs ≤ N
```

**Key Points**:
- Sequence validation happens first
- State update before handler (optimistic lock check)
- Sequence update AFTER handler succeeds
- Diffs only cleared when subscriber confirms processing via PUT

## Gap Flow (Missing Sequences)

```
1. Publisher sends callback sequence=10
2. Subscriber currently at sequence=8 (missing sequence 9)
3. CallbackProcessor detects gap: seq=10 > last_seq + 1
4. CallbackProcessor adds callback to pending queue
5. CallbackProcessor starts gap timeout timer (5 seconds default)
6. Subscriber returns 204 to publisher (callback received, not yet processed)
7. Publisher does not delete diff

Two possible outcomes:

A. Missing callback arrives before timeout:
   - Callback seq=9 arrives
   - CallbackProcessor processes seq=9
   - CallbackProcessor processes pending seq=10
   - Both sequences updated, gap resolved

B. Gap timeout expires:
   - CallbackProcessor returns RESYNC_TRIGGERED on next callback
   - Handler automatically calls sync_subscription()
   - Sync fetches current state from publisher
   - Subscriber updates to current sequence
   - Gap resolved via sync
```

**Key Points**:
- Gaps detected automatically
- Callbacks queued in pending, not rejected
- Timeout triggers automatic resync
- Publisher keeps diffs until subscriber confirms

## Gap Timeout Automatic Resync Flow

```
1. Gap detected → callback added to pending
2. 5 seconds elapse with no resolution
3. Next callback arrives (or manual sync triggered)
4. CallbackProcessor checks gap timeout → EXCEEDED
5. CallbackProcessor:
   - Sets resync_pending = true
   - Resets subscription sequence to 0
   - Clears pending queue
   - Returns RESYNC_TRIGGERED
6. Handler in callbacks.py receives RESYNC_TRIGGERED
7. Handler accepts as success (returns 200, not 400)
8. Handler automatically calls sync_subscription():
   - GET /subscriptions/{actor_id}/{sub_id} from publisher
   - Fetches subscription metadata + available diffs
   - If no diffs: fetches baseline from target resource
   - Processes diffs or applies baseline
   - Updates local subscription sequence
   - Sends PUT {sequence: N} to confirm
9. Publisher clears diffs ≤ N
10. Normal callback flow resumes
```

**Key Points**:
- Automatic recovery from sequence gaps
- No manual intervention required
- Baseline fetch as fallback when diffs unavailable

## Duplicate Callback Flow

```
1. Publisher sends callback sequence=5
2. Subscriber already at sequence=5 (or higher)
3. CallbackProcessor detects: seq=5 ≤ last_seq=5
4. CallbackProcessor returns DUPLICATE (no processing)
5. Subscriber returns 204 to publisher (idempotent behavior)
6. Publisher does not delete diff
7. Later sync sends PUT {sequence: 5} → diff cleared
```

**Key Points**:
- Duplicates detected and safely ignored
- Idempotent behavior (204 response)
- No data corruption from redelivery

## Publisher-Initiated Resync Flow

```
1. Publisher calls suspend_subscriptions(target, subtarget)
2. Publisher makes bulk changes without diff registration
3. Publisher calls resume_subscriptions(target, subtarget)
4. For each subscription:
   a. Check peer capabilities: caps.supports_resync_callbacks()
   b. Increment subscription sequence

   If peer supports resync:
   c. Send resync callback:
      - type: "resync"
      - url: publisher's resource URL
      - sequence: new sequence number

   If peer does NOT support resync:
   c. Send low-granularity callback:
      - granularity: "low"
      - url: publisher's resource URL
      - sequence: new sequence number

5. Subscriber receives resync/low-granularity callback
6. CallbackProcessor handles resync type:
   - Clears pending queue
   - Resets state
   - Invokes handler with full data
7. Subscriber fetches full state from URL if needed
8. Subscriber updates sequence from callback
9. Subscriber returns 204
```

**Key Points**:
- Explicit resync mechanism for bulk changes
- Peer capability detection for protocol version compatibility
- Fallback to low-granularity for older peers

## Sync Operation Flow (Pull-Based)

```
1. Subscriber calls sync_subscription(peer_id, subscription_id)
2. Subscriber GET /subscriptions/{subscriber_id}/{sub_id} from publisher
3. Publisher returns:
   - Subscription metadata (sequence, target, etc.)
   - Array of available diffs since last confirmed sequence

4a. If diffs available:
    - Sort diffs by sequence
    - Process each diff through CallbackProcessor
    - Count: diffs_processed (may be < diffs_fetched if duplicates)
    - Update local sequence to max processed sequence
    - Send PUT {sequence: N} to confirm → Publisher clears diffs ≤ N

4b. If no diffs available:
    - Fetch baseline from target resource
    - Apply baseline data (replaces all existing data)
    - Update local sequence from subscription metadata
    - No PUT needed (no diffs to clear)

4c. If diffs available but all rejected as duplicates:
    - diffs_fetched > 0, diffs_processed = 0
    - Fall back to baseline fetch (NEW FIX)
    - Apply baseline data
    - Update sequence
```

**Key Points**:
- Pull-based sync complements push callbacks
- Baseline fetch when diffs unavailable
- Duplicate detection during sync
- Fallback to baseline on all-duplicate scenario

## Failure Situations and Fixes

### 1. False Duplicate Detection on Optimistic Lock Retry

**Problem**:
```
Attempt 1:
- Update subscription sequence to N ← DONE
- Update CallbackProcessor state ← FAILS (version conflict)
- Retry...

Attempt 2:
- Read subscription sequence → N (already updated!)
- Incoming callback sequence = N
- seq=N ≤ last_seq=N → DUPLICATE (WRONG!)
```

**Root Cause**: Sequence updated BEFORE state update succeeded, so retry saw already-updated sequence.

**Fix**: Reorder operations in CallbackProcessor:
```
1. Update CallbackProcessor state (optimistic lock check) ← FIRST
2. Invoke handler (process callback)
3. Update subscription sequence ← LAST (after success)
```

**Impact**: Prevents false duplicate detection on retry, ensures callbacks processed exactly once.

**Files Changed**: `actingweb/callback_processor.py`

### 2. Diff Deleted Before Subscriber Processing

**Problem**:
```
1. Publisher sends callback seq=20 → gets 204
2. Publisher immediately deletes diff 20 ← TOO EARLY
3. Subscriber added callback to pending queue (gap detected)
4. Gap timeout triggers resync
5. Subscriber syncs: GET /subscriptions/{id} → 0 diffs (already deleted!)
6. Subscriber has no data for sequences that were "delivered"
```

**Root Cause**: 204 means "received", not "processed". Subscriber may queue callback due to gaps.

**Fix**: Remove immediate diff clearing after 204:
```python
# OLD CODE (REMOVED):
if response.status_code == 204:
    sub_obj.clear_diff(diff["sequence"])

# NEW BEHAVIOR:
# Diffs only cleared when subscriber sends PUT {sequence: N} to confirm processing
```

**Impact**: Diffs remain available until subscriber confirms processing, enabling recovery from gaps.

**Files Changed**: `actingweb/actor.py:1673-1677, 1720-1725`

### 3. Gap Timeout No Automatic Resync

**Problem**:
```
1. Gap timeout triggers → CallbackProcessor returns RESYNC_TRIGGERED
2. Handler checks success = result in (PROCESSED, DUPLICATE, PENDING)
3. RESYNC_TRIGGERED not in list → success = False
4. Subscriber returns 400 Bad Request ← Publisher sees failure
5. No automatic resync occurs
6. Subscription stuck permanently out of sync
```

**Root Cause**: RESYNC_TRIGGERED not recognized as successful result, no automatic sync triggered.

**Fix**:
1. Add RESYNC_TRIGGERED to success list (return 200 not 400)
2. Automatically call sync_subscription() when RESYNC_TRIGGERED detected:
```python
success = result in (PROCESSED, DUPLICATE, PENDING, RESYNC_TRIGGERED)

if result == RESYNC_TRIGGERED:
    mgr = SubscriptionManager(actor_interface._core_actor)
    sync_result = mgr.sync_subscription(peer_id, subscription_id)
```

**Impact**: Subscriptions automatically recover from sequence gaps without manual intervention.

**Files Changed**: `actingweb/handlers/callbacks.py:555-594`

### 4. increase_seq() Returns Boolean Instead of Integer

**Problem**:
```
def increase_seq(self):
    self.subscription["sequence"] += 1
    return self.handle.modify(seqnr=self.subscription["sequence"])  # Returns True!

# In _increment_subscription_sequence():
new_seq = sub_obj.increase_seq()  # new_seq = True (not integer!)
return new_seq if new_seq else 1  # Returns True (truthy!)

# In callback payload:
"sequence": new_seq  # "sequence": True

# On subscriber side:
sequence = params.get("sequence", 0)  # sequence = True
sub.handle.modify(seqnr=sequence)  # PostgreSQL: "column seqnr is of type integer but expression is of type boolean"
```

**Root Cause**: Method returns database operation success (boolean), not the new sequence number.

**Fix**: Return the new sequence value:
```python
def increase_seq(self):
    self.subscription["sequence"] += 1
    if not self.handle.modify(seqnr=self.subscription["sequence"]):
        return False  # Operation failed
    return self.subscription["sequence"]  # Return new sequence (int)
```

**Impact**: Prevents PostgreSQL type errors, callbacks contain correct integer sequences.

**Files Changed**: `actingweb/subscription.py:93-104`

### 5. Peer Capabilities Not Loaded Before Check

**Problem**:
```
caps = PeerCapabilities(actor_interface, peer_id)
supports_resync = caps.supports_resync_callbacks()  # Returns False (default)
# Never called ensure_loaded() → capabilities never fetched!
```

**Root Cause**: Capabilities are lazy-loaded, but check happened before load.

**Fix**: Explicitly load capabilities before checking:
```python
caps = PeerCapabilities(actor_interface, peer_id)
caps.ensure_loaded()  # Fetches from peer's /meta/actingweb/supported
supports_resync = caps.supports_resync_callbacks()
```

**Impact**: Correct resync support detection, uses resync callbacks when available.

**Files Changed**: `actingweb/actor.py:2048-2055`

### 6. Redundant CallbackProcessor Invocation

**Problem**:
```
Flow 1: POST /callbacks/subscriptions/... → CallbacksHandler
  → _process_subscription_callback_internal()
  → CallbackProcessor.process_callback()  # FIRST PROCESSING
  → User hooks invoked

Flow 2 (old, WRONG): In CallbackProcessor handler
  → _internal_subscription_handler hook registered
  → _process_subscription_callback()
  → ANOTHER CallbackProcessor instance  # SECOND PROCESSING
  → User hooks invoked AGAIN
```

**Root Cause**: Leftover code from old architecture where CallbackProcessor was part of hook system.

**Fix**: Remove redundant methods and invoke hooks directly:
```python
# REMOVED:
# - _register_internal_subscription_handler()
# - _process_subscription_callback()
# - _invoke_subscription_data_hooks()

# NEW: Invoke hooks directly in callbacks.py handler after CallbackProcessor validation
```

**Impact**: Callbacks processed once, no duplicate logs, reduced database load.

**Files Changed**: `actingweb/interface/app.py`, `actingweb/handlers/callbacks.py`, `actingweb/subscription_config.py`

### 7. Sync With All-Duplicate Diffs Skips Baseline

**Problem**:
```
1. First sync: GET /subscriptions/{id}
   - Publisher returns diffs 22-25 (not yet cleared)
   - Subscriber at sequence 25 (already current)
   - CallbackProcessor rejects all as duplicates
   - diffs_fetched = 4, diffs_processed = 0
   - Baseline check: if diffs_fetched == 0 → False, skip baseline
   - Result: No data fetched, sequence updated

2. First sync sends PUT {sequence: 25} → clears diffs 22-25

3. Second sync: GET /subscriptions/{id}
   - Publisher returns 0 diffs (cleared by first sync)
   - diffs_fetched = 0
   - Baseline check: if diffs_fetched == 0 → True, fetch baseline
   - Result: Data fetched successfully
```

**Root Cause**: Baseline fetch only triggered when NO diffs returned, not when all diffs rejected.

**Fix**: Fall back to baseline when all diffs rejected:
```python
# After processing diffs:
if diffs_fetched > 0 and diffs_processed == 0 and config.auto_storage:
    # All diffs were duplicates/rejected, fetch baseline to ensure sync
    baseline_response = proxy.get_resource(path=target_path)
    store.apply_resync_data(baseline_response)
```

**Impact**: First sync correctly fetches data even when diffs are duplicates, eliminates "first sync does nothing" pattern.

**Files Changed**: `actingweb/interface/subscription_manager.py`

## State Diagram

```
┌─────────────┐
│  Subscriber │
│  Sequence=N │
└──────┬──────┘
       │
       ├─ Callback seq=N+1 arrives ──┐
       │                              │
       │                              ▼
       │                    ┌────────────────┐
       │                    │ Seq Validation │
       │                    └────────┬───────┘
       │                             │
       ├─────────────────────────────┼──────────────────┐
       │                             │                  │
   seq=N+1                       seq>N+1            seq≤N
   (VALID)                        (GAP)          (DUPLICATE)
       │                             │                  │
       ▼                             ▼                  ▼
┌──────────────┐            ┌──────────────┐    ┌──────────┐
│   PROCESS    │            │  ADD PENDING │    │  IGNORE  │
│              │            │              │    │          │
│ 1. Update    │            │ Start timer  │    │ Return   │
│    state     │            │ (5 sec)      │    │ 204      │
│ 2. Handler   │            │              │    │          │
│ 3. Update    │            │ Return 204   │    └──────────┘
│    sequence  │            │ (queued)     │
│              │            └──────┬───────┘
│ Return 204   │                   │
└──────────────┘                   │
                                   ├──── Missing callback arrives ──┐
                                   │                                 │
                                   │                                 ▼
                                   │                        ┌────────────────┐
                                   │                        │  PROCESS ALL   │
                                   │                        │  IN SEQUENCE   │
                                   │                        └────────────────┘
                                   │
                                   └──── Timeout (5 sec) ───┐
                                                            │
                                                            ▼
                                                  ┌──────────────────┐
                                                  │ RESYNC_TRIGGERED │
                                                  │                  │
                                                  │ Auto call        │
                                                  │ sync_subscription│
                                                  │                  │
                                                  │ Fetch baseline   │
                                                  │ Update sequence  │
                                                  └──────────────────┘
```

## Test Coverage Requirements

Based on these flows and failures, integration tests should cover:

1. **Normal callback flow** - Happy path, no gaps
2. **Gap detection** - Callback creates gap, goes to pending
3. **Gap resolution** - Missing callback arrives, pending processed
4. **Gap timeout** - Timeout triggers automatic resync
5. **Duplicate handling** - Duplicate callback safely ignored
6. **Sequence ordering** - Sequence updated after handler success, not before
7. **Diff retention** - Diffs not deleted on 204, only on PUT confirm
8. **Sync with duplicates** - All diffs rejected → baseline fetch
9. **Resync with support** - Peer supports resync → uses resync callback
10. **Resync without support** - Peer doesn't support → uses low-granularity
11. **increase_seq type** - Returns integer, not boolean
12. **Baseline fetch** - No diffs → fetches baseline
13. **No redundant processing** - Callback processed exactly once
14. **Peer capabilities** - Capabilities loaded before check

## Performance Characteristics

- **Gap timeout**: 5 seconds default (configurable)
- **Max pending**: 100 callbacks default (configurable)
- **Optimistic lock retries**: 3 attempts with exponential backoff
- **Diff storage**: Persistent until confirmed (can accumulate if subscriber offline)
- **Baseline fetch**: On-demand, only when diffs unavailable or all rejected

## Protocol Compatibility

- **Resync callbacks**: Protocol v1.4+ feature, checked via peer capabilities
- **Fallback behavior**: Low-granularity callbacks for older peers
- **Backward compatible**: Works with peers not supporting latest protocol features
