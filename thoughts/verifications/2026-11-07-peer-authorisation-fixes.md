# Verification: callers reach only what is theirs on `/callbacks`, `/permissions` and `/subscriptions`

**Date:** 2026-11-07 (started during implementation; `/verify_implementation` completes it)
**Plan:** thoughts/plans/2026-11-06-peer-authorisation-fixes.md
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md,
thoughts/research/2026-11-07-peer-authorisation-research-pass.md
**Branch:** fix/3.16.0-peer-authorisation (local only until the PR opens)

This document opens with what the plan asks each phase to put here before
its handler changes: the phase's scenarios run once on the tree as it was,
and the reason each existing test that pinned the old behaviour was changed.
Nothing from a pre-fix run is committed as a recording. `/verify_implementation`
adds its own sections below.

## Phase 1: `/callbacks`

### Pre-fix runs

The scenarios of `tests/integration/test_wire_access.py`, run on the tree at
`8307037` (Phase 0) with the Phase 1 library changes set aside, DynamoDB,
both topologies (identical outcomes). What each answered, and what the
snapshot showed afterwards:

| Row | Before the fix | After the fix (recorded) |
| --- | --- | --- |
| WA1 | No credentials: the callback for B's subscription **204, applied** (B's replica gains `planted`, sequence 1, the data hook ran); an unknown id 404 | 401 for both; nothing applied |
| WA2 | No credentials: a permission callback for A **204, stored** (B's copy now excludes `planted`), and for a peer B has no trust with **204, stored** (a row for X), the `permissions` hook ran for both | 401; no row for X; no hook |
| WA3 | No credentials on `/callbacks/wire_ping`: GET, POST, PUT **200** (hook not run: nothing processed); DELETE 401 | 401 with a challenge on every method |
| WA4 | A bearer nobody holds: the subscription callback **204, applied**; the permission callback **204, stored**; the generic one 403 | 403 on all three |
| WA5 | C (friend), S (subscriber) and D (admin) under A's id: every subscription and permission callback **204**; C's applied the diff, each permission callback replaced B's stored copy | 403 for each; nothing applied |
| WA6 | B's creator: subscription callback **204, applied**; permission callback **204, stored** | 403 |
| WA7 | E (not approved), under its own id: permission 403; subscription 404 | 403 for both |
| WA8 | A's bearer, a body `url` on `wire_other_app`: **B sent its `GET` with A's bearer to `wire_other_app`**, applied what came back and acknowledged to A | B fetches from A's stored base URI; `wire_other_app` receives nothing |
| WA9 | `DELETE /<B>/callbacks/subscriptions/<A>/<subid>` by C **204, B's subscription deleted** (hook ran); by B's creator 204 | 403 for both; the subscription stays |
| WA10 | B, its bearer, to A under the id of its own subscription at A: **204; A's replica of B gained `planted`** | 403; A holds nothing of B |
| WA11 | A's bearer on the generic branch: `wire_ping` runs its hook (200); an unhandled name 200; **`permissions` ran the `permissions` hook (200)** on GET, POST and DELETE; `subscription`, `www`, `resource_x` 200; a bare `subscriptions` GET 200, POST and DELETE **500** (`IndexError`) | `wire_ping` and the unhandled name as before; the reserved names 403 with no hook; a bare `subscriptions` 403 on GET, 400 on POST and DELETE |
| WA15 | Type `permission`: **204, applied** with the data hook told type `permission`; an unknown type 204, applied as a diff | 400 for both; nothing applied |
| WA17 | A permission callback a day ahead **stored with `fetched_at` in the future**; the next, current one **ignored** (B still excludes `first`) | The first 400 (more than 5 minutes ahead), the second applied (B excludes `second`); the stored time is never ahead |

Expected from reading (plan, Phase 1 "New Tests"): 204 and applied for
`WA1`, `WA2`, `WA4`, `WA5`, `WA6`, `WA10`, `WA15`; `wire_other_app` receives
the fetch for `WA8`; the subscription deleted for `WA9`. All confirmed. Not
predicted: an unauthenticated generic callback answers 200 on GET, POST and
PUT and 401 on DELETE (`WA3`; the Unverified note on what it answers is
settled), and a bare `/callbacks/subscriptions` POST or DELETE raised (500).

### Existing tests changed, and why

- `tests/test_callback_in_progress_answer.py` (four handler setups) and
  `tests/test_db_fault_callers.py::TestB10PermissionCallback`: the mocked
  `auth_obj` gains a real authentication state (`response` code 200 and an
  `acl` naming the peer the path names), because the handler now
  authenticates before anything else; the low-granularity fetch test's
  trust gains a `baseuri`, because the fetch is built from it.
- `tests/integration/test_subscription_flow.py::test_038`: a deleted peer's
  bearer now answers 403 before the lookup (was 404).
- `tests/integration/test_subscription_flow.py::test_016` (not in the
  plan's list): a callback for an unknown subscription id by the right peer
  answers 403, as the specification says for a callback URI that does not
  exist with authentication data (was 404).

### Outside voice on the Phase 1 commit

codex and a fresh-context reviewer, on `8307037..91d027c`. No route around
the binding. Findings and disposition:

- The clamp lost the sender's order (a fast sender's grant arriving after
  its revoke was applied): owner decision, replaced by a 5-minute skew
  window and 400; `WA17` re-recorded.
- A stale permission update still deleted revoked replica data and synced
  (only the hook waited for the store): fixed, nothing runs for it.
- A PUT to a callback was authorised as POST: authorised as PUT.
- A timestamp that overflows in UTC answered 500: 400.
- A peer trustee's Basic retry after a refused bearer cannot succeed on the
  peer branches: for the changelog (Phase 5).

## Phase 2: `/subscriptions`, `/permissions`, `/trust/<type>/<id>`; the method rule

### Pre-fix runs

The scenarios added to `tests/integration/test_wire_access.py`, run on the
tree at `ef5fba1` with the Phase 2 library changes set aside, DynamoDB, both
topologies (identical outcomes). Requests go to A; C, D, S and the other
peers hold trusts to A.

| Row | Before the fix | After the fix (recorded) |
| --- | --- | --- |
| WA12 | C (friend): lists B's subscriptions **200**, reads B's subscription **200**, **consumes B's diff (200)**, **clears B's queue (204)**, **deletes B's subscription (204, hook ran)** | 403 each; B's queue and subscription unchanged |
| WA13 | C subscribing under B's id: 403 (the existing binding) | 403 |
| WA14 | Each peer reads its own (200, every type); **C reads B's permissions (200)**; A's creator reading B's **403** (no row); an admin reads B's 200; C asking for an unknown id 404 | Own 200; C 403; A's creator 200; admin 200; the unknown id 403, the same as another peer's |
| WA16 | S (`subscriber`, an application GET row on `trust/<type>/<id>`): **reads B's trust row (200), its secret and verification token included**, and B's permissions (200); its own 200 | B's: 403 each; its own: 200 |
| WA18 | C, `GET /subscriptions?peerid=<B>`: **200 with B's rows**; with no query 403 | 403 for both |

Expected from reading: `WA12`, `WA14`, `WA16` open; confirmed. Not
predicted: `WA18`'s query reached B's rows because the FastAPI route binds
`?peerid=` to the path's peer (`fastapi_integration.py:1253-1264`), so the
query is the per-peer path and the binding refuses it there; the root
handler's own filter is covered by the unit tests.

### Re-recorded: the three `.subscriber` rows

Read diff, each matching the plan's prediction; the `.subscriber_adopted`
rows and every other recording are byte-identical:

- `WD6.subscriber`: B's acknowledgement `PUT …/<subid>` answers 403 (was
  204); the diff was already consumed by B's `GET …/<subid>/1`, so A's queue
  is the same as before.
