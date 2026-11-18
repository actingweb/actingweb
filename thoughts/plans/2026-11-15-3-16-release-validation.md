---
status: active
approved: 2026-11-18 by Greger Wedel
---

# Implementation Plan: validating 3.16 before its tag

**Date:** 2026-11-15
**Branch:** `release/3.16.0-release-validation`, one PR, one commit per phase plus the ownership commit Phase 1 needs (written on `release/3.16.0-email-as-creator-at-write-time`, updated on `master` at `da6de67`). The branch keeps this name whatever number Phase 1 decides.

No research document: the plan was written by hand from the owner's
seven-item list (2026-11-15). Its research note,
`thoughts/research/<date>-3-16-release-validation.md`, is started by Phase 1
and filled by each phase.

## Update Log

- **2026-11-18**: `/update_plan`, after the last three plans merged (#178,
  #179, #181), and the plan's first evaluation (five evaluators, then
  codex and a fresh-context reviewer; see "Evaluation Notes").
  - *Refreshed*: the counts and the state of the other plans (`master` at
    `da6de67`); what `3-16-pre-rc1-fixes` hands over; Emm's refs and
    `actingwebdemo`'s uncommitted work as they are on disk.
  - *Added by the owner*: an eighth item, whether this release is 3.16 or
    4.0, with `prop-list-key-prefix-scheme` and `dynamodb-known-next`
    judged in that light.
  - *Reshaped* (owner): discovery first. Phase 1 establishes what the
    release is (inventory, the wire against 3.15) and ends with the
    owner's decisions; the guide is restructured once, last, in Phase 4.
    The old order certified the guide in Phase 1 and edited it in Phases 2
    and 3.
  - *Decided by the owner*: a wire break traced to a `SECURITY` entry can
    only be accepted; Emm's suite runs against Emm's `main` with a new
    baseline; the library version is normalised out of the wire
    recordings once; the plan is `done` when Phase 4 lands; the plan
    carries acceptance criteria and a Spec Delta.
  - *Written in this update*: Acceptance Criteria, Traceability, Spec
    Delta. They replace nothing; the numbering starts here.

## Overview

3.16 reaches consumers in one pin change: 28 merges to `master` since
`v3.15.1` and none still to land before this one, 274 changelog entries under
`Unreleased` (3,564 lines, 33 of them **Breaking:**) and a 2,654-line
migration guide, both written plan by plan and never read as one document
(counted on `master` at `da6de67`: `git log v3.15.1..master --first-parent`,
the top-level list items of the section, `wc -l`).
This plan is the last one before the tag. It reads the release as a consumer
will meet it, closes what that reading finds, and ends with a statement that
the release is ready to tag, or with the list of owner decisions that stand
between it and the tag.

## Implementation Order

Last of the 3.16 plans. The order, the dependencies and the gates are in
[`thoughts/todo/INDEX.md`](../todo/INDEX.md), "Planned for 3.16"; that copy
wins.

