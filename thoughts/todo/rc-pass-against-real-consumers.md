# The 4.0.0 release candidate against real consumers

**Filed:** 2026-11-18, by `thoughts/plans/2026-11-15-3-16-release-validation.md`
(Phase 4). `v4.0.0rc1` is on TestPyPI since 2026-11-20 (tag on `717873e`).

## What is left

The release validation ran every consumer check against the branch, by
path. Two of them are left to repeat with the published release candidate (the Agent Skill run and the PostgreSQL pair are done, `thoughts/research/2026-11-18-3-16-release-validation.md`, 2026-11-20),
because only that proves the wheel (the skill is not in it, the console
scripts and the packaged templates are):

1. **`actingwebdemo` to the rc.** The pin is ready in
   `actingweb/actingwebdemo#32` (2026-11-20): `vendor/actingweb` at
   `v4.0.0rc1`, Python 3.14, ruff `^0.15`, the role's
   `dynamodb:BatchGetItem` and `dynamodb:ConditionCheckItem`,
   `AWS_DB_PREFIX` stated, `OPEN_FACTORY=true`; its tests pass on a fresh
   store with no setup step. Left for the owner: the operator steps against
   the demo's store (the guide's "Start here", with `AWS_DB_PREFIX` set and
   an identity with DynamoDB data rights; vouch the existing actors or clear
   them first), then the merge, which deploys `demo.actingweb.io`. The
   public demo runs 3.15.1 until then, and the changelog's `SECURITY`
   section is public from the tag, so this is the first thing to finish.
2. **Emm's pin on the rc.** Emm's suite with `actingweb==4.0.0rc1` from
   TestPyPI instead of the path form; the baseline is the five names in the
   research note, and the run procedure is its section "Running Emm's suite
   against this library".
## When it is done

Each item's outcome goes into the release's verification or the plan for
the stable release; this file is deleted when both are done.
