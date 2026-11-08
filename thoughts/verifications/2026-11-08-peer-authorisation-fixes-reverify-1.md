# Verification: peer authorisation fixes (re-run after the iteration)

**Date:** 2026-11-08
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** fix/3.16.0-peer-authorisation (local only; not pushed)
**Commit:** de5276c (code at d836bd0)

This run verifies the plan's Iterations 1 to 10 (`63bed00..d836bd0`), which
answered `verifications/2026-11-08-peer-authorisation-fixes.md`. Phases 0 to
5 were verified there and are unchanged except for what the iteration
touched; this document does not re-walk them.

## Automated Check Results

- **Browser QA:** N/A. No phase or iteration changes a page (the demo change
  is docstrings only).
- **Second opinion (outside voice):** codex (`codex exec -s read-only`,
  outside the sandbox) and a fresh-context Claude reviewer, on
  `git diff 63bed00..d836bd0 -- actingweb examples tests/test_*.py`. Eleven
  findings plus notes. I checked each against the code and folded them into
  Issues 1 to 8 below.
- **Built-in code review and security review:** not re-run as skills. They
  ran on the whole branch in the previous verification. This round's delta
  (about 600 lines in auth, trust storage and concurrency) got the outside
  voice plus my own line-by-line read of the diff, which is recorded under
  Phase Verification. The delta touches auth, so a review was warranted
  ([scale reviews to the delta]); the outside voice was the one chosen.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (530 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: 54 groups
  documented; the wire rows registry is consistent.
- `make test-all-parallel`, DynamoDB: **6024 passed, 1 failed**, 60
  skipped, 1 xfailed (exit 2).
  - The failure was `tests/performance/test_backend_performance.py::TestActorPerformance::test_actor_update_performance`:
    `assert result is True` / `assert False is True`, meaning
    `DbActor.modify(creator=...)` returned False under parallel load.
  - Re-run alone three times (`TestActorPerformance`, sequential): 4
    passed each time.
  - Neither the test nor the actor storage is in this branch's diff
    (`git diff master...HEAD` touches neither). This is a parallel flake
    outside the plan; see Remaining Tasks.
- `make test-all-parallel`, PostgreSQL: **5822 passed**, 263 skipped, 1
  xfailed (exit 0).
- `sphinx-build -W ...`: build succeeded.
- Emm's suite on `d836bd0` (plan Iteration 10, not re-run here): PostgreSQL
  2 failed / 7406 passed, DynamoDB 3 failed / 54 passed. These are the
  `master` baseline's failures, by name.

## Phase Verification

### Iterations 1 to 10 - ISSUES FOUND

**Changes verified:**
- `actingweb/handlers/trust.py:688-703`: the per-peer GET pops `secret` and
  `verification_token` when `acl["peerid"]` is set and differs from the
  path peer. The trustee bearer sets `acl["peerid"] = ""` (`auth.py:584`),
  so the creator and the trustee keep both fields. Matches Iteration 1.
- `actingweb/handlers/trust.py:862-878`: a peer caller's `baseuri` on
  another peer's row answers 403. Matches.
- `actingweb/actor.py:2234-2242`, `2289-2298`: `_base_uri_serves` checks
  `<baseuri>/meta`'s `id` (one try) after the token check. Matches the
  letter of Iteration 2, but not its rationale (Issue 1).
- `actingweb/db/dynamodb/trust.py:244-335`: the attributes that changed go
  into one `UpdateItem` conditioned on `Trust.id.exists()`, and
  `ConditionalCheckFailedException` returns False.
  `db/postgresql/trust.py:618-621` returns `updated > 0`. Matches
  Iteration 3.
- `actingweb/actor.py:1724-1735`, `1888-1899`, `2035-2111`: on no answer or
  a 5xx, the re-pair calls `_re_pair_unknown` / `_re_pair_unknown_async`,
  which GETs `<stored baseuri>/trust/<rel>/<own id>` with the new bearer.
  Only a 200 stores the new secret. Matches Iteration 4, with a gap
  (Issue 3).
- `actingweb/handlers/callbacks.py:316-394` and
  `peer_permissions.py:216-231`, `277-289`:
  - `fetched_at` is the receiver's clock;
  - `extra_attributes["sender_timestamp"]` holds the sender's timestamp,
    built by the handler (the body cannot set it);
  - callbacks are compared with `_parsed_time` against the previous
    callback only;
  - the store compares parsed times.

  Matches Iteration 5.
- `actingweb/maintenance/peer_state.py:37-41`, `218-223`:
  `--all-permissions` lists every live copy as `permissions-copy`. Matches
  Iteration 6, with a consequence the guide does not state (Issue 5).
- `actingweb/fanout.py:473-532`: no trust, secret or base URI means nothing
  is sent. The URL is built from the stored base URI, and the bearer is
  always set. Matches Iteration 7.
- `callbacks.py:316-320` answers 400 for a body or `data` that is not an
  object, and `callbacks.py:475` sets `hook_data["method"] = method`.
  `auth.py:795-802` is typed. The demo docstrings are corrected. Matches
  Iteration 8.

**Security properties, the test that pins each:**

| Property | Test | What it asserts |
| --- | --- | --- |
| An `admin` peer reads no other peer's secret | `tests/test_peer_paths_binding.py:619` `TestNoPeerReadsAnothersSecret` | no `secret` / `verification_token` in the admin peer's GET; its `baseuri` PUT answers 403 |
| A base URI naming another id is stored unverified | `tests/test_trust_re_pair.py:668` | `w.row(claimed)["verified"] is False` when `/meta` names `someone-else` |
| A usage write cannot restore the old secret | `tests/test_trust_re_pair.py:705` | `w.row(w.b)["secret"] == new` after a stale handle's `modify(last_accessed=...)` |
| A modify after a delete does not recreate the row | `tests/test_trust_re_pair.py:720` | `stale.modify(...) is False` and `not w.row(w.b)` |
| A lost answer the peer confirms is stored | `tests/test_trust_re_pair.py:733` | the probe URL and bearer, then `w.row()["secret"] == new` |
| A slow sender's revocation applies | `tests/test_peer_binding.py:711` | 204, the stored `excluded_patterns == ["revoked"]`, `sender_timestamp` present |
| A pre-3.16 row in another offset does not block | `tests/test_peer_binding.py:727` | the newer callback's `excluded_patterns == ["newer"]` |

The `/meta` test exercises an honest host that names a different id. It
does not exercise a host that names the victim's id, which is the attack
Issue 4 described (Issue 1 below).

**Deviations from plan:**
- The previous verification recommended a swap conditioned on
  `secret = :current`. The iteration conditions only on the row existing.
  The usage write no longer writes back attributes it did not change, which
  is the race the recommendation targeted. Two concurrent proven re-pairs
  from the same peer are last-writer-wins. Acceptable: only the holder of
  the current secret can send either.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-08-peer-authorisation-fixes.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. An `admin` peer reads another peer's secret and becomes that peer | **Fixed as stated; the outcome survives through DELETE** (Issue 2 below) | GET redaction `handlers/trust.py:698-702`; PUT refusal `:862-878`; DELETE still exempt `:1094-1100` |
| 2. The re-pair's write is not atomic on DynamoDB | Fixed | `db/dynamodb/trust.py:319-333`; `tests/test_trust_re_pair.py:705`, `:720` |
| 3. A lost re-pair answer splits the secrets | **Partly fixed**: a re-pair answered 202 (unapproved) is never confirmed (Issue 3 below) | `actor.py:2048-2066`; `handlers/trust.py:680-684` |
| 4. A verified squat is permanent | **Still open** (Issue 1 below) | `actor.py:2289-2298` |
| 5. `prune` keeps a forged copy for a trusted peer | Fixed, with a new consequence (Issue 5 below) | `maintenance/peer_state.py:218-223`; `tests/test_peer_state_command.py:255` |
| 6. `FanOutManager` can send an unauthenticated callback | Fixed | `fanout.py:481-493`; `tests/test_fanout.py` |
| 7. The permission ordering mixes clocks | Fixed for sequential callbacks; concurrent ones race (Issue 4 below) | `callbacks.py:373-394`; `tests/test_peer_binding.py:711`, `:727` |
| 8. The demo's webhook docstrings | Fixed | `examples/demo/shared_hooks/app/callback_hooks.py` |
| 9. The permission branch's edges | Fixed | `callbacks.py:316-320`, `:475`; `tests/test_peer_binding.py:748` |
| 10. `_match_access_row` is untyped | Fixed | `auth.py:795-802` |
| 11. The guide on `remote-data` for a trusted peer | Fixed | `maintenance/peer_state.py:46-49`; `docs/guides/database-maintenance.rst` |

## Remaining Tasks

- [ ] Owner decisions on Issues 1 and 2, before the PR opens. Both are
      holes in what the changelog's SECURITY entry claims.
- [ ] Issues 3 to 5 (`/iterate_plan`).
- [ ] Issues 6 to 8: fold or accept.
- [ ] The parallel flake in `test_actor_update_performance`: outside this
      plan. If it recurs, it belongs in a todo next to
      `ci-postgres-parallel-flakiness.md`. Not filed: seen once, and it
      passed three times alone.
- Todos: the plan closes none. Its one deferral is
  `thoughts/todo/full-state-fallback-replica.md`, which has its `INDEX.md`
  row.

## Issues Found

### Issue 1: the `/meta` check does not stop a squat; auto-accept approves one regardless
**Severity:** High
**Description:**
- **The check is answered by the squatter.** `_base_uri_serves` asks the
  requester's own server whether it is the claimed actor
  (`actor.py:2292`, `res = self.get_peer_info(baseuri, max_retries=1)`;
  `:2298`, `return isinstance(data, dict) and data.get("id") == peerid`).
  An attacker who names X's id serves `/meta` as `{"id": X}`, passes, and
  is stored verified. The real X is then refused (`actor.py:2176`,
  "a verified or approved trust row exists").
- **The attack does not even need to verify.** With auto-accept on,
  `approved` comes from configuration and ignores `verified`
  (`handlers/trust.py:467-471`, `if self.config.auto_accept_default_relationship
  and self.config.default_relationship == relationship: approved = True`).
  An approved row is never replaced, and authentication never reads
  `verified`.
  - The demo sets auto-accept (`examples/demo/application.py:149`). The
    library default is off (`config.py:223`).
- **What does work:** the check refuses an honest host whose `/meta` names
  a different id, and that is what the test pins
  (`tests/test_trust_re_pair.py:668`).
- **The docs:** the changelog and `docs/reference/security.rst:113` say a
  creation verifies only when the base URI's `/meta` names the claimed id.
  That is literally true, but neither says the requester controls the
  answer.

The protocol has no binding of an actor id to a host that a third party can
check, so no URL-shaped test fixes this. Requiring the base URI to end in
`/<peerid>` is forgeable in the same way.

**Location:** `actingweb/actor.py:2234-2242`, `:2289-2298`;
`actingweb/handlers/trust.py:467-471`.
**Recommendation:** Owner decision. Options:
- (a) Auto-accept only a creation that verified, and document that
  `verified` proves control of the base URI, not of the id. A squatted row
  is then pending (until the owner approves it), and a later verified
  request from the real peer replaces it.
- (b) Accept the limitation and document that the remedy is the owner's
  `DELETE …?notify=false`, naming auto-accept as the exposure.

Either way, drop or re-word the `/meta` claim in the changelog and the
security reference. A check whose answer the requester controls should not
be described as a binding.

### Issue 2: an `admin` peer can still become another peer, through DELETE
**Severity:** High
**Description:** The iteration took the secret away from an `admin` peer on
GET and the base URI on PUT. DELETE is still exempt:
`handlers/trust.py:1094-1100` passes `path_peer=peerid`, and the admin
exemption returns True (`auth.py:786-787`, `if relationship == "admin" and
not peer_caller_only: return True`). Admin peer D sends
`DELETE /trust/friend/X`, then sends `POST /trust/friend` with `id=X` and
D's own base URI. Issue 1 makes that row verified, or approved under
auto-accept. D now holds the only secret for "X", which is the outcome
Issue 1 of the previous run described.

`?notify=false` is creator only (`handlers/trust.py:1116-1122`), so D's
DELETE notifies X and X deletes its side too. That makes the takeover
visible to X, but X cannot recover: the row for X is now D's.

**Location:** `actingweb/handlers/trust.py:1094-1100`; `actingweb/auth.py:786-787`.
**Recommendation:** Owner decision, since it narrows the Phase 2 admin
exemption again. Refuse a peer caller's DELETE of another peer's row
(`peer_caller_only=True` there, or the same explicit check as the PUT), or
record the exemption as decided. Closing Issue 1 limits what the re-create
achieves either way.

### Issue 3: the lost-answer probe never confirms a re-pair the peer answered 202
**Severity:** Medium
**Description:** When the peer's owner has not approved the trust, the
re-pair is accepted (secret swapped, 202). If that answer is lost, the
probe GETs the peer's row with the new bearer. The peer answers 403 for an
unapproved trust (`handlers/trust.py:680-684`, `if not my_trust["approved"]
and is_peer_token: … 403`). The initiator accepts only a 200
(`actor.py:2048`, `if status == 200:`), so it keeps the old secret and the
pairing splits, which is the Issue 3 outcome.

The warning's advice ("If requests to the peer now answer 403, the peer
accepted it") cannot tell this case apart: an unapproved trust answers 403
either way.

**Location:** `actingweb/actor.py:2045-2066`; `actingweb/handlers/trust.py:680-684`.
**Recommendation:** Probe something that authenticates before applying the
approval gate, or treat the 403 "Trust relationship not approved" (as
opposed to an authentication failure) as confirmation with
`peer_approved=False`. Add a test for the 202 case.

### Issue 4: concurrent permission callbacks can still roll back a revocation
**Severity:** Medium
**Description:** The ordering check is a read, a compare and an
unconditional write:
- `callbacks.py:371`: `old_permissions = store.get_permissions(...)`;
- `:373-394`: the compare;
- then `store.store_permissions(peer_perms)`.

The sender fires each change as its own task (`trust_permissions.py`,
`asyncio.create_task`). A grant (T1) and a revoke (T2) handled concurrently
both read T0. If the revoke stores first and the grant second, the grant
wins: the revoked data was deleted and is then synced back. Nothing is
logged.

The race predates this plan. The iteration's ordering makes the sequential
case right, not the concurrent one.

**Location:** `actingweb/handlers/callbacks.py:371-394`, `peer_permissions.py:277-289`.
**Recommendation:** A conditional write on the stored `sender_timestamp`
(DynamoDB condition / PostgreSQL `WHERE`), or a per-pair lock; at minimum,
a todo with the scenario.

### Issue 5: after `prune --all-permissions --apply`, the next revocation deletes nothing
**Severity:** Medium
**Description:**
- **What happens:** with the copy gone, the next callback is "initial".
  `detect_permission_changes` returns no revoked patterns when
  `old_permissions is None` (`peer_permissions.py:733-736`). A peer's
  revocation that arrives first after the prune therefore leaves the
  revoked data in `RemotePeerStore`, and it re-syncs every granted pattern.
- **What the docs say:** the module docstring and the guide say only that
  a removed copy "is rebuilt from the peer's next permission callback or
  the next query" (`maintenance/peer_state.py:37-41`).
- **A milder effect:** a copy fetched by query carries no
  `sender_timestamp` (`peer_permissions.py:484-487`, `:589-592`), so the
  ordering check is skipped once after every query. That is by design
  (Iteration 5), but it is the same gap.

**Location:** `actingweb/maintenance/peer_state.py:218-223`, `peer_permissions.py:733-736`.
**Recommendation:** Say in the guide and the `--all-permissions` help that
a prune should be followed by a permission query for each peer (or a
`remote-data` prune for the peer). Alternatively, have the command trigger
the query.

### Issue 6: a refused DynamoDB modify leaves the local object changed; two callers ignore False
**Severity:** Low
**Description:**
- `db/dynamodb/trust.py:256-316` sets `self.handle.*` before the update.
  On `ConditionalCheckFailedException` it returns False without restoring
  them, and `trust.py:345-358` has already changed `self.trust`.
- `auth.py:202` (`db_trust.modify(**modify_kwargs)`) and
  `interface/trust_manager.py:540` ignore the result. The second then logs
  "Updated existing OAuth trust".
- With nothing changed, DynamoDB returns True without a request
  (`db/dynamodb/trust.py:321-322`, `if not changed: return True`), while
  PostgreSQL returns False for a deleted row (`db/postgresql/trust.py:621`).

**Location:** as quoted.
**Recommendation:** Restore `attribute_values` from `before` on failure,
and check the result at the two callers (the usage write may stay
best-effort, but should not report success). Accept or align the no-change
parity.

### Issue 7: the `/meta` fetch: one try, redirects followed, any size
**Severity:** Low
**Description:**
- **Cost per request:** an unauthenticated `POST /trust/<rel>` now causes
  two outbound fetches to a URL the requester chose: the verification GET
  and `get_peer_info(baseuri, max_retries=1)` (`actor.py:2236`). Each can
  stall a worker for up to 15 seconds and follows redirects.
- **Transient failures:** one failed `/meta` stores a legitimate peer
  unverified (pending without auto-accept), and that row can then be
  replaced (`only_if_pending`).
- **The probe's error handling:** the async probe catches only
  `httpx.HTTPError` (`actor.py:2105`), so an `httpx.InvalidURL` from a
  malformed stored base URI escapes. The sync probe catches `Exception`.

The SSRF class itself predates this plan.

**Location:** `actingweb/actor.py:2234-2242`, `:2289-2298`, `:2095-2110`.
**Recommendation:** Fold into the Issue 1 decision. If the check stays,
use the default retries. Catch `Exception` in the async probe, as the sync
one does.

### Issue 8: `FanOutManager` reads the trust outside its `try`
**Severity:** Low
**Description:** `fanout.py:481` (`trust = self._actor.trust.get_trust(peer_id)`)
runs before the `try`. A `DbError` surfaces through
`gather(return_exceptions=True)` as a failed delivery for peer `"unknown"`
(`fanout.py:432-438`). The `callback_url` parameter is still accepted and
now ignored.
**Location:** `actingweb/fanout.py:473-493`.
**Recommendation:** Catch the error inside and report it for the real
peer. Note in the docstring that `callback_url` is ignored, or remove the
parameter.

## Overall Assessment

The iteration fixed what it set out to fix in the cases its tests exercise.
Issues 2, 6, 8, 9, 10 and 11 of the previous run are closed with meaningful
tests, and Issue 7 is closed for sequential callbacks. Both backends are
green, apart from one parallel flake outside the diff that passes alone.
The documentation describes the new behaviour.

It does not close the two holes the previous run ranked highest in effect:
- **A squat is still permanent.** The `/meta` check is answered by the
  squatter, and auto-accept approves a creation that never verified
  (Issue 1).
- **An `admin` peer can still become another peer** by deleting its row and
  re-creating it (Issue 2).

A lost 202 re-pair still splits a pairing (Issue 3). Issues 1 and 2 need
owner decisions, and the changelog's `/meta` sentence should not ship as a
binding. The PR should not open until Issues 1 to 3 are resolved.
`/iterate_plan` is next. A further verification should re-run the outside
voice: the remaining fixes touch auth.
