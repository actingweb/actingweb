# Verification: the fixes 3.16 takes before its release validation

**Date:** 2026-11-16
**Plan:** thoughts/plans/2026-11-16-3-16-pre-validation-fixes.md
**Branch:** release/3.16.0-pre-validation-fixes
**Commit:** b3b5300

A whole-plan verification, the first. The implementer wrote it; the
acceptance-criteria audit, the adversarial pass and the browser walk were
each done by an agent with no view of the implementation session.

## Automated Check Results

Run on the tree of `b3b5300` (the run finished before the commit was made;
nothing changed between).

- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass, 599 files.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass (43 groups, the wire registry
  consistent, `Wire-Phase` trailers match the owners of the three changed
  recordings `WD12`, `WG15`, `WG16`).
- `make test-all-parallel`, **DynamoDB**: pass, 7,973 passed, 212 skipped,
  2 xfailed (parallel run; no failure, so no sequential re-run).
- `make test-all-parallel`, **PostgreSQL**: pass, 7,745 passed, 440
  skipped, 2 xfailed (parallel run).
- `sphinx-build -W --keep-going`: pass (with `.claude/**` excluded locally).
- Benchmarks: not run. The plan touches no list storage or attribute-layer
  code path that the benchmarks measure (the pending queue is one attribute
  row written by the existing conditional write).
- **The two-write test** (AC-3), run alone: 50 of 50 runs failed on each
  backend before the change (`e928e5b` plus the plan commit); 5 of 5 passed
  on each backend on `40f33f0`'s code.
