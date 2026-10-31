# Verification: Spanned list items, Phase 3 (idempotent appends)

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-idempotent-append
**Commit:** 18d7541 plus the uncommitted Phase 3 working tree (nothing
committed yet)

**Scope.** Phase 3 (`append_once`), the last phase. Phases 1-2 were verified
seven times and merged as PR #162; their open items are carried below
unchanged. The owner asked this run to check that every piece of
documentation was updated, so the documentation sweep is its own section.
The plan has no feature document and no consumer message. **Stopping rule**
(verification 7): only a High or Critical is fixed in this plan; the rest
awaits the owner. **No todos** (owner rule): open items stay in this
document.

## Automated Check Results

- **Browser QA:** N/A. Phase 3 touches no page, template or route.
- **Second opinion:** outside-voice agent, providers codex (`codex exec -s
  read-only`) and a fresh-context Claude reviewer: 13 findings (5 codex, 8
  Claude), plus 3 unverified notes.
- **Built-in code review** (`/code-review high`, uncommitted diff): 10
  findings.
- **Built-in security review:** nothing at or above its bar. It checked
  authorization (`_PermissionEnforcingListView.append_once` checks `write`;
  no HTTP, handler or MCP route reaches the method), the key and HMAC
  handling, row-name injection, leakage across actors and lists, and
  envelope forgery (`encode_item` refuses the reserved key).
- **Full tier**, run on this tree in this session after the last code
  change (since then only `thoughts/` files changed, so it was not re-run):
  - `ruff check`, `ruff format --check` (460 files), `pyright` (0/0): pass.
  - `verify_groups.py`: all 51 groups documented.
  - `make test-all-parallel` (DynamoDB): 4931 passed, 40 skipped, 1
    xfailed (the strict `xfail` below).
  - `make test-all-parallel` (PostgreSQL): 4739 passed, 232 skipped, 1
    xfailed.
  - `sphinx-build -W ...`: pass.
- **Benchmark** (`-m benchmark -k list_property`, run alone, DynamoDB
  Local, medians):

  | Benchmark | Phase 2 | Phase 3 |
  | --- | --- | --- |
  | `to_list()` | 11.62 ms | 12.75 ms |
  | `items_with_handles()` | 15.36 ms | 12.39 ms |
  | append + remove | 35.46 ms | 23.53 ms |

  The differences are noise; the unkeyed paths gained only a prefix check.
- Plan grep: no added line in `property_list.py` matches
  `pending|claim|Retry-After`.

## Phase Verification

### Phase 3: Idempotent append - ISSUES FOUND

**Changes verified:**
- `AppendOnceResult` and `ListItemHandle.key_hash`
  (`actingweb/property_list.py`, below `ListItemHandle`); `_handle_for`
  sets `key_hash`. Exported from `actingweb/__init__.py`. Matches the plan.
- `append_once`, `_v2_append_once` and their helpers. The protocol is the
  plan's, with the deviations recorded in the Phase 3 implementation notes:
  - the read-back reuses `_landed_anyway`;
  - step 3 leaves extra keyed heads for `compact()`;
  - a lost step-3 create continues to the write;
  - `verify()` reports lists of ranks.

  All four are acceptable as reasoned. The first two are where V8-1 and
  V8-3 below come from.
- Key rows die with the item: `_retire_key_row` is called in
  `delete_by_handle`, `_v2_pop`, `_v2_remove` and `_v2_delitem`, and
  deletes a key row only when it names the deleted head's token. Matches
  the plan, and adds the token guard.
- `_key_report` in `_v2_verify`, and `_repair_keys` in `_v2_compact`.
  Matches the plan; see V8-3.
- Wrappers: `NotifyingListProperty.append_once`
  (`interface/property_store.py`) and
  `_PermissionEnforcingListView.append_once` (`write`). Match the plan; see
  V8-4.
- Not planned: the gating of `verify_property_lists.py --repair`. It was
  added to make the repair path the docs describe exist. See V8-3.

