# Verification: Spanned list items (Phases 1 and 2 only)

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** a176a82

**Scope.** This verifies Phases 1 and 2 (PR 1). Phase 3 (`append_once`) is
not implemented and not covered, so the plan's `verified:` link is not set
and the plan stays `status: active`. There is no feature document; the
plan's own headline measures stand in for success measures.

## Automated Check Results

- **Browser QA:** Not run. The only UI-facing change is
  `handlers/www.py:967` and `:1017` (`items_with_handles(resolve=False)` in
  the list item edit and delete actions). The demo app signs in only through
  a real OAuth2 provider and the contract names no test account, so a browser
  agent cannot reach `/<actor_id>/www`. Those two paths are unverified in a
  browser; they are covered only by `tests/test_bulk_list_update_handles.py`
  (`TestWwwActionEndpointDetectsRaces`).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`, unsandboxed) and a fresh-context Claude
  reviewer: 13 findings, folded in below.
- **Built-in code review** (`/code-review high a203f46..a176a82`, no
  `--fix`): 10 findings, folded in below.
- **Built-in security review:** no finding at or above the confidence bar.
  Checked and closed: envelope forgery across lists or actors, side-partition
  collisions, the `://` fold widening a match, content in 409/413 bodies and
  logs, remaining MCP fail-open paths, `resolve=False`/`item_at` bypassing the
  permission view, and diff references.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (454 files).
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings).
- `poetry run python tests/integration/verify_groups.py`: pass (51 groups).
- `make test-all-parallel` (DynamoDB): pass, 4,562 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL, the contract's env): pass, 4,416
  passed, 186 skipped.
