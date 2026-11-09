# Verification: peer authorisation fixes (seventh run: the audit's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** fc97b5d (code as of d3fd713; fc97b5d adds records only)

This run verifies Iterations 45 to 55 (`5f33163..d3fd713`). Those
iterations answered the trust-boundary audit
(`verifications/2026-11-09-peer-authorisation-fixes-audit.md`: A1, A2, A3,
A9, and A4 through iteration 50) and reverify-6 Issues 1 to 11, within the
owner's scope decision. Each fix was to be checked against
`docs/protocol/actingweb-spec.rst`. The INDEX row asked for two things in
this run: the security review, and a browser walk of the Approve refusal.

## Automated Check Results

- **Outside voice** (codex `codex exec -s read-only` outside the sandbox,
  then a fresh-context Claude read of the same diff): seven findings.
  - **Issue 1 (critical).** The re-verification, and the creation
    verification under it, can be answered by a second pending row that the
    attacker plants at the real peer. I reproduced it live (below).
  - **Issue 3.** The notify after a failed approval write.
  - **Issues 9 to 11** and the note on non-`properties` targets.
  - **Its view on splitting the changelog:** A1 can ship as its own
    SECURITY entry. The approval entries should not ship as written until
    Issue 1 is closed.
- **Built-in code review** (`/code-review high 5f33163..d3fd713`): ten
  findings, each checked against the code here.
  - Issue 2 is a data leak this range introduced; the other providers
    missed it, and the security review dropped it with a wrong premise.
  - It also gave Issues 4, 6, 7 and 8, and the residue in Issues 11 and 12.
- **Built-in security review** (`/security-review` flow, scoped to
  `5f33163..d3fd713 -- actingweb`, confidence bar 8): no finding at or
  above the bar.
  - It judged the secret egress, the SQL condition and both backends'
    conditional writes sound. I agree on those three.
  - It dropped the subtarget filter on the premise that `register_diffs`
    narrows a diff to the subscription's path. That premise is false for a
    subscription with a subtarget and no resource (Issue 2).
  - It did not consider the mirrored row (Issue 1).