**Tests verified** (`tests/test_property_list_append_once.py`, 39 tests
plus 1 strict `xfail`):
- Every unit case the plan lists has a test, except "a fault in
  `_v2_create_meta_row` leaves no key row": it is covered at `:357`
  (`test_meta_row_fault_writes_no_key_row_and_no_head`). The plan's
  "`count_hint` is 1" and "two point reads, no range read" are both
  asserted in `:203`.
- **Security property, key never stored or logged:** `:182`
  `test_first_call_creates_and_stores_only_the_hash` asserts
  `not any(KEY in str(k) or KEY in str(v) for k, v in store.items())`, and
  that the head and key row carry `_hash()`. `:245`
  `test_invalid_keys_are_refused_before_any_write` asserts that a refused
  key is in neither `caplog.text` nor any backend call. No test asserts the
  absence of the key from the logs on the happy path; the only new log line
  prints `env.key[:8]` (see V8-5).
- **Per-actor HMAC:** `:222` asserts that one key hashes differently under
  two actors.
- Integration (`tests/integration/test_property_list_append_once.py`, 5
  tests): pass on both backends.
- Changed tests: `test_verify_without_spans_reads_no_bodies`,
  `test_identity_verify_resolves_each_spanned_item`,
  `test_v2_verify_still_reports_the_same_way`, and the
  proxy-classification table in `test_authenticated_views.py`. Each
  change is justified by the new key-row read, report keys or method.
- **Gaps:**
  - nothing tests the script's new `--repair` gating;
  - no test runs `compact()` concurrently with `append_once`, or an
    eventually consistent read that lags (the fake reads are always
    current), which is why V8-1 to V8-3 passed.

**Failure Scenarios** (plan -> evidence):

| Scenario | Evidence |
| --- | --- |
| Two repeats overlap | `:367`, `:382` |
| The loser's delete fails (False / `DbError`) | `:400`, `:415` |
| Crash between head and key row; no repeat ever comes | `:275` (reported, then finished); `:550` (`compact()` writes the row) |
| A dangling row's hint is our own reused rank | `:308` |
| A stale hint after `compact()` | `:334`, and the integration test |
| A repeat after deletion | `:509`, and the integration test |
| Attempt budget exhausted | `:437` |

All pass. The scenario tests run on a fake whose reads are always
current, so they cannot show V8-1 or V8-2.

## Documentation sweep (owner's request)

Updated in this phase and checked:
- `docs/guides/property-lists.rst`: new "Idempotent appends" section, and
  the SDK-retry sentence narrowed.
- `docs/migration/v3.16.rst`: Start-here item 16 and an "Idempotent
  appends" section.
- `CHANGELOG.rst`, Unreleased ADDED: one entry with its **Behavior change**.
- Docstrings: `append_once`, `_v2_verify`, `_v2_compact`,
  `_landed_anyway`, `_write_spanning`, `_v2_write_item_at_new_rank`.
- `NotifyingListProperty.append_once` is pulled in by `automodule`
  (`docs/reference/interface-api.rst:26`). `actingweb.property_list` has no
  autodoc page, which predates this phase.
- `thoughts/todo/`:
  - `idempotent-list-item-create.md` is deleted and its row is gone;
  - `conditional-write-ambiguous-after-sdk-retry.md` is narrowed and its
    row updated;
  - `subscription-subscriber-fault-hardening.md` is updated.

Not updated, or now wrong (all in V8-5 and V8-6):
- `docs/guides/property-lists.rst:177` says "A v2 mutator that raises
  ``DbError``, ``RuntimeError`` or ``ListMetadataContentionError`` did NOT
  commit its item row". `append_once` can raise `DbError` after its head
  committed: the key-row create faults (`:275` relies on exactly that), or
  the loser's delete faults (`:415`).
- `docs/guides/property-lists.rst:759`, `docs/migration/v3.16.rst:769` and
  the `append_once` docstring say "Every answer is final". V8-1 and V8-3
  show answers that are false when returned.
