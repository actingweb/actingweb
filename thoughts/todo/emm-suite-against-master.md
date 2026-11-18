# Run Emm's suite against this library: once on master now, then for every 3.16 plan

**Filed:** 2026-11-06, by the owner, during the review of the six 3.16 plans.
Checked against `master` at `5a7e07f` and `../actingweb_mcp` at `dd5e2ccb`.

## What is wrong

Emm (`../actingweb_mcp`) pins `actingweb =3.15.1`
(`../actingweb_mcp/pyproject.toml:11`). `master` already carries the 3.16
work merged so far (the adoption and vouching rules, the fault contract, one
reverse-lookup mechanism, fail-closed creators), and nobody has run Emm's
suite against it. Six more plans are about to land on top, three of them in
the subscription code Emm depends on. With the tag held, all of it reaches
Emm in one pin change, and a failure then has no merge to be bisected to.

## What it buys

- **A known starting point.** A run on `master` as it is separates "what
  3.16 already breaks in Emm" from "what a later plan breaks".
- **A bisect point per plan.** A run on each plan's branch before its PR
  opens ties a consumer failure to one plan.
- **A check the wire recordings cannot give.** The recordings prove what two
  test apps shaped like Emm exchange; Emm's suite proves Emm.

## The first run, on `master`: done 2026-11-07

Recorded in
[`research/2026-11-07-emm-suite-against-master.md`](../research/2026-11-07-emm-suite-against-master.md):
no library regression; five failing tests, all documented 3.16 changes Emm
adopts on its branch, plus the pin guard deselected by design. **That list
is the baseline** for the runs below until Emm's branch adopts them. The
two worktrees exist and stay; the research note says how to re-point them
at a plan's commit. What was known before it ran (Emm does not start
until `with_legacy_property_index` goes; a fresh store stops at
readiness) is confirmed there.

## Per-plan runs

Recorded in each plan (verification or Iterations); all so far showed the
baseline's failures by name and nothing else:

- `peer-authorisation-fixes` (environment 9, last on `999f3b6`), with the
  plan's two `subscriber` rows in Emm's adoption worktree (owner decision).
- `grant-enforcement-per-route` (on `8adb9d6`).
- `subs-list-cache-lifetime` (on `c738f21`); no new IAM action.
- Not run for `subscription-wire-baseline` (no library change).

- `attribute-list-v2-port` (environment 9, last on `a98690a`; the PostgreSQL
  database migrated to `a7b8c9d0e1f2` first): the baseline's failures, plus
  Emm's own date-dependent `tests/test_trial_state_pure.py` case, failing
  from 2026-11-13 on any library
  (`thoughts/verifications/2026-11-14-attribute-list-v2-port-7.md`, which
  says why the two library commits after `a98690a` were not re-run).

