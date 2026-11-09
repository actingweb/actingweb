# Verification: peer authorisation fixes (fifth run: the whole-branch review's fixes)

**Date:** 2026-11-09
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** 5c88e8a (code as of 376b71c; 5c88e8a adds records only)

This run verifies Iterations 32 to 37 (`7fc2f48..376b71c`), which answered
`verifications/2026-11-08-peer-authorisation-fixes-reverify-4.md` and
carried two owner decisions: the built-in `owner` rows compare with the
peer the path names, and `FanOutManager` sends a large payload in full. The
reviews were scoped to that delta, with the `owner`-row change read for
what it newly admits.

## Automated Check Results

- **Browser QA:** N/A. No iteration changes a page.
- **Built-in security review** (`/security-review` flow, scoped to
  `7fc2f48..376b71c -- actingweb`, confidence bar 8): **one HIGH finding**
  (Issue 2): any approved peer can now create a subscription through the
  `owner` row and pull unfiltered diffs. Checked against the code; confirmed.
- **Built-in code review** (`/code-review high 7fc2f48..376b71c`): ten
  findings. Checked each against the code: Issues 1, 2, 4, 6, 8 to 12 below,
  and two notes.
- **Outside voice** (codex `codex exec -s read-only` outside the sandbox,
  plus a fresh-context Claude reviewer): eight findings and two unverified
  notes. It independently found Issues 1 and 2, and added Issues 3, 5 and 7
  and part of 4 and 6. Codex flagged PostgreSQL's `created_at` overwrite;
  the reviewer dropped it because it matches DynamoDB's whole-item write,
  and I agree.
