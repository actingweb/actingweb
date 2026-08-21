# v2 list access — verification follow-ups (3.14.0)

Source: `thoughts/verifications/2026-08-21-v2-positional-access-cost.md`.
**Most of this file was actioned on 2026-08-21** (the same day it was
filed) in the follow-up commit on `release/3.14.0-v2-positional-access-cost`:
the release-blocking cross-version wording (Issue 1), bulk
duplicate-index regression tests (2), the `None`-item diff sentinel (3),
the ambiguous-match WARNING (4), the parametrized permission-enforcement
suite (5), the third drift-term test (6), advisory append-index docs (7),
the orphan-scan replay guard + exit 3 (8), and the low roll-up's code and
docs items (v1 capture-during-scan, stale-cache `_where` tests, guard
hardening, migration-guide restorations, doc nits).

What remains, none release-blocking:

- **`ruff format` drift, 19 files.** The pinned ruff (0.15.20, matches
  poetry.lock) would reformat 15 source files from Phases 9–11 plus the
  four `test_v2_*` files; CI only enforces `ruff check`. Deliberately not
  bundled into the release branch (the maintainer's earlier call). Fix as
  a standalone mechanical commit after 3.14.0 tags, or add
  `ruff format --check` to CI at the same time so it cannot drift again.
- **End-to-end peer-replica integration test for Phase 10 diffs.** Sender
  and receiver halves are each unit-pinned
  (`test_property_list_notifications.py`, `test_remote_storage.py`), but
  no test drives a real `remove_where()`/`update_where()` diff through
  subscription delivery into a `RemotePeerStore` — the plan named this
  test and it was never written.
- **Cross-backend interleaved-append integration test (Phase 9B).**
  Two instances appending alternately, asserting iteration order matches
  insertion order, on both backends. Nearest existing coverage is the
  weaker `test_stale_reader_append_still_lands_correctly`.
- **`www.py` HTML UI has no `ListMetadataContentionError` handler.** The
  docs accurately name only the three JSON handlers as mapping it to 503;
  the browser UI surfaces it as a generic error page (`set_description`)
  or unhandled (`append`). Decide whether the web UI deserves the same
  mapping.
- **Bulk response counts for duplicate deletes of a batch-created index**
  credit each request entry (`items_deleted` can exceed rows removed by
  design, matching update counting) — noise-level; revisit only if a
  consumer reads these counts strictly.
- **Phase 8 `DbError`-on-genuine-fault path untested** — hard to inject
  against a real backend; would need a fault-injection seam in the
  DynamoDB/PostgreSQL property modules.