- `docs/guides/property-lists.rst:779`, the docstring (`:2872`) and
  `CHANGELOG.rst:834` say "A repeat is two point reads". After any
  `compact()` moved the item, a repeat makes a strong range read plus a
  compare-and-swap. The docstring's "two range reads" per pass can be
  three.
- `docs/guides/property-lists.rst:807`, `CHANGELOG.rst:841` and
  `_v2_verify`'s docstring say keys are reported "never by hash", while the
  `_retire_key_row` WARNING logs `env.key[:8]`. The plan asked for exactly
  that prefix in logs ("Logs name the first 8 hex of the hash"), so only
  the wording conflicts.
- The "Idempotent appends" section does not say that `compact()` and
  `--repair` need writes quiesced. The `compact()` docstring and the
  guide's repair warning (`:995`) say so, for compaction in general.
- `docs/guides/property-lists.rst:991` says v2 `verify()`/`compact()` serve
  "a different purpose: detecting and rebalancing rank keys". They now also
  repair keyed duplicates and key rows.
- `actingweb/maintenance/verify_property_lists.py:12` and `:25` (module
  docstring): v2 "unhealthy" means only rank-key length, and `--repair`
  only rebalances. Both are stale.
- `docs/sdk/authenticated-views.rst:155-161` lists the handle and identity
  mutators with their permissions and omits `append_once` (`write`). The
  "Every method ... is reachable" sentence covers it only implicitly.
- `docs/sdk/developer-api.rst:77`: the API summary lists `to_list()`,
  `find()` and `items_with_handles()`, but not `append_once()`.
- `thoughts/todo/INDEX.md:48` (the subscription-subscriber row) still says
  it "pairs with the idempotent list-item create", a todo this phase
  deleted. The todo file itself was updated.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-7.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V7-1 Basic drop broke OAuth client auth (High) | Fixed | entries 64-65, merged in PR #162 |
| V7-2 dropped Basic gives a Basic challenge (Medium) | Still open, owner scope decision | no change |
| V7-3 property name with `/` (Medium) | Still open, owner scope decision | no change |
| V7-4 `approved: false` answers 500 (Low) | Still open | no change |
| V7-5 dot-only trust row cannot be deleted (Low) | Still open | no change |
| V7-6 `{actor_id}` SPA `return_path` lacks base path (Low) | Still open | no change |
| V7-7 invalid outbound URL answers 408 (Low) | Still open | no change |
| V7-8 cleanups (Low) | Still open | no change |

All of these belong to the cross-site and demo hardening the owner took out
of this plan's scope on 2026-10-31.

## Remaining Tasks

- [ ] V8-1 and V8-3 (High), in an iteration batch, per the stopping rule.
- [ ] The owner's decision on V8-2, and on the Mediums and Lows below.
- [ ] Commit Phase 3 and open PR 2 (not done; awaiting the owner).

## Issues Found

### V8-1. A repeat can adopt a deleted item from the eventually consistent scan
**Severity:** High
**Sources:** codex 2; code review 1.
**Location:** `actingweb/property_list.py:2763` (`found =
self._keyed_heads(key_hash, consistent=False)`) and `:2770` (`rank, raw,
env = max(found, ...)`), followed by `return self._keyed_result(rank,
raw)`. For an inline item, `_resolve` returns `env.value` without reading
the head.
**Failure:**
1. A keyed item is deleted: the head goes, and the key row goes or never
   existed.
2. A repeat within the replica lag reads the old head from the scan.
3. It creates a key row naming that head and returns `created=False`, with
   the deleted item and a handle to nothing.

The client believes the item is stored, and the key row it created is
dangling. This is the guide's promised path: "a repeat with the key creates
it again".
**Recommendation:** after choosing the head, point-read it strongly
(`_read_head_tolerant`). If it is gone, or no longer carries the key and
token, do not adopt it. Add a test with a fake whose range reads lag.

