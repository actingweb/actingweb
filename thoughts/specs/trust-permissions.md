# Spec: Trust permissions

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-17 by thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md
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

## Decisions in force

- **TPM-D1** — The window covers overrides only: a trust type's base
  permissions are cached per process without expiry, and nothing is
  invalidated across processes. There is no option for the window. (plans/2026-11-17-3-16-pre-rc1-fixes.md)

## Untested

- None of the above.
