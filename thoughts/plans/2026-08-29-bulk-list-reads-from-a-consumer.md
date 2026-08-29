---
status: done
verified: thoughts/verifications/2026-08-29-bulk-list-reads-from-a-consumer.md
---

# Implementation Plan: scoped bulk list reads, and the attribute-bucket cache

**Date:** 2026-08-29
**Research:** `thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md`
**Todo:** `thoughts/todo/scoped-bulk-list-reads.md` (INDEX row 22)
**Branch:** `docs/scoped-bulk-list-reads`

## Overview

Give the library a way to read one namespace of an actor's list properties
instead of the whole partition, and convert the callers that were paying a
whole-partition dump to read a single list. Separately, make a fully-loaded
attribute bucket authoritative — and fix the DynamoDB bucket over-match that
would otherwise turn "authoritative" into "wrong".

Two of the seven phases are not about read cost at all. Phase 1 is a
data-destruction fix that the security review surfaced while checking Phase 6's
preconditions; Phase 2 removes a path where a transient read fault empties a
list. Both are independent of everything else and go first.

## Decisions Made

- **Scope is a list-name PREFIX, not exact names** — forced by the measurement.
  The consumer's list names are created at runtime, so `memory_*` is N lists
  sharing a prefix. Exact-name scoping delivers none of the measured saving and
  cannot discover the names it would need. Research §6 C2.
- **A new method, `list_prefix_with_rows(prefix)`, one prefix per call** —
  `list_all_with_rows()`'s "the actor's WHOLE partition" contract stays
  literally true, and every existing caller's assumption is untouched.
  Research §7 D1/D7.
- **A new `get_prefix()` on `DbPropertyProtocol`**, not a computed `get_range`
  bound. DynamoDB's `begins_with` is exact for any UTF-8 prefix; no synthesised
  upper bound is. Research §7 D2, §6 C5.
- **Concurrency is the caller's** — the library stays synchronous, one query per
  call. The measured 1,224 ms → 700 ms needs the reads issued concurrently, and
  the consumer already has three independent endpoints to do it from.
  Research §7 D3.
- **`list_prefix_with_rows()` pins `consistent_read=False`**; the three
  converted internal callers pass `consistent_read=True` and do **not** route
  through it. At `get_range`'s default the five families cost ~1,370 RCU against
  the 1,361 dump they replace, so the public path must be eventual to pay at
  all; but once a read is scoped to one list, strong consistency costs ~6–13 RCU
  more, which is ~1% of what scoping already saved and buys a correctness
  guarantee two destructive rewrites currently lack. Research §6 C3; scalability
  review S1.
- **The permission-filtered variant prunes whole lists from both `names` and
  `rows`**, using a row-attribution helper that lives in `property.py` — the
  encoding owner — never in `interface/`. Research §7 D4; architecture and
  security reviews.
- **No REST change.** `handlers/properties.py:471`'s `listall()` keeps its
  contract; this is a library-API release. Research §7 D4.
- **`set_attr()` mirrors the backends' falsy delete** rather than documenting the
  divergence, because Phase 6 makes the loaded dict authoritative and a dict that
  is knowingly wrong about presence cannot be authoritative about absence.
  Research §7 D6.
- **All seven phases land as a single PR, released as 3.14.3** — so that PR *is*
  the release PR, and CLAUDE.md's rule applies to it directly: the version bump
  and the "Unreleased" rename ride in it, and the tag goes on the merge commit
  after CI is green on **both** database backends. Each phase stays its own commit
  inside that PR, and each remains independently testable, so a phase that fails
  late can be dropped without unpicking the others. If any phase has to be
  dropped, the drop happens **before** the version bump commit, not after.
- **Empty prefix raises `ValueError`**, and `list_prefix_with_rows()` propagates
  `DbError` rather than swallowing to `([], {})`. For a scoped read an empty
  result is the common answer, so the existing swallow idiom would render a
  throttled query as "you have no memories". Usability review.

## What We're NOT Doing

- **No names-only sibling** (`list_prefix()`). A keys-only projection saves no
  DynamoDB capacity (`db/protocols.py:217-224`; measured 1,361.0 either way), so
  it would break the `list_all`/`list_all_with_rows` pairing for nothing. The new
  method's docstring says so, otherwise the asymmetry looks like an oversight.
- **No cheap global name discovery.** `-meta` rows interleave with item rows in
  key space, so no range or prefix read selects only them. `list_all()` stays a
  whole-partition dump. A registry row is a key-layout question and belongs to
  `thoughts/todo/prop-list-key-prefix-scheme.md`.
- **No change to `list_all()` / `list_all_with_rows()` behaviour**, including
  their swallow-to-empty error handling. The asymmetry with the new method is
  deliberate and gets stated in both docstrings.
- **No list-name validation.** The security review established that a
  caller-supplied prefix cannot escape the `list:` namespace, because
  `f"list:{prefix}"` puts the literal first and neither primitive is a pattern
  language. Saying this explicitly so nobody adds a validator that gives false
  assurance.
- **No migration page.** `docs/migration/` is minors-only
  (`docs/migration/index.rst:19-28`); patch-level behaviour changes go to
  CHANGELOG in the established `**Behavior change**:` style.
- **Not fixing `_glob_to_regex`'s `$`-vs-`\Z` and `.`-vs-`DOTALL` gaps**
  (`permission_evaluator.py:604-645`). Equally broken in the single-list path
  today; Phase 5 makes them newly *reachable* (names now arrive from storage
  rather than from the caller), so it is noted in that phase and filed to
  `thoughts/todo/` rather than fixed here.
- **No thread pool, no async variant.**

---

## Phase 1: DynamoDB attribute buckets stop matching by bare prefix

Independent of everything else in this plan. It is here first because it is a
data-destruction bug reachable with remote-party-chosen input, and because
Phase 6 cannot ship without it.

`Attribute.bucket_name` is `bucket + ":" + name`, but two methods match on
`startswith(bucket)` — no delimiter. So a bucket whose name is a prefix of
another's sees the other's rows, and in one case deletes them.
`RemotePeerStore.delete_all()` (`remote_storage.py:283-290`) calls
`delete_bucket()` on `remote:{peer_id}`, and 15 library call sites construct that
bucket with `validate_peer_id=False` — including the inbound peer-callback path —
so peer ids there are remote-party-chosen strings and prefix relationships are
reachable. On DynamoDB, ending trust with peer `abc` can delete peer `abcd`'s
entire dataset. PostgreSQL is exact on both paths and unaffected.

The codebase has already decided this question twice, in the same file and one
over: `delete_by_chain` guards with `if t.bucket == bucket`
(`db/dynamodb/attribute.py:358`), and
`db/dynamodb/subscription_suspension.py:76-80` carries the same guard with a
comment naming the hazard. These two methods are the ones that were missed.

A delimiter alone is not sufficient. Bucket names contain `:` (`remote:{peer_id}`)
*and* attribute names contain `:` (`list:{name}:{index}` in `attribute_list.py`,
`"{actor_id}:{peer_id}"` in `peer_capabilities.py:473`), so the composite key is
inherently ambiguous — bucket `remote:abc`/name `x` and bucket `remote`/name
`abc:x` produce an identical `bucket_name`. Narrow the Query *and* compare
exactly, which is what `delete_by_chain` already does.

### Changes

- `actingweb/db/dynamodb/attribute.py:60-71` — `get_bucket()`: query
  `startswith(bucket + ":")`, and skip any row where `t.bucket != bucket`.
- `actingweb/db/dynamodb/attribute.py:290-302` — `delete_bucket()`: the same two
  changes before `t.delete()`.
