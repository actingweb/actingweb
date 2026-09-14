# set_description()/set_explanation() still create the meta row unconditionally

**Provenance:** found during implementation of
[`../plans/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md`](../plans/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md)
(Phase 1: a list's first `append()`/`extend()`/`insert()` now creates its
meta row conditionally, via `_v2_create_meta_row()`, before the first item
write). Depends on that plan having landed.

## What is wrong

`set_description()`/`set_explanation()` (`actingweb/property_list.py`,
`_save_metadata()` calls with `create_if_absent=True`, the default) still
create a missing meta row through `_save_metadata()`'s creation branch, whose
write is an **unconditional** `set()` (`_replace_metadata()` with
`expected_raw=None`). The v1 length writers and `clear()`'s replace go
through the same branch, unconditionally, by the same recorded decision.

After the 2026-09-14 plan, a list's first `append()`/`extend()`/`insert()`
creates the meta row **conditionally** (`create_if_not_exists`). A
`set_description()` racing a first `append()` can now land its unconditional
`set()` over the row the conditional create just wrote, resetting
`count_hint` from 1 back to 0 (whatever the append's `count_delta` had
merged onto the freshly-created row is overwritten by `set_description()`'s
merge, which read the row before the append's touch ran).

Nothing is lost: the description itself is never dropped, and the next
rank-counting mutation (`insert()`/`pop()`/`remove()`/`__delitem__`/
`compact()`) repairs the hint from counted truth, same self-correction the
drift bound already documents. This is a **last-writer-wins race on
`count_hint`**, not data loss — narrower than what existed before that plan
(where a fault on the *unconditional* touch-as-creator could lose the meta
row's existence entirely), not a new class of bug.

## What doing it buys

Every meta-row creation becomes conditional, one creation path
(`_v2_create_meta_row()`) instead of two shapes with different guarantees.
Removes the one remaining unconditional-write race the 2026-09-14 plan's
first-mutation fix introduced a narrower version of.

## What has to be decided first

Whether the shared creation branch inside `_save_metadata()` — used by
`set_description()`/`set_explanation()`, the v1 length writers (with
`create_if_absent=False`, so this doesn't apply to them the same way), and
`clear()`'s replace — should:

- route through `_v2_create_meta_row()` (a v2-only creation path, so the
  branch would need to stay for v1 callers), or
- grow its own conditional create shaped for whatever fields the calling
  writer carries (`description`/`explanation` for these two, `format`/
  `length` for `clear()`'s replace).

Either shape changes a branch three different call sites share; work out the
call-site fields each needs before touching the branch itself.
