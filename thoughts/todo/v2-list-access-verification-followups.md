# v2 list access — verification follow-ups (3.14.0)

What is left from `thoughts/verifications/2026-08-21-v2-positional-access-cost.md`
after its same-day follow-up commit. None of it is release-blocking; the
verification records what was actioned.

- **End-to-end peer-replica integration test for Phase 10 diffs.** Sender
  and receiver halves are each unit-pinned
  (`test_property_list_notifications.py`, `test_remote_storage.py`), but
  no test drives a real `remove_where()`/`update_where()` diff through
  subscription delivery into a `RemotePeerStore` — the plan named this
  test and it was never written. Since 3.16 a spanned item's diff carries a
  reference the receiver deliberately does not resolve
  (`remote_storage.py`), which the same test should cover.
- **Cross-backend interleaved-append integration test (Phase 9B).**
  Two instances appending alternately, asserting iteration order matches
  insertion order, on both backends. Nearest existing coverage is the
  weaker `test_stale_reader_append_still_lands_correctly`.
- **Bulk response counts for duplicate deletes of a batch-created index**
  credit each request entry (`items_deleted` can exceed rows removed by
  design, matching update counting) — noise-level; revisit only if a
  consumer reads these counts strictly.
- **Phase 8 `DbError`-on-genuine-fault path untested.** A store-wrapping
  seam now exists (`actingweb/spans.py`, and the `tests/test_db_fault_*.py`
  files use the pattern), so this is cheap; nothing yet faults `get_range`
  or `find` and asserts `DbError`.