- Add a comment on both pointing at `delete_by_chain`'s guard, so the fourth
  instance of this pattern is written correctly.

### New Tests

- Unit (DynamoDB, mocked): `get_bucket("b")` does not return rows of bucket
  `"bb"`; `delete_bucket("b")` does not delete them. Both fail today.
- Unit: a bucket named `remote:abc` and one named `remote:abcd`, each with an
  attribute named `x` — `get_bucket("remote:abc")` returns exactly one `x`, and
  its value is `remote:abc`'s.
- Unit: the ambiguous-composite case — bucket `remote:abc` / name `x` versus
  bucket `remote` / name `abc:x`. Pins that the exact `t.bucket` compare, not
  just the delimiter, is what separates them.
- Integration (both backends): the same three cases, asserting DynamoDB and
  PostgreSQL now agree. PostgreSQL passes unchanged; that is the point.
- Regression: `RemotePeerStore.delete_all()` for one peer leaves a
  prefix-sibling peer's data intact.

### Verification

- [x] `poetry run pytest tests/test_attribute.py tests/integration/test_db_attribute_buckets.py -v` passes
- [x] `poetry run pytest tests/ -k "remote_storage or attribute" -v` passes (173 passed)
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Both backends: the new integration file passes on DynamoDB and on
  PostgreSQL
- [x] Manual: confirmed no library-constant bucket name is a prefix of another.
  Swept 33 bucket-name literals across `actingweb/` (every `*BUCKET* = "..."` /
  `bucket = "..."` binding) plus the dynamic `remote:` family; no pair has a
  prefix relationship. Holds today by luck; the fix is what makes it not matter

### Implementation Status: Complete

**Deviations and learnings:**

- **The tests went to new homes.** The plan named
  `tests/integration/test_attributes.py`, which is an HTTP request-flow file
  with no direct DB access. The DB-level both-backends cases went to a new
  `tests/integration/test_db_attribute_buckets.py`, modelled on
  `test_db_property_range.py` (the same `aw_app`/`config`/`actor_id` fixture
  shape, so PostgreSQL gets the migrated schema). The mocked-DynamoDB unit
  cases went into `tests/test_attribute.py` as
  `TestDbAttributeBucketIsolation`; all seven fail without the fix.
- **The "ambiguous composite key" case is a primary-key COLLISION, not two
  coexisting rows.** The plan's test asked for bucket `remote:abc`/name `x`
  *and* bucket `remote`/name `abc:x` to be stored simultaneously and told
  apart. They cannot be: both backends key on `(id, bucket_name)` and both
  pairs produce `remote:abc:x`, so they are the same row and the second write
  overwrites the first. That makes the exact-`bucket` compare *more* necessary,
  not less — the delimiter cannot arbitrate ownership of a row only one bucket
  can own — but the test had to be rewritten around storable data: a single
  row written by one bucket must be invisible and undeletable to the other.
- **A cross-backend divergence surfaced underneath it**, orthogonal to this
  phase: on that colliding key DynamoDB's `save()` is a PutItem and reattributes
  the row to the last writer, while PostgreSQL's `ON CONFLICT DO UPDATE`
  refreshes only `data`/`timestamp` and keeps the first writer's `bucket`. The
  test asserts only what both agree on — the row answers to exactly one bucket,
  never both — and the divergence is filed to
  `thoughts/todo/attribute-upsert-bucket-drift.md`.
- **`delete_by_chain()` was left alone** (its bare `begins_with` over-fetches
  but its exact compare is already correct); widening the diff would only
  muddy Phase 5's `/security-review`.

---

## Phase 2: the three v1 list methods stop dumping the partition

Also independent — it uses the **already-shipped** `get_range` and the
already-shipped `_v1_bounds()` helper, so it does not wait for Phase 3.

`verify()`, `compact()` and `migrate_to_v2()` each call
`fetch_all_including_lists()` and then index the result by exact v1 row name.
The v2 counterparts do not: `_v2_verify()` goes through `_v2_load_full()`, a
scoped `get_range`. `_v1_item_names_in_range()`'s own docstring
(`property_list.py:1687-1694`) already makes the argument — *"Deliberately a
`get_range()` and not a `fetch_all_including_lists()` partition dump: the bulk
migration script avoids those precisely because they cost roughly one dump per
list on a typical actor"* — so these three are the callers that were left behind.

**Do not use a name prefix here.** `f"list:{name}"` for list `output` matches
`list:output_embeddings_*` — 403 rows, 5.23 MB, 678 RCU on the measured account.
Use `_v1_bounds()`, which spans `list:{name}-0` … `list:{name}-:` and excludes
both `-meta` (`m`, 0x6D) and every v2 row (`#`, 0x23).