- `WQ3.subscriber`: every clear answers 403 (`{"sequence": 1}`, `0`, none,
  text, an unknown id, `GET ?_method=PUT`), where before the first two and
  the override were 204 and the malformed ones 400 and 404; A's queue keeps
  all three diffs.
- `WC4.subscriber`: A's `DELETE /<B>/subscriptions/<A>/<subid>` answers 403
  (was 204); A deletes its own row and answers its creator 204; B keeps a
  dangling callback subscription.

### Existing tests changed, and why

- `tests/test_permissions_handler.py::test_get_permissions_authorization_failed`:
  authorisation now precedes the trust lookup and carries `path_peer`; the
  test asserts both (the plan's listed `:150-167` needed no change: a
  creator-like mock still reaches the 404 for a missing trust).

### Outside voice on the Phase 2 commit

codex and a fresh-context reviewer, on `ef5fba1..cf4f972`. Findings and
disposition (folded in their own commit):

- The trust-site tests passed without `path_peer` (the default rows refused
  C first): each now inserts a row that admits C.
- A peer bound to its own trust row could, under an application row
  admitting every method, approve the row or write its own permissions:
  refused for every peer but an admin.
- The trust DELETE answers 404 for an unknown row before authorisation,
  unauthenticated callers included: kept, as planned
  (`delete_reciprocal_trust` relies on the 404); an existence probe for
  (actor, relationship, peer id) remains.
- A client view filtered on its trust's peer id but creates rows under its
  accessor id: lists both.
- The subscription root's POST did not bind the body's `peerid`: a peer
  caller may subscribe the actor only to itself.
