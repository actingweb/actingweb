# Verification: peer authorisation fixes (sixth run: reverify-5's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 5f33163

This run verifies Iterations 38 to 44 (`5cabc26..5f33163`), which answered
`verifications/2026-11-09-peer-authorisation-fixes-reverify-5.md` with three
owner decisions. Reverify-5 asked that this run include the security review,
since that range's own fixes had opened two holes.

## Automated Check Results

- **Built-in security review** (`/security-review` flow, scoped to
  `5cabc26..5f33163 -- actingweb`, confidence bar 8): **no finding** at HIGH
  or MEDIUM.
  - **Reverify-5's two holes, as they were reported, are closed:**
    - creating a trust no longer approves an unverified row
      (`actor.py:1722`, `:1776-1777`, async `:1901`, `:1955-1956`);
    - the `owner` row no longer admits a subscription POST
      (`config.py:339`), and pulled diffs are filtered
      (`handlers/subscription.py`, `_as_permitted`).
  - It confirmed both backends' `only_if_pending` conditions are atomic.
  - Below its bar: a stranger's verified row under a peer's id blocks
    pairing (denial of service, predates this range).
- **Built-in code review** (`/code-review high 5cabc26..5f33163`): ten
  findings, each checked against the code: Issues 2, 3, 5, 6, 8, 9 and 11
  below. Its `create_peer_trustee` item is folded into Issue 9.
- **Outside voice** (codex `codex exec -s read-only` outside the sandbox,
  and a fresh-context Claude reviewer): eight findings and four unverified
  notes. It found Issue 1, which the other two providers missed: hole 1
  closed only on the create route. It also found Issues 4 and 7 and
  confirmed 2, 3 and 5. Its SSRF item is a note (an unauthenticated
  `POST /trust` already makes the server fetch any requester-supplied URI).
