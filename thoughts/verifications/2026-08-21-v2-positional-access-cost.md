# Verification: v2 list read cost — the 3.14.0 release

**Date:** 2026-08-21
**Plan:** thoughts/plans/2026-08-20-v2-positional-access-cost.md
**Research:** thoughts/research/2026-08-20-v2-positional-access-cost.md,
thoughts/research/2026-08-20-v2-cost-in-library-callers.md
**Branch:** release/3.14.0-v2-positional-access-cost
**Commit:** 3f96742
**Scope:** all 14 phases plus the plan's "Post-Verification Changes
(2026-08-21)" section (the six post-PR-#134-review fixes), plus a check
that every PR #134 review comment has been actioned.

Verification was run with six parallel read-verification agents (one per
phase group) plus firsthand automated checks. Every file cited below was
read at HEAD, not taken from the plan's claims.

## Automated Check Results

- **Ruff (check):** Pass — `poetry run ruff check actingweb tests`, 0 findings.
- **Ruff (format --check):** **19 files would reformat** (the four `test_v2_*`
  files plus 15 source files from Phases 9–11). The plan's Implementation
  Summary claims `ruff format --check` at 0 errors while its own Deviations
  admit 18 drifting files and attribute them to "an environment ruff version
  difference" — but the local ruff (0.15.20) **matches poetry.lock exactly**,
  so that explanation does not hold; the committed formatting simply differs
  from what the pinned formatter produces. CI only enforces `ruff check`
  (`.github/workflows/tests.yml:492-493`), so this does not break the build.
  Low severity, but the plan's stated explanation is wrong.
- **Pyright:** Pass — `poetry run pyright actingweb tests`, 0 errors,
  0 warnings.
- **Pytest:** Pass — `make test-all-parallel`: **3034 passed, 31 skipped,
  0 failed** (7m20s, DynamoDB + PostgreSQL test containers).
- **CI on PR #134:** green on both backends after the fix commit
  (dynamodb 3017/3048 passed, postgresql 2918/3048 passed, rest skipped,
  0 failed, no flakiness detected).

## PR #134 Review Comments — all actioned

The PR carries one Codex review (4 inline findings: 1 P1 + 3 P2) and one
Claude review that independently confirmed the same 4 findings plus a
CHANGELOG-accuracy note following from the P1. All were actioned in commit
3f96742 and verified in code here (see "Post-Verification Changes" below):

1. **P1 — `update_by_handle()` diffs dropped by peers** → fixed
   (`remote_storage.py:397` guard widened; test added). The dependent
   CHANGELOG claim is now accurate *for 3.14 peers* — but see Issue 1
   below for the cross-version half.
2. **P2 — v2 bulk batch same-index append/delete divergence** → fixed
   (`handlers/properties.py:1243-1312`), but with **zero test coverage**
   (Issue 2).
3. **P2 — remove_where/update_where prefix-assumption diffs** → fixed at
   the core layer (`property_list.py` returns actual items,
   `list[Any]`), tests updated.
4. **P2 — stale cached format recheck after fresh dispatch** → fixed
   (`_v2_items_with_handles()` at `property_list.py:2301-2317`), untested
   for the stale-cache-then-migration scenario it exists for.

Plus two maintainer-initiated fixes from the `old_item` architecture
review (duplicate-value ambiguity handling; spec de-SDK-ification), both
verified landed. The four GitHub review threads remain **unresolved** on
the PR (3 marked outdated) — code-actioned but not closed out in the UI.

## Phase Verification

### Phase 1: Tell the truth + cold-start DescribeTable budget — VERIFIED

- All five documentation-correction sites present
  (`db/protocols.py:216-224`, `property_list.py:454-460, 1016-1023,
  2213-2216`, `docs/guides/property-lists.rst:19, 109-125`); two were
  later legitimately superseded by Phases 5 and 9B with stricter text.
- `tests/test_cold_start_budget.py` (3 tests) verified meaningful,
  including the zero-control-plane-calls pin for
  `AWS_DB_AUTO_CREATE_TABLES=false`.
- **Deviation (Low):** the test derives models from `required_models()`
  dynamically with no count pin, so adding a new PynamoDB model grows the
  cold-start budget silently — the plan explicitly wanted the opposite.

