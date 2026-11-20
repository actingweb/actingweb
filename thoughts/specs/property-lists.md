# Spec: Property lists (and attribute lists)

**Status:** partial (covers: behaviour changed since 2026-11-19)
**Reviewed:** 2026-11-19 by Greger Wedel (with the plan)
**Last changed:** 2026-11-20 by thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**ID prefix:** PLS

## Summary

Ordered lists stored per actor (property lists) and per bucket (attribute
lists), with the same storage-layer interface. This partial spec covers
faults, the stored-format rule and the item ceiling.

## Faults

- **PLS-1** — When the store faults under `exists()`, `list_all()` or
  `list_all_with_rows()`, on either store, `DbError` is raised. [plan+test]
  `tests/test_db_fault_callers.py::TestListStoreLookups`, `tests/test_list_prefix_with_rows.py`, `tests/test_attribute_list_store.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-8, AC-21, AC-44)
- **PLS-2** — When a write is stored and a later step faults, the exception
  is `DbErrorAfterWrite` (503 `stored_not_notified`, no `Retry-After`): the
  value is stored, its diff is not registered. [plan+test] `tests/test_db_error_after_write.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-22)

## Stored format

- **PLS-3** — When an envelope's `need` names something the process does not
  implement, the item cannot be read, written, moved or repaired by it
  (`ListItemNewerFormatError`, 409 over HTTP, and a per-list marker in the
  properties listing), and nothing of it is removed except by deleting or
  clearing the whole list. When a list's meta `format` is not 1 or 2, the
  list is refused by every operation, `delete()` and `clear()` included;
  an unparsable meta row is damage, not a newer layout, and does not stop
  an attribute list's `delete()`. [plan+test] `tests/test_property_list_newer_format.py`, `tests/test_list_newer_format_http.py`, `tests/test_property_list_span_codec.py::TestNeed` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-25 to AC-27, AC-43; iterations 3, 9, 10)
- **PLS-4** — When a list is swept, cleared or deleted, side rows with an
  unrecognised name are left. [plan+test] `tests/test_property_list_newer_format.py::test_unrecognised_side_row_names_survive_sweep_clear_and_delete` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-28)

## Limits

- **PLS-5** — When no ceiling is configured on a backend with a row cap, the
  ceiling is 2 MiB. [plan+test] `tests/test_list_item_limits.py::TestBackendDefaults::test_default_ceiling_is_2_mib_with_a_row_cap` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-29)

## Decisions in force

- **PLS-D1** — Every stored shape 4.0.0rc1 writes is read by 4.0.0 final
  without an operator step. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **PLS-D2** — A later 4.x that changes how an item is stored names the
  change in `need`; one that changes a list's layout raises its `format`.
  Neither reuses a field 4.0.0 ignores for something a writer must
  maintain. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **PLS-D3** — A later side-row kind is named `list:{name}-$<kind>-...`, so
  that it is reaped with the actor and reported when its list is gone. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **PLS-D4** — A list whose layout a later version wrote is refused by
  `delete()` and `clear()` too (owner, 2026-11-20: keep the refusal);
  deleting an actor and revoking a trust remove rows directly and are not
  affected. (plans/2026-11-19-emm-4-0-adoption-findings.md)

## Untested

- PLS-5: no item over 2 MiB is refused under the default ceiling in a test;
  only the value is pinned.
- A property list with an unparsable meta row is still refused by
  `delete()` (as before 4.0).