**Pass `consistent_read=True`.** Today these read eventually
(`Property.query()`'s PynamoDB default), and two of them rewrite destructively
from what they read: `compact()` writes survivors to `0..n-1` then deletes
`len(ordered_values)..highest_seen` (`:3033-3041`), and `migrate_to_v2()` deletes
v1 rows `0..highest_seen` at `:3296-3305`. A row missed by a stale replica read
is overwritten by its successor and its slot deleted — silently, after which
`verify()` reports `healthy: true`. Strong consistency on a one-list read costs
~6–13 RCU more, roughly 1% of what the scoping itself saves.
`property_list.py:526-532` already states the rule for the v2 twins of these two
methods; this makes v1 agree. `migrate_to_v2():3188-3197` already spends a
strongly-consistent point read as a "re-check before the first destructive
write" — this closes the wider window one line above it.

**Drop the `or {}`.** All three lines end in it, and PostgreSQL's
`fetch_all_including_lists` returns `None` on a caught exception
(`db/postgresql/property.py:832-834`). So today a transient read fault makes
`verify()` report every index missing, `compact()` compute `ordered_values = []`,
delete rows `0..stored_length-1` and write `length: 0` — a read fault empties the
list. `get_range` raises `DbError` instead. This is the strongest argument for
the phase and the easiest thing to lose in the edit.

Correctness is unchanged, including orphan detection: `orphan_indices` is drawn
from `present`, which is already filtered by `^list:{name}-(\d+)$`
(`:2745-2753`), so no orphan shape exists outside the prefix. `stored_length`
comes from `_load_metadata()`, not from `rows`. The sibling hazard `_v1_bounds()`
documents is identical to today's, where the whole-partition dump also contains
`list:foo-5-0`.

These call `get_property(self.config).get_range(...)` directly.
`property_list.py` cannot import `PropertyListStore` — `property.py:5` imports
`ListProperty` from it — and `get_property` is already imported at
`property_list.py:21`. The three sites construct `get_property_list(...)` and
discard it immediately, so nothing depends on its `handle`/`actor_id` side
effects.

### Changes

- `actingweb/property_list.py:2742-2743` — `verify()` (v1 path): `get_range` over
  `_v1_bounds()`, `consistent_read=True`, no `or {}`.
- `actingweb/property_list.py:3012-3013` — `compact()`: the same.
- `actingweb/property_list.py:3179-3180` — `migrate_to_v2()`: the same.
- Docstring note on each explaining why this one is strongly consistent while
  `list_prefix_with_rows()` is not.
- `actingweb/property_list.py:3367`, `:3381` — `_maybe_lazy_migrate()` needs no
  edit but gains the benefit: it calls `verify()` then `migrate_to_v2()` (which
  calls `verify()` again) inside a user's `append()`/`insert()`, so three
  whole-partition dumps in one request become three one-list reads. Off by
  default (`ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH`), but it is the only
  user-facing beneficiary and the phase's tests must cover it.

### New Tests

- Unit: a `CountingPropertyDb` spy asserting `verify()` / `compact()` /
  `migrate_to_v2()` issue **zero** `fetch_all_including_lists()` calls and
  exactly one `get_range` each.
- Unit: each of the three passes `consistent_read=True` — in the style of
  `tests/test_v2_consistent_read.py:32`, `:205-208`. An AST guard mirroring
  `:143-179` (which forbids non-`True` under `handlers/`) forbidding
  `consistent_read=False` at these three call sites.
- Unit: a backend fault during `compact()`'s read raises `DbError` and leaves the
  list untouched. **Fails today** — today it empties the list.
- Unit: `verify()` reports the same `missing_indices` / `orphan_indices` /
  `adjacent_duplicates` from a scoped read as from a full dump, including an
  orphan above `stored_length`.
- Unit: a sibling list named `{name}-5` does not perturb `{name}`'s report.
- Unit: `_maybe_lazy_migrate()` with lazy migration enabled issues three
  one-list reads, not three partition dumps.
- Integration (both backends): `compact()` on a damaged v1 list produces the same
  result as before the change.

### Verification

- [x] `poetry run pytest tests/test_property_list_integrity.py tests/test_v2_consistent_read.py -v` passes
- [x] `poetry run pytest tests/test_v1_maintenance_scoped_reads.py -v` passes (18 new tests)
- [x] `poetry run pytest tests/integration/test_property_list_migration.py -v` passes on both backends
- [x] `poetry run pytest tests/integration/test_verify_property_lists_script.py -v` passes on both backends
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Whole suite green: 2,278 unit + 888 integration, DynamoDB; the touched
  integration files also green on PostgreSQL

### Implementation Status: Complete

**Deviations and learnings:**

- **The plan's correctness argument had a hole: `foreign_format_rows`.** v1
  `verify()` also counts v2-shaped residue rows, and it counted them out of the
  partition dump. Those rows sort at `#` (0x23), **below** `_v1_bounds()`'s
  lower bound `list:{name}-0` (0x30), so the scoped read cannot see them — four
  existing tests caught it immediately. It now costs one extra keys-only
  `get_range` via the already-existing `_v2_item_names_in_range()`, which is the
  exact mirror of what `_v2_verify()` already spends on
  `len(self._v1_item_names_in_range())`. So verify() issues two scoped reads,
  not one, and the plan's "exactly one `get_range` each" test was written as
  "every `get_range` is scoped to this list's own rows" instead.
- **`get_property_list` is no longer imported by `property_list.py` at all** —
  these three were its only callers there. That removed the import, which broke
  27 monkeypatches of `actingweb.property_list.get_property_list` in
  `test_property_list_integrity.py`. Deleting them is a strengthening, not a
  concession: those tests now exercise the real scoped read through
  `FakePropertyDb.get_range` rather than a hand-fed partition dict. Two AST
  guards pin it (no `fetch_all_including_lists` call anywhere in the module, and
  the name is not imported).
- **The data-loss claim was demonstrated, not assumed.** Against the pre-fix
  code, with `fetch_all_including_lists` returning `None` (PostgreSQL's
  caught-exception return), `compact()` on a healthy 3-item list deleted all 3
  item rows and wrote `length: 0`, reporting `missing_indices: [0, 1, 2]`.
- **A `CountingPropertyDb` spy asserting zero `fetch_all_including_lists()`
  calls would now be vacuous** — the module cannot reach that method any more.
  The AST guards replace it and cover paths no test triggers.

---

## Phase 3: `get_prefix()` on the property protocol

### Changes

- `actingweb/db/protocols.py` — add `get_prefix(actor_id, prefix, keys_only=False,
  consistent_read=True)` to `DbPropertyProtocol`, next to `get_range` (`:185`).
  It belongs here, not on `DbPropertyListProtocol`: every scoped multi-row read
  already lives on `DbProperty` (`get_range`, `get_last_in_range`,
  `batch_delete`), all touch no instance state, and `property_list.py` already
  consumes them via `get_property(config)`. Carry `get_range`'s docstring
  paragraphs verbatim in spirit — the `keys_only` "no capacity saving on
  DynamoDB" note (`:217-224`), the `consistent_read` RCU arithmetic (`:225-236`),
  and the "ordering is NOT guaranteed" clause (`:204-210`). Document
  `Raises: DbError`.
- `actingweb/db/dynamodb/property.py` — implement with
  `Property.name.startswith(prefix)` (native `begins_with`). Exact for arbitrary
  UTF-8 prefixes: String sort keys are ordered by UTF-8 bytes and UTF-8 is
  prefix-preserving. Note in the docstring that `begins_with` performs no Unicode
  normalization, so NFD and NFC prefixes do not match each other.
- `actingweb/db/postgresql/property.py` — implement with
  `WHERE id = %s AND starts_with(name, %s)`, bound parameters. **Not** a
  `COLLATE "C"` bound pair: a prefix read has no exact inclusive upper bound, and
  the same argument that rejects `list:~` rejects any synthesised sentinel here.
  `starts_with` is PG 11+; the project floor is 12+
  (`docs/contributing/backend-testing.rst:13`). No `LIKE`, so no `%`/`_`/escape
  surface — worth a docstring line, since every family prefix in the measurement
  contains `_`.

  **Verified on a live PostgreSQL 16.11**, because the whole reason for moving
  off `COLLATE "C"` bounds is that collation-aware comparison disagrees with byte
  order, and `starts_with` had to be shown not to inherit that. Running the same
  cases under the database's libc collation and under `en-US-x-icu`:

  | expression | libc `en_US.utf8` | ICU `en-US-x-icu` |
  | --- | --- | --- |
  | `'a' < '{'` | `true` | **`false`** |
  | `'a-a' < 'a+a'` | `false` | **`true`** |
  | `starts_with('list:a-b', 'list:a-')` | `true` | `true` |
  | `starts_with('list:aXb', 'list:a-')` | `false` | `false` |
  | `starts_with(U&'cafe\0301x', 'café')` | `false` | `false` |

  Ordering flips between the two collations — that is C4's hazard, demonstrated,
  and it is why no bound pair can be trusted. `starts_with` is identical under
  both: byte-exact, punctuation not folded, no Unicode normalization. That last
  row matters twice over — it is also what makes PostgreSQL agree with DynamoDB's
  `begins_with`, which normalizes nothing either.

  Two further results to encode: `starts_with('list:memoryXa', 'list:memory_')`
  is `false`, so `_` is literal and there is genuinely no wildcard surface; and
  `starts_with(x, '')` is `true` on PostgreSQL while DynamoDB's `begins_with("")`
  raises `ValidationException` — a real cross-backend divergence that the
  `if not prefix` guard below is what covers.
- Guard `if not prefix` (falsy, not just `None`) and return `{}`:
  `begins_with(name, "")` is a DynamoDB `ValidationException`.

Failure direction matters and goes in the docstring: an inexact prefix bound
*under*-reads, so it cannot leak — it silently truncates, and truncating a v2
list's item rows while keeping its `-meta` row produces `[]` from
`to_list_from_rows()` with no fallback.

### New Tests

- Integration (both backends), in `tests/integration/test_db_property_range.py`:
  a prefix read returns exactly the rows under it and nothing else.
- Integration: **non-ASCII prefix and non-ASCII row names** — the case that fails
  under a `~`-style sentinel. Mirrors
  `tests/test_v2_cost_plain_property_partition.py:82-97`'s `"étag"` list.
- Integration: adversarial names — `list:foo-#…`, `list:foo-$…`, a name
  containing `%` and one containing `_`, a name that is a prefix of another.
  Asserts both backends return byte-identical key sets.
- Integration: empty prefix returns `{}` on both backends and raises nothing.
- Unit: `consistent_read` and `keys_only` are forwarded to the backend call.
- Unit: a backend fault raises `DbError` on both backends.

### Verification

- [x] `poetry run pytest tests/integration/test_db_property_range.py -v` passes on DynamoDB (25)
- [x] `DATABASE_BACKEND=postgresql … poetry run pytest tests/integration/test_db_property_range.py -v` passes (25)
- [x] `poetry run pytest tests/test_db_property_get_prefix.py -v` passes (11 new)
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Whole suite green: 2,289 unit, 897 integration

### Implementation Status: Complete

**Deviations and learnings:**

- **`get_prefix` mirrors `get_range`'s implementation exactly**, checked rather
  than assumed. On DynamoDB that means the `for item in Property.query(...)`
  loop sits INSIDE the `try`, so PynamoDB's lazy `ResultIterator` — which fires
  the HTTP request during iteration and pages transparently at 1 MB — cannot
  raise past the `DbError` wrapper. (`DbAttribute.get_bucket()` has the opposite
  shape; see Phase 6's note.) On PostgreSQL it means one `execute` + `fetchall`
  under the same `get_connection()` idiom.
- **The non-ASCII test is the one that would have caught a sentinel bound.**
  `é` (U+00E9) encodes above `~` (0x7E), so `list:étag~` as a synthesised upper
  bound would exclude rows a prefix read must return. Both backends return the
  same three rows.
- **A Unicode-normalization test was added beyond the plan's list.** It pins
  that an NFD prefix does not match an NFC name on *either* backend — the
  property that makes `starts_with()` and `begins_with` agree, and the one a
  future switch to a collation-aware comparison would silently break.
- **The `_`/`%` test earns its place**: it fails loudly if anyone rewrites the
  PostgreSQL side as `LIKE prefix || '%'`, which is the obvious-looking
  refactor and would turn every family prefix (all of which contain `_`) into
  a wildcard pattern.

---

## Phase 4: `list_prefix_with_rows()` and the row-attribution helper

### Changes

- `actingweb/property.py` — add `PropertyListStore.list_prefix_with_rows(prefix: str)`
  returning `(names, rows)`, reaching `get_property(self._config).get_prefix(...)`
  with `f"list:{prefix}"` and **`consistent_read=False`**, matching today's
  whole-partition read exactly. Raises `ValueError` on an empty prefix, in the
  "wrong door, here's the right one" style of `property.py:113-126`; propagates
  `DbError`. Reaching `DbProperty` from this class has precedent — `exists()`
  (`:20-29`) already does.
- `actingweb/property.py` — add a module-level `rows_for(names, rows)` helper
  that returns only the rows attributable to the given list names, using the
  encoding this module owns: the `-meta` name, `_V1_INDEX_RE`, and the v2 rank
  prefix plus `_v2_is_rank`. A bare `startswith(f"list:{name}-")` is wrong — it
  also claims sibling `{name}-old`'s rows. Phase 5 is its only caller; it lives
  here because `interface/` must not parse row names.
- `actingweb/interface/property_store.py:543` — mirror the new method on the
  interface wrapper.
- Docstrings: the prefix contract (*"every list whose name begins with it —
  including a list named exactly `prefix`, and siblings such as `{prefix}-old`.
  If you mean a namespace, pass the delimiter: `"memory_"`, not `"memory"`"*);
  that `names` is scoped too, necessarily, so `(names, rows)` stays internally
  consistent; the cross-family skew note; that there is deliberately no
  names-only sibling; and the error-handling asymmetry with
  `list_all_with_rows()`.
- `actingweb/property.py:54-71` and `interface/property_store.py:543-552` — add a
  pointer from `list_all_with_rows()` carrying the *cost contrast*, including
  that several scoped reads covering everything cost slightly more than one dump.

### New Tests

- Unit: the storage prefix is `f"list:{prefix}"` and `consistent_read=False` is
  passed. This is the acceptance gate for research §6 C3 — without it the
  doubling trap ships green.
- Unit: `(names, rows)` are consistent — every name in `names` has its `-meta`
  row and all its item rows in `rows`; no row in `rows` belongs to a list not in
  `names`. The A6 invariant.
- Unit: prefix `"memory"` returns `memory`, `memory_a` and `memory-old`; prefix
  `"memory_"` returns only `memory_a`. Pins the documented semantics.
- Unit: `""` raises `ValueError`; the message names `list_all_with_rows()`.
- Unit: a `DbError` from `get_prefix` propagates and is **not** swallowed to
  `([], {})`.
- Unit: `rows_for()` with lists `foo` and `foo-old` present — asking for `foo`
  returns none of `foo-old`'s rows, in both v1 and v2 formats.
- Unit: `list_all()` / `list_all_with_rows()` are byte-identical to before —
  same query count, same `consistent_read`, same swallow-to-empty on error.
- Integration (both backends): end-to-end against real storage, including a
  non-ASCII list name.

### Verification

- [x] `poetry run pytest tests/test_v2_cost_library_callers.py tests/test_hot_path_n_plus_one.py -v` passes (21)
- [x] `poetry run pytest tests/test_list_prefix_with_rows.py -v` passes (20 new)
- [x] `poetry run pytest tests/integration/test_property_lists_advanced.py -v` passes on both backends (25 each)
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Whole suite green: 2,309 unit, 904 integration

### Implementation Status: Complete

**Deviations and learnings:**

- **`consistent_read=False` really does match today's dump**, checked rather
  than assumed: DynamoDB's `fetch_all_including_lists()` calls
  `Property.query(actor_id)` with no `consistent_read` argument, and PynamoDB's
  `Model.query` defaults it to `False`. So the plan's "matching today's
  whole-partition read exactly" is literally true, and this is not a
  consistency downgrade dressed as parity.
- **The A6 invariant only holds in one direction, and that is now a documented
  contract rather than a silent choice.** `names` is derived from `-meta` rows,
  so a damaged list whose meta row was lost contributes rows attributed to no
  name — "no row in `rows` belongs to a list not in `names`" is therefore
  unsatisfiable without pruning those rows. Pruning was rejected: it would
  silently discard recoverable data, and it would diverge from
  `list_all_with_rows()`, which returns them today. A test asserts both methods
  behave identically here, so the choice reads as chosen.
- **`rows_for()` sorts its candidate prefixes longest-first.** For lists `foo`
  and `foo-5`, row `list:foo-5-0` must be tried against `foo-5` (suffix `0`,
  passes `_V1_INDEX_RE`) before `foo` (suffix `5-0`, fails it). Short-first
  happens to give the same answer, but only because the shape check rejects —
  ordering makes it correct by construction rather than by luck.
- **`rows_for()` also handles the legacy `#`-named sibling**, which the plan did
  not call out: a pre-ban list named `foo-#bar` stores `list:foo-#bar-0`, inside
  v2 list `foo`'s item prefix. `_v2_is_rank()` rejects it because `-` is not in
  the base62 alphabet — the same guard every reader in `property_list.py`
  applies. Given its own test.

---

## Phase 5: the authenticated store gets real bulk readers

`AuthenticatedPropertyListStore` defines only `__init__`, `_check_permission`,
`__getattr__`, `exists`, `delete`. So `authed.property_lists.list_all_with_rows()`
falls through `__getattr__`, permission-checks the *method name* as a list name —
which passes, since an unmatched target returns `NOT_FOUND` and only `DENIED`
raises — and returns a `_PermissionEnforcingListView` wrapping a bound method,
which raises `TypeError` on call. That is verbatim the bug this class documents
about its own removed `create()` and its fixed `delete()` (`:419-435`).

**The fix shape is itself the hazard.** Repairing `__getattr__` as "if the name
resolves to a method on `self._store`, return it" would hand a permission-scoped
accessor the *unauthenticated* store's bound `list_all_with_rows()` — a full
unfiltered partition dump. That converts a `TypeError` into a read bypass.

### Changes

- `actingweb/interface/authenticated_views.py` — define `list_all()`,
  `list_all_with_rows()` and `list_prefix_with_rows()` explicitly on
  `AuthenticatedPropertyListStore`. All three, not just the new one: shipping only
  the scoped variant leaves the documented API a latent `TypeError`.
- `__getattr__` (`:397-409`) — raise `AttributeError` for any name that collides
  with a `PropertyListStore` method name, rather than falling through to either
  interpretation. Accept and document the consequence, already true for
  `exists`/`delete`: a user list actually named `list_all` is unreachable through
  the authenticated view.
- Filtering: one `evaluate_bulk_property_access()` call
  (`permission_evaluator.py:145-224`), keeping `result in (ALLOWED, NOT_FOUND)` —
  matching both `_check_permission` (`:381`, denies only on `DENIED`) and
  `handlers/properties.py:566-569`. Prune **whole lists** from `names`, then call
  `property.rows_for(permitted_names, rows)` for the rows. Never a bare
  `startswith` prune, which would strip a permitted sibling's rows and land in the
  silent-`[]` case.
- On evaluator or system error: drop everything and return empty, following
  `handlers/properties.py:572-575` ("On error, exclude all list properties for
  security"). Document that an empty result is then indistinguishable from "no
  lists in that namespace" — the same trade `exists()` makes deliberately at
  `:411-417`.
- Never surface a denied list name in an exception or a caller-visible message.
  `_check_permission`'s messages embed the name (`:382-384`, `:393-395`), which is
  safe in the single-list path because the name came from the caller; in the bulk
  path it came from storage, so raising or logging it tells an accessor a list
  exists that they are not permitted to know about.
- Note in the module docstring that `evaluate_bulk_property_access` logs every
  denied name at WARNING per call (`permission_evaluator.py:209-216`) — owner-side
  log volume, not disclosure, but worth knowing before it lands on a hot path.

### New Tests

- Unit: `authed.list_all_with_rows()` is callable and returns data. **Fails
  today** with `TypeError`.
- Unit: `getattr(authed, "list_all")` never returns anything derived from
  `getattr(self._store, ...)` unwrapped; a method-name collision raises
  `AttributeError`. This is the bypass guard — assert it directly.
- Unit: a denied list appears in neither `names` nor `rows`.
- Unit: lists `foo` (denied) and `foo-old` (allowed) — `foo-old` keeps **all** its
  rows, in both v1 and v2 formats, and `to_list_from_rows()` returns its real
  contents rather than `[]`. This is the test that fails under a bare
  `startswith` prune.
- Unit: `NOT_FOUND` is treated as allowed, and bulk filtering agrees list-for-list
  with N individual `getattr()` reads.
- Unit: an evaluator exception yields an empty result, not a partial one, and
  raises nothing.
- Unit: no denied list name appears in any raised message or any log record
  emitted by the new code path.
- Regression: `tests/test_authenticated_views.py`'s `_PROXY_READS` /
  `public_surface` assertions still pass — they are scoped to
  `_PermissionEnforcingListView`, which this phase does not touch.

### Verification

- [x] `poetry run pytest tests/test_authenticated_views.py -v` passes (54, unchanged)
- [x] `poetry run pytest tests/test_authenticated_bulk_list_reads.py -v` passes (24 new)
- [x] `poetry run pytest tests/ -k "permission" -v` passes (219)
- [x] `poetry run pytest tests/integration/test_property_lists_advanced.py -v` passes on both backends (28 each)
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Whole suite green: 2,333 unit, 907 integration
- [x] `/security-review` on the branch diff

### Implementation Status: Complete

**Deviations and learnings:**

- **The bug was reproduced before it was fixed.** Against the pre-phase code,
  `authed.list_all_with_rows` resolved to a `_PermissionEnforcingListView`; the
  permission check ran with `list_name="list_all_with_rows"` and passed; calling
  the result raised `TypeError: '_PermissionEnforcingListView' object is not
  callable`. Exactly the shape the class documents about its own removed
  `create()`.
- **The collision set is COMPUTED, not hand-listed.** `__getattr__` raises
  `AttributeError` for any name in
  `_PROPERTY_LIST_STORE_METHOD_NAMES`, derived at import from `vars()` of both
  `property.PropertyListStore` and `interface.property_store.PropertyListStore`.
  A hand-written literal would rot: a method added to either store and forgotten
  here is a latent `TypeError` at best, and — if anyone later "fixes"
  `__getattr__` by resolving to the store — a read bypass. A test re-derives the
  set independently and asserts they agree.
- **The bypass guard is asserted directly**, not implied. A sentinel object is
  planted on the unauthenticated store as `list_all_with_rows`, and the test
  asserts `__getattr__` raises rather than ever returning it. The dangerous
  repair (`return getattr(self._store, name)`) makes every other test in the
  file pass, so this is the only one that would catch it.
- **The "no denied name in any log record" test had to be scoped**, as the plan
  half-anticipated: `evaluate_bulk_property_access` logs every denied name at
  WARNING under `actingweb.permission_evaluator`. A bare `caplog` assertion
  catches those. The test asserts only that no record from
  `actingweb.interface.authenticated_views` carries a denied name — the real
  property, since in the single-list path the name came from the caller and here
  it came from storage.
- **The drop-all-on-error path needed two catches, not one.**
  `evaluate_bulk_property_access` swallows its own exceptions and returns
  all-`DENIED`, but `get_permission_evaluator()` itself can raise; both are
  covered, and both yield `([], {})` rather than a partial result.
- **`ValueError` and `DbError` deliberately propagate** through
  `list_prefix_with_rows()`. Neither is a permission outcome, and swallowing
  either would be indistinguishable from "you may read nothing here".

---

## Phase 6: a loaded attribute bucket becomes authoritative

Three changes in order; each is a prerequisite for the next. Phase 1 is a
prerequisite for all of them.

**6a — a faulted bucket load must not set the flag.** Today
`Attributes.get_bucket` sets `data = {}` and `_bucket_loaded = True` when the
backend returns `None` (`attribute.py:91-98`), and both backends return `None`
for a *caught exception* (`db/dynamodb/attribute.py:63-64`,
`db/postgresql/attribute.py:221-223`) — with PostgreSQL additionally returning
`None` for a genuinely empty bucket (`:209-210`). Making the flag authoritative on
top of that would turn "I could not read the bucket" into "the bucket has no such
attribute", permanently for that instance.

The fix stays inside `attribute.py`: set `_bucket_loaded = True` **only when the
backend returned a dict**, and leave it `False` on `None` whatever `None` meant.
On PostgreSQL it is conservative — an empty bucket is never trusted, so `get_attr`
still point-reads there — and that costs nothing real, because an empty bucket has
no absent-name savings to give up.

**Premise corrected, verified empirically (2026-08-29).** The plan said "on
DynamoDB that is exact — `{}` for empty, `None` only on a caught exception". Only
half of that holds, and the half that does not is worth knowing before writing
the test. `DbAttribute.get_bucket()`'s `try/except` wraps the Query
*construction* only; PynamoDB returns a lazy `ResultIterator` there and the HTTP
request fires during `for t in query`, which is **outside** the `except`.
Measured against the running backend:

| what happens | `DbAttribute.get_bucket()` |
| --- | --- |
| genuinely empty bucket | returns `{}` |
| fault during iteration (a throttle mid-page — the realistic case) | **raises past the except** |
| fault during construction (bad credentials, missing table) | returns `None` |

And `Attributes.get_bucket()` does not catch, so a raised fault propagates to the
caller with `_bucket_loaded` still `False` — already the safe outcome. So on
DynamoDB the `None`-means-fault case this phase guards is the narrow
construction-fault one; the case the fix genuinely earns its keep on is
PostgreSQL's catch-to-`None`, where a throttle really does present as an empty
bucket. The fix is unchanged; its justification is.

**Deliberately not normalising the backend contract.** The obvious alternative is
to make PostgreSQL's `get_bucket` return `{}` for an empty bucket so `None` means
fault on both backends. `Attributes.get_bucket:90` carries an explicit comment
about that divergence, so it is known and possibly depended on; a grep of
`get_bucket()` across `actingweb/` finds no caller branching on `is None` (every
one either goes through `Attributes`, which already normalises, or writes
`or {}`), but "no caller I found" is a weaker guarantee than "no backend edit".
The conservative version cannot break a caller that was not found. Aligning the
two backends is worth doing on its own merits — filed to `thoughts/todo/`, not
smuggled into a patch whose correctness argument does not need it.

**6b — `set_attr()` mirrors the backends' delete.** Both backends treat a falsy
`data` as a delete and return `True` (`db/dynamodb/attribute.py:140-148`,
`db/postgresql/attribute.py:339-365`) — and `delete_attr` is literally
`set_attr(data=None)`. Meanwhile `Attributes.set_attr` caches
`{"data": <falsy>, "timestamp": …}` (`:139-144`). Test `not data`, not
`data is None`, or the divergence just moves.

**6c — `get_attr()` honours `_bucket_loaded`.** Return `None` for a name absent
from `self.data` when the flag is set. This also stops `get_attr()` polluting the
bucket: `:110` assigns `self.data[name] = None` on a miss and `get_bucket()`
returns `self.data` by identity (`:99`), so a loaded bucket can currently grow
keys with no stored row.

The measured saving is zero today — no library call site pairs `get_bucket()` with
`get_attr()` on one instance, and the miss is already negatively cached, so only
the first lookup per absent name ever cost anything. The argument is the contract:
`InternalStore` (`attribute.py:9-66`), held for an `Actor`'s lifetime, already
loads the bucket once and thereafter reads its own `__dict__` — the same bypass a
consumer wrote a seven-line comment to justify.

### Changes

- `actingweb/attribute.py:85-99` — set `_bucket_loaded` only when the backend
  returned a dict; update the docstring to say the flag means "loaded and the
  backend answered". No backend edit.
- `actingweb/attribute.py:117-154` — `set_attr()` drops the key from `self.data`
  when `not data`, mirroring the backend.
- `actingweb/attribute.py:101-115` — `get_attr()` returns `None` early when
  `_bucket_loaded` and the name is absent.

### New Tests

- Unit: `get_bucket()` on a faulting backend leaves `_bucket_loaded` False and a
  subsequent `get_attr()` still reads through. **Fails today.**
- Unit (DynamoDB): `get_bucket()` on a genuinely empty bucket sets the flag, so
  `get_attr()` on it costs nothing.
- Unit (PostgreSQL): `get_bucket()` on an empty bucket does **not** set the flag,
  and `get_attr()` still point-reads. Pins the conservative choice deliberately,
  so a later backend alignment changes a test rather than surprising someone.
- Unit: after `get_bucket()`, `get_attr("absent")` issues **zero** backend calls
  and returns `None`.
- Unit: after `get_bucket()` then `get_attr("absent")`, a second `get_bucket()`
  does not contain `"absent"`. **Fails today.**
- Unit: `set_attr(name, data={})` — and `[]`, `""`, `0`, `False`, `None` — leaves
  the name absent from `self.data`, and a following `get_attr(name)` returns
  `None` without a backend call.
- Unit: "absent" vs "present with value `None`" stays distinguishable — a stored
  row holding null returns the truthy dict `{"data": None, …}`, absence returns
  `None`. Pins research §6 B5.
- Unit: `delete_attr()` on a loaded bucket leaves the flag set and the name
  absent.
- Unit: `InternalStore` behaviour is unchanged across all of the above.
- Regression: `tests/test_attribute.py` passes unchanged.

### Verification

- [x] `poetry run pytest tests/test_attribute.py -v` passes (unchanged)
- [x] `poetry run pytest tests/test_attribute_bucket_authority.py -v` passes (28 new; 19 fail without the change)
- [x] `poetry run pytest tests/integration/test_db_attribute_buckets.py -v` passes on both backends (10 each)
- [x] `poetry run pytest tests/ -k "oauth or token" -v` passes (332)
- [x] `poetry run ruff check actingweb tests` passes
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Whole suite green: 2,361 unit, 911 integration

### Implementation Status: Complete

**Deviations and learnings:**

- **The premise correction recorded above was written into the code**, not just
  the plan: `get_bucket()`'s docstring now says which fault shapes actually
  produce `None` on each backend, and notes that on DynamoDB a throttle raises
  through the method rather than returning `None` at all — because
  `DbAttribute.get_bucket()` wraps only the Query construction while PynamoDB
  fires the request lazily during iteration.
- **The integration test asserts the divergence rather than papering over it.**
  `attrs._bucket_loaded is (DATABASE_BACKEND != "postgresql")` after loading a
  genuinely empty bucket: DynamoDB returns `{}` and is trusted, PostgreSQL
  returns `None` and is not. The *answer* is identical on both; the divergence
  costs one point read on PostgreSQL and nothing else. So a later backend
  alignment (`thoughts/todo/`) changes a test rather than surprising someone.
- **`set_attr()` needed restructuring, not a one-line guard.** The old body
  unconditionally built `self.data[name] = {}` before assigning; the falsy
  branch has to `pop` instead, and the truthy branch keeps the old shape.
  `not data`, not `data is None` — `{}`, `[]`, `""`, `0` and `False` all delete
  on both backends, each covered by a parametrised case.
- **`InternalStore` keeps its own `_loaded` latch**, so a faulted load still
  leaves that instance looking empty — unchanged by this phase, and given an
  explicit test so the difference from `Attributes` is not later mistaken for a
  regression introduced here.

---

## Phase 7: documentation, changelog, release

### Changes

- `docs/guides/property-lists.rst:458-482` — restructure "Reading Many Lists
  Cheaply" into two recipes. Carry three things the current prose cannot: that
  the scoped read is **not** universally cheaper (summing every family is
  1,363.5 RCU / 15 queries against 1,361.0 / 11, so replacing one dump with six
  scoped calls makes things marginally worse); that the latency win is
  caller-side and its floor is the deepest pagination chain, not one round trip;
  and the cross-family skew note. Keep the existing "pass it straight into
  `prime_from_rows()`/`to_list_from_rows()`" paragraph applying to both.
- `CHANGELOG.rst` — a fresh "Unreleased" section. Phase 1 and Phase 2 lead: both
  are correctness fixes with a data-loss shape, and they matter more to a reader
  than the cost work. Phase 6 needs the `**Behavior change**:` treatment in the
  house style (`:26-34`, `:77-81`, `:88-93`) — nothing raises or warns, so the
  release note *is* the discovery mechanism. Say explicitly that a long-lived
  `Attributes` instance loses the accidental first-miss re-read, and that
  `handlers/mcp.py` caches an `ActorInterface` on a sliding five-minute TTL.
- File the `_glob_to_regex` `$`/`DOTALL` gaps to `thoughts/todo/`.
- Update `thoughts/todo/INDEX.md` row 22 and delete
  `thoughts/todo/scoped-bulk-list-reads.md` when the work lands — the plan and
  its verification are the record.
- **PR shape (decided).** One PR carrying all seven phases, each as its own
  commit. That PR is therefore the release PR, so the bump and the "Unreleased"
  rename belong in it, per CLAUDE.md — there is no separate release PR and no
  bump on master afterwards.

  Two consequences worth stating, because a single PR is where phasing quietly
  stops paying:

  - **Phases 1-6 write their CHANGELOG entries under "Unreleased" as they land.**
    Only this phase renames that section to `v3.14.3: <date>` and opens a fresh
    empty one. Doing the rename earlier would leave later phases writing into a
    released section.
  - **The version bump is the last commit.** If a phase has to be dropped because
    it cannot be made green, it is dropped before the bump, not reverted after —
    which is the whole reason the phases stay independently testable inside one
    PR. Phase 6 is the likeliest candidate: it depends on Phase 1 and has the
    smallest measured payoff. Phases 1 and 2 are the least droppable, since both
    are correctness fixes with a data-loss shape.
- Version bump to **3.14.3** in `pyproject.toml` and `actingweb/__init__.py`,
  rename "Unreleased" to `v3.14.3: <date>`, per CLAUDE.md's release process. The
  bump rides in this PR, as the shape note above requires; the tag goes on the
  merge commit after it lands on `master`, which is protected.

### New Tests

- `poetry run sphinx-build -W docs docs/_build` treats warnings as errors.
- No new code tests; this phase adds none.

### Verification

- [ ] `poetry run pytest tests/ --ignore=tests/integration -n auto` passes
- [ ] `poetry run pytest tests/integration` (SEQUENTIAL) passes on DynamoDB
- [ ] `DATABASE_BACKEND=postgresql … poetry run pytest tests/integration`
  (sequential) passes

  **Deviation from `make test-all-parallel`, measured.** On this machine the
  parallel integration run is not a usable gate: `pytest tests/ -n auto` gave
  103 failed / 167 errors in 623 s, every one an HTTP `TimeoutError` against a
  per-worker uvicorn, spread across all nine workers. The same suite run
  sequentially is **888 passed, 8 skipped, 71 s** — faster in wall clock as well
  as trustworthy, because the failures are contention between ~10 concurrent
  servers plus DynamoDB Local, not isolation. The `make` targets also (a) invoke
  `docker-compose` hyphenated, which does not resolve here, and (b) end in
  `down -v`, which destroys the containers and the mounted
  `tests/integration/dynamodb-data` volume mid-session. Unit tests parallelise
  fine (`-n auto`, 2,278 passed, ~3.5 min) and that half is kept.
- [x] `poetry run ruff format --check actingweb tests` passes (357 files, CI enforces it)
- [x] `poetry run pyright actingweb tests` reports 0 errors
- [x] Docs build clean (`sphinx-build -W`)
- [x] Manual: `pyproject.toml` and `actingweb/__init__.py` both read `3.14.3`

### Implementation Status: Complete

**Deviations and learnings:**

- **The docs section grew a sub-section rather than becoming two parallel
  recipes.** "When the scoped read actually pays" carries the three things the
  old prose could not: that summing scoped reads over everything is *worse*
  than one dump (1,363.5 RCU / 15 queries against 1,361.0 / 11), that the
  latency win is caller-side and its floor is the deepest pagination chain, and
  that there is no snapshot isolation across calls or across lists within one.
  The existing "pass it straight into `prime_from_rows()`" paragraph now applies
  to both, as planned.
- **Two todos were filed, not one.** The `_glob_to_regex` gaps went to
  `thoughts/todo/glob-to-regex-anchoring-gaps.md` (INDEX row 23) as planned; the
  backend upsert divergence found in Phase 1 went to
  `thoughts/todo/attribute-upsert-bucket-drift.md` (row 24).
- **`thoughts/todo/scoped-bulk-list-reads.md` is deleted and INDEX row 22 is
  gone**, with §1 carrying a one-line pointer at this plan instead of a "CLOSED"
  row. `prop-list-key-prefix-scheme.md`'s reference to the deleted file was
  repointed at this plan rather than left dangling.
- **PostgreSQL's *unit* leg needs `alembic upgrade head` against the `public`
  schema first**, which CI does as a separate step and which is easy to miss
  locally: without it 58 tests fail identically on this branch and on `master`.
  After the migration the only remaining failures are two
  `tests/performance/test_backend_performance.py` subscription cases, which fail
  on `master` too — the test passes a callback URL where the backend expects a
  boolean. **CI never sees them**: they carry `@pytest.mark.benchmark` and the
  workflow runs `-m "not benchmark"`, under which the PostgreSQL unit leg is
  2,245 passed / 0 failed. Untouched by this branch, and not filed here because
  it is a test bug in code this release does not go near.

---

## Evaluation Notes

### Architecture

- **`get_prefix` belongs on `DbPropertyProtocol`, not `DbPropertyListProtocol`.**
  Confirmed rather than assumed: every scoped multi-row read already lives on
  `DbProperty`, none touches instance state, and `property_list.py` already
  consumes them via `get_property(config)`. `DbPropertyList` is the *stateful*
  whole-partition class. Adopted in Phase 3.
- **Phase 2 cannot route through `PropertyListStore`** — `property.py:5` imports
  `ListProperty`, so the reverse import is circular. The three sites call
  `get_property(self.config)` directly, which is already imported. Adopted.
- **The `or {}` finding** was not in the research doc and is the strongest
  argument for Phase 2: today a transient PostgreSQL read fault makes `compact()`
  empty the list. Promoted into the phase body and given its own test.
- **`bucket + ":"` alone does not make Phase 1 exact**, because bucket names and
  attribute names both contain `:`. Phase 1 now narrows the Query *and* compares
  `t.bucket` exactly, matching `delete_by_chain`. A third precedent
  (`db/dynamodb/subscription_suspension.py:76-80`) was found and is cited.
- **Row filtering must not live in `interface/`** — `property.py:66-71` declares
  row names opaque, and the permission layer is the furthest thing from the
  encoding owner. Resolved with `rows_for()` in `property.py` (Phase 4), called
  from `authenticated_views.py` (Phase 5).
- Confirmed no test pins the current broken `__getattr__` routing, so Phase 5
  breaks nothing; and `prime_from_rows`/`to_list_from_rows` are already written
  for partial input.

### Security

- **`delete_bucket()` shares `get_bucket()`'s over-match and deletes.** Reachable
  through `RemotePeerStore.delete_all()` on `remote:{peer_id}`, with 15 call sites
  passing `validate_peer_id=False`, so peer ids are remote-party-chosen and prefix
  relationships are reachable. Promoted to Phase 1 and put first in the plan.
- **The `__getattr__` repair shape could become a read bypass** if written as
  "resolve to the store's method". Phase 5 specifies `AttributeError` on
  collision, explicit method definitions, and a test asserting nothing unwrapped
  is ever returned.
- **A bare `startswith` row prune strips a permitted sibling's rows**, landing in
  the silent-`[]` case. Phase 4's `rows_for()` uses the library's own attribution
  logic; Phase 5 has the `foo` / `foo-old` test.
- **My PostgreSQL answer was wrong** and is corrected in Phase 3: a prefix read has
  no exact inclusive upper bound, so `starts_with()` with a bound parameter
  replaces the `COLLATE "C"` pair. The failure direction is silent truncation, not
  disclosure.
- **Prefix injection: no finding.** `f"list:{prefix}"` puts the literal first and
  neither primitive is a pattern language, so no prefix escapes the namespace.
  Recorded under "What We're NOT Doing" so nobody adds a validator that gives
  false assurance. The one way it becomes a finding is `LIKE`, which Phase 3
  avoids.
- **Filter semantics pinned** to `result in (ALLOWED, NOT_FOUND)`, drop-all on
  error, and no denied name in any message or log.
- **Item 6 is not an authz surface today** — every `Attributes` in the permission
  and token paths is constructed per call. Confirmed rather than assumed; it stays
  a release-note item.

### Scalability

- **`consistent_read=False` must not reach Phase 2's callers.** Once a read is
  scoped to one list, strong consistency costs ~6–13 RCU — about 1% of what the
  scoping saved — and buys a guarantee two destructive rewrites currently lack.
  Split explicitly: eventual on the public bulk path (where the 2× decides
  whether the change pays at all), strong on the converted internal callers.
- **`f"list:{prefix}"` would be a regression for Phase 2** — `list:output` matches
  `list:output_embeddings_*`, 678 RCU. Phase 2 uses `_v1_bounds()` instead, which
  also removes its dependency on Phase 3.
- **`_maybe_lazy_migrate()` is the only user-facing beneficiary** — three
  whole-partition dumps inside an `append()`. Added to Phase 2's scope and tests.
- **Per-query rounding is not a risk.** Break-even against a 1,361 RCU dump is
  ~2,700 tiny lists on one actor, versus the ~13 the repo itself cites. Measured
  overhead at family granularity is 0.18%. But the maintenance scripts' saving is
  ~3× on a single-list actor, not the headline ratio — stated in Phase 7's release
  note so nobody expects otherwise.
- **PostgreSQL's win is TOAST detoasting, not index seeks** — the PK is under the
  default collation, so neither today's read nor the scoped one range-scans on
  `name`. Rows average 8.1 KB, well past the ~2 KB TOAST threshold, so excluded
  rows genuinely never pay. Whether the planner also skips heap fetches is
  unverified and deliberately not claimed.

### Usability

- **`list_prefix_with_rows` kept** over the alternatives: it carries the `list`
  verb, that scoping is by prefix, and the `_with_rows` return-shape signal.
  Parameter is singular `prefix`, matching one-prefix-per-call.
- **Empty prefix raises**, rather than silently becoming the whole-partition dump
  under a name promising the opposite.
- **The new method propagates `DbError`** while `list_all_with_rows()` keeps its
  swallow. For a scoped read empty is the *common* answer, so `([], {})` would
  render a throttled query as content. The asymmetry is stated in both docstrings
  so it reads as chosen.
- **The most likely migration bug is silent**: a caller swapping methods and still
  iterating `names` loses every list outside the prefix. Documented as a contract
  ("`names` is scoped too, necessarily"), not as a caveat.
- **Phase 5 must add all three bulk readers**, not just the new one — otherwise the
  documented API stays a latent `TypeError` while the new one works.
- **No migration page**; `docs/migration/` is minors-only. Behaviour changes go to
  CHANGELOG in the established style, and for Phase 6 the release note *is* the
  discovery mechanism, since nothing raises or warns.

## Implementation Summary

**Completed:** 2026-08-29
**All phases:** Complete (1-7)
**Test status:** All passing

Final run, per the amended Phase 7 gate:

| suite | DynamoDB | PostgreSQL |
| --- | --- | --- |
| unit (`tests/`, `--ignore=tests/integration`) | 2,361 passed, 23 skipped | 2,245 passed, 122 skipped, 17 deselected |
| integration (`tests/integration`, sequential) | 911 passed, 8 skipped | 903 passed, 16 skipped |

The PostgreSQL unit column uses CI's own `-m "not benchmark"` filter. Without
it, two `tests/performance` subscription cases fail — identically on `master`,
in code this branch does not touch — and CI deselects them, so its Postgres leg
is clean. That leg also needs `alembic upgrade head` against the `public` schema
first, which CI does as its own step.

`ruff format --check` clean over 357 files, `ruff check` clean, `pyright` 0
errors, `sphinx-build -W` clean, `poetry check --lock` clean.

Six commits, one per phase, then the release commit. `master` is protected, so
the tag goes on the merge commit after CI is green on both backends.

### Deviations from Plan

Each phase's own "Deviations and learnings" carries the detail. The four that
changed the work rather than its packaging:

1. **Phase 2 had a correctness hole the plan did not see.** v1 `verify()` counts
   `foreign_format_rows` — v2-shaped residue — out of the partition dump, and v2
   rows sort at `#` (0x23), *below* `_v1_bounds()`'s lower bound `list:{name}-0`
   (0x30). Four existing tests caught it. It now costs one extra keys-only range
   read via `_v2_item_names_in_range()`, the mirror of what `_v2_verify()`
   already spends counting v1 residue.
2. **Phase 1's "ambiguous composite key" is a primary-key COLLISION, not two
   coexisting rows.** Both backends key on `(id, bucket_name)`, so bucket
   `remote:abc`/name `x` and bucket `remote`/name `abc:x` are the same row and
   the second write overwrites the first. That makes the exact-`bucket` compare
   *more* necessary, not less, but the test had to be rewritten around storable
   data. A backend divergence underneath it is filed to `thoughts/todo/`.
3. **Phase 4's A6 invariant only holds in one direction.** `names` comes from
   `-meta` rows, so a damaged list whose meta row was lost contributes rows
   attributed to no name. Pruning them was rejected — it would discard
   recoverable data and diverge from `list_all_with_rows()` — so it is a
   documented contract with a test asserting both methods agree.
4. **Phase 6a's stated premise was half wrong.** On DynamoDB most real faults do
   not arrive as `None` at all: `DbAttribute.get_bucket()` wraps only the Query
   construction while PynamoDB fires the request lazily during iteration, so a
   throttle raises straight through with the flag unset — already safe. Measured
   against the running backend. The fix is unchanged; its justification is
   PostgreSQL's catch-to-`None`.

Packaging deviations: tests went to new files where the plan named files that
turned out to be the wrong shape (`tests/integration/test_attributes.py` is an
HTTP flow suite, not a DB-level one); and Phase 7's `make test-all-parallel`
gate was replaced with a parallel unit run plus a sequential integration run,
because the parallel integration run on this machine gives 103 failures in 623 s
where the sequential one gives 0 in 71 s.

### Learnings

- **`get_property_list` had exactly three callers in `property_list.py`.**
  Removing them removed the import, which broke 27 monkeypatches in
  `test_property_list_integrity.py`. Deleting those is a strengthening: the tests
  now exercise the real scoped read rather than a hand-fed partition dict.
- **The three "fails today" claims were each demonstrated against the pre-change
  code** rather than asserted: `compact()` deleting all three rows of a healthy
  list and writing `length: 0` on a faulted read; `authed.list_all_with_rows`
  resolving to a `_PermissionEnforcingListView` and raising `TypeError` when
  called, after the permission check passed on the *method name*; and 19 of
  Phase 6's 28 tests failing without the attribute change.
- **`rows_for()` was verified independently.** The security review brute-forced
  every name pair over `{a, -, 0, #}` up to length 5 against all five row shapes
  and found zero cross-attribution leaks. The longest-first ordering turns out to
  be defensive rather than load-bearing — the shape checks alone are sufficient —
  but it makes the property true by construction rather than by argument.
- **The security review found nothing.** It specifically cleared the PostgreSQL
  parameterisation, the prefix's inability to escape the `list:` namespace, the
  new `AttributeError` branch, and the fail-closed paths; and noted that
  `NOT_FOUND`-counts-as-permitted is the existing REST behaviour this SDK path is
  reaching parity with, not new ground.
