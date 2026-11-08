# Verification: peer authorisation fixes (fourth run: the whole-branch review)

**Date:** 2026-11-08
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 7fc2f48

This run verifies Iterations 25 to 31 (`dca966f..7fc2f48`), which answered
`verifications/2026-11-08-peer-authorisation-fixes-reverify-3.md`, and
carries the owner's decision of iteration 25: one review of the whole
branch, `master...HEAD`, by three providers with no earlier findings in
their brief.

## Automated Check Results

- **Browser QA:** N/A. No phase or iteration changes a page.
- **Whole-branch review (iteration 25), three providers:**
  - **Built-in security review** (`/security-review` flow, scan plus
    false-positive filter at confidence 8): **no finding** at HIGH or
    MEDIUM. It checked the access binding, `/callbacks`, `/subscriptions`,
    `/trust` (re-pair, replacement, redaction, base URI), `/permissions`,
    the initiator's re-pair, SQL and DynamoDB conditions, logging and the
    new outbound `/meta` request. Two items below its bar (a secret-in-use
    oracle against full-strength tokens; `peer_approved` on a pending row
    proven by its own creator).
  - **Built-in code review** (`/code-review high master...fix/3.16.0-peer-authorisation`):
    ten candidates; I checked each against the code (Issues 1, 2, 4, 6, 8,
    9, 10, 14, 15 below; its `time.sleep` item is the owner's accepted
    cost).
  - **Outside voice** (codex `codex exec -s read-only` outside the
    sandbox, and a fresh-context Claude reviewer) on `git diff master --
    actingweb examples` and the security docs: ten findings, two unverified
    notes. Neither found a way for a peer to reach another peer's rows or
    secret. Checked against the code (Issues 3, 5, 6, 7, 10 to 13 below;
    two are accepted or below the bar, see Notes).
- **Full tier**, run on the exact tree committed as `7fc2f48`:
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6056 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5853 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed.
- **Emm's suite:** last run on `dca966f` (baseline on both backends,
  reverify-3). Not re-run on `7fc2f48`: the delta changes only the
  permission-callback restore, the sender's log, `prune`'s rebuild fault
  and the replacement log, none on a path Emm's suite exercises. Re-run
  after the next code change, before the PR.

## Phase Verification

### Iterations 25 to 31 - VERIFIED

**Changes verified:**
- `actingweb/handlers/callbacks.py` `_still_granted` and the three exits
  of the permission branch: the stored path filters by `peer_perms`, the
  ignored path by the row read, the 503 exit re-reads and filters. Matches
  iteration 26.
- `actingweb/trust_permissions.py` `_notify_peer`: success only on a 2xx
  `last_response_code`, WARNING with the status otherwise. Matches 27.
- `actingweb/maintenance/peer_state.py` `_rebuild_copy`: query and store
  inside one `except DbError`. Matches 28.
- `actingweb/peer_permissions.py` `store_permissions`: the stored
  `sender_timestamp` carried into a query copy. Matches 29 (the callback
  path does not carry it: Issue 6).
- `actingweb/actor.py`: the replacement WARNING after the conditional
  write. Matches 30.
- `CHANGELOG.rst`, `docs/migration/v3.16.rst`: storage fault named, the
  restore best effort. Matches 31.

**Tests verified** (each failed before its fix, checked by stashing the
code): `test_a_revocation_that_loses_to_another_revocation_restores_nothing`,
`test_the_503_exit_restores_what_the_stored_copy_grants`,
`test_a_query_copy_keeps_the_last_callbacks_timestamp`
(`tests/test_peer_binding.py`); `test_the_sync_sender_gives_up_after_two_resends`
(`tests/test_trust_permissions_unit.py`, now asserts the WARNING);
`test_a_fault_while_querying_the_peer_is_listed`
(`tests/test_peer_state_command.py`);
`test_a_replacement_that_loses_is_not_logged_as_one`
(`tests/test_trust_re_pair.py`; tightened after it first passed without
the fix).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The restore filters by the last diff | Fixed | iteration 26; `callbacks.py` `_still_granted` |
| 2. The sync sender logs a final 503 as success | Fixed | iteration 27 |
| 3. A fault in the rebuild's fetch escapes `prune` | Fixed; its exit code does not show it (Issue 7) | iteration 28 |
| 4. A query copy drops the sender timestamp | Fixed for the query path; the callback path still drops it (Issue 6) | iteration 29 |
| 5. The replacement WARNING precedes the write | Fixed | iteration 30 |
| 6. The 503 exit restores nothing | Fixed | iteration 26 |
| 7. The 503 causes and the restore's limits | Fixed | iteration 31 |

