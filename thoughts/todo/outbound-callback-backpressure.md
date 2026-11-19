# Outbound callbacks: back-off, a per-peer breaker, payload limits

Filed 2026-11-15 by `spec-1-5` Phase 4, which made one write's callbacks
concurrent (`actingweb/callback_sender.py`) and removed `FanOutManager`.
Specification 1.5 keeps these as optional mechanisms; the stored diff and
polling are the recovery every implementation has. Nothing here is a defect.

## What is not done

- **Acting on 429 and 503.** The sender treats any non-2xx as a failed
  delivery and does not retry or back off; the subscriber recovers by the gap
  at its next callback, by polling, or (a resync) on the next resume.
- **A per-peer breaker.** A subscriber that keeps failing is still sent every
  write's callback, each costing up to the timeouts.
- **A payload cap with a downgrade** to a low-granularity callback, and
  **compression**.
- **A process-wide bound** on sends and on the tasks kept on a running loop:
  the bound is per write (owner, 2026-11-15), so many simultaneous writes, or
  writes outpacing slow subscribers on a loop, are bounded only by their
  timeouts.

## What the removed class got right and wrong

`FanOutManager` had a breaker per peer persisted between processes and a
payload downgrade, but it was never on the publish path: it numbered one
sequence for all subscribers, applied no permission filter, read the wrong
option tag, and downgraded to a URL a 4.0 subscriber does not fetch. A design
here starts from the sender (units per subscriber, the per-write bound) and
keeps the per-subscription sequence and the grant filter.

## Added 2026-11-19 (a consumer's A11)

Treat `callback_delivery_budget_seconds` as a deadline for the whole
request, not only for its callbacks, and send a permission notice the budget
cut later instead of dropping it to the next change. No peer, subscription
or replica in the asking consumer's production yet, so there is nothing to
test it against (`thoughts/plans/2026-11-19-emm-4-0-adoption-findings.md`).