- `AwProxy` raised on a non-2xx answer whose JSON body is not an object:
  turned into an error; the async 403 is tested.
- FastAPI and Flask answer the root's `?peerid=` differently (403 through
  the per-peer handler, a filtered 200): recorded.
- The default `owner` rows never bind through `authorize()`, which passes
  no `peerid`: a design note for the specification plan.

Answered with nothing found: every `change_resource` caller treats `error`
as failure or ignores the result; no code reads `.subscriptions` through a
view; `acl["rights"]` is never read, so the method rule's second probe
changes nothing later in the request.

## Phase 3: a trust request for an existing peer

### Pre-fix runs

The scenarios of `tests/integration/test_wire_trust.py`, run on the tree at
`a53efb8` with the Phase 3 library changes set aside, DynamoDB, both
topologies (identical outcomes):

| Row | Before the fix | After the fix (recorded) |
| --- | --- | --- |
| WT1 | B re-initiates: A verifies with the new secret and **replaces its row: `approved` reset to false** (the owner's approval lost), 202, `trust_request_received` ran; B's row loses `peer_approved` | B proves its current secret: 201, the secret swapped, `approved` kept, no hook; the next callback carries the new secret |
| WT2 | A request with no credentials for B's id naming `wire_other_app`: the verification went to `wire_other_app` (403), and **A's row was replaced anyway: base URI `wire_other_app`, the planted secret, `verified` false, `approved` false**, 202, hook ran | 403; A's row unchanged; nothing contacted |
| WT3 | A new peer: 202, verified, hook ran | The same |
| WT4 | B re-initiates asking for `admin`: **A's row becomes `admin`** (approval reset), 202; B's row becomes `admin` | 403; both rows unchanged |
| WT5 | B, `?notify=false` (ignored then): **B deleted A's row** (a peer may delete its own row; the flag did nothing); A's creator then 404 | B's bearer 403 (the flag is the creator's); A's creator 204, the row and cascade gone, B contacted by nothing |

Expected from reading: A's row overwritten and `approved` reset (`WT1`),
B's row deleted on the refusal. Confirmed for A; B kept its row in `WT1`
and `WT4` because the request succeeded (202), so the refusal path did not
run. Not predicted: the unauthenticated request of `WT2` rewrote the base
URI and secret even though its verification failed (`verified` false is
stored, nothing refuses it).

### Existing tests changed, and why

- `tests/test_trust_verification_token_missing.py` (three tests) and
  `tests/test_actor_logging_redaction.py::test_async_trust_request_logs_no_secret`:
  the patched `Trust.get()` returns `None` before the request (a creation
  request for an existing peer is now a re-pair), then the created row.
- `tests/integration/test_trust_flow.py::test_021`: after `test_018`
  removed actor1's row only, actor2's stale row is removed by its owner
  (`?notify=false`) before actor1 initiates again; without that the
  request is a re-pair actor1 cannot prove (403, then 408 from actor1).

### Outside voice on the Phase 3 commit

codex and a fresh-context reviewer, on `a53efb8..3d0ae38`. Findings and
disposition (folded in their own commit):

- **[critical]** The initiator sent its current secret to any URL whose
  `/meta` claimed the peer's id: it re-pairs only toward the stored base
  URI. Tested with a URL other than the stored one: nothing is sent.
- A creation could overwrite a row created during its verification (both
  backends upsert): conditional creates on both backends; the stale-grant
  cleanup runs only after the write wins.
- A re-pair to a peer that lost its row left that peer an unverified row: a
  bearer for a peer with no row answers 403.
- An unverified (squatted) row blocked the real peer: owner decision, a
  verifying request replaces it, without the squatter's grants.
- `peer_approved` after a 202, a different relationship (refused before
  sending; `WT4` re-recorded), the half-finished re-pair's log: fixed.
- Recorded: `trust_initiated` runs at the initiator for a re-pair.

## Phase 4: `actingweb-peer-state`

### Outside voice on the Phase 4 commit and the Phase 3 fold

codex and a fresh-context reviewer, on `3d0ae38..7254b1b`:

- **[critical]** A squatter could re-pair its own unverified row with the
  secret it chose and have it marked verified; **[high]** a verifying
  request could replace an approved (live) unverified row, since
  verification proves only control of the requester's base URI; **[high]**
  the replacement was an unconditional write. Owner decision: only a
  pending row (neither verified nor approved) is replaceable, by a
  conditional write on both backends with its grants cleared afterwards; a
  re-pair never marks a row verified. Tested on both backends: a squatter's
  re-pair leaves its row unverified and the real peer replaces it; an
  approved unverified row is refused (no verification sent); the
  conditional write refuses a row no longer pending.
