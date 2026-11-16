# Two concurrent low-granularity writes leave a replica without one of them

Found 2026-11-15 while writing `spec-1-5` Phase 4's two-write test
(`tests/integration/test_callback_delivery_shapes.py`,
`test_two_simultaneous_low_granularity_writes_reach_every_replica`, an
`xfail`, not strict since it passed once on CI, PR #178). Two writes to one publisher at the same moment, four
low-granularity subscribers on another origin of the same process: both
writes are answered, but one subscriber's replica lacks one of the two
values after 20 s. It fails the same way with the serial sender of Phase 3
(a different subscriber each time), so the new sender is not the cause.

## What to look at

- The receiver's low-granularity path when the second sequence arrives
  first: `precheck` before the fetch, the fetch consuming the diff at the
  publisher, and what the pending queue holds for a low-granularity entry
  when the earlier sequence lands and drains it.
- Whether the change is recovered by the subscriber's next callback (a gap
  resync) or only by a poll; the test waits 20 s with no further traffic.

## Why it waits

Low granularity is rarely used with concurrent writers; the replica
recovers on the subscriber's next callback or poll. Specification 1.5 does
not change the receiver's ordering rules.
