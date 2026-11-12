# Run the Wire-Phase trailer check in CI, not only locally

**Origin:** `thoughts/plans/2026-11-06-subscription-wire-baseline.md`
(Phase 1, "Deviation: the `Wire-Phase` check is local only") and
`thoughts/verifications/2026-11-12-subscription-wire-baseline.md`
(Remaining Tasks, Issue 4).

`tests/integration/verify_groups.py` checks that every commit on a branch
that changes or removes a wire recording carries a `Wire-Phase:
<plan>:<phase>` trailer naming one of that row's owners in `rows.toml`.
The check needs the branch's history, but CI's test job
(`.github/workflows/tests.yml`, the `tests` job's `actions/checkout@v5`)
checks out at depth 1. There the check finds no merge base with `master`
and reports that it was skipped. A PR can therefore re-record a row its
phase does not own, and CI stays green. Today the check runs only when a
developer runs `verify_groups.py` locally.

**What doing it buys:** the "rows.toml is the only copy of which phase may
change which recording" rule (owner, 2026-11-07) holds for every PR, not
only for those whose author ran the script.

**What it needs:**

- The owner's decision on changing the workflow: `fetch-depth: 0` (or
  enough depth to reach the merge base) on the `tests` job's checkout. The
  `changes` job already fetches full history.
- The check's own gaps (verification Issue 4) are closed (plan iteration
  1, 2026-11-12): owners are read at the merge base, merges are checked,
  git runs from the repository root, an unparsable registry is reported.
- In CI, `master` is `origin/master` (the PR's base); the check already
  prefers the newer of `origin/master` and `master`.
