# TODO: Postgres per-actor attribute DELETE intermittently not persisting under parallel CI

**Date:** 2026-06-15
**Status:** **Symptom gone, root cause never found.** Both leading hypotheses
had their proximate mechanism removed by unrelated work (#115, #117); the
quarantine was lifted on 2026-08-15 and the postgres matrix has been green on
every run since, across four PRs, with zero reruns. That is evidence the
symptom is gone, **not** evidence of a diagnosis — so this file stays rather
than being deleted, and `ACTINGWEB_PG_DELETE_DIAGNOSTICS` stays on in CI to
name the mechanism if it ever returns. Delete this file after a few weeks of
continued green. See "What changed
under this todo" below before doing any further investigation: the code this
document describes is not the code that runs today.
**Severity:** Medium (test-infra reliability; no confirmed production impact, but the
mechanism *could* drop writes in production under concurrency)
**Origin:** PR #105 (Apple Sign-In / native OIDC / GitHub mobile parity)
**Owner:** unassigned

## Summary

Under the **parallel postgresql CI matrix** (`pytest -n 4 --dist loadgroup` over the
full `tests/` suite), a per-actor attribute `DELETE` performed during OAuth2-client /
trust deletion intermittently does **not persist**: the client row remains and
`OAuth2ClientManager.list_clients()` still returns it, so
`tests/integration/test_trust_oauth_integration.py::TestTrustDeletionOnClientDeletion`
fails with `assert 1 == 0`.

It reproduces **only** in CI under concurrent load. The same tests pass on the
**dynamodb** matrix and in **all local postgres runs** (sequential, `-n 4`
integration-only, and full-suite `-n 4 --dist loadgroup` → 2293 passed).

Two of these assertions are currently **quarantined on postgresql only** (skipif),
documented in the test file and `CHANGELOG.rst`. They still run on dynamodb. This
TODO tracks removing that quarantine once the root cause is fixed.

## Quarantine to remove once fixed

`tests/integration/test_trust_oauth_integration.py`:
- `_PG_DELETE_FLAKE` / `_PG_DELETE_FLAKE_REASON` module constants.
- `@pytest.mark.skipif(_PG_DELETE_FLAKE, ...)` on:
  - `TestTrustDeletionOnClientDeletion::test_deleting_trust_deletes_client_and_revokes_tokens`
  - `TestTrustDeletionOnClientDeletion::test_delete_client_succeeds_when_global_index_missing`

Delete those three things to re-enable; CI on the branch will then verify the fix.

## Evidence gathered (PR #105 investigation)

1. **The failing assertion** is `assert len(client_manager.list_clients()) == 0`
   (`test_trust_oauth_integration.py`). `list_clients()` reads the per-actor
   `mcp_clients` attribute bucket (`client_registry.list_clients_for_actor`).

2. **`delete_client` runs to completion** — CI logs
   `Deleted OAuth2 client <id> as part of trust deletion` (`trust.py:98`). After the
   PR's `delete_client` robustness fix it also logs
   `missing from global index; deleting from actor <id>'s bucket using the
   caller-provided actor_id` — i.e. it *does* reach the per-actor
   `bucket.delete_attr(name=client_id)` call. The client still remains afterward.

3. **Not eventual consistency.** A 5-second poll on the post-deletion state did not
   change the result — the row never disappears within the test. (The poll was
   reverted; it was the wrong remedy.)

4. **Not the global client index.** `_load_client` reading the shared
   `OAUTH2_SYSTEM_ACTOR:CLIENT_INDEX_BUCKET` was missing the entry, which originally
   made `delete_client` bail early. That was fixed (deletion now proceeds on the
   caller-supplied `actor_id`). The DELETE still doesn't persist — so the index miss
   was a *second* symptom of the same underlying problem, not the cause.

5. **Reproduced in a minimal single-actor test.**
   `test_delete_client_succeeds_when_global_index_missing` creates one client,
   deletes the global index entry, calls `registry.delete_client(client_id,
   actor_id=actor.id)`, and asserts `list_clients() == 0`. It **passes locally**,
   **fails in CI** — so it is not cross-test data contention on the client bucket;
   the actor's own `DELETE` simply doesn't take effect in CI.

6. **Recurring postgres error in the CI logs:**
   `ERROR: duplicate key value violates unique constraint "property_lookup_pkey"`.
   This aborts the transaction on whatever connection raised it. On a **pooled**
   connection (`psycopg_pool.ConnectionPool`, `db/postgresql/connection.py`) a
   subsequent operation reusing a connection left in a bad state could fail to
   commit. This is the leading hypothesis for the DELETE not persisting.
   - **Unresolved:** we could not locate the INSERT that raises this. The two
     `INSERT INTO property_lookup` sites are `property.py:303` (has
     `ON CONFLICT (property_name, value) DO NOTHING` — should not raise) and
     `property_lookup.py:86` (plain INSERT, **no** `ON CONFLICT`) — but the latter
     (`DbPropertyLookup.create()`) appears to have **no callers** (only `.get()` is
     used). Find the real source of the duplicate-key error.

7. **Schema-isolation angle (also unconfirmed).** CI uses per-worker schema
   isolation via `PG_DB_PREFIX`; `_configure_connection` (`connection.py:91`) sets
   `search_path` once per physical connection. Local runs that pass did **not** set
   `PG_DB_PREFIX`. If a pooled connection's `search_path` were ever lost/reset, a
   `DELETE` could hit the wrong schema (no-op) while a `SELECT` hits the right one —
   matching the symptom. Worth ruling in/out.

8. **Environment delta:** CI = Python 3.11, fresh containerized postgres, per-worker
   schema; local = Python 3.14, long-lived container, `public` schema. Could not
   reproduce locally; full-suite postgres parallel runs take ~1h wall in the dev
   sandbox, which blocked local iteration.

## What changed under this todo (found 2026-08-15)

The evidence above was gathered against the code as it stood on 2026-06-15.
Two of the three ranked hypotheses have had their proximate mechanism removed
since, by work that was not aimed at this bug and did not update this file.

1. **The unaccounted-for `property_lookup_pkey` INSERT is gone.** Evidence
   item 6 could not locate the statement raising the duplicate-key error, and
   named `property_lookup.py:86` (`DbPropertyLookup.create()`, a plain INSERT
   with no `ON CONFLICT`) as the only candidate, apparently callerless. That
   statement gained `ON CONFLICT (property_name, value)` — both the
   `DO UPDATE` and `DO NOTHING` branches — in **#115**
   (`89f1b0b`, the v3.13.0 DynamoDB-scalability PR), two months after this was
   filed. All three `INSERT INTO property_lookup` sites are now idempotent.
   Hypothesis 1 depends on *something* aborting a pooled connection's
   transaction; the only identified candidate for that no longer exists.
2. **The pool no longer serves a mix of schemas.** Hypothesis 2 was
   `search_path` instability under per-worker isolation. `get_pool()` now
   tracks the schema a pool was built for (`_pool_schema`) and rebuilds when
   `PG_DB_PREFIX`/`PG_DB_SCHEMA` changes, instead of holding connections
   configured against different schemas and handing them out load-dependently
   (`connection.py`, added in **#117**). Test fixtures set `PG_DB_PREFIX`
   in-process, which is exactly the mutation that produced the mixed pool.

Also worth knowing before re-reading the evidence: `pool.connection()` rolls
back on exception exit, and every `with get_connection()` block in
`attribute.py` has its `try` *outside* the `with`, so a swallowed exception
cannot return a connection to the pool mid-transaction. The "audit every
`with get_connection()` block" step below was written before that was checked;
it is done for `attribute.py`.

**Action taken 2026-08-15:** quarantine lifted and instrumentation added, on
one branch, rather than instrumenting a bug that may already be fixed. If the
postgres matrix is green across several runs the flake dies with evidence; if
it is not, `ACTINGWEB_PG_DELETE_DIAGNOSTICS=1` (on in CI) prints `PG_DELETE_DIAG`
lines naming the mechanism in the first failing run. That is strictly more
information than either half alone.

## Hypotheses (ranked)

1. **Pooled-connection transaction contamination.** The `property_lookup_pkey`
   error (or another aborted statement) leaves a pooled connection in a state where
   the next `DELETE` + `conn.commit()` does not persist. Investigate connection
   reset/`check` behavior and whether any code path swallows a DB exception without
   `rollback()` before the connection returns to the pool.
2. **`search_path` instability on pooled connections** under per-worker schema
   isolation → DELETE targets the wrong schema.
3. **An unidentified non-idempotent `INSERT INTO property_lookup`** (source of the
   duplicate-key error) racing under concurrency.

## Suggested investigation steps

**Decided 2026-08-14** (owner walkthrough): do the first step now, on one branch
shared with `thoughts/todo/ci-postgres-parallel-flakiness.md`. Same CI matrix,
same conditions, and that todo's process-global psycopg pool is hypothesis 1
here — one instrumentation pass should collect evidence for both.

- [x] **Done 2026-08-15.** Reproduce in CI deterministically: debug in the
      `delete_attr` path (`db/postgresql/attribute.py`) logging `cur.rowcount`
      after the `DELETE` and `current_schema()` / `search_path` for the
      connection. Confirm whether the DELETE matches 0 rows (wrong schema /
      wrong key) or matches but doesn't commit. Shipped as an opt-in
      (`ACTINGWEB_PG_DELETE_DIAGNOSTICS`) rather than temporary debug, with a
      post-commit re-read on a *fresh* connection — that third data point is
      what actually separates "did not commit" from "reader is in a different
      schema than the writer", which rowcount alone cannot.
- [x] **Done, before this todo was picked up.** Find what raises
      `property_lookup_pkey`; make that INSERT idempotent (`ON CONFLICT`) — see
      "What changed under this todo". Auditing every `with get_connection()`
      block for `rollback()` is done for `attribute.py`; the other backend
      modules follow the same try-outside-the-`with` shape but were not walked
      line by line.
- [ ] Consider pinning `search_path` at the protocol level (conninfo
      `options=-c search_path=<schema>`) instead of (or in addition to) the
      per-connection `configure` hook, so it cannot drift.
- [ ] Evaluate `psycopg_pool` `reset=`/`check=` configuration so a connection that
      experienced an error is reset before reuse.
- [ ] Once fixed, remove the quarantine (above) and confirm green on the postgres CI
      matrix across several runs.

## Related

- `actingweb/oauth2_server/client_registry.py` — `delete_client`, `list_clients_for_actor`,
  `_load_client` / global index (`CLIENT_INDEX_BUCKET`).
- `actingweb/db/postgresql/attribute.py` — `set_attr` (delete branch), `get_bucket`.
- `actingweb/db/postgresql/connection.py` — pool + `_configure_connection`.
- `actingweb/db/postgresql/property.py` / `property_lookup.py` — `property_lookup` writes.
- `actingweb/trust.py:76` — `Trust.delete()` → `registry.delete_client(...)` (logs
  success regardless of return value; consider checking the return value).
