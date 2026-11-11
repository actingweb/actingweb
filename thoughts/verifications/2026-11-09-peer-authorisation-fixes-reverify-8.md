# Verification: peer authorisation fixes (eighth run: reverify-7's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 244ccb9

This run verifies Iterations 56 to 68 (`6d6784b..244ccb9`), which answered
`verifications/2026-11-09-peer-authorisation-fixes-reverify-7.md` Issues 1
to 12 (owner: "include all").

## Automated Check Results

- **Outside voice:**
  - **Codex** (`codex exec -s read-only` outside the sandbox) reviewed a
    stale diff file left in the temp directory, not this range. Its
    findings cite files outside the range and were not triaged.
  - **The fresh-context Claude reviewer** reviewed the range:
    - it found Issues 1, 3, 5, 6 and 7;
    - it confirmed the mirror attack closed on two independent counts;
    - it confirmed that `master`'s initiator still pairs: its row is
      approved, and its GET answers 200 with a boolean.
- **Built-in code review** (`/code-review high 6d6784b..244ccb9`): nine
  findings, each checked against the code here: Issues 1, 2, 4, 6, 8 and 9.
- **Built-in security review** (`/security-review` flow, scoped to the
  range, confidence bar 8): no finding at or above the bar.
  - It found every change narrows access.
  - The HTML refusal body is a constant, escaped.
  - The SQL condition is a literal.
- **Browser QA:** not repeated in this run. The walk recorded in iteration
  61 (gstack browse, demo in local QA mode on `:5055`, throwaway actors
  deleted) ran against the templates committed in `244ccb9`:
  - the unverified request is marked, red, with no Approve;
  - the hint is readable at 1280 px and 375 px;
  - the refusal page links back;
  - a pasted Approve URL meets the cross-site guard.
- **Full tier** on `244ccb9`:
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6127 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5924 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed: the tree is clean after the runs.
- **Emm's suite** on `244ccb9`:
  - **Set-up.** The library worktree was re-pointed and Emm's adoption
    worktree reinstalled (unchanged). The environment 9 server was stopped
    afterwards.
  - **PostgreSQL** (`scripts/with-preview-env.sh 9 poetry run pytest
    --timeout=180 --deselect tests/test_dependency_pin_guard.py`): **2
    failed / 7406 passed**:
    - `test_dynamodb_iam_coverage::test_role_grants_every_dynamodb_action_the_backend_uses`;
    - `test_stripe_integration::…test_create_subscription_proceeds_with_expired_apple_subscription`.
  - **DynamoDB** (`scripts/test-backends.sh 9`): **3 failed / 54 passed**:
    - the two `test_dynamodb_operation_profile` tests;
    - `test_restore_actor_dynamodb::…test_full_force_import_caps_and_confirms_the_wipe`.
  - All five are the `master` baseline's failures by name
    (`research/2026-11-07-emm-suite-against-master.md`). Iteration 56's
    change to what a verification accepts breaks nothing in Emm.

## Phase Verification

### Iterations 56 to 68 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **56, the approved answer.**
  - `actor.py` `_answered_by_approved_row` is used by the creation
    verification and by `reverify_pending_trust`.
  - `handlers/trust.py` `TrustPeerHandler.get` drops `verification_token`
    for a pending row's own peer.
  - Residue: the POST 202 answer still carries it (Issue 7).
- **57, the subtarget exclusions.**
  - `PermissionEvaluator.excluded_property_paths` names only `denied` and
    `excluded_patterns` matches.
  - `filter_subscription_blob` drops those keys.
  - It evaluates twice (Issue 9).
- **58, the bulk evaluation** in `_filter_subscription_data_by_permissions`.
- **59, the approval write.** `modify_trust_and_notify` passes
  `only_if_secret` and returns before notifying when nothing was written.
- **60, re-approval.** `only_if_verified` is now verified OR approved on
  both backends (`db/dynamodb/trust.py`, `db/postgresql/trust.py`).
- **61, the refusal and the trust page.**
  `TrustPeerHandler._refuse_unverified_approval`, and both templates.
- **62, `TrustManager.modify_trust`.** It re-verifies; its write has no
  `only_if_secret` (Issue 4).
- **63, the owner's create.** Both twins gate the second check on an empty
  `_re_pair_refusal`.
- **64, the PUT.** 404 for a missing row, 400 for an approval with a move.
  Residue in Issue 6.
- **65, the no-row gate.** `_is_unapproved` denies a missing row. It also
  denies `as_client(client_id)` views (Issue 2).
- **66, the bounded second check.** `_bounded_get_json` follows no
  redirect and caps the size, but its deadline does not hold (Issue 1).
- **67 and 68, the docs and the spec.** The approved-answer rule is in the
  spec. Two stale passages remain (Issue 8).

**Security properties, demonstrated (test, then what it asserts):**
- **The mirror:** `tests/test_trust_re_pair.py`
  `TestTheMirroredRequestAfterReverify7`.
  - `test_the_mirrored_request_is_not_verified_or_approved` asserts B's
    row stays `verified False, approved False`.
  - `test_the_second_check_refuses_the_planted_request` asserts A's second
    check and `modify_trust_and_notify` refuse it, with no notification.
  - Both run two actors through the real handlers, and both failed before
    with B verified.