## Remaining Tasks

- [ ] Owner decisions on Issues 2 and 4 (they change what consumers must
      do), then `/iterate_plan` for Issues 1 to 15 as decided.
- [ ] Emm's suite after that iteration, before the PR.
- Todos: the plan closes none; its deferral
  `thoughts/todo/full-state-fallback-replica.md` has its `INDEX.md` row.

## Issues Found

No provider found a way for a peer to read, write or delete another
peer's state, obtain another peer's secret, or act unauthenticated. The
issues are behaviour regressions, unconditional writes the branch left,
consistency gaps and hygiene.

### Issue 1: an owner's "create trust" toward a peer with a pending inbound request no longer approves it
**Severity:** Medium
**Description:** `create_reciprocal_trust` (and its async twin) treat any
existing row as a re-pair (`actor.py:1718`, `if existing:`). When peer B
has asked A for trust (A holds `approved=False`, `verified=True`) and A's
owner then creates the trust toward B, the re-pair swaps the secret and,
on B's 201, `_finish_re_pair` runs only
`current.modify(secret=secret, peer_approved=status == 201)`
(`actor.py:2146`). A's row stays unapproved, so A refuses B's requests,
while the call returns the trust as if it had succeeded. Before the
branch the upsert wrote `approved=True`.
**Location:** `actingweb/actor.py:1718-1745`, `:2146`
**Recommendation:** when the owner initiates toward a peer whose row is
unapproved, approve it (the owner's action is the approval), or refuse
with a message pointing at the approval route; a test either way.

### Issue 2: `owner` access rows never match on `authorize()` paths
**Severity:** Medium (owner decision)
**Description:** `AuthResult.authorize` passes `path_peer` but no `peerid`
to `check_authorisation` (`base_handler.py:397-399`), and `owner` rows
match only when `len(peerid) > 0 and self.acl["peerid"] == peerid`
(`auth.py:858-861`). So `("owner", "subscriptions", "", "a")` and
`("owner", "trust/<type>/<id>", "", "a")` (`config.py:330`, `:337`) never
admit anything on the subscription and trust peer handlers. This predates
the branch, but the branch now authorises a subscription PUT or DELETE as
itself, which is why a subscriber type without PUT/DELETE rows needs the
two adoption rows (migration guide; Emm's worktree carries them). Passing
`peerid=path_peer` would let the `owner` rows admit a peer's own paths,
with the path binding still holding the caller to its own id, and would
remove that adoption step. It would also admit every method on a peer's
own trust row (the handlers' own refusals for approving and permissions
stay).
**Location:** `actingweb/handlers/base_handler.py:397-399`
**Recommendation:** owner decision: pass `peerid=path_peer` (and drop the
adoption rows from the migration guide) or keep the explicit rows and
document why the `owner` rows are inert.

### Issue 3: the initiator creates its row unconditionally and deletes it on failure
**Severity:** Medium
**Description:** after reading "no row" (`actor.py:1715`), the initiator
writes with a plain upsert (`:1749-1759`, `dbtrust.create(...
approved=True, verified=True ...)`, no `only_if_absent`) and, when the
peer refuses, deletes the row (`:1818-1821`, `dbtrust.delete()`); the
async twin repeats both. A request from the same peer landing between the
read and the write is replaced, then possibly deleted. `CHANGELOG.rst`
says "A new row is written conditionally, so a request racing another
never replaces its row", which holds only on the receiving side.
**Location:** `actingweb/actor.py:1749-1759`, `:1818-1821`; async twin
**Recommendation:** `only_if_absent=True` on both initiator creates; on
failure delete only a row that still holds this call's secret.

### Issue 4: `FanOutManager`'s granularity downgrade is live but unfetchable
**Severity:** Medium (owner decision)
**Description:** a payload over `max_payload_size` is still sent as a
low-granularity callback with a resource URL (`fanout.py:526`), but a 3.16
subscriber fetches `<baseuri>/subscriptions/<own>/<subid>/<seq>`, where no
diff exists for it: 404, the subscriber answers 503 on every redelivery,
the sequence stalls and the publisher's circuit breaker opens for that
peer. The CHANGELOG's Check names the incompatibility; the code path is
still reachable.
**Location:** `actingweb/fanout.py:526`
**Recommendation:** owner decision: store a diff the subscriber can fetch
before downgrading, or stop downgrading (send in full, or skip with an
ERROR), with a test.

### Issue 5: a revocation from a multi-instance sender can be dropped silently
**Severity:** Medium
**Description:** callbacks are ordered by the sending process's clock
(`trust_permissions.py:531`), compared with the last stored sender
timestamp (`callbacks.py:401-424`). Two sender instances a few seconds
apart (allowed by the five-minute skew window) can make a revoke look
older than the grant before it; the receiver logs at INFO and answers 204,
so the sender sees success and `auto_delete_on_revocation` never runs
until the next query.
**Location:** `actingweb/handlers/callbacks.py:401-424`
**Recommendation:** when an ignored callback would have revoked something
against the stored copy, run a permission query to the peer (its current
state is the truth) and log at WARNING; a test.

### Issue 6: a callback without a timestamp erases the stored sender timestamp
**Severity:** Low
**Description:** `callbacks.py:373-377` stores `extra_attributes={}` when
the body has no `timestamp`, and `replace_permissions` stores it whole, so
a later resend of an older callback is no longer recognised as older.
`store_permissions` carries the value forward on the query path only.
**Location:** `actingweb/handlers/callbacks.py:373-377`
**Recommendation:** carry the stored `sender_timestamp` forward on the
callback path too; a test.

### Issue 7: `prune --apply` exits 1 when a copy was not rebuilt
**Severity:** Low
**Description:** `cmd_prune` returns 1 (`peer_state.py:337`) whatever the
rebuild did; a `not rebuilt` line is the only signal, so a script cannot
tell a deleted-and-unrebuilt copy from a normal run.
**Location:** `actingweb/maintenance/peer_state.py:327-337`
**Recommendation:** exit 2 when any copy was not rebuilt; say so in the
guide and the changelog.

### Issue 8: the async re-pair POST catches only `httpx.HTTPError`
**Severity:** Low
**Description:** `actor.py:1896` `except httpx.HTTPError` while the sync
path and both probes catch `Exception`: an `httpx.InvalidURL` or a stream
error escapes as a 500 and the probe never runs.
**Location:** `actingweb/actor.py:1896`
**Recommendation:** `except Exception` with the "peer HTTP only" marker,
as the sync path.

### Issue 9: `DELETE /callbacks/subscriptions/<peer>/<subid>` is ambiguous about which row it deletes
**Severity:** Low
**Description:** the POST branch requires `callback=true`; the DELETE
branch calls `delete_callback_subscription` (our subscription to the
peer, `callback=True`), while the handler's comment says "they're deleting
their subscription to us" and loads hook data with `callback=False`
(`callbacks.py:212-226`). Both rows involve only the path's peer (the
binding holds), but the hook may receive the wrong row's data.
**Location:** `actingweb/handlers/callbacks.py:205-245`
**Recommendation:** align the comment and the hook's lookup with
`callback=True`.

### Issue 10: DynamoDB `modify` compares with the loaded copy, not the database
**Severity:** Low
**Description:** `db/dynamodb/trust.py:322-325` writes only attributes
that differ from the handle and returns True with no write when none do.
A stale handle whose cached value equals the new one writes nothing even
when the database differs, and a deleted row reads as success; PostgreSQL
returns False there. Reverify-1 accepted the no-change difference; this
is the wider consequence.
**Location:** `actingweb/db/dynamodb/trust.py:322-325`
**Recommendation:** write every attribute passed (conditioned on the row
existing), as PostgreSQL does.

### Issue 11: an owner's approval can land on a replaced pending row
**Severity:** Low
**Description:** a pending row can be replaced conditionally
(`only_if_pending`), and the owner's approval `modify` is conditioned only
on the row existing (`db/dynamodb/trust.py:328`): approving a request the
owner looked at a moment before approves its replacement (another base
URI and secret).
**Location:** `actingweb/handlers/trust.py` (the approval PUT);
`actingweb/db/dynamodb/trust.py:328`
**Recommendation:** document that approval applies to the current row, or
condition it on the base URI the owner saw.

### Issue 12: a replaced pending row keeps the old `created_at` on PostgreSQL
**Severity:** Low
**Description:** `_TRUST_UPSERT`'s update list has no `created_at`
(`db/postgresql/trust.py`), while DynamoDB writes the whole item.
**Location:** `actingweb/db/postgresql/trust.py` `_TRUST_UPSERT`
**Recommendation:** set `created_at = EXCLUDED.created_at` under
`only_if_pending`.

### Issue 13: the security reference's heading overstates
**Severity:** Low
**Description:** "**A trust request never replaces a trust row**" heads
an item that describes a pending row being replaced.
**Location:** `docs/reference/security.rst:113`
**Recommendation:** "never replaces a verified or approved trust row".

### Issue 14: new parameters without type hints
**Severity:** Low
**Description:** `db/dynamodb/trust.py:370-371` `only_if_absent=False,
only_if_pending=False` and `CallbacksHandler.post(self, actor_id, name,
method: str = "POST")` (`callbacks.py:282`) are unannotated; CLAUDE.md
requires type hints, and the PostgreSQL twin annotates the same
parameters.
**Location:** as above
**Recommendation:** annotate.

### Issue 15: the re-pair code exists in four copies
**Severity:** Low
**Description:** `proven` is computed in `post()` and again in
`_re_pair()` (`handlers/trust.py:445`, `:558`); the initiator's re-pair
block and `_re_pair_unknown` are duplicated for async, and the copies have
already drifted (Issue 8).
**Location:** `actingweb/handlers/trust.py:445`, `:558`; `actingweb/actor.py`
**Recommendation:** pass `proven` into `_re_pair`; share one request and
answer helper between the twins.

### Notes (accepted or below the bar)
- Two proven re-pairs from the same peer at once are last-writer-wins
  (outside voice finding 2): accepted in reverify-1; only the real peer
  can cause it.
- Secret uniqueness is check-then-write (`actor.py:2362` before `:2366`;
  the creation path already did): a collision needs another peer's secret.
- The synchronous resend blocks the owner's request (code review): the
  owner's iteration 18 decision.
- A DynamoDB row with no `verified` attribute fails the
  `only_if_pending` condition and is refused as "a row was created
  meanwhile" (outside voice, unverified): rows written by this library
  always carry it.

## Overall Assessment

The whole-branch review did what the owner asked for: three providers,
none anchored on earlier rounds. The security review found nothing at
HIGH or MEDIUM, and neither of the other two found a way for a peer to
reach another peer's rows or secret, so the branch's security goal holds
across all its iterations. Iterations 25 to 31 closed reverify-3's seven
issues with tests that failed before. Both backends are green, the docs
build, no recording changed.

What the fresh read found is of a different kind than the delta rounds:
one behaviour regression an owner would notice (Issue 1), two pieces of
existing design the branch now leans on (Issues 2 and 4, which need owner
decisions because they change what consumers do), the initiator's
unconditional write the receiving side's guarantee does not cover
(Issue 3), and a silent drop of a revocation from a multi-instance sender
(Issue 5). The rest are small. I would fix Issues 1, 3 and 5, decide 2
and 4, fold 6 to 15, run Emm's suite, and verify that delta before the PR.
