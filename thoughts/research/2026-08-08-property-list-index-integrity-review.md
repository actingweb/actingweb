# Research: evaluation of the property-list index-integrity findings and remediation options

**Date:** 2026-08-08
**Branch:** master
**Commit:** 04f624c
**Reviews:** `thoughts/research/2026-08-07-property-list-index-integrity.md`
**Also read:** `thoughts/todo/property-list-delete-leaves-holes.md`,
`../actingweb_mcp/thoughts/research/2026-07-28-run-records-index-skew.md`

## Research Question

Review the 2026-08-07 research document, thoroughly evaluate its claims, and
evaluate the options it lays out for solving the issues.

## Summary

**The 2026-08-07 document holds up.** Every claim it marks "measured" was
independently re-reproduced for this review — the interrupted-delete residue
table byte-for-byte with a fresh fake-DB harness, and all four real-backend
claims (broken `insert()`, silent read-swallow corruption, hole migration, the
`insert(0, header)` signature) against a live dynamodb-local. Its code citations
were re-checked line by line and all are accurate; its eleven external
references were verified against the primary sources and all are accurate,
including the two figures that eliminate DynamoDB transactions (100 actions /
4 MB) and the Lambda shutdown semantics (0 ms budget without extensions,
SIGKILL). Four claims need minor correction — none changes a conclusion; they
are listed in "Errata" below.

Two things the document missed, both found while re-verifying. First, a
**fourth no-crash formation path: stale metadata cache / concurrent mutation.**
There is no locking anywhere around list mutations, and `_meta_cache`
(`property_list.py:53,64-67`) is never invalidated by other instances' writes.
Measured: two `ListProperty` instances, two ordinary sequential deletes, zero
errors — result is the production hole fingerprint *plus the wrong item
destroyed*. Any two concurrent mutations (realistic under concurrent Lambda
invocations) can produce the same residue with no crash and no error. This
strengthens the document's Decision-3 ranking: options 1-4 and 7 do nothing for
this path; only option 5 (single-write delete) removes it structurally. Second,
the sibling `ListAttribute` has the **same non-transactional shift design** in
`__delitem__` (`attribute_list.py:286-389`, skip-over-holes at `:341,347`,
length-last at `:377-381`) — the 08-07 document cites it only as the fail-fast
reader. The crash-residue class exists there too and belongs in the Decision-6
scope inventory.

On the options themselves: the document's recommendations survive scrutiny with
three refinements. (a) The Decision-1 concern that fixing the DynamoDB
cached-handle bug "touches the hot path" is overstated — honouring `name` is
one key comparison per call. (b) Decision-3 option 4 (zero-padding) is weaker
than presented: it retires the stored-counter class but does **not** close the
delete crash window unless shifting also stops, at which point it has become
option 5 with worse insert semantics; and any query-by-prefix counting
introduces a new list-name ambiguity (`list:foo-` matches rows of a list named
`foo-bar`) that no current code has, because today nothing prefix-scans item
rows. (c) Decision-3 option 7's DynamoDB half — catching only `DoesNotExist` in
`get()` — changes error semantics for *every* property read in the library, not
just lists; it is still the right fix, but its blast radius is library-wide and
needs its own test pass. One additional constraint for any storage-format
change (options 4/5/6): the subscription diff protocol is positional
(`interface/property_store.py:262-275` ships `operation`/`index`/`length` to
subscribers), so positional indices remain the wire contract regardless of how
rows are keyed — format changes must translate at that edge.

## How this was verified

- **Independent re-reproduction, fake backend** (`reverify_holes.py`, session
  scratchpad, throwaway): re-implemented the dict-backed fake from scratch
  (not reusing the 08-07 harness, which is gone with its scratchpad) and
  replayed: the 8-point interruption table, the read-swallow delete, the
  PostgreSQL-style ignored-`False` append, cached-handle `insert()` semantics,
  hole migration, the lossy `to_list→clear→extend` repair, `pop()` on a
  trailing hole, the read-path split, insert-over-hole fingerprint decay, the
  metadata self-heal orphaning, and the new stale-cache scenario. Every result
  matched the 08-07 document's tables exactly.