- **No token for a pending peer:** `test_a_pending_rows_own_peer_reads_no_token`;
  the control is `test_an_approved_rows_own_peer_still_reads_it`.
- **Subtarget exclusion:** `tests/test_peer_paths_binding.py`
  `test_a_subtarget_subscription_gets_no_excluded_resource`. The pull reads
  `{}`, and the push body holds no `hidden`.
- **The approval lands on the row read:**
  `test_a_failed_approval_write_tells_the_peer_nothing`.
- **No row, no grant:** `test_a_peer_with_no_trust_row_gets_nothing`
  asserts DENIED for an orphan override.

**The spec check.** The approved-answer rule (`actingweb-spec.rst`, after the
reverse-URL paragraph) sits within the spec's own step 1 ("200 OK"). The
POST answer contradicts it (Issue 7).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-7.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Mirrored pending rows pass verification | Fixed (POST residue, Issue 7) | iteration 56; two-actor tests |
| 2. Subtarget subscription gets an excluded resource | Fixed | iteration 57 |
| 3. Notify after a failed write | Fixed | iteration 59 |
| 4. Approved-unverified rows refuse `approved=true` | Fixed | iteration 60 |
| 5. Blank 403, Approve offered | Fixed (browser walk) | iteration 61 |
| 6. `modify_trust` named as re-verifying | Fixed (it does now; residue Issue 4) | iteration 62 |
| 7. Create refuses a re-verified mismatch | Fixed | iteration 63 |
| 8. PUT 403 for a missing row, a move probes the old URI | Fixed (residue Issue 6) | iteration 64 |
| 9. No row passes `_is_unapproved` | Fixed (side effect, Issue 2) | iteration 65 |
| 10. Second check unbounded | Partly: no redirects, size capped; the deadline does not hold (Issue 1) | iteration 66 |
| 11. Extra trust read per key | Fixed for whole-target diffs (subtarget residue, Issue 9) | iteration 58 |
| 12. Probe, 503, `fetched_at` | Accepted and documented | iteration 67 |
| Note: non-`properties` targets | Decided: the application's | Decisions Made |

## Remaining Tasks

- [ ] `/iterate_plan` for Issues 1 to 9 below. None is a hole in the mirror
      fix. Issues 1 to 3 are medium.
- [ ] Emm's suite again only if that iteration changes what Emm can see:
      `as_client` (Issue 2) is one.
- Todos unchanged: `grant-enforcement-per-route.md` (A5 to A20, with the
  delivery of a subtarget's keys the grant does not name, see the note
  under Issues), `web-ui-trust-page-gaps.md`, `full-state-fallback-replica.md`.

## Issues Found

### Issue 1: the second check's 15-second deadline does not hold
**Severity:** Medium (both reviewers)
**Description:**
- **Where the deadline is checked.** `_bounded_get_json` tests it only
  between chunks: `for chunk in answer.iter_content(chunk_size=4096)` at
  `actor.py:81`.
- **Why that is not enough.** Each chunk read waits for 4096 bytes or EOF,
  and `timeout=(5, 5)` is per socket read. A base URI that sends a byte
  every 4.9 s holds the owner's PUT or create for hours. Headers sent
  slowly are not bounded at all.
- **The claim it falsifies.** The changelog's "within 15 seconds".
**Location:** `actingweb/actor.py:62-90`
**Recommendation:**
- Run the GET under a real wall-clock limit (a worker thread with
  `join(timeout)`), or read in small pieces while lowering the socket
  timeout to the time left.
- Add a direct test with a slow fake.

### Issue 2: `as_client(client_id)` views are now denied everything
**Severity:** Medium (a behaviour change to a documented API, not in the
changelog)
**Description:**
- **The documented use.** `actor.as_client(client_id="mcp_chatgpt", …)`
  (`docs/sdk/authenticated-views.rst:62`) sets the accessor to the raw
  client id (`authenticated_views.py:47-49`).
- **Why it is denied.** OAuth trust rows are stored under
  `oauth2_client:<email>:<client>`, so iteration 65's no-row gate
  (`permission_evaluator.py`, `_is_unapproved`) now answers DENIED. Every
  property read and write in such a view raises `PermissionError`, where it
  used to fall through as NOT_FOUND.
- **What still works.** The library's own MCP and `base_handler` paths pass
  the trust row's peer id. Emm's suite is unaffected.
**Location:** `actingweb/permission_evaluator.py` (`_is_unapproved`),
`actingweb/interface/authenticated_views.py:47`
**Recommendation:**
- Resolve a client view's accessor to its trust row (by `oauth_client_id`)
  before evaluating, or name the change in the changelog and the SDK page.
- Test `as_client` with a real OAuth trust.

