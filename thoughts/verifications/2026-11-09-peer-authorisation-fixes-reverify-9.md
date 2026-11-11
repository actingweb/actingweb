# Verification: peer authorisation fixes (ninth run: reverify-8's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 9b0c6c0 (code as of 20abc3a; 9b0c6c0 adds records only)

This run verifies Iterations 69 to 75 (`34e5370..20abc3a`), which answered
`verifications/2026-11-09-peer-authorisation-fixes-reverify-8.md` Issues 1
to 9 (owner: all nine; a client view resolves to its trust row).

## Automated Check Results

- **Outside voice:**
  - **Codex** (`codex exec -s read-only` outside the sandbox). Its first run
    hung on stdin and was killed. The rerun ran the exact `git diff
    34e5370..20abc3a` and read no stale file. It found Issues 1, 2 and 3,
    and the hardening in Issue 5.
  - **The fresh-context Claude reviewer** found Issues 1, 2, 3 and 6. It
    also checked that the 2xx requirement breaks no older peer (`master`'s
    approved row answers 200), and that the worker touches no database or
    context.
- **Built-in code review** (`/code-review high 34e5370..20abc3a`): ten
  findings, each checked against the code here: Issues 1, 2 and 4 to 7.
  - Its claim about the FastAPI single-segment PUT is not a regression: on
    `master` an empty relationship already makes `modify_trust_and_notify`
    return False. Only the status changed, from 400 to 404 (note below).
- **Built-in security review** (`/security-review` flow, scoped to the
  range, confidence bar 8): no finding at or above the bar.
  - It found every change tightens, or matches what came before.
  - It noted that a caller-supplied trust dict reaches `as_client` only
    from application code.
- **Browser QA:** N/A. No template or page changed in this range.
- **Full tier** on `20abc3a`:
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6138 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5935 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - Wire: WT3 was re-recorded in iteration 73 (the 202 body lost `secret`
    and `verification_token`). The tree is clean after the runs.
- **Emm's suite** on `20abc3a` (recorded in the plan, code unchanged since):
  PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54 passed, the
  baseline's failures by name.

## Phase Verification

### Iterations 69 to 75 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **69, the client view.** `authenticated_views.py`
  `_client_trust_peer_id`, `AuthContext.client_peer_id` and
  `permission_id`. All four permission checks evaluate `permission_id`;
  `accessor_id` is unchanged. Residue: Issue 5.
- **70, the bounded GET.** `actor.py` `_bounded_get_json`, `_fetch_json`
  and the eight-worker `aw-verify` pool. The creation verification uses it
  and needs a 2xx.
  - The caller returns within the deadline (tested).
  - The `/meta` step that follows is not bounded (Issue 1).
  - A worker is not released (Issue 2).
- **71, flags.** `trust.py` `_as_flag`; `modify_trust` converts the flag
  and passes `only_if_secret`. Residue: Issue 3.
- **72, the PUT.** The base URI is validated before the row is read, and
  another relationship answers 404.
- **73, the 202 answer.** It drops the token and secret, and WT3 is
  re-recorded. The re-pair answer is not covered (Issue 4).
- **74, the exclusions.** `evaluate_property_with_exclusions` reads once.
  Residue: Issues 6 and 7.
- **75, the changelog.** The "15 seconds in all" sentence is false while
  Issue 1 stands.

**Security properties, demonstrated:**
- **The deadline:** `tests/test_trust_re_pair.py`
  `TestTheDeadlineHoldsAfterReverify8`. The caller returns in under 2 s
  against a trickled body and an answer that never starts, with a 0.5 s
  deadline. Both failed before. The tests mock `iter_content`, so they
  measure the caller, not the worker (Issue 2).
- **The client view:** `TestTheClientViewAfterReverify8`. A view over a
  real OAuth trust reads and writes its grant and is refused an exclusion.
  A client with no row gets nothing.
- **The edges:** `TestTheEdgesAfterReverify8`:
  - an approval lands on the row re-verified;
  - text approval is gated;
  - a PUT for another relationship answers 404 with no probe;
  - a base URI that is not text answers 400;
  - the 202 body carries no token.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-8.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. The second check's deadline does not hold | Partly: the caller returns in time for the GET; `/meta` unbounded (Issue 1), worker pinned (Issue 2) | iteration 70 |
