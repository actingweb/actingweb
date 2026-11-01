# Verification: One mode after the 3.16 upgrade, and the two consumer primitives

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Plan:** thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md (all four phases)
**Research:** thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** release/3.16.0-single-mode-and-consumer-primitives

Per-phase notes: `...-phase-1.md`, `...-phase-2.md`, `...-phase-3.md` in this directory. This note covers the whole plan.

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page; the SPA endpoints are JSON. The manual demo walks in the plan's Verification lists (Phase 1 demo start and unmark, Phase 2 quickstart run, Phase 3 `curl`, Phase 4 `curl`) were not run; tests cover the same requests.
- **Second opinion:** the fresh-context reviewer twice (Phase 1, then Phases 2 to 4). Codex cannot start in the sandbox. Every finding is listed with its fate in the per-phase notes and the plan.
- ruff check, ruff format --check, pyright: 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: 51 groups documented.
- Full tier, DynamoDB (`pytest tests/ -n auto --dist loadgroup`): 5104 passed, 43 skipped, twice against one store.
- Full tier, PostgreSQL (after `alembic upgrade head`): 4918 passed, 229 skipped, twice.
- Alembic `upgrade head`, `downgrade -1`, `upgrade head`: clean (Phase 1).
- `sphinx-build -W`: pass.
- The compose containers were unreachable after the Phase 1 runs (the OrbStack VM slept), so the later runs used DynamoDB Local 2.x and a PostgreSQL started from `pixeltable-pgserver` binaries on other ports.

## Phase Verification

All four phases VERIFIED; deviations are in the plan's Implementation Summary.

## Success Measures

| Measure | Target | Observable? | Evidence | Status |
| --- | --- | --- | --- | --- |
| Deployments that start with a lookup table or `creators` table that is not ready | Zero; `check_ready()` raises | Yes | `tests/test_property_lookup_readiness.py`, `tests/integration/test_property_lookup_readiness.py`, `tests/integration/test_unique_creator_default.py` | Met in tests; **post-ship** for real deployments (baseline: the 3.15 startup only logged) |
| Registry growth the consumer measured | Registrations expire | No | Deferred by the owner to its own plan (D5) | Not met by design; todo rewritten |
| The consumer's 401 predicate | A 401 on refresh carries `X-ActingWeb-Error` | Yes | `tests/test_spa_error_codes.py` (Flask and FastAPI, CORS exposed) | Met in tests; **post-ship** for the consumer's gateway half |
| An atomic create the consumer can use for its unlock ask | `create_attr_if_absent` with a nonce gives one winner | Yes | `tests/test_create_attr_if_absent.py` on both backends | Met |

## Remaining Tasks

- [ ] The consumer's halves (API Gateway exposed headers, `isApi401`, the unlock-ask rewrite) follow the pin.
- [ ] Registration expiry design (`thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md`).
- [ ] Open items filed from the reviews: `property-lookup-stale-owner-and-races.md`, `unique-creator-direct-config-auto-create.md`.
- [ ] The PR (opened after this phase, per the plan), then the release PR.

## Overall Assessment

The release delivers one reverse-lookup mechanism and uniqueness on by default, each refusing to start with the command that makes the store ready, plus the two consumer primitives. The reviews found a false-ready empty-store probe, a reusable backfill checkpoint, orphan rows, an import-time config default in a second handler, and several operator traps; all are fixed and tested except the two filed todos. The first-ship measures (zero unready deployments, the consumer's sign-out predicate) can only be confirmed after release, and the registry-growth measure waits for the deferred plan.
