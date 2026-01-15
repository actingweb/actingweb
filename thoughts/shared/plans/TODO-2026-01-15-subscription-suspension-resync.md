# TODO: Property-Level Subscription Suspension and Resync Callback

## Status

**Spec:** COMPLETED (v1.4)
**Implementation:** PENDING

---

## Completed Work

### Spec Updates (v1.4)

The following have been added to `docs/protocol/actingweb-spec.rst`:

1. **Option tag**: `subscriptionresync` - signals support for resync callbacks
2. **Resync Callback section** - documents the `type: "resync"` callback format
3. **Changelog entry** - v1.4 now includes resync callback support

---

## Pending Implementation

### Problem Statement

When many property changes occur rapidly (e.g., bulk imports, migrations, batch updates), the current subscription system has limitations:

1. **Diff accumulation**: Each change creates a diff entry, potentially overwhelming storage
2. **Callback storms**: High-granularity subscriptions trigger a callback for each change
3. **Out-of-sync risk**: Failed callbacks or network issues can cause peers to miss diffs
4. **No recovery mechanism**: Peers must manually detect and handle gaps in sequence numbers

### Solution Design

**Key insight**: Multiple subscriptions can exist on the same property/subtarget. Suspension must be at the **property level** (target/subtarget), not per-subscription. When suspension is lifted, ALL affected subscriptions receive a resync callback.

### Core Concepts

1. **Property Suspension**: Actor-level state that pauses diff registration for a specific target/subtarget
2. **Resync Callback**: Special callback type (`type: "resync"`) telling peers to do a full GET
3. **Manual control only**: Application explicitly suspends/resumes via developer API
4. **No diff storage during suspension**: Diffs are not registered while suspended

---

## Developer API Design

Suspension is controlled via the Python developer API only (not exposed via REST endpoints).

### Usage Example

```python
from actingweb.interface import ActorInterface

actor = ActorInterface(actor_id="abc123", config=config)

# Suspend diff registration for a target/subtarget
actor.subscriptions.suspend(target="properties", subtarget="memory_travel")

# Perform bulk operations - no diffs registered, no callbacks sent
for item in large_import_data:
    actor.properties.set("memory_travel", item)

# Resume - sends resync callback to all affected subscriptions
actor.subscriptions.resume(target="properties", subtarget="memory_travel")
```

### Resync Callback Payload

```json
{
  "id": "actor123",
  "subscriptionid": "sub456",
  "target": "properties",
  "subtarget": "memory_travel",
  "sequence": 7,
  "timestamp": "2026-01-15T12:00:00.000000Z",
  "granularity": "high",
  "type": "resync",
  "url": "https://example.com/actor123/properties/memory_travel"
}
```

---

## Data Model

### New: Suspension State Table

**DynamoDB:**
```python
class SubscriptionSuspension(Model):
    class Meta:
        table_name = "subscription_suspensions"

    id = UnicodeAttribute(hash_key=True)  # actor_id
    target_key = UnicodeAttribute(range_key=True)  # "target:subtarget"
    target = UnicodeAttribute()
    subtarget = UnicodeAttribute(null=True)
    suspended_at = UTCDateTimeAttribute()
```

**PostgreSQL:**
```sql
CREATE TABLE subscription_suspensions (
    id VARCHAR(255) NOT NULL,        -- actor_id
    target VARCHAR(255) NOT NULL,
    subtarget VARCHAR(255),
    suspended_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id, target, subtarget)
);
```

---

## Implementation Phases

### Phase 1: Data Model (Database Layer)

| File | Change |
|------|--------|
| `actingweb/db/dynamodb/subscription_suspension.py` | **NEW** - Suspension model |
| `actingweb/db/postgresql/subscription_suspension.py` | **NEW** - Suspension model |
| `actingweb/db/postgresql/schema.py` | Add suspension table |
| `actingweb/db/postgresql/migrations/versions/xxx_*.py` | **NEW** - Alembic migration |
| `actingweb/db/protocols.py` | Add `SubscriptionSuspensionProtocol` |

### Phase 2: Core Logic

| File | Change |
|------|--------|
| `actingweb/actor.py` | Add `suspend_subscriptions()`, `resume_subscriptions()`, `is_suspended()` |
| `actingweb/actor.py` | Modify `register_diffs()` to check suspension |
| `actingweb/actor.py` | Modify `callback_subscription()` to support `type: "resync"` |

### Phase 3: Interface Layer (Developer API)

| File | Change |
|------|--------|
| `actingweb/interface/subscription_manager.py` | Add `suspend()`, `resume()` methods |

### Phase 4: Testing

| File | Change |
|------|--------|
| `tests/integration/test_subscription_suspension.py` | **NEW** - Integration tests |

---

## Sequence Number Handling

| Event | Sequence Change |
|-------|-----------------|
| Suspend | No change |
| Property change while suspended | No change (diff not registered) |
| Resume | Increment by 1 for each affected subscription |
| Resync callback | Includes new sequence number |

---

## Verification Plan

1. **Unit tests:**
   - Suspension state creation/deletion
   - `is_suspended()` logic with various scopes
   - `register_diffs()` skip behavior when suspended

2. **Integration tests:**
   - Full suspend → property changes → resume flow
   - Verify no diffs registered during suspension
   - Verify resync callbacks sent to all affected subscriptions
   - Verify sequence number increment on resume

3. **Edge cases:**
   - Suspend with no existing subscriptions
   - Resume when already not suspended
   - Multiple overlapping suspensions (target vs target/subtarget)
   - Subscription created during suspension period