- **Independent re-reproduction, real backend** (`reverify_real_dynamo.py`):
  against dynamodb-local (docker-compose.test.yml, port 8001) with the real
  `Config`/PynamoDB stack: `insert(1,"NEW")` into a 5-item list, an injected
  transient exception on one read during `del lp[1]`, hole migration under
  front deletes, and `insert(0, {"_meta": "header"})` into a 6-item list. All
  four outputs matched the 08-07 document's reported outputs exactly, including
  `exception seen by caller: None` on the read-swallow path.
- **Line-by-line code verification** by two sub-agents across
  `handlers/properties.py`, the integrations, `attribute_list.py`, `actor.py`,
  `db/protocols.py`, both DB backends, and the templates.
- **Test-coverage audit** by a sub-agent across all of `tests/`.
- **External-reference verification** by a web-research sub-agent against AWS
  documentation and the cited repositories, plus direct source inspection of
  the installed PynamoDB 6.1.0.

## Detailed Findings

### Claim-by-claim verdicts on the 2026-08-07 document

| 08-07 claim | Verdict on review |
| --- | --- |
| Interrupted-delete residue table (8 interruption points, 4 holes / 3 duplicates / 1 no-damage) | **Reproduced exactly** (fake harness, independent implementation) |
| Duplicate residue has `length == readable`, no fingerprint, no log | **Reproduced** |
| DynamoDB `get()` swallows all exceptions → silent skip → item destroyed, caller told success | **Reproduced on real dynamodb-local**; `db/dynamodb/property.py:144-158` confirmed — both the fresh-get branch and the `handle.refresh()` branch |
| PostgreSQL `set()` returns `False` on error; no `ListProperty` call site checks it → tail hole | **Confirmed in code; reproduced with fake** — but see Errata 2: PG logs an ERROR line, so "no error at all" is overstated |
| `insert()` on DynamoDB destroys the last element on every call into a non-empty list | **Reproduced on real dynamodb-local**, exact same rows; mechanism confirmed in PynamoDB semantics (`refresh()`/`save()` address the handle's own key) |
| Hole migration: one slot per front delete, fingerprint preserved | **Reproduced on real dynamodb-local** |
| `insert(0, header)` produces `length=7 readable=6 missing=[6]` — the production signature | **Reproduced on real dynamodb-local**; the falsification (consumer never calls insert) not re-checked, taken as reported |
| Read paths split: `to_list`/`slice`/`to_list_from_rows` compact; iterator/`index`/`count`/`remove` raise; `pop()` on trailing hole permanently stuck | **Reproduced** (all seven behaviours) |
| `handlers/properties.py` pairings and the two disagreeing counts (`:1526`, `:1642`, `:1677`, `:480/:513` vs `:525`, bulk POST `:937-1028`) | **All confirmed** at the cited lines; bulk POST loop confirmed to have no sort/reverse/re-read |
| FastAPI-only `/items` route; Flask has none | **Confirmed** (`fastapi_integration.py:1007-1008`; Flask catch-all would receive `name="foo/items"`) |
| `www.py:352` + `loop.index0`, shipped template read-only | **Confirmed** (`templates/aw-actor-www-property.html:26-28`; edit forms only in the non-list branch) |
| `actor.py:2527,2558` full-state build raises on a hole | **Confirmed**; scoped: only the fallback branch for peers lacking the `subscriptionresync` capability (`actor.py:2465-2489`) |
| No library call sites of `insert`/`pop`/`remove` on `ListProperty` | **Confirmed** with one clarification: the pass-through delegations in `NotifyingListProperty` (`interface/property_store.py:359-370`) exist but contain no logic; `remote_storage.py:394,425` call insert/remove on `ListAttribute`, a different class |
| Metadata self-heal resets `length` to 0 and orphans rows; `clear()`/`delete()` cannot reach orphans | **Reproduced / confirmed** (`property_list.py:102-126`, `:400`, `:418`) |
| Test-coverage claims (no hole tests; seven methods uncovered; `insert` only on empty lists) | **Confirmed** by audit; the two `insert(0,…)` tests run zero shift iterations (function-scoped fresh actor at `test_property_lists_advanced.py:52-53`); additionally `/items` GET has zero tests and `/items` POST is tested only with `action=add` (`test_spa_api.py:78,86`) |
| All 11 external references (AWS limits, Lambda lifecycle, fractional indexing, LexoRank, Powertools, awslabs/dynamodb-transactions, Sagas) | **All confirmed** against primary sources; figures exact (100 actions/4 MB; 25-request non-atomic batches; 400 KB item; 1024-byte sort key; 0 ms/500 ms/2,000 ms shutdown budgets; SIGKILL; LexoRank 128/160/254) |
| "Delete payoff of fractional indexing not written up" | **Not falsified** — a second, independently-angled search also found no prior art on fractional sort keys as a crash-safety fix for deletion specifically |

### Errata in the 2026-08-07 document

None of these changes a conclusion; recorded so the plan doesn't inherit them.

1. **Test-mock mechanism misdescribed.** `tests/test_property_list.py:78-101`
   does not patch `actingweb.property_list.get_property`; it mocks
   `mock_config.DbProperty.DbProperty.return_value` (`:81-82`), which works
   because `get_property()` is a factory over `config.DbProperty`
   (`db/__init__.py:85-88`) and `Mock.return_value` caches a single object.
   The document's *advice* (patch `get_property` with a dict-backed fake) is
   independently sound — this review's harness did exactly that — but the
   description of the existing pattern is wrong. Also worth knowing: no
   mocked-DB test in that file calls a single mutation method.
2. **"No error at all" on the PostgreSQL append path is overstated.**
   `db/postgresql/property.py:305-307` logs `Error setting property …` at
   ERROR before returning `False`. The corruption result stands (caller
   ignores the return and increments `length`), but there *is* a log line —
   unlike the DynamoDB read-swallow, which is genuinely log-free. Detection
   guidance should treat the two differently.
3. **PynamoDB `Connection` note: right hazard, wrong mechanism.** Verified
   against installed PynamoDB 6.1.0: `Connection.__init__` does `self.host =
   host` with no settings fallback, and `PYNAMODB_CONFIG` has no `host` key at
   all (`default_settings_dict` covers region/timeouts/retries only). A bare
   `Connection()` therefore passes `endpoint_url=None` to botocore — the real
   AWS regional endpoint — which is the hazard the note warns about, but not
   because settings override anything. Also confirmed: no client-side check of
   the 100-action transaction cap (and `parameter_validation=False` is set),
   so the limit surfaces only as a service `ValidationException`.
4. **The sibling is `ListAttribute`, and it shares the write-side defect.**
   The 08-07 document cites `attribute_list.py:473-492` only for its fail-fast
   `to_list()`. The same file's `__delitem__` (`:286-389`) is the same
   non-transactional delete-shift-length-last loop, including the
   skip-over-holes step (`:341,347`) — differing only in that errors are
   wrapped in `RuntimeError` with partial-state messages and `insert()`
   (`:543-641`) uses fresh handles (no DynamoDB `insert()` bug there). The
   crash-residue class therefore also exists for attribute lists, and
   `remote_storage.py:394,425` does call `insert`/`remove` on them.

### New finding: stale-cache / concurrent mutation is a fourth no-crash path

There is no locking or serialization anywhere around list mutations (the only
lock in the library is the JWKS cache lock, `oauth2_jwks.py:35`), and
`_meta_cache` is populated on first read and never invalidated by other
writers (`property_list.py:64-67`). Measured with the fake harness — two
instances, strictly sequential operations, zero backend errors:

```
lp1, lp2 over the same 5-item list; len(lp2) primes lp2's cache (length=5)
del lp1[0]   # completes normally: rows item1..item4 at 0..3, meta length=4
del lp2[3]   # lp2 still believes length=5; row 3 now holds item4
result: length=4, readable=3, to_list=['item1','item2','item3']
        -> production fingerprint, AND item4 destroyed instead of item3
```

The same residue falls out of genuinely concurrent mutations (two Lambda
invocations for the same actor interleaving their shift loops), where no cache
staleness is needed — both writers read `length=n`, both write `n−1`, and the
interleaved row writes produce holes/duplicates. The interleaved variant is
derived, not measured (the stale-cache variant above is measured and is the
deterministic reduction of it). Exposure note: `NotifyingListProperty` is
constructed fresh per attribute access (`interface/property_store.py:396-406`),
so within-request staleness is limited — the risk is held references and
cross-process concurrency.

Consequence for the options: crash-safety and error-handling fixes (Decision 3
options 1, 2, 7) do not touch this path. Transactions (option 3) do not either
— two serialized-but-interleaved shift transactions still corrupt. Only a
storage model whose delete is a single write against a key that never moves
(option 5; option 6 partially) removes it structurally, and stored-`length`
elimination (counting rows) removes the counter half of it.

### New constraint: prefix-query ambiguity for options 4 and 5

Today no code enumerates item rows by prefix — discovery is exact-name or
`-meta`-suffix based (`property.py:41-45`, `handlers/properties.py:439-443`),
so list names containing hyphens are currently unambiguous. Options 4 and 5
both want `Query(begins_with("list:{name}-"))`, and for lists named `foo` and
`foo-bar`, `begins_with("list:foo-")` matches both lists' rows (plus
`list:foo-meta`). Any query-based read/count therefore needs one of: a
client-side filter on the digit/rank tail, a new delimiter that cannot appear
in names, or list-name validation — and the migration has to handle names that
violate whichever rule is chosen. PostgreSQL has the identical issue with
`LIKE 'list:foo-%'`.