| 2. `as_client(client_id)` denied | Fixed (residue: Issue 5) | iteration 69 |
| 3. The first verification unbounded | Partly: its GET bounded; its `/meta` not (Issue 1) | iteration 70 |
| 4. `modify_trust` approval not tied to the row | Fixed | iteration 71 |
| 5. A string `approved` skips the gates | Fixed, but over-reached: other truthy values now revoke (Issue 3) | iteration 71 |
| 6. PUT relationship and base URI | Fixed | iteration 72 |
| 7. The POST 202 carries the token | Fixed for creation; the re-pair 202 still does (Issue 4) | iteration 73 |
| 8. Stale passages | Fixed | iteration 73 |
| 9. Hygiene and cost | Fixed (residue: Issues 6 and 7) | iterations 70, 74 |

## Remaining Tasks

- [ ] `/iterate_plan` for Issues 1 to 7.
- [ ] Todos unchanged: `grant-enforcement-per-route.md`,
      `web-ui-trust-page-gaps.md`, `full-state-fallback-replica.md`.

## Issues Found

### Issue 1: the `/meta` step of both verifications is unbounded and follows redirects
**Severity:** Medium (all three providers; the requester-chosen fetch is
pre-existing, and the changelog claim is new and false)
**Description:**
- **The path.** After the bounded GET, both verifications call
  `_base_uri_serves` (`actor.py:2545`, `:2233`), then `get_peer_info`,
  then `requests.get(url=url + "/meta", timeout=timeout)` (`actor.py:311`).
  That fetch follows redirects and reads the whole body, with per-read
  timeouts only.
- **The bypass.** An anonymous requester answers the bounded GET at once,
  then trickles or redirects `/meta`, so the request thread is held as
  before.
- **What it falsifies.** The changelog's "both verifications follow no
  redirect, read at most 64 KB and give up after 15 seconds in all".
- **A blind spot in the test.** The new test leaves `/meta` out of its
  assertion.
**Location:** `actingweb/actor.py:311`, `:2620-2635`
**Recommendation:** have `_base_uri_serves` fetch `/meta` through the
bounded helper, under the same overall deadline as the GET before it.
`get_peer_info` keeps its retries for its other callers.

### Issue 2: a slow peer pins a pool worker, and enough of them stop all verification and block shutdown
**Severity:** Medium
**Description:**
- **The pinning.** `_fetch_json` reads `answer.iter_content(chunk_size=1024)`
  (`actor.py:104`) with `timeout=(5, 5)`. Each read blocks until 1024
  bytes arrive, and a byte every 4 s resets the per-read timeout. Headers
  have no deadline at all. `cancelled` is checked only between chunks.
- **The effect.** Eight anonymous requests pin the eight workers for about
  an hour each, or indefinitely during headers. Every honest verification
  in the process then fails closed after 15 s.
- **Shutdown.** `ThreadPoolExecutor` workers are joined at exit, so a
  pinned worker hangs the process until SIGKILL.
- **What it falsifies.** The comment "holds only that worker (until its
  socket times out)" (`actor.py:55-58`).
- **Compared with before.** Whole-service availability improves, since
  request threads are no longer held. Denying pairing is cheaper.
**Location:** `actingweb/actor.py:55-145`
**Recommendation:**
- Close the connection from the caller when it times out (keep the
  response or socket handle), so the worker's read fails at once.
- Make the workers daemon threads, or shut the pool down without waiting
  at exit.
- Correct the comment.
- A test with a real slow socket would show the worker, not only the
  caller.

### Issue 3: `_as_flag` turns other truthy values into `False`, revoking an approval
**Severity:** Medium (a silent behaviour change in a public method)
**Description:** `return str(value).strip().lower() == "true"`
(`trust.py:615`), and the same parse in `interface/trust_manager.py:906`.
`modify_trust(peer, approved=1)`, `"1"`, `"yes"` or `"True "` from a form
now writes `approved=false` on an approved row. Before, it stored True. No
log, no changelog line.
**Recommendation:**
- Accept a bool, `"true"` or `"false"` (any case), and refuse anything else
  with a `ValueError`, or treat it as not given.
