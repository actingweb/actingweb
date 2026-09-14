# Research: a v2 list mutation can raise after its item write has committed

**Date:** 2026-09-14
**Branch:** master
**Commit:** adfecc3

## Research Question

Triage of an inbound report, filed 2026-09-14 by the Emm AI consumer project
(`actingweb_mcp`). It came out of a retry-safety audit of that project's MCP
error-envelope branch (`fix/mcp-error-envelope-iserror`; consumer plan
`thoughts/plans/2026-09-11-mcp-error-envelope-missing-iserror.md`, consumer
todo `thoughts/todo/list-mutation-reported-failed-after-commit.md`, filed
2026-09-13). That branch tells an agent to retry a tool call once on
`internal_error`, which made every "exception after a committed write" in the
stack observable as a wrong retry.

The report's claim: every v2 `ListProperty` mutator commits the item row and
then calls `_v2_touch_metadata()`. Its `advisory=True` swallows contention
(compare-and-swap exhaustion) but not a backend fault, so a throttle, timeout
or connection error during the touch raises out of a mutation that happened.
The caller cannot tell "nothing happened" from "it happened, the bookkeeping
failed", so any retry-on-exception is wrong in one of the two cases.

Does the claim hold against the tree? What exactly is the blast radius? What
fix shapes does the codebase already support, and what constrains them?

## Summary

**The claim holds, and the design already says it should not.** Every v2
mutator commits the item row, then calls `_v2_touch_metadata()` with no
exception handling anywhere between the two. `_save_metadata(advisory=True)`
swallows exactly one condition: falling out of the CAS retry loop
(`actingweb/property_list.py:924-935`). Both backends raise `DbError` from the
calls the touch makes (on the row-creation branch PostgreSQL's `set` instead
returns `False`, which becomes `RuntimeError`), and no layer of the library
retries or translates it,
so it surfaces as HTTP 500 or MCP `-32603`. Yet the class docstring's drift
bound already lists "one per mutation whose advisory metadata touch failed
(tolerated CAS exhaustion, **or a backend fault after the item write**)"
(`property_list.py:312-314`). Plan 2026-08-20 carries the same term
(`:829-831`) and gives the carve-out's rationale as exactly the consumer's
symptom (`:1341-1353`): "a raise from the touch propagates *after* the item is
committed — and a 503 whose entire meaning is 'retry' then manufactures a
duplicate". The implementation covered the contention half only. The
`DbError`-on-fault path was already recorded as untested
(`thoughts/verifications/2026-08-21-v2-positional-access-cost.md:155-157`).

**The blast radius is wider than the report's table.**
- `_v2_pop` loses the popped item itself, not just the success signal.
- `remove_where`/`update_where` and the v2 bulk POST loop lose a partial
  result whose first k−1 operations committed.
- `NotifyingListProperty` registers its subscription diff only after the
  mutator returns, so subscribers never see a committed change whose touch
  faulted.
- v1 mutators and `_v2_compact` have the same commit-then-fallible shape by
  recorded decision (non-advisory), including a 503 "retry" on
  `ListMetadataContentionError` after a committed v1 write.
- The report mislabels one row and misplaces where the fault occurs. Details
  are in the verification section below.

**The hard case is a list's first-ever mutation**, where the touch creates the
meta row. If that write faults, item rows exist without a meta row. That list
is not merely invisible to `exists()`/`list_all()`/the REST handlers. It is
one `delete()`, `clear()` or `migrate_to_v2()` call away from having its items
swept as residue, because all three treat "no meta row" as "the list is gone".
The consumer's observed "save retried came back as a duplicate" follows
directly: the retry sees the orphan's `a0` as the last rank and appends `a1`.
Web research is consistent across AWS, Google AIP-194, Stripe and Django's
`on_commit(robust=True)`: a non-authoritative follow-up write that fails
after the primary commit is logged, not raised, or else made atomic with the
primary. Raising a generic error after a committed write is the one option
none of the sources supports.

## Verification against the report

### Confirmed

- **Commit, then touch, with nothing in between.** All nine sites in the
  report's table commit before touching, and no `try`/`except` spans
  commit→touch in any of them. The only broad `except` in the file is in
  `_maybe_lazy_migrate` (`property_list.py:3438`), which runs before any
  write.
- **Only contention is swallowed.** `_save_metadata`'s loop catches nothing.
  The advisory path swallows only exhaustion (`:924-935`); non-advisory
  exhaustion raises `ListMetadataContentionError` (`:936`). A CAS loss
  (`_replace_metadata` returning `False`) is the only non-exception retry
  trigger (`:911-922`).