### New constraint: the positional wire contract

Storage-format options (4/5/6) change how rows are keyed, but two external
surfaces speak positional indices and cannot silently change:

- The REST API: `/properties/{name}/items` POST takes `index`; `PUT
  /properties/{name}?index=N`; the bulk POST takes per-item `index`
  (`handlers/properties.py:962`).
- The subscription diff protocol: every mutation registers a blob with
  `operation`, `index`, `length` (`interface/property_store.py:262-275`),
  consumed by subscribers and by `remote_storage.py`.

Under fractional keys both must be translated at the edge (position → key via
one query). That is workable — the same race between read and write exists
today — but it means Decision 5 (the `/items` index space) has to be settled
*before* or *with* any format change, not after.

## Evaluation of the options, decision by decision

### Decision 1 — `insert()` on DynamoDB

The 08-07 recommendation (**fix both** the call site and the backend,
immediately and independently of everything else) survives review, with one
adjustment: the stated cost of the backend fix is overstated. Honouring `name`
in `DbProperty.get()`/`set()` means comparing the requested `(actor_id, name)`
against `self.handle`'s keys and dropping the handle on mismatch — one string
comparison on a path that already does a network round trip. The pattern is
already proven in-tree: `ListAttribute.insert()` uses fresh instances per
operation and is correct on both backends. Note the protocol
(`db/protocols.py:118-131`) documents *nothing* about handle-vs-name
precedence, so the backend fix also needs a sentence in the protocol docstring
— today's DynamoDB behaviour is technically not a contract violation, which is
how it survived.

