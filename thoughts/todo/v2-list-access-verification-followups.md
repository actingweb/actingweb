# v2 list access — verification follow-ups (3.14.0)

What is left from `thoughts/verifications/2026-08-21-v2-positional-access-cost.md`.
None of it is release-blocking.

- **Bulk response counts for duplicate deletes of a batch-created index**
  credit each request entry (`items_deleted` can exceed rows removed by
  design, matching update counting) — noise-level; revisit only if a
  consumer reads these counts strictly.
