# Investigation: on PostgreSQL the 3.16 adoption rule read a backend fault as "nothing there"

**Date:** 2026-10-27
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; the fix is uncommitted in the working tree with the rest of the 3.16 work)
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md

## Symptom

`thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory.md`
reported this as Issues 1, 2, 3 and 8. It was found by reading the code; no
production incident was involved. On PostgreSQL a caught database read error
during a sign-in could:

- wipe a legitimate, vouched user's actor (passphrase rotated; trusts,
  subscriptions and sessions removed);
- mark a squatted actor vouched with its trusts still in place;
- leave a squatter's SPA session alive after an adoption logged as complete.

The backfill script could also overwrite a `factory` marker on a read fault.
The expected behaviour was that the sign-in fails closed and the next one
retries, which is what happens on DynamoDB.

## Root Cause

The adoption rule was built on DynamoDB's contract that a read fault raises.
PostgreSQL catches the error and returns the empty value instead:

- `db/postgresql/attribute.py:235-236` `return None` for a bucket, which
  `Attributes.get_bucket` turns into `{}` (`attribute.py:113-114`);
- `db/postgresql/trust.py:774-775` and `db/postgresql/subscription.py:392-393`
  `return []` for the lists.

Four consumers took the empty answer as real:

1. **`_adopt_actor` decided vouching from the marker read** (`oauth2.py`,
   `is_vouched_actor`). An unreadable `_internal` bucket reads as "no
   marker", which means legacy and unvouched, so the clean-in-place path
   ran on a vouched actor.
2. **`Actor.purge_relationships`** re-read the lists to set `confirmed`
   (`not trusts_left and not subs_left`). A fault on both reads deletes
   nothing and still confirms the wipe.
3. **`OAuth2SessionManager.revoke_all_tokens`** read the two SPA token
   buckets through `Attributes.get_bucket()` and discarded the result of
   every `delete_attr`. It could not report a fault, although
   `_revoke_all_actor_tokens` was documented to raise on one.
4. **`scripts/mark_actors_vouched.py`** read the marker the same way as (1),
   and counted a write it never confirmed.

The plan's implementation (2026-10-26) introduced all four. Before it, no
sign-in path destroyed state on these reads.

## Hypotheses Rejected

- **"DynamoDB is affected too."** Rejected. `DbAttribute.get_bucket` and the
  list `fetch`es iterate a lazy Query outside any `try`, so a throttle raises
  through `adopt_actor`'s `except` and the sign-in returns `None`.
- **"`Attributes.loaded` already protects `InternalStore`."** Rejected.
  `InternalStore._ensure_loaded` sets its own `_loaded = True` before reading
  (`attribute.py:33-34`) and never consulted `_db.loaded`.

## Fix

- `actingweb/attribute.py`: `InternalStore.loaded` reports `_db.loaded`, and
  `InternalStore.mark_empty()` / `Attributes.mark_loaded_empty()` replace
  `Actor.create`'s write to the private `__dict__["_loaded"]`. Without that
  change a freshly created actor would report not-loaded.
- `actingweb/oauth2.py` `_adopt_actor`: return `None` when the store is not
  `loaded`, before the vouching decision.
- PostgreSQL list backends (`db/postgresql/trust.py`, `db/postgresql/subscription.py`):
  `fetch(actor_id, *, strict=False)`, which re-raises on a fault when
  `strict` is set. The DynamoDB backends accept `strict` for protocol parity,
  and `db/protocols.py` declares it.
- `actingweb/actor.py` `purge_relationships`: both the first read and the
  re-read are strict. A fault before the wipe removes nothing; a fault after
  it leaves `confirmed` False.
- `actingweb/oauth_session.py` `revoke_all_tokens(..., strict=False)`: in
  strict mode it raises `TokenStoreUnavailable` when a bucket was not
  `loaded` or a delete was not confirmed. The theft response keeps today's
  best-effort behaviour, and `_revoke_all_actor_tokens` passes
  `strict=True`.
- `scripts/mark_actors_vouched.py`: an unread marker counts as an error and
  is never marked; a write is counted only after it reads back.

Reuse: `Attributes.loaded` (3.15) and `TokenStoreUnavailable`, the same
contract `ActingWebTokenManager._snapshot_bucket` uses.

Release: part of 3.16.0, a minor. The new keywords are keyword-only with
defaults.

## Evidence

- Regression tests, all in `tests/test_adoption_backend_faults.py`. Each
  reproduces PostgreSQL's shape at the backend seam, so it runs on either
  backend. All five failed before the fix, on DynamoDB, each for the reason
  named, and all pass after it on both backends:
  - `TestVouchingReadFault::test_unreadable_marker_fails_closed_and_wipes_nothing`
    asserts `lookup_or_create_actor_by_identifier(creator) is None` and
    `row.passphrase == "own-pass"`. Before the fix the passphrase was
    rotated.
  - `TestWipeConfirmationReadFault::test_unreadable_list_leaves_actor_unvouched[trusts|subscriptions]`
    asserts the sign-in is `None` and `not istore(row).auth_method`.
  - `TestSpaRevokeReadFault::test_unreadable_session_bucket_fails_the_adoption`
    asserts the sign-in is `None` and the actor stays unvouched.
  - `TestBackfillReadFault::test_unreadable_marker_is_an_error_not_a_mark`
    asserts `counts["marked"] == 0 and counts["errors"] == 1` and that the
    marker is still `"factory"`.
- Full suite (parallel, with the rest of the iteration's changes):
  DynamoDB 3995 passed, 31 skipped; PostgreSQL 3886 passed, 140 skipped;
  ruff, ruff format, pyright 0/0.
- Scope lock: self-check. The cause spans the storage seam:
  - `actingweb/attribute.py`, `actingweb/actor.py`, `actingweb/oauth2.py`,
    `actingweb/oauth_session.py`;
  - `actingweb/db/{postgresql,dynamodb}/{trust,subscription}.py`,
    `actingweb/db/protocols.py`;
  - `scripts/mark_actors_vouched.py`, `tests/`, `CHANGELOG.rst`, `docs/`.

  That is more than five files. The user approved the scope (verification
  Issues 1-10) before the work started.
- Fresh reproduction: the five tests were re-run after the fix on both
  backends, and all pass.

## Related

- `thoughts/todo/db-layer-get-bucket-or-empty.md`: the same class at six
  older sites. It now names the `strict` list fetch and
  `InternalStore.loaded` as the primitives to reuse.
- 3.14.2 emptied a list through the same shape
  (`fetch_all_including_lists() ... or {}`). This class keeps recurring in
  the PostgreSQL backend. Any new code that acts on an absence should
  require a read the backend answered, not infer one from an empty value.

## Status

DONE