### Phase 2: AuthenticatedPropertyListStore TypeError + write gap — VERIFIED (security fix confirmed)

- `_PermissionEnforcingListView` (`authenticated_views.py:186-337`) is
  fail-closed: no `__getattr__` fallback, all mutators gated (`write`),
  destructive ops gated (`delete`); `delete(name)` fixed; `create()`
  removed. No public accessor leaks the raw store. The four Phase 10/11
  mutators added later are all gated.
- Tests verified: read-only context blocked *before* delegation, write
  context delegates, `create()` absence pinned, surface parity asserted.
- **Deviation (documented, Low):** `pop()`/`remove()` gate on `write`
  while `remove_where()` gates on `delete` — recorded in the plan, but
  inconsistent and undocumented in `docs/sdk/authenticated-views.rst`.
- See Issue 5: the surface-parity test proves name equality, not
  enforcement.

### Phase 3: Library's own callers stop paying — VERIFIED (with test gaps)

- `list_all_with_rows()` public with the opacity contract
  (`property.py:54-90`); `www.py`, `trust.py` (including the phantom-list
  bonus fix), `actor.py:2554-2591` subscription fallback, de-bounds-checked
  handler sites, and the `len()`-free append diff all verified.
- `tests/test_v2_cost_library_callers.py` (10 tests) asserts exact query
  counts against real DynamoDB Local — strong coverage.
- Deviations where Phases 4/5/11 superseded Phase 3's literal text are
  all correct end-states.
- See Issue 7 (append diff index now advisory) and three Low test gaps
  (Remaining Tasks).

### Phase 4: Plain-property reads exclude list rows — VERIFIED

- DynamoDB range-pair with the `list;` (0x3B) sentinel
  (`db/dynamodb/property.py:697-729`); PostgreSQL `NOT LIKE 'list:%%'`
  with the collation rationale; empty-partition `{}` contract on both
  backends; `fetch_all_including_lists()` untouched.
- All planned tests present including the non-ASCII list-name sentinel
  test (`tests/test_v2_cost_plain_property_partition.py`), PostgreSQL
  mirrors gated on backend.

### Phase 5: Advisory count — VERIFIED (implementation) / ISSUES (contract coverage)

- `count_hint` plumbing complete and correct across all mutators;
  `get_metadata()` serves the hint with counted fallback; REST `count`
  sites hint-served; `verify()` reports drift excluded from `healthy`;
  `compact()` repairs. Drift bound documented as contract with all three
  terms and the quota recipe (`docs/guides/property-lists.rst:148-184`).
- 10 meaningful tests in `tests/test_v2_count_hint.py`.
- **Issue 6:** the third drift term (failed advisory touch) has no test
  asserting the drift or its repair, anywhere at HEAD — the Phase 5
  deferral target (Phase 9) has passed without discharging it.

### Phase 6: consistent_read per-call — VERIFIED

- Parameter threaded protocol → both backends → `ListProperty` → both
  wrapper layers; every default `True` (enumerated); `get_last_in_range`,
  `_v2_ensure_rank_cache`, `items_with_handles` unconditionally strong on
  all legs; zero handler call sites spend the guarantee (AST-pinned).
- 10 meaningful tests; the positional-mutator signature test is stronger
  than the plan asked.
- Low notes: a weak read still warms the rank cache (stale `len()`
  possible after `to_list(consistent=False)` — docs-precision only, no
  library path passes `False`); the AST guard only catches a literal
  `False` and globs non-recursively.

### Phase 7: Value-addressed reads — VERIFIED

- `find()`/`find_all()` universal, `items_with_handles()` v2-only with
  the stale-replica rationale in-code; frozen `ListItemHandle` with
  `repr` omitting `raw_value`; both wrapper layers delegate; docs carry
  the generation caveat explicitly.
- 14 meaningful tests including exact query counts and the
  raw-value round-trip against actual stored bytes.

### Phase 8: Conditional-set + last-rank primitives — VERIFIED

- `set_if_value_equals` / `get_last_in_range` on protocol and both
  backends exactly as specified (condition-failure → `False`, fault →
  `DbError`; `COLLATE "C"` on bounds *and* ordering in PostgreSQL).
