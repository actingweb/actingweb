# `AuthenticatedPropertyListStore.create()` and `.delete()` raise `TypeError` on every call

**Status:** Open — unscheduled. Small, self-contained, and **not** part of the
v2 cost cluster it was found alongside.
**Found in:** the consumer audit reported in
`actingweb_mcp/thoughts/research/2026-08-20-v2-list-read-cost.md` as *"an
incidental correctness bug"*; verified first-hand in
[`thoughts/research/2026-08-20-v2-cost-in-library-callers.md`](../research/2026-08-20-v2-cost-in-library-callers.md).

**This has nothing to do with property-list v2.** It was introduced 2025-12-14
(`30216d1`) and last touched 2026-01-30 (`6be6158`) — it predates the v2 format
entirely and has never worked. Do not sequence it behind the cost work.

## The defect

`interface/authenticated_views.py:252-259`:

```python
def create(self, name: str, **kwargs: Any) -> Any:
    """Create a new list (requires write permission)."""
    self._check_permission(name, "write")
    return self._store.create(name, **kwargs)

def delete(self, name: str) -> bool:
    """Delete a list (requires delete permission)."""
    self._check_permission(name, "delete")
    return self._store.delete(name)
```

`self._store` is `interface/property_store.py:404` `PropertyListStore`,
constructed at `authenticated_views.py:422`. That class defines exactly three
members — `exists`, `list_all`, and `__getattr__` (`:427-437`), which returns a
`NotifyingListProperty` for **any** non-underscore name:

```python
def __getattr__(self, name: str) -> NotifyingListProperty:
    if name.startswith("_"):
        raise AttributeError(...)
    list_prop = getattr(self._core_store, name)
    return NotifyingListProperty(list_prop, name, self._actor)
```

It has no `create` and no `delete`. Neither `NotifyingListProperty` nor
`ListProperty` defines `__call__`. So both wrapper methods resolve to a *list
object named `"create"` / `"delete"`* and then call it:

```
TypeError: 'NotifyingListProperty' object is not callable
```

after the permission check has already passed. The core store one layer down
(`property.py:15-67`) has the same three members and the same hole, so nothing
would change if the wrapper were bypassed.

## Reachability

`grep` finds **no callers, no tests and no documentation** for either method
anywhere in this repo. It is exported from `actingweb.interface`
(`interface/__init__.py:19,64`), so it is reachable only by an application
developer using the permission-enforcing view — which is exactly the audience
least able to diagnose it, since the exception names an internal type they never
asked for.

## What each method should do

- **`delete(name)` is a real operation with a real implementation.**
  `ListProperty.delete()` exists at `property_list.py:1210` and handles the v1/v2
  split, the foreign-format sweep and the meta row. The wrapper simply reaches
  for it wrongly — `getattr(self._store, name).delete()` is what it means.
- **`create(name)` has no clear meaning.** Lists are created lazily on first
  write; there is no core-store `create` for it to delegate to. Options: make it
  materialise the metadata row (the shape `handlers/www.py:1032` improvises with
  `_ = len(list_prop)`), or remove it.

## Options

1. **Fix `delete()`, remove `create()`** — smallest honest surface. Removing an
   exported method that has never worked cannot break a caller.
2. **Fix both**, giving `create()` an explicit metadata-materialising
   implementation. Worth it only if an explicit create is wanted for its own
   sake — see the `www.py:1032` workaround, which suggests it might be.
3. **Fix `delete()`, leave `create()` broken** — not defensible now that it is
   written down.

Whichever is chosen: **add a test**. The absence of one is why eight months
passed. `exists()` on the same class (`authenticated_views.py:244-250`) is the
only member of the trio that is exercised, and it is the one that works.
