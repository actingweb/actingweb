# TODO: Postgres per-actor attribute DELETE intermittently not persisting under parallel CI

**Date:** 2026-06-15
**Status:** Open — root cause not yet found
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

- [ ] Reproduce in CI deterministically: add temporary debug to `delete_attr`
      (`db/postgresql/attribute.py`) logging `cur.rowcount` after the `DELETE` and
      `current_schema()` / `search_path` for the connection. Confirm whether the
      DELETE matches 0 rows (wrong schema / wrong key) or matches but doesn't commit.
- [ ] Find what raises `property_lookup_pkey`; make that INSERT idempotent
      (`ON CONFLICT`), and audit every `with get_connection()` block to ensure a DB
      error triggers `rollback()` before the connection is returned to the pool.
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