Test gap to close with it: both existing `insert()` tests run zero shift
iterations; a 3-item non-empty insert on the integration backend would have
caught this bug on day one.

### Decision 2 — reads: fail fast or keep compacting

No new option found; two facts sharpen the trade-off:

- The blast radius of converging on fail-fast is smaller than it looks: the
  compacting readers' only library consumers are the handlers, `www.py`
  (read-only template), and the subscription baseline path; `/items` GET has
  zero test coverage and `?format=full` is exercised by a handful of tests. The
  breaking risk concentrates on *already-holed production lists*, which is a
  repair-first sequencing problem (as the 08-07 document says), not an API
  problem.
- The already-inconsistent split is confirmed and now fully measured,
  including `pop()`'s permanent wedge on a trailing hole. Converging is
  strictly better than the status quo in either direction; the direction
  choice is genuinely open and belongs to the plan.

The 08-07 document's option 2 (`to_indexed_list()` returning
`(storage_index, value)`) is compatible with either direction and is the only
option that also fixes the REST `/items` contract without a behaviour break —
the handler can return storage indices and validate against them (Decision 5).

### Decision 3 — making mutation safe

Per-option refinements from this review:

1. **Update `length` first — confirmed dead.** Independent trace agrees with
   the 08-07 measurement: it converts a data-preserving detectable residue
   into silent loss of the final element (orphaned beyond `length`, then
   overwritten by the next `append()`). Nothing to add.
2. **Single-pass rewrite** — slightly better than the 08-07 document credits:
   the read half can be one existing partition query
   (`fetch_all_including_lists`, already used by `listall`), so a delete
   becomes 1 read + (n−i−1) writes + 1 delete + 1 meta write. Residues shrink
   to adjacent-duplicate or trailing-hole (never a mid-list hole, never extra
   destruction on the swallow paths *if combined with option 7*). Retry after
   interruption still deletes the wrong content. A real reduction of the
   window; not a fix. Does nothing for the concurrency path.
