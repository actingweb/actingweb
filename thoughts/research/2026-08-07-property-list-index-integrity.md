# Research: property-list index integrity — verifying the "delete leaves holes" report

**Date:** 2026-08-07
**Branch:** master
**Commit:** 04f624c
**Verifies:** `thoughts/todo/property-list-delete-leaves-holes.md` (external, 2026-08-05)
**Upstream evidence:** `../actingweb_mcp/thoughts/research/2026-07-28-run-records-index-skew.md`

## Research Question

An external bug report claims `ListProperty.__delitem__` leaves permanent holes
and an inflated `length` when interrupted mid-shift, that this is rare (needs a
process death), and that the user-visible damage was contained by a fix in the
consumer. Verify the claims, and evaluate the options.

## Summary

**The reported mechanism is real and I reproduced every residue state it
predicts. But the report is wrong about the trigger, wrong about the detection
fingerprint, and wrong that the damage is contained.** The severity is higher
than reported, not lower.

Three findings change the picture:

1. **No process death is required.** Three no-crash paths to a holed list; two
   measured against a real DynamoDB, the third code-cited and demonstrated
   against a fake. `DbProperty.get()` catches *every* exception
   and returns `None` (`db/dynamodb/property.py:151-157`), which the shift loop
   cannot distinguish from "row absent" — so one transient throttle or timeout
   during a delete silently skips a shift, destroys an extra item, leaves a
   hole, decrements `length` anyway, and **returns success to the caller with no
   exception and no log line**. On PostgreSQL, `set()` catches every exception
   and returns `False` (`db/postgresql/property.py:305-307`) and `ListProperty`
   never checks a return value, so any failed write does the same (code-cited
   and demonstrated with a fake; not measured against a real PostgreSQL). This
   also resolves the upstream forensics' open puzzle — it inferred a Lambda
   timeout precisely *because* no log line existed, but the swallowing paths
   leave no log line either and need no crash.

2. **`insert()` is unconditionally broken on DynamoDB and is a hole factory.**
   `insert()` is the one method that reuses the long-lived `self._db` handle
   (`property_list.py:497,502,514`) instead of taking a fresh one, and the
   DynamoDB `DbProperty` ignores the `name` argument once `self.handle` is set —
   `get()` calls `handle.refresh()` (`:148-153`) and `set()` assigns onto the
   cached handle (`:330-331`). Measured on real DynamoDB: `insert(1, "NEW")` into
   a 5-item list destroys the last element, writes the new item over it, leaves
   `length=6` and a permanent hole at slot 5. Every existing test calls
   `insert(0, …)` on an *empty* list, where the shift loop never runs
   (`tests/integration/test_property_lists_advanced.py:160,212`), which is why
   900+ tests miss it. This is correct on PostgreSQL — a silent backend
   divergence.

3. **"length is one greater than the number of readable rows" is not the
   fingerprint.** Measured across every interruption point of a delete: roughly
   half leave a hole (detectable), and the rest leave an **exact duplicate with
   `length` correct and no error log** — completely invisible to the sweep that
   found the two production lists. The upstream "2 of 43 lists holed" is a floor
   for the detectable residue only; the invisible residue was never searched for.
   Interrupted `insert()` is likewise fingerprint-free.

The report's claim that the consumer-side fix contained the damage is also
false: ActingWeb's **own HTTP API** pairs a compacted read with storage-index
writes. `GET /{actor}/properties/{name}/items` returns `to_list()`
(`handlers/properties.py:1526`); `POST` to the same URL with `action=update` /
`action=delete` feeds the client's index straight to `list_prop[index]` /
`del list_prop[index]` (`handlers/properties.py:1642,1677`), bounds-checked
against the *metadata* length. Any consumer of the documented REST API
rediscovers the skew without writing a line of the pattern the report blames.

One report claim survives intact and one is overstated: there is genuinely no
named repair primitive, but `to_list()` → `clear()` → `extend()` does repair a
hole today — it just silently wipes `description`, `explanation` and
`created_at` (`property_list.py:407` calls `_create_default_metadata()`).

