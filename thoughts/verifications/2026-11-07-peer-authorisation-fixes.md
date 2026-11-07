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
