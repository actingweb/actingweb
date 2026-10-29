# Investigation: a fault reading the OAuth2 state key replaced the key

**Date:** 2026-10-29
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 8e8b4df (base; the fix is uncommitted with the PR 1 work)
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md

## Symptom

When the system actor's property read faulted while the OAuth2 state manager
was being built, the library generated a new state encryption key and stored
it over the existing one. Every MCP OAuth2 authorization in flight, on every
instance, then failed to decrypt its state. Expected: a fault leaves the
stored key alone, and the request fails and retries. Found in the second
verification of the fault contract
(`thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-2.md`,
Issue J2).

## Root Cause

`actingweb/oauth2_server/state_manager.py` `_get_or_create_encryption_key`:
- The read `getattr(sys_actor.property, "oauth2_state_encryption_key", None)`
  sits inside `except Exception as e: logger.debug(...)`.
- On any exception it falls through to `Fernet.generate_key()` and
  `sys_actor.property.oauth2_state_encryption_key = key_str`.
- `DbProperty.get` has raised `DbError` on a backend fault since before 3.16
  (`actingweb/db/postgresql/property.py` and the DynamoDB twin, "property
  read"), so a throttle read as "no key stored yet".

Two sibling catches had the same shape:
- The key store's `except Exception`: a faulted write returned an in-memory
  key that no other instance shares.
- The outer `except Exception`: a fault loading the system actor generated a
  non-persistent key.

The method runs once, when the global state manager is built
(`get_oauth2_state_manager`), so the overwritten key spread to every later
request.

## Hypotheses Rejected

None. The first hypothesis was confirmed by the regression test before the
change:
- The stored key differed after a key-read fault (`assert b'Ge5z...' ==
  b'3Ats...'` failed).
- No `DbError` was raised on the system-actor load fault.

## Fix

`actingweb/oauth2_server/state_manager.py`: `except DbError: raise` ahead of
the three catch-alls:
- the key read;
- the key store;
- the outer system-actor block.

A fault now fails the manager's construction, the singleton stays unset, and
the next request builds it again. The two handlers with no database access
(the config key decode, the state decrypt) carry the fault guard's
`# folds DbError:` marker.

Reuse: no new primitive. The fix uses the same `DbError` re-raise as the
rest of the fault contract.

Release: no route, hook, kwarg, response field, signature or config option
changes, so this would be patch-level on its own. It ships in 3.16 with the
fault contract and has a FIXED entry there.

## Evidence

- Regression tests: `tests/test_oauth2_state_key_read_fault.py`:
  - `test_a_key_read_fault_raises_and_keeps_the_stored_key` asserts
    `pytest.raises(DbError)` and that the stored key is unchanged;
  - `test_a_system_actor_load_fault_raises_instead_of_an_in_memory_key`
    asserts `pytest.raises(DbError)`;
  - `test_without_a_fault_the_stored_key_is_reused` is the control.
  Before the fix: 2 failed, 1 passed. After: 3 passed on DynamoDB, and 3
  passed on PostgreSQL.
- Full suite: run with the iteration batch that carries this fix (see the
  plan's Iterations entry).
- Scope lock: self-check. Paths: `actingweb/oauth2_server/state_manager.py`,
  `tests/test_oauth2_state_key_read_fault.py`, `CHANGELOG.rst`.
- Fresh reproduction: the first test reproduces the original scenario (a
  stored key, then a manager built under a key-read fault), and passes now.

## Related

- The outer fallback still logs a generated key in plaintext
  ("Store this key persistently: %s") for non-DB errors. It is older than
  3.16 and out of scope here; it is filed in
  `thoughts/todo/adoption-fault-and-hygiene-followups.md`.
- Same fault class as the 3.16 fault-contract work. `tests/test_db_fault_guard.py`
  flags this file's catch-alls, so the class cannot come back unnoticed.

## Status

DONE