## How this was verified

Two harnesses, both in
`/private/tmp/claude-501/.../scratchpad/` (throwaway):

- `repro_holes.py` — monkeypatches `actingweb.property_list.get_property` with a
  dict-backed fake whose `set()` raises after the *N*th write, then walks *N*
  across every interruption point. Raising is not a process kill, but for **store
  residue** the two are equivalent: nothing after the raise point runs and
  nothing is rolled back. Metadata is always read back through a fresh
  `ListProperty` so the `_meta_cache` (`property_list.py:64-67`) cannot mask a
  write that never happened.
- `repro_real_dynamo.py` — runs against dynamodb-local (`docker-compose.test.yml`,
  port 8001) with the real `Config`/`DbProperty` stack, for the two claims that
  depend on backend semantics.

## Detailed Findings

### The report's claims, verified

| Report claim | Verdict | Evidence |
| --- | --- | --- |
| `__delitem__` shifts row-by-row, non-transactionally, `length` last | **Confirmed** | `property_list.py:306-355` |
| An interruption leaves a permanent hole and inflated `length` | **Confirmed, measured** | table below |
| An interruption can leave an exact duplicate | **Confirmed, measured** | table below |
| All three residues share the fingerprint `length > readable` | **False** | duplicate residues have `length == readable` |
| `to_list()` hides holes and logs on every read | **Confirmed** | `property_list.py:433-445` |
| `__delitem__` migrates holes rather than repairing | **Confirmed** | `property_list.py:335` |
| Nothing recomputes `length` | **Confirmed** | only `append`/`insert`/`__delitem__` write it |
| Trigger is rare, needs a process death | **False** | three no-crash paths, two measured |
| Damage contained by the consumer-side fix | **False** | same pairing in `handlers/properties.py` |
| No supported way to repair a holed list | **Overstated** | `to_list`+`clear`+`extend` works, lossy on metadata |
| Cost is `1 + 3 × (n − i − 1)` round trips | **Slightly under** | plus 2 metadata round trips |

### Measured residue of an interrupted delete

5-item list, `del lp[1]`; a complete delete costs 8 writes (7 item + 1 metadata).
Interrupting before write *N*:

| Interrupt before write | `length` | Rows present | `to_list()` | Detectable? |
| --- | --- | --- | --- | --- |
| 1 | 5 | 0,1,2,3,4 | 5 items, correct | no damage |
| 2 | 5 | 0,**_**,2,3,4 | 4 items | **yes** — `length > readable` |
| 3 | 5 | 0,1,2,3,4 | `[item0, item2, item2, item3, item4]` | **no** |
| 4 | 5 | 0,1,**_**,3,4 | 4 items | **yes** |
| 5 | 5 | 0,1,2,3,4 | `[item0, item2, item3, item3, item4]` | **no** |
| 6 | 5 | 0,1,2,**_**,4 | 4 items | **yes** |
| 7 | 5 | 0,1,2,3,4 | `[item0, item2, item3, item4, item4]` | **no** |
| 8 | 5 | 0,1,2,3,**_** | 4 items | **yes** |

