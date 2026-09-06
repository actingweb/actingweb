# Postgres parallel CI: the watchdog bounds the symptom, the flakiness remains

**Origin:** `thoughts/research/2026-06-15-ci-postgres-test-hang.md`
§"Follow-up (not done here)" — read it before re-deriving the root cause or
re-trying the several approaches that did not help. A watchdog now bounds the
hang (it used to reach ~99% of the suite, go silent, and be cancelled at the
20-minute wall with no diagnostics), so a hang fails fast and says something.
The three causes below are untouched.

This is **test-infrastructure reliability**, not correctness.

1. **Stabilise `test_oauth2_client_manager.py::TestOAuth2ClientCreation` under
   parallel execution.** It combines a fixed `creator="user@example.com"` with
   two process-global singletons — the psycopg pool and
   `trust_type_registry._registry`.
2. **Speed up the per-worker `alembic upgrade head` session fixture.** Every
   xdist worker runs a subprocess through the full migration chain.
3. **Decide whether `--dist loadgroup` is actually required**, or whether
   disabling rerunfailures' xdist socket machinery under parallel runs is
   viable instead.

Follow-ups 1 and 3 both touch pooled-connection behaviour under
`-n 4 --dist loadgroup`; `ACTINGWEB_PG_DELETE_DIAGNOSTICS` is still enabled in
`tests.yml` and is the nearest existing instrumentation.
