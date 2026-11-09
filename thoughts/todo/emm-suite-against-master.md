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
at a plan's commit. The section below is what was known before it ran,
kept because the run confirmed both points.

## Per-plan runs

- **`peer-authorisation-fixes`, 2026-11-08:** the library worktree at
  `0ce0112`, Emm's adoption worktree with the plan's two `subscriber` rows
  (uncommitted, owner decision), environment 9. PostgreSQL 2 failed / 7406
  passed, DynamoDB 3 failed / 54 passed: the baseline's failures by name.
  Recorded in `verifications/2026-11-07-peer-authorisation-fixes.md`, with
  Emm's adoption items (one new: Emm's connect flow subscribes twice after
  a re-pair answering 201). Re-run on 2026-11-08 after that plan's
  iteration (`d836bd0`), on `a8007e5` after the second, on `dca966f` after the third, on `376b71c` after the whole-branch review's fixes, on `d3fd713` after the audit's fixes on `244ccb9` after reverify-7's on `20abc3a` after reverify-8's and on `16f5972` after reverify-9's (environment 9): the same counts and failures.

## What was known before the first run

Read on 2026-11-06, not run:

- **Emm does not start on `master`.** `../actingweb_mcp/application.py:566`
  calls `.with_legacy_property_index(enable=False)`, and that method now
  always raises `RuntimeError` (`actingweb/interface/app.py:485-502`). No
  test runs until the call is removed.
- **A fresh test database probably stops at readiness.** Emm turns creator
  uniqueness on (`application.py:561`), and 3.16 raises
  `UniqueCreatorNotReady` until `actingweb-unique-creators enable --apply`
  has run (`docs/migration/v3.16.rst`, the opening note). Nothing in Emm's
  code or scripts names the command or the exception.
- **Emm's own todo for the pin predates both.**
  `../actingweb_mcp/thoughts/todo/actingweb-3-16-pin.md` (filed 2026-10-29)
  covers the account marking and the fault contract, not the removed call or
  the readiness step.

So the first run is Emm's 3.16 adoption, done on a branch in Emm, not a
plain test run. That branch is what every later run uses.

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
- Emm's preview environment and Docker free; environment 8 is the one the
  runs use.

Delete this file when the last of the six plans has merged with its run
recorded. The order and the rule that each plan waits on its run are in
[`INDEX.md`](INDEX.md), "Planned for 3.16".