The odd rows are the reported bug. The even rows are the same bug producing
**silent** corruption: the deleted item is destroyed, its successor is
duplicated, `length` matches the readable count, and nothing is logged. Three of
seven interruption points land there. (By wall-clock the hole windows are wider —
each contains a read round trip the duplicate windows do not — but the duplicate
windows are not narrow, and a retry then deletes the index again, now holding the
successor's content, destroying a second item.)

Note what the hole residue is *not*: in every crash-interrupted case above,
`to_list()` returns the **correct surviving content** — `[item0, item2, item3,
item4]`. A crash-formed hole preserves data; the harm is the inflated `length`,
the per-read ERROR line, and the positional skew it induces in callers. The
error-swallowed holes in the next section are different — those destroy an extra
item outright. Worth keeping distinct when reasoning about remediation urgency.

**Consequence for remediation:** a `compact()` that recomputes `length` and
closes holes, as the report proposes, cannot repair a duplicate residue and would
silently bless it.

### Hole formation without a crash — measured on real DynamoDB

`DbProperty.get()` (`db/dynamodb/property.py:144-158`) returns `None` on any
exception, with no logging:

```python
try:
    self.handle = Property.get(actor_id, name, consistent_read=True)
except Exception:  # PynamoDB DoesNotExist exception
    return None
```

The shift loop treats `None` as "row absent" and skips
(`property_list.py:335`). Injecting one simulated throughput exception on the
read of row 3 during `del lp[1]` on a 5-item list:

```
before : length=5 rows={0:item0, 1:item1, 2:item2, 3:item3, 4:item4}
after  : length=4 rows={0:item0, 1:item2, 3:item4}
to_list: ['item0','item2','item4']   (len=3)
exception seen by caller: None      <-- caller was told SUCCESS
```

`length` 4 vs 3 readable — **exactly the production fingerprint** — plus `item3`
destroyed. No exception, no log line, no crash. The upstream forensics ruled out
a swallowed exception because no swallow *logged*; this path never logs.

The PostgreSQL analogue is the write side: `set()` wraps everything and returns
`False` on any exception (`db/postgresql/property.py:305-307`), and no
`ListProperty` call site checks the return value. Demonstrated with the fake: an
`append()` whose item write returns `False` still increments `length`, leaving a
tail hole with no error at all.

So the two backends fail in opposite directions — DynamoDB raises on write and
swallows on read; PostgreSQL swallows on write and logs on read — and
`ListProperty` is written for neither.

### `insert()` on DynamoDB — measured

`insert()` is the sole method using the long-lived `self._db`
(`property_list.py:54`, used at `:497,502,514`); everything else takes a fresh
handle with the comment "Use fresh DB instance to avoid handle conflicts"
(`property_list.py:72,135`). Those conflicts are exactly what happens:

```
before insert(1,'NEW'): length=5 rows={0:item0,1:item1,2:item2,3:item3,4:item4}
after  insert(1,'NEW'): length=6 rows={0:item0,1:item1,2:item2,3:item3,4:'NEW'}
to_list()             : ['item0','item1','item2','item3','NEW']
expected              : ['item0','NEW','item1','item2','item3','item4']
```

Every `get`/`set` after the first lands on row 4, because `handle.refresh()`
(`:150`) and `self.handle.value = value` (`:331`) both ignore the `name`
argument. Net effect of *any* `insert()` into a non-empty list on DynamoDB:
the last element is destroyed, the new item is written over it, and a permanent
hole appears at the tail. Correct on PostgreSQL, which has no handle
short-circuit.

Interrupted `insert()` (measured with the fake, backend-independent) is also
fingerprint-free: `length` stays correct, a ghost row sits beyond `length`, and
`to_list()` returns a duplicate — e.g. `['item0','item1','item2','item3','item3']`
with `item4` reachable only at slot 5, where the next `append()` overwrites it.

### Holes migrate and persist — measured

The report claims a later delete *migrates* a hole rather than closing it
(`property_list.py:335`). Measured on real DynamoDB, from both a directly punched
hole and an `insert()`-formed one:

```
hole punched at slot 4:      length=6 readable=5 missing=[4]
after 1 front delete:        length=5 readable=4 missing=[3]  fingerprint=1
after 2 front deletes:       length=4 readable=3 missing=[2]  fingerprint=1
after 3 front deletes:       length=3 readable=2 missing=[1]  fingerprint=1
```

One slot per delete, `length − readable == 1` preserved indefinitely. A hole
formed anywhere therefore walks toward slot 0 under a retention sweep and never
heals — confirming the report, and explaining how a hole formed at the tail can
be observed mid-list months later.

### Did `insert()` cause the two production holes? Tested — no

An `insert()`-formed hole is a candidate explanation for the upstream forensics'
explicitly unresolved "where the hole came from". The signature matches exactly:

```
6 items, then insert(0, {'_meta': 'header'})   <- the "metadata as item 0" pattern
  length=7  readable=6  missing slot=[6]  fingerprint=1
  rows={0:item0, 1:item1, 2:item2, 3:item3, 4:item4, 5:{'_meta':'header'}}
  no crash, no exception, no timeout — deterministic
```

A tail hole plus *d* front-deletes gives a hole at slot `n − d` with the
fingerprint intact — which would reproduce both `run_records` (202, hole at 111)
and `output_improvement` (33, hole at 11) deterministically, with no timeout
inference needed.

**But the consumer never calls it.** `PropertyListAccessor`
(`../actingweb_mcp/repositories/property_list_accessor.py`) exposes `append`,
`update_at_index`, `delete_at_index`, `replace_all`, `to_indexed_items` — and no
insert. The only `.insert(` anywhere in that repository is
`hooks/mcp/tools/agent_run.py:870`, a plain Python list. **Hypothesis
falsified**; the upstream's delete-path inference stands as the best available
explanation, now with a far more probable trigger than a timeout (the read-swallow
above). The `insert()` bug remains a live hazard for every *other* consumer,
which is why it is Decision 1 rather than a footnote.

### Detectability decays

`insert()` into a list that already has a hole converts the detectable residue
into an undetectable one. Measured: hole at slot 2, `insert(0,'NEW')` →
`length=6`, 6 readable rows, an adjacent duplicate, and **no fingerprint left**.
Any remediation that waits loses evidence.

### Read paths disagree with each other

| Path | Behaviour on a hole |
| --- | --- |
| `to_list()` `:433-445`, `slice()` `:447-469`, `to_list_from_rows()` `:165-186` | compact silently, log per hole per read |
| `__iter__` / `ListPropertyIterator` `:32-38`, `index()` `:533-543`, and transitively `count()` `:545-551`, `remove()` `:525-531` | raise `IndexError` |
| `pop()` `:471-481` on a trailing hole | raises before `del` runs, so `length` stays inflated **permanently** — that list can never be popped |

Measured on a 5-item list with slot 2 removed: `to_list()` and `slice()` return
4 items; `list(iter(lp))`, `count()`, `index()`, `remove()` all raise
`IndexError`. This matters beyond aesthetics — `actor.py:2527,2558` build
subscription full-state with `items = list(list_attr)`, so **a hole breaks
subscription resync with an exception** while HTTP GET quietly hides it.

The sibling implementation already made the opposite choice and documented it.
`AttributeList.to_list()` (`attribute_list.py:473-492`) has no `try/except`:

> *Raises: IndexError: If any items are missing from the list, which indicates
> data corruption or inconsistent metadata.*

`property_list.py`'s `to_list`/`slice` are the drifted copies.

### Blast radius inside ActingWeb itself

The report treats the compacted-read/storage-write pairing as a consumer
mistake. It is in the library's own handlers:

- **`PropertyListItemsHandler`** — `GET /{actor}/properties/{name}/items` returns
  `list_prop.to_list()` (`handlers/properties.py:1526`); `POST` with
  `action=update` → `list_prop[index] = …` (`:1642`) and `action=delete` →
  `del list_prop[index]` (`:1677`). The bounds check uses `len(list_prop)`
  (metadata length) against an index derived from the compacted array, so past a
  hole every write hits the wrong row *and* the last client index passes a check
  it should fail. FastAPI only — Flask has no `/items` route
  (`fastapi_integration.py:1007-1008` vs `flask_integration.py:386`).
- **`PropertiesHandler`** — `GET /properties/{name}` → `to_list()` (`:243`);
  `PUT /properties/{name}?index=N` → `list_prop[index] = …` (`:621`).
- **`listall` `format=full`** — the subscription/baseline read path emits
  `to_list_from_rows()` (`:496-497`), written back positionally by the bulk POST
  (`:1014-1017`, `:992-993`).
- **Bulk POST is independently skewed** even with no hole: `:937-1028` iterates
  client-supplied indices computed against the pre-loop list while `del` shifts
  rows underneath it — no sort, no reverse pass, no re-read.
- **`www.py:352`** pairs `to_list()` with `loop.index0` in the template; the
  shipped template renders read-only, so this is latent until an app overrides it.

`insert()`, `pop()` and `remove()` have **no library call sites** — they are
public API for app developers only.

### Repair and detection: what exists today

Nothing named. A repo-wide search for verify/repair/compact/rebuild/audit
against `list:{name}-{index}` returns nothing (`scripts/` holds only lookup-table
and migration tooling).

What does work, measured:

```
to_list() → clear() → extend()
before: length=5 desc='a description' expl='an explanation' created='…:07.714448'
after : length=4 desc=''              expl=''              created='…:07.714545'
```

Holes closed, `length` correct — and `description`, `explanation` and
`created_at` silently gone, because `clear()` calls `_create_default_metadata()`
(`property_list.py:407`).

The cheapest **detector** needs no new code: `listall` already reports two
different counts for the same list. `GET /properties` uses `len(list_prop)` —
metadata length (`handlers/properties.py:525`) — while `?format=full` and
`?metadata=true` use `len(items)`, the compacted count (`:513`, `:480`). Any
divergence is a hole. It is blind to duplicate residue.

Two adjacent hazards found while looking:

- **The only self-heal makes things worse.** On unparsable metadata,
  `_load_metadata()` writes a fresh default with `"length": 0`
  (`property_list.py:102-112` → `:114-126`), orphaning every existing row with no
  way to find them again.
- **`clear()` and `delete()` cannot reach orphans.** Both iterate
  `range(length)` from metadata (`:400`, `:418`), so a row past the recorded
  length survives `delete()`, and the next `append()` writes at index `length`,
  overwriting it.

### Why the tests miss all of this

- No test anywhere creates a hole, an interrupted mutation, or a
  `length`/rows mismatch.
- `slice()`, `index()`, `count()`, `pop()`, `remove()`, `extend()`, `clear()`
  have **zero behavioural coverage**.
- `insert()` is covered only as `insert(0, …)` on an empty list
  (`tests/integration/test_property_lists_advanced.py:160,212`), where
  `range(length-1, index-1, -1)` is empty and the broken loop never executes.
- `tests/test_property_list.py:78-101` already drives `ListProperty` through a
  mocked DB, so a hole-simulation unit test needs no fixtures — patch
  `actingweb.property_list.get_property` with a dict-backed fake returned on
  *every* call (a `side_effect`-list fake exhausts, because `ListProperty` takes
  a fresh handle per operation).

## Decisions Needed

### Decision 1: `insert()` on DynamoDB — fix the caller, the backend, or both?

1. **Give `insert()` fresh handles** (3 lines: `self._db` → `get_property(self.config)`
   at `property_list.py:497,502,514`). Restores parity with every other method
   and with PostgreSQL. Leaves the landmine for anyone else who reuses a
   `DbProperty` — and `handle` is a *public* attribute in the protocol
   (`db/protocols.py:118`).
2. **Make `DbProperty.get()`/`set()` honour `name`** — drop or invalidate the
   cached handle when the requested `(actor_id, name)` differs. Fixes the class,
   but touches the hot path for every property read/write on DynamoDB.
3. **Both.**

**Recommendation:** both, and independently of everything else in this document.
This is a 100%-reproducible data-loss bug on the default backend, reachable from
public API, with no crash and no error — the only thing keeping it quiet is that
no library code calls `insert()`.

### Decision 2: do reads fail fast or keep compacting?

1. **Fail fast**, matching `AttributeList` (`attribute_list.py:473-492`).
   Converts silent skew into a loud `IndexError`. Breaking for lists that are
   *already* holed — the two known production lists would start throwing on
   read, so a repair path has to ship first or simultaneously.
2. **Keep compacting, add `to_indexed_list()`** returning `(storage_index, value)`
   and move the library's own handlers onto it. Non-breaking. Does not stop a
   third party pairing `to_list()` with `__setitem__`, which is what happened.
3. **Preserve positions with a sentinel** at the hole. No API change, all
   existing positional callers become correct — but callers now see a value they
   did not store, and can write it back.
4. **`strict=` flag / config switch**, defaulting to today's behaviour, flipped
   in a major version.

Note the library is *already* inconsistent — `__iter__`, `index`, `count`,
`remove` fail fast today while `to_list`, `slice`, `to_list_from_rows` compact.
The decision is which way to converge, not whether to change behaviour.

### Decision 3: how to make mutation crash-safe

1. **Update `length` first** (the report's proposal). **Measured not to help, and
   arguably worse.** Today's crash residue preserves all surviving data (above).
   Writing `length = n-1` first means the same crash leaves the final row
   orphaned *beyond* `length`, invisible to `to_list()` and overwritten by the
   next `append()` — silent element loss, no fingerprint, replacing a residue
   that lost nothing. Derived independently by the web research from the same
   code, reaching the same conclusion. **Drop this from the plan.**
2. **Rewrite the affected range in one pass.** Fewer round trips, narrower
   window, still non-atomic.
3. **Use real transactions.** **Eliminated for DynamoDB by arithmetic, not
   cost.** `TransactWriteItems` caps at **100 actions / 4 MB**
   ([AWS API reference]). A delete at index *i* of *n* needs `2(n−i−1)+1`
   actions — for the 202-element production `run_records` list, deleting element
   0 needs **403**. Chunking reintroduces the crash window at every boundary, and
   202 document-sized JSON strings likely exceed 4 MB anyway. `BatchWriteItem` is
   documented **not** atomic as a unit and caps at 25. PostgreSQL *could* do this
   today in one transaction (`db/postgresql/property.py:277-296`), which would
   leave the two backends with divergent correctness for the same operation.
   Neither backend exposes any batch/transaction API today (zero hits for
   `batch_write|TransactWrite` under `actingweb/`).
4. **Zero-pad the index and derive `length` from the rows.** `Property` is
   `id` (hash) / `name` (range) — confirmed at
   `db/dynamodb/property.py:61-63` — so `list:<name>-<index>` *is* the DynamoDB
   sort key, and today `list:foo-10` sorts before `list:foo-2`. Padding to
   `list:foo-000010` makes the existing scheme lexicographically sortable, which
   buys a single `Query(begins_with(...))` in place of N `GetItem`s **and** lets
   `length` be counted rather than stored — retiring the entire stored-counter
   off-by-one class without changing the addressing model. Mechanical, but needs
   a migration of every existing row.
5. **Stop shifting entirely — fractional index keys.** Delete becomes one
   `DeleteItem`; there is no compaction step left to interrupt, and `insert()` is
   fixed by the same change. The crash window closes because the multi-write
   sequence is gone, not because it became atomic. Well-established technique
   (Figma, tldraw, Jira's LexoRank) with a byte-compatible Python port available.
   Bound key growth against DynamoDB's 1024-byte sort-key limit less the
   `list:<name>-` prefix; LexoRank rebalances at 128 chars, so headroom is large.
   Cost: storage-format change plus migration. Note the literature pitches this
   as an *insert/reorder* optimisation — the delete payoff is the relevant one
   here and is not something I found written up.
6. **Stable ids + an order array in the meta row.** Delete becomes one write to
   the meta row plus best-effort orphan cleanup. Attractive, but it reintroduces
   a second write that must stay in sync with the first — the same non-atomic
   shape being eliminated — and the meta row becomes a size bottleneck at large
   lists.
7. **Fix the error handling only** — check `set()` return values, and stop
   treating a read error as an absent row. Two of the three confirmed
   hole-formation paths are error-swallowing, not crashes, so this is the
   highest value per line changed. Does not address genuine process death.

**Recommendation:** 7 now — it retires most of the *measured* exposure for a
small diff. Then 4 as a mechanical, backend-neutral step that kills the
stored-`length` bug class, and 5 as the durable direction. 1 is measurably not a
fix; 3 is unavailable on the backend that matters.

Implementation note if any transactional path is ever revisited: PynamoDB's
`TransactWrite` requires an explicit `Connection`, and a bare `Connection()`
resolves `host` from `PYNAMODB_CONFIG` rather than `Meta.host` — so it would
bypass `AWS_DB_HOST` and target real AWS from the test suite. Reported from
PynamoDB source, not its prose docs; confirm against dynamodb-local first.

### Decision 4: repair and detection

- **Repair** exists but is lossy (`to_list`+`clear`+`extend` wipes
  `description`/`explanation`/`created_at`). A `compact()` preserving metadata is
  small. Open question: `compact()` **cannot** repair duplicate residue and would
  silently bless it — should it refuse, report, or rewrite anyway?
- **Detection** of holes needs no new code (the `listall` count divergence
  above), but detection of duplicate residue needs adjacent-content comparison
  and is heuristic — legitimate duplicates exist.
- **Ship where?** Library API, `scripts/`, or both. The two known production
  lists need remediation regardless of which fix lands.
- **Urgency:** detectability decays — a subsequent `insert()` converts a
  detectable hole into an undetectable duplicate (measured above).

### Decision 5: fix the library's own index skew

`handlers/properties.py:1526` + `:1642`/`:1677` is the same pairing the report
attributes to consumers, on ActingWeb's documented REST API. Options: fix the
handlers to address storage indices; fix it under them via Decision 2; or accept
and document that the `/items` index is a compacted index and make the bounds
check agree (`len(items)`, not `len(list_prop)`). Whichever way, the bounds check
and the write currently disagree about which index space they are in.

### Decision 6: scope of this cycle

The report is one bug. This document found: a broken `insert()` on the default
backend, two error-swallowing paths that need no crash, a
`length`-reset self-heal that orphans whole lists, an
orphan-row leak in `clear()`/`delete()`, a subscription-resync path that raises
on a hole, and near-zero test coverage for six public methods. These do not all
belong in one PR. Does this become one plan with phases, or a P0 fix
(Decision 1 + Decision 3.5) followed by a design cycle for the format change?

## Code References

- `actingweb/property_list.py:306-355` — `__delitem__`, non-transactional shift, `length` last
- `actingweb/property_list.py:335` — `if item_value is not None`, the skip that turns a read error into a hole
- `actingweb/property_list.py:483-523` — `insert()`, same defect plus the shared-handle bug
- `actingweb/property_list.py:497,502,514` — the `self._db` reuse
- `actingweb/property_list.py:433-445`, `:447-469`, `:165-186` — the three compacting readers
- `actingweb/property_list.py:32-38` — iterator, raises where `to_list()` compacts
- `actingweb/property_list.py:471-481` — `pop()`, permanently inflates `length` on a trailing hole
- `actingweb/property_list.py:102-126` — metadata self-heal resets `length` to 0
- `actingweb/property_list.py:392-431` — `clear()`/`delete()` cannot reach orphan rows
- `actingweb/attribute_list.py:473-492` — the sibling that fails fast, with the integrity docstring
- `actingweb/db/dynamodb/property.py:144-158` — `get()` swallows all exceptions, no logging
- `actingweb/db/dynamodb/property.py:148-153`, `:330-331` — cached handle ignores `name`
- `actingweb/db/postgresql/property.py:305-307` — `set()` swallows all exceptions, returns `False`
- `actingweb/db/protocols.py:115-171` — `DbPropertyProtocol`, public `handle` attribute
- `actingweb/handlers/properties.py:1526`, `:1642`, `:1677` — compacted read, storage-index write, metadata-length bounds check
- `actingweb/handlers/properties.py:937-1028` — bulk POST, intra-batch shift skew
- `actingweb/handlers/properties.py:480`, `:513`, `:525` — the two disagreeing `count` values
- `actingweb/actor.py:2527`, `:2558` — subscription full-state raises on a hole
- `tests/integration/test_property_lists_advanced.py:160,212` — the `insert()` tests that never run the loop
- `tests/test_property_list.py:78-101` — the mock-DB pattern a hole test can reuse

## External References

**Bounds on the atomicity options**

- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html> — 100 actions / 4 MB per transaction; the ceiling that eliminates transactional compaction for the lists that actually corrupted
- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html> — "two underlying reads or writes of every item… consumed even when a transaction does not succeed" (the 2× WCU cost, charged on failure); also advises against transactions for bulk work
- <https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchWriteItem.html> — "`BatchWriteItem` as a whole is not [atomic]"; 25 requests, `UnprocessedItems` must be retried by the caller
- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html> — 400 KB item, 1024-byte sort key (the budget for any key-encoding scheme)
- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.UpdateExpressions.html> — `REMOVE` on a List attribute shifts remaining elements server-side, atomically. Ruled out here: 202 document-sized elements do not fit one 400 KB item
- <https://pynamodb.readthedocs.io/en/stable/transaction.html>, <https://pynamodb.readthedocs.io/en/stable/batch.html> — PynamoDB `TransactWrite` / `batch_write`; no client-side check of the 100-item cap, and `batch_write` retries unprocessed items without backoff

**Addressing without dense indices**

- <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-sort-keys.html> — sort-key ordering and range queries within an item collection
- <https://www.figma.com/blog/realtime-editing-of-ordered-sequences/> — Figma's fractional indexing: insert between neighbours by averaging, arbitrary precision to avoid exhaustion
- <https://observablehq.com/@dgreensp/implementing-fractional-indexing> — the reference algorithm over lexicographically-ordered strings
- <https://github.com/httpie/fractional-indexing-python> — byte-compatible Python port of `rocicorp/fractional-indexing`
- <https://www.steveruiz.me/posts/reordering-fractional-indices> — "an index only needs to ensure that, when our items are sorted by their index, the items end up in the right order"; why floats fail after ~52 bisections
- <https://confluence.atlassian.com/adminjiraserver/managing-lexorank-938847803.html> — LexoRank rebalance thresholds (128 / 160 / 254 chars), useful as calibration for key-length growth. Operational surface only; the algorithm internals circulating publicly are community reconstruction

**Crash semantics and recoverability**

- <https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html> — on timeout Lambda resets the environment; the `Shutdown` event goes to *registered extensions*, not function code, with a **0 ms** budget when none are registered, then `SIGKILL`. No `atexit`, no `finally` — which is why a mid-shift timeout leaves no log line. Also: incomplete background work **resumes** if the environment is reused, and environments are recycled every few hours regardless
- <https://docs.aws.amazon.com/lambda/latest/dg/python-context.html> — `context.get_remaining_time_in_millis()`, the one proactive escape hatch: a shift loop could abort into a known-recoverable state rather than be killed at an arbitrary point
- <https://docs.aws.amazon.com/powertools/python/latest/utilities/idempotency/> — AWS-maintained, DynamoDB-backed write-ahead intent record (conditional `PutItem` → INPROGRESS → COMPLETE), including timeout handling via `register_lambda_context`
- <https://github.com/awslabs/dynamodb-transactions/blob/master/DESIGN.md> — AWS's pre-native-transactions library: transaction record plus per-item locks, and **sweepers** for stuck transactions. The closest prior art to this exact problem, and still relevant because the native API's 100-action cap does not cover it
- <https://dl.acm.org/doi/10.1145/38713.38742> — Garcia-Molina & Salem, "Sagas" (SIGMOD 1987); the paper itself warns that compensation does not fully restore prior state, which applies directly: compensating a half-done shift is itself an interruptible multi-write sequence