- **Both backends raise `DbError` from `get` and `set_if_value_equals`.**
  - DynamoDB: `get` at `actingweb/db/dynamodb/property.py:208-209,215-216`;
    `set_if_value_equals` returns `False` only on a failed condition and
    otherwise raises `DbError` (`:642-647`).
  - PostgreSQL: `get` at `actingweb/db/postgresql/property.py:134-136`;
    `set_if_value_equals` at `:700-702`.
  - The protocol documents this: `actingweb/db/protocols.py:129-133`,
    `:430-431`.
- **Retry loops do not repeat the item write on a touch fault.** In
  `_v2_append` (`:1523`), `_v2_insert` (`:2060`), `_v2_pop` (`:1999`) and
  `_v2_remove` (`:2161`), the touch sits in the success branch right before
  `return`. An exception exits the loop.
- **The item write is durable before the touch on PostgreSQL.** Each backend
  method checks out its own pooled connection and commits before returning
  (`postgresql/property.py:333,622,654,696`). `ListProperty` takes a fresh
  `get_property(config)` per call, so no transaction spans item and meta.

### Corrected

- **Line 2161 is not `remove_where`.** It is `_v2_remove`, the v2 path of
  public `remove()`, whose committed write is `delete_if_value_equals` at
  `:2141`. `remove_where` is affected, but through `delete_by_handle`
  (see Added).
- **On the first attempt the fault point is a write, not `_read_meta_row()`.**
  - Every mutator calls `_dispatch_and_stash()` before its item write
    (`:380-426`), which reads the meta row and stashes it.
  - Attempt 0 of `_save_metadata` consumes that stash (`:788-790`).
    `_read_meta_row()` → `get` runs only on CAS retry attempts (`:792`).
  - So the post-commit fault on an existing row is `set_if_value_equals`
    (`:911` → `:984-990`), or `get` on a retry.
  - On the row-creation branch it is `_load_metadata()`'s two `get`s
    (`:588-591`, `:606-612`) plus the unconditional `set` (`:846` →
    `:978-982`).
- **The row-creation exception type depends on the backend.**
  `_replace_metadata`'s docstring says `RuntimeError` (`:967-969`), which is
  true on PostgreSQL only:
  - PostgreSQL `set` reports faults "through this boolean (logged, not
    raised)" (`postgresql/property.py:277-279,342-344`). The `False` becomes
    `RuntimeError("list metadata write failed …")` (`property_list.py:982`).
  - DynamoDB `set` raises `DbError("property write")` directly
    (`dynamodb/property.py:401-404`).
  - `ValueError` is also reachable after the commit. The creation branch
    re-runs `_load_metadata()`'s `#`-name ban and scalar-collision check
    (`property_list.py:596-612`), so a scalar property created between the
    pre-commit check and the touch raises.

### Added (not in the report)

- **`_v2_pop` loses the item.** Its row is deleted (`:1995-1997`); the
  `return item` at `:2000` is never reached.
- **`remove_where` / `update_where` lose partial results.** Their v2 paths
  call `delete_by_handle` (`:2451`) / `update_by_handle` (`:2503`) once per
  match. A fault on the k-th match discards the accumulated
  `removed`/`updated` list (`:2444`, `:2496`) though k−1 operations
  committed.
- **The v2 bulk POST loop has the same shape.** `update_by_handle` / `append`
  / `delete_by_handle` run at `handlers/properties.py:1322,1333,1357`. A fault
  part-way through goes to `except Exception` → 500 (`:1559-1565`) with
  earlier entries applied.
- **`_v2_extend`, mid-batch.**
  - A `DbError` from a per-item `create_if_not_exists` (`:1609-1613`) leaves
    items `0..i-1` committed. The rank-cache extend (`:1627-1628`) and the
    touch (`:1630`) are skipped.
  - On a brand-new list, no meta row is created at all.
  - The docstring's "`count_delta` covers exactly the items that landed, even
    on the raise path" (`:1582-1585`) holds only for the collision-exhaustion
    raise at `:1631-1634`, which comes after the touch.
- **Subscribers miss the change.** `NotifyingListProperty`
  (`actingweb/interface/property_store.py:400-498`) calls the mutator, then
  `_register_diff`. A raise skips the diff, so peers subscribed to the list
  never see a change that is in storage.
