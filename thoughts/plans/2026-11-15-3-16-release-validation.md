---
status: proposed
---

# Implementation Plan: validating 3.16 before its tag

**Date:** 2026-11-15
**Branch:** `release/3.16.0-release-validation`, one PR, one commit per phase (written on `release/3.16.0-email-as-creator-at-write-time`)

First draft, written by hand from the owner's seven-item list (2026-11-15).
It has not been through `/create_plan`'s evaluation or an outside voice; run
`/update_plan` on it before work starts, once `spec-1-5` has its final shape.

## Overview

3.16 reaches consumers in one pin change: 22 merges to `master` since
`v3.15.1` with two plans still to land before this one, 233 changelog entries under `Unreleased` and a 2,000-line
migration guide, both written plan by plan and never read as one document.
This plan is the last one before the tag. It reads the release as a consumer
will meet it, closes what that reading finds, and ends with a statement that
3.16 is ready to tag, or with the list of owner decisions that stand between
it and the tag.

## Implementation Order

Last of the 3.16 plans. The order, the dependencies and the gates are in
[`thoughts/todo/INDEX.md`](../todo/INDEX.md), "Planned for 3.16"; that copy
wins.

**This plan** starts when `spec-1-5` has merged, because every item below
judges the release as a whole: the changelog and the guide are not complete
before it, the specification still says 1.4, and the 3.15-to-3.16 comparison
(item 6) has nothing to compare until the 1.5 changes exist. It uses the wire
recordings (`tests/integration/wire/`) as the record of what 3.16 puts on the
wire, the Emm worktrees of
[`emm-suite-against-master`](../todo/emm-suite-against-master.md) for the
consumer runs, and it takes over the three items of
[`ai-agent-discoverability-followups`](../todo/ai-agent-discoverability-followups.md).

## The seven items, and where each is done

The owner's list, numbered as given. Each phase's verification names the
items it closes, so that none is lost in the grouping.

| # | Item | Phase |
| --- | --- | --- |
| 1 | Review every change in 3.16; clean up and correct the changelog; everything a consumer needs is in the migration guide | 1 |
| 2 | Review the migration guide against the implementation; make it readable and easy to follow for a consumer | 1 |
| 3 | Review how `../actingweb_mcp` (Emm AI) uses the library; does the guide, with the docs, answer every question its maintainer will have when migrating | 2 |
| 4 | Compare this repository's test coverage with Emm's uses of the library and name the gaps; in particular trust relationships, subscriptions, and the diff mechanisms that share memories | 2 |
| 5 | Is the local demo (`examples/demo/`) migrated properly to 3.16; prepare `../actingwebdemo` to use 3.16 once it is on TestPyPI | 3 |
| 6 | Protocol compatibility between 3.15 (what `actingwebdemo` runs) and 3.16; identify breaking changes; decide what to do about each | 3 |
| 7 | The remaining agent-discoverability work: review it and include what can be included in 3.16 | 4 |

## Decisions Made

- **Findings are fixed in this plan** - a wrong changelog entry, a hole in
  the guide, a missing test or a demo that was not migrated is corrected in
  the phase that finds it, not filed as a todo (owner rule). A finding that
  is a design question goes to the owner as a decision; the tag waits on it.
- **The docs stay consumer-generic** - the Emm reading (items 3 and 4)
  produces questions and gaps; what goes into `docs/` and `CHANGELOG.rst` is
  the pattern, with no Emm or `actingweb_mcp` specifics (owner rule
  2026-11-15). The Emm-specific answers are a research note,
  `thoughts/research/<date>-3-16-release-validation.md`.
- **No Emm production code** - Emm is read, and its suite is run in its
  adoption worktree; nothing is written into Emm beyond what the test harness
  needs (owner rule 2026-11-07). What its maintainer has to do is a list in
  the research note.
- **The plan stops at "ready to tag"** - the tag is the owner's, after
  the PR merges (the bump is the decision below). The `actingwebdemo`
  pin moves only after the pre-release is on TestPyPI, so that step is
  prepared here and carried out after the tag.
