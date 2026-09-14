# A v2 list mutation can raise after its item write has committed

**Provenance:** filed by the Emm AI consumer (`actingweb_mcp`) on 2026-09-14.
It came out of the retry-safety audit on their `fix/mcp-error-envelope-iserror`
branch. Triaged the same day against `master` at `adfecc3`. Findings, line
references and options are in
[`../research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md`](../research/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md).

## What is wrong

Every v2 `ListProperty` mutator commits its item row, then calls
`_v2_touch_metadata()`. `advisory=True` there swallows only compare-and-swap
exhaustion (`property_list.py:924-935`). A backend fault in the touch is
different: a `DbError` on either backend, or a `RuntimeError` from
PostgreSQL's `set` when the row is being created. That fault propagates out
of a mutation that already happened. The library's HTTP handlers return it as
500, and MCP tool hooks return it as `-32603`.

A caller that retries then misreports its own write:
- a save comes back as a duplicate
- a delete comes back `not_found`
- an update gets a revision conflict
- a two-phase move can lose both copies

Beyond the report:
- `pop()` loses the popped item.
- `remove_where`/`update_where` and the v2 bulk POST loop discard partial
  results that committed.
- `NotifyingListProperty` never registers the diff, so subscribers miss the
  change.

The class docstring (`property_list.py:312-314`) and plan 2026-08-20 already
list "a backend fault after the item write" as tolerated drift. The code does
not implement it.

On a list's **first** mutation the touch is what creates the meta row. A
fault there leaves item rows with no meta row, and three things follow:
- `exists()`/`list_all()`/REST cannot see the list.
- `verify()` calls it healthy.
- `delete()`, `clear()` and `migrate_to_v2()` would sweep its items as
  residue.

## What doing it buys

A committed write stops being reported as a failure, so a caller's retry can
no longer duplicate or lose data. This is the class a consumer cannot guard
against in-process on lambda. Pinning it needs a fault-injection double at the
`property_list.py` level, which is a different seam from the backend-level one
the "`DbError`-on-genuine-fault path untested" line in
[`v2-list-access-verification-followups.md`](v2-list-access-verification-followups.md)
asks for. That line stays open.

## What has to be decided first

The research lays out options for each. In short:

1. **Existing meta row:** swallow a backend fault in the advisory touch the
   way contention is swallowed. The evidence favours this.
2. **Meta-row creation (first mutation):** options are
   - meta row first
   - atomic item + meta (a new backend primitive)
   - swallow and rely on next-mutation repair
   - repair on read
   - a typed "committed" exception carrying the lost result

   Option 3 and repair on read each run into a recorded constraint.
3. **Scope:** v2 item mutators only, or also v1 and whole-list operations.
   Those are non-advisory by recorded decision, and a v1 contention error is a
   503 "retry" after a committed write.
4. **Partial multi-item results:** what `remove_where`/`update_where`/
   `extend`/bulk POST report when k−1 of k operations committed.
5. **Which texts change:** the docstrings, guide and handler comment that
   currently contradict each other.
6. **The adjacent finding, in or out:** botocore retrying a timed-out
   conditional write can make `create_if_not_exists`/`delete_if_value_equals`
   return `False` for a write that landed. That would give a duplicate
   `append`, or a `pop` that removes two items. It was traced, not
   reproduced, and is a different mechanism from the one reported.