- **v1 paths are the same shape, non-advisory by recorded decision.**
  - Sites: `__setitem__` `:1375→1383`, `__delitem__` `:1430-1464→1467`,
    `append` `:1556→1572`, `insert` `:2098-2119→2123`, `compact`
    `:3052-3065→3067`.
  - They call `_save_metadata(create_if_absent=False)` with the default
    `advisory=False`. A backend fault and `ListMetadataContentionError` both
    raise after the commit.
  - The latter maps to **503 with `Retry-After`** (`property_list.py:196-199`),
    whose meaning is "retry".
  - The handler comment at `handlers/properties.py:797-803` ("A v2 list's
    metadata touch is advisory and never raises this") is accurate for the
    contention error only.
- **Other whole-list operations with a fallible second write.**
  - `_v2_compact`: rewrite `:2870-2916`, then non-advisory
    `_save_metadata({"count_hint": n})` at `:2922`.
  - `clear()`: v2 `batch_delete` `:1782` → `_replace_metadata` `:1785`.
  - `delete()`: `batch_delete` `:1825` → meta delete `:1829-1832`.
  - `migrate_to_v2()`: step-6 deletes (`:3353-3361`) after the flip (`:3348`).
- **`ListAttribute` already names this exact case.**
  - `actingweb/attribute_list.py`: `append` (`:412→415-417`) and
    `__setitem__` (`:280→283-284`) have the uncaught shape.
  - `__delitem__` (`:377-389`) and `insert` (`:629-641`) catch the metadata
    failure and re-raise
    `RuntimeError("Items were shifted successfully but metadata update failed…")`.
  - That is existing library precedent for telling the caller the write
    landed. It is still an untyped `RuntimeError`, so a caller has to match on
    the message.
- **Documentation disagrees with itself.**
  - The class docstring (`property_list.py:312-314`) and plan 2026-08-20
    (`:829-831`) list a backend fault as tolerated drift.
  - `_v2_touch_metadata`'s docstring (`:1302-1308`) says only contention is
    swallowed.
  - `_save_metadata`'s `advisory` docstring (`:767-773`) says the creation
    branch "raises on a genuine backend fault, which is not a condition to
    swallow either way".
  - `docs/guides/property-lists.rst:158-168` states the third drift term
    without the backend-fault wording.
- **Already recorded as untested.**
  `thoughts/verifications/2026-08-21-v2-positional-access-cost.md:155-157`
  ("the DbError-on-genuine-fault half is untested") and
  `thoughts/todo/v2-list-access-verification-followups.md:26-28`.

## Detailed Findings

### How the fault reaches the caller

The library has no retry and no translation for this fault. By surface:

| Surface | What a post-commit `DbError`/`RuntimeError` becomes |
| --- | --- |
| `ListProperty` / `NotifyingListProperty` / `_PermissionEnforcingListView` (`interface/authenticated_views.py:272-340`) | Propagates unchanged; the diff is not registered |
| `PUT /properties/{name}?index=` (`handlers/properties.py:707-810`) | Catches only `ListMetadataContentionError` (→ 503) and `ValueError`/`IndexError` (→ 400). Everything else reaches the integration mapper (`flask_integration.py:1657-1674`, `fastapi_integration.py:2535-2557`). That mapper looks for `connection`/`timeout`/`ssl` in `str(e)`. `DbError`'s sanitized message (`db/exceptions.py`, "database error during {op} for actor {id}") and "list metadata write failed" match none of them, so the result is **500** |
| Bulk POST, list DELETE, `/items` POST (`handlers/properties.py:1559-1565`, `:1690-1693`, `:2288-2291`) | Local `except Exception` → **500** |
| `handlers/www.py:899,951,1001` | Catches only `IndexError`, so the fault reaches the integration mapper → **500** |
| MCP tool hooks (`handlers/mcp.py:1519-1525`) | `-32603 "Tool execution failed: …"`. The library itself calls no list mutators from MCP; application hooks do |

The consumer's observed failures are what these surfaces produce when a caller
retries:

| Retried tool call | What the retry sees |
| --- | --- |
| Save | A duplicate of its own write |
| Delete | `not_found` against its own delete |
| Update | A revision conflict against its own update |
| Run append | An open run whose id never reached the caller |
| Cross-list move | Rollback deleted the target after the source delete had committed, so no copy survived (the consumer has since guarded this) |

### What actually reaches the library, and how often

PynamoDB 6.1.0 (`poetry.lock`), with the default
`retry_configuration='LEGACY'`, builds a botocore client in **standard** retry
mode with `total_max_attempts = 1 + max_retry_attempts` = **4**. The web
researcher verified this in the installed source: `pynamodb/connection/base.py:429-443`,
settings `max_retry_attempts: 3`. ActingWeb sets the same value
(`dynamodb/property.py:64`).

Standard mode retries:
- `ThrottlingException` and `ProvisionedThroughputExceededException`
- 500/502/503/504
- `ConnectionError` and `HTTPClientError`, which includes `ReadTimeoutError`

It also has a retry-quota circuit breaker that can cut retries short under
sustained faults.

Two consequences, stated rather than argued:

1. **A touch fault means sustained trouble, not a single blip.** A fault that
   reaches `_save_metadata` has already failed four attempts, or hit the
   retry quota.
2. **An ambiguous-outcome class exists below the library regardless.** AWS
   documents that a 500 on a single-item write "may have succeeded or failed"
   and that the application should read the item or use condition expressions
   before retrying. The post-commit raise widens the ambiguity from rare
   500s/timeouts on the *primary* write to *any* fault on the *secondary*
   write.

**Adjacent finding (traced, not reproduced).** Because botocore retries a
timed-out `PutItem`/`DeleteItem` automatically, the conditional primitives
can return `False` for a write that landed on an earlier attempt:
- The first attempt commits, but its response times out.
- The retry fails its condition (`ConditionalCheckFailedException`).
- PynamoDB raises `PutError`/`DeleteError` with that cause.
- ActingWeb maps it to `False`: `create_if_not_exists` at
  `dynamodb/property.py:588-593`, `delete_if_value_equals` at `:612-617`.

Read against the mutators:
- `_v2_append` treats the `False` as a rank collision and writes the item
  again under the next rank (`property_list.py:1516-1530`), producing a
  duplicate.
- `_v2_pop` re-resolves and deletes the item that now occupies the index
  (`:1973-2001`), removing two items and returning the second.
- `delete_by_handle` / `update_by_handle` return `False` ("changed or
  vanished") for their own write (`:2361-2366`, `:2399-2405`).

This is a different mechanism from the reported one: it happens inside a
single primitive, not between two writes. It is out of scope for this report
but bears on any fix that claims "the caller can now retry safely".

### The orphan state: item rows with no meta row

How a brand-new list gets its meta row (`append()` as the example):

1. `_maybe_lazy_migrate()` → `_is_v2()` → `_load_metadata()` runs the
   `#`-name and collision checks and caches a v2 default, writing nothing
   ("Don't save yet", `:614-619`).
2. `_dispatch_and_stash()` reads `(None, None)` and dispatches as v2
   (`:419-422`).
3. `create_if_not_exists(list:{name}-#a0)` commits the item (`:1516-1520`).
4. The touch takes the creation branch (`:794-847`) and writes the meta row
   with an **unconditional** `set` (`:846`, `:978-982`).

`_v2_touch_metadata`'s docstring says this outright (`:1292-1300`): "under v2
there is no separate creation step, so `append()` to a list with no metadata
row is how a list comes into existence." The only earlier writers of a meta
row are `set_description`/`set_explanation` (`:1106`, `:1116`).

If step 4 faults, the list is left with item rows and no meta row:

| Operation | Behaviour on the orphan |
| --- | --- |
| `PropertyListStore.exists()` (`property.py:78-87`) | `False`. It also swallows exceptions |
| `list_all()` / `list_all_with_rows()` / `list_prefix_with_rows()` (`property.py:89-249`) | Name absent: names come only from `-meta` rows. Item rows remain in the raw dict attributed to no name, deliberately (`property.py:213-218`; `thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md:513-520`) |
| Permission views (`authenticated_views.py:506-556` via `rows_for()`) | Orphan rows dropped |
| REST: `GET /properties/<name>` and six other `exists()` gates (`handlers/properties.py:273-279`, `:675-682`, `:1150-1155`, `:1652-1657`, `:1838-1846`, `:1882-1890`, `:2037-2045`) | 404 / list skipped |
| Full-state resync (`actor.py:2534`, `:2581`), `www.py:170` | Absent |
| Maintenance scripts (`maintenance/migrate_property_lists.py:192`, `verify_property_lists.py:153`) | Never enumerate it |
| `to_list()`, `__iter__`, `__getitem__`, `__len__`, `items_with_handles()` | **Work**: a missing meta row reads as a new v2 list and the range read returns the orphan items |
| `get_metadata()` | `length: 0` (default `count_hint`), `created_at`/`updated_at` = now; nothing written |
| `verify()` (`:2618-2643`) | True length; `count_hint: None`, `healthy: True`, so the missing meta row is not flagged |
| Next mutation through `ListProperty` | **Recreates** the meta row as v2. `append`/`extend`/`insert` merge their delta onto `count_hint: 0`, so the hint undercounts by the orphan count. `__setitem__`/`__delitem__`/`pop`/`remove` write an exact count. `created_at` resets |
| `compact()` (`:2922`) | Recreates the meta row with an exact count |
| **`delete()`** (`:1820`), **`clear()`** (`:1759-1787`), **`migrate_to_v2()`** `already_v2` path (`:3162-3170`) | **Sweep the orphan rows.** `sweep_foreign_format_rows()` with `stored is None`: "the list is gone, and both namespaces are residue by definition -- both are swept" (`:1723-1725`, `:1743-1744`) |
| Scalar with the same name | Allowed (`PropertyStore.__setattr__` checks `exists()`, `property.py:322-331`). After that, the list's `_load_metadata()` raises `ValueError` |

**How the consumer's duplicate happens.** Step 4 faults, the caller retries,
and `_v2_last_rank()` returns the orphan's `a0`. The retry appends `a1`, and
its touch creates the meta row with `count_hint: 1` while the true count is 2.

Existing tests already pin that an append after a concurrent `delete()`
recreates a coherent list (`tests/test_property_list_integrity.py:1717-1754`).
No test injects a fault on the creation branch.

### Recorded constraints on a fix

- **The carve-out is existing-row only, deliberately.** Plan 2026-08-20
  `:1341-1353`, and `ListMetadataContentionError`'s docstring
  (`property_list.py:201-208`): "Metadata writes that create the row or carry
  semantic fields … still raise: there the metadata write *is* the
  operation." The same passage explains why consumers cannot fix this
  themselves: they "cannot guard against [duplicates] in-process on lambda
  (their idempotency dict dies with the container)."
- **v2 has no creation step.** Plan 2026-08-15 `:184-189` and `:429-433`
  (`status: done`, no verification file): the v1 length writers skip an
  absent row, while the v2 touch creates it. A `delete()` racing an `append()`
  leaves a one-item list by design (`property_list.py:1296-1300`).
- **v2 rows without a meta row are known to be hazardous.** Plan 2026-08-15
  `:196-203`: `migrate_to_v2()`'s abort must roll back what it wrote because
  such rows are "invisible to `exists()`/`list_all()`, and adopted as items by
  the next list of that name". Its rollback deletes conditionally on bytes
  because ranks are deterministic (`property_list.py:3309-3318`).
- **Orphan rows are deliberately not attributed to a name** by the bulk
  readers (`thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md:513-520`). A "repair on read" in those readers
  would reverse that decision.
- **Prefer visible failures, and remember listing is not a snapshot.**
  `thoughts/todo/whole-list-rewrite-atomicity.md`:
  - "Prefer a visible failure to an invisible one" (`:65-66`).
  - `fetch_all_including_lists` on DynamoDB is a paginated Query, not a
    snapshot (`:57-64`).
  - Transactions cap at 100 actions (`:74-77`).
- **Tests pin the current boundary.** `tests/test_v2_metadata_cas.py:212-237`
  pins that CAS exhaustion on the touch does not raise and the item lands
  once. `:239-292` pins the drift bound and its repair by `pop()`. `:294-314`
  pins that v1's semantic write still raises.

### Test seams that exist

- **`tests/test_property_list_integrity.py`:**
  - `FakePropertyDb` (`:31-118`) shares a dict across instances and is
    patched in via `_patch_get_property` (`:156-157`).
  - `fail_get_on` raises `DbError` from `get` (`:46-49`).
  - `fail_set_on` makes `set` and all the conditional writes return
    `False`, which simulates contention, not a fault.
  - `CrashInjectingPropertyDb` (`:121-148`) raises after N calls but wraps
    only `get`/`set`.
- **`tests/test_v2_metadata_cas.py`:** `_ConcurrentWriterPropertyDb`
  (`:47-64`), `_AlwaysFailsCASPropertyDb` (`:67-84`), and the autouse
  `_no_real_sleep` fixture (`:87-94`).
- **Not covered by any double:** raising `DbError` from
  `set_if_value_equals`, `create_if_not_exists` or `delete_if_value_equals`.
  "metadata write failed" appears nowhere in `tests/`.
- **Adding one is small.** Subclass `FakePropertyDb` and raise `DbError` from
  `set_if_value_equals` and `set` when `name.endswith("-meta")`. The only
  item-row user of `set_if_value_equals` is `update_by_handle`, and item
  names never end in `-meta`, so the filter hits only the touch. To reach the
  meta `get`, make attempt 0 lose its CAS first, since attempt 0 never calls
  `get`.

### External context

- **Swallowing a failed follow-up write has precedent.**
  - Django `on_commit(robust=True)`: "All errors derived from Python's
    `Exception` class are caught and logged".
  - Kubernetes API warnings: advisory information on a success response
    "does not change the status code or response body in any way".
  - DynamoDB `BatchWriteItem`: partial success is a successful response with
    `UnprocessedItems`, not an exception.
- **Raising a generic error on a committed mutation has none.**
  - Stripe: "treat the result of a `500` request as indeterminate".
  - Google AIP-194: clients should not automatically retry `INTERNAL` or
    `UNKNOWN`, nor "requests in which repeated runs would cause unintended
    state changes".
  - AWS Builders' Library: "APIs with side effects aren't safe to retry
    unless they provide idempotency", and retry "at a single point in the
    stack". botocore is already that point here.
- **Making the two writes atomic is possible but not free.**
  - DynamoDB `TransactWriteItems`: 2× WCU per item, consumed even on
    cancellation; `TransactionConflictException` for plain writes that collide
    with an in-flight transaction; `TransactionCanceledException` is not
    retried by the SDK; 100 actions / 4 MB.
  - PynamoDB supports it via `TransactWrite(client_request_token=...)`
    (10-minute idempotency window).
  - PostgreSQL: one `with conn.transaction():` gives both rows one outcome. A
    lost `COMMIT` remains ambiguous (SQLSTATE `08007`, `pg_xact_status`).
  - Neither fits today's `DbPropertyProtocol`, which has no multi-row write
    and whose `ListProperty` callers take a fresh backend instance per call.
- **MCP gives no guidance on idempotency.** The spec separates protocol
  errors from `isError` tool errors, and says tool errors enable the model to
  "self-correct and retry", but says nothing about mutations with an unknown
  outcome.

## Decisions Needed

### Decision 1: On an existing meta row, does a backend fault in the advisory touch raise?

**Options:**
1. **Catch it, log one WARNING, return.** The same treatment CAS exhaustion
   already gets.
   - Matches the class docstring (`:312-314`), plan 2026-08-20 (`:829-831`,
     `:1341-1353`) and every external precedent above.
   - `updated_at` drives no library decision; only `get_metadata()` returns it
     (`:1158`). `count_hint` drift is bounded and repaired by the next
     rank-counting mutation or `compact()`.
   - Cost: append-only workloads do not self-repair the hint
     (`docs/guides/property-lists.rst:158-168`), so each swallowed fault
     leaves permanent drift of one until an operator runs `compact()`.
   - Open sub-question: which exceptions count as faults. `DbError` for sure;
     `RuntimeError` from PostgreSQL's `set` on the creation branch (see
     Decision 2). The post-commit `ValueError` (name collision) is semantic,
     not a fault.
2. **Keep raising.** Then the class docstring and plan must lose the
   backend-fault term. It leaves the consumer's symptom in place for every
   mutator.

**Recommendation:** Option 1. The design and its written rationale already
chose it; only the implementation stopped at contention.

### Decision 2: What happens when the meta row is being *created* (a list's first mutation)?

**Options:**
1. **Write the meta row first for a new list.**
   - Shape: when `_dispatch_and_stash()` read `(None, None)`, create the meta
     row conditionally (`create_if_not_exists`), then write the item, then run
     the advisory touch for the count.
   - Closes the fault case: an item row can no longer exist without a meta row
     through this path.
   - New state: a fault on the item write leaves an empty but visible list.
     That matches what `clear()` produces and is the visible side of "prefer
     visible failure".
   - Costs one extra write on a list's first mutation only.
   - Does not close the `delete()`-races-`append()` window, where a sweep runs
     between the two writes (accepted today, `:1296-1300`).
   - Every creating mutator needs the same ordering: `append`, `extend`,
     `insert`, and `set_description`/`set_explanation` already create
     separately.
2. **Atomic item + meta** (`TransactWriteItems` / one PostgreSQL transaction).
   - Removes the state entirely on both backends.
   - Needs a new protocol primitive on both backends.
   - Costs 2× WCU on DynamoDB and conflicts with plain writes to the same
     meta row.
   - Only needed on first mutation, which limits the cost but not the new
     surface.
3. **Swallow the creation fault too; rely on next-mutation repair.**
   - Smallest change.
   - The list stays invisible to discovery until another mutation, and is
     exposed to `delete()`/`clear()`/`migrate_to_v2()` sweeping its items in
     the meantime.
   - `verify()` does not flag it.
   - Contradicts `_save_metadata`'s docstring and the "prefer visible failure"
     constraint.
4. **Repair on read** (readers recreate a meta row when item rows exist
   without one).
   - Reverses the decision in
     `thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md:513-520`
     to leave orphan rows unattributed.
   - Turns reads into writes.
   - Collides with `sweep_foreign_format_rows()`'s rule that a missing meta
     row means residue.
5. **Raise, but distinguishably.**
   - Shape: a typed exception (for example a `ListMutationCommittedError`
     subclass) carrying `committed=True` and whatever the mutator would have
     returned (the popped item, `True`, the partial `removed` list).
   - Follows `ListAttribute`'s existing "…successfully but metadata update
     failed" precedent (`attribute_list.py:377-389`), typed instead of
     message-matched.
   - Lets consumers and the library's own handlers map it to "done, do not
     retry".
   - Composes with 1–3 rather than replacing them: it can be the outcome for
     whatever faults remain un-swallowed.

### Decision 3: Scope — do v1 paths and whole-list operations change?

v1 mutators and `_v2_compact` raise after a committed write by recorded
decision (non-advisory: there "the metadata write *is* the operation"). v1's
contention error maps to a 503 "retry".

**Options:**
1. **v2 item mutators only** (the report's table plus `remove_where`,
   `update_where`, bulk POST). Production is all-v2 (730/730 per research
   2026-08-20) and new lists are born v2. The v1 residual stays documented.
2. **Include v1 and `compact`/`clear`/`migrate_to_v2`.** A v1 `length` write
   cannot be made advisory without reopening the index-integrity defects, so
   the fix there would have to be Decision 2 option 5 (tell the caller it
   committed), not swallowing.

### Decision 4: What does a partial multi-item operation report?

`remove_where`, `update_where`, `_v2_extend` and the v2 bulk POST loop can
commit k−1 of k operations and then raise, discarding the partial result.

**Options:**
1. **Unchanged, but fixed at the root.** Decision 1 removes the touch fault as
   a cause. A fault in the item write itself (`create_if_not_exists`,
   `delete_if_value_equals`) still discards the partial result.
2. **Carry the partial result on the exception.** Same mechanism as Decision 2
   option 5.
3. **Return partial success in-band** (`BatchWriteItem`'s `UnprocessedItems`
   shape). A return-type change, so not a patch.

### Decision 5: Which text changes to match?

Whichever way Decision 1 goes, one of these is wrong today:
- `_v2_touch_metadata`'s docstring (`:1302-1312`)
- `_save_metadata`'s `advisory` docstring (`:759-773`)
- the class docstring drift bound (`:312-314`)
- `docs/guides/property-lists.rst:158-168`
- the handler comment at `handlers/properties.py:797-803`

`_replace_metadata`'s "Raises: RuntimeError" (`:967-969`) is wrong on DynamoDB
either way.

### Decision 6: Is the adjacent ambiguous-primitive finding in or out?

The botocore-retry-after-timeout path can turn a committed conditional write
into `False` (duplicate append, double pop). It is a separate mechanism, and
the fix shapes are different: read-back on `False`, or an idempotency token
where one exists.

**Options:**
1. **File a separate todo.**
2. **Fold it into this plan's scope.**

Either way, a plan for this report should not claim retries become safe.

## Code References

- `actingweb/property_list.py:25-39` — advisory CAS bound constants and comment (exhaustion only)
- `actingweb/property_list.py:196-208` — `ListMetadataContentionError`: 503 "retry"; the advisory carve-out rationale
- `actingweb/property_list.py:303-323` — class docstring drift bound, including "or a backend fault after the item write"
- `actingweb/property_list.py:380-426` — `_dispatch_and_stash()`: pre-commit meta read consumed by the touch's attempt 0
- `actingweb/property_list.py:588-620` — `_load_metadata()`: absent row → unsaved v2 default, `#`-name and collision checks
- `actingweb/property_list.py:654-692` — `_read_meta_row()`
- `actingweb/property_list.py:694-936` — `_save_metadata()`; creation branch `:794-847`; swallow `:924-935`
- `actingweb/property_list.py:938-993` — `_replace_metadata()`; unconditional `set` → `RuntimeError` `:978-982`
- `actingweb/property_list.py:1251-1321` — `_v2_touch_metadata()`; "committed regardless of what happens to this touch" `:1302-1308`
- `actingweb/property_list.py:1343-1347`, `:1399-1408` — `_v2_setitem`, `_v2_delitem`
- `actingweb/property_list.py:1481-1533` — `_v2_append`, collision loop
- `actingweb/property_list.py:1574-1634` — `_v2_extend`
- `actingweb/property_list.py:1716-1835` — `sweep_foreign_format_rows()`, `clear()`, `delete()`
- `actingweb/property_list.py:1973-2004` — `_v2_pop` (loses the item)
- `actingweb/property_list.py:2054-2061` — `_v2_insert`
- `actingweb/property_list.py:2141-2162` — `_v2_remove` (the report's "remove_where" row)
- `actingweb/property_list.py:2338-2407` — `delete_by_handle`, `update_by_handle`
- `actingweb/property_list.py:2444-2503` — `remove_where`, `update_where` partial results
- `actingweb/property_list.py:2922` — `_v2_compact` non-advisory count write
- `actingweb/property_list.py:3162-3170`, `:3309-3361` — `migrate_to_v2()` `already_v2` sweep, rollback, flip
- `actingweb/db/dynamodb/property.py:187-217`, `:341-413`, `:574-648` — `get`, `set` (raises), conditional writes
- `actingweb/db/postgresql/property.py:95-136`, `:265-344`, `:599-702` — `get`, `set` (returns `False`), conditional writes
- `actingweb/db/protocols.py:129-133`, `:163-165`, `:339-340`, `:382-383`, `:430-431` — documented contracts
- `actingweb/property.py:78-249`, `:322-331` — `exists()`, `list_all*`, scalar collision check
- `actingweb/interface/property_store.py:400-498` — `NotifyingListProperty` registers diffs only after success
- `actingweb/handlers/properties.py:797-803`, `:1316-1368`, `:1559-1565`, `:2288-2291` — handler comment, bulk loop, 500 paths
- `actingweb/attribute_list.py:377-389`, `:629-641` — existing "…successfully but metadata update failed" re-raise
- `tests/test_v2_metadata_cas.py:212-314` — advisory carve-out boundary tests
- `tests/test_property_list_integrity.py:31-157`, `:1717-1754` — `FakePropertyDb`, fault doubles, append-after-delete test
- `thoughts/plans/2026-08-20-v2-positional-access-cost.md:829-831`, `:1341-1353` — drift bound term, carve-out decision
- `thoughts/plans/2026-08-15-property-list-metadata-integrity.md:184-203` — create-vs-skip per caller, orphan hazard
- `thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md:513-520` — rows of a list whose meta row was lost stay attributed to no name, by decision
- `thoughts/verifications/2026-08-21-v2-positional-access-cost.md:155-157` — `DbError` path recorded untested
- `thoughts/todo/whole-list-rewrite-atomicity.md:57-77` — listing is not a snapshot; prefer visible failure; transaction cap

## External References

- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Programming.Errors.html> — throttling semantics; a 500 on a single-item write "may have succeeded or failed"
- <https://docs.aws.amazon.com/boto3/latest/guide/retries.html> — legacy/standard/adaptive retry modes, `total_max_attempts` vs `max_attempts`
- <https://pynamodb.readthedocs.io/en/stable/settings.html> — `max_retry_attempts`, `retry_configuration`
- <https://pynamodb.readthedocs.io/en/stable/transaction.html> — `TransactWrite`, `client_request_token`
- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html> — 2× capacity, conflicts, no SDK retry on cancellation
- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html> — `ClientRequestToken` 10-minute window, 100 actions / 4 MB
- <https://d1.awsstatic.com/builderslibrary/pdfs/timeouts-retries-and-backoff-with-jitter.pdf> — side effects and retries; retry at a single layer
- <https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/> — client request identifiers
- <https://www.postgresql.org/docs/current/functions-info.html> — `pg_xact_status` for commit-in-doubt
- <https://www.postgresql.org/docs/current/errcodes-appendix.html> — `08007 transaction_resolution_unknown`
- <https://docs.stripe.com/error-low-level> — treat 500 as indeterminate
- <https://google.aip.dev/194> — which errors clients may retry automatically
- <https://docs.djangoproject.com/en/5.2/topics/db/transactions/> — `on_commit(robust=True)`: post-commit failures logged, not raised
- <https://kubernetes.io/blog/2020/09/03/warnings/> — success with an advisory warning
- <https://modelcontextprotocol.io/specification/2025-11-25/server/tools> — `isError` tool errors vs protocol errors

## Confidence

**Verified first-hand:**
- `_save_metadata` in full, including the creation branch and the swallow.
- `_replace_metadata` and `_v2_touch_metadata`'s docstring.
- `_v2_append`, `_v2_extend`, `_v2_pop`, `delete_by_handle`, `update_by_handle`.
- The class docstring's drift-bound wording and `ListMetadataContentionError`'s docstring.
- DynamoDB `set` raising vs PostgreSQL `set` returning `False`.
- Plan 2026-08-20 `:826-832` and `:1338-1356`; verification 2026-08-21 `:150-160`.
- `ListAttribute.__delitem__`'s re-raise; `tests/test_v2_metadata_cas.py:205-240`.
- The consumer's todo.

**From sub-agent reads, cross-consistent but not each re-read:**
- The remaining line references for v1 mutators, handlers, integration
  mappers, `NotifyingListProperty` and `property.py` listing.
- The orphan-state table.
- Plan 2026-08-15 and 2026-08-29 line references.
- PynamoDB/botocore retry internals (read from installed source in the
  consumer's virtualenv; PynamoDB version matches this repo's `poetry.lock`,
  botocore not confirmed identical).

**Traced, not reproduced:**
- The adjacent ambiguous-primitive finding (Decision 6).
- The claim that a creation-branch `ValueError` is reachable post-commit
  (needs a scalar created between the pre-commit check and the touch).

**Not evaluated:**
- How often touch faults occur in production (no metrics consulted).
- Whether PostgreSQL's empty-value `set` path calling `get()` outside its
  `try` (`postgresql/property.py:301`) matters anywhere.
- `_v2_delitem` letting a raw PynamoDB `DeleteError` out through the
  unwrapped `delete()` (`dynamodb/property.py:482`). That is the *item* write,
  so it is before the touch.