- `report` exited 1 for ever on a `remote-unknown` bucket it never removes:
  only removable rows count now.
- Checked with nothing found: the DynamoDB condition on the composite key;
  `cur.rowcount` for `ON CONFLICT DO NOTHING`; whole-name comparisons with
  `:` in peer ids; the callback-state names; a `validate_peer_id=False`
  bucket is never removed; the consumer only reads `RemotePeerStore`.

## Phase 5: documentation, records, and Emm

### Emm's adoption items (for Emm's inbound note when the PR opens)

From this plan, for `../actingweb_mcp` when it moves its pin to 3.16:

1. **The two rows on its `subscriber` type** (`application.py`, the
   `acl_rules` of `subscriber`): `("subscriptions/<id>/<subid>", "PUT",
   "a")` and `("subscriptions/<id>/<subid>", "DELETE", "a")`. Without them
   a subscriber's queue clear and the publisher's unsubscribe answer 403
   once both sides run 3.16 (`WQ3.subscriber`, `WC4.subscriber`). Added in
   the adoption worktree for the run below, not committed.
2. **Re-pairing:** `create_relationship` against a peer Emm already
   trusts is a re-pair (current secret as bearer, only toward the stored
   base URI, the relationship unchanged); a moved peer is re-pointed with
   `PUT /trust/<rel>/<peer>` (`baseuri`); a change of relationship is a
   delete and a new pairing; a dead peer is removed with
   `DELETE /trust/<rel>/<peer>?notify=false`. Where one side removed its
   row locally, the other side's owner removes its own before pairing
   again.
3. **A fixed preview domain:** a development tunnel whose address changes
   on every start is a moved peer each time.
4. **After every instance runs 3.16:** `actingweb-peer-state report`, then
   `prune --apply`, then a restart. Emm only reads `RemotePeerStore`, so the
   command removes nothing Emm writes itself.
5. Anonymous `/callbacks/<name>` requests answer 401. Emm registers
   callback hooks `ping`, `status` and `permissions`
   (`hooks/actingweb/callback_hooks.py:170-202`); nothing in its repository
   calls `/callbacks/ping` or `/callbacks/status` (a health check
   configured outside it, the plan's unverified note, would now get 401).
   `permissions` is a reserved name: a direct `/callbacks/permissions`
   request answers 403, and the hook receives only what the library's
   permission branch builds. `status` answers any authenticated caller,
   any peer included, with the actor's creator and counts: Emm's to judge.
6. **A re-pair through Emm's "connect" flow subscribes a second time.**
   `api/trust.py:286-298` calls `on_trust_approved_async` (which subscribes
   to the peer's `properties`) whenever `create_relationship` returns a
   peer-approved row. Emm checks for no existing trust first. With 3.16 a
   connect to a peer Emm already trusts is a re-pair, and a peer that had
   approved answers 201, so Emm creates a second subscription to the same
   target (before, the replaced row answered 202 and nothing subscribed).
   The library does not deduplicate (`subscribe_to_peer_async`). Remedy on
   Emm's side: skip the auto-subscribe when
   `actor.subscriptions.get_subscriptions_to_peer(peer)` already holds one
   for `properties`, or refuse a connect to a peer already trusted.

### Emm's suite on this branch

Run 2026-11-08 as `thoughts/research/2026-11-07-emm-suite-against-master.md`
describes: the library worktree re-pointed at `0ce0112`, Emm's adoption
worktree (`emm-3-16`) with the two rows of item 1 added (uncommitted, owner
decision), a fresh environment 9 (`actingweb_mcp_9`, created, migrated and
`actingweb-unique-creators enable --apply` before the server started).

| Line | This branch | `master` baseline |
| --- | --- | --- |
| `scripts/with-preview-env.sh 9 poetry run pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py` (PostgreSQL) | 2 failed, 7406 passed, 14 skipped, 179 deselected | 2 failed, 7406 passed, 14 skipped, 179 deselected |
| `scripts/test-backends.sh 9` (DynamoDB Local) | 3 failed, 54 passed | 3 failed, 54 passed |

The failures are the baseline's, by name: PostgreSQL
`test_dynamodb_iam_coverage.py::test_role_grants_every_dynamodb_action_the_backend_uses`
and `test_stripe_integration.py::...::test_create_subscription_proceeds_with_expired_apple_subscription`;
DynamoDB the two `test_dynamodb_operation_profile.py` constructions and
`test_restore_actor_dynamodb.py::...::test_full_force_import_caps_and_confirms_the_wipe`.
No failure the `master` run did not have. Emm's suite exercises no
subscription PUT or DELETE between two actors, so the run does not show
the two rows' effect; `WD6`, `WQ3` and `WC4` in both subscriber variants do.