3. **Transactions — confirmed unavailable at the sizes that corrupted.**
   Arithmetic re-verified: deleting element 0 of the 202-element production
   list needs 403 actions against a hard cap of 100; PynamoDB adds no
   client-side check and the bare-`Connection` endpoint hazard is real
   (Errata 3). Note also transactions would *not* fix concurrent-shift
   interleaving — two serialized transactions shifting the same rows still
   corrupt. PostgreSQL-only transactions remain possible and remain a
   backend-divergence trap.
4. **Zero-pad + counted length — narrower than presented.** What it buys:
   retires the stored-counter class (including the metadata self-heal orphan
   bug and the stale-cache `length` half), enables single-query reads, and
   makes hole *fingerprints* impossible (counted length always equals readable
   rows — which cuts both ways: it also destroys today's only detection
   signal for a shift interrupted mid-way, whose duplicate residue remains).
   What it does not buy: the delete crash window — if indices stay dense, the
   shift loop and all its residues remain; if indices go sparse, delete is
   fixed but `insert()` between items has no key to use and dense positional
   `GetItem` addressing breaks anyway. Sparse integers are just option 5 with
   an exhaustible key space. Plus the prefix-ambiguity constraint above, plus
   a row-key migration that is itself an interruptible multi-write sequence
   (needs a format-version marker in the meta row so readers can tell which
   scheme a list is in mid-migration). Verdict: defensible only as an explicit
   waypoint to 5; as a destination it is the weakest of 2/4/5.
5. **Fractional index keys — strongest option, and the only one that closes
   the concurrency path.** Delete = one idempotent `DeleteItem` of a key that
   never moves; there is no shift to interrupt, no stored counter to skew, no
   wrong-row retry, and a concurrent pair of deletes deletes exactly the two
   intended rows. Verified practicalities: the Python port
   (httpie/fractional-indexing-python) is real, current (v4.0.0, 2026-08-06,
   tracking rocicorp v4.0.0), CC0-licensed, and byte-compatible with the JS
   reference; key growth is bounded in practice (LexoRank operates at 128-254
   chars against DynamoDB's 1024-byte sort-key budget minus the
   `list:{name}-` prefix). Two caveats the plan must own: concurrent inserts
   at the same position generate identical keys unless jitter is added (the
   upstream library deliberately ships none — for a last-writer-wins property
   store an identical key means silent overwrite, so jitter or a
   uniqueness-condition write is required); and the positional wire contract
   (REST + subscription diffs) must be translated at the edge. Same
   prefix-ambiguity and migration-versioning constraints as option 4. The
   delete-payoff framing remains original — a second independent search found
   no prior art.
6. **Order array in the meta row** — one new fact: in legacy reverse-lookup
   mode every property value is a GSI hash key capped at 2048 bytes, so a meta
   row carrying an order array would hit the legacy-mode write limit at
   roughly 100-200 ids. Combined with the 08-07 objections (reintroduces the
   two-write sync problem it set out to remove), this option is dominated.
7. **Error-handling fix — confirmed highest value per line, with a wider
   blast radius than the diff suggests.** The PostgreSQL half is contained:
   make `ListProperty` raise when `set()` returns `False` (~10 call sites in
   `property_list.py`), giving parity with DynamoDB's raise-on-write. The
   DynamoDB half — `get()` catching only `Property.DoesNotExist` (both
   branches, `:148-153` and `:154-158`) — changes failure semantics for
   *every* property read in the library: today a throttle reads as "property
   absent" everywhere (auth lookups, trust checks, OAuth state), after the
   fix it raises. That is the correct semantic (absence and error are
   different facts) but it is a library-wide behaviour change that needs its
   own test sweep, not a rider on a list fix. One scope note: the
   `set(value=None)` delete path also routes through the swallowing `get()`
   (`db/dynamodb/property.py:306-310`) and silently skips the delete on a
   transient error while returning `True` — traced here to be *benign* in
   `__delitem__` (the shift overwrites the row anyway, and in the
   delete-last-element case the orphan is logically dead and overwritten by
   the next append) but it is the same defect and should be fixed in the same
   pass.