- **Browser QA** (provider: gstack browse, headless Chromium; demo in local
  QA mode on `localhost:5055`, throwaway actors, data dropped afterwards):
  - **Path 1, create a trust from the web form:** expected behaviour. The
    demo auto-accepts `friend` (`examples/demo/application.py:149`), so the
    request never waits.
  - **Path 2, approve on create:** pass with `associate`. The receiver saw
    the request pending (`approved=false, peer_approved=true, verified=true`),
    then its own create approved it, with no duplicate row
    (`true/true/true` on both sides).
  - **Path 3, validation and edge input:** pass. Empty, invalid,
    `javascript:` and self URLs answer 400 and create nothing; a 596-character
    description with markup and unicode is stored whole and shown escaped.
  - **Path 4, 375 px width:** pass.
  - **Pre-existing web UI gaps** (not on this plan's path): peer approval is
    never shown (medium), nothing links to `/www/trust/new` (medium), error
    pages are bare (low), and creating an existing trust redirects silently
    (low). Filed as `thoughts/todo/web-ui-trust-page-gaps.md`.
  - Console: no application errors.
- **Full tier**, run on the code committed as `5f33163` (the commit then
  added only plan text):
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6088 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5885 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed, including the three `.subscriber` rows.
- **Emm's suite** on `325370f`: PostgreSQL 2 failed / 7406 passed,
  DynamoDB 3 failed / 54 passed, the `master` baseline's failures by name.
  `5f33163` changes only which hooks the create routes run.

## Phase Verification

### Iterations 38 to 44 - ISSUES FOUND

**Changes verified (match the iterations):**
- `actingweb/actor.py`:
  - `_is_unproven_pending` and the `only_if_pending` replacement in both
    twins (38). It is closed on the create route only (Issue 1), and it
    strands an honest request whose verification failed (Issue 2).
  - `_drop_failed_attempt` compares the `secret` argument and keeps a row
    the peer approved (42).
- `actingweb/interface/trust_manager.py` `_fire_approved_on_create`, with
  `handlers/trust.py`, `handlers/async_trust.py` and `handlers/www.py`
  (38, 44): the hook routing works; residue in Issue 9.
- `actingweb/config.py:339`: the narrowed `owner` row (39). It also drops
  the listing GET (Issue 3).
- `actingweb/handlers/subscription.py` `_as_permitted`, `_may_read` (39):
  - filtering works for a whole-target subscription and a scalar subtarget;
  - it misses the resource (Issue 4);
  - it handles an object under a subtarget differently (Issue 5);
  - its `{}` placeholder (Issue 6).
- `actingweb/handlers/trust.py`:
  - the base-URI move check (40);
  - `str(params["approved"])` (42).
- `actingweb/handlers/callbacks.py` `_reconcile_with_granting_peer` (41):
  the order and the propagation are right; residue in Issues 7 and 8.
- `actingweb/db/dynamodb/trust.py`, `fanout.py`,
  `maintenance/peer_state.py` (42): as recorded.
- `CHANGELOG.rst`, `docs/migration/v3.16.rst`,
  `docs/guides/access-control.rst` (43, 44): the listing claim is wrong
  (Issue 3), and so is the claim about every create route (Issue 9).

**Tests verified:**
- Every test named in iterations 38 to 44 exists and passes on both
  backends.
- 17 of them failed with the library before the change. The rest are
  controls (the plan records this per iteration).
- Gaps:
  - No test approves an unverified row through `PUT /trust` or
    `TrustManager.approve_relationship` (Issue 1).
  - No test runs the replacement against a peer that holds its own row
    (Issue 2).
  - No test lists subscriptions as a non-`friend` peer (Issue 3).
  - No test covers a resource subscription's pull, or an object value
    under a subtarget (Issues 4 and 5).

**Security properties, demonstrated:**
- `test_an_unverified_pending_row_is_replaced_by_the_owners_request`
  asserts the stored secret is the owner's.
- `test_the_owner_row_admits_no_subscription_creation` asserts 403.
- `test_a_pulled_diff_carries_only_what_the_peer_may_read` asserts the
  diff reads `{}`.
- `test_a_move_to_a_base_uri_that_names_another_id_is_refused` asserts 400
  with the row unchanged.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Create approves an unverified pending row | Fixed on the create route; still open through an explicit approval (Issue 1) | iteration 38; `actor.py:1722` |
| 2. Any peer subscribes and pulls unfiltered diffs | Fixed; the narrowing also drops the listing (Issue 3); the filter misses the resource (Issue 4) | iteration 39; `config.py:339` |
| 3. Base-URI move skips `/meta` | Fixed | iteration 40; `handlers/trust.py:906-927` |
| 4. Reconcile deletes before storing, swallows a fault | Fixed; refused-store residue (Issue 7) | iteration 41 |
| 5. `_approve_on_create` fires no local hook | Fixed for `POST /trust`, the web form and `TrustManager`; not the trustee path (Issue 9) | iterations 38, 44 |
| 6. `_drop_failed_attempt` gaps | Fixed (window documented) | iteration 42 |
| 7. `{"approved": false}` answers 500 | Fixed | `handlers/trust.py:845` |
| 8. DynamoDB handle left changed | Fixed | `db/dynamodb/trust.py:334-339` |
| 9. `FanOutManager` leftovers | Fixed | `fanout.py:374-381` |
| 10. `prune` exits 2 on a newer copy | Fixed | `peer_state.py` `_rebuild_copy` |
| 11. Stale comment, wrapper | Fixed (comment removed; wrapper kept) | `handlers/subscription.py` |
| 12. Changelog wording | Fixed; two new overstatements (Issues 3, 9) | iterations 43, 44 |
| 13. Tests that could not see 1 and 2 | Fixed | `TestTheInitiatorAfterReverify5`, `TestAPeersOwnSubscriptionAfterReverify5`, `TestAPeersOwnTrustRowAfterReverify5` |

## Remaining Tasks

- [ ] An owner decision on Issue 1 (whether an unverified request can be
      approved at all), then `/iterate_plan` for Issues 1 to 11.
- [ ] Emm's suite after that iteration, before the PR.
- Todos: `thoughts/todo/web-ui-trust-page-gaps.md` (new, with its
  `INDEX.md` row) holds the pre-existing web UI gaps the browser walk
  found. The plan's deferral `full-state-fallback-replica.md` keeps its row.

## Issues Found

None of the providers found a peer reaching another peer's rows through a
path, or a way around the closed holes as they were reported. Issue 1 is the
same hole as reverify-5's Issue 1, reached by another route: it is on
`master` too, and iteration 38 closed only the create route.

### Issue 1: an owner's explicit approval still approves an unverified request
**Severity:** High (security; pre-existing, on `master` too)
**Description:**
- **The approval paths never read `verified`.** The web UI shows Approve on
  every pending row (`templates/aw-actor-www-trust.html:43`,
  `{% if not approved and approveuri %}`; the verified badge at `:40` is
  separate). The UI, `PUT /trust/<rel>/<peer>` with `approved=true`, and
  `TrustManager.approve_relationship` (`trust_manager.py:296`,
  `modify_trust_and_notify(... approved=True)`) all approve without
  reading it.
- **This is reverify-5's exploit, by another route.** A stranger's failed
  `POST /trust` under Q's id, with Q's real base URI and the stranger's
  secret, is shown to the owner as "Q wants to connect". One click makes
  the stranger Q, since bearer authentication never reads `verified`.
- **The documented advice does not help.** The security reference's "check
  the base URI of a pending request before approving it"
  (`docs/reference/security.rst:113`) is no protection here, because the
  base URI is Q's real one.
- **Iteration 38's rule is enforced on one route.** "Only a verified
  pending row is approved" holds only in `create_reciprocal_trust`.

**Location:** `actingweb/actor.py` `modify_trust_and_notify`;
`actingweb/handlers/trust.py` (the approval PUT);
`actingweb/interface/trust_manager.py:285-300`;
`actingweb/templates/aw-actor-www-trust.html:40-48`
**Recommendation (owner decision):** refuse `approved=True` on an
unverified row in one place (`modify_trust_and_notify` or below it), with
the reason, on every approval route. At approval time, either re-run the
verification against the row's base URI (approve if it passes), or tell
the owner to delete the request and create the trust instead. The web UI
shows "unverified" and offers delete. Add tests on the PUT, `TrustManager`
and the web form.

### Issue 2: replacing an honest unverified request strands both sides
**Severity:** Medium
**Description:** A genuine request whose verification failed briefly
(a timeout on the verify GET or on `/meta`) is stored unverified. When the
owner then creates the trust toward that peer:
1. The owner's create replaces the stored request (`actor.py:1722`) and
   sends a plain request.
2. The peer holds its own approved initiator row, so it treats the request
   as a re-pair without its secret and answers 403
   (`handlers/trust.py:451-455`, `:572`).
3. The owner then deletes its row (`_drop_failed_attempt`, `actor.py:1817`)
   and answers 408.

Neither side can pair until the peer's owner deletes its row. Before this
range the same create approved the request.
**Location:** `actingweb/actor.py:1722-1728`, `:1817`; async twin
**Recommendation:** re-verify the pending row first. It still holds the
requester's `verification_token` and base URI, so run the GET
`<baseuri>/trust/<rel>/<self>` and the `/meta` check that
`create_verified_trust` runs. Mark it verified and approve in place when it
passes; replace it only when it fails. A squatter's request never passes at
the real peer's URL. The same re-verification is one answer to Issue 1.

### Issue 3: the narrowed `owner` row refuses a peer listing its own subscriptions
**Severity:** Medium (regression against `master`)
**Description:**
- **`master` admitted the listing.** `master`'s
  `SubscriptionRelationshipHandler.get` passes `peerid=peerid` (and
  `approved=False`), so `("owner", "subscriptions", "", "a")` admitted
  `GET /subscriptions/<own id>` for every relationship.
- **The narrowed row does not match it.** The new
  `("owner", "subscriptions/<id>/<subid>", "GET,PUT,DELETE", "a")` does not
  match the full path `subscriptions/<id>` (`config.py:339`;
  `handlers/subscription.py:233-241`). Every type without its own
  `subscriptions/<id>` row (`associate`, `partner`, custom types) now gets
  403.
- **The changelog says the opposite.** It says listing "stays with the
  relationship's own rows, as before", which is not true.

**Location:** `actingweb/config.py:339`; `CHANGELOG.rst` (the CHANGED entry)
**Recommendation:** add `("owner", "subscriptions/<id>", "GET", "a")` before
it (POST stays excluded by method), with a test listing as an `associate`
peer, and correct the changelog.

### Issue 4: the pull filter ignores a subscription's resource
**Severity:** Medium (security; the push path has the same gap)
**Description:**
- **Writes register the resource.** A property write registers
  `subtarget=name, resource=resource` (`handlers/properties.py:1030-1031`).
- **The filter checks only the subtarget.** `_as_permitted` checks
  `_may_read(subtarget)` for a value and `subtarget/<key>` for an object,
  never `subtarget/resource`.
- **The exploit.** A peer granted `*` with `settings/private` excluded
  subscribes with `subtarget=settings, resource=private` (the POST checks no
  permission) and pulls `settings/private`, which a direct read refuses
  (`handlers/properties.py:309`).
- **Push has the same gap.** The pushed callback has it too
  (`_filter_subscription_data_by_permissions`), so pull is no worse than
  push, but both leak.

**Location:** `actingweb/handlers/subscription.py` (`_as_permitted`);
`actingweb/actor.py` `_filter_subscription_data_by_permissions`
**Recommendation:** check `subtarget/resource` when the subscription has a
resource, on both paths; add a test.

### Issue 5: under a subtarget, an object value is filtered per key
**Severity:** Medium
**Description:** A scalar value under a subtarget is checked as the
subtarget, but an object value is checked as `subtarget/<key>`. A peer
granted exactly `settings` (or a list's name; list diffs are objects,
`property_store.py:332-335`) can read `GET /properties/settings`, but now
pulls `{}` for its changes, where before this range it got the data. A 3.16
subscriber uses the pull for gap fetches, so its replica silently misses
them.
**Location:** `actingweb/handlers/subscription.py` `_as_permitted`
**Recommendation:** under a subtarget, gate the whole value on
`_may_read(subtarget[/resource])`; filter per key only for a whole-target
subscription. Consider the push path, which has the same per-key rule.

### Issue 6: a diff the peer may not read is pulled as `{}`, but never pushed
**Severity:** Low
**Description:** For the same diff, `callback_subscription` sends nothing
(the filter returns None), while the pull returns
`{"sequence": n, "data": {}}`. A subscriber that applies a subtarget diff
as the property's value overwrites its replica with `{}`; for a whole-target
subscription it merges an empty change.
**Location:** `actingweb/handlers/subscription.py` `_as_permitted`
**Recommendation:** decide how a refused diff is represented on pull (`null`
data, or the entry omitted with the sequence still advancing). Check the
subscriber's handling (`handlers/callbacks.py`, the gap fetch), and add a
test.

### Issue 7: a reconcile store refused for another reason is read as "a newer copy won"
**Severity:** Low
**Description:** `store_permissions` also returns False when the peer's
answer fails `validate()`, or after `STORE_ATTEMPTS` lost writes
(`peer_permissions.py:281-285`). The reconcile then re-fetches what the
stored (old) copy grants, which is the data it just deleted, and logs that a
newer copy was stored.
**Location:** `actingweb/handlers/callbacks.py` `_reconcile_with_granting_peer`
**Recommendation:** re-sync only when the stored copy's `fetched_at` is
newer than the fetched one's; otherwise log the refusal.

### Issue 8: a non-`DbError` in the reconcile answers 500
**Severity:** Low
**Description:** Only the fetch is wrapped. A non-`DbError` from the delete
(`_delete_revoked_peer_data` re-raises every failure), the read or the
change detection escapes, and the callback answers 500 after a partial
delete. The sender resends only on 503. The callback's main path behaves
the same way.
**Location:** `actingweb/handlers/callbacks.py` `_reconcile_with_granting_peer`
**Recommendation:** answer 503 for a failed deletion on both paths, so the
resend finishes it, or accept this and document it.

### Issue 9: the hook routing is incomplete and rides on a side channel
**Severity:** Low
**Description:** Four problems:
- **The trustee path is missed.** `Actor.create_peer_trustee`
  (`actor.py:1446`) still calls `create_reciprocal_trust` directly, so an
  approve-on-create there runs no hook.
- **The web form never fires `trust_initiated`.** It still runs no
  `trust_initiated` for an ordinary create. That predates this range, but
  the changelog says every create route runs the same hooks.
- **The outcome travels through a mutable attribute.** It is
  `Actor.last_trust_approved_on_create`, reset only by `TrustManager`.
- **The async hook blocks the event loop.**
  `TrustManager.create_relationship_async` runs the application's hook on
  the event loop.

**Location:** `actingweb/interface/trust_manager.py:231-265`;
`actingweb/actor.py:1446`; `actingweb/handlers/www.py:985-1003`;
`CHANGELOG.rst`
**Recommendation:** return the outcome from `create_reciprocal_trust` (or a
small result object) instead of the attribute; run the async hook through
`asyncio.to_thread`; narrow the changelog claim or route the trustee path
too.

### Issue 10: a replaced pending row fires no `trust_deleted`
**Severity:** Low
**Description:** The replacement (`actor.py:1723-1728`), like
`create_verified_trust`'s, only logs. Whatever an application built from
the replaced request's `trust_request_received` stays.
**Location:** `actingweb/actor.py:1723-1728`
**Recommendation:** fire `trust_deleted` for the replaced row once the
conditional write wins, or document it.

### Issue 11: hygiene and cost
**Severity:** Low
**Description:** Two items:
- **Duplicated restore.** The handle restore is written three times in
  `db/dynamodb/trust.py:328-339`.
- **Per-key lookups on every poll.** `_as_permitted` builds the evaluator
  and evaluates per key per diff on every poll (`evaluate_bulk_property_access`
  exists), so a large backlog costs N×M lookups.

**Location:** as above
**Recommendation:** one restore before the raise or return; evaluate once
per request.

## Overall Assessment

**This range closes reverify-5's two holes as they were reported.** The
security review found nothing at HIGH or MEDIUM. Both backends are green,
the docs build, no recording changed, Emm's suite matches its baseline, and
the web form's approve-on-create works in a browser.

**The outside voice saw what the reviews of the create route missed.**
Approving an unverified request is the hole, whatever the route, and the
web UI's Approve button still does it (Issue 1). That button predates the
branch, but it is the plan's subject, and the security reference's advice
does not protect against it.

**The new pull filter and the narrowed row have three consequences.** The
filter checks the wrong path for a resource (Issue 4) and for an object
under a subtarget (Issue 5), and the narrowed row dropped a listing that
`master` allowed (Issue 3).

**Before the PR:**
- Issue 1, with an owner decision.
- Issues 2 to 5.
- The rest as small fixes.
- Then Emm's suite and another verification with the security review.

One fix answers Issues 1 and 2 together: re-verify a pending row before
any approval.
