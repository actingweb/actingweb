# Verification: Phase 1 of the single-mode and consumer-primitives plan

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Plan:** thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md (Phase 1 only; the plan stays `active`, so no `verified:` link)
**Research:** thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** release/3.16.0-single-mode-and-consumer-primitives

## Automated Check Results

- **Browser QA:** N/A (no UI in this phase). The manual demo walk in the plan's Verification list was not run; the integration tests cover the same start and refuse paths on both backends.
- **Second opinion:** the fresh-context reviewer (Codex cannot start inside the sandbox). 12 findings.
- ruff check, ruff format --check, pyright: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass (51 groups documented).
- Full tier on DynamoDB (`make test-all-parallel`): 4999 passed, 43 skipped.
- Full tier on PostgreSQL (`alembic upgrade head`, then the same pytest line): 4816 passed, 226 skipped.
- Sphinx `-W`: pass.
- Alembic `upgrade head`, `downgrade -1`, `upgrade head` against the test container: pass.
- `actingweb-property-lookup --help` lists the four subcommands; the script shim maps flags (tested).

## Phase Verification

### Phase 1 - VERIFIED, with deviations

Changes match the plan except the deviations below. Tests: readiness (fake and real backends), command (both backends), D15 fault injection (both backends), the integration start/refuse/backfill path, the constructor and tombstone refusals.

**Deviations (also in the plan's Phase 1 notes):**
- "Empty store" ignores `_actingweb_*` rows, because the system actors write properties before the probe runs.
- D15 on PostgreSQL needed no source change.
- The test seam is `tests/_lookup_probe.py`, loaded by both conftests.
- `ensure_table(PropertyLookupV2)` added to the transactional write.

## Previous Verification

None.

## Issues Found (outside-voice review) and their fate

| Finding | Status |
| --- | --- |
| Probe read a populated DynamoDB store as empty (`limit` caps the total, not the page) | Fixed (`page_size`), tested |
| Checkpoint left after a collision run could skip rows; not keyed by names or table | Fixed (signature, removed unless a fault), tested |
| Refusal message did not tell the operator the CLI ignores `with_indexed_properties()` | Fixed (message and guide name `--properties`) |
| DynamoDB backfill wrote rows for orphaned property rows | Fixed (actor existence check, counted), tested |
| PostgreSQL `record_configured` delete-then-insert race | Fixed (one fixed-key upsert; `value` column in the migration), tested |
| `report --properties` could print a pass for a partial set | Fixed (verdict covers the configured set), tested |
| Empty indexed list records no set | Documented in the migration guide |
| `mark-complete` accepts a partial backfill | Warning added; not a refusal because shared values make lookups fewer than properties |
| Runtime role needs `dynamodb:Scan` for the probe | Documented |
| Stale lookup owner is a permanent "collision"; same-actor stale-handle race; one over-long value aborts the PostgreSQL pass | Open, filed as `thoughts/todo/property-lookup-stale-owner-and-races.md` |

## Remaining Tasks

- [ ] Phases 2 to 4.
- [ ] The manual demo check from the plan's Phase 1 Verification list.

## Overall Assessment

Phase 1 delivers its headline measure for the lookup half: a store with data and unmarked names refuses to start with the command that fixes it, a fresh store marks itself, and both are pinned on both backends. The review found one critical false-ready path and several operator traps; all but three lower-severity items are fixed and tested. The manual demo walk was not run, and the stale-owner and race items are open by design.
