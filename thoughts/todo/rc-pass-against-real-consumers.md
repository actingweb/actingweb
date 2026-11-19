# The 4.0.0 release candidate against real consumers

**Filed:** 2026-11-18, by `thoughts/plans/2026-11-15-3-16-release-validation.md`
(Phase 4). Waits on `v4.0.0rc1` being on TestPyPI.

## What is left

The release validation ran every consumer check against the branch, by
path. Three of them are repeated, and one is new, with the published release candidate,
because only that proves the wheel (the skill is not in it, the console
scripts and the packaged templates are):

1. **`actingwebdemo` to the rc.** In its worktree: the submodule to the
   `v4.0.0rc1` tag, `poetry lock`, its tests (after the README's
   `actingweb-unique-creators enable --apply` on a fresh store), then the
   owner's `deploy.yml` dispatch with `pypi_index: testpypi`. Its adoption
   work first: a fresh-store step in its CI, ruff `^0.15` or a `vendor/`
   exclude, and `dynamodb:BatchGetItem` and `dynamodb:ConditionCheckItem` on
   its function role. The data steps run before the merge that deploys; the
   order is the runbook in
   `thoughts/research/2026-11-18-3-16-release-validation.md`
   ("`actingwebdemo` against this branch"). The public demo runs 3.15.1
   until then, and the changelog's `SECURITY` section is public from the
   tag, so this is the first thing after it.
2. **Emm's pin on the rc.** Emm's suite with `actingweb==4.0.0rc1` from
   TestPyPI instead of the path form; the baseline is the five names in the
   research note, and the run procedure is its section "Running Emm's suite
   against this library".
3. **The Agent Skill with the library from TestPyPI.** The same task as the
   release validation's (a FastAPI app, a property hook, a fresh DynamoDB
   Local prefix, a REST round trip), in a scratch repository with the rc
   installed and the skill copied from the repository at the rc tag, for
   Claude Code and Codex.

4. **3.15.1 on a PostgreSQL database at `a7b8c9d0e1f2`.** The guide's
   checklist runs `alembic upgrade head` before the deploy; whether a
   3.15.1 process keeps serving on the retyped `attributes` key columns
   was not tested (the live pair ran on DynamoDB). Run the live pair's
   3.15.1 side on PostgreSQL against a database at head; if it works, the
   guide's step 4 can drop its maintenance-window advice.

## When it is done

Each item's outcome goes into the release's verification or the plan for
the stable release; this file is deleted when all four are done.