### V8-2. On DynamoDB, the eventual step-3 scan can miss a crashed head, leaving two items for one key
**Severity:** Medium (owner decision)
**Source:** codex 3.
**Location:** `actingweb/property_list.py:2763`.
**Failure:**
1. Call A writes its head and dies before its key row.
2. Repeat B's eventually consistent scan misses A's head.
3. B writes its own head and wins the key row.

Every later repeat follows B's row, and only an operator `compact()`
removes A's copy. The plan chose an eventually consistent scan because
"the write it looks for is at least a request old". A repeat after a
gateway timeout is about 30 s later, so in practice the replica has caught
up.
**Recommendation:** either scan strongly (twice the read capacity on a
first call, the cost the plan saved), or name it in the guide as a third
window. The owner's call.

### V8-3. `compact()`, `--repair` and `healthy` act on a state that is normal while calls are in flight
**Severity:** High
**Sources:** codex 1 and 5; Claude 6, 7 and 9; code review 6 and 9.
**Location:**
- `actingweb/property_list.py:4483-4485`: `_repair_keys` drops a key row
  whose key hash has no head in the heads it loaded earlier.
- `actingweb/property_list.py:4496`: `keep = max(keyed, ...)`, then the
  delete of the other heads.
- `actingweb/property_list.py:4365`: duplicates make `healthy` false.
- `actingweb/maintenance/verify_property_lists.py:374`:
  `report["needs_rebalance"] or report.get("duplicate_keyed_items")`.

**Failure:** two overlapping calls, or a call between its head and its key
row, look exactly like `duplicate_keyed_items` and `unkeyed_keyed_items`.
A sweep with `--repair` on a live fleet sees the duplicate, marks the list
unhealthy and runs `compact()`. `_repair_keys` then:
- deletes the head of a call that is about to win its key row, which then
  returns `created=True` for an item that is not stored;
- or drops the key row an append created after compact read the heads.

Step 3 was changed so it never deletes another writer's head, for this
exact reason. The repair path reintroduces it, and `--repair` now triggers
it on lists it would have left alone, rewriting every row of the list to
delete one.
**Recommendation:**
- count a keyed duplicate or an unkeyed head toward `healthy`, the
  script's gating and `_repair_keys` only when its token is older than a
  grace age (the token carries a millisecond timestamp, as span orphans'
  gens do, `_SPAN_ORPHAN_MIN_AGE_SECONDS`);
- re-read strongly before dropping a key row;
- in the script, run the key repair without the rebalance when only keys
  need it.

Test with an interleaving fake.

### V8-4. A repeat that finishes a crashed call sends no diff and leaves `count_hint` one low
**Severity:** Medium
**Sources:** code review 3; Claude 8.
**Location:** `actingweb/interface/property_store.py:447` (`if
result.created:`); `actingweb/property_list.py:2986` (the touch only in
`_created`).
**Failure:** this is the motivating case.
1. The first call writes its head and times out before its key row and its
   diff.
2. The repeat finishes it and returns `created=False`.
3. No subscriber ever hears of the item, and `count_hint` stays low until a
   counting mutation.

`compact()`'s `key_rows_created` path has the same gap.
**Recommendation:** when step 3 adopts a head that had no key row, report
that, for example with an internal flag, so the wrapper registers the
`append` diff and the touch runs. The public `created=False` stays as it
is.

### V8-5. The documentation claims more than the code
**Severity:** Medium
**Sources:** this run's sweep; codex 5; Claude 12 and 13.
**Location:** the first five bullets of "Not updated, or now wrong" above:
the raise guarantee at `property-lists.rst:177`, "Every answer is final",
"two point reads", "never by hash" against the 8-hex log prefix, and the
missing quiescence note.
**Recommendation:**
- give `append_once` its own sentence in the guarantees list: a `DbError`
  can follow its committed head, and a repeat converges;
- qualify "final" to calls not racing a `compact()` or a delete;
- correct the costs;
- scope "never by hash" to `verify()`'s report, or log the rank instead;
- add the quiescence note.