- Use one helper in both places, and name the change in the changelog.

### Issue 4: a re-pair's 202 answer still carries the verification token
**Severity:** Low
**Description:** `_re_pair` writes `json.dumps(new_trust)` for an
unapproved, verified row (`handlers/trust.py:600`), `verification_token`
and `secret` included. Iteration 73 stripped them only from the creation
answer, while the changelog and the security reference say a 202 never
carries them. The requester holds the current secret, so this is the spec
rule, not the mirror.
**Recommendation:** one serializer for the creation 202, the re-pair answer
and the peer GET.

### Issue 5: the client view's identity
**Severity:** Low
**Description:**
- **Two ids.** `create_local_subscription` stores a client's subscription
  under `accessor_id`, the raw client id (`authenticated_views.py:719`).
  Its permission was checked as the trust row, and the diff filter later
  evaluates the raw id, so its diffs are dropped. They were dropped before
  this range too (the filter needs ALLOWED).
- **An unchecked peer id.** A caller-supplied `peerid` in the trust dict
  (`:39-41`) is not checked against `client_id`. Only application code
  passes one.
- **Cost.** Each client view now lists the actor's trusts in its
  constructor, which can raise `DbError`. A non-dict trust object fails
  there with an `AttributeError`.
**Recommendation:**
- Store and list a client's subscriptions under its trust's peer id.
- Accept a given peer id only when that row's `oauth_client_id` is the
  client.
- Resolve the row lazily, on the first permission check.

### Issue 6: the new evaluator path logs no denial, and the flag parse is duplicated
**Severity:** Low
**Description:**
- `evaluate_property_with_exclusions` calls `_evaluate_rules(...,
  suppress_logging=True)` and logs no DENIED (`permission_evaluator.py:579`).
  `evaluate_permission` logs "Permission denied" (`:228-231`), so refused
  diffs leave no trace.
- The flag parse exists twice (Issue 3).
**Recommendation:** log DENIED as `evaluate_permission` does, and share one
flag helper.

### Issue 7: a `list:` key under a subtarget is checked at a path the list does not live at
**Severity:** Low
**Description:** iteration 74 checks `list:<name>` as `<subtarget>/<name>`
(`actor.py:3612`). Lists are top-level properties, and the whole-target
filter and the list store check `<name>`. An exclusion of the top-level
list `notes` does not match `settings/notes`. Such a key under a subtarget
is unusual; the iteration's premise was wrong.
**Recommendation:** check a `list:` key by its bare name, as the other
filters do.

**Notes** (no finding):
- **The FastAPI form PUT.** `GET /trust/<peerid>?_method=PUT` reaches the
  PUT with an empty relationship and fails, as on `master` (now 404,
  before 400).
- **The re-pair probe.** `_re_pair_unknown`'s probe (`actor.py:2398`) is
  still a plain `requests.get`. We initiate it, toward a stored base URI.
- **Test isolation.** The deadline tests leave pool workers busy for a few
  seconds after they finish. No flake was seen in either run.

## Overall Assessment

Reverify-8's fixes land where they were aimed:
- **The client view** evaluates as its trust row, and `as_client` works
  again.
- **The approval** is tied to the row it re-verified.
- **The PUT** checks its input first.
- **The 202** carries no token on creation.
- **The caller** of the bounded GET returns within its deadline.
- **The checks are green.** The Full tier on both backends: DynamoDB 6138,
  PostgreSQL 5935. Emm's suite matches its baseline. The security review
  found nothing.

What stands before the PR:
- **Issue 1.** The `/meta` step still lets an anonymous requester hold a
  request thread, and the changelog says it cannot.
- **Issue 2.** The pool bounds the caller but not the worker, so pairing is
  cheap to deny and shutdown can hang.
- **Issue 3.** The flag parse revokes approvals passed as `1` or `"yes"`.
- **Four low items.**

None is a hole in the identity fixes. Issues 1 and 2 belong together: a
fetch helper whose deadline reaches the socket, used for both steps.