- **Full tier**, run on `5c88e8a` (same code as `376b71c`):
  - `poetry run ruff check actingweb tests`: pass.
  - `poetry run ruff format --check actingweb tests`: pass (530 files).
  - `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
  - `poetry run python tests/integration/verify_groups.py`: 54 groups;
    wire rows registry consistent.
  - `make test-all-parallel`, DynamoDB: **6063 passed**, 60 skipped,
    1 xfailed.
  - `make test-all-parallel`, PostgreSQL: **5860 passed**, 263 skipped,
    1 xfailed.
  - `sphinx-build -W ...`: build succeeded.
  - No wire recording changed by the run.
- **Emm's suite** on `376b71c`: PostgreSQL 2 failed / 7406 passed,
  DynamoDB 3 failed / 54 passed. Same tests as its `master` baseline (plan
  record, `5c88e8a`). Not re-run; no code changed since.

## Phase Verification

### Iterations 32 to 37 - ISSUES FOUND

**Changes verified (match the iterations):**
- `actingweb/handlers/base_handler.py:397-405`: `authorize` passes
  `peerid=path_peer or ""`. The owner decision is applied, but it admits
  more than the iteration's record says (Issue 2).
- `actingweb/handlers/subscription.py:13-22`: `_authorize_subscription_write`
  is a plain `authorize`. The refusal log is removed; its comment is left
  behind (Issue 11).
- `actingweb/fanout.py:519-530`: no downgrade; WARNING above the threshold.
- `actingweb/actor.py`:
  - `_approve_on_create` (`:2024-2039`) and its two call sites
    (`:1725`, `:1897`): Issue 1;
  - `only_if_absent=True` (`:1764`, `:1938`);
  - `_drop_failed_attempt` (`:2011-2022`): Issue 6;
  - the async catch widened (`:1911`).
- `actingweb/handlers/callbacks.py`:
  - `_reconcile_with_granting_peer` (`:1162-1202`) and its call on the
    ignored path (`:423-431`): Issue 4;
  - the untimed timestamp carry (`:458-469`);
  - the DELETE hook reads the `callback=True` row (`:218-227`).
- `actingweb/db/dynamodb/trust.py:254-330`: writes every given attribute
  under `Trust.id.exists()` (Issue 8 is a residue).
- `actingweb/db/postgresql/trust.py:28`: `created_at = EXCLUDED.created_at`.
- `actingweb/maintenance/peer_state.py:341-358`: exit 2 for a copy not
  rebuilt (Issue 10 is an edge).
- `actingweb/handlers/trust.py:453`, `:541-556`: `proven` passed into
  `_re_pair`.
- Docs and changelog: the adoption rows are gone and the new `owner`
  admissions are named, but not the subscription POST (Issue 12).

**Tests verified** (they exist and pass on both backends; reverify-4's
iteration record says each failed before its fix):
- `tests/test_trust_re_pair.py`:
  - `TestTheInitiatorAfterTheWholeBranchReview`:
    - `test_creating_the_trust_approves_a_pending_request`;
    - `test_a_row_written_meanwhile_is_not_replaced`;
    - `test_a_refused_attempt_keeps_a_row_another_request_wrote`;
    - `test_the_async_re_pair_probes_after_any_send_error`.
  - `TestTheTrustStoreAfterTheWholeBranchReview`:
    - `test_a_stale_handle_still_writes_what_it_is_given`;
    - `test_replacing_a_pending_row_renews_its_creation_time`.
- `tests/test_peer_binding.py`:
  - `test_an_ignored_revocation_asks_the_peer`;
  - `test_a_callback_without_a_timestamp_keeps_the_last_one`.
- `tests/test_peer_paths_binding.py`:
  - `test_the_owner_row_admits_a_peers_own_put_and_delete`;
  - `test_the_owner_row_admits_no_other_peers_subscription`.
- `tests/test_fanout.py`: `test_a_large_payload_is_sent_in_full`.

**Test gaps** (Issue 13):
- The approve test only covers an unverified-free setup, so it cannot see
  Issue 1.
- No test covers a subscription POST through the `owner` row, so nothing
  saw Issue 2.
- The `TestTheOwnersPartOfATrustRow` cases still insert an application row
  first, so the new `owner`-row admission on the trust row has no test of
  its own.
- The async approve-on-create path has no test.

**Security property, demonstrated** (`.claude/workflow/verify_implementation.md`):
the path binding still holds the caller to its own id.
`test_the_owner_row_admits_no_other_peers_subscription` asserts 403 for
peer `c` on peer `b`'s subscription. No provider found a cross-peer path.
The two new holes in this range (Issues 1 and 2) are not cross-peer path
access:
- Issue 1 hands a peer's identity to the wrong party.
- Issue 2 lets a peer read the owner's data past its permission grant.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Owner-initiated trust no longer approves a pending row | Fixed, but the fix approves an unverified row too (Issue 1) | iteration 32; `actor.py:1725` |
| 2. `owner` rows inert on `authorize()` paths | Fixed (owner decision); admits subscription creation for every relationship (Issue 2) | `base_handler.py:403` |
| 3. Initiator's unconditional create and delete | Fixed; check-then-delete residue (Issue 6) | `actor.py:1764`, `:2011` |
| 4. `FanOutManager` downgrade unfetchable | Fixed (owner decision) | `fanout.py:519-530` |
| 5. Multi-instance revocation dropped | Fixed; the reconcile deletes before it stores and swallows a fault (Issue 4) | `callbacks.py:1162-1202` |
| 6. Untimed callback erases the sender timestamp | Fixed | `callbacks.py:458-469` |
| 7. `prune` exits 1 when not rebuilt | Fixed; benign refusal also exits 2 (Issue 10) | `peer_state.py:349-358` |
| 8. Async re-pair catches only `httpx.HTTPError` | Fixed | `actor.py:1911` |
| 9. DELETE callback hook reads the wrong row | Fixed | `callbacks.py:218-227` |
| 10. DynamoDB `modify` compares with the handle | Fixed; handle left changed on a non-conditional fault (Issue 8) | `db/dynamodb/trust.py:254-262` |
| 11. Approval can land on a replaced pending row | Accepted and documented | `docs/reference/security.rst` (check the base URI before approving) |
| 12. PostgreSQL keeps the old `created_at` | Fixed | `db/postgresql/trust.py:28` |
| 13. Security heading overstates | Fixed | `docs/reference/security.rst:113` |
| 14. Missing type hints | Fixed | `db/dynamodb/trust.py:371-372`, `callbacks.py:287` |
| 15. Re-pair code in four copies | Partly: `proven` passed once; the sync/async twins stay separate (accepted) | `handlers/trust.py:453` |

## Remaining Tasks

- [ ] Owner decision on Issue 2 (what the `owner` row on `subscriptions`
      admits, and whether pulled diffs are filtered), then `/iterate_plan`
      for Issues 1 to 13.
- [ ] Emm's suite after that iteration, before the PR.
- Todos: the plan closes none; its deferral
  `thoughts/todo/full-state-fallback-replica.md` has its `INDEX.md` row.

## Issues Found

Two of this range's changes open holes the branch did not have at
`7fc2f48` (Issues 1 and 2). Neither lets a peer reach another peer's rows
through a path. Issue 1 hands a real peer's identity to whoever filed a
failed request under its name. Issue 2 lets any approved peer read the
owner's data past its permission grant.

### Issue 1: creating a trust approves an unverified pending row, with the requester's secret
**Severity:** High (security)
**Description:**
- An unauthenticated `POST /trust/friend` with `{"id": "Q", "baseuri":
  "<Q's real URL>", "secret": S}` whose verification fails is stored as a
  pending row: unverified, unapproved, Q's base URI, the attacker's secret.
- When the owner later creates the trust toward Q's URL, the URL equals the
  stored base URI and the relationship matches, so `_re_pair_refusal`
  passes (`actor.py:2042-2061`).
- `if not existing.get("approved"): return self._approve_on_create(...)`
  (`actor.py:1725-1728`; async `:1897-1902`) then approves the row as it
  stands. The owner's own `secret` argument is discarded.
- Bearer authentication never checks `verified` (`auth.py:276-286`), so S
  now authenticates as Q with `friend` rights.
- The approval notice to the real Q fails, and that failure is logged only
  at DEBUG (`actor.py:1602-1604`).
- With the `owner` row the attacker can then move "Q's" base URI
  (Issue 3).

The creation path refuses to auto-accept the same row (`actor.py:2310-2318`).
Before this range, the re-pair path stored a new secret only after the real
peer accepted. On `master`, the upsert overwrote the row with the owner's
secret. So the CHANGELOG's "as before" is not true.
**Location:** `actingweb/actor.py:1725-1728`, `:1897-1902`, `:2024-2039`
**Recommendation:** approve on create only when `existing.get("verified")`.
For an unverified pending row, either replace it with the owner's own
request (a conditional delete of the pending row, then the normal create
with the owner's secret), or refuse and name the pending request. Add a
test with an unverified row on both twins.

### Issue 2: any approved peer can now subscribe and pull unfiltered diffs
**Severity:** High (security)
**Description:**
- **The admission is new.** On `master` and at `7fc2f48`, `authorize()`
  passed no `peerid`, so `("owner", "subscriptions", "", "a")`
  (`config.py:337`) never matched. Only `friend` (`config.py:338`),
  `creator`, `trustee` and application rows admitted `POST
  /subscriptions/<id>`. Now the `owner` row admits every method on
  `subscriptions/<own id>[/...]` for every relationship type
  (`base_handler.py:400-404`): `associate`, `partner`, `admin` and custom
  types.
- **Nothing filters the stored diffs.** The POST checks no permission
  (`subscription.py:246-311`). `register_diffs` stores the unfiltered blob
  (`actor.py:4466`, `sub_obj.add_diff(blob=finblob)`), and only the push
  path filters (`actor.py:3062-3070`, and only `target == "properties"`).
  Both pull paths return stored diffs as stored (`subscription.py:383-396`
  and the `<seq>` handler).
- **The exploit.** An `associate` peer whose grant is `public/*`
  (`trust_type_registry.py:493`) POSTs a `properties` subscription. It gets
  201 where it got 403 before, then GETs every property change.
- **Already true for `friend`.** A `friend` peer with a narrowed grant
  already had this pull path on `master`.
- **Undocumented.** The changelog and migration guide name the trust-row
  PUT and the permissions read as new `owner` admissions, not subscription
  creation.

**Location:** `actingweb/handlers/base_handler.py:400-404`;
`actingweb/config.py:337`; `actingweb/handlers/subscription.py:246`, `:357`,
`:596`
**Recommendation (owner decision):**
- Narrow the admission: either pass `peerid` only from
  `_authorize_subscription_write` (the PUT and DELETE that motivated the
  change), or split the `owner` row into GET/PUT/DELETE on
  `subscriptions/<id>/<subid>`. Creation stays with the relationship's own
  rows.
- And/or filter served diffs through the peer's permissions on both GET
  paths. This also closes the pre-existing `friend` case, and the plan's
  own pull path (a 3.16 subscriber fetches `<seq>`) serves those diffs.
- Either way, add a test: an `associate` POST answers 403, or a pulled diff
  is filtered.

### Issue 3: a peer's own base-URI move skips the creation-time check and keeps `verified`
**Severity:** Medium (security)
**Description:**
- **What the move does.** Through the `owner` row, any approved peer may
  now `PUT /trust/<rel>/<own id>` with a new `baseuri`, which is the owner's
  accepted decision. The handler checks only `is_valid_peer_baseuri`
  (`handlers/trust.py:897-903`), which allows `http`, IP literals and
  private hosts. The row keeps `verified=True`.
- **What creation checks.** A creation runs `_base_uri_serves(baseuri,
  peerid)` and clears `verified` when the base URI does not serve the
  claimed id (`actor.py:2300`).
- **Consequence.** `FanOutManager`, permission callbacks and fetches then
  send authenticated requests to that host (for example
  `http://169.254.169.254/`): an authenticated SSRF from the actor's
  server. No secret leaks beyond the peer's own. Combined with Issue 1, the
  attacker holding Q's identity redirects Q's traffic.

**Location:** `actingweb/handlers/trust.py:897-913`
**Recommendation:** on a peer's own base-URI move, run `_base_uri_serves(new,
peerid)` and refuse (or clear `verified`) when it fails; add a test.

### Issue 4: the reconcile deletes before it stores, and swallows a fault
**Severity:** Medium
**Description:** `_reconcile_with_granting_peer` (`callbacks.py:1192-1200`)
reads the stored copy, deletes the revoked data, then calls
`store_permissions(fetched)` and ignores its result. It has three problems:
- **A concurrent grant loses its data.** If a newer callback stores a grant
  of `x` meanwhile, the reconcile deletes `x`'s data, its own store loses
  on `fetched_at`, and the stored copy grants `x` with the data gone. The
  reconcile's deletions are not added to `deleted`, so `_still_granted`
  (`:432-435`) never re-fetches them.
- **A fault is swallowed.** `except Exception` swallows a `DbError` from the
  strict delete, and the callback answers 204. The main path answers 503 on
  that fault so the sender resends; here revoked data stays.
- **The fetch blocks the answer.** The fetch is synchronous before the 204,
  although the docstring says "the callback is already answered".

**Location:** `actingweb/handlers/callbacks.py:1162-1202`, `:423-431`
**Recommendation:** store first (conditionally); delete only when the store
wins, against the copy it replaced. Let a `DbError` propagate to the 503
exit. Fix the docstring. Add tests for a fault and for a newer grant
landing first.

### Issue 5: `_approve_on_create` never fires `trust_fully_approved_local`
**Severity:** Medium
**Description:** `_approve_on_create` calls only `modify_trust_and_notify(...
approved=True)` (`actor.py:2030`). The `trust_fully_approved_local` hook is
fired by the HTTP PUT handler (`handlers/trust.py:921-947`), not by
`modify_trust_and_notify`. An application that subscribes back in that hook
never does so for a trust approved this way, while the peer's
`trust_fully_approved_remote` fires.
**Location:** `actingweb/actor.py:2024-2039`
**Recommendation:** fire the hook when the row ends approved and
peer-approved, as the PUT handler does; add a test.

### Issue 6: `_drop_failed_attempt` is check-then-delete, and misses two cases
**Severity:** Low
**Description:** `actor.py:2011-2022` reads the row, compares the secret,
then `delete()`s by peer id. That leaves three gaps:
- **A race.** A row replaced between the read and the delete is deleted.
- **No secret read back.** When `attempt_secret` is None (the read after
  create returned nothing), the attempt's own row is kept, and the log says
  another request replaced it. The `secret` argument is what was written.
- **A lost answer.** A row the peer already accepted (`peer_approved`)
  whose answer was lost is deleted.

The delete was unconditional on `master`, so this narrows old behaviour.
**Location:** `actingweb/actor.py:2011-2022`
**Recommendation:** compare with the `secret` argument; delete conditionally
(on the secret) where the backend allows it.

### Issue 7: a peer's `PUT {"approved": false}` on its own trust row answers 500
**Severity:** Low
**Description:** `handlers/trust.py:842` `params["approved"] is True or
params["approved"].lower() == "true"`: a JSON `false` has no `.lower()`, and
only `ValueError` is caught. The code is old, but peers reach it only since
this range.
**Location:** `actingweb/handlers/trust.py:842`
**Recommendation:** `str(params["approved"]).lower() == "true"`.

### Issue 8: DynamoDB `modify` leaves the handle changed on a non-conditional fault
**Severity:** Low
**Description:** The given values are set on `self.handle` before
`update()` (`db/dynamodb/trust.py:255-257`). Only the conditional-check
failure restores the handle, so after a throttling or network `DbError` the
object holds values never written. Writing every given attribute also means
the per-request `last_connected_via` write (`auth.py:189`) is now always
sent.
**Location:** `actingweb/db/dynamodb/trust.py:254-270`
**Recommendation:** restore `before` on any exception, or set the handle
only after `update()` succeeds.

### Issue 9: `FanOutManager` leftovers
**Severity:** Low
**Description:** Two leftovers from removing the downgrade:
- `granularity_downgraded` is always False but still threaded into the
  delivery result (`fanout.py:192`, `:524`, `:560`).
- The size WARNING is logged once per subscriber per delivery, not once per
  fan-out (`fanout.py:525-529`).

**Location:** `actingweb/fanout.py:524-530`
**Recommendation:** log once in `deliver()`; drop the dead field (or keep it
documented as always False).

### Issue 10: `prune --apply` exits 2 when a newer copy already exists
**Severity:** Low
**Description:** `store_permissions` returns False when a concurrent
callback stored a newer copy, which is a rebuilt copy. `_rebuild_copy`
reports it "not rebuilt" and the command exits 2.
**Location:** `actingweb/maintenance/peer_state.py:370-385`
**Recommendation:** re-read on a refused store; a stored copy counts as
rebuilt.

### Issue 11: stale comment and a one-line wrapper in the subscription handler
**Severity:** Low
**Description:** `subscription.py:10-12` still describes the removed
`_GET_ROW_REFUSALS_LOGGED` set, above `_authorize_subscription_write`, which
is now a pass-through.
**Location:** `actingweb/handlers/subscription.py:10-22`
**Recommendation:** remove the comment; inline the wrapper or keep it as the
single place Issue 2's fix lands.

### Issue 12: the changelog's wording for this range is not exactly true
**Severity:** Low
**Description:** The entries for this range have three wording gaps:
- "creating the trust approves it (and tells the peer), as before"
  (`CHANGELOG.rst:89`) is not what `master` did (Issue 1).
- The subscription-creation admission (Issue 2) is not named.
- Approve-on-create and full-payload delivery have no bold
  **Behavior change:** sentence, which `CLAUDE.md` `### Changelog` requires
  for a consumer-visible shift.

**Location:** `CHANGELOG.rst:85-95`, the CHANGED entry on access rows
**Recommendation:** reword after Issues 1 and 2 are decided.

### Issue 13: tests that could not see Issues 1 and 2
**Severity:** Low
**Description:** Four gaps:
- **Approve-on-create, sync.**
  `test_creating_the_trust_approves_a_pending_request`
  (`tests/test_trust_re_pair.py:1015`) uses a verified row. Its `all(...)`
  assertion is vacuous, and it never checks that the peer was notified.
- **Approve-on-create, async.** The async path has no test.
- **Subscription POST.** No test covers a subscription POST through the
  `owner` row.
- **The trust row's `owner` admission.** `TestTheOwnersPartOfATrustRow`
  (`tests/test_peer_paths_binding.py:500`) inserts an application row
  first, so the `owner` row's own admission is untested.

**Location:** as above
**Recommendation:** add the cases with the fixes for Issues 1 to 3.

### Notes (below the bar or unverified)
- `GET /trust/<any type>/<own id>/permissions` does not compare the path's
  relationship with the peer's (outside voice, unverified): a peer may read
  another type's default permissions. This is low value.
- OAuth2, MCP and SPA callers: `acl["peerid"]` is set only from a trust
  bearer (`auth.py:~285`, `~617`), so the `owner` rows do not match for
  them (security scan). The outside voice left open whether an OAuth2
  client trust's stored secret could ever match as a bearer.
- `max_payload_for_high_granularity` no longer limits anything. The
  migration note says so; a large fan-out now costs its full size.

## Overall Assessment

Iterations 32 to 37 closed reverify-4's fifteen issues as recorded. The
Full tier is green on both backends, the docs build, Emm's suite matches
its baseline, and the path binding still holds every peer to its own id.

Two fixes in this range opened security holes the branch did not have at
`7fc2f48`.
- **Issue 1, approve-on-create.** It approves an unverified pending row
  with whatever secret its requester chose, so a stranger who filed a
  failed request under a real peer's name becomes that peer the moment the
  owner pairs with it.
- **Issue 2, the `owner`-row change.** Decided to spare subscribers two
  adoption rows, it also opened subscription creation to every
  relationship, and pulled diffs are never permission-filtered.
- **Issue 3** widens what the accepted base-URI move can reach.

The PR must not open with Issues 1 to 3. Issue 2 needs an owner decision
(narrow the admission, filter the pulled diffs, or both); 1, 3 and 4 have
clear fixes. Then run Emm's suite and verify that delta. Given that this
range's own fixes introduced the two holes, the next verification should
again include the security review.
