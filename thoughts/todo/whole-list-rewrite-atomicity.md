# Whole-list rewrites are not crash-atomic

`compact()` in both storage formats rewrites a list's rows in place: survivors
are written to their new positions before the old rows are retired, so an
interruption leaves a copy at both. Supersedes
`thoughts/todo/v2-compact-staged-commit.md`, which was deleted when
`thoughts/plans/2026-08-15-property-list-metadata-integrity.md` landed the
adjacent fixes and deferred this one.

**Status:** Open, deferred from 3.13.0 GA deliberately. rc6 documents the window
in the migration guide, the property-lists guide and both docstrings; the damage
is *visible* in the data (`length` goes to roughly `2n` for v2; `verify()`'s
adjacent byte-identical heuristic catches v1) and re-running `--repair` does not
remove it.

**Severity:** Medium. Reachability is low — `compact()` is an operator action,
not on any request path — and the failure is loud. It was scoped as a GA blocker
on the argument that GA triggers fleet-wide `--repair` runs; that argument is
still true, but two candidate designs failed adversarial review, and shipping a
third under time pressure was judged worse than shipping the documented window.

## Two designs already died here — read this before proposing a third

**A lease row carrying a recovery journal.** Cut because both candidate payloads
destroy data that today's journal-less re-run preserves.

- *v1:* sources `[1,2,3,4]`, targets `0..3`, rows `1:b 2:c 3:d 4:e`. Write
  `0:=b`, write `1:=c`, crash. Resume re-reads the sources → `[c,c,d,e]`, **`b`
  destroyed**. A re-run today yields `[b,c,c,d,e]` — duplicate visible, nothing
  lost. Sound resume needs an *exact* per-item cursor (a resume at cursor `k` may
  read `sources[k:]` because no target `>= k` has been written yet); a
  checkpointed-every-N cursor is not sufficient.
- *v2:* classifying a rank as "new" iff it is in
  `generate_n_keys_between(None, None, n)` fails both ways. A list built by
  repeated `insert(0, …)` has no old rank in the target set, so recovery deletes
  every uncopied row. And where old ranks *are* in the target set — exactly why
  the nudge branch at `property_list.py:1659-1672` exists — recovery keeps stale
  rows as authoritative and **silently permutes** the list.

**Stage-and-flip: build a complete copy in an inactive namespace, commit with one
metadata write naming the active namespace.** Its core claim held — single-runner
crash atomicity, a clean v2 crash matrix at all four steps, re-run convergence,
and the rank-collision retry loop becomes unnecessary. Cut on three findings, the
second of which is the most valuable constraint any of this produced.

1. **No concurrency required to break it.** Alternating markers mean a compacted
   list *rests* on the scratch marker. `migrate_to_v2()`'s commit never writes
   `item_marker`, so the documented `--repair` → `--migrate` sequence produces
   `{format:2, item_marker:"%"}`, and surviving `%{i}` rows read as v2 items
   (`_v2_is_rank("0")` is True — digits are in the base62 alphabet) sorting
   `0,1,10,11,2,…`: silently permuted, `verify()` reports healthy.
2. **`fetch_all_including_lists` is a paginated DynamoDB `Query`, not a
   snapshot.** Sort order puts a scratch range before `-meta`, so one dump can
   miss the staged rows *and* pick up the flipped marker — `GET
   /properties/<list>` returns 200 with an empty array, with a single writer.
   Today the same page skew yields *duplicates*: visible, and caught by
   `verify()`. **Any scheme that stores "which namespace is live" in the item
   partition converts a visible failure into an invisible one on the default
   backend.** PostgreSQL is immune (single `SELECT`, one MVCC snapshot).
3. **Cache-derived namespaces.** Resolving the namespace from `_meta_cache` turns
   a stale cache from a wrong-*format* problem into a wrong-*namespace* one:
   `len()` → 0, `to_list()` → `[]` with no error, `append()` into a dead
   namespace, unbounded for any retained `ListProperty`.

## Constraints any third design must satisfy

- **A CAS now exists on `DbProperty`** (`set_if_value_equals`, backed by
  `_v2_touch_metadata()`'s bounded retry loop — see
  `thoughts/plans/2026-08-20-v2-positional-access-cost.md` Phases 8-9;
  `docs/guides/property-lists.rst` "Concurrency during a whole-list
  rewrite" has the current state). The primitive a stage-and-flip-style
  design needs to commit its metadata flip atomically against a
  concurrent writer exists now. **It does not by itself make `compact()`
  crash-atomic** — the two designs below died on *data*-shape findings (a
  lease journal that destroys survivors on replay, a scratch-namespace
  marker a documented `--repair` → `--migrate` sequence permutes), not on
  the missing CAS. Re-read both post-mortems before assuming the CAS
  closes either hole.
- **DynamoDB transactions cap at 100 actions**, below the list sizes that need
  rebalancing — the same reason `thoughts/plans/2026-08-08-property-list-index-integrity.md`
  ruled them out for the original shift-loop fix.
- **`length` is an absolute value with more than one writer.** Several reviewed
  failures traced to a mutation computing `length` against one view and merging
  it into metadata describing another. v2 avoids this by storing no length.

  The 2026-08-15 plan fixed the *write* side — `_save_metadata()` names the
  fields it changes and merges them into a fresh read, and refuses to write
  `length` into a v2 row at all — and left the *read* side open, deliberately.
  v1's `append()`/`insert()` still derive the new length from `len(self)`, which
  reads `_meta_cache`, so a retained instance can compute a stale absolute value
  and write it. Making `length` relative (a delta, or dropping it in favour of a
  counted range read as v2 does) is the residual, and it belongs to whatever
  design lands here.
- **v1 now HAS a range read, as of 2026-08-15**: `_v1_bounds()` /
  `_v1_item_names_in_range()` in `property_list.py`, with the `^\d+$` shape
  filter this constraint said one would need — a sibling list named `foo-5`
  stores `list:foo-5-0`, which sorts inside list `foo`'s v1 range, so the filter
  is load-bearing rather than cosmetic. "The inactive namespace" therefore has a
  defined extent under v1 now, which removes one obstacle a third design would
  otherwise have had to build first. `sweep_foreign_format_rows()` is the
  existing consumer.
- **Prefer a visible failure to an invisible one.** This is the principle both
  cut designs violated, and it is why the current duplicate residue, for all its
  awkwardness, was kept in the first place.

## Related

- `thoughts/plans/2026-08-15-property-list-metadata-integrity.md` — the GA plan
  that deferred this; its "Designs cut" section is the long form of the above.
- `thoughts/todo/attribute-list-shift-design.md` — INDEX row 4, decided to
  sequence after this work, and it inherits this gap if done first.