- Cross-backend integration tests present including the byte-order
  case boundary. Low: the DbError-on-genuine-fault half is untested;
  concurrency simulated sequentially.

### Phase 9: Metadata CAS — VERIFIED

- Bounded jittered CAS retry with stash-then-fresh-read semantics; row
  9c fresh-dispatch discipline with the retained staleness WARNING;
  v1 length deltas; `ListMetadataContentionError` exported and mapped to
  503 + `Retry-After` at all four JSON handler sites; advisory carve-out
  (`advisory=True` on every `_v2_touch_metadata`) verified.
- Both sides of the carve-out boundary are pinned by tests; the
  documented 503-never-after-committed-v2-write invariant holds for every
  advisory path; the two non-advisory writes that follow a committed
  write (`_v2_compact()`'s counted-truth hint, v1 `__setitem__` touch)
  are idempotent on retry, so the rationale survives — noted, Low.
- Deviations disclosed in the plan (integrity-suite rewrites) confirmed
  as described. `www.py`'s HTML UI has no contention handler (Low,
  consistent with docs which name only the three JSON handlers).

### Phase 9B: append()/extend() last-rank point read — VERIFIED

- `_v2_last_rank()` with the legacy-`#`-sibling fallback; single
  last-rank read per `extend()` batch; collision re-key from the
  collision point; v1 untouched; warm-cache-only sync (the
  infinite-loop fix) pinned by test.
- Deviation (Low): the plan-named cross-backend interleaved-append
  integration test was not added; nearest coverage is a pre-existing
  weaker test.

### Phase 10: Handle mutations + value-addressed writers — VERIFIED

- All four mutators present with the exact contracts (single-shot
  conditional writes, no retry inside `*_by_handle`, v1 rejection naming
  `migrate_to_v2()`, descending v1 delete order); the silently-dropped
  `remove()` peer notification fixed and regression-pinned; permission
  gating exact; no new operation names on the wire; docs complete
  including the fan-out arithmetic.
- 17 meaningful tests in `tests/test_v2_handle_mutators.py` (including
  the stale-handle generation-boundary test and exact query-count
  assertions) plus notification and remote-storage suites — 118 passed
  when run directly.
- See Issues 3 and 4 for the `None`-value diff gap and the silent
  ambiguous-match drop.
- Deviation (Low): two plan-named peer-replica integration tests don't
  exist; coverage is split into sender-side and receiver-side unit tests
  — each half pinned, but no end-to-end sender→receiver test.

### Phase 11: Bulk endpoint moves onto handles — VERIFIED (with issues)

- v2 branch resolves handles once (`items_with_handles()` at
  `handlers/properties.py:1143`), updates then descending deletes via
  handle mutators, per-item conflict reporting, v1 branch byte-for-byte
  unchanged, single-item PUT and both action endpoints (JSON + www)
  mapped to 503 on contention. 10 meaningful tests including the
  v1-vs-v2 same-final-state test and race-not-clobbered tests.
- See Issue 2 (post-review fix untested) and the Low items on duplicate
  delete indices and doc drift.

### Phase 12: Batched teardown — VERIFIED

- `batch_delete` on protocol and both backends (PynamoDB `batch_write`
  with retry; PostgreSQL single `DELETE ... ANY(%s)`); `clear()`/
  `delete()` on both formats; the `format_ever_changed` sweep-skip gate
  verified sound at every metadata write site; `DbPropertyList.delete()`
  batched.
- 6 unit tests (including a real `UnprocessedItems` retry payload) + 3
  cross-backend integration tests, all meaningful. Two Low wording/docs
  notes.

### Phase 13: Orphan scan — VERIFIED

- `actingweb/maintenance/verify_orphans.py`: all four cases (fail-closed
  exit 2, reserved-prefix, consistent reads everywhere with the
  no-GSI note, report-only with no delete flag), function-local backend
  imports, entry point registered, docs in both target files. Both
  plan-recorded deviations (whole-table checkpoint; deliberate non-reuse
  of `DbActorList.fetch()`) confirmed exactly as described.
- 17 unit tests (all pass) + 1 cross-backend integration test with the
  consistency pin.
- See Issue 8 (checkpoint replay after cleanup) and two Low notes (AST
  guard omits the `set(value=None)` delete idiom; package docstring
  omits the new tool).