The 08-07 sequencing recommendation (7 now → 4 as a waypoint → 5 as the
destination) is *weakened* by this review in one respect: given that option 4
does not close the delete window and adds its own migration, and given that
the concurrency path (new) is only closed by 5, the intermediate step buys
little — the defensible sequences are **7 → 5 directly** (one migration
instead of two) or **7 only**, with 5 as a designed-but-unscheduled follow-up.
That choice is a scope decision (Decision 6), not a technical one.

### Decision 4 — repair and detection

Confirmed as framed, with two additions:

- The detector asymmetry is now sharper: hole residue is detectable via the
  existing `listall` count divergence (`:525` vs `:513`/`:480`, confirmed);
  duplicate residue is invisible to it *and* the PostgreSQL write-swallow path
  leaves an ERROR log while the DynamoDB read-swallow leaves nothing —
  log-based detection helps on one backend only.
- A metadata-preserving `compact()` must decide its duplicate policy before it
  ships (refuse / report / rewrite); this review adds one datapoint for
  "report, don't bless": a crash-formed hole preserves all surviving content,
  so compaction of *hole* residue is always safe, while duplicate residue
  always means an item was destroyed — the two cases are distinguishable by
  whether `length > readable` at repair time.

### Decision 5 — the library's own `/items` skew

Confirmed, and the test audit adds: `action=update` and `action=delete` have
zero HTTP-level tests and `/items` GET has none, so whichever index-space
contract is chosen (storage indices, or compacted indices with a matching
bounds check) can be shipped without breaking any tested behaviour. The bulk
POST's independent intra-batch skew (`:937-1028`, no sort/reverse/re-read —
confirmed) needs fixing under either contract.

### Decision 6 — scope

The inventory grows by three items found in this review: the stale-cache /
concurrency formation path, the same shift design in `ListAttribute`, and the
`/items`-contract test vacuum. The 08-07 framing stands: this does not fit one
PR. The natural cut implied by everything above:

1. **P0, no design needed:** Decision 1 (both halves) + Decision 3.7 (both
   backends) + hole-simulation unit tests + non-empty `insert()` tests.
2. **Behaviour convergence, small design:** Decision 2 direction +
   `to_indexed_list()` + Decision 5 contract + `compact()`/detection
   (Decision 4), sequenced repair-before-fail-fast if fail-fast wins.
3. **Format change, real design cycle:** Decision 3.5 (fractional keys),
   covering migration versioning, prefix disambiguation, jitter/uniqueness,
   the positional edge translation, and whether `ListAttribute` migrates too.

## Decisions Needed

Unchanged from the 08-07 document in substance; restated with this review's
deltas:

1. **`insert()` fix scope** — evidence now firmly supports "both" (caller +
   backend + protocol docstring); the hot-path objection is retired.
2. **Read convergence direction** — still open; repair-path sequencing is the
   only hard constraint on the fail-fast direction.
3. **Mutation safety** — drop 1 (confirmed), 3 (confirmed unavailable), 6
   (dominated). Choose between: 7 alone; 7 + 2 (window narrowed, cheapest);
   7 → 5 (window closed, concurrency closed, one migration). 4 is only
   worth doing as an explicit waypoint to 5, and this review found the
   waypoint buys little.
4. **`compact()` duplicate policy** — refuse/report/rewrite; this review's
   datapoint: hole-only compaction is provably content-safe, duplicates never
   are.
5. **`/items` index space** — must be decided with or before any format
   change; currently unconstrained by tests.
6. **Cycle scope** — the three-tier cut above, or P0 only.

## Decisions Settled (2026-08-08, with the maintainer)

Settled the same day this review was written; `/create_plan` should treat
these as inputs, not open questions:

