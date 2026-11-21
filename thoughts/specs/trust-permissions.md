# Spec: Trust permissions

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-21 by thoughts/plans/2026-11-21-trust-request-answer-secret.md
**ID prefix:** TPM

## Summary

A peer's access to an actor is its trust type's base permissions, narrowed
or widened by a per-peer override the actor's owner stores. This partial
spec covers only how long a process relies on what it has read of an
override.

## Caching

- **TPM-1** — When a process has cached a peer's permission override, or its
  absence, it uses that for at most 300 seconds before reading storage
  again. [plan+test] `tests/test_permission_cache_bounds.py::test_an_override_changed_elsewhere_is_in_force_after_the_window`,
  `::test_an_override_stored_elsewhere_replaces_a_cached_absence_after_the_window`,
  `::test_an_entry_just_inside_the_window_reads_nothing` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-1 to AC-3)
- **TPM-2** — When a process itself stores or deletes an override, it uses
  the change at once. [plan+test] `tests/test_permission_cache_bounds.py::test_a_store_and_a_delete_here_are_seen_at_once` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-4)

## Telling the peer

- **TPM-3** — When an application with `with_sync_callbacks()` stores a
  trust's permission override through `store_permissions_async`, the peer
  is told before the call returns; without the setting it is told by a
  background task. With `callback_delivery_budget_seconds` set, the wait
  counts against the deadline the request's callbacks use in the same
  `contextvars` context: the peer exchange is cut when it runs out, nothing
  is sent when it already has, and either is logged. [plan+test]
  `tests/integration/test_consumer_sdk_calls.py::test_store_permissions_async_tells_the_peer_before_returning_when_sync`,
  `tests/test_trust_permissions_unit.py::TestTrustPermissionStoreAsyncNotifications`
  (`::test_store_permissions_async_calls_notify_peer_async`,
  `::test_store_permissions_async_awaits_the_peer_when_sync`,
  `::test_store_permissions_async_cut_by_the_delivery_budget`,
  `::test_store_permissions_async_shares_the_request_deadline`,
  `::test_store_permissions_async_waits_only_what_the_request_has_left`) (plans/2026-11-15-3-16-release-validation.md; iterations entries 1, 3, 4)

- **TPM-4** — A permission change is not sent to a peer whose id has an
  OAuth2 prefix (`oauth2:`, `oauth2_client:`, `oauth2_interactive:`), on the
  sync or the async path, and nothing is logged above DEBUG for it; any other
  peer whose trust has no base URI logs a WARNING. [plan+test]
  `tests/test_trust_permissions_notify.py::test_an_oauth2_peer_is_not_notified`,
  `::test_a_peer_without_baseuri_still_warns` (plans/2026-11-21-trust-request-answer-secret.md, AC-14, AC-15)

## Decisions in force

- **TPM-D1** — The window covers overrides only: a trust type's base
  permissions are cached per process without expiry, and nothing is
  invalidated across processes. There is no option for the window. (plans/2026-11-17-3-16-pre-rc1-fixes.md)

## Untested

- TPM-3 across contexts: a sync handler that FastAPI runs in its thread
  pool works in a copy of the request context, so a deadline it starts is
  not seen by the request task, or the reverse; the statement holds within
  one context only. A deadline the notification starts itself (no callback
  before it) is not tested.
