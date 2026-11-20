# The 4.0.0 release candidate against real consumers

**Filed:** 2026-11-18, by `thoughts/plans/2026-11-15-3-16-release-validation.md`
(Phase 4). `v4.0.0rc1` is on TestPyPI since 2026-11-20 (tag on `717873e`).

## What is left

The release validation ran every consumer check against the branch, by
path. One is left to repeat with the published release candidate (the
Agent Skill run, the PostgreSQL pair and the demo's deploy are done,
`thoughts/research/2026-11-18-3-16-release-validation.md`, 2026-11-20),
because only that proves the wheel (the skill is not in it, the console
scripts and the packaged templates are):

**Emm's pin on the rc.** Emm's suite with `actingweb==4.0.0rc1` from
TestPyPI instead of the path form; the baseline is the five names in the
research note, and the run procedure is its section "Running Emm's suite
against this library".

## When it is done

The outcome goes into the release's verification or the plan for
the stable release; this file is deleted when it is done.