- `email-as-creator-at-write-time` (environment 9, on `844695a` and again
  on `515f09a` after its iteration): the baseline's failures, nothing new.
  Before each, `actingweb-unique-creators creator-to-email` on the
  environment's database (the start-up check refuses Emm's flag-on
  application without its marker): nothing to move, the marker written.
  Emm's role grants no `dynamodb:ConditionCheckItem`, which uniqueness
  already needed and the rename's marker check needs too; its IAM coverage
  test does not look for it (an adoption item on Emm's side)
  (`thoughts/verifications/2026-11-15-email-as-creator-at-write-time-2.md`).

- `spec-1-5` (environment 9, on `2f1a891`, `creator-to-email` first:
  nothing to move): the baseline's failures, nothing new. Not re-run for
  its four iteration commits (merged as #178, `e928e5b`), against gate 2's
  rule; verification `2026-11-16-spec-1-5-2` deferred it. The release
  validation's run on `master` covers them, so a new failure there may be
  theirs.

- `3-16-pre-validation-fixes` (environment 9, on `d62021b`,
  `creator-to-email` first: nothing to move): the same six failures by name
  as the `spec-1-5` run, nothing new. Run again on `3fb93ab` (the branch
  after its verification's iteration): PostgreSQL 3 failed, 7,405 passed;
  DynamoDB lane 3 failed, 54 passed; the same six by name; and on `ab11326`
  (after the second iteration) with the same counts and names; and on the
  uncommitted third, fourth and fifth iterations (`8bb63cf` with the
  working tree's `actingweb/` diff applied in the library worktree; run
  after entries 20 and 26): the same counts and names each time; and on
  `320925d` (entries 11 to 37 committed, the library worktree checked out
  at that commit): the same counts and names; and on `1a68f1d` (entries
  38 to 41) and `e6a8976` (entries 42 to 45): the same counts and names. Emm's `properties` data hook sends its UI a
  full-sync notification on `"resync"`: since this plan a poll that rebuilt
  the replica calls it (a quiet poll does not), and so does a callback that
  ran an owed rebuild.

- `3-16-pre-rc1-fixes` (environment 9, the library worktree at `a416e81`
  with the branch's uncommitted `actingweb/` diff applied;
  `creator-to-email` first: nothing to move): PostgreSQL 3 failed, 7,405
  passed; DynamoDB lane 3 failed, 54 passed; the same six by name, nothing
  new (2026-11-17). Again on its commits (library worktree at `e4c3015`,
  after its iterations): the same counts, the same six (2026-11-18).

**Running it: the PostgreSQL lane needs the environment's preview server.**
Emm's `tests/integration/mcp/` tests call `http://localhost:50<env>`; with
no server they error (125 connection refusals on 2026-11-17), which reads
as a regression until the log is opened. Start
`scripts/preview-start.sh 9 --no-ngrok` in Emm's worktree first, stop it
after. The DynamoDB lane (`scripts/test-backends.sh 9`) starts its own.

**What the runs taught the migration guide** (2026-11-17): the adoption
items Emm needed are now each in `docs/migration/v3.16.rst`, and the guide
gained what was missing: one table of the DynamoDB permissions 3.16 adds
(with the note that IAM has no `TransactWriteItems` action), the
fresh-database order for CI and test scripts, the `except Exception`
around a write that turns a 503 into a 500, test doubles that passed
because 3.15 swallowed a failed write, and a hooks-only subscriber's
`"resync"` and the poll's 429. The research note's open question about a
standing list of IAM actions is answered by that table.

Still to run: `3-16-release-validation` (the last; it deletes
this file). A run now starts with `creator-to-email` (dry run, then
`--apply`) on the environment's database before the preview server.

## How a run is done

Two worktrees and a virtualenv of Emm's own, so that neither repository's
main checkout moves and Emm's working environment stays on 3.15.1 (owner,
2026-11-07):

1. A git worktree of this repository at the commit under test (`master`, or
   a plan's branch). This checkout's `HEAD` does not move.
2. A git worktree of Emm on its 3.16 adoption branch, with its own
   virtualenv: `poetry install` there creates one for that checkout, so the
   path dependency, the lock and the installed library differ from Emm's
   main checkout without touching it. Its preview server and database are
   its own (`scripts/preview-start.sh N --no-ngrok`, Emm's `CLAUDE.md`).
3. In that worktree: switch `pyproject.toml` to the path form (line 12),
   pointed at the worktree from step 1; `poetry lock && poetry install`.
4. Emm's Full tier, the Python lines, as its `CLAUDE.md` gives them: the
   pytest line on PostgreSQL against its preview server (through
   `scripts/preview-start.sh N --no-ngrok` and `scripts/with-preview-env.sh
   N` when another session may hold `:5000`), and `scripts/test-backends.sh
   N` for DynamoDB. The frontend lines are not needed.
5. Before anything is committed in Emm: `git checkout pyproject.toml
   poetry.lock && poetry install`, as Emm's `CLAUDE.md` requires.
6. One run at a time, and not while a run of this repository's suite is
   going: both use Docker and local ports.

## What a result means

- **The first run, on `master`:** every failure is triaged as a library
  regression (fixed here before plan 0 starts), a documented 3.16 change Emm
  must adopt (fixed on Emm's branch; if the migration guide does not name
  it, the guide is corrected here), or a test of Emm's that was already
  failing. The list of what is left is the baseline for the later runs.
- **A later run, on a plan's branch:** no failure the baseline did not have.
  A new one is a regression to fix in the plan, or a consumer-visible change
  the plan's changelog and migration text must name and Emm's branch adapts
  to. The result goes in the plan's verification document.

## Needs first

- The two worktrees and Emm's virtualenv exist since 2026-11-07
  (`.claude/worktrees/master-5a7e07f` here, `.claude/worktrees/emm-3-16`
  on branch `actingweb-3-16-adoption` in Emm, uncommitted adoption edits
  in it). A run on a plan's branch re-points the library worktree and
  reinstalls, per the research note.
- Emm's preview environment and Docker free; environment 9 is the one the
  runs use (8 was the `master` run's).

Delete this file when the last of the 3.16 plans has merged with its run
recorded. The order and the rule that each plan waits on its run are in
[`INDEX.md`](INDEX.md), "Planned for 3.16".
