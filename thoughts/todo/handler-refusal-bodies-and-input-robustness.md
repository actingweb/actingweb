# Handler refusals: readable bodies, and input that answers 500

**Provenance:** `plans/2026-11-21-trust-request-answer-secret.md`, phase 1
(2026-11-21). That plan gave the peer-facing refusals of
`POST /<id>/trust/<rel>` a JSON `{"error": …}` body and left the rest here
(owner decision: too wide for an rc).

## What is still open

- **The other bare refusals in `actingweb/handlers/`** answer a status line
  and an empty body (about 240 `set_status(4xx, …)` calls). A JSON client
  sees no reason. The pattern to reuse is
  `TrustRelationshipHandler._refuse_request` (and
  `_refuse_unverified_approval` for the browser/JSON split). Do it per
  handler, with the wire rows that record each refusal re-recorded under a
  plan phase.
- **The trust request's remaining bare refusals**: the 403 when
  `create_verified_trust` refuses a creation (a pending or existing row the
  request cannot replace; `handlers/trust.py`, "Forbidden") and the 400 for
  a body that is not JSON. And a refused re-pair answers "Existing trust not
  verified" whatever `replace_trust_secret` gave as its reason (another
  relationship, a secret already in use): map the reasons. Each moves wire
  rows, so under a plan phase.
- **A non-string `secret` in a trust request's body** (a number, a list)
  reaches `Trust.create` and may answer 500. Not run; a unit test first,
  then a 400 at the handler. On a re-pair it is written by the swap, then
  the read-back guard (`secret_equals(str, int)` is False) answers 403 while
  the old secret no longer works.
- **An `Authorization` header with more than one space crashes basic
  auth.** `actingweb/auth.py:156` unpacks `authz.split(" ")` into two
  names; `Bearer two words` (a bearer that failed token auth, then falls to
  basic) raises `ValueError` and answers 500 on any route that admits basic
  auth after token auth. Found writing phase 1's tests. Peer-reachable, no
  state change. Fix: `split(" ", 1)` and refuse anything that is not two
  parts.
- **`enable` records reserved `#…` creators** without filtering them
  (`actingweb/maintenance/unique_creators.py`); `record` (phase 5 of the
  same plan) refuses them. Decide whether `enable` should list them instead.