### Phase 14: Release — ISSUES FOUND

- Version files match (`3.14.0` in both); CHANGELOG restructured with a
  fresh Unreleased section; migration guide exists and is wired in; the
  full docs sweep verified present; `thoughts/todo/` cleanup verified
  (five rows deleted, register re-ranked, refile added).
- **Issue 1 (High):** the cross-version peer claim in the release notes
  is false — see below.
- Low: the migration guide dropped three plan-required items (v1
  retry-idempotency note, the operation-counter recipe carried from
  v3.13, the orphan-scan IAM/runtime envelope) without the consumer-first
  rewrite recording the drops; CHANGELOG paraphrases where the plan
  asked for exact numbers (drift bound, measured RCU saving) though the
  guide it links to has them.

### Post-Verification Changes (six fixes) — ALL LANDED

All six verified in code; items 1, 2, 4, 5, 6 with their named tests
present and meaningful (103 passed when run directly). Item 3 (bulk
duplicate-index) is correct by hand-traced inspection against the v1
branch but has **zero test coverage** (Issue 2). Item 4's return-value
*contents* are untested (only lengths asserted — a post-update-values
regression would pass). Item 5's stale-cache-then-migration scenario is
untested.

## Issues Found

### 1. Release notes' cross-version peer claim is false
**Severity:** High
**Description:** `CHANGELOG.rst:64-65` and `docs/migration/v3.14.rst:159-161`
state that peers on an older ActingWeb "keep working exactly as before --
no upgrade is required on their side." After commit 3f96742,
`update_where()`/`update_by_handle()` diffs carry `old_item` and **no
`index`** (`interface/property_store.py:446, 482`); a 3.13 receiver's
update branch requires `"index" in data`, so it drops every such diff as
"unknown operation" — the update is not applied at all, not "positionally,
best-effort" as the plan's Phase 14 bullet requires.
`docs/guides/subscriptions.rst:405-406` already states the correct
behavior, so the tree contradicts itself. Root cause: Post-Verification
item 6 recorded these files as "checked, not edited: … now accurate
end-to-end thanks to item 1's fix" — but item 1's fix is receiver-side
only and does nothing for 3.13 receivers. Scope is value-addressed
*update* diffs only (`remove` diffs still carry `item`).
**Location:** `CHANGELOG.rst:64-65`, `docs/migration/v3.14.rst:159-161`
**Recommendation:** Two-sentence wording fix in both files before
tagging: old peers keep working for positional operations and `remove`,
but value-addressed *updates* are not applied on pre-3.14 peers (they
have nothing to match on) — matching what the subscriptions guide
already says. No code change implied.

### 2. Post-review bulk-endpoint fix has zero test coverage
**Severity:** Medium
**Description:** Fix 3 in commit 3f96742 (+73 lines in
`handlers/properties.py`: `final_value_by_index`, `skip_new_indices`,
single-write-per-index Pass 1, per-entry count preservation) ships with
no tests. Neither of the scenarios the PR review named — two updates at
the same append-index; update-then-delete at a newly-appended index —
appears anywhere in the bulk test suites. Hand-tracing confirms
v1/v2 equivalence for the handled cases, but nothing pins it.
**Location:** `actingweb/handlers/properties.py:1243-1312`;
`tests/test_bulk_list_update_handles.py` (unchanged since Phase 11)
**Recommendation:** Add regression tests for: duplicate update index at
the append boundary (later wins, one row), create-then-delete no-op at
both `snapshot_length` and interior new indices, and duplicate
pre-existing index in one batch.

### 3. `None`-valued items still hit the silently-dropped-diff class
**Severity:** Medium (latent)
**Description:** `_register_diff` omits any field whose value is `None`
(`interface/property_store.py:288-295`), and the receiver gates are
membership checks. So `delete_by_handle()` on a `None`-valued row,
`update_by_handle()` where the old or new value is `None`, and
`NotifyingListProperty.remove(None)` all produce diffs the receiver
classifies as "unknown operation" and drops — the exact failure mode
Phase 10 and PR-fix 1 repaired for other values. `None` items are legal
(the v1 bulk path writes `append(None)` as gap padding).
**Location:** `actingweb/interface/property_store.py:288-295`;
`actingweb/remote_storage.py:397, 462`
**Recommendation:** Use an `_UNSET` sentinel instead of `is not None`
in `_register_diff`, or document `None` items as non-replicable.