- **Browser QA** (provider: gstack browse, headless Chromium; demo in local
  QA mode on `localhost:5055`, fresh `demoqarv7` tables, throwaway actors
  deleted afterwards):
  - **Set-up.** A request was filed at A under B's id and B's real base
    URI, with a secret B does not hold. It was stored
    `approved=false, verified=false`.
  - **By API:**
    - the request's secret reads `/<A>/properties`: **403** (A1 closed);
    - it reads its own row: 202;
    - the owner's `PUT /trust/associate/<B> {"approved": true}`: **403**
      with an empty body (Flask drops the reason phrase), and the row is
      unchanged;
    - logged: "did not verify on a second check (status 403)" and "Refused
      to approve ... the request is not verified".
  - **In the browser:**
    - `/www/trust` shows the row as Pending with an Approve button and no
      sign that it is unverified;
    - Approve lands on a blank 403 page with no message and no way back;
    - the row stays Pending, with Approve offered again (Issue 5);
    - the 375 px layout is fine;
    - console: only the 403 resource error.
  - **Live reproduction of Issue 1** (same demo, two new throwaway actors,
    deleted afterwards), with no action by either owner:
    - the attacker's request at A, under B's id;
    - its read of A's stored `verification_token` with its own secret
      (202);
    - its request at B, under A's id, with that token: **201, `approved
      true, verified true`** (the demo auto-accepts `friend`);
    - then `GET /<B>/properties` with the attacker's secret: **200**.
- **Full tier**, on the code at `d3fd713` (HEAD `fc97b5d`):
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6113 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5910 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed: the tree is clean after the runs.
- **Emm's suite** on `d3fd713` (recorded in iteration 55, code unchanged
  since): PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54 passed,
  the `master` baseline's failures by name. It was not re-run.
- **Benchmarks:** not run; the range does not touch list storage.

## Phase Verification

### Iterations 45 to 55 - ISSUES FOUND

**Changes verified (they match the iterations):**
- **45, the approval gate.** `permission_evaluator.py:539-561`
  `_is_unapproved` is called at `:204` (single), `:305` (bulk) and `:504`
  (`get_allowed_items`).
  - A DB fault raises `DbError` (both backends' `get` are strict), so it
    fails closed.
  - `config is None` is reachable only in tests: `__init__` requires a
    config (`:164`).
  - A missing row passes on to the grant lookup (Issue 9).
  - The live demo shows the 403.
- **46, the conditional approval.**
  - `trust.py:399` `only_if_verified=approved is True`; DynamoDB
    `db/dynamodb/trust.py:334-337`; PostgreSQL
    `db/postgresql/trust.py:617-621` (a bound parameter).
  - Both evaluate the stored row, so `modify(approved=True, verified=True)`
    in one call is refused on an unverified row.
  - The PUT gate is at `handlers/trust.py:907-919`, and
    `modify_trust_and_notify` at `actor.py:1547-1557` (the async twin
    delegates through `to_thread`).
  - `reverify_pending_trust` (`actor.py:2062-2115`) can be passed by the
    mirrored row (Issue 1).
- **47, the conditional re-pair.**
  - `handlers/trust.py:572` passes `proven_secret=bearer`.
  - `actor.py:2559` conditions the swap on that bearer, and a pending row
    is refused.
- **48, re-verify before replacing.** It is in both twins
  (`actor.py:1738`, `:1929` via `asyncio.to_thread`). Residue: Issue 7.
- **49, the revocation probe.** `interface/subscription_manager.py:858-886`.
  Residue: Issue 12.
- **50, one diff filter.**
  - `actor.py:3438-3490` is called from `callback_subscription` (`:3203`)
    and from `handlers/subscription.py:17`.
  - A non-object whole-target value fails closed (`:3470`).
  - A subtarget subscription without a resource is sent whole (Issue 2).
- **51, the owner listing row.** `config.py` row `subscriptions/<id>` GET.
- **52, 53, the reconcile and the 503.** `handlers/callbacks.py:1205-1235`
  and `:521-531`. Residue: Issue 12.
- **54, the approval flag.** It is cleared per call, and the async hook
  runs through `to_thread`.
- **55, the docs and the spec.** The claims in Issue 1 and Issue 6 are
  now false.

**Security properties, demonstrated (test, then what it asserts):**
- **A1:** `tests/test_peer_paths_binding.py:833`
  `test_properties_methods_and_actions_refuse_it`. An unapproved `friend` or
  `admin` row is refused on properties GET/PUT/DELETE, methods and actions.
  `:865` asserts DENIED for every permission type. `:856` keeps an approved
  peer reading. Also shown live (403).
- **A3:** `tests/test_trust_re_pair.py:1500`
  `test_every_approval_route_refuses_an_unverified_row` asserts every route
  leaves the row unapproved. `:1533` covers a second check that passes.
  These tests stub the peer's answer, so they cannot see Issue 1.
- **A2:** `tests/test_trust_re_pair.py:1442` asserts the swap is
  conditioned on the authenticating secret. `:1470` asserts that a row
  replaced after authentication keeps its secret.
- **A9:** `tests/test_revoked_trust_detection.py:342` asserts an unreachable
  peer or a 5xx keeps the trust. `:351` asserts a JSON refusal is not read
  as live.
- **Filter:** `tests/test_peer_paths_binding.py:937`, `:959` and `:986`
  cover a resource subscription and an object under a subtarget. No test
  covers a subtarget subscription receiving a resource-level write
  (Issue 2).

**The spec check.** These fixes stay within the spec's MAY/SHOULD:
- the conditional re-pair at `:1595-1605`;
- refusing a manual approval of an unverified relationship (`:1606-1609`);
- granting nothing before approval (`:1609-1612`);
- the 503 reason (`:3114`).

Two of the new spec sentences are false while Issue 1 stands:
- `:1609` says an unverified request "holds a secret only its requester
  knows". That is true, but a verification can still be answered with it.
- `:1611` admits the peer's own status read, which is the read the mirror
  attack uses.

**The consumer message.** This plan has no separate consumer message. What
consumers read is the changelog and `docs/migration/v3.16.rst`, which carry
the new behaviours:
- unapproved peers get nothing;
- only verified requests are approved;
- the listing row.

The verification guarantee those pages state is false while Issue 1
stands.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-6.md
(and the audit `-audit.md`, for the items the owner put in this PR)

| Issue then | Status now | Evidence |
| --- | --- | --- |
| R6-1. An explicit approval approves an unverified request | Fixed as reported, but the re-check it relies on can be passed (Issue 1) | iteration 46; `trust.py:399`, `handlers/trust.py:907` |
| R6-2. Replacing an honest request strands both sides | Fixed. Residue: a relationship or URL mismatch now refuses (Issue 7) | iteration 48; `actor.py:1738` |
| R6-3. `owner` row refuses the listing | Fixed | iteration 51; `test_peer_paths_binding.py:1009` |
| R6-4. Pull ignores the resource | Fixed for a subscription that names the resource | iteration 50; `:937` |
| R6-5. Object under a subtarget filtered per key | Fixed. Its fix opened Issue 2 | iteration 50; `:959` |
| R6-6. Refused diff pulled as `{}`, never pushed | Fixed (push skips; pull `{}` kept, documented) | iteration 50 |
| R6-7. Refused reconcile read as a newer copy | Fixed. Residue in Issue 12 | iteration 52; `test_peer_binding.py:1243` |
| R6-8. Non-`DbError` answers 500 | Fixed. Residue in Issue 12 | iteration 53; `test_peer_binding.py:1273` |
| R6-9. Hook routing | Fixed (per-call flag; docs name the routes without a hook) | iteration 54; `test_trust_re_pair.py:1589` |
| R6-10. No `trust_deleted` for a replaced row | Accepted and documented | `docs/reference/hooks-reference.rst` |
| R6-11. Hygiene and cost | Fixed | iteration 54 |
| Audit A1. An unapproved row passes the evaluator | Fixed (tests and live). Residue: a missing row (Issue 9) | iteration 45 |
| Audit A2. Re-pair lands on a replacement row | Fixed | iteration 47 |
| Audit A3. Every approval route approves an unverified row | Fixed as a condition, but Issue 1 passes the verification it requires | iteration 46 |
| Audit A9. Revocation probe | Fixed. Residue in Issue 12 | iteration 49 |
| Audit A4. Push of a subtarget's single value | Fixed. Issue 2 is a new leak on the same path | iteration 50 |

The deferred audit items (A5 to A8, A10, A11, A12 to A20) have their todo
file, `thoughts/todo/grant-enforcement-per-route.md`, with its `INDEX.md`
row. A20 is still open: the listing route passes `approved=False`
(`handlers/subscription.py:202`). `web-ui-trust-page-gaps.md` and
`full-state-fallback-replica.md` keep their rows.

## Remaining Tasks

- [ ] `/iterate_plan` for Issues 1 to 8. Issue 1 blocks the PR; Issue 2 is
      a leak this range introduced.
- [ ] Decide where Issues 9 to 12 go: this PR or the second security plan.
- [ ] Emm's suite after that iteration.
- [ ] The browser gaps in Issue 5 extend `thoughts/todo/web-ui-trust-page-gaps.md`
      unless the iteration fixes them (the blank 403 is on this plan's path).

## Issues Found

### Issue 1: two mirrored pending rows pass the verification, so an attacker becomes a peer
**Severity:** Critical. Introduced by the branch: `a8007e5` let a pending
row's own peer read the row, and this range builds the re-verification on
that read.
**Description:**
- **How the verification works.** Both verifications prove only that a
  host answers our own trust row with the secret, or token, that the
  requester supplied:
  - creation, `actor.py:2385-2415`, compares `verification_token`;
  - re-verification, `actor.py:2087-2100`, checks
    `body.get("peerid") == self.id`.
- **The read the attacker uses.** A pending row's own peer can read that
  row. `handlers/trust.py:640` (`approved=False`) and `:697-705` serve it
  with its `verification_token`. On `master` the same read answered 403
  ("Trust relationship not approved").
- **The attack:**
  1. The attacker files a request at A under B's id and B's real base URI,
     with secret S.
  2. It reads A's stored token with S.
  3. It files a request at B under A's id and A's real base URI, with S
     and that token.
  4. B's verification reads A's row with S and gets the token, so B's row
     is verified. B approves it automatically when that relationship
     auto-accepts, or on the owner's click.
  5. The same mirror passes A's `reverify_pending_trust`. A's owner's Approve
     on "B wants to connect", or the owner's own create toward B
     (`actor.py:1738` then `:1762-1765` `_approve_on_create`), approves a
     row whose secret the attacker holds.
- **Shown live:** a 201 with `approved true, verified true` at B, then a
  200 on `/<B>/properties`.
- **The docs claim the opposite:**
  - the docstring (`actor.py:2068-2071`, "only a host holding the secret
    answers ... never passes");
  - `CHANGELOG.rst:97`;
  - `docs/reference/security.rst:113`;
  - the spec at `:1609`.
**Location:** `actor.py:2099`, `actor.py:2410`, `handlers/trust.py:697-705`
**Recommendation:** a verification must be answered by a row its host
approved. A genuine initiator's row is created `approved=True,
verified=True` (`actor.py:1797`, `:1987`). So:
- accept the creation verification and `reverify_pending_trust` only when
  the answer's `approved` is true. Compare it as
  `str(...).lower() == "true"`: a POST answer serialises the flag as the
  string `"false"`, and the GET answer as a boolean. `master`'s initiator
  also creates its row `approved=True` (`master:actingweb/actor.py:1709`,
  `:1838`), so a released peer still pairs. Check Emm's pinned version
  before the iteration;
- serve `verification_token` (and a 2xx) to a pending row's own peer only
  where needed, and never for a row that is neither verified nor approved;
- check this against the spec's trust GET (`:1666-1672`), and correct
  `:1609-1611` and the three docs above;
- add a two-actor integration test of the mirror, on both backends, and a
  wire row in `rows.toml` that records the attack before the fix, as Phase
  3 did for the re-pair rows.

### Issue 2: a subtarget subscription without a resource receives an excluded resource
**Severity:** Medium (a data leak past an `excluded_patterns` entry,
introduced by iteration 50; the parent read beside it is the deferred A5).
**Description:**
- **The leak.** Take a subscription to `properties/settings` with no
  resource. A write to `settings/private` reaches it as `{"private": ...}`
  (`actor.py:4588-4600`, "send [resource] = blob").
- `filter_subscription_blob` checks only `settings` (`actor.py:3475-3490`),
  so the excluded value is pushed and pulled.
- **What it used to do.** Before iteration 50, the push checked
  `settings/private` per key, and so does `master`
  (`master:actingweb/actor.py:2637-2641` passes the subtarget). This is new
  exposure against the released library, not a shifted one.
**Location:** `actor.py:3476`
**Recommendation:**
- Under a subtarget, keep the object whole when the subtarget is readable,
  but drop each key whose `<subtarget>/<key>` evaluates DENIED. That keeps
  reverify-6 Issue 5's exact-grant case.
- Add a test with an exclusion on `settings/private`, on both paths.

### Issue 3: `modify_trust_and_notify` tells the peer "approved" after a failed write
**Severity:** Medium
**Description:**
- **The failed write is ignored.** `result = dbtrust.modify(...)`
  (`actor.py:1566`) is never checked. The POST to the peer follows
  (`:1588-1600`), built from `this_trust`, which was read before the
  re-verification.
- **Two ways it goes wrong:**
  - when `only_if_verified` refuses, the peer is still told "approved";
  - a verifying request that replaces the row in between is approved
    without the owner having seen it, while the notification goes to the
    old row's base URI and secret.
**Location:** `actor.py:1566-1600`
**Recommendation:**
- Return False when `result` is falsy.
- Condition the approval write on `only_if_secret=this_trust["secret"]`.

### Issue 4: a row approved before 3.16 but never verified refuses every `approved=true` write
**Severity:** Medium (a behaviour change for existing data)
**Description:**
- **Which calls fail.** `modify_trust_and_notify` re-verifies whenever
  `approved is True` and the row is unverified, already-approved rows
  included (`actor.py:1547-1551`). `Trust.modify(approved=True)` then
  refuses the write (`trust.py:399`).
- **What breaks.** An idempotent `PUT {"approved": true, "desc": "x"}`, or
  `modify_and_notify(approved=True, ...)`, on such a row blocks on a probe
  of the peer (up to about 15 s plus the `/meta` tries). It then answers
  403, and the description change is lost.
**Location:** `actor.py:1547`, `handlers/trust.py:907`, `trust.py:399`
**Recommendation:**
- Treat `approved=True` on an already-approved row as no change: no probe,
  no condition.
- State in the migration guide what happens to approved but unverified
  rows.

### Issue 5: a refused Approve shows a blank page, and the page offers Approve on a request it will refuse
**Severity:** Medium (the browser walk's F-001 and F-002; the agent rated
F-001 high, but nothing is approved wrongly and the owner has a way out)
**Description:**
- **The blank page.** The Approve form (`templates/aw-actor-www-trust.html:44-49`)
  GETs `/trust/<rel>/<peer>?_method=PUT&approved=true`. The refusal is a
  403 with an empty body: a blank white page, no message, no link back.
- **No sign the request is unverified.** The row shows "Pending" and no
  "Verified" badge. Nothing says it cannot be approved, and Approve stays
  offered after the refusal.
- **Repro:** walk path 2 above.
- **Screenshots:** `scratchpad/qa-rv7/01-…04-*.png` in this session's
  scratch directory.
**Location:** `actingweb/templates/aw-actor-www-trust.html:39-49`,
`handlers/trust.py:916-919`
**Recommendation:**
- Show "Unverified" on the row, and replace Approve with a hint to create
  the trust toward the peer's URL.
- For a browser request, send the refusal back to `/www/trust` with a
  message.

### Issue 6: the security reference names `TrustManager.modify_trust` as re-verifying
**Severity:** Low (docs)
**Description:** `docs/reference/security.rst:113` lists
`TrustManager.modify_trust` among the routes that "first repeat its
verification". In fact it calls `Trust.modify` directly
(`interface/trust_manager.py:901`), which refuses with no probe and no log.
**Recommendation:** correct the list, or route `approved=True` through
`reverify_pending_trust` there as well.

### Issue 7: the owner's create refuses a request that verifies on the second check but differs in relationship or URL
**Severity:** Low
**Description:**
- After `reverify_pending_trust` passes (`actor.py:1738`), the row takes
  the re-pair branch. `_re_pair_refusal` (`:2177-2186`) refuses a different
  relationship, or a URL that differs from the stored base URI.
- The row was the requester's pending one, now marked verified. The
  owner's create fails (408), where it used to replace the row.
**Recommendation:** after a second check that passes, compare the
relationship and URL. On a mismatch, fall back to replacing the row, as
for an unproven one.

### Issue 8: the PUT approval answers "not verified" for a missing row, and probes the old base URI on a move
**Severity:** Low
**Description:**
- **A missing row.** `handlers/trust.py:907` runs `reverify_pending_trust`
  before anything checks that the row exists, so a deleted row answers 403
  "not verified" rather than 404.
- **A move.** A PUT carrying `approved` and a new `baseuri` probes the
  stored base URI.
**Recommendation:**
- Answer 404 when the row is gone.
- Order the base-URI move before the approval, or refuse the combination.

### Issue 9: `_is_unapproved` passes a peer with no trust row
**Severity:** Low
**Description:** `permission_evaluator.py:558` (`if row and approved is
False`) lets a missing row continue to the grant lookup. `:575` then
grants from a permission override that a faulted delete left behind.
Bearer auth needs the row, so few callers reach this.
**Recommendation:** deny when the row is missing, unless the caller is a
known non-trust identity. Alternatively, file it with A8 in the second
plan.

### Issue 10: the re-verification has no total deadline
**Severity:** Low
**Description:**
- `actor.py:2087` `requests.get(..., timeout=(5, 10))` follows redirects,
  and its read timeout is per read. The `/meta` tries come on top of that.
- A pending row's base URI is the requester's choice, so a host that
  trickles its answer holds the owner's PUT or create.
**Recommendation:**
- Set `allow_redirects=False`.
- Stream the answer with a total deadline and a size cap.

### Issue 11: an extra trust read per evaluation
**Severity:** Low (cost)
**Description:** `_is_unapproved` (`permission_evaluator.py:552`) reads the
trust row once per `evaluate_permission`, beside the lookup in
`_get_effective_permissions`. The per-key loop in
`_filter_subscription_data_by_permissions` (`actor.py:3524-3545`) pays it
for every key, for every subscriber.
**Recommendation:** read approval once per filter call (the bulk evaluator
already does), or fold it into the lookup the evaluator already makes.

### Issue 12: residue in the probe and the permission callback
**Severity:** Low
**Description:**
- **The probe** (`subscription_manager.py:880`) treats a transient 404 or
  403 from a gateway as a revocation. This is narrower than before, where
  every error was read as revoked.
- **The 503** (`handlers/callbacks.py:524-531`) is also given to a failure
  that repeats every time, and to one after a successful store. The sender
  resends a bounded number of times.
- **The reconcile** (`callbacks.py:1221-1229`) restores nothing when either
  `fetched_at` is missing.
**Recommendation:** accept these and document them, or require two probes
before deleting.

**Note** (no finding): a diff for a target other than `properties` passes
unfiltered (`actor.py:3462`), as on `master` and as the docstring says.
Record it as a decision, or file it beside A11.

## Overall Assessment

The range does what the iterations say, on both backends:
- the Full tier is green: DynamoDB 6113 passed, PostgreSQL 5910 passed;
- A1 is closed, in the tests and in a live run: an unapproved request's
  secret now gets 403;
- the conditional writes are sound, and A2 and A9 are closed.

**It is not ready for a PR.** The approval gate of A3 rests on a
verification that a third party can answer. It does so with a second
pending row planted at the real peer, which this branch made readable. I
reproduced a full impersonation with no owner action under auto-accept;
without auto-accept, it takes one Approve or one create. The SECURITY and
trust entries, the security reference and the spec claim the opposite.

Issue 2 is a new leak this range made while fixing reverify-6 Issue 5.
Issues 3 and 4 are correctness problems on the approval path. The web UI
refuses correctly but leaves the owner on a blank page (Issue 5).

Iterate on Issues 1 to 8 before the PR. The outside voice's split
suggestion is worth keeping for the release order: A1 stands alone. Both
security plans still stay local.
