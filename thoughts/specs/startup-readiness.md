# Spec: Start-up readiness

**Status:** partial (covers: behaviour changed since 2026-11-19)
**Reviewed:** 2026-11-19 by Greger Wedel (with the plan)
**Last changed:** 2026-11-20 by thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md
**ID prefix:** SRD

## Summary

`ActingWebApp.check_ready()` (called by `integrate_*`) decides whether an
application may serve on its store. This partial spec covers creator
uniqueness at the first start and the handling of faults.

## Creator uniqueness

- **SRD-1** — When the store has no user actors, the application enables
  enforcement itself (on DynamoDB only with an explicit prefix); with user
  actors and no enforcement it refuses. [plan+test]
  `tests/integration/test_unique_creator_empty_store.py`, `tests/test_unique_creator_default.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-13 to AC-15, AC-48, AC-50)
- **SRD-2** — When one of the library's system actors (its fixed id with its
  own creator) is created on first use before an empty store is enabled (a
  trust type registered at import), it is written without a creator record
  (DynamoDB) or before the unique index exists (PostgreSQL), and the enable
  covers it; any other actor with a system creator is refused as before.
  [plan+test] `tests/integration/test_unique_creator_empty_store.py::test_a_trust_type_registered_before_the_start_on_a_fresh_store`, `::test_only_the_system_actors_own_ids_skip_the_record` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-13; iterations 2, 15)
- **SRD-3** — When two first starts enable an empty DynamoDB store at once,
  the marker is written once. A start that finds it never removes it, runs
  the same late pass over what was created meanwhile, and refuses (naming
  `enable --apply`) if that fails; a start whose own late pass fails removes
  only its own marker. [plan+test] `tests/integration/test_unique_creator_empty_store.py::test_a_failing_enable_never_removes_another_starts_marker`, `::test_a_fault_after_the_marker_removes_it`, `::test_a_start_that_finds_the_marker_records_what_was_created_meanwhile` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-50; iterations 4, 14, 20)

## Faults

- **SRD-4** — When a check faults, it is tried three times; a refusal for a
  fault has `unavailable` true. [plan+test] `tests/test_startup_check_retry.py` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-16, AC-17)

## Decisions in force

- **SRD-D1** — A start is still refused when the store does not answer after
  the retries; `unavailable` is not permission to serve. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **SRD-D2** — While an empty store enables itself, no older process may
  create actors in it; the second scan catches one that does. A start on a
  store that already enforces has no such rule. (plans/2026-11-19-emm-4-0-adoption-findings.md)

## Untested

- A start killed between writing the marker and finishing its late pass
  leaves "complete" unchecked (accepted 2026-11-20).
- A system actor saved after the enable's late pass has no creator record;
  `report` lists it as unrecorded (accepted 2026-11-20).