### 4. Ambiguous value-match is a silent no-write with no signal
**Severity:** Medium
**Description:** The uniqueness-gated match from PR-fix 2 returns
`{"error": "item not found or ambiguous"}` with no log line
(`remote_storage.py:419`), and all five call sites discard the return
value. Two rows sharing a value + `update_where()` (whose diffs now
carry no `index`) → both diffs dropped → the peer replica silently stays
stale forever. The strictness was an explicitly accepted trade in the
plan; the invisibility was not.
**Location:** `actingweb/remote_storage.py:419`; callers in
`interface/subscription_manager.py:1059, 1104, 1922, 1964`,
`handlers/callbacks.py:607`
**Recommendation:** `logger.warning` in the error branch at minimum;
ideally surface apply-failures to the subscription layer so an operator
can trigger a resync.

### 5. Permission-proxy test proves surface, not enforcement
**Severity:** Medium
**Description:** `test_proxy_surface_matches_notifying_list_property`
asserts name-set equality only — a proxy method that delegates without
calling `_check` passes. Denial is tested for 5 of the 17 mutators; the
other 12 (including all four Phase 10/11 additions, `pop`, `insert`,
`extend`, `compact`, `migrate_to_v2`) have no test asserting they
enforce anything. The Phase 10/11 mutators *are* correctly gated — by
hand, not by any guard.
**Location:** `tests/test_authenticated_views.py:479-495`;
`actingweb/interface/authenticated_views.py:264-337`
**Recommendation:** A parametrized test driving every mutator on the
proxy against a read-only context, asserting `PermissionError` and zero
delegation, closes the class.

### 6. The drift bound's third contract term is untested
**Severity:** Medium
**Description:** The advisory count's documented drift bound has three
terms; the third (a failed advisory metadata touch leaves the hint low
by one, repaired by the next rank-counting mutation) has no test
asserting either the drift or the repair. The CAS-exhaustion test
asserts only that the item lands and the warning fires. Since a consumer
enforces quota against this contract, its third term is
contract-without-test.
**Location:** `tests/test_v2_metadata_cas.py:212-239`;
`tests/test_v2_count_hint.py`
**Recommendation:** Extend the advisory-exhaustion test to assert
`count_hint` is low by one, `verify()` reports `count_hint_drift`, and a
subsequent `pop()`/`remove()` restores exactness.

### 7. Append diffs' `index` is now advisory but undocumented as such
**Severity:** Medium
**Description:** Phase 3 removed `append()`'s own `len()`; the diff's
`index` now derives from `get_metadata()["length"]`, which under v2 is
the advisory `count_hint` — so `{"operation": "append", "index": N}` can
carry a wrong `N` under concurrent mutation. The library's own receiver
ignores it (`remote_storage.py:388-390` appends by item), but an
external subscriber trusting it positionally is exposed, and
`docs/guides/subscriptions.rst` documents index-omission rationale only
for `update`/`remove`.
**Location:** `actingweb/interface/property_store.py:273-278`
**Recommendation:** Either drop `index` from append diffs (consistent
with the value-addressed direction) or document it as advisory in the
subscriptions guide and spec.

### 8. Orphan-scan checkpoint replay masquerades as a fresh scan
**Severity:** Medium
**Description:** The checkpoint file is written by default and *kept*
when orphans are found. An operator who deletes the reported rows and
re-runs gets the checkpoint replayed: the original counts are reprinted
and exit is 1 **without scanning a single row** — indistinguishable from
a fresh scan except for one INFO line. The docs show `--checkpoint-file`
in the example but never say to delete it before re-running.
**Location:** `actingweb/maintenance/verify_orphans.py:346-349, 380,
413-425`; `docs/reference/actor-deletion.rst:245-247`
**Recommendation:** On a run where every table is already checkpointed,
refuse to reprint stale results (or clearly label the summary as
replayed and exit distinctly); document deleting the checkpoint after
cleanup.

### Low-severity items (roll-up)

- `ruff format` drift: 19 files under the pinned formatter; plan's
  explanation ("environment ruff version difference") is incorrect.
