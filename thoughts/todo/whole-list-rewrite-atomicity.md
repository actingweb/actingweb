# Whole-list rewrites are not crash-atomic

`compact()` in both storage formats rewrites a list's rows in place: survivors
are written to their new positions before the old rows are retired, so an
interruption leaves a copy at both.

**Severity:** Medium. Reachability is low — `compact()` is an operator action,
not on any request path — and the failure is loud: the damage is visible in the
data (`length` goes to roughly `2n` for v2; `verify()`'s adjacent
byte-identical heuristic catches v1). Re-running `--repair` does not remove it.
The window is documented in the migration guide, the property-lists guide and
both docstrings.

**Why it is still open:** two designs died under adversarial review, and the
argument that a release triggers fleet-wide `--repair` runs was judged not to
justify shipping a third in a hurry. `thoughts/plans/2026-08-15-property-list-metadata-integrity.md`
("Designs cut") is the long form of both post-mortems.

## Two designs already died here — read this before proposing a third

**A lease row carrying a recovery journal.** Cut because both candidate payloads
destroy data that today's journal-less re-run preserves.

- *v1:* sources `[1,2,3,4]`, targets `0..3`, rows `1:b 2:c 3:d 4:e`. Write
  `0:=b`, write `1:=c`, crash. Resume re-reads the sources → `[c,c,d,e]`, **`b`
  destroyed**. A re-run today yields `[b,c,c,d,e]` — duplicate visible, nothing
  lost. Sound resume needs an *exact* per-item cursor; a checkpointed-every-N
  cursor is not sufficient.
- *v2:* classifying a rank as "new" iff it is in
  `generate_n_keys_between(None, None, n)` fails both ways. A list built by
  repeated `insert(0, …)` has no old rank in the target set, so recovery deletes
  every uncopied row. And where old ranks *are* in the target set — exactly why
  the nudge branch in `property_list.py` exists — recovery keeps stale rows as
  authoritative and **silently permutes** the list.

**Stage-and-flip: build a complete copy in an inactive namespace, commit with one
metadata write naming the active namespace.** Its core claim held — single-runner
crash atomicity, a clean v2 crash matrix at all four steps, re-run convergence,
and the rank-collision retry loop becomes unnecessary. Cut on three findings:

1. **No concurrency required to break it.** Alternating markers mean a compacted
   list *rests* on the scratch marker. `migrate_to_v2()`'s commit never writes
   `item_marker`, so the documented `--repair` → `--migrate` sequence produces
   `{format:2, item_marker:"%"}`, and surviving `%{i}` rows read as v2 items
   (`_v2_is_rank("0")` is True — digits are in the base62 alphabet) sorting
   `0,1,10,11,2,…`: silently permuted, `verify()` reports healthy.
2. **It converts a visible failure into an invisible one** — see the first
   constraint below, which is the most valuable thing either post-mortem
   produced.
3. **Cache-derived namespaces.** Resolving the namespace from `_meta_cache` turns
   a stale cache from a wrong-*format* problem into a wrong-*namespace* one:
   `len()` → 0, `to_list()` → `[]` with no error, `append()` into a dead
   namespace, unbounded for any retained `ListProperty`.

## Constraints any third design must satisfy

- **`fetch_all_including_lists` is a paginated DynamoDB `Query`, not a
  snapshot.** Sort order puts a scratch range before `-meta`, so one dump can
  miss the staged rows *and* pick up the flipped marker — `GET
  /properties/<list>` returns 200 with an empty array, with a single writer.
  Today the same page skew yields *duplicates*: visible, and caught by
  `verify()`. **Any scheme that stores "which namespace is live" in the item
  partition converts a visible failure into an invisible one on the default
  backend.** PostgreSQL is immune (single `SELECT`, one MVCC snapshot).
- **Prefer a visible failure to an invisible one.** The principle both cut
  designs violated, and why the current duplicate residue was kept.
- **A CAS exists on `DbProperty`** (`set_if_value_equals`, backed by
  `_v2_touch_metadata()`'s bounded retry loop; `docs/guides/property-lists.rst`
  "Concurrency during a whole-list rewrite" has the current state). So the
  primitive a stage-and-flip-style design needs to commit its metadata flip
  atomically against a concurrent writer is available. **It does not by itself
  make `compact()` crash-atomic** — both designs above died on *data*-shape
  findings, not on a missing CAS.
- **DynamoDB transactions cap at 100 actions**, below the list sizes that need
  rebalancing — the same reason
  `thoughts/plans/2026-08-08-property-list-index-integrity.md` ruled them out
  for the original shift-loop fix.
- **`length` is an absolute value with more than one writer.** Several reviewed
  failures traced to a mutation computing `length` against one view and merging
  it into metadata describing another. v2 avoids this by storing no length; the
  write side is fixed (`_save_metadata()` names the fields it changes, merges
  them into a fresh read, and refuses to write `length` into a v2 row). The
  **read** side is the residual: v1's `append()`/`insert()` still derive the new
  length from `len(self)`, which reads `_meta_cache`, so a retained instance can
  compute a stale absolute value and write it. Making `length` relative (a
  delta, or dropping it for a counted range read as v2 does) belongs to whatever
  design lands here.
- **v1 has a range read**: `_v1_bounds()` / `_v1_item_names_in_range()` in
  `property_list.py`, with a `^\d+$` shape filter that is load-bearing rather
  than cosmetic — a sibling list named `foo-5` stores `list:foo-5-0`, which
  sorts inside list `foo`'s v1 range. So "the inactive namespace" has a defined
  extent under v1. `sweep_foreign_format_rows()` is the existing consumer.

## Related

- `thoughts/plans/2026-08-15-property-list-metadata-integrity.md` — the plan
  that deferred this; "Designs cut" is the long form of both post-mortems.
- `thoughts/todo/attribute-list-shift-design.md` — sequenced after this work,
  and it inherits this gap if done first.
