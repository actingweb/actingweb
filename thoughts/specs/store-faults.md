# Spec: Store faults

**Status:** partial (covers: behaviour changed since 2026-11-23)
**Reviewed:** 2026-11-23 by Greger Wedel (with the plan)
**Last changed:** 2026-11-23 by thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md
**ID prefix:** SFT

## Summary

A store fault is a `DbError`: the database backend could not answer. This
partial spec covers how a fault is classified for an application and for
the HTTP answer, and the strict mode of the conditional attribute update.
The rest of the fault contract is in `docs/reference/database-backends.rst`
and `docs/migration/v4.0.rst` ("fault contract") until it is written here.

## Classification

- **SFT-1** — `actingweb.faults.classify_fault()` names a store fault's
  class (retryable, stored, permanent, conflict) and retry delay, follows
  `raise ... from` up to five links, and answers `None` for anything else;
  the integrations' HTTP answers are derived from it. [plan+test]
  `tests/test_public_fault_classifier.py` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-10, AC-11)
- **SFT-2** — `AttributeKeyCollision` is permanent: HTTP 500 without
  `Retry-After`. [plan+test]
  `tests/test_db_fault_http.py::TestFlask::test_a_key_collision_answers_500_without_retry_after`, `::TestFastAPI::test_a_key_collision_answers_500_without_retry_after` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-9)

## Conditional writes

- **SFT-3** — `conditional_update_attr` answers `False` on a fault by
  default. With `strict=True` a store fault raises `DbError` chained to the
  backend's exception, and `False` means the condition did not hold: the
  row holds something other than `old_data` (the same value another writer
  wrote included), there is no row, or another bucket holds the key. In
  neither mode does `False` prove the write did not land. [plan+test]
  `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-16 to AC-18, AC-28, AC-29)
- **SFT-4** — With `strict=True`, a caller's value that JSON cannot order
  or encode raises `TypeError` or `ValueError` before the store is touched;
  an exception inside the backend is a `DbError` whatever its type.
  [plan+test] `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_a_value_that_cannot_be_compared_is_not_an_outage`, `::test_a_store_side_value_error_is_still_a_fault` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-33)

## Decisions in force

- **SFT-D1** — The default of `conditional_update_attr` does not raise.
  (plans/2026-11-01-single-mode-and-consumer-primitives.md, D10)
- **SFT-D2** — `actor.store` folds a failed read; `loaded` is its signal.
  (plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md)
- **SFT-D3** — Strict is the backends' to decide, not a re-read above them:
  only the backend knows why its write did not happen. (plans/2026-11-23-emm-4-0-rc2-production-observations.md, iteration 1)

## Untested

- SFT-3: a write that landed and whose answer was lost (`False` or a
  `DbError` for a write that is stored) is documented, not tested;
  `todo/conditional-write-ambiguous-after-sdk-retry.md`.