1. **`insert()` fix (Decision 1): both halves.** Fix the call site (fresh
   handles, copying `ListAttribute.insert()`'s pattern) and the DynamoDB
   backend (honour `name` against the cached handle), plus a protocol
   docstring sentence on handle-vs-name precedence.
2. **Read convergence (Decision 2): fail fast, repair ships first.** Converge
   `to_list()`/`slice()`/`to_list_from_rows()` on `ListAttribute`'s documented
   fail-fast behaviour. Hard sequencing constraint: `compact()` and
   remediation of known holed lists land before or with the read change.
3. **Mutation safety + scope (Decisions 3 and 6): everything in one cycle,
   7 → 5 directly.** One plan covering: the error-handling fix on both
   backends (3.7), the `insert()` fix, `compact()`/detection, fail-fast
   reads, the `/items` contract, tests, **and** the fractional-key storage
   migration (3.5). Option 4 (zero-padding) is skipped as a waypoint. The
   plan must own: migration versioning (format marker in the meta row, both
   formats readable during migration), list-name prefix disambiguation for
   range queries, jitter or conditional writes for concurrent inserts,
   position→key translation at the REST and subscription-diff edges, and
   whether `ListAttribute` migrates in the same cycle or follows.
4. **`compact()` duplicate policy (Decision 4): repair holes, report
   duplicates, never rewrite them silently** (hole compaction is provably
   content-safe; duplicate residue always means a destroyed item).
5. **`/items` contract (Decision 5): storage indices.** GET returns
   `(index, item)` pairs carrying storage indices (`to_indexed_list()`);
   POST update/delete validates against the same index space. Under
   fail-fast-plus-repair the two index spaces coincide anyway.

## Code References

Verified anew for this review (beyond those re-confirmed from the 08-07 doc):

- `actingweb/property_list.py:53,64-67` — `_meta_cache`, never invalidated cross-instance (stale-cache path)
- `actingweb/oauth2_jwks.py:35` — the only lock in the library; none around list mutations
- `actingweb/attribute_list.py:286-389` — `ListAttribute.__delitem__`, same shift design; `:341,347` skip-over-holes; `:377-381` length last
- `actingweb/attribute_list.py:543-641` — `ListAttribute.insert()`, fresh handles (the pattern Decision 1 should copy)
- `actingweb/remote_storage.py:394,425` — library call sites of `insert`/`remove` on `ListAttribute`
- `actingweb/interface/property_store.py:262-275` — positional subscription diff blob (`operation`, `index`, `length`)
- `actingweb/interface/property_store.py:359-370,396-406` — `NotifyingListProperty` pass-throughs; fresh wrapper per attribute access
- `actingweb/db/dynamodb/property.py:306-310` — `set(value=None)` delete routed through swallowing `get()` (benign in `__delitem__`, same defect)
- `actingweb/db/protocols.py:118-131` — protocol silent on handle-vs-name precedence
- `actingweb/property.py:41-45`, `actingweb/handlers/properties.py:439-443` — `-meta`-suffix discovery (why no prefix ambiguity exists today)
- `actingweb/templates/aw-actor-www-property.html:26-28` — read-only list rendering
- `actingweb/actor.py:2465-2489` — resync fallback branch that iterates (and raises on a hole)
- `tests/integration/test_property_lists_advanced.py:52-53` — function-scoped fresh actor (why the insert tests see empty lists)
- `tests/integration/test_spa_api.py:78,86` — the only `/items` HTTP tests, both `action=add`
- `tests/test_property_list.py:81-88` — the actual mock pattern (config-attribute, not `get_property` patch)

## External References

All eleven references in the 08-07 document were verified accurate. Additional
sources consulted for this review:

- <https://docs.aws.amazon.com/lambda/latest/dg/runtimes-extensions-api.html> — shutdown budgets 0 ms / 500 ms / 2,000 ms and SIGKILL, confirming the lifecycle figures
- <https://github.com/httpie/fractional-indexing-python> — v4.0.0 (2026-08-06), CC0, byte-compatible with rocicorp v4.0.0
- <https://github.com/rocicorp/fractional-indexing> — README: jitter deliberately not included; pointer to jittered variants
- <https://madebyevan.com/algos/crdt-fractional-indexing/> — jitter/interleaving analysis for concurrent inserts
- <https://support.atlassian.com/jira/kb/troubleshooting-lexorank-system-issues/> — 128 (rebalance in 12 h) / 160 (immediate) / 254 (hard cap) — operational thresholds, not an algorithm spec
- Installed PynamoDB 6.1.0 source (`pynamodb/connection/base.py`, `pynamodb/settings.py`, `pynamodb/transactions.py`) — `Connection(host=None)` → `endpoint_url=None` (real AWS); no `host` key in settings; no client-side 100-action check; `parameter_validation=False`