- **The consumer's suite** (gate 2), on `d62021b`, environment 9:
  PostgreSQL 3 failed, 7,405 passed, 14 skipped, 179 deselected; DynamoDB
  lane 3 failed, 54 passed. The same six failures by name as the `spec-1-5`
  run (the baseline's five and the date-dependent trial-state case). **Not
  re-run for `b3b5300`**, which changed the poll's hook rule, the delivery
  filter and the new-trust handler.
- **Browser QA:** ran twice, provider headless Playwright (Node 1.61.1,
  Chromium headless shell), against the demo in local QA mode.
  - First walk (on Phase 3's working tree): every step met its expectation
    at 1280 and 375 px. One medium finding in what the plan added (the
    demo's "New trust" button lost its label on hover), fixed before the
    Phase 3 commit; one medium outside the plan (QA mode never prompts a
    browser for basic auth), filed as
    `thoughts/todo/demo-qa-mode-basic-auth-challenge.md`; four low, the
    demo's own styling.
  - Re-walk on `b3b5300`: six steps, all passed, with a real second actor
    as the peer. A first create shows the row "Active" and no notice; the
    same submit again redirects to `?notice=trust_repaired` with the fixed
    text and no second row, and the peer's own trust list still shows the
    relationship "Active"; an upper-case host with a trailing slash matches
    the same row; another trust type redirects to `?notice=trust_exists`
    and leaves the row `friend`; a failing submit returns to an empty form
    with the alert; an unknown notice code shows nothing. A row both sides
    approved but not verified reads "Waiting for peer". No console error,
    no sideways scroll at 375 px. Two low findings, below.
- **Second opinion:** provider codex (`gpt-5.6-sol`, read-only) with a
  fresh-context reviewer, four passes: after each phase commit (findings
  and their handling are in the plan) and, for this verification, on
  `40f33f0..b3b5300` and the branch as a whole. The last pass found nothing
  High, three Medium and four Low; all are under Issues Found.
- **Built-in code review and security review:** not run as separate
  providers. Each commit had the adversarial pass above with a security
  brief (the reviews of the delivery filter, the trust form and the OAuth2
  default); a fifth pass over the same diff was judged not worth its cost.

## Phase Verification

### Phase 1: the receiver keeps every callback - VERIFIED

**Changes verified:**
- `actingweb/callback_processor.py`: `_drain` / `_drain_sync`,
  `_claim_queued`, `_finish_batch`, `_run_handlers[_sync]`,
  `_swap_pending`, `_read_pending_row`; the gap branch drains once after
  queueing and does not check the gap timeout while the next callback in
  line is queued. Matches the plan's six rules as amended by the phase's
  review.
- `tests/integration/test_callback_processor_concurrency.py`: event-gated,
  `make_config(database=DATABASE_BACKEND)`, and it asserts the backend.
- `tests/integration/test_callback_delivery_shapes.py`: no `xfail` or skip
  marker is left on the two-write test or in its fixtures.
- The two todos are deleted with their index rows.

**Tests verified:** `tests/test_callback_pending_drain.py` (19 cases; they
run on PostgreSQL in a PostgreSQL run, none skipped). Each failure
scenario has its test (`:211`, `:268`, `:310`, `:330`, `:357`, `:399`,
`:415`); the subscription deleted during a drain is a todo line, as the
plan said.

**Deviations from plan:** the drain takes one callback per claim, always
the first, then at most 20 and none after 5 seconds (the plan: a share of
the lease); a non-finite number is refused; a sequence is queued once. All
from the phase's review, recorded in the plan. Acceptable.

### Phase 2: resume, resource notifications, polls - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py`: `_callback_subscription_resync` sends one callback
  of type `resync` and reads no capabilities; the fallback and its helpers
  are gone. No live reference to a removed name remains (only the removal
  notes in the changelog and the migration guide).
- `actingweb/interface/subscription_manager.py`: `notify_subscribers`
  passes a lazy `whole`; `sync_subscription[_async]` wrap
  `_poll_subscription[_async]` and call `_tell_polled_baseline`.
- `docs/protocol/actingweb-spec.rst`: the passages reworded (three more
  than the plan listed).
- Wire row `WD12` re-recorded: one POST of type `resync`, then the
  subscriber's two GETs; the replica ends with `y` as an object, no `x`,
  the list once.

**Tests verified:** `tests/test_resume_always_resyncs.py`,
`tests/test_notify_subscribers_whole_value.py`,
`tests/test_replica_rebuild.py::TestAPollTellsTheDataHooks`.

**Deviations from plan:**
- A quiet poll tells no hook (owner, after implementation). See Issue 2.
- A baseline is told only when applied whole. Acceptable.
- Two fallback tests deleted and not re-pinned: the deep value (the
  baseline read has its own test), and **the publisher with a holed list,
  which no test now joins to a subscriber's resync** (Issue 6).

### Phase 3: the public surface and the trust page - ISSUES FOUND

**Changes verified:**
- `actingweb/handlers/callback_oauth.py` raises `ImportError` naming
  `docs/migration/v3.16.rst`; `handlers/__init__.py` no longer lists it.
- `actingweb/config.py`, `actingweb/interface/app.py`: the default
  `redirect_uri` is `<root>/oauth/callback`. Demonstrated by a request on
  both integrations with OAuth configured: `GET /oauth?code=x&state=y`
  answers 302 to the provider's authorize URL, `GET /oauth/callback?...`
  attempts the token exchange. Wire rows `WG15` and `WG16` re-recorded.
- `actingweb/handlers/www.py`: every outcome of the new-trust POST is a
  302; `TRUST_FORM_MESSAGES`, `TRUST_LIST_NOTICES`, `trust_status_label`,
  `_same_peer_url`.
- Templates: the library's three and the demo's two.

**Tests verified:** `tests/test_www_trust_pages.py` (Flask and FastAPI),
`tests/test_demo_example.py::test_the_demo_trust_templates_render`,
`tests/test_subscription_processing.py::...::test_the_removed_callback_oauth_module_raises_its_pointer`.

**Deviations from plan:** the default `redirect_uri` (owner decision in the
phase); the form's re-pair is kept and announced; the label is computed in
the handler; the tests are in process under `tests/`, with
`database="dynamodb"` fixed, so they do not run on PostgreSQL (acceptable:
the handler has no backend-specific code, and the trust store's flags are
read through `as_flag`).

## Acceptance Criteria

Audited by a separate agent, which named for each test the one-line
mutation that makes it fail. 13 Covered, 4 Weak, none Uncovered.

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | `tests/test_callback_pending_drain.py:138` - `assert s.ran == [1, 2]`, `assert s.sequence() == 2`, `assert s.queued() == []` | Yes (fails without either drain call) | Pass |
| AC-2 | `tests/test_callback_pending_drain.py:160` - the same three asserts on the async twin | Yes | Pass |
| AC-3 | `tests/integration/test_callback_delivery_shapes.py:130` - `wait_until(all_hold, timeout=20)` | Weak: the overlap of the two callbacks is not forced; the evidence is the measured rate (50 of 50 failed before, 5 of 5 pass) | Pass |
| AC-4 | `tests/integration/test_callback_processor_concurrency.py:60` - `assert runs == [1]`, `assert waits == [True]`, results `PROCESSED` and `IN_PROGRESS`; `assert config.database == DATABASE_BACKEND` | Yes | Pass (both backends) |
| AC-17 | `tests/test_callback_pending_drain.py:211` - `assert s.queued() == [2]` | Yes (fails with an unconditional write) | Pass |
| AC-5 | `tests/test_resume_always_resyncs.py:83` - `[p.get("type") for p in payloads] == ["resync"]`, `stored == []`; wire row `WD12` | Yes | Pass |
| AC-6 | `tests/test_resume_always_resyncs.py:91` - `result is True`, `("resync", "status", "properties/status")`, `stored == []` | Weak: "records it" is only the return value; the caller's bookkeeping is not reached | Pass |
| AC-7 | `tests/test_notify_subscribers_whole_value.py:82` - `sent["target"] == {"settings": {"theme": "x", "deep": {"a": 1}}}`, `sent["subtarget"] == STORED`, `sent["resource"] == {"a": 1}` | Yes | Pass |
| AC-8 | `tests/test_replica_rebuild.py:796` - `seen == [(PEER, "properties", {"status": "paid"}, 5, "resync")]` on four paths, sync and async; `:886` a quiet poll: `seen == []`, the replica still holds the value | Yes | Pass |
| AC-9 | `tests/test_replica_rebuild.py:822` - `assert not result.success`, `assert seen == []` | Yes, behind two guards; sync only | Pass |
| AC-10 | `tests/test_replica_rebuild.py:833` - `types == ["resync"]`, `loops == callers[:1]` | Yes (it proves the loop, not only that the hook ran) | Pass |
| AC-11 | `tests/test_subscription_processing.py:96` - `pytest.raises(ImportError, match=r"docs/migration/v3\.16\.rst")` | Yes | Pass |
| AC-12 | `tests/test_www_trust_pages.py:125` - `assert f">{label}<" in row` for six rows, and the OAuth2 client's row keeps its two badges; browser walk | Yes | Pass - the five labels and "Waiting for peer" for approved-unverified were seen in the browser |
| AC-13 | `tests/test_www_trust_pages.py:179`; `tests/test_demo_example.py:433` - the link asserted in all four templates | Yes | Pass |
| AC-14 | `tests/test_www_trust_pages.py:190`, `:206`, `:216` - `status == 302`, `location == f"{site.www}/trust/new?error={code}"`, the message on the page, `"db-host-17" not in page`; browser walk | Yes | Pass - seen in the browser for the empty, the invalid and the unreachable submit |
| AC-15 | `tests/test_www_trust_pages.py:228`, `:245` - `create.call_args.kwargs["peer_url"] == baseuri`, `notice=trust_repaired`; `create.assert_not_called()`, `notice=trust_exists` | Weak: both tests plant an approved row, so removing the "approved only" condition passes them; the rotation itself is mocked | Pass (the browser re-walk did the real re-pair: the peer's side stayed "Active") |
| AC-16 | `tests/test_www_trust_pages.py:257` - `for text in ("evil.example", "evilrel", "alert(1)", '<div class="aw-error"'): assert text not in form`; the list likewise | Weak: a preselected `trust_type` is not asserted; no case sends a known code together with other parameters | Pass |

**The security properties the plan claims, demonstrated:**
- *Nothing from a request is rendered on the trust pages*: the test above,
  and the browser's tampered URLs showed no alert, no notice and empty
  fields.
- *A submitted value never reaches the redirect*:
  `tests/test_www_trust_pages.py:276`, `assert location ==
  f"{site.www}/trust/new?error={code}"` with a `peer_url` and description
  carrying `\r\n` and `//evil.example`, on the refused and the exception
  path.
- *A part the grant excludes beneath a `list:` key is not sent to a
  subtarget subscriber*:
  `tests/test_grant_stored_text.py::TestListDiffObjects::test_a_stored_value_under_a_list_key_is_filtered_beneath_it`,
  `assert json.loads(out) == {"theme": "x", "list:notes": {"open": 2}}`.
  **Only beneath the key: see Issue 1.**

## Remaining Tasks

- [ ] Issues 1 to 5 below, for `/iterate_plan`.
- [ ] The consumer's suite on the final commit (it ran on `d62021b`).
- [ ] The plan's own stale lines (Issue 9).

## Issues Found

### 1. The `list:` key fix filters beneath the key, not the key itself
**Severity:** Medium (a peer with a subscription to one property can reach
it; it needs an owner-stored key named `list:<x>` and an exclusion that
names that key)
**Description:** For a subtarget-level subscription a `list:<x>` key whose
value is not a list diff is filtered with `_diff_part` at
`<subtarget>/<key>`, which prunes children of that path and never asks
whether the path itself is excluded. With `excluded_patterns
["profile/list:secret"]` and `profile = {"name": "x", "list:secret":
"hunter2"}`, a subscriber to `properties/profile` is sent `list:secret`; a
direct read and a whole-target subscription are not. The reviewer confirmed
it by calling the filter. The opposite error is in the same branch (Low to
Medium): the key is first gated on the unrelated top-level name `<x>`, so
with `excluded_patterns ["secret"]` the subscriber loses a key it may read,
and applies the result as the property's whole value. The plan's recorded
residual (a stored object with `list` and `operation` keys passes whole)
stands too.
**Location:** `actingweb/actor.py:4382` `if k.startswith("list:") and
self._may_read(snapshot, k[5:])`; `:4395-4396` `value =
self._diff_part(rules, f"{subtarget}/{key}", value)`
**Recommendation:** Decide every key that is not a list diff at
`<subtarget>/<key>` (fold them into the `_diff_part(rules, subtarget, ...)`
call beside it) and keep the bare-name gate for list diffs only; tests for
the excluded key, the unrelated top-level name, and a string, a list and
`null` under such a key. The reviewer found no library code that emits a
`list:<x>`-keyed diff to a subtarget subscription; if only the two pinned
tests need the exemption, the owner may prefer to remove it there.

### 2. A quiet poll after a gap resync is not state the hook has heard
**Severity:** Medium (no attacker needed; a lost callback is enough)
**Description:** The owner's rule, a quiet poll tells no hook, rests on
"nothing changed". The gap-resync path resets the sequence to 0 and clears
the queued callbacks, none of which any hook saw, and then polls. When the
publisher retains no diff (the queued low-granularity diffs were already
fetched, or the publisher clears on 204) that poll is quiet: the replica is
healed from the baseline and a hook-driven application is told nothing of
the cleared changes. Before `b3b5300` this poll told the baseline.
**Location:** `actingweb/interface/subscription_manager.py:1333` `if
diffs_fetched == 0 and config.auto_storage:` with the comment at
`:1404-1406`; the caller at `actingweb/handlers/callbacks.py:1512`;
`actingweb/callback_processor.py:1542-1543`
**Recommendation:** Tell the baseline when the subscription's stored
sequence at the start of the poll is 0 or below the sequence the publisher
answers; stay silent only when they are equal. A test through the gap
timeout.

### 3. "Paired again" is shown when a different peer answered at the URL
**Severity:** Low (the peer at the stored URL decides the outcome, and only
when the owner submits the form; cross-site posts are refused)
**Description:** The handler matches an approved row by URL; the library
then acts on the id the URL's `/meta` answers now. If that id is another
one, a second row is created and approved while the page says "It was
paired again with a new secret; nothing else was changed". With two rows at
one base URI the first one found decides between the two notices.
**Location:** `actingweb/handlers/www.py:1155` `"/trust?notice=trust_repaired"
if existing else "/trust",`
**Recommendation:** Show `trust_repaired` only when the returned row's peer
id is the matched row's; otherwise redirect without a notice.

### 4. A malformed port matches the stored peer
**Severity:** Low (authenticated owner only; the request goes to the stored
URI, so no secret leaves for another host)
**Description:** `_same_peer_url` reads a port it cannot parse as the
default port, and ignores userinfo, query and fragment, so
`https://peer.example:not-a-port/actor` matches `https://peer.example/actor`
and rotates the secret with no error.
**Location:** `actingweb/handlers/www.py:64-65` `except ValueError:` /
`port = None`
**Recommendation:** A `ValueError` on the port is no match; refuse a URL
`is_valid_peer_baseuri` refuses before matching.

### 5. Four acceptance criteria have weak tests
**Severity:** Low
**Description:** AC-3 does not force the overlap it tests; AC-6 does not
reach the bookkeeping that records a resume; AC-15 has no row waiting for
approval, so the "approved only" condition can be removed unnoticed (the
test that pins the approval path, `tests/test_trust_re_pair.py:1431`,
asserts no notice either way); AC-16 does not assert the select and sends
no known code with other parameters.
**Location:** as cited in the table above
**Recommendation:** Add the four cases with the fixes of Issues 1 to 4.

### 6. No test joins a publisher's holed list to a subscriber's resync
**Severity:** Low
**Description:** `TestResyncSkipsCorruptedListsOnly` tested the removed
full-state function and was deleted. What a resync's baseline read does for
a publisher with a holed list is unchanged, and untested as one behaviour.
**Location:** `tests/integration/test_property_list_repair.py` (the class
is gone)
**Recommendation:** One wire-level test, or accept and say so in the
release validation.

### 7. A resync is not fenced against a diff in progress, and drops or strands what is queued above it
**Severity:** Low on this branch (both predate it; the publisher's own
timing only)
**Description:** A diff's handler that finishes after a resync landed
writes its older sequence over the resync's (`callback_processor.py:818`,
unconditional, as on `master`). A resync clears the whole queue, a callback
above its own sequence included, and does not drain what is queued after
the clear. Phase 2 makes the resync the normal resume path, so both are
met more often: suspend, bulk write, resume, one more write can leave a
quiet subscription without the last write until later traffic.
**Location:** `actingweb/callback_processor.py:818`, `:1680`, `:1721`
**Recommendation:** Recorded in
`thoughts/todo/subscription-subscriber-fault-hardening.md` by this
verification; the release validation should weigh it against rc1.

### 8. Browser, low
**Severity:** Low
**Description:** The demo's "New trust" hover label is 4.40:1 in the dark
scheme (4.5:1 asked of small text). The demo's legend describes "Waiting
for peer" as "you approved; the peer has not yet", which does not cover the
approved-but-unverified row, and its "Relationship Types" list names
`acquaintance`, which the form does not offer (the second predates the
plan).
**Location:** `examples/demo/templates/aw-actor-www-trust.html`
**Recommendation:** One legend line; the rest is the demo's styling.

### 9. Hygiene
**Severity:** Low
**Description:**
- `examples/demo/templates/aw-actor-www-root.html` was rewritten from CRLF
  to LF line endings (563 changed lines for a 3-line change); no phase
  mentions it.
- `.oss-scanner/threat_model.md:119` still lists
  `handlers/callback_oauth.py` as a handler.
- The plan contradicts itself in three places the later section supersedes:
  the Phase 2 note that a quiet poll tells the hook every time, "Not fixed,
  filed" for the `list:` key, and Phase 3's test path under
  `tests/integration/`.
- Two commits carry a todo deletion that belongs to the phase after them
  (`09823be`, `334fdaf`); the tree at each phase commit is right.
**Recommendation:** Fix the plan's lines and the threat model entry in the
iteration; say in the PR that the template's line endings changed.

## Todos checked against the plan

Deleted with their index rows: `low-granularity-concurrent-writes-replica`,
`callback-concurrency-test-sequential-postgresql`,
`full-state-fallback-replica`, `callback-oauth-handler-unrouted`,
`web-ui-trust-page-gaps`, and `subtarget-diff-list-key-exclusion` (filed
and closed inside the plan; Issue 1 reopens its subject).
`subscriber-hooks-and-resource-diffs-after-1-5` is trimmed to what is left.
`demo-qa-mode-basic-auth-challenge` exists with its row. Every todo file
has an index row and every row has its file. The changelog and `docs/` name
no consumer in the lines this branch added.

## Spec Merge

- None. The repository keeps no `thoughts/specs/`; the plan's Spec Delta
  says so and names the documentation pages each phase changed instead. The
  protocol specification (`docs/protocol/actingweb-spec.rst`) was reworded
  in Phase 2 itself, by the owner's decision.

## Overall Assessment

The plan landed: the six todos are closed, each acceptance criterion has a
test that passes on both backends where it has a backend, the receiver's
race is reproduced and gone, the fallback is removed with its wire row
re-recorded, and the trust pages were exercised in a browser twice, the
second time with a real peer for the re-pair. Nothing High is open.

It is not clean by the owner's stop rule. Two Medium findings stand against
the last commit, both in the two decisions made after the implementation:
the `list:` key filter still sends a key the grant excludes by its own path
(peer-reachable, narrow), and a quiet poll that follows a gap resync leaves
a hook-driven application without the changes the resync discarded. Both
are small and have a clear remedy; they, the two low findings on the
re-pair match, and the four weak tests are one iteration. The consumer's
suite has not run on the final commit, and that iteration will change the
same code, so it should run after it. Before the PR: that iteration, the
suite, and the check for unreleased security records on the branch.
