# Postgres parallel CI: the watchdog bounds the symptom, the flakiness remains

**Origin:** `thoughts/research/2026-06-15-ci-postgres-test-hang.md`
§"Follow-up (not done here)".
**Status:** Open. The mitigation shipped; none of the three follow-ups did.

## What already shipped

The `Tests (Python 3.11, postgresql)` job used to reach ~99% of the suite in
~2.5 min, go silent, and be cancelled at the 20-minute `timeout-minutes` wall
**with no diagnostics**. A watchdog now bounds that, so a hang fails fast and
says something. Root cause and the several attempts that did *not* help are in
the research doc — read it before re-deriving them.

**Decided 2026-08-14** (owner walkthrough): instrument now, on one branch shared
with the DELETE todo below rather than waiting for the next hang.

**Done 2026-08-15, and it collected for the DELETE todo only.** The shared
branch shipped `ACTINGWEB_PG_DELETE_DIAGNOSTICS` and lifted that todo's
quarantine. Nothing here was instrumented: follow-up 1's process-global
singletons were the shared surface, and the pool half of that surface was
already rebuilt in #117 (see the DELETE todo's "What changed under this todo"),
leaving `trust_type_registry._registry` and the fixed `creator` as the only
untouched part of it. The three follow-ups below all remain open.

## The three follow-ups

1. **Stabilise `test_oauth2_client_manager.py::TestOAuth2ClientCreation` under
   parallel execution.** It combines a fixed `creator="user@example.com"` with
   two process-global singletons — the psycopg pool and
   `trust_type_registry._registry`.
2. **Speed up the per-worker `alembic upgrade head` session fixture.** Every
   xdist worker runs a subprocess through the full migration chain.
3. **Decide whether `--dist loadgroup` is actually required**, or whether
   disabling rerunfailures' xdist socket machinery under parallel runs is
   viable instead.

## Why this is not the same item as the DELETE todo

`thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md` is a
**correctness** question — a per-actor attribute `DELETE` that intermittently
does not persist, with a mechanism that could drop writes in production. This
one is **test-infrastructure reliability** only. Same date, same CI matrix, same
`-n 4 --dist loadgroup` conditions, different defect.

They are worth reading together anyway: follow-up 1's process-global singletons
and follow-up 3's distribution-mode question both touch the pooled-connection
behaviour that is the DELETE bug's leading hypothesis. If one investigation
instruments the postgres CI matrix, it should collect for both.
