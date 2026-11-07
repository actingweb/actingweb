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
