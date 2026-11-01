# Verification: Phase 2 of the single-mode and consumer-primitives plan

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Plan:** thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md (Phase 2 only; the plan stays `active`, so no `verified:` link)
**Research:** thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** release/3.16.0-single-mode-and-consumer-primitives

## Automated Check Results

- **Browser QA:** N/A (no UI).
- **Second opinion:** the fresh-context reviewer, once over Phases 2 to 4 together (Codex cannot start in the sandbox). Findings and their fate below.
- This phase's tree (lint, types, the unit tier on DynamoDB Local): ruff, ruff format, pyright pass; 3861 passed.
- The final tree of all four phases, the Full tier on both backends, run twice against one store as the plan's audit asks: DynamoDB 5103 and 5104 passed; PostgreSQL 4918 passed twice. Sphinx `-W` passes.
- The database containers were unreachable for most of the session (the OrbStack VM slept), so the Full tier ran against a local DynamoDB Local 2.x jar and a local PostgreSQL started from the `pixeltable-pgserver` binaries. They are the same engines the compose file starts; the compose file itself was not used for these runs.

## Phase Verification

### Phase 2 - VERIFIED, with additions

Changes match the plan. Tests: the default pinned on `Config` and `ActingWebApp`; the opt-out reads nothing; the refusal text (long form, short "no actors yet" form); no `DescribeTable` and a missing table still reported as absence; `BaseHandler` without config; the first-run sequence on an isolated store on both backends.

**Deviations:** the audit found more fixed-creator test sites than the plan named; `MCPHandler` had its own import-time default; `no_actors()` ignores system actors. All recorded in the plan.

## Issues Found

| Finding (review) | Status |
| --- | --- |
| A default-uniqueness `Config` that skips `check_ready()` auto-creates an empty `creators` table | Accepted in the plan's failure scenarios; filed as `thoughts/todo/unique-creator-direct-config-auto-create.md` |
| `MCPHandler` kept an import-time `Config(mcp=True)` default | Fixed |
| `no_actors` swallowed scan faults silently | Fixed (logged) |

## Remaining Tasks

- [ ] Phases 3 and 4 (see their notes).
- [ ] The manual quickstart run from the plan's Phase 2 Verification list was not run; the integration test covers the same refusal and the second start on both backends.

## Overall Assessment

The default is on, the first-run sequence is the same for every deployment, and the readiness check costs one consistent read. The hazard that remains is code that builds a default `Config` and creates actors without `check_ready()`, which the migration guide names and a todo tracks.
