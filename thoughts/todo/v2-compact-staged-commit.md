# `_v2_compact()` needs a recoverable commit protocol

`ListProperty._v2_compact()` rebalances a v2 list's fractional rank keys by
writing every item under a fresh, evenly-spaced rank and then deleting the old
rows in a second pass. A crash between those two passes leaves both copies of
every already-rewritten item inside the authoritative range: reads return
duplicates, and re-running `compact()` cannot recover — it sees 2n rows, treats
all of them as genuine items, and rebalances the doubled list.

Raised as a P1 on PR #121 (Codex review, `actingweb/property_list.py:1186`) and
accepted as real. Not fixed there: the fix is a protocol change, not a patch,
and the current behaviour is the safer of the two obvious options.

## Why the obvious fix is worse

Delete each old row immediately after writing its replacement, so at most one
item is ever duplicated? That trades a visible failure mode for an invisible
one. Target ranks come from `generate_n_keys_between(None, None, n)` — always
`a0, a1, a2, …` — while existing ranks can sort anywhere; a list built by
repeated `insert(0, …)` has ranks like `Zz, Zy, …`, all *below* `a0`. Rename
item 0 to `a0` and retire its old row and item 0 now sorts *after* items
1..n-1. A crash there leaves a silently permuted list: no duplicates, rank
lengths healthy, `verify()` reports nothing wrong. Duplicate residue is at
least detectable in the data.

## What a real fix needs

Any of these, roughly in increasing cost:

1. **Marked staging.** Write replacements under a rank that carries a
   "pending" marker outside the readable set, then flip the whole list in one
   metadata write, then retire the old rows. Needs a second reserved marker
   character with the same isolation proof `#` has, and readers that
   understand both states.
2. **A compaction journal row.** Record the intended old→new rank mapping in a
   single row before any item write. A re-run reads the journal and can tell
   stale copies from live ones, making recovery mechanical instead of manual.
   Cheapest of the three and probably the right one.
3. **Backend transactions.** DynamoDB caps a transaction at 100 actions, which
   is below the list sizes that need rebalancing in the first place — the same
   reason `thoughts/plans/2026-08-08-property-list-index-integrity.md` ruled
   transactions out for the original shift-loop fix.

## Why the current failure mode is at least loud

Worth recording, because it is the strongest part of the argument for leaving
this as-is until the redesign lands: after a crashed compact, `_v2_verify()`'s
`length` goes from `n` to close to `2n`, and so does `len(mylist)`. That is a
coarse signal but a reliable one, and it does not depend on the
adjacent-duplicate heuristic — which is *not* guaranteed to catch this, since
an item's old and new ranks need not sort adjacently. The reordering failure
mode the alternative design would produce has no signal at all: same length,
same values, healthy rank lengths, `verify()` reports nothing.

## Context

- Reachability is low: `compact()` under v2 is a rank-length rebalance, invoked
  by an operator via `scripts/verify_property_lists.py --repair` or directly
  from library code — not on any request path.
- The window is documented in `_v2_compact()`'s docstring, including how an
  operator distinguishes stale copies (old ranks are the ones *not* drawn from
  the fresh `a0, a1, …` sequence).
- Related deferred work: `thoughts/todo/attribute-list-shift-design.md`.