### V8-6. Documentation not updated for the new API
**Severity:** Low
**Location:** the last five bullets of "Not updated, or now wrong" above:
`property-lists.rst:991`, the script's module docstring,
`docs/sdk/authenticated-views.rst:155-161`, `docs/sdk/developer-api.rst:77`,
and `thoughts/todo/INDEX.md:48`.
**Recommendation:**
- add `append_once` (`write`) to the authenticated-views list and to the
  API summary;
- extend the v2 repair sentence and the script docstring;
- update the INDEX row.

### V8-7. The rank cache goes off by one on the arbitration paths
**Severity:** Low
**Sources:** code review 2; Claude 10.
**Location:** `actingweb/property_list.py:2984`
(`self._v2_rank_cache.append(rank)` after a strong scan has already cached
the rank); `_retire_own_head` does not drop the rank it deleted.
**Failure:** `len()` on that instance is one too high after a
dangling-row retry or a lost race. A fresh instance is correct.
**Recommendation:** append only if the rank is absent, and remove the rank
in `_retire_own_head`.

### V8-8. A keyed `str()`-fallback item with non-ASCII text can outgrow the row
**Severity:** Low
**Source:** Claude 11.
**Location:** `actingweb/property_list.py:993` (`return
wrap(value=item, key=key, tok=tok, extra=extra)`). `json.dumps` escapes
non-ASCII to `\uXXXX`, while the size check measured the UTF-8
`value_str`.
**Failure:** a value `json` cannot encode, whose `str()` is about
66-390 KB of non-ASCII text, passes the check and fails at DynamoDB's
400 KB cap inside the envelope. It is an untyped `DbError`, raised before
any key row is written.
**Recommendation:** measure the wrapped head when deciding to span a keyed
or carried item.

### V8-9. Smaller protocol edges
**Severity:** Low
**Sources:** code review 4, 5 and 8.
- `actingweb/property_list.py:2777`: a lost step-3 create whose row has
  vanished on read-back makes the call write a second head, a duplicate
  `compact()` removes.
- `:2749`: the best-effort hint rewrite and the dangling-row drop in
  `_find_keyed` let a `DbError` fail a repeat that already found its item.
- `_key_rows` repeats `_aux_names("key")`'s prefix and shape filter.
  `_keyed_heads` and `_keyed_by_hash` repeat the same envelope loop.

**Recommendation:**
- treat the vanished row as "retry the create";
- make the hint repair best-effort (WARNING);
- share one enumeration and one parse.

### V8-10. The script's new gating is untested
**Severity:** Low
**Location:** `actingweb/maintenance/verify_property_lists.py:374`.
**Recommendation:** a script test for a list whose only finding is
`duplicate_keyed_items`, written with the V8-3 change.

Accepted, not issues: the O(heads) read on a first call (code review 7) is
the plan's recorded decision and cost. A `compact()` overwriting a head
written after its read (codex 4) predates keys and falls under compact's
documented quiescence; V8-3's guard and the V8-5 note cover what keys add.

## Overall Assessment

Phase 3 is complete against the plan. Every planned test exists and passes
on both backends, the security review finds nothing, and the documentation
the plan named is written. The unit tests pin each protocol branch,
including rank reuse, adopting our own head, a stale hint, and the strict
`xfail` that keeps the narrowed SDK-retry todo honest.

The reviews found one gap the tests cannot see: eventually consistent reads
and repairs running while calls are in flight. Two of the resulting
findings are High:
- **V8-1:** a repeat can adopt an item that was just deleted.
- **V8-3:** the repair path, now triggered by `--repair` on live lists, can
  delete an in-flight call's head and turn its `created=True` into a lie.

Both need fixing before PR 2 opens, under the stopping rule. The sweep the
owner asked for found the docs mostly in place, with the overclaims in V8-5
and the small gaps in V8-6. The plan stays `status: done` without a
`verified:` link until a run finds no High.
