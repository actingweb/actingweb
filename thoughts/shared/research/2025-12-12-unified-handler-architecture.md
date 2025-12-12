---
date: 2025-12-12T10:30:00-08:00
researcher: Claude
git_commit: 28556b11ad477f387f240cea92b4f6b08fb3a23c
branch: master
repository: actingweb/actingweb
topic: "Unified Handler Architecture: Flask, FastAPI, and Developer API Alignment"
tags: [research, architecture, handlers, developer-api, fastapi, flask, register_diffs, subscriptions]
status: complete
last_updated: 2025-12-12
last_updated_by: Claude
last_updated_note: "Replaced auth_context parameter with authenticated views pattern (as_peer, as_client methods)"
---

# Research: Unified Handler Architecture for Flask, FastAPI, and Developer API

**Date**: 2025-12-12T10:30:00-08:00
**Researcher**: Claude
**Git Commit**: 28556b11ad477f387f240cea92b4f6b08fb3a23c
**Branch**: master
**Repository**: actingweb/actingweb

## Research Question

Review the FastAPI integration and developer API to identify how to modify the Python developer API and move functionality to ensure consistent behavior regardless of whether core actor, trust, subscription functionality is triggered from FastAPI, Flask, or the developer API.

## Summary

There are significant architectural gaps between the handler layer (used by Flask/FastAPI) and the developer API interfaces. The handlers include important functionality like:

1. **Subscription notifications** (`register_diffs`) - Handlers automatically notify subscribers after property changes
2. **Lifecycle hooks** - Handlers trigger `trust_approved`, `trust_deleted` lifecycle hooks
3. **Permission checking** - Handlers integrate with the unified access control system
4. **Verified trust creation** - Handlers implement the full ActingWeb trust verification protocol

The developer API (`ActorInterface`, `TrustManager`, `SubscriptionManager`) provides a cleaner interface but bypasses much of this functionality. Applications using the developer API directly will not get subscription notifications unless they explicitly call `actor.subscriptions.notify_subscribers()`.

## Detailed Findings

### Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HTTP Requests                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
          ┌─────────▼─────────┐          ┌─────────▼─────────┐
          │ Flask Integration │          │ FastAPI Integration│
          │  (flask_integration.py)     │ (fastapi_integration.py)
          └─────────┬─────────┘          └─────────┬─────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │         HANDLERS              │
                    │  (actingweb/handlers/*.py)    │
                    │  - properties.py              │
                    │  - trust.py                   │
                    │  - subscription.py            │
                    │  + register_diffs()           │
                    │  + lifecycle hooks            │
                    │  + permission checks          │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │        CORE ACTOR             │
                    │    (actingweb/actor.py)       │
                    │  - register_diffs()           │
                    │  - callback_subscription()    │
                    │  - create_verified_trust()    │
                    └───────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        Developer Applications                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      DEVELOPER API            │
                    │  (actingweb/interface/*.py)   │
                    │  - ActorInterface             │
                    │  - PropertyStore              │  ← NO register_diffs!
                    │  - TrustManager               │  ← NO lifecycle hooks!
                    │  - SubscriptionManager        │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │        CORE ACTOR             │
                    │    (actingweb/actor.py)       │
                    └───────────────────────────────┘
```

### Gap 1: Property Modifications and register_diffs

**Handler behavior** (`actingweb/handlers/properties.py`):

| Operation | Handler Code | Subscription Notification |
|-----------|-------------|---------------------------|
| PUT property | Line 424 | `myself.register_diffs(target="properties", subtarget=name, blob=body)` |
| PUT nested | Line 472-474 | `myself.register_diffs(target="properties", subtarget=name, resource=resource, blob=blob)` |
| POST property | Line 837 | `myself.register_diffs(target="properties", blob=out)` |
| DELETE property | Line 944 | `myself.register_diffs(target="properties", subtarget=name, blob="")` |
| DELETE all | Line 876 | `myself.register_diffs(target="properties", subtarget=None, blob="")` |

**Developer API behavior** (`actingweb/interface/property_store.py`):

```python
# PropertyStore.__setitem__ at line 36-38
def __setitem__(self, key: str, value: Any) -> None:
    self._core_store[key] = value  # NO register_diffs called!
```

**Property Lists** (`actingweb/property_list.py`):

```python
# ListProperty.append at lines 275-299
def append(self, item: Any) -> None:
    # ... serializes and stores item
    # NO register_diffs called!
```

**However**, the `PropertyListItemsHandler` in `handlers/properties.py:1315-1320` DOES call register_diffs for list operations:

```python
# Line 1315-1320 (POST /properties/{name}/items)
myself.register_diffs(
    target="properties",
    subtarget=name,
    blob=json.dumps(
        {"action": "add", "index": len(list_prop) - 1, "value": item_value}
    ),
)
```

### Gap 2: Trust Management and Lifecycle Hooks

**Handler behavior** (`actingweb/handlers/trust.py`):

| Operation | Handler | Lifecycle Hook |
|-----------|---------|----------------|
| POST approval notification | Line 456-491 | `trust_approved` triggered |
| DELETE trust | Line 658-671 | `trust_deleted` triggered |
| Create verified trust | Line 273-283 | Verification callback to peer |

**Developer API behavior** (`actingweb/interface/trust_manager.py`):

```python
# TrustManager.approve_relationship at lines 201-210
def approve_relationship(self, peer_id: str) -> bool:
    trust_rel = self._core_actor.get_trust_relationship(peer_id)
    # ... calls modify_trust_and_notify with approved=True
    # NO trust_approved lifecycle hook!
```

**Missing in TrustManager**:
- `create_verified_trust()` - Used for incoming peer trust requests
- Permission override management via `TrustPermissionStore`
- `trustee_root` management
- Shared properties query

### Gap 3: Subscription Management

**Handler behavior** (`actingweb/handlers/subscription.py`):

- Accepts incoming subscription requests via `create_subscription()` (line 193)
- Provides diff retrieval and clearing (lines 255-332, 354-400)

**Developer API behavior** (`actingweb/interface/subscription_manager.py`):

```python
# Only outbound subscriptions supported
def subscribe_to_peer(...) -> SubscriptionInfo | None:
    return self._core_actor.create_remote_subscription(...)

# No method to accept incoming subscriptions
# No diff management methods
```

## Proposed Architecture: Extract Business Logic to Developer API

After further analysis, the correct approach is to **move business logic INTO the developer API** and have handlers call the developer API. This avoids code duplication and ensures a single source of truth.

### Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        HTTP Request                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │    Unified HTTP Layer         │   ← Thin, shared
                    │  (request parsing, response)  │
                    └───────────────┬───────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
    ┌─────▼─────┐            ┌─────▼─────┐            ┌─────▼─────┐
    │  Flask    │            │  FastAPI  │            │  Direct   │
    │ Response  │            │ Response  │            │   Call    │
    └───────────┘            └───────────┘            └───────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │      DEVELOPER API            │   ← Business logic here
                    │  (Single source of truth)     │
                    │                               │
                    │  PropertyStore                │
                    │    .set(name, value)          │
                    │    → permission check         │
                    │    → execute hooks            │
                    │    → store value              │
                    │    → register_diffs           │
                    │                               │
                    │  TrustManager                 │
                    │    .approve(peer_id)          │
                    │    → permission check         │
                    │    → modify trust             │
                    │    → notify peer              │
                    │    → execute lifecycle hooks  │
                    │                               │
                    │  SubscriptionManager          │
                    │    .create_subscription()     │
                    │    .notify_subscribers()      │ ← Already has this!
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │        CORE ACTOR             │   ← Pure data operations
                    │    (Database operations)      │
                    └───────────────────────────────┘
```

### Why This Approach

1. **Single source of truth**: Business logic lives in one place (developer API)
2. **No code duplication**: Handlers don't duplicate logic that's in developer API
3. **Handlers become thin**: Just HTTP parsing → call developer API → HTTP response
4. **Flask/FastAPI can share more code**: They differ only in request/response handling
5. **Developer API gets full functionality**: Same behavior whether called from HTTP or directly
6. **Easier testing**: Test business logic without HTTP layer

### Key Insight: Flask/FastAPI Are Nearly Identical

Analysis of `flask_integration.py` and `fastapi_integration.py` shows:

| Aspect | Flask | FastAPI |
|--------|-------|---------|
| Handler dictionary | Identical | Identical |
| Handler selection logic | Identical | Identical |
| Argument building | 90% identical | 90% identical |
| Error handling | Identical | Identical |
| Template mappings | Identical | Identical |

The only real differences:
- FastAPI uses `async`/`await` and wraps sync handlers in `run_in_executor()`
- FastAPI explicitly passes `request` object; Flask uses global `request`

This confirms they should share a common HTTP handling layer.

### Handler Code Distribution

Analysis of `properties.py` handler shows:

| Category | Approximate % |
|----------|---------------|
| HTTP-specific (parsing, responses, status codes) | ~25% |
| Business logic (validation, hooks, register_diffs) | ~75% |

The 75% business logic should move to the developer API.

### Comparison with Previous Option B

**Previous Option B** (rejected): Add `register_diffs` calls to developer API alongside existing handler calls.

**Problem**: This duplicates the business logic - handlers would still have their own `register_diffs` calls, and developer API would have separate calls. Two places to maintain.

**New approach**: Extract business logic FROM handlers INTO developer API, then refactor handlers to CALL the developer API. One place to maintain.

### Example: Property SET Operation

**Current state** (logic split):
```
Handler.put():
    parse request
    check permissions          ← business logic in handler
    execute hooks              ← business logic in handler
    core_store[key] = value    ← data operation
    register_diffs()           ← business logic in handler
    set response status

Developer API PropertyStore.__setitem__():
    core_store[key] = value    ← data operation only
    # NO permissions, hooks, or register_diffs
```

**Target state** (logic in developer API with authenticated views):
```
Handler.put():
    parse request
    actor = ActorInterface.get_by_id(actor_id, config)
    view = actor.as_peer(peer_id, trust)  ← create authenticated view
    view.properties[key] = value          ← all logic encapsulated
    set response status

                    │
                    ▼

AuthenticatedPropertyStore.__setitem__(key, value):
    _enforce_permission(key, "write")     ← permission check
    self._store[key] = value              ← delegate to base store

                    │
                    ▼

PropertyStore.__setitem__(key, value):
    execute_property_hooks()              ← transform/validate
    core_store[key] = value               ← store value
    register_diffs()                      ← notify subscribers
```

### Components to Refactor

1. **ActorInterface**: Add `as_peer()`, `as_client()` methods returning AuthenticatedActorView
2. **AuthenticatedActorView** (NEW): Wrapper with permission-enforced property access
3. **AuthenticatedPropertyStore** (NEW): Wrapper enforcing permissions, delegating to PropertyStore
4. **AuthenticatedPropertyListStore** (NEW): Wrapper for property list operations
5. **AuthenticatedSubscriptionManager** (NEW): Wrapper for subscription operations
6. **PropertyStore**: Add hooks execution and `register_diffs()` to `__setitem__`, `__delitem__`
7. **ListProperty**: Add `register_diffs()` to `append()`, `__setitem__()`, `__delitem__()`
8. **TrustManager**: Add lifecycle hooks to `approve_relationship()`, `delete_relationship()`
9. **SubscriptionManager**: Already has `notify_subscribers()` - may need permission filtering
10. **Handlers**: Refactor to use authenticated views instead of implementing logic directly
11. **Flask/FastAPI integrations**: Extract shared HTTP handling code

## Code References

### Current Handler Business Logic (to be extracted)
- `actingweb/handlers/properties.py:50-117` - `_check_property_permission()` permission checking
- `actingweb/handlers/properties.py:398-417` - Hook execution in PUT
- `actingweb/handlers/properties.py:424` - `register_diffs()` after PUT
- `actingweb/handlers/properties.py:472-474` - `register_diffs()` for nested paths
- `actingweb/handlers/properties.py:1315-1320` - `register_diffs()` for list items
- `actingweb/handlers/trust.py:456-491` - `trust_approved` lifecycle hook
- `actingweb/handlers/trust.py:658-671` - `trust_deleted` lifecycle hook

### Current Developer API (thin wrappers)
- `actingweb/interface/property_store.py:36-38` - `__setitem__` just delegates
- `actingweb/property_list.py:275-299` - `append()` just stores
- `actingweb/interface/trust_manager.py:201-210` - `approve_relationship()` no hooks
- `actingweb/interface/subscription_manager.py:186-203` - `notify_subscribers()` ← already has register_diffs

### Core Actor (data operations)
- `actingweb/actor.py:1426-1641` - `register_diffs()` implementation
- `actingweb/actor.py:667-751` - `modify_trust_and_notify()`
- `actingweb/actor.py:961-1064` - `delete_reciprocal_trust()`

### Flask/FastAPI Integrations (nearly identical)
- `actingweb/interface/integrations/flask_integration.py:1335-1484` - `_handle_actor_request()`
- `actingweb/interface/integrations/fastapi_integration.py:2129-2281` - `_handle_actor_request()`
- Both use identical handler dictionaries and argument building logic

## Architecture Insights

### Current State
1. **Three-tier design**: HTTP integrations → Handlers → Core Actor
2. **Developer API bypasses handlers**: Goes directly to Core Actor, missing business logic
3. **Business logic scattered**: 75% of handler code is business logic that should be reusable
4. **Flask/FastAPI duplicate code**: Nearly identical implementations

### Target State
1. **Four-tier design**: HTTP integrations → Thin Handlers → Developer API → Core Actor
2. **Developer API is single source of truth**: All business logic in one place
3. **Handlers become thin**: Just HTTP parsing and response building
4. **Flask/FastAPI share HTTP layer**: Common code extracted

## Open Questions

1. **Backward compatibility**: ✅ Resolved - `__setitem__` on `actor.properties` remains owner mode; authenticated views are additive
2. **Permission context**: ✅ Resolved - authenticated views (`as_peer()`, `as_client()`) carry identity; direct access is owner mode
3. **Bulk operations**: Confirmed no `set_many()` - keep operations simple
4. **Hook dependency**: ✅ Resolved - wire hooks through ActorInterface constructor and pass to managers
5. **Async support**: Partially resolved - need async variants for Actor methods that make outbound HTTP calls

## Recommendations

### Guiding Principle
**Same operation, same behavior** - whether triggered via HTTP or developer API.

### Migration Strategy
1. **Phase 1**: Enhance developer API with full business logic (permissions, hooks, register_diffs)
2. **Phase 2**: Refactor handlers to call developer API instead of implementing logic directly
3. **Phase 3**: Extract shared HTTP handling code from Flask/FastAPI integrations
4. **Phase 4**: Deprecate direct core Actor access where appropriate

### Backward Compatibility
- Keep `__setitem__` working on `actor.properties` - this remains owner mode (no permission checks)
- Authenticated views (`as_peer()`, `as_client()`) are new, additive API - no breaking changes
- PropertyStore gains hooks and register_diffs behavior - existing code benefits automatically
- Add deprecation warnings for direct handler instantiation outside of integrations

---

## Follow-up Research: Additional Requirements

### 1. External Web Framework Support

**Goal**: Enable developers to use ActingWeb with frameworks other than Flask/FastAPI (e.g., Django, Starlette, Quart).

**Current State**:
- Flask and FastAPI integrations are nearly identical (~90% shared logic)
- Both use handlers from `actingweb/handlers/` which are framework-agnostic
- Request/response abstraction exists via `AWWebObj` (`aw_web_request.py`)

**Required for External Framework Support**:

1. **Request Normalization Interface**: Document the expected format for `AWWebObj`:
   ```python
   webobj = AWWebObj(
       url=str,           # Full request URL
       params=dict,       # Query parameters + form data
       body=bytes|str,    # Request body
       headers=dict,      # HTTP headers (including Authorization)
       cookies=dict,      # Cookies (especially oauth_token)
   )
   ```

2. **Response Handling**: Document how to read from `webobj.response`:
   - `status_code`, `status_message`
   - `body`, `headers`, `cookies`
   - `redirect` (for 302 responses)
   - `template_values` (for HTML rendering)

3. **Handler Invocation Pattern**: Expose a documented way to invoke handlers:
   ```python
   from actingweb.handlers import properties

   handler = properties.PropertiesHandler(webobj, config, hooks=hooks)
   handler.put(actor_id, name)  # Returns via webobj.response
   ```

4. **Authentication Helpers**: `check_and_verify_auth()` and `check_and_verify_auth_async()` already support any framework via `AWWebObj`.

**Recommendation**: Create `actingweb/interface/integrations/base_integration.py` documenting the integration contract.

---

### 2. Property List Gaps

**Critical Finding**: Property list item operations do NOT trigger subscription diffs.

| Operation | Location | Calls register_diffs? |
|-----------|----------|----------------------|
| PUT /properties/{name} | PropertiesHandler.put():424 | **Yes** |
| POST /properties | PropertiesHandler.post():837 | **Yes** |
| DELETE /properties/{name} | PropertiesHandler.delete():944 | **Yes** |
| DELETE /properties/{list} | PropertiesHandler.delete():912 | **Yes** |
| POST /properties/{list}/items (add) | PropertyListItemsHandler.post() | **NO** |
| POST /properties/{list}/items (update) | PropertyListItemsHandler.post() | **NO** |
| POST /properties/{list}/items (delete) | PropertyListItemsHandler.post() | **NO** |
| PUT /properties/{list}/metadata | PropertyMetadataHandler.put() | **NO** |
| ListProperty.append() | property_list.py:275-299 | **NO** |
| ListProperty.insert() | property_list.py:397-437 | **NO** |
| ListProperty.__setitem__() | property_list.py:189-218 | **NO** |
| ListProperty.__delitem__() | property_list.py:220-269 | **NO** |

**Additional Gap**: `GET /properties` (without `?metadata=true`) does NOT include list properties in response. List properties are stored with `list:` prefix and filtered out by default.

**Fix Required**: Add `register_diffs()` calls to:
1. `PropertyListItemsHandler.post()` for add/update/delete actions
2. `PropertyMetadataHandler.put()` for metadata changes
3. `ListProperty` methods when accessed via developer API

**Diff Format for List Operations** (proposed):
```json
{"action": "add", "index": 5, "value": {...}}
{"action": "update", "index": 3, "value": {...}}
{"action": "delete", "index": 2}
{"action": "metadata", "description": "...", "explanation": "..."}
```

---

### 3. Authenticated Views Pattern

**Problem**: When developer API is called directly (not via HTTP), there's no auth context. But some operations need to identify the remote actor/client for permission checks.

**Design Insight**: Using `actor.properties.set("key", value, auth_context=...)` is confusing because `actor.properties` conceptually refers to the actor's data, not who is accessing it. This mixes two distinct concerns.

**Solution: Authenticated Views**

Instead of passing auth_context as a parameter, create authenticated views of the actor that carry the identity context.

```python
class ActorInterface:
    def as_peer(self, peer_id: str, trust_relationship: dict) -> "AuthenticatedActorView":
        """Create a view of this actor as seen by a peer.

        All operations on this view will have permission checks enforced
        based on the peer's trust relationship.
        """
        return AuthenticatedActorView(
            self,
            auth_context={"peer_id": peer_id, "trust_relationship": trust_relationship}
        )

    def as_client(self, client_id: str, trust_relationship: dict) -> "AuthenticatedActorView":
        """Create a view of this actor as seen by an OAuth2/MCP client.

        All operations on this view will have permission checks enforced
        based on the client's trust relationship.
        """
        return AuthenticatedActorView(
            self,
            auth_context={"client_id": client_id, "trust_relationship": trust_relationship}
        )


class AuthenticatedActorView:
    """A view of an actor with enforced permission checks.

    This class wraps ActorInterface and enforces permission checks on all
    operations based on the auth_context provided at construction time.
    """

    def __init__(self, actor: ActorInterface, auth_context: dict):
        self._actor = actor
        self._auth_context = auth_context

    @property
    def properties(self) -> "AuthenticatedPropertyStore":
        """Property store with permission checks enforced."""
        return AuthenticatedPropertyStore(
            self._actor.properties,
            self._auth_context,
            self._actor._hooks
        )

    @property
    def property_lists(self) -> "AuthenticatedPropertyListStore":
        """Property list store with permission checks enforced."""
        return AuthenticatedPropertyListStore(
            self._actor.property_lists,
            self._auth_context,
            self._actor._hooks
        )

    @property
    def subscriptions(self) -> "AuthenticatedSubscriptionManager":
        """Subscription manager with permission checks enforced."""
        return AuthenticatedSubscriptionManager(
            self._actor.subscriptions,
            self._auth_context
        )


class AuthenticatedPropertyStore:
    """Property store wrapper that enforces permission checks."""

    def __init__(self, property_store: PropertyStore, auth_context: dict, hooks):
        self._store = property_store
        self._auth_context = auth_context
        self._hooks = hooks

    def __setitem__(self, key: str, value: Any) -> None:
        self._check_write_permission(key)
        self._store[key] = value
        self._register_diff(key, value)

    def __getitem__(self, key: str) -> Any:
        self._check_read_permission(key)
        return self._store[key]

    def _check_write_permission(self, key: str) -> None:
        evaluator = get_permission_evaluator()
        # Permission evaluation uses auth_context to identify accessor
        ...
```

**Three Modes of Operation**

**Mode 1: Owner Mode** (actor operating on its own data)
```python
# Direct access - full permissions, no checks
actor = ActorInterface.get_by_id(actor_id, config)
actor.properties["key"] = value  # Full access
```

**Mode 2: Peer Mode** (another actor accessing via trust)
```python
# Create authenticated view with peer identity
peer_view = actor.as_peer(peer_id, trust_relationship)
peer_view.properties["key"] = value  # Permission checks enforced
# Raises PermissionError if peer doesn't have write access to "key"
```

**Mode 3: Client Mode** (MCP/OAuth2 client accessing)
```python
# Create authenticated view with client identity
client_view = actor.as_client(client_id, trust_relationship)
client_view.properties["key"] = value  # Permission checks enforced
# Raises PermissionError if client doesn't have write access to "key"
```

**Key Principle**: The view pattern keeps the identity context separate from the data operations:
- `actor.properties` = the data
- `actor.as_peer(...)` = who is accessing
- `peer_view.properties` = data operations with enforced permissions

**For Subscription Operations**:
```python
# When a peer subscribes, use their authenticated view
peer_view = actor.as_peer(peer_id, trust_relationship)
peer_view.subscriptions.create_local(target="properties")
# Permission checks ensure peer can subscribe to this target
```

**For MCP Operations**:
```python
# MCP client operations use client view
client_view = actor.as_client(client_id, mcp_trust_record)
result = client_view.methods.execute("search", data)
# Permission checks based on client's trust relationship
```

**Benefits of This Pattern**:
1. **Clear separation of concerns**: Identity context is separate from data operations
2. **Type safety**: AuthenticatedActorView is a distinct type, making permission enforcement explicit
3. **No parameter pollution**: Methods don't need auth_context parameter
4. **Immutable context**: Once a view is created, its auth context can't be changed
5. **Familiar pattern**: Similar to database connections with different permission levels

---

### 4. Hook Registry Access from Developer API

**Current State**:
- Handlers receive hooks via constructor: `BaseHandler.__init__(..., hooks=None)`
- Config has `_hooks` attribute set by `ActingWebApp.get_config()`
- ActorInterface does NOT store or provide hooks to child managers

**Proposal: Wire Hooks Through ActorInterface**

```python
class ActorInterface:
    def __init__(self, core_actor, config=None, hooks=None):
        self._core_actor = core_actor
        self._config = config or core_actor.config
        self._hooks = hooks or getattr(self._config, "_hooks", None)

    @property
    def properties(self) -> PropertyStore:
        if self._property_store is None:
            self._property_store = PropertyStore(
                self._core_actor.property,
                actor=self._core_actor,
                hooks=self._hooks,  # Pass hooks
                config=self._config,
            )
        return self._property_store

    def as_peer(self, peer_id: str, trust_relationship: dict) -> "AuthenticatedActorView":
        """Create authenticated view - hooks are passed to view's stores."""
        return AuthenticatedActorView(
            self,
            auth_context={"peer_id": peer_id, "trust_relationship": trust_relationship},
            hooks=self._hooks  # Pass hooks to authenticated view
        )
```

**PropertyStore with hooks** (base store, no auth checks):
```python
class PropertyStore:
    def __init__(self, core_store, actor=None, hooks=None, config=None):
        self._core_store = core_store
        self._actor = actor
        self._hooks = hooks
        self._config = config

    def __setitem__(self, key: str, value: Any) -> None:
        # Execute pre-hook (transform/validate)
        if self._hooks:
            transformed = self._hooks.execute_property_hooks(
                key, "put", self._actor_interface, value, [key]
            )
            if transformed is None:
                raise ValueError("Hook rejected value")
            value = transformed

        # Store
        self._core_store[key] = value

        # Register diff for subscribers
        if self._actor:
            self._actor.register_diffs(target="properties", subtarget=key, blob=value)
```

**AuthenticatedPropertyStore** (with permission checks):
```python
class AuthenticatedPropertyStore:
    """Wraps PropertyStore and adds permission checks before operations."""

    def __init__(self, property_store: PropertyStore, auth_context: dict, hooks):
        self._store = property_store
        self._auth_context = auth_context
        self._hooks = hooks

    def __setitem__(self, key: str, value: Any) -> None:
        # Check permission BEFORE delegating to base store
        self._check_write_permission(key)
        # Delegate to base store (which handles hooks and register_diffs)
        self._store[key] = value

    def _check_write_permission(self, key: str) -> None:
        evaluator = get_permission_evaluator()
        peer_id = self._auth_context.get("peer_id")
        client_id = self._auth_context.get("client_id")
        trust = self._auth_context.get("trust_relationship")

        result = evaluator.evaluate_property_access(
            accessor_id=peer_id or client_id,
            property_name=key,
            operation="write",
            trust_relationship=trust,
        )
        if result != PermissionResult.ALLOWED:
            raise PermissionError(f"Access denied: write to '{key}'")
```

---

### 5. Async Variants for Developer API

**Current Async Support**:

| Module | Method | Has Async? |
|--------|--------|-----------|
| aw_proxy.py | get/create/change/delete_resource | **Yes** |
| oauth2.py | validate_token_and_get_user_info | **Yes** |
| auth.py | check_token_auth, check_and_verify_auth | **Yes** |
| actor.py | get_peer_info, create_reciprocal_trust, etc. | **No** |

**Methods Needing Async Variants** (make outbound HTTP to peers):
- `Actor.get_peer_info()` → `get_peer_info_async()`
- `Actor.modify_trust_and_notify()` → `modify_trust_and_notify_async()`
- `Actor.create_reciprocal_trust()` → `create_reciprocal_trust_async()`
- `Actor.create_verified_trust()` → `create_verified_trust_async()`
- `Actor.delete_reciprocal_trust()` → `delete_reciprocal_trust_async()`
- `Actor.create_remote_subscription()` → `create_remote_subscription_async()`
- `Actor.delete_remote_subscription()` → `delete_remote_subscription_async()`
- `Actor.callback_subscription()` → `callback_subscription_async()`

**Developer API Async Wrappers** (in managers):
```python
class TrustManager:
    async def create_relationship_async(self, peer_url, ...) -> TrustInfo:
        return await self._core_actor.create_reciprocal_trust_async(...)

    async def approve_relationship_async(self, peer_id) -> bool:
        result = await self._core_actor.modify_trust_and_notify_async(...)
        # Execute lifecycle hooks (sync is fine, no network)
        if result and self._hooks:
            self._hooks.execute_lifecycle_hooks("trust_approved", ...)
        return result
```

---

### 6. Documentation Reorganization

**Current State**: 36 docs files mixing four different audiences.

**Proposed Structure**:

```
docs/
├── index.rst                    # Landing page with audience selector
│
├── protocol/                    # Audience: Protocol Implementers
│   ├── actingweb-spec.rst      # The formal specification
│   └── protocol-overview.rst   # High-level protocol concepts
│
├── quickstart/                  # Audience: App Developers (Flask/FastAPI)
│   ├── overview.rst            # 5-minute intro
│   ├── getting-started.rst     # Step-by-step tutorial
│   ├── local-dev-setup.rst     # Environment setup
│   ├── configuration.rst       # ActingWebApp config
│   └── deployment.rst          # Production deployment
│
├── guides/                      # Audience: App Developers (deeper topics)
│   ├── authentication.rst      # OAuth2, MCP auth
│   ├── trust-relationships.rst # Trust management
│   ├── subscriptions.rst       # Pub/sub patterns
│   ├── property-lists.rst      # Large collections
│   ├── hooks.rst               # Extending behavior
│   ├── mcp.rst                 # MCP applications
│   └── web-ui.rst              # Frontend templates
│
├── sdk/                         # Audience: SDK Developers (advanced)
│   ├── developer-api.rst       # ActorInterface, managers
│   ├── custom-framework.rst    # Using with Django, etc. ← NEW
│   ├── handler-architecture.rst # How handlers work ← NEW
│   ├── async-operations.rst    # Async peer communication
│   └── advanced-topics.rst     # Core components access
│
├── reference/                   # API Reference (all audiences)
│   ├── interface-api.rst       # Public API
│   ├── hooks-reference.rst     # Hook signatures
│   ├── handlers.rst            # Handler classes
│   └── config-options.rst      # All config options
│
└── contributing/                # Audience: Contributors
    ├── architecture.rst        # Codebase architecture
    ├── testing.rst             # Test suite
    └── style-guide.rst         # Code style
```

**Missing Documentation to Create**:
1. `sdk/custom-framework.rst` - How to integrate with other frameworks
2. `sdk/handler-architecture.rst` - Handler system internals
3. `contributing/architecture.rst` - Codebase overview for contributors

---

### 7. Permissions in Developer API

**Principle**: Permissions must always be enforced when a remote party is involved. The authenticated view pattern ensures this enforcement is automatic.

**Architecture: Permission Enforcement via Views**

```
Direct Access (Owner Mode)          Authenticated View (Peer/Client Mode)
─────────────────────────────       ──────────────────────────────────────

actor.properties["key"] = value     peer_view.properties["key"] = value
        │                                       │
        ▼                                       ▼
   PropertyStore                    AuthenticatedPropertyStore
   (no auth checks)                 (enforces permissions)
        │                                       │
        ▼                                       ▼
   execute hooks                         check_permission()
        │                                       │ (raises PermissionError if denied)
        ▼                                       ▼
   store value                          delegate to PropertyStore
        │                                       │
        ▼                                       ▼
   register_diffs()                      (hooks, store, diffs)
```

**Implementation**:

```python
class AuthenticatedPropertyStore:
    """Enforces permission checks on all property operations."""

    def __init__(self, property_store: PropertyStore, auth_context: dict, hooks):
        self._store = property_store
        self._auth_context = auth_context
        self._hooks = hooks

    def __setitem__(self, key: str, value: Any) -> None:
        self._enforce_permission(key, "write")
        self._store[key] = value  # Delegate to base store

    def __getitem__(self, key: str) -> Any:
        self._enforce_permission(key, "read")
        return self._store[key]

    def __delitem__(self, key: str) -> None:
        self._enforce_permission(key, "delete")
        del self._store[key]

    def _enforce_permission(self, key: str, operation: str) -> None:
        evaluator = get_permission_evaluator()
        accessor_id = (self._auth_context.get("peer_id") or
                      self._auth_context.get("client_id"))
        trust = self._auth_context.get("trust_relationship")

        result = evaluator.evaluate_property_access(
            accessor_id=accessor_id,
            property_name=key,
            operation=operation,
            trust_relationship=trust,
        )
        if result != PermissionResult.ALLOWED:
            raise PermissionError(
                f"Access denied: {operation} on '{key}' for {accessor_id}"
            )
```

**Trust Identification for Subscriptions**:
```python
class AuthenticatedSubscriptionManager:
    """Enforces permission checks on subscription operations."""

    def __init__(self, subscription_manager: SubscriptionManager, auth_context: dict):
        self._manager = subscription_manager
        self._auth_context = auth_context

    def create_local(self, target: str, subtarget: str = None) -> SubscriptionInfo:
        """Accept a subscription request from the authenticated peer/client."""
        accessor_id = (self._auth_context.get("peer_id") or
                      self._auth_context.get("client_id"))
        trust = self._auth_context.get("trust_relationship")

        # Check if accessor has permission to subscribe to this target
        evaluator = get_permission_evaluator()
        result = evaluator.evaluate_subscription_access(
            accessor_id=accessor_id,
            target=target,
            subtarget=subtarget,
            trust_relationship=trust,
        )
        if result != PermissionResult.ALLOWED:
            raise PermissionError(f"Subscription denied: {accessor_id} to {target}")

        # Delegate to base manager
        return self._manager.create_local_subscription(
            peer_id=accessor_id,
            target=target,
            subtarget=subtarget,
        )
```

**Handler Integration** (handlers use authenticated views):
```python
class PropertiesHandler:
    def put(self, actor_id: str, name: str) -> None:
        # Get actor
        actor = ActorInterface.get_by_id(actor_id, self.config)

        # Create authenticated view based on request auth
        if self.auth_result.peer_id:
            view = actor.as_peer(self.auth_result.peer_id, self.auth_result.trust)
        elif self.auth_result.client_id:
            view = actor.as_client(self.auth_result.client_id, self.auth_result.trust)
        else:
            view = actor  # Owner mode

        # Set property - permission checks automatic for authenticated views
        try:
            view.properties[name] = self.request_body
            self.response.status_code = 204
        except PermissionError as e:
            self.response.status_code = 403
            self.response.body = {"error": str(e)}
```

---

### Summary of Additional Requirements

| Requirement | Status | Notes |
|-------------|--------|-------|
| External framework support | Needs documentation | Handler system is framework-agnostic |
| Property list diffs | **Gap exists** | Handlers don't call register_diffs |
| Authenticated views pattern | Proposal ready | `as_peer()`, `as_client()` methods create permission-enforced views |
| No batch set_many | Confirmed | Keep operations simple |
| Hook registry access | Proposal ready | Wire through ActorInterface |
| Async variants | Partial | AwProxy has async; Actor needs it |
| Documentation structure | Proposal ready | Four-audience organization |
| Permissions with trust ID | Proposal ready | AuthenticatedActorView enforces for remote parties |
