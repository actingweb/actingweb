# Verification: the fixes 3.16 takes before its release validation (re-run 2)

**Date:** 2026-11-16
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** 8bb63cf

A re-run, scaled to what changed since re-run 1: the second iteration
(`ab11326`, iterations log entries 7 to 10: the `list:` key's path check,
the behind poll's rebuild, the stored-trust URL match, small things) and
the consumer's suite record (`8bb63cf`, Markdown only). The phases and
the acceptance criteria the iteration did not touch were verified in the
first run and are not repeated.

## Automated Check Results

The Full tier ran on `8bb63cf`.

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass (43 groups, wire registry,
  Wire-Phase trailers).
- `make test-all-parallel`, **DynamoDB**: pass, 8,018 passed, 212 skipped,
  2 xfailed.
- `make test-all-parallel`, **PostgreSQL**: pass, 7,790 passed, 440
  skipped, 2 xfailed.
- `sphinx-build -W --keep-going`: pass.
- **The consumer's suite** on `ab11326`, environment 9: PostgreSQL 3
  failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB lane 3 failed,
  54 passed. The same six failures by name as on `d62021b` and `3fb93ab`
  (the record is `8bb63cf`).
- **Browser QA:** ran, headless Playwright (the offstage MCP server did not
  connect; nothing headed was started). The demo in local QA mode on port
  5055 with a throwaway actor, deleted after. Both trust pages loaded at
  1280 and 375 px wide: the legend reads "Waiting for peer - You approved;
  the peer has not yet approved or verified", the page scrolls no wider
  than the viewport at either width, and the console shows no error or
  warning. No finding.
- **Second opinion:** fresh-context adversarial reviewer on
  `3b1200e..ab11326` (the delta only). Nothing High or Medium; four Low
  (Issues 1 to 4 below).
- **Built-in code review and security review:** not run as separate
  providers, as in the earlier runs (the delta is small and was read in
  full by the reviewer).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-16-3-16-pre-validation-fixes-2.md
**Iterations since:** entries 7 to 10 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A behind poll tells no hook when the baseline is empty (Medium) | Fixed with `auto_storage`; a hooks-only subscriber is still told nothing (Issue 3 below) | `actingweb/interface/subscription_manager.py:1368-1382` (async twin `:2389-2395`); `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks::test_a_behind_poll_tells_an_empty_baseline_and_empties_the_replica` |
| 2. The path check drops every `list:` key under a grant that names the property (Low) | Partly fixed: the path check asks exclusions only; the bare-name gate stays, recorded in iterations entry 7 | `actingweb/actor.py` `filter_subscription_blob`; `tests/test_grant_stored_text.py::TestListDiffObjects::test_a_grant_that_names_the_property_keeps_its_list_keys` |
| 3. A skipped or partly stored behind baseline loses its claim (Low) | Partly fixed: a failed entry stays owed; a skipped (covered) baseline is now told (Issue 1 below) | `::test_a_behind_poll_whose_baseline_was_not_stored_whole_stays_owed` |
| 4. `_same_peer_url` matches `?`, `#` and a tab in the host (Low) | Fixed; trailing whitespace no longer matches (Issue 4 below) | `actingweb/handlers/www.py` `_same_peer_url`; `tests/test_www_trust_pages.py::test_which_typed_urls_name_the_stored_peer` |
| 5. "Already exists" speaks for the row matched by URL (Low) | Partly fixed: "paired again" needs a peer id; `trust_exists` accepted (iterations entry 9) | `::test_a_returned_row_without_a_peer_id_is_not_called_a_re_pair` |
| 6. Smaller findings in the poll's comparison (Low) | Partly fixed: `NaN` and `Infinity` are never behind; a sequence that is a string or `null` still raises later, at `if final_seq > 0:`, as before the branch | `::test_a_publisher_sequence_that_is_no_integer_is_not_behind` |
| 7. The contract's cut-off date excludes this plan (Low) | Fixed | `CLAUDE.md` ("Living specs"), `thoughts/specs/README.md:20-21` |

## Acceptance Criteria

Only the criterion the iteration touched; the others stand as in the
earlier runs.

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-8 (annotation: quiet means level with the publisher; behind runs a rebuild) | `tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks`: `test_a_quiet_poll_tells_no_hook`, `test_a_behind_poll_tells_an_empty_baseline_and_empties_the_replica`, `test_a_behind_poll_whose_baseline_was_not_stored_whole_stays_owed`, `test_a_publisher_sequence_that_is_no_integer_is_not_behind`, `test_without_sequence_tracking_a_quiet_poll_is_never_behind` | Yes, with `auto_storage` on. A covered subtarget subscription and a hooks-only subscriber are not asserted (Issues 1 and 3) | Pass |
| AC-16 | `tests/test_www_trust_pages.py::test_nothing_from_the_query_string_is_rendered` now first asserts the type is offered | Yes (the select assertion is no longer vacuous) | Pass |

## Remaining Tasks

- [ ] Issues 1 to 4 below, if the owner wants them closed before the PR;
  by the stop rule none blocks it.

## Issues Found

### 1. A behind poll of a covered subtarget subscription is told a baseline it did not store
**Severity:** Low (no data exposed; a hook hears a value the replica does
not hold, which a covering subscription holds already)
**Description:** The behind path hands the poll to
`rebuild_subscription(force=True)`, which treats only `applied.failed` as
unsettled. A baseline that `apply_subscription_baseline` skipped because a
whole-target subscription covers the subtarget is settled, so the rebuild
returns it as `baseline` and the hooks are told it. The docs say a skipped
baseline is not told; entry 2's quiet-path rule kept that, entry 8 lost it
for the behind case.
**Location:** `actingweb/interface/subscription_manager.py:2979` `if
applied.failed:` and `:3043` `baseline=baseline if settled else None`
**Recommendation:** Return no baseline when `applied.skipped`, or say in
the hooks reference that a rebuild tells the baseline whether or not this
subscription stored it.

### 2. A forced rebuild that fails before it writes the sequence is retried every poll
**Severity:** Low (the subscriber's own polls; three requests to the
publisher each, no hook, no sweep)
**Description:** `force=True` skips the one-minute interval between
rebuilds. When the baseline fetch fails, the sequence stays behind, so the
next poll is behind again and forces another attempt. The changelog says a
rebuild is attempted at most once a minute.
**Location:** `actingweb/interface/subscription_manager.py:1381` `peer_id,
subscription_id, config=config, force=True` (async twin `:2394`)
**Recommendation:** Let the behind path respect the interval (no `force`,
or a separate stamp for it), or narrow the changelog's sentence.

### 3. The behind fix holds only with `auto_storage`
**Severity:** Low (a configuration without a replica; the hook is the
application's only record)
**Description:** The behind comparison sits inside `if diffs_fetched == 0
and config.auto_storage:`. A subscriber with `auto_sequence` and hooks but
no `auto_storage` is told nothing after a gap resync, as before the
branch. The hooks reference names only `auto_sequence` as the condition.
**Location:** `actingweb/interface/subscription_manager.py:1363` `if
diffs_fetched == 0 and config.auto_storage:`
**Recommendation:** Name `auto_storage` in the hooks reference, or move the
comparison out of the storage condition (a rebuild without storage would
then only tell).

### 4. Whitespace around a typed URL no longer matches the stored peer
**Severity:** Low (owner only; a pasted URL with a trailing space creates a
second trust instead of a re-pair)
**Description:** `_same_peer_url` now refuses what `is_valid_peer_baseuri`
refuses, which includes surrounding whitespace, and the handler does not
strip `peer_url` before comparing. `https://peer.example/a ` matched before
the iteration and does not now.
**Location:** `actingweb/handlers/www.py:1079` `peer_url =
self.request.get("peer_url")`
**Recommendation:** Strip `peer_url` where it is read.

## Spec Merge

- Not merged, and `spec_merged:` is not written. The plan is the last one
  the contract names as carrying no mergeable Spec Delta
  (`thoughts/specs/README.md:20-21`); its delta has no ADDED, MODIFIED,
  REMOVED or DECISION line.

## Overall Assessment

The second iteration closed re-run 1's Medium: a poll that is behind the
publisher now runs a rebuild, which empties the replica for an empty
baseline, tells the hooks, and stays owed when an entry could not be
stored. The filter no longer drops `list:` keys under a grant that names
the property, and the stored-trust match refuses what the library refuses
as a base URI. The Full tier is green on both backends on `8bb63cf`, the
consumer's suite is at its baseline, and the trust pages' legend loads
cleanly at desktop and phone widths.

Four Low findings remain, each an edge of the iteration's own fixes:
a covered subtarget told a baseline it did not store, a failing rebuild
retried on every poll, the behind rule limited to `auto_storage`, and a
typed URL's whitespace. None is peer-reachable at Medium or above, so by
the stop rule the record is clean; the owner decides whether to close
them now or accept them.