- `sphinx-build -W --keep-going ...`: pass.
- Benchmarks (run alone, DynamoDB Local, from the implementation run at
  `a176a82`'s parent tree; not re-run here): plain 1,000-item list medians
  `to_list()` 11.62 ms, `items_with_handles()` 15.36 ms, append + remove
  35.46 ms, against the Phase 1 baseline 14.88 / 15.45 / 35.74 ms: within
  5%. With 20 spanned items: 52.08 / 63.14 ms, and 16.35 ms with
  `resolve=False`.

## Phase Verification

### Phase 1: Typed size error, backend-aware limits, the `://` fold, fail-closed list filters, baseline - ISSUES FOUND (minor)

**Changes verified:**
- `db/dynamodb/property.py` and `db/postgresql/property.py`: `MAX_ROW_BYTES`
  (`409_600`, `None`); `db/protocols.py` docstring names the capability.
- `config.py:324` pair rule after the kwargs loop; `:451-475` validating
  properties; defaults resolved from the kwargs' backend (declared deviation).
- `interface/app.py:603` `_apply_list_item_limits`, `:614`
  `with_list_item_limits` with the `_UNSET` pattern; validates against the
  effective other value.
- `property_list.py:333` `ListItemTooLargeError`, `:668` `_limits()`,
  `:683` `_check_item_size()`, called before `_v2_create_meta_row()` in the
  three creating mutators and before any v1 write.
- `handlers/properties.py:58` `_write_list_error`, `:104` the 413 writer;
  arms at `:894`, `:1602`, `:1652`, `:2417` ahead of the generic arms.
- `permission_evaluator.py:693` `pattern = pattern + "*"`; `grep
  "startswith(pattern)"` returns nothing.
- `handlers/mcp.py:1197`, `:1313`, `:1457`, `:1495`, `:1544`, `:1575`:
  empty list on construction failure, item skipped on evaluation error;
  `grep "fail-open\|and evaluator"` returns nothing.
- `tests/integration/test_harness.py` sets 390,000 / 4 MiB for both backends;
  `examples/demo/application.py:147` sets `MAX_CONTENT_LENGTH`.
- Todos: `permission-uri-prefix-branch.md` deleted with its row;
  `rest-permission-legacy-fallback.md` filed with a row.

**Tests verified:**
- `tests/test_list_item_limits.py`: defaults per backend and for a backend
  without the attribute, validation from kwargs and assignment, refusal with
  nothing written on a never-created list, the v1 DynamoDB/PostgreSQL split,
  no item content in the message, the 413 for PUT, `/items` add and update
  and the bulk POST. Meaningful.
- `tests/test_actingweb_app.py::TestListItemLimits`, the `://` fold tests in
  `tests/test_permission_pattern_matching.py`, and
  `TestListFiltersFailClosedOnEvaluatorErrors` (shown to fail on the old
  code during implementation).
- Integration: `TestPutOverMaxBytes` and `TestPostgresqlDefaults`, both
  backends.

**Failure scenarios:** each is covered as the plan says (never-created-list
assertion; property validation; MCP ERROR log and the 503 test;
`except` ordering tests; the harness limits make the PostgreSQL span suite
run).

**Deviations from plan:** the four declared in the plan's notes are
acceptable. Not declared: the www list editor maps `ListItemTooLargeError`
to 500 (Issue L2), and the bulk POST answers 413 after earlier entries
committed (Issue M4).

### Phase 2: Spanned items - ISSUES FOUND

**Changes verified:**
- `property_list_span.py`: envelope codec, shapes, `aux_partition`.
- `property_list.py:250` `ListItemSpanError`; `:144` `UNRESOLVED`; `:820`
  `_write_bodies`; `:874` `_write_spanning`; `:904` `_read_span`; `:972`
  `_resolve` with the two-reread bound; `:810` `_cascade`; `:1620`
  `sizes_from_rows`; `:3228` `item_at`; `:4053` `_copy_span_head`; `:4075`
  `_sweep_spans`; `:4454` the migration refusal; `:361`/`:409` diff
  references.
- `property.py:512` `_delete_side_partition` (three passes); `actor.py:579`
  the id refusal; `actor.py:3245` references in the full-state fallback;
  `remote_storage.py:398`; `maintenance/verify_orphans.py:216`;
  `maintenance/migrate_property_lists.py:381`;
  `maintenance/verify_property_lists.py:392`, `:401`.
- Handlers: `resolve=False` at `www.py:967`, `:1017` and four handle-only
  reads in `handlers/properties.py` (declared); `except ListItemSpanError`
  at `handlers/properties.py:2317`, `:2380`; `sizes_from_rows` at `:658`;
  `format=full` marker at `:679`.
- Enumeration audit: recorded in the plan's Phase 2 notes; no caller found
  that should learn the side partition and does not.
- Todos: `spanned-list-items.md` deleted with its row;
  `prop-list-key-prefix-scheme.md` amended.

**Tests verified:**
- `tests/test_property_list_span_codec.py` (39) and
  `tests/test_property_list_spans.py` (58, call order and counts asserted on
  a recording fake): round trip, row shape, deferred resolution, boundary,
  envelope refusals, cascades for every mutator, the actor-level wipe,
  reader races including the two-reread bound, broken spans, orphans and
  the age gate, compact's fresh generations and crash copies, the point-read
  race, residue, downgrade, partial `extend`, diffs and the receiver, the
  full-state fallback, the id refusal.
- Integration (both backends): HTTP round trip with a 1 MiB item, the broken
  span 409, a library cascade, the DynamoDB 450 KB row shape (DynamoDB Local
  enforces the cap), the PostgreSQL v1 migration; the script tests for
  `--spans`, `--sweep-spans`, the downgrade and the migrate refusal.
- Gap: no test drives a fault or an ambiguous `False` on a spanning head
  write (Issue H1), a concurrent delete under a reader (H2), or a broken
  span met by `compact()` (H3).

**Failure scenarios:** "Head write lost after bodies landed" is handled for a
clean `False` and tested, but its handling is wrong when the write committed
and the outcome was a raise or a retried-condition `False` (H1). "A reader
holding a stale head" is handled for a concurrent update, not for a
concurrent delete (H2). "A head whose bodies are really gone ... a crash
inside compact's own window" now also arises without a crash (H3). The
others are covered as the plan says.

**Deviations from plan:** the ten declared in the plan's Phase 2 notes are
acceptable as written; the `resolve=False` extension is the right call. The
`--sweep-spans` gate still runs a full rebalance (M7).

## Success Measures

No feature document. The plan's two headline measures:

| Measure | Target | Observable? | Evidence | Status |
| --- | --- | --- | --- | --- |
| A 1 MiB item round-trips through `append` and `to_list()` on DynamoDB, existing rows unchanged in shape, no body byte in a partition dump | Holds on both backends under the harness limits | Yes | `tests/integration/test_property_list_spans.py` `test_round_trip_cascade_and_actor_delete` asserts the round trip, three body rows in `{actor}$aux`, and no `$span-` row in `list_all_with_rows()` | Met (pre-ship, in tests) |
| `append_once` yields one item per key | Phase 3 | n/a | Not implemented | Not in scope |

**User experience walk-through:** no feature document. The consumer path
(store an item over 380,000 bytes, read it back, list without bodies)
exists end to end; the www edit path was not walked in a browser.

## Remaining Tasks

- [ ] Address the High and Medium issues below through `/iterate_plan`
      before PR 1 opens (each with a regression test).
- [ ] Phase 3 (`append_once`), on its own branch after PR 1 is open. Several
      findings below (H1, M1) sit on the same write path and should land
      first.

## Issues Found

### H1. A head write that committed but reported a fault or a retried `False` loses the item
**Severity:** High
**Description:** `_write_spanning` deletes the new body generation whenever
the head write raises or returns `False`. Neither proves the head did not
land: a timeout after DynamoDB applied the write raises `DbError`, and a
PynamoDB retry of a committed conditional write returns `False`
(`db/dynamodb/property.py:669-671`). The committed head then names deleted
bodies: the item reads as a broken span (409), the old generation is an
orphan the aged sweep deletes, and `--sweep-spans` removes the head. In the
append loop the same retry writes a second head at the next rank.
Raised by the code review and the outside voice.
**Location:** `actingweb/property_list.py:894-899` (`except BaseException:
self._span_delete_bodies(span)`; `if not landed: self._span_delete_bodies(span)`),
also `_v2_extend`'s fault path and `_copy_span_head`'s caller in compact.
**Recommendation:** on a raise or `False` after writing bodies, read the
head once; keep the bodies if it names the new generation, otherwise leave
them as an orphan for the aged sweep rather than deleting. Add fault and
retried-condition tests on the fake.

### H2. A concurrent delete makes a healthy list answer 409
**Severity:** High
**Description:** a reader that loaded a spanned head while `delete_by_handle`
/`pop`/`remove` deleted it and its bodies finds the bodies short, re-reads the
head, finds no row and raises `ListItemSpanError` ("its head is gone"). So
`to_list()`, GET of the list, `/items` and `?index=` answer 409 with a repair
hint for an undamaged list under ordinary concurrency. Raised by the outside
voice; confirmed in code.
**Location:** `actingweb/property_list.py` `_resolve`, the `if head_raw is
None: raise ListItemSpanError(...)` branch.
**Recommendation:** a head that is gone on the strong re-read is a deleted
item: drop it from whole-list reads and raise `IndexError` (not
`ListCorruptionError`) from point reads. Add the interleaving test.

### H3. `compact()` leaves duplicates without a crash when it meets an unreadable span
**Severity:** High
**Description:** `_copy_span_head` raises `ListItemSpanError` inside the
rebalance write loop, after earlier items were already written at new ranks;
the cleanup loop never runs, leaving the documented crash-window duplicates.
One broken span, or a spanned `update_by_handle` racing compact (its cascade
deletes the generation compact is about to copy), triggers it.
**Location:** `actingweb/property_list.py` `_v2_compact` write loop
(`self._copy_span_head(value, old_rank) if moved`) and `_copy_span_head`'s
`raise ListItemSpanError(...)`.
**Recommendation:** copy or at least read every moved spanned head's bodies
before the first write and abort with nothing written; document the race.

### M1. `delete()` racing an in-flight spanned append leaves a head without bodies
**Severity:** Medium
**Description:** `delete()` removes every `$span-` row of the list with no
age gate, including a fresh generation whose head has not landed; the head
then lands on the deleted list and is adopted by the next list created under
that name, answering 409. `clear()` avoids this by cascading only heads it
deleted; `delete()` does not.
**Location:** `actingweb/property_list.py` `delete()`,
`self._delete_aux_rows(self._aux_names("span") + self._aux_names("key"))`.
**Recommendation:** delete only generations named by deleted heads plus
unnamed generations older than `_SPAN_ORPHAN_MIN_AGE_SECONDS`, or document
quiescence for `delete()`.

### M2. A malformed head cannot be removed by the named remedies and blocks the list
**Severity:** Medium
**Description:** `_handle_for` raises on a malformed envelope, so
`items_with_handles(resolve=False)` fails for the whole list; every
handle-based REST mutation, `remove_where`/`update_where`, value scans and
`NotifyingListProperty.delete_by_handle` fail. `_sweep_spans` ignores
malformed heads, yet the verify script tells the operator to use
`delete_by_handle()`. Only positional `del lst[i]` removes one. Raised by
both reviewers.
**Location:** `actingweb/property_list.py:964-965` (`env =
self._parse_head(raw, rank)`); `_sweep_spans`
(`span_heads, _ = self._span_heads(pairs)`);
`actingweb/maintenance/verify_property_lists.py:204-209`.
**Recommendation:** give writers a tolerant handle (plain handle for a
malformed head), have `_sweep_spans` remove malformed heads, and correct the
script's message.

### M3. `verify(identity_key=...)` raises on a broken span and blocks `--sweep-spans`
**Severity:** Medium
**Description:** with an identity key, `_v2_verify` resolves every spanned
item; a broken one raises, `sweep_actor` counts the list as errored and
`continue`s before the sweep branch, so the remedy the 409 names never runs
when `--identity-key` is passed.
**Location:** `actingweb/property_list.py` `_identity_of`
(`self._resolve(raw_value, rank=rank, consistent=True)`);
`actingweb/maintenance/verify_property_lists.py:180-186`.
**Recommendation:** catch `ListItemSpanError` in `_identity_of`, exclude the
rank and report it under `broken_spans`.

### M4. The bulk POST answers 413 after earlier entries committed
**Severity:** Medium
**Description:** an oversized entry later in a bulk `items` batch raises
after earlier updates were written; the handler answers 413 ("nothing was
written" by the error's contract), registers no diff and skips the pending
deletes. A client retries thinking nothing changed. (The 500 path for other
errors was already partial; the 413 now claims otherwise.)
**Location:** `actingweb/handlers/properties.py:1602` (re-raise) and `:1652`
(the 413 arm); the v2 pass at `:1413`.
**Recommendation:** size-check every entry during the batch's validation
pass, before any write, the way `extend()` does.

### M5. Reference diffs: the merged full-state blob can still exceed the cap, and the built-in receiver never re-reads
**Severity:** Medium
**Description:** the full-state fallback applies `diff_reference` per list,
but an all-properties subscription merges scalars and every list into one
blob, which can still exceed 400 KB and fail the store. Separately,
`RemotePeerStore` answers a reference with `success: false` and every caller
discards the result, so a built-in mirror stays out of sync with a WARNING
whose "a resync brings it back" is false for a peer without resync. The
fallback also resolves every spanned body only to discard it.
**Location:** `actingweb/actor.py:3245`; `actingweb/remote_storage.py:398`;
callers in `subscription_manager.py` and `handlers/callbacks.py:621`.
**Recommendation:** apply the size rule to the merged blob; make the
receiver trigger a re-read (or document that a consumer handler must); read
with `resolve=False` when the result will be a reference; correct the
WARNING text.

### M6. Raising the span threshold makes value scans miss spanned items
**Severity:** Medium
**Description:** `_sought_value_cannot_span` compares the sought value with
the threshold configured now; an item that spanned under a lower threshold
is skipped, so `remove()`, `index()` and `count()` miss an equal item.
**Location:** `actingweb/property_list.py:2990` region,
`_sought_value_cannot_span`/`_head_equals`.
**Recommendation:** skip a spanned head only when the sought value's encoded
size differs from `span.bytes` (from the head, no read).

### M7. `--sweep-spans` runs a full rebalance copy
**Severity:** Medium
**Description:** the sweep is reached only through `compact()`, which then
rebalances and copies every moved spanned item's bodies; an orphan cleanup
becomes an O(total spanned bytes) copy, triggered even for orphans too young
to remove.
**Location:** `actingweb/property_list.py` `_v2_compact`;
`actingweb/maintenance/verify_property_lists.py` sweep branch.
**Recommendation:** expose the sweep as its own operation and call that from
the script.

### M8. An existing actor whose id ends in `$aux` is wiped by another actor's delete
**Severity:** Medium (only consumer-supplied pre-3.16 ids)
**Description:** `Actor.create` refuses `$` only for new ids. If a consumer
created `alice$aux` before 3.16, deleting `alice` deletes every `list:` row
of that actor.
**Location:** `actingweb/property.py` `_delete_side_partition`;
`actingweb/property_list_span.py` `aux_partition`.
**Recommendation:** add a pre-deploy audit to the migration guide (no actor
id containing `$`), or check for such an actor before sweeping.

### L1. The limit pair allows more than 9,999 parts
**Severity:** Low
**Description:** `span_threshold=100, max_bytes=4 MiB` is accepted; a large
item then fails in `split_parts` with a plain `ValueError` after the meta row
was created (400, not 413). Same for an existing `$` actor id at `_aux()`.
**Location:** `actingweb/property_list_span.py:111` `validate_limit_pair`.
**Recommendation:** require `max_bytes <= span_threshold * 9999`; check the
part count and `aux_partition` inside `_check_item_size`.

### L2. Status mapping gaps on the PUT index path and the www editor
**Severity:** Low
**Description:** `PUT ?index=` maps `ListItemSpanError` to 400 through
`except (ValueError, IndexError)`; the www editor maps it to 400 and
`ListItemTooLargeError` to 500.
**Location:** `actingweb/handlers/properties.py:897`; `actingweb/handlers/www.py:973`.
**Recommendation:** add the 409 and 413 arms ahead of the generic ones.

### L3. One malformed head fails the whole metadata GET
**Severity:** Low
**Location:** `actingweb/handlers/properties.py:658` (`sizes_from_rows`).
**Recommendation:** isolate per list, like `format=full`.

### L4. Smaller hygiene items
**Severity:** Low
- A pre-3.16 v2 item whose first key is `__aw_env` now reads as an envelope
  (`property_list_span.py` `parse`); report such heads in `verify()` or the
  migration guide.
- `_delete_side_partition` stops after three passes without a log line
  (`property.py`); log a WARNING naming the partition.
- `_read_span` checks the byte count only (`encoded_size(joined) !=
  span.bytes`); a short digest in the envelope would catch same-length
  wrong content.

## Overall Assessment

Phases 1 and 2 are implemented as planned, with the declared deviations, and
both full test suites, the type checks, the docs build and the benchmarks
pass. Phase 1 is sound apart from the bulk-413 and status-mapping gaps (M4,
L2). The security review found nothing exploitable.

Phase 2 is not ready to merge. The happy paths and the tested races work.
But spanning opens new ways into states that read as corruption under
ordinary faults and concurrency: an ambiguous head write loses the item
(H1), a concurrent delete makes a healthy list answer 409 (H2), and
`compact()` leaves duplicates on any unreadable span (H3). The repairs the
409 names cannot reach malformed heads, or broken spans when an identity key
is given (M2, M3). Fix H1-H3 and M1-M4 through `/iterate_plan`, each with a
regression test on the recording fake, before PR 1 opens; M5-M8 and the Lows
can be fixed or filed as todos then. The www path was not exercised in a
browser.