- `update_where()`/`remove_where()` return-value *contents* untested
  (only lengths asserted); v1 branches re-read values after the scan
  (`property_list.py:2445, 2493`), reintroducing at v1 the drift class
  fix 4 closed at v2 — capture during `enumerate` instead.
- `_v2_items_with_handles()` stale-cache-then-migration scenario
  untested (the exact scenario the fix exists for).
- Duplicate *delete* index in one bulk batch diverges v1 (two rows gone)
  vs v2 (one row gone; arguably correct) — untested, undocumented, and
  contradicts the plan's identical-output claim; duplicate deletes of a
  batch-created index also double-count `items_deleted`.
- Bulk docs (`property-lists.rst:556-561`) don't distinguish
  pre-existing vs batch-created indices for same-index update+delete,
  and don't document later-duplicate-wins.
- `old_item` cannot express a genuine `null` previous value
  (`remote_storage.py:400` sentinel doubles as "absent").
- Cold-start test doesn't pin the aggregate model count; consistent-read
  AST guard catches only literal `False` and globs non-recursively;
  orphan-scan AST guard omits the `set(value=None)` delete idiom.
- `pop()`/`remove()` gate on `write` vs `remove_where()` on `delete` —
  documented plan deviation, but inconsistent and absent from the
  authenticated-views docs.
- Missing plan-named tests: peer-replica integration for Phase 10
  diffs; `PropertyListItemsHandler` out-of-range → 400; REST `/items`
  POST 201-body `index`; cross-backend interleaved-append integration
  (9B); www append-path logging cost pin.
- Migration guide dropped three plan-required items (v1
  retry-idempotency note, operation-counter recipe, orphan-scan IAM
  envelope) without recording the drops.
- `docs/guides/property-lists.rst:437` "Both return the number of items
  actually affected" is now layer-dependent; `maintenance/__init__.py`
  docstring omits `actingweb-verify-orphans`; `batch_delete` docstring
  lacks the plan-required capacity note; `www.py` HTML UI has no
  contention handler (docs name only the three JSON handlers).

## Remaining Tasks

- [ ] Fix Issue 1 (CHANGELOG + migration-guide cross-version wording)
      **before tagging v3.14.0** — two files, no code change.
- [ ] Add bulk duplicate-index regression tests (Issue 2).
- [ ] Decide on the `None`-value diff gap (Issue 3): sentinel fix or
      documented limitation.
- [ ] Add a warning log to the ambiguous-match drop path (Issue 4).
- [ ] Parametrized enforcement test over all proxy mutators (Issue 5).
- [ ] Test the third drift term (Issue 6).
- [ ] Decide append-diff `index` policy and document it (Issue 7).
- [ ] Harden orphan-scan checkpoint replay UX (Issue 8).
- [ ] Low roll-up items as time permits; resolve the four PR #134 review
      threads on GitHub (code-actioned, threads still open).

Non-blocking remainder filed in
`thoughts/todo/v2-list-access-verification-followups.md`.

## Overall Assessment

The implementation is complete and of unusually high fidelity to the
plan: all 14 phases landed as specified, every deviation the plan
records was confirmed accurate in code, the two independent security/
correctness fixes (Phase 2's permission bypass, Phase 10's dropped
`remove()` notification) are real and pinned, and all six post-PR-review
fixes from PR #134 are in place — every review comment on the PR has
been actioned in code. Automated checks are clean (ruff check, pyright,
3034 tests, green CI on both backends). Test quality is generally
strong — exact query-count assertions against real backends, both sides
of the CAS carve-out boundary pinned, a real UnprocessedItems retry
payload.

One thing must change before the tag: the release notes' claim that
older peers "keep working exactly as before" is false for value-addressed
updates (Issue 1) — a 3.13 peer silently drops every
`update_where()`/`update_by_handle()` diff, and the same tree's
subscriptions guide already says so. It is a two-sentence docs fix. The
remaining medium items are test-coverage and observability debt around
the newest code (the post-review bulk fix shipped untested; ambiguous
value-matches fail invisibly; the permission proxy's enforcement is
hand-verified rather than test-guarded) — none block the release, but
Issues 2–4 are worth closing while the context is fresh.