- **A break between 3.15 and 3.16 on the wire is not accepted silently** -
  the aim is none. Each one found gets one of three outcomes, chosen by the
  owner: restore the 3.15 behaviour, keep both behaviours behind what the
  peer advertises (`/meta/actingweb/supported`, `/meta/actingweb/version`),
  or accept it with a **Breaking:** changelog lead, a guide section and a
  statement of which side must upgrade first.

- **This plan's PR carries the bump, as `Pre-release v3.16.0rc1`** (owner,
  2026-11-15) - it is the last PR before the tag, and CLAUDE.md puts the
  bump and the changelog rename in the release PR itself. An rc, not a
  beta: when this plan ends, 3.16 is feature-complete and validated, so the
  build is the release unless the TestPyPI pass (the `actingwebdemo`
  deployment, Emm's pin, the skill on the published wheel) finds something;
  a finding is fixed and tagged `rc2`. It also matches `v3.15.0rc1`. The
  stable release is then the second, version-only PR that
  `.claude/workflow/release.md` describes. The bump is Phase 4's last
  change; the tag itself stays the owner's.

- **What the owner supplies for item 7** (owner, 2026-11-15):
  - *Context7*: the owner has an account; the Context7 Admin MCP server
    (`context7-admin`, user scope) is the way in. The submission is made
    after the 3.16 docs are live on Read the Docs, and confirmed by the
    owner like any other change there.
  - *The MCP quickstart*: the OAuth2 client of the `actingwebdemo`
    deployment is reused; the owner adds the quickstart's local callback as
    an authorised redirect URI and puts the id and secret in a local,
    unstaged `.env`. The MCP client (`mcp-remote` or Claude Desktop) runs on
    the owner's machine. The demo application itself is not the target: it
    runs with `.with_mcp(enable=False)`.
  - *The Agent Skill*: the scratch repository is an empty directory this
    plan creates (`git init`, the library installed, nothing else); the
    owner starts one fresh agent session in it and gives it the task.
    `actingwebdemo` cannot be that repository: its `CLAUDE.md` and
    `vendor/actingweb` would make the task succeed without the skill.

## What We're NOT Doing

- New features or behaviour changes beyond what a finding requires - this
  plan validates 3.16, it does not extend it.
- Emm's migration itself - its branch `actingweb-3-16-adoption` is Emm's
  work; this plan only checks that the guide lets its maintainer do it.
- Deploying `demo.actingweb.io` - the deployment is `actingwebdemo`'s
  `deploy.yml`, run by the owner.
- The other todos in `thoughts/todo/` - only the discoverability follow-ups
  are in scope.
- Pushing `docs/3-16-rollup-records` or anything the security-records rule
  holds back.

## What Already Exists

- `CHANGELOG.rst`, `Unreleased` - 233 entries, written per plan. Reused;
  Phase 1 edits it in place.
- `docs/migration/v3.16.rst` - 2,039 lines, a "Start here" section followed by one
  section per change. Reused; Phase 1 edits it in place.
- `tests/integration/wire/` and `rows.toml` - the recorded exchanges of two
  test apps shaped like Emm, on one host and on two. The evidence base for
  item 6; `verify_groups.py` checks the row assignments.
- `thoughts/research/2026-11-07-emm-suite-against-master.md` and
  `thoughts/todo/emm-suite-against-master.md` - the baseline of Emm's suite
  against 3.16 (five failing tests, all documented changes Emm adopts), the
  per-plan runs, and how a run is done. Reused for items 3 and 4.
- `thoughts/research/2026-01-18-library-extraction-candidates-from-actingweb-mcp.md`
  and `thoughts/plans/2025-10-03-actingweb-mcp-protection-tests.md` - earlier
  inventories of what Emm uses and a plan for tests to protect it (January 2026 and October 2025, so
  both predate most of what Emm does today). Phase 2 reads them as a
  starting point and checks them against Emm as it is now.
- `examples/demo/` - the application behind `demo.actingweb.io`, imported by
  this repository's tests.
- `../actingwebdemo` - deploys `examples/demo/` from a `vendor/actingweb`
  submodule (`branch = master`, currently at `v3.15.1`) with a path
  dependency on it; `deploy.yml` requires the submodule commit to be a
  release tag and verifies a pre-release on TestPyPI. So "preparing" it is
  the submodule, the lock, its own tests, its environment and its data, not
  a version string.
- `docs/protocol/actingweb-spec.rst` - version 1.4 until `spec-1-5` lands.
- `thoughts/plans/2026-08-22-ai-agent-discoverability.md` (`status: done`),
  `skills/actingweb-app/SKILL.md`, `examples/mcp_quickstart.py`,
  `docs/guides/mcp-quickstart.rst` - what the discoverability work shipped.

## Phase 1: the changelog and the migration guide (items 1 and 2)

### Changes

- **An inventory first.** List every PR merged to `master` since `v3.15.1`
  (`git log v3.15.1..master --first-parent`) and, for each, its consumer-
  visible changes: routes, status codes, wire shapes, hook names and
  arguments, public signatures, configuration options, environment
  variables, operator commands, database migrations, start-up checks. The
  inventory is a table in the research note; the rest of the phase is
  checked against it.
- `CHANGELOG.rst`, `Unreleased` - read as one section against the inventory:
  - every inventory row has an entry, and every entry describes the final
    behaviour (a later plan often changed what an earlier entry says);
  - entries that describe the same change from two plans are merged, and an
    entry for something added and removed inside 3.16 is deleted;
  - categories and order follow the contract (`SECURITY`, `REMOVED`,
    `CHANGED`, `ADDED`, `FIXED`); every consumer-visible shift has its
    **Behavior change:** sentence and every wire or API change its
    **Breaking:** lead;
  - the section opens with the `.. note::` pointing at the guide;
  - no Emm or `actingweb_mcp` specifics.
- `docs/migration/v3.16.rst` - two passes:
  - *correctness*: every statement about behaviour, every code sample,
    command line, option name and error text is checked against the tree
    (samples are run, commands are run with `--help` and against a test
    store); every inventory row that needs consumer action has a section,
    and "Start here" names it;
  - *readability*: restructured for a maintainer who reads it once, top to
    bottom, with a deployment to upgrade. A "Start here" that is a checklist
    in the order the steps are done (before the upgrade, the upgrade itself,
    operator commands, after); sections grouped by who is affected (every
    application, applications with OAuth sign-in, SPA, MCP, peers and
    subscriptions, direct database or custom-backend users) with "skip this
    if" lines; the reasoning behind a change after the instruction, not
    before it; one term per concept.
- `docs/migration/index.rst` - the 3.16 row matches the guide's final scope.
- The reference and guide pages the migration guide links to
  (`docs/quickstart/configuration.rst`, `docs/reference/`, `docs/guides/`) -
  corrected where the inventory shows they still describe 3.15.

### New Tests, both unit and integration tests

- None planned. A code sample in the guide that cannot be run as written
  gets a test only if it shows an untested public path; that is then a
  finding of item 4's kind and is recorded there.

### Failure Scenarios

- The guide is restructured and a section's content is lost - covered by
  checking the inventory rows against the new guide after the restructure,
  not only before.
- An entry is "corrected" to what the code does when the code is the defect
  - a mismatch between an entry and the tree is first decided as a doc error
  or a regression; a regression is fixed in code, with the Full tier.

### Verification

- [ ] Item 1: every inventory row maps to a changelog entry and, where a
  consumer must act, to a guide section; the table in the research note
  shows the mapping with no empty cell
- [ ] Item 2: every sample and command in the guide was run; the guide's
  "Start here" is a complete ordered checklist
- [ ] The docs build from the Full tier (`sphinx-build -W`), with
  `.claude/**` excluded locally
- [ ] The fast tier, if any docstring or code changed

### Implementation Status: Not Started

---

## Phase 2: the release read from Emm's side (items 3 and 4)

### Changes

- **An inventory of how Emm uses the library**, from `../actingweb_mcp` on
  its main branch and on `actingweb-3-16-adoption`: every import from
  `actingweb`, every `ActingWebApp` builder call and configuration value,
  every hook it registers, every direct use of `Actor`, `ActorInterface`,
  the trust, subscription, property-list and attribute APIs, every route of
  the library it calls or exposes, its deployment shape (Lambda, sync
  callbacks, DynamoDB in production, PostgreSQL locally), and its
  environment variables and IAM actions. Written to the research note.
- **Item 3, the maintainer's questions.** Walk the upgrade as Emm's
  maintainer, with only the changelog, the guide and `docs/`: for every row
  of the usage inventory that 3.16 changes, is there a place that says what
  changes, what to do, in which order, and how to know it worked? Include
  the operational questions: which commands run before the new code starts
  and which after, what a rollback to 3.15.1 leaves behind, which new IAM
  actions or tables are needed, what the start-up checks say on a store that
  is not ready, what must happen to the peers Emm talks to. Each unanswered
  question is fixed in the guide or the docs, as the generic pattern. The
  adoption branch's diff is the cross-check: every change it needed that the
  guide does not name is a hole in the guide.
- **Item 4, coverage against use.** For every row of the usage inventory,
  name the tests in this repository that would fail if that behaviour
  broke, on both backends. Three areas get a full matrix rather than a
  spot check:
  - *trust*: creation, approval and verification in both directions,
    relationship types and the permissions they carry, grant overrides,
    deletion from either side, the hooks and their arguments;
  - *subscriptions*: creation on a trust, targets and subtargets,
    granularity, callbacks (sync, as Emm runs them), sequence gaps,
    suspension and resume, resync, deletion, a peer that is down;
  - *the diffs that share memories*: what a write to a property, a property
    list and an attribute list puts in a diff (scalar, nested, list append,
    update, delete, spanned items), how the grant filters it, how the
    subscriber applies it to its replica, pull as well as push.
  A row with no test, or a test on one backend only, or a test that asserts
  less than Emm relies on, is a gap. Gaps are closed here with tests, and
  with wire rows where the behaviour is on the wire; a gap whose test fails
  is a defect to fix before the tag.
- `tests/integration/wire/rows.toml` - a `[reserved]` id range for this
  plan's slug, and each new row with `owners` naming this plan and phase.
  This plan adds rows and re-records none of the existing ones (gate 5); a
  restored 3.15 behaviour in Phase 3 that changes an existing recording is
  named in that row's `owners` and `reason` before it is re-recorded.
- **Emm's suite** on this plan's branch, as gate 2 requires, after the tests
  are in: the baseline's failures and nothing else.

### New Tests, both unit and integration tests

- One per gap, named in the research note's matrix next to the row it
  covers. Integration tests where Emm's use crosses two actors; both
  backends.

### Failure Scenarios

- The inventory is taken from Emm's main branch and misses what the
  adoption branch had to change - both are read, and the adoption diff is
  the cross-check.
- A new test passes on a behaviour Emm does not actually rely on in that
  shape - each new test cites the Emm call site it protects.
- A new wire row is not byte-stable - gate 3 applies: it is shown identical
  over repeated runs on both backends before it joins the regression set.

### Verification

- [ ] Item 3: the research note lists the maintainer's questions, each with
  the guide or docs location that answers it; none is open
- [ ] Item 4: the usage-to-test matrix has no empty cell for trust,
  subscriptions and diffs, on either backend
- [ ] The Full tier (tests were added)
- [ ] Emm's suite on this branch: no failure the baseline did not have
- [ ] No Emm production code touched; `docs/` and the changelog name no
  consumer

### Implementation Status: Not Started

---

## Phase 3: the demo, `actingwebdemo`, and the wire between 3.15 and 3.16 (items 5 and 6)

### Changes

- **Item 5, `examples/demo/`.** Read it against the guide's "Start here" as
  if it were a consumer: every builder call, hook, template and environment
  variable uses the 3.16 form; nothing relies on a removed option or a
  compatibility path; `examples/demo/README.md` and `.env.example` describe
  what a fresh start needs (the readiness checks, `actingweb-unique-creators`,
  `actingweb-property-lookup`). Then start it in local QA mode per CLAUDE.md
  ("App") on a fresh database and walk the web UI with the throwaway account:
  create, sign in, properties, trust, subscriptions, delete. Rough edges are
  library problems and are fixed in the library (owner rule).
- **Item 5, `../actingwebdemo`.** Establish what moving it to 3.16 takes and
  write it down as a runbook in the research note, in the order it will be
  done:
  - before the tag: its own tests against `vendor/actingweb` at this
    branch's head (in a worktree of it, so its checkout does not move); its
    `serverless.yml`, `Dockerfile` and environment against the guide (new
    variables, tables, IAM actions, Python 3.14); what the deployed 3.15
    data needs before 3.16 starts on it (the migration commands, in order,
    and whether each can run while 3.15 serves);
  - after the pre-release is on TestPyPI: the submodule to the rc tag,
    `poetry lock`, its tests, and the `deploy.yml` dispatch with
    `pypi_index: testpypi`. These are the owner's steps; the plan prepares
    the branch and the commands, it does not deploy.
- **Item 6, protocol compatibility.** Three sources, in this order:
  - *the specification*: every normative difference between 1.4 and 1.5,
    classed as additive, a clarification of what 3.15 already did, or a
    change in what a conforming peer sends or accepts;
  - *the recordings*: every wire row whose recording changed since the
    baseline (`git log` on `tests/integration/wire/`), classed the same way;
  - *a live pair*: a 3.15.1 application and a 3.16 application (a worktree
    at `v3.15.1`, each with its own database and port) put through the
    peer flows in both directions - trust creation and approval, permission
    exchange, subscription creation, push callbacks, pull, resync,
    suspension, list diffs, deletion - recording what each side sends and
    how the other answers.
  The result is a table: flow, direction, 3.15 behaviour, 3.16 behaviour,
  compatible or not. For each incompatible row the owner chooses one of the
  three outcomes in "Decisions Made"; the choice is implemented here. The
  order of deployment follows from the table and goes into the guide: may a
  3.16 application talk to 3.15 peers indefinitely, and the reverse.
- `docs/migration/v3.16.rst` and `CHANGELOG.rst` - a "Peers on 3.15" section
  stating exactly what holds between the two versions.

### New Tests, both unit and integration tests

- A test per compatibility path that is kept or restored (a 3.16 actor
  receiving what 3.15 sends, from the live pair's captures), so the
  statement in the guide is held by the suite.
- Tests for anything the demo walk finds and fixes.

### Failure Scenarios

- The live pair shares a port or a database prefix with a test run - one
  run at a time; own ports and prefixes, not `:5555`, not `:5000`.
- A break is judged from the recordings alone, which are 3.16 against 3.16
  - the live pair is required for item 6, not optional.
- The demo walk needs a browser - through the browser QA agent or offstage,
  never a headed browser on the owner's screen.

### Verification

- [ ] Item 5: the demo starts on a fresh 3.16 store and the walk is clean;
  the `actingwebdemo` runbook is complete and its tests pass against this
  branch
- [ ] Item 6: the compatibility table has a decision for every incompatible
  row, each implemented or written into the changelog and guide
- [ ] The Full tier
- [ ] Emm's suite, if library code changed since Phase 2's run

### Implementation Status: Not Started

---

## Phase 4: agent discoverability, and the statement of readiness (item 7)

### Changes

- **Item 7.** The three follow-ups, each with what it needs from the owner:
  - *Context7 submission* - held until stable 3.16 is tagged and its docs
    are live on Read the Docs (owner, 2026-11-15), so it is not done in this
    phase: the steps are in "After the tag" below. The claim adds a
    `context7.json` to the repository.
  - *A real MCP client against `examples/mcp_quickstart.py`* - a real
    OAuth2 client id and secret and an MCP client (Claude Desktop, Cursor or
    `mcp-remote`). Follow `docs/guides/mcp-quickstart.rst` as a fresh user
    on 3.16 and fix what does not match. This one belongs in 3.16: the
    quickstart is the first thing an agent-led consumer runs, and 3.16
    changed the MCP OAuth server and the start-up checks under it.
  - *The Agent Skill in a consumer repository* - a throwaway repository
    with only the library installed (this branch by path; repeated on the rc
    from TestPyPI after the tag, like the `actingwebdemo` pin) and a fresh
    agent session. Confirms `skills/actingweb-app/SKILL.md` activates and is
    followed; and, new with 3.16, that what it teaches is still right.
- Whatever the resources allow or not, the content is reviewed here against
  3.16: `skills/actingweb-app/SKILL.md`, `examples/*.py`, `examples/README.md`,
  the quickstart guides and `README.rst` teach the 3.16 API and nothing
  removed. That part needs nothing from the owner.
- `thoughts/todo/ai-agent-discoverability-followups.md` - items done are
  removed; the file and its `INDEX.md` row are deleted if all three are.
- **The statement of readiness**, in the verification document: the seven
  items with their evidence, the open owner decisions if any, and the exact
  next step.
- **The bump**, last, through `/release`: `pyproject.toml` and
  `actingweb/__init__.py` to `3.16.0rc1`, `Unreleased` renamed to
  `v3.16.0rc1: <date>` with a new empty `Unreleased` above it, commit
  `Pre-release v3.16.0rc1`. Only when the statement says ready.

### New Tests, both unit and integration tests

- Tests for fixes to the quickstart or the examples, where a path was
  untested.

### Failure Scenarios

- The skill test is run before an rc exists and so tests 3.15 - it runs
  against this branch installed by path, and is repeated on the rc if the
  owner wants the published wheel confirmed.
- Real credentials - the owner supplies them in `.env` files that are never
  staged; the browser agent types no real account's credentials.

### Verification

- [ ] Item 7: each of the three follow-ups is done, or names the resource
  it still waits on; the skill, examples and quickstarts are checked
  against 3.16
- [ ] The Full tier, on both backends, on the final tree
- [ ] Emm's suite on the final tree
- [ ] `thoughts/todo/emm-suite-against-master.md` deleted with its row (this
  is the last 3.16 plan)
- [ ] The verification document states "ready to tag" or lists what is not

### Implementation Status: Not Started

---

## After the tag

Steps this plan prepares and cannot finish, because each needs a published
build or live docs. They are the owner's to trigger; the verification
document lists them as open until done, and the plan is not `done` while
one is.

- [ ] **After `v3.16.0rc1` is on TestPyPI:** `actingwebdemo` to the rc
  (Phase 3's runbook: submodule, lock, tests, the `deploy.yml` dispatch with
  `pypi_index: testpypi`).
- [ ] **After the rc:** the Agent Skill test repeated on the published
  wheel, if the owner wants it confirmed there.
- [ ] **After stable `v3.16.0` is tagged and its docs are live on Read the
  Docs:** `actingweb` into Context7, through the `context7-admin` MCP server
  (connected 2026-11-15; teamspace "Personal", no libraries yet). Not
  before: adding it earlier indexes the 3.15 docs. In order, each confirmed
  by the owner:
  1. `add_library` for the repository, then `get_library` with `wait: true`
     until the parse is complete;
  2. `claim_library`, which returns a `context7.json`; commit it through a
     `docs/context7-claim` PR; after it merges, `claim_library` with
     `verify: true`;
  3. read `get_library_benchmarks` and `get_library_suggestions` once; a
     real documentation gap they show becomes a todo;
  4. delete item 1 from
     `thoughts/todo/ai-agent-discoverability-followups.md` (and the file and
     its `INDEX.md` row, if it was the last).

---

## Evaluation Notes

Not evaluated. `/update_plan` runs the evaluators and the outside voice
before this plan is approved; the points they should press on are whether
Phase 2's matrix is bounded enough to finish, and whether item 6's live pair
can be built from a `v3.15.1` worktree on both backends.
