# The callback-processor concurrency test fails in a sequential PostgreSQL run

`tests/integration/test_callback_processor_concurrency.py::test_two_concurrent_deliveries_run_the_handler_once`
fails every time it runs alone (or in `make test-integration`) on
PostgreSQL:

```
assert ['duplicate', 'processed'] == ['in_progress', 'processed']
```

It passes in `make test-all-parallel` on PostgreSQL and on DynamoDB.

**Verified 2026-11-10** (during Phase 4 of
`thoughts/plans/2026-11-10-grant-enforcement-per-route.md`): it fails the
same way on `master` (`999f3b6`) and at that branch's Phase 3 commit
(`6097f62`), so it predates the grant work and is not caused by it.

**What it means.** The handler still ran once: the losing delivery answered
`duplicate` (it read the winner's state after the winner had finished)
instead of `in_progress` (the live claim). Either the barrier does not hold
both deliveries before the claim on PostgreSQL in a single process (the
winner commits before the loser reads), or `duplicate` is a correct answer
there and the test pins one interleaving. Both answers keep the publisher
safe (`in_progress` is a 503, so the diff is kept; `duplicate` is a 204 for a
callback already applied).

**To do.** Trace the claim on PostgreSQL (`callback_processor` state write,
plan D13 of the callback work) with the barrier's timing, decide whether the
test or the barrier placement is wrong, and fix that one. Sequential
PostgreSQL runs are part of the Full tier's fallback ("re-run a failure
sequentially"), so this failure shows up there until it is fixed.
