# Benchmark subscription tests pass a URL to the boolean `callback` column

**Provenance:** found on 2026-09-14 while running the full parallel suite
against PostgreSQL to validate the 3.14.7 dependency refresh (PR #146).
Pre-existing; unrelated to the upgrade. CI never sees it because the
parallel job runs with `-m "not benchmark"`
(`.github/workflows/tests.yml:263`).

## What is wrong

`tests/performance/test_backend_performance.py:365` and `:393`
(`TestSubscriptionPerformance::test_subscription_create_performance` and
`::test_subscription_read_performance`) call
`DbSubscription.create(..., callback="https://callback.example.com")`.

`callback` is a **boolean** on both backends -- `BooleanAttribute` in
`actingweb/db/dynamodb/subscription.py:36`, `sa.Boolean()` in
`actingweb/db/postgresql/schema.py:151` -- meaning "deliver by callback",
not a URL.

- On PostgreSQL the INSERT fails with `invalid input syntax for type
  boolean: "https://callback.example.com"`, `create()` logs the error and
  returns `False`, and both tests fail (`assert result is True`, then the
  read test's `assert result is not None`).
- On DynamoDB the same call passes: the test suite reports both tests green
  there. Whether PynamoDB coerces the non-empty string to `True` or the
  attribute is stored as-is has not been checked; either way the test
  asserts nothing about the stored value, so it proves less than it looks
  like it proves.

Observed: `DATABASE_BACKEND=postgresql ... pytest tests/ -n auto --dist
loadgroup` → `2 failed, 3401 passed, 140 skipped`; the two failures are
exactly these.

## What doing it buys

The benchmark suite becomes runnable on PostgreSQL, which is the point of
having a backend-parametrised performance test at all. One-line fix per
site (`callback=True`), plus a decision on whether the DynamoDB backend
should reject a non-bool `callback` rather than accept whatever it was
given.

## What has to be decided first

Nothing for the test fix itself. The DynamoDB-side question (reject or
coerce a non-bool `callback`) is separate and can wait; `DbSubscription`'s
public callers in the library always pass a bool.