### Issue 3: the first verification, which anyone can trigger, is still unbounded
**Severity:** Medium (pre-existing on `master`; next to Issue 1)
**Description:** `create_verified_trust` still fetches with
`requests.get(url=requrl, headers=headers, timeout=(5, 10))`
(`actor.py:2468`). That fetch:
- reads the whole body;
- follows redirects;
- is triggered by an unauthenticated `POST /trust/<rel>` with a base URI
  the requester chooses.

Iteration 66 bounded only the owner-triggered second check.
**Location:** `actingweb/actor.py:2468`
**Recommendation:** route it through the bounded helper, once Issue 1 is
fixed.

### Issue 4: `TrustManager.modify_trust`'s approval is not tied to the row it re-verified
**Severity:** Low
**Description:** `TrustManager.modify_trust` re-verifies, then writes
`approved=True` without `only_if_secret` (`interface/trust_manager.py:915`).
A verified row that replaced the one read in between is approved unseen.
`modify_trust_and_notify` already guards this (iteration 59).
**Recommendation:** pass `only_if_secret=row["secret"]` when approving.

### Issue 5: a string `approved` skips both gates
**Severity:** Low (application code)
**Description:**
- **Where.** `kwargs.get("approved") is True`
  (`interface/trust_manager.py:903`) and
  `only_if_verified=approved is True` (`trust.py:399`).
- **Effect.** `modify_trust(peer, approved="true")` re-verifies nothing
  and writes with no condition. PynamoDB stores a non-empty string as
  True, even `"false"`.
**Recommendation:** convert to a bool at both entry points.

### Issue 6: PUT edges
**Severity:** Low
**Description:**
- **The wrong relationship.** `current = myself.get_trust_relationship(peerid=peerid)`
  (`handlers/trust.py:938`) ignores the relationship in the path. A PUT to
  `/trust/admin/<peer>` on a `friend` row re-verifies the row (an outbound
  GET, and possibly `verified=True`), then fails to modify it.
- **A non-string base URI.** `baseuri.rstrip("/")` (`:945`) runs before
  `is_valid_peer_baseuri`, so a body such as `{"approved": true,
  "baseuri": 5}` answers 500, not 400.
**Recommendation:**
- Answer 404 when the row's relationship differs.
- Validate the base URI before comparing it.

### Issue 7: the POST answer gives a pending row's requester its verification token
**Severity:** Low (the mirror stays closed: the approved-answer rule, and
the GET's withheld token, each stop it)
**Description:** `out = json.dumps(new_trust)` (`handlers/trust.py:537`)
returns the created row, `verification_token` included. That contradicts
the spec sentence iteration 68 added: "A MUST NOT return the verification
token from a relationship it has not approved".
**Recommendation:** drop `verification_token` (and `secret`) from the 202
body.

### Issue 8: two stale passages say a pending row's peer gets its token
**Severity:** Low (docs)
**Description:**
- `docs/reference/security.rst:110`: "the per-relationship GET returns them
  to … the peer reading its own row".
- The comment at `handlers/trust.py:707-713` says the same.

Someone "restoring" what they describe would reopen the mirror.
**Recommendation:** say "its own approved row" in both.

### Issue 9: hygiene and cost
**Severity:** Low
**Description:**
- **Two evaluations per diff.** A subtarget subscription without a resource
  evaluates each diff twice: `evaluate_property_access`, then
  `excluded_property_paths` (`actor.py:3566-3594`).
- **Dead conditions.** `or not evaluator` is unreachable after `allowed`,
  and `existing and` beside `_is_unproven_pending(existing)` is redundant.
- **A misleading log line.** The creation verification's debug line
  (`actor.py:2483`) calls `data.get` before the dict check, so an array
  answer logs "No response".
- **No `list:` stripping.** `excluded_property_paths` does not strip a
  `list:` prefix.
- **Untested.** `_bounded_get_json` has no test of its deadline or
  streaming.
**Recommendation:**
- Derive the allow decision and the exclusions from one read of the
  effective permissions.
- Tidy the rest with Issue 1.

**Note** (no finding): under a subtarget subscription, keys the grant
merely does not name are delivered, and only exclusions are dropped. This is
iteration 57's deliberate choice: it matches a direct read of the parent,
and the parent read is the deferred A5.

## Overall Assessment

The fixes for reverify-7 hold:
- **The mirror attack is closed** on two independent counts, pinned by a
  two-actor test through the real handlers. No provider found a way around
  it.
- **The rest is in place:** the subtarget exclusions, the approval tied to
  the row read, the re-approval of approved rows, the refusal page and the
  trust page, and the no-row gate.
- **The checks are green.** The Full tier on both backends: DynamoDB 6127,
  PostgreSQL 5924. Emm's suite matches its baseline on both backends.

What stands before the PR is smaller than before:
- the second check's deadline does not hold (Issue 1);
- the no-row gate denies `as_client(client_id)` views without a changelog
  line (Issue 2);
- the anonymous first verification is still unbounded (Issue 3,
  pre-existing);
- six low items, among them the POST answer contradicting the new spec
  sentence and two stale passages.

One more iteration should close these. A full re-review is not needed
unless that iteration touches the verification rule.
