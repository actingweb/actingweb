# `migrate_to_v2()` still has an unguarded window before its first write

> **Planned 2026-08-15 —
> `thoughts/plans/2026-08-15-property-list-metadata-integrity.md`.** That plan
> does **not** take the claim row this file argues for, and none of the three
> options below survived. It closes the *unbounded* variant of this window (a
> stale metadata cache writing back over a completed migration — a worse trace
> than the one below, found during review) and then **accepts** the residual
> two-query window as documented last-writer-wins at list granularity. Read the
> plan's "Decisions Made" and "Designs cut" before reopening this.

`ListProperty.migrate_to_v2()` guards against a concurrent migration by
reading the stored format twice: once before deciding the list is v1, and
once more — directly from the meta row, not through the cache — immediately
before step 3 clears any leftover v2-range rows. Two ordinary reads are not a
lock. If another instance completes a migration *and* appends a new item in
the gap between that second read and the clear, this attempt deletes the
now-authoritative rows (including the new item) and writes its older
`ordered_values` snapshot over them.

Raised as a P1 on PR #121 (Codex, second review round) and accepted as real.
Not fixed there: closing it needs a mutual-exclusion primitive, which is a
design addition rather than a patch.

## How big the window actually is

Materially smaller than the one the first round found, which is why this is a
todo rather than a blocker:

- **Before the fix in `602b404`:** the decision was made from a possibly
  stale *cache*, so the window was unbounded in time — an instance could hold
  a v1 metadata cache indefinitely and then destroy a list migrated minutes
  earlier.
- **After it:** the window is between two adjacent queries — a single `get()`
  of the meta row and the `get_range()` that starts the clear. The other
  instance has to complete a *whole* migration plus a mutation inside that.

It is not zero, and the lazy trigger means concurrent migration attempts on
the same list are a real scenario (any two mutating requests for the same
actor race for it), so this should not be left indefinitely.

## Options

1. **A claim row, taken with `create_if_not_exists()`.** The primitive
   already exists and is already used for conditional item writes. Write
   `list:{name}-migrating` (note: outside the v2 rank range — the range's
   upper bound is `list:{name}-$`, and `m` sorts above `$`, so it cannot be
   mistaken for an item row), proceed only if the create succeeded, delete it
   at the end. The catch is the usual one: a holder that dies leaves the list
   permanently unmigratable, so it needs an expiry timestamp in the row and a
   documented "stale claim" override in the bulk script.
2. **CAS on the meta row.** Conceptually the right fit — the transition being
   protected *is* the format flip — but neither backend's `DbProperty`
   currently exposes a compare-and-set, so this means a new protocol method
   plus two implementations.
3. **Make step 3 non-destructive.** Rather than clearing the v2 range and
   rewriting, claim it: write each v2 row with `create_if_not_exists()` and
   abandon the attempt on any collision. This removes the destructive step
   entirely, at the cost of the idempotency step 3 exists for — an
   interrupted attempt's own leftover rows would block every retry, so it
   needs a way to distinguish "my leftovers" from "someone else's", which
   lands back at option 1 or 2.

Option 1 is the cheapest that actually closes it.

**Decided 2026-08-14** (owner walkthrough): planned jointly with
`thoughts/todo/v2-compact-staged-commit.md` under one `/create_plan`. Both want
a mutual-exclusion / recoverable-commit primitive over the same storage layer,
and designing them separately risks two divergent mechanisms.

## Context

- The narrower cousin of this bug (deciding from a cached format) IS fixed;
  see `thoughts/verifications/2026-08-09-property-list-index-integrity.md`.
- The same "two reads are not a lock" shape applies to `_v2_setitem`/
  `_v2_delitem`/`_v2_getitem`, which force a rank re-read before acting.
  There the residual window is inherent to a positional API over shared
  storage and is a stale-read, not a destructive, race — the distinction that
  makes those acceptable and this one worth closing.
- Related: `thoughts/todo/v2-compact-staged-commit.md` wants a recoverable
  commit protocol for the same class of reason. If both get done, they should
  probably share one mechanism.