**This plan** is the only one left: the nine before it have merged (the
last, `3-16-pre-rc1-fixes`, as #181 on 2026-11-18), so the changelog and the
guide are complete, the specification says 1.5, and the 3.15-to-3.16
comparison (item 6) has both sides. From `3-16-pre-rc1-fixes` it carries:
six more changelog entries to read (one `SECURITY`, two **Breaking:**), the
recordings `WG16` and `WG17` re-recorded, and a demo that is signed in to
through the browser's Basic prompt on Flask. It uses the wire
recordings (`tests/integration/wire/`) as the record of what 3.16 puts on the
wire, the Emm worktrees of
[`emm-suite-against-master`](../todo/emm-suite-against-master.md) for the
consumer runs, and it takes over the three items of
[`ai-agent-discoverability-followups`](../todo/ai-agent-discoverability-followups.md).

Gates 2, 3 and 5 apply. Gate 5 as this plan meets it: the only existing
recordings it changes are the eight that carry the library version (Phase
1), and any a restored 3.15 behaviour changes (Phase 2); each is owned in
`rows.toml` by a commit before the one that re-records it.

## The eight items, and where each is done

The owner's list, numbered as given; item 8 was added on 2026-11-18. Each
phase's verification names the items it closes.

| # | Item | Phase |
| --- | --- | --- |
| 1 | Review every change in 3.16; clean up and correct the changelog; everything a consumer needs is in the migration guide | 1 (inventory, entries correct), 4 (the section as it reads) |
| 2 | Review the migration guide against the implementation; make it readable and easy to follow for a consumer | 4 |
| 3 | Review how `../actingweb_mcp` (Emm AI) uses the library; does the guide, with the docs, answer every question its maintainer will have when migrating | 2 |
| 4 | Compare this repository's test coverage with Emm's uses of the library and name the gaps; in particular trust relationships, subscriptions, and the diff mechanisms that share memories | 2 |
| 5 | Is the local demo (`examples/demo/`) migrated properly to 3.16; prepare `../actingwebdemo` to use 3.16 once it is on TestPyPI | 3 |
| 6 | Protocol compatibility between 3.15 (what `actingwebdemo` runs) and 3.16; identify breaking changes; decide what to do about each | 1 (the table and the decisions), 2 (what was decided, built), 4 (the guide's section) |
| 7 | The remaining agent-discoverability work: review it and include what can be included in 3.16 | 3 |
| 8 | Is this 3.16 or 4.0; `prop-list-key-prefix-scheme` and `dynamodb-known-next` judged in that light and on what 3.16 changed | 1 |

## Decisions Made

- **Findings are fixed in this plan** - a wrong changelog entry, a hole in
  the guide, a missing test or a demo that was not migrated is corrected in
  the phase that finds it, not filed as a todo (owner rule). A finding that
  is a design question goes to the owner as a decision; the tag waits on it.
- **The docs stay consumer-generic** - the Emm reading (items 3 and 4)
  produces questions and gaps; what goes into `docs/` and `CHANGELOG.rst` is
  the pattern, with no Emm or `actingweb_mcp` specifics (owner rule
  2026-11-15). The Emm-specific answers are in the research note.
- **No Emm production code** - Emm is read, and its suite is run in its
  adoption worktree; nothing is written into Emm beyond what the test harness
  needs, and nothing is committed or pushed there (owner rule 2026-11-07).
  What its maintainer has to do is a list in the research note.
- **The plan stops at "ready to tag"** - the tag is the owner's, after
  the PR merges. The `actingwebdemo` pin moves only after the pre-release
  is on TestPyPI, so that step is prepared here and carried out after the
  tag.
- **The plan is `done` when Phase 4 lands** [Updated 2026-11-18] (owner) -
  as the contract has it. The steps that need a published build or live
  docs are todos, not open phases: Context7 stays in
  `thoughts/todo/ai-agent-discoverability-followups.md`, and Phase 4 files
  `thoughts/todo/rc-pass-against-real-consumers.md`. For this plan that
  wins over `.claude/workflow/release.md`'s "after the tag ... set the
  plan's `status: done`", which is about a release's own plan.
- **The plan carries acceptance criteria and a Spec Delta** (owner,
  2026-11-18) - although it is dated before the cutoff in `CLAUDE.md`: it
  is built after the five partial specs came to exist, and a finding may
  change behaviour.
- **Discovery first, the guide last** (owner, 2026-11-18) - Phase 1
  establishes what the release is and puts the decisions that follow from
  it to the owner; Phases 2 and 3 add content to the guide where a hole is
  found; Phase 4 restructures it once, under the number decided.
- **A break between 3.15 and 3.16 on the wire is not accepted silently**
  [Updated 2026-11-18] - the aim is none. Each one found gets an outcome
  chosen by the owner:
  - *accept*: a **Breaking:** changelog lead, a guide section and a
    statement of which side must upgrade first;
  - *restore* the 3.15 behaviour, or *keep both* behaviours for a peer that
    lacks an option tag (`/meta/actingweb/supported`).
  **A break traced to a `SECURITY` entry can only be accepted** (owner,
  2026-11-18): the 3.15 behaviour is the hole. Restore and keep-both are
  for other rows, each with a written argument that no security check is
  relaxed. Nothing is ever gated on `/meta/actingweb/version` or
  `/meta/version`: both are self-reported, a 3.15.1 peer announces protocol
  `1.0` like every older peer (`v3.15.1:actingweb/config.py:355`), and the
  specification forbids deciding by it (`docs/protocol/actingweb-spec.rst:88-90`).
- **More than three rows to restore or keep is its own plan** - this plan
  then ends at "not ready, decisions listed", which its Overview allows.
  Deduced, not asked: the feasibility evaluator's threshold.
- **Emm's suite runs against Emm's `main`, with a new baseline** (owner,
  2026-11-18) - the adoption worktree is brought up to `main` (`c1be751c`;
  the branch is a strict ancestor, the four uncommitted adoption edits are
  kept and re-applied), and one run on this repository's `master` gives the
  baseline this plan's runs are compared with. The nine earlier runs were
  against Emm of `dd5e2ccb`, 215 files behind, without Emm's newest sharing
  code.
- **The library version is normalised out of the wire recordings, once**
  (owner, 2026-11-18) - eight recordings carry `"version": "3.15.1"`, so
  every bump would re-record them (rc1, rc2, stable). The wire harness
  replaces the value with a placeholder and the eight are re-recorded in
  Phase 1.
- **Calling the release 4.0 removes nothing in this plan** - the three
  "removed at the next major" tombstones were created in this release and
  are what points an upgrader at the guide; their text is retargeted. A
  removal a major could take is a plan of its own. Deduced, not asked: the
  outside voice's finding, and this plan's own scope.
- **Three small tests are added** (`test_migration_guide.py`,
  `test_demo_first_run.py`, two functions in
  `test_docs_api_consistency.py`), where the first draft planned none, and
  **the guide's path becomes one constant with a documentation URL** in the
  eleven library messages that spell it. Deduced, not asked: each holds an
  acceptance criterion that was a manual read, and the constant is a change
  to message text a consumer sees.
- **At most fifteen new wire rows** - the CI wire step has ten minutes.
  Deduced, not asked.
- **This plan's PR carries the bump, as a release candidate** (owner,
  2026-11-15) - `3.16.0rc1`, or `4.0.0rc1` if Phase 1 decides so. It is the
  last PR before the tag, and CLAUDE.md puts the bump and the changelog
  rename in the release PR itself. An rc, not a beta: when this plan ends
  the release is feature-complete and validated, so the build is the
  release unless the TestPyPI pass finds something; a finding is fixed and
  tagged `rc2`. The stable release is then the second, version-only PR
  that `.claude/workflow/release.md` describes. The bump is Phase 4's last
  commit: the version files and the changelog heading only (the middle
  steps of `/release`); the PR is reviewed like any other, and the tag is
  the owner's.
- **No sub-headings in the changelog** - the contract's five categories
  stay as they are. Readability comes from the opening note, **Breaking:**
  entries first within `CHANGED`, and one order within a category.
  Deduced, not asked: sub-headings would change the contract.
- **The release is 4.0.0** (owner, 2026-11-18, at the end of Phase 1) -
  `4.0.0rc1` from this plan. What decided it: a consumer pinned `^3.15`,
  `~=3.15` or `<4` would take a 3.16.0 on a routine update, with 113 silent
  changes and converted attribute lists a 3.15.1 process reads as empty;
  and the
  v3.13 guide promised the lookup fallbacks to "the next major release",
  which is this one. Phase 4 does the rename; the branch and this plan's
  slug keep "3.16". The rule for a patch, a minor and a major is in
  `CONTRIBUTING.rst` ("Which number a release gets").
- **The key-prefix scheme stays out** (owner, 2026-11-18) - its trigger is
  no longer "the next major" but a measured one (the todo has it).
- **No item of `dynamodb-known-next` rides** (owner, 2026-11-18) - the file
  notes that item 3 needs neither the scheme nor a major.
- **Every difference the live pair and the code reading found is accepted**
  (owner, 2026-11-18) - the one observed break (a second trust request from
  a 3.15.1 application) traces to a `SECURITY` entry; a spanned reference
  and the missing resync callback for a `none` subscriber are accepted as
  3.15.1's own limits. Phase 2 builds no restore and no keep-both; Phase 4
  gives each a **Breaking:** lead, a guide section and the upgrade order.
- **What the owner supplies for item 7** (owner, 2026-11-15):
  - *Context7*: the owner has an account; the Context7 Admin MCP server
    (`context7-admin`, user scope) is the way in. The submission is made
    after the stable docs are live on Read the Docs, and confirmed by the
    owner like any other change there.
  - *The MCP quickstart*: the OAuth2 client of the `actingwebdemo`
    deployment is reused; the owner adds the quickstart's local callback as
    an authorised redirect URI and removes it after the test. The MCP
    client (`mcp-remote` or Claude Desktop) runs on the owner's machine.
    The demo application itself is not the target: it runs with
    `.with_mcp(enable=False)`.
  - *The Agent Skill*: the scratch repository is an empty directory outside
    this repository and its two siblings (`git init`, the library
    installed, nothing else, no `.env` copied in); the owner starts one
    fresh agent session in it and gives it the task. `actingwebdemo` cannot
    be that repository: its `CLAUDE.md` and `vendor/actingweb` would make
    the task succeed without the skill.

## Decisions Deferred

None. The three deferred on 2026-11-18 (the number, the key-prefix scheme,
the DynamoDB register) were decided the same day at the end of Phase 1 and
are under "Decisions Made".

## What We're NOT Doing

- New features or behaviour changes beyond what a finding requires - this
  plan validates the release, it does not extend it.
- Removals because of a major number - see "Decisions Made".
- Emm's migration itself - it is Emm's work; this plan only checks that the
  guide lets its maintainer do it.
- Deploying `demo.actingweb.io` - the deployment is `actingwebdemo`'s
  `deploy.yml`, run by the owner.
- The other todos in `thoughts/todo/` - only the discoverability follow-ups
  are in scope; the rest have no failure behind them that the tag should
  wait for.
- Designing or building the `prop#`/`list#` key-prefix scheme or an item of
  the DynamoDB register - each changes stored keys or a default and is a
  plan of its own. This plan judges them (item 8) and builds neither.
- A live pair on PostgreSQL, or against a peer older than 3.15 - the wire
  is the same on both backends (`rows.toml:18-19`, "One file serves both
  backends"), and what an older or non-library peer meets is answered from
  the specification, not tested.
- A check in CI that a 3.15 peer accepts what 3.16 sends - CI has one
  version of the library; that direction rests on the live pair's table.
- Pushing `docs/3-16-rollup-records` or anything the security-records rule
  holds back.

## What Already Exists

- `CHANGELOG.rst`, `Unreleased` - 274 entries: `SECURITY` 32, `REMOVED` 4,
  `CHANGED` 115, `ADDED` 38, `FIXED` 85; 29 **Breaking:** leads and four
  inline. No opening note yet. Reused; edited in place.
- `docs/migration/v3.16.rst` - 2,654 lines: "Start here" (a 32-item list in
  the order the plans were written), then "What changed and why" with one
  section per change (some forty), and "What stays the same". "Cross-site
  requests" is a top-level heading by mistake and takes fourteen sections
  under it. One label (`Step 0`); 8 code blocks and about 23 command lines.
  Reused; edited in place.
- Seven guide section titles are quoted by library messages and operator
  tools (`actingweb/config.py:65,73`, `actingweb/interface/app.py:1763,1801`,
  `actingweb/maintenance/property_lookup.py:59`,
  `actingweb/maintenance/email_as_creator.py:34`, among eleven places that
  spell the guide's path), and one test matches on a title
  (`tests/test_subscription_processing.py:113`).
- `tests/test_docs_api_consistency.py` - checks hook decorators in `docs/`
  and `skills/` against the library; excludes `docs/migration/` (line 24)
  and does not read `README.rst`. Extended, not replaced.
- `tests/test_version_consistency.py` - asserts the changelog's first
  release heading, `__version__` and `pyproject.toml` agree (line 64) and
  that `Unreleased` is near the top (line 94). The check for the bump.
- `tests/integration/wire/`, `rows.toml`, `_wire.py`, `verify_groups.py` -
  136 rows recorded between two test apps shaped like Emm, in one process.
  The recorder scrubs secrets (`_wire.py:828-839`) and compares bytes
  (`_wire.py:1036`); it has no rule for the version, which reaches eight
  files through `actingweb/interface/app.py:222` and
  `actingweb/handlers/mcp.py:1177`. A row's owner is read at the commit's
  first parent, so ownership is taken in an earlier commit than the
  re-record (`verify_groups.py:202-204`). The CI wire step has ten minutes
  (`.github/workflows/tests.yml:328`).
- `thoughts/research/2026-11-07-emm-suite-against-master.md` and
  `thoughts/todo/emm-suite-against-master.md` - how a run of Emm's suite is
  done (environment 9, `creator-to-email` first, the preview server for the
  PostgreSQL lane) and the nine runs so far: six failures by name (the five
  of the note's "Baseline" and Emm's own date-dependent
  `tests/test_trial_state_pure.py` case), the pin guard deselected. The
  last, on `e4c3015`, is close to `master`'s library code but not it
  (three files differ by twelve lines), and `spec-1-5`'s four iteration
  commits were never run alone.
- Emm on disk (2026-11-18): `../actingweb_mcp` is checked out on
  `research-docs`; `main` is at `c1be751c`; the branch
  `actingweb-3-16-adoption` is at `dd5e2ccb`, behind `main`; the adoption
  edits are uncommitted in `../actingweb_mcp/.claude/worktrees/emm-3-16`
  (`application.py`, `scripts/test-backends.sh`, `pyproject.toml`,
  `poetry.lock`). Emm's surface, outside its tests: 48 imported names, 16
  builder calls, 62 hook registrations (39 of them action hooks), four
  trust methods and seven subscription methods.
- `thoughts/research/2026-01-18-library-extraction-candidates-from-actingweb-mcp.md`
  and `thoughts/plans/2025-10-03-actingweb-mcp-protection-tests.md` - earlier
  inventories of what Emm uses; a starting point, checked against Emm as it
  is now.
- `examples/demo/` - the application behind `demo.actingweb.io`, imported by
  this repository's tests. In local QA mode it binds `127.0.0.1`
  (`application.py:338`). `tests/test_demo_example.py:36-39` stubs the
  readiness check, so no test runs the README's first-run sequence.
- `../actingwebdemo` - deploys `examples/demo/` from a shallow
  `vendor/actingweb` submodule (currently at `v3.15.1`); `deploy.yml`
  requires the submodule commit to be a release tag and verifies a
  pre-release on TestPyPI. Its checkout, on
  `deps/actingweb-3.16-python-3.14`, has seven uncommitted files that move
  it to Python 3.14.
- `docs/protocol/actingweb-spec.rst` - version 1.5, with its list of what
  changed since 1.4 (line 37 on, 49 "Changed:" lines).
- `v3.15.1` on PyPI, `python = "^3.11"`; `.venv311` here shows a 3.11
  interpreter is at hand. Its demo binds `0.0.0.0:5000` with `debug=True`
  and its test harness has no wire recorder, so neither is the 3.15 side of
  a pair.
- `examples/mcp_quickstart.py` - reads `OAUTH_CLIENT_ID` and
  `OAUTH_CLIENT_SECRET` from the environment (lines 49-50, no `.env`
  loading) and binds `0.0.0.0` on port 5000 (lines 30, 97).
- `skills/actingweb-app/SKILL.md` - is not in the wheel
  (`pyproject.toml:27-29`). Its local run has no first-run step (lines
  84-88) and it points at a migration from the GSI lookup that 3.16
  removed (lines 385-386).
- `thoughts/specs/` - five `partial` specs, created from
  `3-16-pre-rc1-fixes`; almost every statement is tagged `[plan]`.
- `thoughts/plans/2026-08-22-ai-agent-discoverability.md` (`status: done`),
  `docs/guides/mcp-quickstart.rst` - what the discoverability work shipped.

## Acceptance Criteria

Written in this plan (2026-11-18) from the owner's items; there is no
feature document. Many of a validation plan's results are documents and
runs, so several checks are named manual checks whose record is the
research note or the verification document.

- **AC-1** (item 1) — When a consumer reads the changelog for this
  release, every consumer-visible change merged since `v3.15.1` has an
  entry.
- **AC-2** (item 1) — When a changelog entry or the guide names a class,
  function, option, command or exception, that name exists in the release,
  or the text says it was removed.
- **AC-3** (items 1 and 2) — When a change needs the consumer to act, the
  migration guide has a section for it.
- **AC-4** (item 2) — When a consumer follows "Start here" from top to
  bottom, the steps come in the order they are done, and each says how to
  know it worked.
- **AC-5** (item 2) — When a consumer copies a command line from the
  guide, the command and its arguments exist as written.
- **AC-6** (item 2) — When a library message or operator tool names a
  section of the guide, the guide has a section with that title.
- **AC-7** (item 2) — When a consumer has to go back to 3.15.1, the guide
  says what is reversible, what is not, and after which step it is too
  late.
- **AC-8** (item 3) — When Emm's maintainer upgrades with only the
  changelog, the guide and `docs/`, every change the adoption needed is
  named there with what to do.
- **AC-9** (item 4) — When Emm calls the library for trust, subscriptions
  or the diffs that share memories, a test in this repository exercises
  that call between real actors on both backends.
- **AC-10** (item 4, gate 2) — When Emm's suite runs against this plan's
  branch, no test fails that the baseline of Phase 1 did not have.
- **AC-11** (item 5) — When `examples/demo/` is taken through its README's
  first-run steps on a fresh database, it starts.
- **AC-12** (item 5) — When a user walks the demo's web UI (create, sign
  in, properties, trust, subscription, delete), no step shows an error.
- **AC-13** (item 5) — When `actingwebdemo`'s own tests run against this
  branch's library, they pass.
- **AC-14** (item 6) — When a 3.15.1 application and an application of
  this release are peers, each of the nine flows in each direction either
  completes or is a break with an owner-chosen outcome.
- **AC-15** (item 6) — When a 3.15 peer sends a request in a form this
  release still accepts but no longer sends, the release answers as the
  compatibility table says.
- **AC-16** (item 6) — When a consumer has other versions running beside
  this release, the guide says which side upgrades first, for its own
  instances during a deploy, for peer applications on 3.15, and for older
  or other peers.
- **AC-17** (item 7) — When a user follows `docs/guides/mcp-quickstart.rst`
  with a real OAuth2 client and a real MCP client, the client signs in and
  lists the quickstart's tools.
- **AC-18** (item 7) — When a fresh agent session in a repository with
  only the library installed is asked to add a property hook, it uses
  `skills/actingweb-app/SKILL.md`.
- **AC-19** (item 7) — When that session's application is started on a
  fresh database by the skill's own instructions, it starts.
- **AC-20** (item 7) — When a consumer reads `examples/`, the quickstart
  guides, the skill or `README.rst`, no name the release removed is taught.
- **AC-21** (the bump) — When the PR merges, `actingweb.__version__`,
  `pyproject.toml` and the changelog's first release heading name the same
  release candidate.
- **AC-22** (the bump) — When the library version changes, no wire
  recording changes.
- **AC-23** (item 8) — When a contributor asks which number a release
  gets, `CONTRIBUTING.rst` states the rule for a patch, a minor and a
  major.

## Traceability

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | manual: the inventory table in the research note, one row per consumer-visible change with its changelog entry; no empty cell (a reading of prose) | Done 2026-11-18: 301 rows; the four with no entry have one now |
| AC-2 | 1, 4 | `tests/test_docs_api_consistency.py::test_release_notes_name_only_what_exists` (the guide and `Unreleased`, with a list of names the text says are removed), and `::test_release_notes_removed_list_is_current` | Passing (seen red on four names first; run again in Phase 4) |
| AC-3 | 4 | manual: the inventory's "guide section" column, filled after the restructure | Not run |
| AC-4 | 4 | manual: "Start here" walked against the operator-command table; each step's success signal read | Not run |
| AC-5 | 4 | `tests/test_migration_guide.py::test_guide_commands_exist_and_parse`; manual: the eight code samples run, the log in the research note | Not run |
| AC-6 | 4 | `tests/test_migration_guide.py::test_quoted_guide_sections_are_headings` | Not run |
| AC-7 | 4 | manual: the rollback section read against the inventory's "irreversible" rows | Not run |
| AC-8 | 2 | manual: the question list in the research note, each with the location that answers it; the adoption worktree's diff as the cross-check | Not run |
| AC-9 | 2 | the tests the usage-to-test matrix names, existing and new; each new test is added to this row when written, with the Emm call site it protects | Not run |
| AC-10 | 2, 4 | manual: Emm's suite in environment 9 (both lanes), failures compared by name with Phase 1's baseline (another repository's suite) | Not run |
| AC-11 | 3 | `tests/integration/test_demo_first_run.py::test_readme_first_run_sequence` | Not run |
| AC-12 | 3 | manual: the browser walk in local QA mode on a fresh database (a rendered UI) | Not run |
| AC-13 | 3 | manual: `actingwebdemo`'s test line in a worktree of it (another repository's suite) | Not run |
| AC-14 | 1, 2 | manual: the live pair's table, 18 cells (two versions cannot share the test process) | Done 2026-11-18: 18 of 18 complete; every difference has the owner's outcome (accept) |
| AC-15 | 2 | `tests/integration/test_wire_v315.py`, one test per row of the table marked "kept" or "restored"; each is added to this row when written | No row is "kept" or "restored" (owner, 2026-11-18): Phase 2 writes the tests for the forms the release still accepts from a 3.15 peer, from the pair's captures |
| AC-16 | 4 | manual: the section read against the table and the inventory's rolling-deploy rows; docs build | Not run |
| AC-17 | 3 | manual: the owner's machine, real client and credentials (cannot run in CI) | Not run |
| AC-18 | 3 | manual: one fresh agent session in the scratch repository, started by the owner | Not run |
| AC-19 | 3 | manual: the same session; the application is started, not only written | Not run |
| AC-20 | 3 | `tests/test_docs_api_consistency.py::test_taught_names_are_not_removed` (`README.rst`, `skills/`, `examples/`, `docs/` outside `migration/`, with the allow-list of pages that name a removed option on purpose) | Not run |
| AC-21 | 4 | `tests/test_version_consistency.py` (both tests) | Not run |
| AC-22 | 1, 4 | the wire suite in the Full tier, run after the bump commit | Phase 1: the eight recordings pass with the version set to `9.9.9`; run again after the bump |
| AC-23 | 1 | manual: the rule read in `CONTRIBUTING.rst` and CLAUDE.md "Release" | Done 2026-11-18 |

## Spec Delta

Empty when written (2026-11-18): this plan validates, and changes no
behaviour by design. The phase that changes behaviour (a defect fixed, a
3.15 behaviour restored) adds its statement here, under the spec it belongs
to, in the commit that makes the change. A new test that covers an existing
`[plan]` statement is a **MODIFIED** line that changes its tag to
`[plan+test]`; a new test adds no statement unless behaviour changed.
`/verify_implementation` merges what is here when the plan lands. A fix in
a capability with no spec (properties, lists, the demo) is noted in the
iterations log.

### `thoughts/specs/trust-permissions.md`

- None yet.

### `thoughts/specs/subscriptions.md`

- None yet.

### `thoughts/specs/web-ui.md`

- None yet.

### `thoughts/specs/mcp-server.md`

- None yet.

### `thoughts/specs/oauth-client-registration.md`

- None yet.

## Rules for every phase

- **One run at a time.** The Full tier, Emm's suite, the live pair and the
  demo walk never overlap: they share Docker and local ports, and
  `make test-all-parallel` ends with `down -v` (`Makefile:59`), which wipes
  DynamoDB Local. A live pair or a walk is finished, its results written to
  files and its servers stopped, before a suite starts.
- **What the notes may hold.** The research note, the verification document
  and any capture record outcomes and status lines. Never an
  `Authorization` header, a token, an authorization code, a client id or
  secret, a passphrase, a trust secret or a real account's address. No
  screenshot of a provider's consent page. Emm's inventory takes names
  only, from its source files; no `.env*` file of any repository is opened.
- **A hole that 3.15.1 also has** is written up only in the commit that
  fixes it; until the PR opens it stays local.
- **Everything listens on `127.0.0.1`**, with `ENABLE_DEVTEST` and
  `NUKE_SECRET` unset, and is stopped and its data removed when the step
  ends. The step's verification says so.
- **A browser** goes through the browser QA agent or offstage. If neither
  is available the walk stops and is reported; it is not run headed and not
  in the owner's signed-in profile.
- **Emm's suite** runs when `actingweb/` changed since its last run, and
  once on the final tree.
- **The verify loop's stop rule** (owner, 2026-11-11): clean is no
  peer-reachable Medium or higher; re-verification is scaled to the delta.

## Phase 1: what the release is, and what number it gets (items 1, 6 and 8)

Two commits: the first takes ownership in `rows.toml`, the second is the
phase.

### Changes

- **The ownership commit.** `tests/integration/wire/rows.toml`: a
  `[reserved]` entry for this plan's slug (`"WT10-WT29"`, `"WS20-WS39"`,
  `"WD30-WD49"`, `"WL40-WL59"`, `"WG20-WG39"`, and `"WV1-WV29"` for
  requests in a 3.15 peer's form), and this plan's Phase 1 added to the
  `owners` of `WT1`, `WT3`, `WT4`, `WG16` and `WG17`. Nothing else.
- **The version leaves the recordings.** `tests/integration/_wire.py`: the
  normaliser replaces the library version with a placeholder where it is
  recorded (the `/meta` `version` and MCP `serverInfo.version`). The eight
  files are shown byte-identical over repeated runs on both backends first
  (gate 3), then re-recorded under the trailer `Wire-Phase:
  3-16-release-validation:1`, each with a dated `reason` line.
- **Emm's new baseline.** The adoption worktree is brought up to Emm's
  `main` with its four edits re-applied, and Emm's suite is run once
  against this repository's `master` (`da6de67`), before the branch changes
  any library code. The failures by name are the baseline for AC-10. It is
  also the first run that covers `spec-1-5`'s iteration commits, so a new
  failure in it is triaged as theirs before anything else.
- **The inventory**, the first table of the research note. One row per
  consumer-visible change in the 28 merges, built from each merge's own
  changelog hunk (`git show <merge> -- CHANGELOG.rst`) and a diff of the
  public names, not from the 44,000-line code diff. Columns: the change;
  its changelog entry; who is affected; whether the consumer must act; and
  how it meets an upgrader who did nothing, as one of *refuses to start*,
  *silent* (behaviour differs with no error) or *irreversible* (a 3.15
  process cannot read what the release wrote). The guide-section column is
  filled in Phase 4.
- **`CHANGELOG.rst`, `Unreleased`, made correct** against the inventory:
  - every row has an entry, and every entry describes what the release
    ships (a later plan often changed what an earlier entry says);
  - entries for one change from two plans are merged; a merge keeps every
    **Behavior change:** and "check" sentence;
  - an entry for something added and removed inside the release is deleted,
    but only with `git` evidence that it is absent at `v3.15.1`;
  - **a `SECURITY` entry is never deleted and never moved to another
    category**; the note records the count before and after with the
    mapping; no edit adds request-level detail of an exploit;
  - the four inline **Breaking:** marks become leads or are dropped, by the
    contract's rule;
  - no Emm or `actingweb_mcp` specifics.
  The order of the section and its opening note are Phase 4's.
- **`tests/test_docs_api_consistency.py`**: the names check extended to the
  newest migration guide and to the changelog's first section that has
  entries (so it still reads this release after the bump empties
  `Unreleased`) (AC-2). A dry run found 7 names in the guide
  and 20 in the section that do not exist in the tree; each is triaged as
  "removed, and the text says so" (it goes on the test's list) or wrong (it
  is corrected).
- **Item 6, the wire against 3.15.** Three sources:
  - *the specification*: the 49 "Changed:" lines since 1.4, each classed as
    additive, a clarification of what 3.15 did, or a change in what a peer
    sends or accepts. The class is a claim about a conforming peer; what
    3.15.1 does is what the pair shows;
  - *the recordings*: every row whose recording changed since its first
    (`git log` on the directory; the `reason` lines say why, `WG16` and
    `WG17` among them), classed the same way;
  - *a live pair*: `scripts/live_pair.py`, one launcher that builds a
    FastAPI application from builder calls both versions have (the shape of
    `tests/integration/conftest.py:1034-1052`), with a small ASGI logger
    that writes each request and response to a file, secrets scrubbed. It
    runs once under a fresh Python 3.11 virtualenv with `actingweb==3.15.1`
    from PyPI (what a peer actually runs) and once under this branch. Both
    on DynamoDB Local with their own table prefixes, on two ports outside
    5000, 5055 and 5555-5564; the release side goes through the real
    first-run steps (`actingweb-unique-creators enable --apply`). The
    launcher labels each side in its capture, because until the bump both
    report `3.15.1` at `/meta`. Nine
    flows in both directions, 18 cells: trust creation and approval,
    permission exchange, subscription creation, push callbacks, pull,
    resync, suspension, list diffs, deletion. The captures stay outside
    `tests/integration/wire/` and outside the repository; the table goes in
    the note.
  The result is the compatibility table: flow, direction, what 3.15.1
  does, what the release does, compatible or not, and for a break the
  `SECURITY` entry it traces to, if any.
- **Item 8, the number.** In the research note, in this order:
  - *the rule first*: a draft of what a patch, a minor and a major mean
    for this library, written before the release is classed against it.
    CLAUDE.md has only "patch vs minor"; `CONTRIBUTING.rst` has nothing;
  - *what the number tells whom*: the inventory's rows by how they meet an
    upgrader, against how consumers pin: none (`pip install -U`), `>=3.15`,
    `~=3.15`, `^3.15`, `<4`, exact. A refusal to start protects an
    upgrader; a silent or irreversible row does not, and those are named
    (unmarked actors cleaned at first sign-in, converted lists a 3.15
    process reads as empty, the first `append_once` on a list);
  - *the package and the protocol apart*: the compatibility table for
    peers, and what the announced protocol version (`1.0` to `1.5`) changes
    for a peer, which is nothing by itself;
  - *the promises in the tree*, three ways: fulfilled by this release
    (`docs/migration/v3.13.rst:1059` said the lookup fallbacks are "removed
    in the next major release", and this release removes them); made by
    this release (the tombstones at `actingweb/interface/app.py:529`,
    `actingweb/fanout.py:6`, `actingweb/handlers/callback_oauth.py:7`,
    which stay); and removals possible now (the deprecated `trust_approved`
    name at most; the old attribute-list reader cannot go, a rollback
    relies on it);
  - *precedent*: 3.7, 3.10, 3.11, 3.13, 3.14 and 3.15 each have a
    migration guide, so a breaking minor is what this project has done;
  - *what each answer costs here*: for 4.0, the guide's file and the
    eleven messages that spell its path, "3.16" in `actingweb/` (541
    lines), `docs/` (260), `tests/` (262), `CHANGELOG.rst`, CLAUDE.md,
    `thoughts/todo/` (53), a rule for a major in
    `.claude/workflow/release.md`, and whether the documentation links say
    `latest` or a version. Names outside this repository (Emm's branch and
    worktree) keep theirs.
- **Item 8, the two storage todos**, judged on the code as it is, not on
  their text:
  - `prop-list-key-prefix-scheme`, requirement by requirement: items larger
    than one row (closed for list items on DynamoDB by spanning, with a
    4 MiB default ceiling; **not** for a plain property, still one row);
    the partition's 1 MB Query page (unchanged; a cost, not a failure);
    payload under the span threshold (unchanged; does a lower
    `span_threshold` already give it); the attribute key delimiter (a
    colliding write now fails). Then: the PostgreSQL case argued by itself;
    which layouts "out" publishes that the scheme must later read beside
    its own (`{actor_id}$aux`, the attribute-list rows, the pre-3.16
    attribute reader); what holds while old and new versions write side by
    side; whether it adds an Alembic revision; and a measured threshold to
    replace "the next major" as its trigger. The 964 KB figure is from
    August: the owner is asked for the largest partition today. And what
    "in" costs in time: 32 `SECURITY` entries stay unreleased behind a
    design whose first choice is open, while the public demo runs 3.15.1.
  - `dynamodb-known-next`, item by item: item 3 (the `SubscriptionDiff`
    range key) is a key migration of the same kind as the scheme and rides
    with it or not at all; items 2 and 5 are behaviour changes without a
    migration; item 6 is judged against the creator-uniqueness table that
    now exists; items 1 and 7 are checked only for still describing the
    tree. An item that no longer does is corrected in the file.
- **The owner's decisions**, each with a recommendation: the outcome of
  each incompatible row; the number; the scheme; the register. Recorded
  under "Decisions Made", and the "Decisions Deferred" entries removed.
  - *Nothing in, either number*: Phases 2 to 4 follow. For 4.0, Phase 4
    does the rename, and the todos whose trigger is "the next major" get a
    trigger that still means something.
  - *The scheme or a register item in*: Phases 2 and 3 follow, since their
    tests are the net a key migration needs; Phase 4 is held, that work
    gets `/research_codebase` and `/create_plan`, and this plan comes back
    through `/update_plan` when it has merged. Phases 1 to 3 then go to
    `master` as a PR of their own first, so the other plan builds on them;
    that is an exception to one PR per plan and is the owner's to confirm
    with the decision.
  `/implement_plan` stops here: Phase 2 does not start before the
  decisions are recorded.
- `CONTRIBUTING.rst` and CLAUDE.md "Release": the versioning rule as
  decided (AC-23).

### New Tests, both unit and integration tests

- `tests/test_docs_api_consistency.py::test_release_notes_name_only_what_exists`
  — AC-2.
- No new wire row: the eight re-recorded files are the existing rows.

### Failure Scenarios

- A re-recorded file differs between runs - gate 3: shown identical on both
  backends before it is re-recorded; one that is not stays as it is and the
  bump's effect on it is put to the owner.
- An entry is "corrected" to what the code does when the code is the defect
  - a mismatch is first decided as a doc error or a regression; a
  regression is fixed in code, with the Full tier.
- The pair's tables are wiped by a test run - see "Rules for every phase";
  the pair is scripted from an empty store and finished first.
- A break is judged from the recordings alone, which are 3.16 against 3.16
  - the live pair is required, not optional.
- The number is decided on the size of the changelog - the note crosses
  what a consumer meets with how consumers pin, which is what the number
  tells them.
- The 3.15.1 side does not install on Python 3.11 today - then the pair's
  3.15 side is a worktree at the tag with `poetry install`, and the note
  says which was used.

### Verification

- [x] Item 1 (first half): every inventory row maps to a changelog entry;
  the `SECURITY` count before and after is in the note (32 and 32)
- [x] Item 6 (first half): the compatibility table has 18 cells and a
  class for each specification change and each changed recording; every
  break has the owner's outcome
- [x] Item 8: the note has the evidence, the three decisions are recorded
  with name and date, the two todos and their `INDEX.md` rows say what was
  decided, and the versioning rule is written
- [x] Emm's baseline on `master` is in the note, by name (five names)
- [x] `poetry run python tests/integration/verify_groups.py`
- [x] The Full tier (the harness and eight recordings changed)
- [x] The pair is stopped, its virtualenv and tables removed

### Notes from implementing (2026-11-18)

- **The record** is `thoughts/research/2026-11-18-3-16-release-validation.md`
  with two appendices beside it (`.inventory.md`, 301 rows; `.wire.md`, the
  49 specification lines, the recordings and fifteen candidates read from
  code).
- **The names test went further than planned.** It checks call-shaped,
  CamelCase, dotted `actingweb.` and `snake_case` literals against every
  identifier and string constant of the library and its examples, and a
  second test keeps its removed-names list honest. Seen red on
  `fit_full_state`, `evaluate_property_with_exclusions` (both never
  shipped) and `create_peer_trustee` (never existed).
- **Behaviour changed nowhere**: the only edit under `actingweb/` is the
  `Actor.modify` docstring. So Emm's suite is not re-run for this phase,
  and the Spec Delta stays empty.
- **`scripts/live_pair.py` also runs probes** (`drive --probes`) beyond the
  nine flows, and each was run with 3.15.1 as its own peer and the release
  as its own peer as controls. Without the controls three 3.15.1 defects
  would have read as breaks.
- **Guide edits made here** are only the three sentences that shared a
  wrong statement with a corrected changelog entry. The 93 inventory rows
  with no guide section, the stale guide paragraphs the inventories name
  (lines 461-463, 641-642, 2644-2645 at `da6de67`), the "Start here"
  warning that omits the reverse-lookup refusal, and the eleven
  specification-1.5 entries to re-mark **Breaking:** are Phase 4's.
- **For Phase 2**: no row is restored or kept, so `test_wire_v315.py` has
  only the "still accepted" forms to pin; the pair's captures name them.
  Not examined by the pair: what a peer on the other version is sent when
  an actor is deleted with its trusts still in place.
- **For Phase 4 (4.0.0)**: the rename sweep; the three tombstones' "next
  major" then means 5.0; `docs/migration/v3.13.rst:1059` is now true as
  written.
- **Reviewed by the outside voice** (codex and a fresh-context reader) on
  the changelog diff against the code: ten more sentences corrected (three
  functions given to the wrong owner, `ids_only` missing from
  `get_by_creator`, the guide's custom-backend list lacking what the
  changelog cites it for, an overlap between the minor and the major rule).
  The names test has a known limit it found: it checks each part of a
  dotted name against one set, so `Class.method` passes when both exist
  anywhere. Phase 4 tightens it with the guide tests.
- **After the owner's answers** two things were corrected and reported:
  only the attribute-list conversion is irreversible for an application
  that changed nothing, and a text value pushed to a 3.15.1 subscriber of
  one property is answered 400 (the replica is as empty as with a 3.15.1
  publisher). The note's last section lists what was deduced, not asked.
- **Emm's suite** now has five baseline names, not six, and Emm's adoption
  worktree sits on Emm's `main` (`c1be751c`) with its four edits
  uncommitted.

### Implementation Status: Complete

---

## Phase 2: the release read from Emm's side, and the wire decisions built (items 3, 4 and 6)

### Changes

- **An inventory of how Emm uses the library**, from `../actingweb_mcp` at
  `main` (read with `git show` or `git grep`; its checkout does not move)
  and from the adoption worktree's uncommitted diff: every import, every
  builder call and configuration value, every hook it registers, every
  direct use of `Actor`, `ActorInterface`, the trust, subscription,
  property-list and attribute APIs, every route of the library it calls or
  exposes, its deployment shape, and the names of its environment
  variables and IAM actions. Written to the research note.
- **Item 3, the maintainer's questions.** Walk the upgrade as Emm's
  maintainer, with only the changelog, the guide and `docs/`: for every row
  of the usage inventory that the release changes, is there a place that
  says what changes, what to do, in which order, and how to know it worked?
  Include the operational questions: which commands run before the new
  code starts and which after, what a rollback to 3.15.1 leaves behind,
  which new IAM actions or tables are needed, what the start-up checks say
  on a store that is not ready, what must happen to the peers it talks to.
  Each unanswered question is answered in the guide or the docs, as the
  generic pattern, in the section it belongs to; Phase 4 places it. The
  adoption worktree's diff is the cross-check: every change it needed that
  the guide does not name is a hole in the guide.
- **Item 4, coverage against use.** A matrix in the research note whose
  rows are Emm's call sites, not the cross product of features: each
  builder call, each lifecycle, callback, property and subscription hook
  by name, the action hooks as one mechanism, each distinct library method
  and imported name; about a hundred rows, thirty to forty of them in
  trust, subscriptions and the diffs that share memories. For each row,
  the test here that would fail if the behaviour broke.
  - A cell is filled by citing an existing test or wire row. A test that
    mocks the layer under test, or is pinned or skipped to one backend,
    does not fill a both-backends cell.
  - A new test is written only where the row has an Emm `file:line`, and
    cites it. The gaps a sample of ten already shows:
    `subscribe_to_peer_async`, `unsubscribe_from_peer`, `sync_peer_async`,
    `get_peer_capabilities`, an `AttributeListStore` read on a replica, and
    the list-diff fault cases that run on DynamoDB only.
  - At most fifteen new wire rows, only where the behaviour is on the wire
    and no existing row asserts it; the CI wire step's time is recorded.
  - A gap that needs a new kind of fixture (a wire application with
    `sync_callbacks=True`, as Emm runs in production) is put to the owner
    with its cost when it is found.
  - A gap whose new test fails is a defect, fixed before the tag.
- **Item 6, what the owner decided in Phase 1, built.** A restored or kept
  behaviour is implemented with its Spec Delta line. A restored behaviour
  that changes an existing recording takes ownership of that row in a
  commit before the phase commit, as in Phase 1.
- `tests/integration/test_wire_v315.py`, new: one scenario per row of the
  compatibility table marked "kept" or "restored", where the test plays
  the 3.15 peer and sends the request as the pair's captures show it,
  rebuilt by hand with the scenario's own ids and secrets. Rows `WV1` on.
  "Kept" includes a form the release accepts but no longer sends, so the
  file has tests even if no break was found.
- **Emm's suite** on the branch (gate 2): no failure the baseline of Phase
  1 did not have.

### New Tests, both unit and integration tests

- One per gap, named in the matrix next to the row it covers. Integration
  tests where Emm's use crosses two actors; both backends.
- `tests/integration/test_wire_v315.py` — AC-15.

### Failure Scenarios

- The inventory is taken from an old Emm - it is read at `main`, and the
  worktree that runs the suite is at `main` too.
- A new test passes on a behaviour Emm does not rely on in that shape -
  each new test cites the Emm call site it protects.
- A new wire row is not byte-stable - gate 3: identical over repeated runs
  on both backends before it joins the set.
- The matrix does not end - its rows are fixed when the inventory is
  written, and a row is closed by a citation; the phase ends when no row
  in the three areas is open or with the owner.

### Verification

- [ ] Item 3: the note lists the maintainer's questions, each with the
  location that answers it; none is open
- [ ] Item 4: every matrix row in trust, subscriptions and diffs names a
  test on both backends, or is a decision of the owner's
- [ ] Item 6: every "kept" or "restored" row has its test
- [ ] The Full tier; the wire step's CI time noted
- [ ] Emm's suite on this branch against the baseline
- [ ] No Emm production code touched; `docs/` and the changelog name no
  consumer

### Implementation Status: Not Started

---

## Phase 3: the demo, `actingwebdemo`, and agent discoverability (items 5 and 7)

### Changes

- **Item 5, `examples/demo/`.** Read it as a consumer would against the
  guide: every builder call, hook, template and environment variable uses
  the release's form; nothing relies on a removed option or a
  compatibility path; `examples/demo/README.md` and `.env.example` describe
  what a fresh start needs. Then start it in local QA mode per CLAUDE.md
  ("App") on a fresh database and walk the web UI with the throwaway
  account: create, sign in through the browser's Basic prompt, properties,
  trust, subscriptions, delete. Rough edges are library problems and are
  fixed in the library (owner rule). Afterwards: the actor deleted, the
  server stopped, the containers down, no `examples/demo/.env` left behind.
- `tests/integration/test_demo_first_run.py`, new: the README's sequence
  on an isolated store through Flask's test client. The first start stops
  with `UniqueCreatorNotReady`, `actingweb-unique-creators enable --apply`
  runs, the second start serves. Today every demo test stubs that check.
- **Item 5, `../actingwebdemo`.** What moving it takes, as a runbook in
  the research note, in the order it will be done:
  - first, its seven uncommitted files are read and taken as the starting
    point; a worktree of it is made from its `HEAD` with that diff applied.
    Nothing is committed there by this plan;
  - before the tag: in that worktree, `git submodule update --init`, then
    this branch fetched into `vendor/actingweb` from this repository's
    local path (the branch is not on GitHub before the PR), `poetry lock`,
    and its tests; its `serverless.yml`, `Dockerfile` and environment
    against the guide (new variables, tables, IAM actions, Python 3.14);
    what the deployed 3.15 data needs before the release starts on it (the
    commands, in order, and whether each can run while 3.15 serves);
  - after the pre-release is on TestPyPI: the submodule to the rc tag, the
    lock, its tests, and the `deploy.yml` dispatch with
    `pypi_index: testpypi`. These are the owner's steps, and the first
    thing after the tag: the changelog's `SECURITY` section is public
    while the public demo runs 3.15.1.
- **Item 7.** The three follow-ups:
  - *Context7* - held until the stable release is tagged and its docs are
    live (owner, 2026-11-15); the steps are in "After the tag".
  - *A real MCP client against `examples/mcp_quickstart.py`* - follow
    `docs/guides/mcp-quickstart.rst` as a fresh user and fix what does not
    match. The owner exports the two variables in their own shell and
    starts the server there, on a port other than 5000; the agent never
    reads the file they come from. That the example binds every interface
    on port 5000 is reviewed as a finding of this step. After the test:
    the redirect URI removed from the OAuth client, the local actor, MCP
    client registration and tables deleted, the MCP client's token cache
    cleared.
  - *The Agent Skill in a consumer repository* - the scratch repository
    with this branch installed by path, and one fresh agent session. The
    session starts the application it wrote, on a fresh database, by the
    skill's instructions. Two gaps are known before it runs and are fixed
    first: the skill's local run has no first-run step
    (`SKILL.md:84-88`), and it points at a migration from the removed GSI
    lookup (`SKILL.md:385-386`). The transcript is not committed; the
    outcome goes in the note; the directory is removed.
- **The content, against the release**: `skills/actingweb-app/SKILL.md`,
  `examples/*.py`, `examples/README.md`, the quickstart guides and
  `README.rst`. Each taught flow is run from a fresh database, and the
  names taught are checked against the inventory's removals, its
  deprecations (`trust_approved`) and the new required steps. That part
  needs nothing from the owner.
- `tests/test_docs_api_consistency.py`: a scan for removed names over
  `README.rst`, `skills/`, `examples/` and `docs/` outside `migration/`,
  seeded from the inventory, with an allow-list for the pages that name a
  removed option on purpose (`docs/quickstart/configuration.rst:501-502`,
  `docs/guides/subscriptions.rst:234-236`).

### New Tests, both unit and integration tests

- `tests/integration/test_demo_first_run.py::test_readme_first_run_sequence`
  — AC-11.
- `tests/test_docs_api_consistency.py::test_taught_names_are_not_removed`
  — AC-20.
- Tests for anything the walk, the quickstart or the skill run finds and
  fixes.

### Failure Scenarios

- The skill test runs against 3.15 - the library is installed from this
  branch by path; after the rc it is repeated with the library from
  TestPyPI and the skill from the repository at the rc tag (the skill is
  not in the wheel).
- A real secret reaches a file in the tree - see "Rules for every phase";
  the agent does not open the file the variables come from.
- The session passes because it inherits the owner's memory or tools - the
  note records what the session had access to.
- The `actingwebdemo` diff does not apply in a fresh worktree - then its
  tests are run in its checkout on its present branch, and the note says
  so.

### Verification

- [ ] Item 5: the first-run test passes, the walk is clean, the
  `actingwebdemo` runbook is complete and its tests pass against this
  branch
- [ ] Item 7: the quickstart and the skill run are done, or each names the
  resource it still waits on; the content is checked against the release
- [ ] The Full tier, if code or tests changed (they did if the first-run
  test was added)
- [ ] Emm's suite, if `actingweb/` changed since its last run
- [ ] Everything started is stopped; the redirect URI is removed

### Implementation Status: Not Started

---

## Phase 4: the guide and the changelog as a consumer reads them, and the bump (items 1, 2 and 6)

Not started while a decision of Phase 1 holds it.

### Changes

- **One place for the guide's name.** A constant for the reference to the
  migration guide, used by the eleven messages and the two operator tools
  that spell it today; with it, a documentation URL a `pip` user can open
  (the path alone is not on their disk). If the number is 4.0: the guide
  becomes `docs/migration/v4.0.rst`, the version strings in `actingweb/`,
  `docs/`, `tests/`, `CHANGELOG.rst`, CLAUDE.md and `thoughts/todo/` are
  swept, `.claude/workflow/release.md` gains its line for a major, and the
  tombstones' "next major" is retargeted. The sweep ends with a grep whose
  remaining hits are each explained (history, earlier guides, the data
  layout that is named "pre-3.16").
- **The guide, correct**: every statement about behaviour is checked per
  inventory row, not per sentence; the eight code samples are run; the
  command lines are held by a test. A block that shows the previous
  pattern is marked as such.
- **The guide, readable**, for a maintainer who reads it once with a
  deployment to upgrade:
  - "Start here" is a checklist in the order the steps are done: before
    the upgrade, the upgrade, after. It names every step that stops a
    start (today its short list omits three: creator uniqueness, the
    property-lookup backfill, the PostgreSQL revisions);
  - one table of the operator commands: `alembic upgrade head` (both
    revisions), `actingweb-mark-actors-vouched`,
    `actingweb-unique-creators` (report, resolve, enable,
    creator-to-email), `actingweb-property-lookup`, `actingweb-peer-state`,
    `actingweb-verify-property-lists --attributes`. For each: when,
    relative to the deploy; whether it is safe under live 3.15 traffic;
    who needs it; its cost on a large store and whether it can be paced;
    what it prints on success. And that the commands ship with the new
    version, so they run from an install that is not serving;
  - "Rolling back to 3.15.1": what is reversible, what is not (spanned
    items, `append_once`, converted attribute lists), and the step after
    which it is too late;
  - "Other versions beside this one", three cases kept apart: the
    consumer's own instances during a deploy; peer applications on 3.15;
    older and other peers (from the specification, not tested). For each:
    which side upgrades first, what fails and with which status, how long
    the mix may last. It says that a 3.15 peer stays exposed, on its own
    side, to what the `SECURITY` entries describe, whichever side upgrades
    first;
  - sections grouped by who is affected (every application, OAuth
    sign-in, SPA, MCP, peers and subscriptions, direct database or
    custom-backend users) with "skip this if" lines; the instruction
    before the reasoning; one term per concept ("the flag" names two
    settings today, and one setting has three spellings);
  - the heading levels repaired; titles that say what the section is for;
    every section an explicit label, and references by label, never by
    item number. **The seven titles that library messages quote keep their
    text**, or the message changes in the same commit.
- **`CHANGELOG.rst`, as it reads**: the opening `.. note::` with what stops
  a start, the commands, and the pointer to "Start here"; **Breaking:**
  entries first within `CHANGED`; one order within each category, by the
  guide's groups; a `CHANGED` entry that points at "Other versions beside
  this one".
- `docs/migration/index.rst` - the row describes the release as it is (it
  still says "a security release for the actor factory").
- The reference and guide pages the migration guide links to
  (`docs/quickstart/configuration.rst`, `docs/reference/`, `docs/guides/`) -
  corrected where the inventory shows they still describe 3.15.
- `tests/test_migration_guide.py`, new: every `actingweb-<command>` line
  in the guide names a console script of `pyproject.toml` and arguments
  its parser accepts; every guide section a library message quotes is a
  heading in the guide. It finds the guide through the constant, not by a
  file name of its own.
- **The todos.**
  - `thoughts/todo/emm-suite-against-master.md` is deleted with its row,
    after its run procedure is moved into the research note;
  - `thoughts/todo/INDEX.md`: "Planned for 3.16" is history once this plan
    merges and is removed; the discoverability row says what is left;
  - `thoughts/todo/ai-agent-discoverability-followups.md` keeps item 1
    (Context7) only;
  - `thoughts/todo/rc-pass-against-real-consumers.md`, new, with its row
    (section 3, waiting on the rc): `actingwebdemo` to the rc, Emm's pin
    on the rc, the skill with the library from TestPyPI. It points at the
    runbook in the research note.
- **The statement of readiness**, in the verification document: the eight
  items with their evidence, the open owner decisions if any, and the
  exact next step.
- **The bump**, the last commit, only when the statement says ready:
  `pyproject.toml` and `actingweb/__init__.py` to the release candidate,
  `Unreleased` renamed to its heading with a new empty `Unreleased` above
  it, `docs/requirements.txt` regenerated (the pre-commit hook does it),
  commit `Pre-release v<version>rc1`. The Full tier runs again after it.

### New Tests, both unit and integration tests

- `tests/test_migration_guide.py::test_guide_commands_exist_and_parse` —
  AC-5.
- `tests/test_migration_guide.py::test_quoted_guide_sections_are_headings`
  — AC-6.

### Failure Scenarios

- A section's content is lost in the restructure - the inventory's
  guide-section column is filled after it, not before.
- A renamed section orphans a library message - the test for AC-6; the
  docs build with `-W` does not catch it, because the references are prose.
- A reorder breaks a reference by item number - none survives; the docs
  build catches a broken label.
- The bump changes a recording - Phase 1 removed the version from them;
  the Full tier after the bump commit is the check (AC-22).
- 4.0 is chosen and a "3.16" survives in a message a consumer reads - the
  sweep's closing grep.

### Verification

- [ ] Items 1 and 2: the inventory's guide-section column has no empty
  cell where a consumer must act; "Start here" walked against the command
  table; the samples run
- [ ] Item 6: "Other versions beside this one" agrees with the table
- [ ] `docs/migration/index.rst` describes the release; each docs page the
  inventory showed describing 3.15 is corrected, listed in the note
- [ ] `grep -rn "v3.16.rst\|v4.0.rst" actingweb docs CHANGELOG.rst tests`:
  every quoted title is a heading
- [ ] The docs build from the Full tier (`sphinx-build -W`), with
  `.claude/**` excluded locally
- [ ] The Full tier, on both backends, on the final tree, after the bump
- [ ] Emm's suite on the final tree
- [ ] The todos as listed; `thoughts/README.md` re-read before recording
  the work as finished
- [ ] The verification document states "ready to tag" or lists what is not

### Implementation Status: Not Started

---

## After the tag

Steps this plan prepares and cannot finish, because each needs a published
build or live docs. They are the owner's to trigger. They do not hold the
plan open: the first three are
`thoughts/todo/rc-pass-against-real-consumers.md`, filed by Phase 4, the
last is item 1 of `thoughts/todo/ai-agent-discoverability-followups.md`.
The order is kept here.

- [ ] **First, after the rc is on TestPyPI:** `actingwebdemo` to the rc
  (Phase 3's runbook: submodule, lock, tests, the `deploy.yml` dispatch with
  `pypi_index: testpypi`).
- [ ] **After the rc:** Emm's pin on the rc, in Emm's own adoption work.
- [ ] **After the rc:** the Agent Skill test repeated with the library from
  TestPyPI and the skill from the repository at the rc tag, if the owner
  wants it confirmed there.
- [ ] **After the stable release is tagged and its docs are live on Read
  the Docs:** `actingweb` into Context7, through the `context7-admin` MCP
  server (connected 2026-11-15; teamspace "Personal", no libraries yet). Not
  before: adding it earlier indexes the 3.15 docs. In order, each confirmed
  by the owner:
  1. `add_library` for the repository, then `get_library` with `wait: true`
     until the parse is complete;
  2. `claim_library`, which returns a `context7.json`; read it for anything
     the owner wants private, commit it through a `docs/context7-claim` PR;
     after it merges, `claim_library` with `verify: true`;
  3. read `get_library_benchmarks` and `get_library_suggestions` once; a
     real documentation gap they show becomes a todo;
  4. delete item 1 from
     `thoughts/todo/ai-agent-discoverability-followups.md` (and the file and
     its `INDEX.md` row, if it was the last).

---

## Evaluation Notes

Evaluated 2026-11-18 by `/update_plan`: five evaluators on the refreshed
text, then the outside voice on their findings and on the first form of
the version question (then a "Phase 0").

**Outside voice:** codex (`codex exec -s read-only`, outside the sandbox),
then a fresh-context reviewer.

The plan is about 1,000 lines before this section, well over the guideline
of 600. The preamble is 460 of them (the decisions, what exists, the
criteria and traceability, the rules) and Phase 1 another 180. Phase 1 is
the candidate for a plan of its own: it ends in decisions that can hold
Phase 4. It is kept here because the owner asked for one plan with few
phases and its evidence is what the other phases read; item 6 has a
threshold that splits it off ("more than three rows").

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Architecture, Tests | `tests/integration/wire/WT1.two_hosts.json:208` `"version": "3.15.1"`, compared by `_wire.py:1036` `if expected != text:` — the bump changes eight recordings the plan said it never re-records | User decided: normalise once (Phase 1) |
| 2 | Architecture, Tests | `verify_groups.py:202-204` "no commit can make its own phase an owner of a row it re-records" — one commit per phase cannot re-record | Folded: the ownership commit in Phase 1; the same rule in Phase 2 |
| 3 | Architecture, Tests | `_wire.py:6-9` "Everything here runs in the pytest process" — a `WV` row cannot be a recording of two versions | Folded: `test_wire_v315.py` plays the 3.15 peer; `WG20-WG39` reserved |
| 4 | Architecture | `v3.15.1:examples/demo/application.py:275` `app.run(host="0.0.0.0", port=5000, debug=True)` — the pair has no application or recorder on the 3.15 side | Folded: `scripts/live_pair.py`, 3.15.1 from PyPI, loopback |
| 5 | Architecture, Outside | `v3.15.1:actingweb/config.py:355` `self.aw_version = "1.0"` — the 1.4-to-1.5 diff does not describe 3.15.1, and the version cannot gate anything | Folded: the specification class is a claim, the pair is the source; no gating on a version |
| 6 | Architecture | `git diff --stat actingweb-3-16-adoption main`: 215 files — Emm's suite would prove the release against an old Emm | User decided: Emm's `main`, new baseline |
| 7 | Architecture | `git diff --stat e4c3015 da6de67 -- actingweb/`: three files — "the last run is `master`'s library code" was false | Folded: corrected; the new baseline is the first run on `master` |
| 8 | Architecture, Feasibility, Usability, Outside | plan (old Phase 2) "Each unanswered question is fixed in the guide" — the guide was certified in Phase 1, then edited | User decided: discovery first, the guide last |
| 9 | Architecture | `.claude/workflow/release.md:20` "After the tag ... set the plan's `status: done`" — against "done when Phase 4 lands"; `/release` also opens a PR and tags | Folded: the bump is the version files and heading only; the decision says which rule wins |
| 10 | Architecture | `../actingwebdemo/.gitmodules:4-5` `shallow = true` — the branch's head is not on GitHub | Folded: fetched from the local path (Phase 3) |
| 11 | Architecture | `thoughts/todo/emm-suite-against-master.md:95` "the PostgreSQL lane needs the environment's preview server" — exists only in a todo the plan deletes | Folded: moved to the note first; `INDEX.md` section removed; Emm's pin in the new todo |
| 12 | Architecture | `pyproject.toml:27-29` `packages = [{ include = "actingweb" }]` — the skill is not in the wheel | Folded: reworded |
| 13 | Security, Outside | `CHANGELOG.rst:204-206` "Callbacks were accepted without authentication" (one of nine) — restore or keep-both can reopen it | User decided: such a row can only be accepted |
| 14 | Security | `tests/integration/conftest.py:618` `host="0.0.0.0"` — pair and harness bind wide | Folded: "Rules for every phase" |
| 15 | Security | `examples/mcp_quickstart.py:49-50` `os.getenv("OAUTH_CLIENT_ID", "")`, `:97` `host="0.0.0.0"` — the `.env` is never read; a secret-holding server on every interface | Folded: Phase 3's steps and cleanup. The production client is kept (owner, 2026-11-15); a throwaway client would remove the exposure and remains the owner's option |
| 16 | Security | plan "the log in the research note" — nothing bounded what notes capture | Folded: "Rules for every phase" |
| 17 | Security | `thoughts/research/2026-11-07-emm-suite-against-master.md:109` — an Emm inventory in a public repository has precedent; values would be new | Folded: names only, no `.env*` |
| 18 | Security | `CHANGELOG.rst:896` "Released in v3.15.1 and earlier" marks only two entries — the cleanup could delete an advisory | Folded: `SECURITY` entries are never deleted or moved |
| 19 | Security | `.github/workflows/publish-to-pypi.yml:207-222` puts the section in the release body while the public demo runs 3.15.1 | Folded: `actingwebdemo` is the first step after the tag. Whether the stable tag waits on it is the owner's at the tag |
| 20 | Feasibility, Tests | plan "no empty cell for trust, subscriptions and diffs" — no row definition; a sample of ten call sites found about half without a real two-actor test | Folded: rows are Emm's call sites, with the rules and the cap; a new fixture kind goes to the owner |
| 21 | Feasibility | `rows.toml:18-19` "One file serves both backends" — the pair's matrix was unstated | Folded: 18 cells, DynamoDB |
| 22 | Feasibility | plan verification lists three Emm runs and three Full tiers | Folded: Emm's suite when `actingweb/` changed; the stop rule written in |
| 23 | Feasibility, Tests | `tests/test_docs_api_consistency.py:24` excludes `DOCS_ROOT / "migration"` — nothing checks the guide; a names check and a command check are cheap | Folded: three tests (AC-2, AC-5, AC-20) |
| 24 | Feasibility | `.github/workflows/tests.yml:328` `timeout-minutes: 10` — 109 reserved ids against a step near its limit | Folded: at most fifteen new rows |
| 25 | Feasibility, Tests | `Makefile:59` `down -v` — a Full-tier run wipes the pair's and the walk's stores | Folded: "Rules for every phase" |
| 26 | Usability | `docs/migration/v3.16.rst:19-21` "Most applications need to check only the first three items, item 11..." — the list omits three steps that stop a start | Folded: Phase 4 |
| 27 | Usability | `docs/migration/v3.16.rst:1351` "Upgrade order, with both flags on" is the only ordered sequence | Folded: the command table |
| 28 | Usability | `docs/migration/v3.16.rst:2069` "plan a rollback before lists have converted" — rollback exists per section only | Folded: a rollback section and AC-7 |
| 29 | Usability | `docs/migration/v3.16.rst:1587-1588` a top-level heading swallows fourteen sections | Folded: Phase 4 |
| 30 | Usability, Tests | `actingweb/config.py:65` `see docs/migration/v3.16.rst "Callback delivery".` — titles are a shipped interface | Folded: titles kept, labels added, AC-6 and its test |
| 31 | Usability | `CHANGELOG.rst:1193` the first **Breaking:** lead is 215 lines into `CHANGED` | Folded: note, order. Sub-headings rejected: they change the contract |
| 32 | Usability | plan "a 'Peers on 3.15' section" in `CHANGELOG.rst` — not one of the five categories | Folded: a `CHANGED` entry |
| 33 | Usability, Tests | plan AC-1, 2, 3, 5, 7, 10, 12, 14 joined two results or could not fail | Folded: the list rewritten (it was written in this update) |
| 34 | Usability | `docs/migration/v3.16.rst:1438`, `:222`, `:232` — three mixed-version cases folded into one | Folded: AC-16 and the section's three cases |
| 35 | Usability | `skills/actingweb-app/SKILL.md:84-88` no first-run step; `:385-386` the removed GSI migration — a search for removed names finds neither | Folded: Phase 3, AC-19 |
| 36 | Tests | `tests/test_version_consistency.py:64` `assert changelog_version == init_version == pyproject_version` — the pre-merge check for the bump exists | Folded: AC-21 names it |
| 37 | Tests | `tests/test_demo_example.py:36-39` stubs `missing_enforcement` — the README's sequence is never run | Folded: `test_demo_first_run.py`, AC-11 |
| 38 | Tests | plan (old AC-6) "fails the baseline's six tests and no other" — one is date-dependent | Folded: AC-10's wording |
| 39 | Tests | plan Spec Delta had four headings for five specs | Folded |
| 40 | Outside | plan (old Phase 0) "what breaks with no opt-out, from the changelog's 33 **Breaking:** leads" — the number was decided before its evidence | User decided: at the end of Phase 1 |
| 41 | Outside | `actingweb/interface/app.py:522` "Removed in 3.16; always raises"; `docs/migration/v3.13.rst:1059` "removed in the next major release" — the promises were read backwards | Folded: the three-way split; no removals in this plan |
| 42 | Outside | `docs/migration/v3.16.rst:52-60`, `:2069-2071`, `:1533-1536` — the silent and irreversible changes were not in the evidence | Folded: the inventory's column and the pin table |
| 43 | Outside | plan (old Phase 0) "this plan stops here" — the wire table and the tests do not depend on storage keys | Folded: only Phase 4 is held |
| 44 | Outside | `actingweb/property_list.py:353` (`$aux`), `thoughts/todo/whole-list-rewrite-atomicity.md:14` — "out" publishes layouts the scheme must read later; no PostgreSQL line | Folded: the storage evidence |
| 45 | Outside | `actingweb/config.py:55` "see docs/migration/v3.16.rst" — eleven literals, and a path a `pip` user does not have | Folded: one constant with a URL (Phase 4) |
| 46 | Outside (codex) | `pyproject.toml:13-25` "Production/Stable" with no policy — the rule should exist before the release is classed | Folded: the rule first; AC-23 |
| 47 | Outside (codex) | `README.rst:165-167` links to `/en/latest/` | Folded: part of the number's evidence |
| 48 | Outside (codex) | a narrow 3.15.x security release first, then 4.0 | Rejected: the fix itself adds a builder, a hook and a start-up refusal (`docs/migration/index.rst:35-48`), which the contract does not allow in a patch |

**Unverified notes** (concerns that could not cite a line):

- Whether Read the Docs already serves `latest` from `master`. If it does,
  the guide's title-derived anchors are public, and "nothing named 3.16 has
  been published" is not quite true.
- No measured time for the Full tier this month; Phase 1's run records it.
- Whether `actingweb==3.15.1` and its locked dependencies install cleanly
  on Python 3.11 today (Phase 1 has the fallback).
- Whether the REST subscription handler shares its code with
  `subscribe_to_peer_async`; if it does, two of the sampled gaps are
  narrower.
- Whether the six `wait=` sites in `actor.py` already take the blocking
  path with `sync_callbacks` off, which decides the size of the fixture
  question in Phase 2.
- Whether a localhost redirect URI on the deployed OAuth client is
  exploitable depends on the provider and the client type, not inspected.
- Where `mcp-remote` or Claude Desktop keeps its tokens on disk.
- The largest partition today is a figure from a 3.15 store; whether it
  describes the partition after the 3.16 conversions is not known.
- `dynamodb-known-next` was added to the version question after the
  outside voice had started; it was reviewed by headings only.
