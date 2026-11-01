# Verification: Phase 3 of the single-mode and consumer-primitives plan

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Plan:** thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md (Phase 3 only; the plan stays `active`, so no `verified:` link)
**Research:** thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** release/3.16.0-single-mode-and-consumer-primitives

## Automated Check Results

- **Browser QA:** N/A (no UI; the SPA endpoints are JSON).
- **Second opinion:** the fresh-context reviewer, once over Phases 2 to 4 (Codex cannot start in the sandbox).
- This phase's tree (lint, types, the unit tier on DynamoDB Local): ruff, ruff format, pyright pass; 3898 passed.
- The final tree of all four phases, Full tier on both backends, twice: DynamoDB 5103 and 5104 passed; PostgreSQL 4918 twice. Sphinx `-W` passes. See the Phase 2 verification for how the databases were provided.
- The plan's manual `curl` against the demo was not run; the same request is a test on both integrations (`tests/test_spa_error_codes.py`).

## Phase Verification

### Phase 3 - VERIFIED

`create_attr_if_absent`: first wins, second loses with the row unchanged; an expired row is replaced with its new TTL; a live TTL row and a permanent row are not; another bucket's row is untouched; the name is stored; a missing argument raises `ValueError`; a fault raises `DbError`; a JSON-equal row after a lost condition is a win and a different row is a loss; a fault while reading back raises; a vanished winner is retried; two threads with a nonce have exactly one winner and with identical data both win; the `Attributes` wrapper caches a win and reads the winner's row through after a loss. D10 is pinned for the two older methods. The error codes: unknown refresh token, bogus grant type, invalid JSON, a store fault, the fault handler on `/oauth/spa/token` and `/oauth/token`, the FastAPI session retrieve and the passphrase grant outside devtest, each on Flask and FastAPI, with `Access-Control-Expose-Headers` checked.

## Issues Found

| Finding (review) | Status |
| --- | --- |
| A lost write whose winner vanished before the read-back was reported as lost | Fixed, tested (DynamoDB), same logic on PostgreSQL |
| `Attributes` caches the caller's data and timestamp after a retry-win | Left as the plan specifies; recorded in the plan notes |
| Logout answers from the OAuth2 endpoints handler carry no code | Documented in the SPA guide; out of the plan's scope |

## Remaining Tasks

- [ ] Phase 4.

## Overall Assessment

The two consumer primitives exist with the contracts the consumer asked for, and the second one is observable from the client: a 401 either carries the header or it does not. The consumer's own halves (the gateway's exposed headers, `isApi401`) follow the pin and are not part of this change.
