---
status: done
verified: thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-8.md
---

# Implementation Plan: callers reach only what is theirs on `/callbacks`, `/permissions` and `/subscriptions`

**Date:** 2026-11-06
**Research:** thoughts/research/2026-11-06-peer-authorisation-fixes.md
**Branch:** docs/3-16-rollup-records (written here; implement on `fix/3.16.0-peer-authorisation`, one PR, one commit per phase)

## Update Log

- **2026-11-06**: A review of the 3.16 plans found that no integration test
  proves what a subscriber holds after a publisher's write, so nothing would
  show whether this fix leaves the legitimate flows alone. Phase 0 added
  (owner): the wire harness, and recordings of the fourteen flows this plan
  must not change. The full baseline is its own plan,
  `2026-11-06-subscription-wire-baseline.md`, which lands after this one
  (owner): this PR stays small and carries no test that passes because a hole
  is open. The fix stays in 3.16, with no 3.15.x backport (owner). From the
  same review: a callback is accepted against a subscription the actor holds
  as publisher (added to Phase 1); a peer cannot create a subscription under
  another peer's id today, and the consumer does not turn on
  `auto_delete_on_revocation` (both corrected below and in the research).
- **2026-11-06**: Second review recorded in the Evaluation Notes, not
  folded; a Readiness paragraph says what the plan needs before approval.
- **2026-11-06**: `WD9` moved to the baseline plan (owner). It records a
  property the peer may not read reaching its replica through a gap resync,
  which is a passing recording of an exposure, and this PR carries none. The
  subscriber polling and clearing its own queue, which is what Phase 2's rule
  sits on, is in `WQ1` to `WQ3`. Fourteen rows.
- **2026-11-06**: The order, the dependencies between the six plans and
  the gates between them moved to one copy in `thoughts/todo/INDEX.md`
  (owner); the copy here is a pointer. Two gates touch this plan: Emm's
  suite runs on `master` and is triaged before Phase 0 starts
  (`thoughts/todo/emm-suite-against-master.md`), and Phase 3's verification
  gains the Emm run on this branch (owner). Which plan builds the wire
  harness, this one's Phase 0 or the baseline plan's spike, is open; Phase 0
  is unchanged until it is decided.
- **2026-11-07**: The wire harness is the baseline plan's spike to build
  (owner); Phase 0 lands it and records the fourteen rows on it. Phase 0
  carries a "Superseded in part" note until the redraft; a decision and the
  Readiness paragraph record the order: spike, research pass, then this
  plan's redraft.
- **2026-11-07, later**: The spike is done
  (`thoughts/research/2026-11-07-subscription-wire-spike.md`); Phase 0's
  file list is the one under "What was built" there, and its rows that
  restrict reads use an `excluded_patterns` grant (a `friend` grant only
  adds). The research pass is next.
- **2026-11-07, later**: The research pass is done
  (`thoughts/research/2026-11-07-peer-authorisation-research-pass.md`):
  the three `[research]` items answered from the code, five decisions laid
  out for the redraft (replacement guard, where the peer binding lives,
  GET-for-write on subscriptions, state written before the fix, the
  `permission` type). Nothing here changes until `/update_plan`.
- **2026-11-07, decisions (owner)**, taken on the research pass, for the
  redraft: (1) **a replacement guard**: a trust-creation request for an
  existing peer id replaces the row only when it verifies against the
  *stored* base URI, and then swaps credentials only, keeping the owner's
  `approved` and the stored relationship; (2) **the peer binding is one
  central rule in `check_authorisation`**: a matched row whose path holds
  `<id>` requires the caller's peer id to equal the path's (creator,
  trustee and admin exempt), so application `acl_rules` are covered, and
  every call site passes the real peer id; (3) **an access row authorises
  the HTTP method the request performs, not its effect** (owner, restated
  after a walk-through of the queue-clearing flows): a GET with a side
  effect (`GET …/<subid>/<seq>` consumes the diff) stays a GET under a GET
  row; a `GET ?_method=PUT|DELETE` is evaluated as PUT or DELETE (it
  already dispatches into `put()`/`delete()`, `handlers/subscription.py:302-306`);
  a PUT or DELETE is never admitted by a GET row. So `put()` and `delete()`
  authorise as `"PUT"` and `"DELETE"` (today `"GET"`, `:381`, `:440`).
  Consequence to carry: a peer type whose rows grant only GET on
  `subscriptions/<id>/<subid>` (the consumer's `subscriber`) loses the
  gap-resync clear, the low-granularity acknowledgement and the
  publisher-initiated unsubscribe, each failing quietly (a WARNING, the
  queue grows, a dangling callback subscription); the changelog's
  **Behavior change:**, the migration guide and the consumer's adoption
  list name the two rows to add (`PUT`, `DELETE` on that path), and a wire
  row in a `subscriber`-shaped pair shows it; (4) **an operator command** for
  state written before the fix (peer-permission rows with no trust row,
  callback state for missing subscriptions, an optional replica rebuild),
  dry run by default; (5) **only `diff` and `resync` are accepted on the
  subscription callback path**; any other type answers 400.
- **2026-11-07, redraft (`/update_plan`)**: Rewritten from the spike
  (`research/2026-11-07-subscription-wire-spike.md`, harness on
  `spike/subscription-wire-harness` at `e350847`), the research pass and the
  owner's decisions above, plus five more taken in this redraft (owner):
  the central rule is **keyed on the call site** (a handler that names a
  path peer passes it; the matched row does not matter); a replacement
  whose verification fails answers **403 with the row unchanged**; a bearer
  that matches no trust stays **403** (`auth.py` unchanged); a callback's
  fetch URL is **built from the stored base URI**, never taken from the
  body; generic `/callbacks/<name>` admits **any authenticated caller**, and
  the names the library dispatches itself are **reserved**. Phase 0 is the
  spike's harness with a `subscriber`-shaped pair in two variants; Phases 1
  and 2 sit on the central rule; two phases are new (trust replacement, the
  operator command); the old Phase 3 is Phase 5. The five-dimension review
  of the redraft is in the Evaluation Notes under "Third review".
- **2026-11-07, review of the redraft folded**: five evaluators and the
  outside voice (Codex and a fresh-context reviewer); findings and their
  disposition under "Third review". Seven decisions taken on it (owner):
  no `admin` exemption on `/callbacks`; the initiator keeps a trust row it
  already had during a re-pair; a moved peer re-pairs after the owner
  updates the base URI, and a creator-only local delete is added for a dead
  peer; a credential swap fires no `trust_request_received`; refused
  callback names answer 403, as the specification says; a future permission
  timestamp is clamped to the receiver's clock; the operator command drops
  the replica rebuild. The rest folded as mechanical.
- **2026-11-07, approved and started (owner)**: `/implement_plan` on
  `fix/3.16.0-peer-authorisation`, branched from `docs/3-16-rollup-records`
  so the records land in this PR (they stay local until it opens: the repo
  is public and they describe the holes). The two deduced decisions are
  confirmed: the operator command reads per actor with `--rps`; a PUT or
  DELETE refused where a GET row would have admitted it is logged once per
  process per relationship and path at WARNING.
- **2026-11-08, Phase 3's re-pair (owner)**: the plan's receiver rule
  (verify with the request's new secret) and its initiator rule (write
  nothing before the answer) cannot both hold: the initiator would answer
  the verification with its old secret and every re-pair would fail. A
  fallback to the stored secret plus the initiator's verification token was
  considered and dropped: anyone holding that token (leaked to other peers
  before this fix) could take over the trust. Decided: a trust request for
  a peer that already has a row must carry the current trust secret as its
  bearer, or it answers 403 and nothing changes; the receiver then swaps in
  the new secret and nothing else; the initiator writes nothing until the
  answer. No verification round trip for a swap. A moved peer is re-pointed
  by the owner, as decided; a peer that lost its secret deletes and pairs
  again.
- **2026-11-08, Phase 4 review (owner)**: the replacement rule above was
  too broad: a verification proves only that the requester controls the
  base URI it sent, and a squatter could re-pair its own row with the
  secret it chose and have it marked verified. Narrowed: a verifying
  request replaces only a *pending* row (neither verified nor approved), in
  one conditional write on both backends (`only_if_pending`), its grants
  cleared after the write wins; an approved row is the owner's and changes
  only through a re-pair with its secret; a re-pair never marks a row
  verified.
- **2026-11-08, Phase 3 review (owner)**: an unverified trust row (never
  proven: an unauthenticated request that failed verification leaves one)
  is replaced by a later request that verifies; a verified row is still
  only re-paired with its secret. Folded with it, as mechanical: the
  initiator re-pairs only toward the stored base URI and the stored
  relationship (it sent the current secret to any URL whose `/meta`
  claimed the peer's id); a creation writes conditionally on both backends
  (`only_if_absent`), so a request racing another never replaces its row;
  a bearer for a peer with no row answers 403 instead of creating one;
  `peer_approved` follows the answer (201 or 202); the log for a
  half-finished re-pair names the remedy.
- **2026-11-07, Phase 1 review (owner)**: the outside voice on the Phase 1
  commit found that clamping a future permission timestamp loses the
  sender's order; the clamp is replaced by a 5-minute skew window and 400
  ("Decisions Made"). Folded with it, as mechanical: a stale permission
  update deletes and syncs nothing (only the hook waited for the store); a
  PUT to a callback is authorised as PUT; an overflowing timestamp answers
  400. Its own commit, before Phase 2.

## Overview

An unauthenticated caller can post a permission callback for any peer id and
have it stored, and with a subscription id can inject diffs and have a trust's
secret sent to a URL it chooses. A peer can read another peer's permissions,
and a `friend` peer (or a consumer's custom type with a GET row) can read,
clear and delete another peer's subscriptions. The trust row every one of
these checks relies on can be replaced by a trust-creation request for an
existing peer id. All of it exists in the released library. This plan binds
every peer caller to the peer the path names in one place, authorises the
method a request performs, guards the trust row against replacement, and
gives operators a command to remove state written before the fix. Before it
changes a handler it records, as Phase 0, the legitimate flows that run over
the same paths, so the fix is shown to leave them byte-identical. It lands
first of the six 3.16 plans of this date.

## Implementation Order

The order of the six 3.16 plans, what depends on what between them and the
gates between them are kept in one place: `thoughts/todo/INDEX.md`, "Planned
for 3.16: order, dependencies and gates". One PR per plan, one commit per
phase, phases in the order written. What this plan uses from the others is
below.

**Readiness, 2026-11-07.** Redrafted after the spike and the research pass,
with every decision the second review left open taken by the owner. The
five-dimension review of the redraft and the outside voice are recorded
under "Third review"; the seven decisions it raised are taken and the rest
folded. No open question remains. Approval is the owner's.

**This plan: first.** It needs nothing merged; Emm's suite on `master` has
run (gate 1, `research/2026-11-07-emm-suite-against-master.md`). Phase 0
lands the spike's harness. What follows it: the baseline plan records every
other flow on that harness; the `subs_list` plan's
`get_subscriptions_by_peer()` is delegated on the authenticated view and
inherits the filter added here; the `ListAttribute` plan's receiver changes
assume an authenticated peer on the subscription callback path; the
specification plan adds an opt-in for anonymous third-party webhooks on top
of the 401 added here, writes the rules into the specification, and drops
its T6 (a 409 on a repeated trust request), which the guard here replaces.

## Decisions Made

- **Security first**, ahead of the other plans (owner, 2026-11-06).
- **The fix ships with 3.16; there is no 3.15.x backport** (owner,
  2026-11-06). Released versions stay open until the 3.16 tag: the consumer
  pins `=3.15.1`, and the publish workflow accepts tags on `master` only
  (`.github/workflows/publish-to-pypi.yml:36-41`). Merging this PR publishes
  the description and the fix ahead of the release; accepted.
- **The baseline is its own plan, after this one** (owner, 2026-11-06). This
  PR records only the flows it must leave unchanged, and its access tests are
  written with the fix, in their secured form. No test in it passes because a
  hole is open.
- **Recordings, not hand-written expectations** (owner, 2026-11-06), on the
  harness the spike built (owner, 2026-11-07), with the baseline plan's
  format decisions: full transcripts from the first scenario step, timestamp
  tokens carrying the format class only, one file per row for both
  backends.
- [Updated 2026-11-08, iteration 1] **No peer reads another peer's secret**
  (owner): the per-peer trust GET returns `secret` and `verification_token`
  only to the creator, the trustee and the row's own peer; no peer changes
  another peer's base URI. This narrows the `admin` exemption below.
- [Updated 2026-11-08, iteration 2] **A verification binds the claimed id**
  (owner): a creation is verified only when the requester's base URI serves
  the claimed peer id (`/meta`).
- [Updated 2026-11-08, iteration 11] **Auto-accept approves only a verified
  request; the id stays self-asserted** (owner, option (a) of the
  re-verification's Issue 1): the `/meta` check is answered by the requester,
  so it catches a wrong base URI, not a false id. An unverified creation is
  never approved automatically and stays pending, so the real peer's
  verified request replaces it. A host running its own server can still
  verify under another actor's id and, with auto-accept, be approved; that
  row blocks the real peer until the owner deletes it. Documented as a
  limitation (changelog, security reference, migration guide, spec note).
- [Updated 2026-11-08, iteration 12] **An `admin` peer keeps DELETE on any
  peer's trust row** (owner, re-verification Issue 2 accepted): with it, it
  can re-create the row under that peer's id. Documented: grant `admin`
  only to a peer trusted as much as the owner.
- [New 2026-11-08, iteration 18] **The permission sender resends a 503**
  (owner, re-verification 2's Issue 1): up to twice, with the same body (its
  timestamp orders it), waiting `Retry-After` up to 2 s (1 s on the
  synchronous sender, which cannot read the header). The synchronous path
  blocks the owner's permission change by at most that.
- [New 2026-11-08, iteration 22] **The `/meta` check is two short tries**
  (owner, re-verification 2's Issue 8): `(3, 5)` s each, instead of
  `get_peer_info`'s three tries of `(5, 10)`, since an unauthenticated
  request chooses the host.
- [New 2026-11-08, iteration 25] **One whole-branch review before the PR**
  (owner, after re-verification 3): the last review of
  `master...HEAD` as a whole ran at `63bed00`; three iterations since (about
  680 lines in auth and the permission copy) were reviewed per delta, and
  two of the last rounds found defects in older code next to the newest
  fix. Once re-verification 3's issues are fixed, `/security-review`,
  `/code-review` (high) and codex run once on the whole branch with no
  earlier findings in the brief; their findings and this batch make the
  next verification. A repository-wide `/cso` audit was judged more than
  the question needs.
- [New 2026-11-08, iteration 32] **The `owner` rows bind to the path's
  peer** (owner, reverify-4 Issue 2): `AuthResult.authorize` passes the
  path's peer as `peerid`, so the built-in `owner` rows admit a peer to its
  own subscription and trust row. A GET-only subscriber type needs no
  adoption rows (they stay harmless); a peer also reads its own trust's
  permissions and may PUT its own trust row (approval and permissions stay
  the owner's). Supersedes the "add PUT and DELETE rows" migration step.
  [Updated 2026-11-09, iteration 39] The `owner` row on subscriptions is
  `("owner", "subscriptions/<id>/<subid>", "GET,PUT,DELETE", "a")`: it admits
  a peer to read, clear and end its own subscription, never to create one
  (owner, reverify-5 Issue 2); and both pull paths filter a `properties`
  diff by the peer's permissions, as the callback does (owner, both).
- [New 2026-11-09, iteration 38] **Creating a trust replaces an unverified
  pending request** (owner, reverify-5 Issue 1): a pending row nobody proved
  (neither verified nor approved) is replaced by the owner's own request,
  with the owner's secret, in one conditional write (`only_if_pending`); a
  verified pending row is approved in place, and `TrustManager` runs
  `trust_fully_approved_local`.
- [New 2026-11-09, iteration 40] **A peer's own base-URI move must name it
  on `/meta`** (owner, reverify-5 Issue 3): 400 otherwise, the row
  unchanged; the same check a creation's base URI gets.
- [New 2026-11-09, after the audit] **This PR closes identity and approval;
  grant enforcement is a second local security plan** (owner, after
  `verifications/2026-11-09-peer-authorisation-fixes-audit.md`): this PR
  closes audit A1 (one approval gate under the permission evaluator), A2
  (re-pair only on a verified or approved row, the swap conditional on the
  old secret), A3 with reverify-6 Issues 1 and 2 (one conditional
  approve-where-verified; re-verify a pending row before approving it), A9
  (the revocation probe), and reverify-6 Issues 3 to 11. A4 to A8, A10, A11
  and the Lows go to a second security plan, fixed before anything is
  pushed. Every fix is checked against `docs/protocol/actingweb-spec.rst`
  (owner). What the spec already fixes for these:
  - Approval: "B MUST NOT approve a relationship automatically unless it
    verified" (spec ~1603); manual approval "through a trustee or a human"
    (~1853) does not require verification, and verification is optional for
    the requester (~1739). Refusing an owner's approval of an unverified row
    is therefore a stricter local rule the spec allows; the owner's own
    create toward the peer's URL stays the way to pair with a peer that does
    not support verification. The spec gets a sentence that an actor MAY
    refuse to approve an unverified relationship.
  - Unapproved access: an associate relationship "MAY be allowed ...
    unapproved" (~1949). A1's gate refuses an unapproved row everywhere
    except its own trust row (status GET ~1671 and delete), as the access
    table already does; allowing unapproved associates stays a deliberate
    option, not a default.
  - Re-pair: B "MUST accept it only as a re-pair from the requesting actor
    itself, authenticated with the current shared secret" and "Otherwise
    ... 403" (~1595-1600); a pending row may be "replaced by a request that
    verifies" (~1602). Refusing a re-pair on a pending row is within this;
    the conditional swap is internal.
  - A peer "MUST NOT change the approval of its relationship or the
    permissions granted to it" (~1782); MCP access "identically to REST
    access control" (~1370), so the A1 gate covers MCP.
- [New 2026-11-08, iteration 33] **`FanOutManager` sends a large payload in
  full** (owner, reverify-4 Issue 4), with a WARNING above
  `max_payload_for_high_granularity`; the downgrade to an unfetchable URL is
  gone. The parameter and `DeliveryResult.granularity_downgraded` (now
  always False) stay for compatibility.
- [Updated 2026-11-07] **One central peer binding, keyed on the call site**
  (owner). `check_authorisation` gains a keyword `path_peer`: when it is
  set and the caller is authenticated as a peer, the caller's peer id must
  equal it, or the check fails, whichever row matched. Creator and trustee
  are not peer callers and are unaffected; an `admin` peer is exempt
  everywhere except `/callbacks` (owner, review of the redraft), where the
  two peer branches (`callbacks/subscriptions/<peer>/…`,
  `callbacks/permissions/<peer>`) also require a peer caller: creator,
  trustee, OAuth2, MCP and SPA callers, and an admin peer naming another
  peer, are refused there with 403. An empty path peer answers 400. Every
  handler that names a peer in its path passes it, through
  `check_authorisation` or through `AuthResult.authorize(..., path_peer=)`.
  It is separate from the existing `peerid` argument, so `owner` rows match
  exactly where they match today and which relationship types may subscribe
  stays where it is. This replaces the per-handler rule of the first draft.
- [New 2026-11-07] **An access row authorises the HTTP method the request
  performs, not its effect** (owner). A GET with a side effect stays a GET;
  a `GET ?_method=PUT|DELETE` is a PUT or DELETE; a PUT or DELETE is never
  admitted by a GET row. The subscription handler's `put()` and `delete()`
  authorise as themselves.
- [New 2026-11-07] **A trust-creation request for an existing peer id
  verifies against the stored base URI and swaps credentials only** (owner).
  The swap sets `secret`, a fresh `verification_token`, `verified=True`
  and `peer_approved=True`; it keeps `approved`, the relationship, base URI,
  description, `created_at` and the grants. The new secret passes the same
  uniqueness check creation has (`trust.py:420-427`). A failed verification
  answers 403 and changes nothing. A swap answers 201 or 202 from the
  stored `approved` and fires no `trust_request_received` (owner, review of
  the redraft); it is logged at INFO.
- [New 2026-11-07] **The initiator keeps a row it already had** (owner):
  `create_reciprocal_trust` against a peer it already trusts writes nothing
  before the request, stores the new secret only after a 201 or 202, and
  never deletes a row that existed before the call. A refused re-pair
  changes nothing on either side.
- [New 2026-11-07] **Re-pairing after a refusal** (owner): a peer that moved
  is re-paired by the owner updating the stored base URI (`PUT
  /trust/<rel>/<peer>` with `baseuri`, creator or trustee, as today); a
  change of relationship is a delete and a new pairing; a dead peer is
  removed with a new, creator-only local delete
  (`DELETE /trust/<rel>/<peer>?notify=false`), which never contacts the
  peer and always removes the local row.
- **Every unauthenticated callback request answers 401**, and **generic
  `/callbacks/<name>` admits any authenticated caller** (owner, 2026-11-07):
  the empty-role row becomes an `any` row.
- [New 2026-11-07] **The library's own hook names are reserved on the
  generic callback branch** (owner): `permissions`, `subscription`,
  `subscriptions`, `www` and any `resource_*` name answer 403 there (the
  specification's status for a callback URI that does not exist,
  `docs/protocol/actingweb-spec.rst:1158-1159`; owner, review of the
  redraft), on GET, POST, PUT and DELETE, so those hooks only receive data
  the library built.
- [Updated 2026-11-07] **A callback's fetch URL is built from the stored
  base URI** (owner): `<baseuri>/subscriptions/<own id>/<subid>/<sequence>`,
  as the resync and the acknowledgement already do. The body's `url` is
  never fetched; a body with `url` and no `data` still selects the fetch
  branch, as the specification's callback shape has it
  (`actingweb-spec.rst:2858-2861`). A `FanOutManager` downgrade, which sends
  a resource URL with no stored diff (`fanout.py:486-490`, `:620-623`), is
  not fetchable under this rule; the library never calls it, and the
  changelog says it is unsupported for a subscriber on 3.16.
- [New 2026-11-07] **Only `diff` and `resync` are accepted on the
  subscription callback path** (owner); an absent `type` is a diff; any
  other answers 400.
- **A bearer that matches no trust keeps answering 403** (owner,
  2026-11-07): `auth.py:138-144` is not changed; the rows record 403.
- **The permission query is for the peer itself, the creator and admin.**
- **A subscription callback is accepted only for a subscription this actor
  made** (a row with `callback` true), enforced in
  `SubscriptionManager.get_callback_subscription`, not on the callback
  DELETE, where the row is the publisher's and the subscriber is the
  rightful sender (second review). Refused with 403. Its other callers
  (`subscription_manager.py:898`, `:1570`, `:1789`, `:2675`) are all on the
  subscriber side and only ever want such rows.
- [Updated 2026-11-07, on the Phase 1 review] **A permission callback's
  timestamp is kept within a skew window** (owner): the receiver stores the
  sender's timestamp as sent, so updates keep the sender's order even when
  they arrive out of order, and refuses with 400 and a WARNING a timestamp
  more than 5 minutes ahead of its own clock, so nothing far in the future
  is stored. A timestamp that does not parse as ISO-8601 (or overflows in
  UTC) answers 400. This replaces the clamp decided on the redraft's
  review: clamping lost the sender's order, so a fast sender's grant
  arriving after its revoke was applied and the revoke lost.
- [New 2026-11-07] **An operator command removes state written before the
  fix** (owner), dry run by default; it reports and prunes, and does not
  rebuild replicas (owner, review of the redraft: the `ListAttribute` plan
  rewrites the replica code and brings its own `reset`).
- [Updated 2026-11-07] **The wire apps are shaped like the consumer's off
  Lambda**: processing with automatic storage, peer capabilities,
  permissions and profiles, and **synchronous callbacks off**. With them on,
  the consumer's import flow deadlocks (the loop blocks in the resync
  callback while the subscriber fetches the publisher's baseline), and a
  REST write's callbacks block whatever the flag says (the handler runs in
  the executor). Two topologies.

Confirmed by the owner at approval (2026-11-07):

- **The operator command reads per actor** (one Query per bucket prefix on
  DynamoDB, one indexed `SELECT` on PostgreSQL) with `--rps` throttling from
  `verify_orphans.RateLimiter`, rather than whole-table scans joined in
  memory: its decisions are per actor and its deletes are per row.
- **The refusal of a PUT or DELETE admitted only by a GET row is logged
  once per process per relationship and path at WARNING**, naming the two
  rows to add. The publisher is the deployment that must add them, and its
  access check logs only at DEBUG today (`auth.py:774-785`).

- [Updated 2026-11-09] **Reverify-7 is fixed in this PR, all of it** (owner,
  "include all"). Accepted with documentation, not code (iteration 67):
  - the revocation probe reads a gateway's 401/403/404 as a revocation;
  - a failed permission callback answers 503 even when the failure repeats;
  - the reconcile restores nothing from a copy without `fetched_at`.
- [Updated 2026-11-09] **A diff for a target other than `properties` is the
  application's** (reverify-7 note). It passes the library's filter
  unfiltered on push and pull, as on `master`: the library knows no
  permission model for application targets. `FanOutManager`'s unfiltered
  payload is the deferred A11.

## What We're NOT Doing

- **The full baseline** - `2026-11-06-subscription-wire-baseline.md`, next.
  Phase 0 records the flows over the handlers this plan changes.
- **Recording an exposure another plan closes** - `WD9` (an unfiltered
  stored diff reaching a replica through a gap resync) is the baseline
  plan's; the `ListAttribute` plan closes it.
- **Recording the holes as passing tests** - decided above. That each hole is
  open today is shown once, by the scenarios run on the tree before each
  phase's change, and written into the verification.
- **An opt-in for anonymous third-party webhooks** - a feature with a design
  in the specification plan. The demo's documented webhooks do not run
  anonymously today either.
- **Default deny and reserved relationship names** - specification plan; each
  has a design there.
- **401 for a bearer that matches no trust** - decided above; a
  library-wide change with no bearing on what a caller can reach.
- **Letting every relationship type subscribe** - the binding is a separate
  argument for that reason.
- **Reaping stale state on read** - the operator command does it once; a
  read-time trust lookup on the permission path would cost every request.
- **Rate limiting on `/callbacks`** - none exists anywhere in the library; a
  deployment's edge has it.
- **Rotating secrets that may have reached a third party** - cannot be known
  from the library; the changelog says which deployments are exposed and
  that deleting and re-establishing the trust rotates the secret.
- **Changing what a pending peer may set on its own row** (only
  `peer_approved`, and deleting its row): read in the research pass, both
  are the protocol's approval and termination steps.

## What Already Exists

- `spike/subscription-wire-harness` at `e350847` - the harness Phase 0
  lands: `tests/integration/_wire.py` (recorder, driver, snapshot,
  normaliser, comparer), `create_test_app`'s keyword options and recording
  hooks, the `wire_app`/`wire_peer_app` fixtures and `wire_pair` (with
  `relationship=`), the consumer's `subscriber` trust type copied verbatim,
  the `wire` marker and group. Its row files are spike rows, not this plan's.
- `actingweb/auth.py:740-813` - `check_authorisation`; the approval gate
  (`:751-760`), the `owner` match (`:800-804`), the `any` role requiring an
  authenticated caller (`:787-788`). `auth.py:270-290` sets `acl["peerid"]`
  from a peer's bearer.
- `actingweb/handlers/base_handler.py:373-395` - `AuthResult.authorize`,
  which passes no peer today; `:164-260` - `_authenticate_dual_context`, 401
  with a challenge when `add_response=True`.
- `actingweb/handlers/subscription.py:235-244` and
  `actingweb/handlers/trust.py:1275-1282` - the two bindings that exist; the
  central rule subsumes them, they stay.
- `actingweb/trust.py:316-389` - `Trust.modify` already takes `secret`,
  `verification_token`, `verified`, `peer_approved` on both backends
  (`db/postgresql/trust.py:398-406`, `db/dynamodb/trust.py:220-228`).
- `actingweb/handlers/callbacks.py:558-575`, `:824-833` - the resync and the
  acknowledgement build their URL under the stored base URI.
- `actingweb/maintenance/verify_orphans.py`, `deletions.py` and the
  `[tool.poetry.scripts]` entries (`pyproject.toml:36-43`) - the shape of a
  scanning, dry-run-first operator command.
- `tests/_adoption_helpers.py`, `tests/test_db_fault_callers.py:314-330` -
  driving a handler with an `AWWebObj` (the latter mocks authentication; the
  unit tests here use real credentials).
- `thoughts/research/2026-11-07-peer-authorisation-research-pass.md` - the
  access table, application rows included; the replacement field table;
  which state each backend keeps.

## Phase 0: the wire harness, and the flows this fix must not change

Test-only. No file under `actingweb/` changes. Row identifiers are shared
with the baseline plan, which adds the rest.

### Changes

- From `spike/subscription-wire-harness`, minus its spike rows:
  `tests/integration/_wire.py`; `tests/integration/test_harness.py`
  (keyword options `sync_callbacks`, `peer_capabilities`,
  `peer_permissions`, `peer_profile`, `record`; the recording hooks; the
  `wire_import` method; the `subscriber` trust type); `conftest.py`
  (`wire_app` 5561, `wire_peer_app` 5562, `wire_pair` with topology, grant,
  subtarget, granularity, `relationship` and capability warming, teardown
  through the library that resumes suspension rows first);
  `pytest.ini`/`pyproject.toml` (the `wire` marker); `XDIST_GROUPS.md`.
- `wire_pair` gains `extra_acl_rules`, so a pair can use the `subscriber`
  type with the two rows the consumer adds in its adoption
  (`("subscriptions/<id>/<subid>", "PUT", "a")`,
  `("subscriptions/<id>/<subid>", "DELETE", "a")`); registered as a second
  type, `subscriber_adopted`, on every wire app's configuration (rows are
  per configuration, `permission_integration.py:409-416`; the type itself is
  shared through the system actor, `trust_type_registry.py:181-183`), so
  both variants run in one session.
- A third recorded app, `wire_other_app` (5563), for rows that record that
  a host named in a request receives nothing (Phases 1 and 3).
- The driver registers a secret, token or id first seen mid-row under a
  numbered name (`trust:A-B#2`), so the normaliser's guard still fails on
  anything unnamed.
- `tests/integration/test_wire_peer_paths.py` (new) - the rows below.
- `tests/integration/wire/` - one file per row, and `rows.toml`: what each
  records and which phase or plan is expected to change it.
- `.github/workflows/tests.yml` - a step of the `tests` job after the main
  step, with the same `if: needs.changes.outputs.code == 'true'` gate and
  its own `timeout-minutes`: `pytest tests/ -m wire -p no:rerunfailures`
  (from `tests/`, so the root conftest and its hang watchdog load), its own
  junit file (`test-results/wire-${backend}.xml`, read by the summary step)
  and `--cov=actingweb --cov-append` into the main step's coverage file. The
  main step's marker becomes `-m "not benchmark and not wire"` (pytest keeps
  only the last `-m`). The marker is registered in `pyproject.toml` and
  `tests/integration/pytest.ini` (`--strict-markers`). Locally, `make
  test-all-parallel` passes no `-m` and so runs the wire rows in parallel;
  the five-run check below is the sequential one.
- `tests/integration/verify_groups.py` - every scenario has a recording and
  every recording a scenario.

The rows. Granularity `high`, a grant of `*`, a target-level subscription and
both topologies unless stated; "SDK" is a step in the test process:

| Row | Steps | Runs over |
| --- | --- | --- |
| WS1.target | `PUT /properties/<p>` with an object, a string and a number | The subscription callback |
| WL11.target | SDK: `append`, `insert` at the front and in the middle, an update by index, `update_where`, a delete by index, `pop()`, `pop(0)`, `remove_where`, `extend`, `clear`, `delete`, `set_description` | List diffs |
| WD6 | Granularity `low`: a write | The callback; B's fetch of `…/<subid>/<seq>` with its bearer; B's `PUT {"sequence": n}` |
| WD8 | The recorded callback of an SDK `append`, posted again with the bearer | A duplicate |
| WD10 | SDK `suspend("properties")`; two writes and a delete; `resume` | The resync and B's baseline fetch |
| WD10.import | The consumer's import: `POST /methods/wire_import` (suspend one subtarget, clear and refill a list, resume), two hosts | The resync on the loop, after the method answers |
| WD12 | As WD10, with A's trust row for B lacking `subscriptionresync` and freshly stamped, B already holding a list | The full-state fallback, fetched by B |
| WQ1 | `GET /subscriptions/<B>/<subid>` as B after two writes | The queue |
| WQ2 | `GET …/<subid>/<seq>` as B, twice | One diff, consumed |
| WQ3 | `PUT …/<subid>` as B with `{"sequence": 1}`, `{"sequence": 0}`, no sequence, text, on an unknown id, and `GET …?_method=PUT&sequence=1` | Clearing |
| WC1 | `POST /<B>/subscriptions` as B's creator | B subscribing at A |
| WC2 | `POST /<A>/subscriptions/<B>` with B's bearer | The same, direct |
| WC3 | `DELETE /<B>/subscriptions/<A>/<subid>` as B's creator | B's delete reaching A on the callback path |
| WC4 | `DELETE /<A>/subscriptions/<B>/<subid>` as A's creator | A's delete reaching B on B's subscription path |
| WP1 | `PUT /<A>/trust/<rel>/<B>/permissions` with an exclusion | The permission callback and B's follow-up fetch |
| WD6, WQ3, WC4 `.subscriber` | The same, in a pair of the consumer's `subscriber` type, rows verbatim (GET-only on `subscriptions/<id>/<subid>`), same host | Re-recorded in Phase 2: the record of the method rule's effect on a GET-only type |
| WD6, WQ3, WC4 `.subscriber_adopted` | The same, with the two adoption rows | Identical through every phase: the proof the migration step is enough |

A row that restricts reads grants with `excluded_patterns`: a `friend` grant
only adds patterns (spike note, "Findings beyond the questions"). `WQ2`
records a GET that consumes a diff, which the specification forbids
(`actingweb-spec.rst:1207`, `:2885-2887`); its `rows.toml` entry names
`spec-1-5` as the plan expected to change it. `rows.toml` has a column
naming the plan or phase that owns each row, which the later plans read
instead of restating the list.

### New Tests, both unit and integration tests

- The rows above, integration, both backends, both topologies where stated.
- The recorder: a callback posted to a wire app is recorded once, nested in
  the request that caused it, with the status the caller received and
  without the secret; a handler exception is recorded as a 500.
- The normaliser: a recording made twice with different actors is
  byte-identical; a planted secret, actor id or port fails the comparison.
- The driver refuses `WIRE_RECORD` when `CI` is set.

### Failure Scenarios

- A recording differs between backends or topologies - one file per row is
  the rule (the spike: nine runs, two backends, identical); a difference is
  a second file with a reason in `rows.toml` when understood, otherwise the
  phase stops and reports.
- A cold capability cache makes a resume emit a refresh that races the
  resync (spike, answer 4) - `wire_pair` warms it; a row that wants it cold
  says so and records the refresh as unordered.
- The pair's teardown leaves rows - suspension rows are resumed first, the
  actors deleted through the library, and the fixture fails on a leftover;
  the tombstone (30 days, the worker's prefix) is expected.
- The `subscriber` variants drift from the consumer's real rows - the type is
  copied verbatim with the file and line it came from; Phase 5's Emm run on
  this branch is the check that the copy still matches.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time, both backends
- [x] `poetry run pytest tests/integration -m wire -p no:rerunfailures` passes
      five times in a row on each backend, sequentially, and once under
      `make test-all-parallel`
- [x] `git show --stat HEAD -- actingweb examples` is empty
- [x] Each recording is read against the research notes' "as read" sections
      and every difference is in "Recorded outcomes"

### Recorded outcomes

First recorded 2026-11-07, both backends, both topologies; each file is read
against the "as read" sections of the research notes and the spike note.
Identical across five sequential runs per backend and under
`make test-all-parallel` on both.

- As read: `WS1.target`, `WL11.target` (one top-level callback per SDK list
  operation, `metadata` for `set_description`, `delete_all` for `delete`),
  `WD8` (the duplicate answers 204 with no hook), `WD10` and `WD10.import`
  (the spike's shape), `WQ1`, `WQ2` (200 then 404: the GET consumes),
  `WQ3` (`{"sequence": 0}` 204; no sequence and text 400; an unknown id 404;
  `GET ?_method=PUT&sequence=2` 204 and clears the rest), `WC1` to `WC4`.
- `WD6`: the acknowledgement PUT clears nothing, the diff is already
  consumed by B's GET, as the outside voice predicted.
- `WD6`, `WQ3`, `WC4` `.subscriber`: every PUT and the publisher's DELETE
  are admitted by the GET-only row today (204), byte-for-byte the same
  shape as `.subscriber_adopted`. Phase 2 re-records the three
  `.subscriber` rows.
- `WP1`: no fetch follows an exclusion; B's replica keeps the excluded
  property. The wire apps leave `auto_delete_on_revocation` off, as the
  consumer does; the plan's "B's follow-up fetch" happens only after a
  grant (the setup's grant shows it in the logs, not in the row).
- `WD12`, known wrong and recorded as is: the fallback a publisher sends a
  subscriber it thinks lacks resync is applied as an ordinary diff; B's
  list gets its items again (an `extend`), the object `y` is stored as a
  JSON string wrapped in `{"value": ...}`. Filed as
  `thoughts/todo/full-state-fallback-replica.md` (with an INDEX row); not in
  scope here.

### Notes

- **Deviation, `rows.toml` schema:** a row run in both topologies has one
  file per topology (`<row>.<topology>.json`, a `topologies` key) because
  the transcripts name different hosts; the baseline plan's `second` key
  stays for a declared backend difference. `verify_groups.py` checks the
  registry (every recording has a row and every row its recordings and
  scenario, owners as `plan:phase`, exposure listed, no `.actual.json`
  left over). The commit-trailer check (`Wire-Phase:`) is the baseline
  plan's Phase 1; this plan's commits carry the trailer already.
- **Deviation, `extra_acl_rules`:** the adoption rows are a second trust
  type, `subscriber_adopted`, registered on every wire app beside
  `subscriber` (`test_harness.py`, `SUBSCRIBER_ADOPTION_ROWS`), selected
  with `wire_pair(relationship=...)`; no separate keyword was needed. A row
  whose method does not match falls through (`auth.py:807`), so the order
  of the rows does not matter.
- `wire_pair` gained `subscribe=False` (for `WC1`, `WC2`) and the scenario
  carries `relationship` and `trust_secret`; `Scenario.name()` names a
  value first seen mid-row, and a secret under a secret key that nobody
  named becomes `mid-row#N`, so a bearer carrying it resolves and an
  unknown bearer still fails the guard. The port guard covers every
  worker's ports (`localhost:5[5-9]xx`).
- The settle conditions that poll B's replica tolerate an `IndexError`: a
  list read during a resync's rewrite raises it (seen once under parallel
  load in `WD10.import`; noted in the todo above).
- The wire rows run from the repository root (`pytest tests/ -m wire`): from
  `tests/` the integration `pytest.ini` becomes the rootdir and the root
  conftest is not loaded.
- Harness self-tests: `tests/integration/test_wire_harness.py` (normaliser,
  guard, named and unnamed mid-row secrets, the comparer under `CI` and its
  row list, the recorder's 500 and nesting, a real callback recorded once
  without its secret, the registry check).
- Release impact: none; test and CI only.
- **Outside voice on the Phase 0 commit** (codex and a fresh-context
  reviewer, 2026-11-07), folded before Phase 1, every row re-recorded on the
  unfixed tree (only fields added) and identical five times per backend:
  - the snapshot gains both sides' trust rows (authorisation fields, the
    secret by name, the verification token as present or not), the
    publisher's grant row and the subscriber's stored peer permissions, so
    Phases 1 to 3 cannot change them unseen and Phase 3 needs no snapshot
    change;
  - `WIRE_RECORD` takes row ids (`WIRE_RECORD=WD6.subscriber,...`), never
    "all": a re-recording rewrites only the rows it names;
  - a step opens and closes the recorder only when no wire request is in
    flight (a counter in the middleware), and returns a deep copy;
  - a secret under a secret key that nobody named fails the guard (the
    first draft's automatic `mid-row#N` would have let a leaked credential
    pass); a scenario names one with `Scenario.name(..., secret=True)`;
  - a handler exception after its response started keeps the status the
    caller received; snapshot rows sort by what they subscribe to before
    their random id;
  - the registry check: an owner must be a `[reserved]` plan and a row id
    must fall in a reserved range;
  - CI: the wire step runs unless cancelled (also when the main step
    failed), and the PR summary counts a missing wire result as an error.
  Accepted as is: the recorder's one stack per process nests by start time,
  not by cause (a step's requests are sequential, and `-n` workers are
  separate processes); format-only timestamp tokens (owner decision); an
  HTML body recorded by length; the start probe accepting whatever answers
  on the port (one run at a time is the rule); the registry not proving a
  scenario calls `check()` for its row (a missing call shows as an orphan
  recording only when the file exists).

### Implementation Status: Complete

---

## Phase 1: one peer binding, and `/callbacks` requires the peer it names

### Changes

- `actingweb/auth.py` - `check_authorisation(..., *, path_peer: str | None
  = None, peer_caller_only: bool = False)`: after a row matches, when
  `path_peer` is set and `self.acl["peerid"]` is non-empty, return False
  unless the two are equal or (only when `peer_caller_only` is False) the
  caller's relationship is `admin`. With `peer_caller_only`, a caller whose
  `acl["peerid"]` is empty (creator, trustee, OAuth2, MCP, SPA) fails too.
  The existing `peerid` argument and the `owner` match are unchanged.
- `actingweb/handlers/base_handler.py:373-395` - `authorize(method, path,
  subpath, *, path_peer=None)` passes it through.
- `actingweb/handlers/callbacks.py`
  - `get()`, `post()` (and so `put()`, `:74-76`), `delete()`: authenticate
    with `add_response=True` and return on failure; an unauthenticated
    request answers 401 with a challenge on every branch.
  - The two peer branches (`permissions/<peer>`, `subscriptions/<peer>/<subid>`
    on POST; `subscriptions/<peer>/<subid>` on DELETE): an empty peer
    segment answers 400; a path shorter than the branch needs answers 400
    (today `:341-343` and `:88-90` raise `IndexError`); then
    `path_peer=<peer>, peer_caller_only=True`, before any lookup, so a
    caller that is not the peer cannot tell a real subscription id from an
    unknown one.
  - Permission branch: `timestamp` must parse as ISO-8601 (else 400) and
    be at most 5 minutes ahead of the receiver's clock (else 400 with a
    WARNING naming both times; the clamp of the first draft, replaced on the
    Phase 1 review); an update older than the stored one deletes, syncs and
    runs nothing; the `permissions` hook runs only when the store accepted
    the update.
  - Subscription branch, `type`: absent, `diff` or `resync`; anything else
    400, checked before both the processor and the legacy hook branch
    (`:402-415`).
  - Low-granularity fetch (`:600-628`): the URL is
    `<trust baseuri>/subscriptions/<own id>/<subid>/<sequence>` (joined so a
    stored base URI with a trailing slash gives one slash); the body's `url`
    is not fetched; it still selects the branch and is still passed to
    legacy hooks.
  - Generic branch, on GET, POST and DELETE: names `permissions`,
    `subscription`, `subscriptions`, `www` and `resource_*` answer 403; the
    rest run the hook as today for an authenticated caller.
- `actingweb/interface/subscription_manager.py:524-528`
  (`get_callback_subscription`) - returns only a row with `callback` true
  (the backends do not filter on the flag, `db/dynamodb/subscription.py:69-73`,
  `db/postgresql/subscription.py:59-66`); the handler answers 403 when none.
  Not used by the callback DELETE.
- `actingweb/config.py:286-289` - `("", "callbacks", "", "a")` becomes
  `("any", "callbacks", "", "a")`; the `owner` row above it stays.
- `actingweb/fanout.py` - a module docstring line: a low-granularity
  downgrade is not fetchable by a 3.16 subscriber.
- Docstrings in `callbacks.py` and `auth.py`.

### Wire rows

The Phase 0 recordings are byte-identical after this commit, both
topologies, both backends. The URL rule changes nothing in `WD6` and `WD12`:
the stored base URI and the publisher's own root give the same URL on the
wire apps. The rows below that record "the other host receives nothing" use
a third recorded app, `wire_other_app` (5563), added to Phase 0's fixtures.

New rows, recorded with the fix in place. C is a third actor with an
approved `friend` trust to B; S a peer of the consumer's `subscriber` type;
D a peer with an `admin` trust:

| Row | Request to B | Recorded |
| --- | --- | --- |
| WA1 | No credentials: a subscription callback for a real subscription, and for an unknown id | 401 for both; nothing applied |
| WA2 | No credentials: a permission callback for a peer with a trust, and for one without | 401; nothing stored, no hook |
| WA3 | No credentials: `GET`, `POST`, `PUT`, `DELETE` on `/callbacks/<name>` | 401 with a challenge |
| WA4 | A bearer that is nobody's, on the three paths | 403 |
| WA5 | C, S and D post a subscription callback and a permission callback under A's id | 403; nothing applied |
| WA6 | B's creator posts either | 403 |
| WA7 | A peer whose trust is not approved posts a callback | 403 |
| WA8 | A low-granularity callback with A's bearer whose body `url` names `wire_other_app` | B fetches from A's stored base URI; `wire_other_app` receives nothing |
| WA9 | `DELETE /<B>/callbacks/subscriptions/<A>/<subid>` by C and by B's creator | 403; the subscription remains |
| WA10 | To A, by B with its bearer, under the id of B's own subscription at A | 403; nothing in A's replica store for B |
| WA11 | A peer's `GET`, `POST` and `DELETE` to a generic path a hook handles, to one no hook handles, and to each reserved name | The hook's answer; today's answer for the unhandled one; 403 for each reserved name, no hook run |
| WA15 | A's bearer: a subscription callback with `type` `permission`, and with an unknown type | 400; nothing applied, sequence unchanged, no hook |
| WA17 | A's bearer: a permission callback with a timestamp a day ahead, then one with a current timestamp | The first 400 (beyond the skew window), the second applied; the stored `fetched_at` is not in the future |

### New Tests, both unit and integration tests

- Before the handler changes, on the tree as it is: the scenarios of `WA1`
  to `WA17` run once and their output goes into the verification document
  (expected from reading: 204 and applied for `WA1`, `WA2`, `WA4`, `WA5`,
  `WA6`, `WA10`, `WA15`; `wire_other_app` receives the fetch for `WA8`; the
  subscription deleted for `WA9`). No recording of it is committed.
- Unit, `check_authorisation`: with `path_peer`, a peer equal to it passes;
  a different peer fails whatever row matched, including an application row
  inserted at index 0 and a row without `<id>`; creator and trustee pass;
  an `admin` peer passes; with `peer_caller_only`, creator, trustee and an
  admin peer naming another peer fail; without either, behaviour is
  unchanged (the existing auth tests pass untouched).
- Unit, real storage, each callback branch: unauthenticated 401 and nothing
  stored, deleted or run; another peer 403; the creator 403; an admin peer
  under another id 403; an unapproved peer 403; an empty or short peer
  segment 400; the peer itself 204 for high and low granularity, a resync
  and a permission callback.
- Unit: `type` other than `diff`/`resync` 400 and neither the processor nor
  a legacy hook is called.
- Unit: the low-granularity fetch goes to the stored base URI, with and
  without a trailing slash on it, whatever the body's `url` says; the HTTP
  client is patched to fail the test on any other host.
- Unit: a subscriber posting to its publisher under its own subscription
  id, both backends: 403, nothing stored.
- Unit: permission timestamp: unparsable 400; future clamped with a
  WARNING; an older one than stored ignored as today.
- Unit: reserved names on GET, POST, DELETE 403, no hook (a `*` hook
  included); an ordinary name with a hook: the hook runs.
- Integration, both backends, both topologies: the wire rows.
- Existing tests that pin today's behaviour, each updated in this commit
  with a line in the verification saying why:
  `tests/test_callback_in_progress_answer.py:41-45`, `:76-80`, `:108-112`,
  `:151-155` (mocked `auth_obj`: give it a real response code and a trust
  with `baseuri`), `tests/test_db_fault_callers.py:325-329`,
  `tests/integration/test_subscription_flow.py:953-970` (`test_038`: a
  deleted peer's bearer now answers 403 before the lookup, not 404).

### Failure Scenarios

- A peer on an older library sends an unauthenticated callback - none does;
  the synchronous senders always send the bearer (`actor.py:2683`,
  `aw_proxy.py:123-125`), the asynchronous permission sender only when the
  row has a secret (`trust_permissions.py:381-383`), which every trust row
  does; the Phase 0 rows staying identical is the check.
- A publisher that moved sends a low-granularity callback - the fetch goes
  to the stored base URI and fails there; the callback answers 503 as any
  failed fetch does today and the subscriber retries; the owner updates the
  base URI (Phase 3's remedy). Logged with the remedy.
- An application that pointed a third party at `/callbacks/<name>` - it
  received a 2xx and nothing ran; it now receives 401. Changelog.
- An application whose own hook is named like a reserved name - reachable
  only with data the caller chose; 403 now. Changelog.
- A request carrying a stale `oauth_token` cookie on `/callbacks` - takes
  the `www` authentication path (`base_handler.py:194-212`); the unit tests
  cover it and record whether it answers 401 or redirects; a redirect is
  changed to 401 on `/callbacks`.
- A call site that names a peer but forgets `path_peer` - the unit test per
  handler and the `WA` rows catch it; Phase 2 adds the rest of the sites.
- Until Phase 3 lands, the binding is to a row a creation request can
  replace; nothing ships between the commits of one PR, and each phase's
  verification says so.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time
- [x] `grep -n '("", "callbacks"' actingweb/config.py` returns nothing
- [x] `git show --stat HEAD -- tests/integration/wire` shows `WA1` to `WA11`,
      `WA15` and `WA17` added and no other recording changed
- [x] The verification document holds the pre-fix run for each row

### Notes

- **Deviation: 401 whenever the request carries no `Authorization`
  header.** A stale web session cookie takes the `www` path
  (`base_handler.py:190-212`) and, with no OAuth provider, answers 403
  rather than redirecting; on `/callbacks` any failed authentication
  without the header now answers 401 with a challenge (redirect included).
  Credentials that match nobody keep 403 (`WA4`).
- **A callback for an unknown subscription id, by the right peer, answers
  403** (was 404), as the specification says for a callback URI that does
  not exist with authentication data (`actingweb-spec.rst:1153-1159`) and
  as the plan's "403 when none" has it. One more existing test pinned the
  404: `test_subscription_flow.py::test_016`, updated (verification).
- The callback handler: `_authenticate_callback` (one place for the 401,
  403 and 404), `_peer_segments` (the 400 for an empty or short peer
  segment), `_refuse_reserved_name`; module helpers
  `is_reserved_callback_name` and `low_granularity_fetch_url`. A fetch for
  a trust with no base URI answers 503 with nothing processed.
- `check_authorisation` keeps its matching in `_match_access_row`; the
  binding is applied after a row admits the request.
- The wire apps gained a generic callback hook (`wire_ping`) for `WA3`,
  `WA4` and `WA11`; `wire_pair` is a factory object with `add_peer()` for
  C, S, D and E. The `WA` rows are recorded in both topologies.
- Pre-fix runs and the changed tests: verification document, "Phase 1".
  Not predicted there: an unauthenticated generic callback answered 200 on
  GET, POST and PUT (nothing ran), and a bare `/callbacks/subscriptions`
  POST or DELETE raised (500).
- Until Phase 3 lands, the binding is to a row a creation request can
  replace; nothing ships between the commits of this PR.
- Release impact: `check_authorisation` and `AuthResult.authorize` gain
  keyword-only parameters with defaults (additive); the behaviour changes
  are the changelog's (Phase 5). 3.16 is a minor.
- **Outside voice on the Phase 1 commit** (codex and a fresh-context
  reviewer): no route around the binding (the `_method` overrides, the
  integrations' `name`, case, bare branch names and every token path's
  `acl["peerid"]` checked). Folded in its own commit after Phase 1: the
  timestamp window (owner decision above), a stale permission update
  deleting and syncing nothing, a PUT authorised as PUT (the hook is told
  `PUT`), an overflowing timestamp 400; `WA17` re-recorded. For the Phase 5
  changelog: a peer trustee's Basic retry after a refused bearer
  (`aw_proxy.py:132-135`) cannot succeed on the two peer branches. Noted,
  not changed: an access row with `r` does not refuse (any matching row
  admits, `auth.py`), so a row cannot narrow a broader one below it.

### Implementation Status: Complete

---

## Phase 2: `/permissions`, `/subscriptions` and `/trust/<type>/<id>` for the peer they name; the method rule

### Changes

- `actingweb/handlers/subscription.py` - every per-peer handler passes
  `path_peer=<peerid>` (GET, POST, the subscription GET, PUT, DELETE, the
  single-diff GET); `put()` authorises as `"PUT"` and `delete()` as
  `"DELETE"` (`:381`, `:440`). The `?_method=` override already dispatches
  into them (`:302-306`).
- `actingweb/handlers/permissions.py:55-91` - authorise before the trust
  lookup with `path_peer=<peer>`, so an unknown id and another peer's id
  answer the same 403. Rows: the four role rows become
  `("owner", "permissions/<id>", "GET", "a")`,
  `("creator", "permissions", "GET", "a")` and
  `("admin", "permissions/<id>", "GET", "a")`, so every relationship type
  reads its own.
- `actingweb/handlers/trust.py` - the per-relationship GET, POST, PUT and
  DELETE (`:534-540`, `:637-648`, `:716`, `:964-973`) and the permissions
  sub-handlers (`:1061`, `:1169`, `:1237`) pass `path_peer=<peerid>`. The
  DELETE keeps its row lookup before authorisation (`:944-961`, needed by
  `delete_reciprocal_trust`), so a peer can still tell an existing row from
  an unknown id there; recorded as known, not changed.
- `actingweb/handlers/subscription.py:20-49` (`GET /subscriptions?peerid=`)
  - a peer caller sees only its own rows (the query's `peerid` is replaced
  by `acl["peerid"]`); creator and trustee unchanged. The path rule cannot
  reach a peer named in the query.
- `put()` and `delete()` in `subscription.py`: when the refusal is one a GET
  row would have admitted, log once per process per relationship and path
  at WARNING, naming the two rows to add. An application
  row such as the consumer's `("trust/<type>/<id>", "GET")` then admits a
  peer to its own row only.
- `actingweb/interface/authenticated_views.py:691-705` - one private filter
  method on `AuthenticatedSubscriptionManager`, used by the three
  properties: a peer or client view lists only its own trust's
  subscriptions; owner mode unchanged. The `subs_list` plan's
  `get_subscriptions_by_peer()` passes through the same method.
- `actingweb/actor.py:2545` - the publisher's failed remote unsubscribe is
  logged at WARNING with the status (today DEBUG);
  `handlers/callbacks.py:835-838` and `interface/subscription_manager.py:1201-1204`,
  `:1226-1229` (and the async copies) include the status in their WARNING,
  and log a 403 at ERROR.
- `docs/sdk/authenticated-views.rst` - what a view lists.

### Wire rows

Byte-identical: every Phase 0 row except the three `.subscriber` rows, and
`WA1` to `WA15`. Re-recorded in this commit, with the diff read and written
into the verification: `WD6.subscriber` (B's acknowledgement 403; the diff
is already gone, consumed by B's GET, so the queue is unchanged from
today), `WQ3.subscriber` (each clear 403, the queue keeps its diffs),
`WC4.subscriber` (A's delete to B 403, B keeps its callback subscription).
The `.subscriber_adopted` rows stay identical.

New rows:

| Row | Request to A | Recorded |
| --- | --- | --- |
| WA12 | C: `GET /subscriptions/<B>`, and `GET`, `PUT`, `DELETE` and the diff `GET` on `…/<B>/<subid>` | 403 each; nothing listed, cleared, consumed or deleted |
| WA13 | C: `POST /subscriptions/<B>` | 403, as before |
| WA14 | `GET /permissions/<B>` by B for each built-in type and `subscriber`, by C, by A's creator, by an admin peer, for an unknown id | B reads its own for every type; C 403; creator and admin 200; the unknown id the same 403 |
| WA16 | S (`subscriber` type): `GET /trust/subscriber/<B>` and `GET /trust/subscriber/<B>/permissions` on A | 403 each; its own 200 |
| WA18 | C: `GET /subscriptions?peerid=<B>` on A | Only C's own rows |

### New Tests, both unit and integration tests

- Before the changes: the scenarios of `WA12`, `WA14`, `WA16` run once on
  the tree as it is, output into the verification document.
- Subscriptions, each handler: a peer on another peer's path 403 and nothing
  changed, on its own path as before; a GET-only application row admits GET
  and the diff GET and refuses PUT, DELETE and `GET ?_method=PUT|DELETE`;
  creator and trustee as before.
- Permission query: own, for each built-in type and a custom type; another
  peer's 403; the creator and an admin peer any; an unknown id 403; a
  pending peer 403.
- Trust, one test per site (`:534`, `:637`/`:648`, `:716`, `:964`, `:1061`,
  `:1169`, `:1237`): another peer 403, the peer itself as before; an
  application type's `trust/<type>/<id>` GET row admits its own row only.
- The subscription root with `?peerid=`: a peer sees only its own.
- The once-per-process WARNING on a GET-row refusal, and its absence on a
  plain refusal.
- Existing tests moved here from Phase 1:
  `tests/test_permissions_handler.py:150-167`, `:182-214` (authorisation
  now precedes the lookup and carries `path_peer`).
- View filter: two peers' subscriptions; a peer view and a client view each
  see their own; a client view with no trust sees nothing.

### Failure Scenarios

- An application whose peers clear or delete through a GET-only row (the
  consumer) - the gap-resync clear and the publisher's delete fail with 403
  (the low-granularity acknowledgement too, but its diff was already
  consumed by the GET), the queue grows and a dangling callback
  subscription stays; the publisher logs the WARNING naming the rows. **Behavior change** with the two rows to add, in the
  changelog and the migration guide; the `.subscriber` re-recordings show it
  and the `.subscriber_adopted` rows show the remedy.
- An application that used a `friend` peer to administer other peers'
  subscriptions - refused. Changelog.
- An admin peer reading every trust row's secret - unchanged (exempt by
  decision); the security reference says so.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before the phase commit
- [x] `git show --stat HEAD -- tests/integration/wire` shows `WA12` to
      `WA14`, `WA16`, `WA18` added, the three `.subscriber` files changed,
      and nothing else
- [x] The verification document holds the pre-fix runs and the read diff of
      the three `.subscriber` files

### Notes

- **A refusal with no body was read as success.** `AwProxy.change_resource`
  and its async twin returned `{}` for a non-2xx answer without a JSON
  body, and every caller tests `"error" in result`, so a 403 on the clear
  or the acknowledgement was logged as success. Both now return an `error`
  with the status for any non-2xx answer; the subscriber's WARNINGs carry
  the status (ERROR for a 403, naming the rows the publisher must admit),
  through one helper (`_log_peer_clear_failure`).
- The method rule and its WARNING live in one helper,
  `_authorize_subscription_write` (`handlers/subscription.py`); the
  once-per-process set is keyed on (relationship, path).
- The subscription root: a peer caller lists only its own rows. On
  FastAPI the root route binds `?peerid=` as the path's peer
  (`fastapi_integration.py:1253-1264`), so the query reaches the per-peer
  handler and the binding refuses it there (`WA18`); the root handler's
  filter is the unit tests'.
- Permission rows: `owner`, `creator` and `admin`, as planned. A peer of
  any built-in type and an application type with a `permissions/<id>` row
  reads its own (`WA14`).
- Not changed, recorded: no built-in row admits an `admin` peer on
  `/subscriptions` (the exemption applies only after a row admits), and a
  `friend` cannot read its own trust's `/permissions` sub-resource (the
  handler passes no peer id, so `owner` never binds), both as before.
- The trust DELETE keeps its row lookup before authorisation (known, as
  planned).
- Pre-fix runs, the three re-recordings and the changed test: verification
  document, "Phase 2".
- Release impact: no new route or option; the behaviour changes are the
  changelog's (Phase 5).
- **Outside voice on the Phase 2 commit** (codex and a fresh-context
  reviewer), folded in its own commit: the trust-site tests now insert a
  row that admits C, so only the binding refuses it (before, the default
  rows refused first and the tests passed without `path_peer`); a peer on
  its own trust row (where an application row admits it) cannot approve it
  or write or reset its own permissions (`_is_non_admin_peer`); the
  subscription root's POST lets a peer caller subscribe the actor only to
  itself; a client view lists the rows it creates (under its accessor id)
  and its trust's peer id under either key; `AwProxy` turns any non-object
  JSON body of a non-2xx answer into an error; the async proxy's 403 is
  tested. Recorded, not changed: the trust DELETE still answers 404 for an
  unknown row before authorisation, to unauthenticated callers too
  (`delete_reciprocal_trust` relies on it; planned as known); FastAPI binds
  the root's `?peerid=` to the per-peer handler (403) where Flask filters
  (200); the default `owner` rows never bind on `authorize()` calls, which
  pass no `peerid` (a design note for the specification plan).

### Implementation Status: Complete

---

## Phase 3: a trust-creation request cannot replace an existing row

### Changes

Receiver side ([Updated 2026-11-08] to the owner's re-pair decision; the
first text verified the swap with a GET using the request's new secret,
which the initiator rule below made impossible):

- `actingweb/handlers/trust.py` (`TrustRelationshipHandler.post`) - read the
  row for the peer id once. When it exists, the request is a re-pair
  (`_re_pair`): accepted only when it is authenticated as that peer with
  the trust's current secret as its bearer; then
  `Actor.replace_trust_secret` checks the relationship is the stored one
  (else refusal: delete and pair again), that a new secret is given and is
  not in use on any of the actor's rows (`is_token_in_db`, the peer's own
  included, as creation refuses), and swaps `secret`, a fresh
  `verification_token`, `verified=True` and `peer_approved=True`, nothing
  else. No verification round trip. The status follows the stored
  `approved` (201 or 202); no `trust_request_received`; INFO log. A refused
  re-pair answers 403 `Existing trust not verified`, WARNING (actor, peer
  id, reason; never the body's base URI), row unchanged.
- `actingweb/actor.py` (`create_verified_trust`) - a creation request never
  replaces a row: it refuses when one exists (an SDK caller or a race), and
  creates with `Trust.create(..., known_absent=True)` otherwise.
- `actingweb/trust.py` (`Trust.create`) - `known_absent` skips the second
  read.

Initiator side:

- `actingweb/actor.py` (`create_reciprocal_trust` and its async twin) - when
  a row for the peer already exists: write nothing before the request; send
  it with the existing row's secret as the bearer (`_re_pair_request`), the
  new secret in the body; after a 201 or 202 store the new secret (and
  `peer_approved` on 201, `_finish_re_pair`); on anything else leave the
  row as it was and return False with a WARNING naming the status, the
  reason phrase and the remedies. A row that did not exist before the call
  is created and deleted on failure, as today.

The remedies:

- `actingweb/handlers/trust.py:886-1049` (DELETE) - `?notify=false`,
  creator only (403 for anyone else): `delete_peer_trust(notify_peer=False)`,
  which never contacts the peer and removes the local row and its cascade
  (`actor.py:2084-2223`). `?peer=true` keeps its meaning.
- Updating a stored base URI is `PUT /trust/<rel>/<peer>` with `baseuri`,
  creator or trustee, as today (`:711-885`); unchanged, documented in
  Phase 5.

### Wire rows

Phases 0 to 2 recordings are byte-identical. New, two hosts (`WT2` uses
`wire_other_app` as the named base URI). The driver registers a secret, a
token or an id introduced mid-row under a numbered name (`trust:A-B#2`):

| Row | Steps | Recorded |
| --- | --- | --- |
| WT1 | B re-initiates its trust to A (`create_relationship`, as the consumer does), then A writes | B's request carries its current secret; A's row keeps `approved` and relationship; 201 from the stored row; B's row `peer_approved`; the next callback carries the new secret; the replica updates; no `trust_request_received` |
| WT2 | A creation request for B's id naming `wire_other_app` as base URI, without B's secret | 403; A's row unchanged; nothing is contacted |
| WT3 | A creation request for a new peer id | As today (201 or 202) |
| WT4 | B re-initiates asking for a different relationship type | 403; both rows unchanged; B's subscriptions intact |
| WT5 | A's creator: `DELETE /trust/<rel>/<B>?notify=false` with B unreachable; then the same as B's bearer | 204 and A's row and cascade gone, B contacted by nothing; B's bearer 403 |

### New Tests, both unit and integration tests

- Before the change: `WT1`, `WT2` and `WT4` run once on the tree as it is
  (expected from reading: A's row overwritten and `approved` reset; B's row
  deleted on the refusal), output into the verification document.
- Unit, both backends, receiver: a verifying peer swaps `secret`, the token,
  sets `verified` and `peer_approved`, and keeps `approved`, relationship,
  base URI, description, `created_at` and the grants; non-verifying peers
  (unreachable, wrong token, non-JSON) 403 and every field unchanged; a new
  secret already in use 403; the status follows the stored `approved` with
  and without auto-accept; `trust_request_received` not called on a swap
  and called on a creation.
- Unit, both backends, initiator: an existing approved row survives a 403,
  a 5xx and a connection error unchanged; a 201 swaps its secret and keeps
  it approved; a new peer's row is still deleted on failure.
- Unit: `?notify=false` by the creator removes the row with no outbound
  request (the HTTP client patched to fail); by a peer or trustee 403.
- Existing tests updated: `tests/test_trust_verification_token_missing.py:31-48`,
  `:57-73`, `:82-98` (the patched `Trust` gets `get.return_value = None`).

### Failure Scenarios

- A peer that moved re-initiates from its new address - refused; the owner
  updates the base URI and the peer pairs again. Migration guide, with the
  request.
- A peer that wants another relationship type - refused (`WT4`); delete and
  pair again.
- A peer unreachable at the moment of re-initiation - refused, both rows
  kept; the initiator retries later.
- A dead peer whose trust cannot be deleted because the remote delete fails -
  `?notify=false`.
- A development setup whose base URI changes on every start (the
  consumer's preview tunnel without a fixed domain) - every re-pair is a
  moved peer; the migration guide says to use a fixed domain or delete and
  pair again.
- Rows replaced before the fix are undetectable (they were stored with
  `verified` true against the body's base URI); the changelog says a
  deployment that suspects it deletes and re-establishes the trust.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before the phase commit
- [x] `git show --stat HEAD -- tests/integration/wire` shows `WT1` to `WT5`
      added and nothing else

### Notes

- **The re-pair rule changed at implementation** (owner, 2026-11-08,
  Update Log): the plan's receiver verified with the request's new secret
  while its initiator wrote nothing before the answer, so every re-pair
  would have failed. A fallback to the stored secret and the initiator's
  verification token was dropped (anyone holding that token, leaked before
  this fix, could take the trust over). A re-pair now proves the current
  secret; no verification GET.
- The receiver's swap is `Actor.replace_trust_secret` (returns the row or
  the reason); the handler's `_re_pair` decides from the authentication.
- The initiator's request and its completion are shared by the sync and
  async paths (`_re_pair_request`, `_finish_re_pair`).
- `?notify=false` runs `delete_reciprocal_trust(notify_peers=False)` for the
  creator; the hook `trust_deleted` runs as for any delete.
- Tests compare a row's authorisation state, not its usage stamps
  (`last_accessed` and `last_connected_*` move whenever a bearer
  authenticates).
- The wire apps record `trust_request_received`; the trust rows name both
  rows' verification tokens (a trust request and a trust row read back
  carry them).
- Pre-fix runs: verification document, "Phase 3".
- **A consequence for Phase 5's migration guide:** when one side removed
  its row locally (`?peer=true`, `?notify=false`) and the other kept its
  own, the side without a row can no longer pair again by itself (it cannot
  prove the old secret): the other side's owner removes its stale row first
  (`DELETE …?notify=false`), then they pair. `test_trust_flow.py::test_021`
  does exactly that now.
- The swapped row is read back through a fresh `Trust` (after `modify()` a
  cached DynamoDB row holds its flags as strings; `WT1` showed the
  difference between the backends).
- The wire normaliser keeps only the wire apps' trust types in a listing of
  them (`/meta`'s `aw_trust_types`): every app in a test worker shares the
  registry, and other tests add theirs.
- Release impact: no new route (a query flag on an existing one, recorded
  for the changelog's `ADDED`); a creation request for an existing peer is
  a behaviour change.
- **Outside voice on the Phase 3 commit** (codex and a fresh-context
  reviewer), folded in its own commit:
  - [critical] the initiator decided "re-pair" from the peer id the target
    URL's `/meta` claimed and sent the current secret there: it now
    re-pairs only toward the stored base URI (`_re_pair_refusal`), and
    posts there;
  - a creation request whose verification is slow could still overwrite a
    row created meanwhile (both backends upsert): a new row is written
    conditionally (`Trust.create(only_if_absent=True)`, DynamoDB
    `attribute_not_exists`, PostgreSQL `ON CONFLICT DO NOTHING`), and its
    stale grants are cleared only after the write wins;
  - a re-pair to a peer that lost its row made that peer store an
    unverified row: a bearer for a peer with no row answers 403;
  - an unverified row blocked the real peer for good (owner decision: a
    request that verifies replaces it, without the squatter's grants);
  - `peer_approved` follows 201 or 202; the initiator refuses a different
    relationship before sending (`WT4` re-recorded); the half-finished
    re-pair's log names the remedy.
  Recorded, not changed: the initiator's `trust_initiated` hook runs for a
  re-pair, as for any pairing its owner starts.

### Implementation Status: Complete

---

## Phase 4: an operator command for state written before the fix

### Changes

- `actingweb/maintenance/peer_state.py` (new) and the script entry
  `actingweb-peer-state = "actingweb.maintenance.peer_state:main"`. Same
  environment as the application. Subcommands `report` and `prune
  [--apply]`, required; optional positional `ACTOR_ID`; `--rps` (default as
  `actingweb-verify-orphans`, reusing its `RateLimiter`). Per actor, reading
  strictly (a fault exits 2, never prunes on a guess), it reports:
  - `_peer_permissions` rows whose name is not `<actor>:<peer>` for a peer
    with a trust row, compared as whole names built from the live trust
    list (peer ids may contain `:`);
  - `_peer_permissions` rows whose stored `fetched_at` is in the future or
    does not parse, for any peer;
  - `_callback_state` rows whose name is not `state:` or `pending:` plus
    `<peer>:<subid>` for a subscription with `callback` true, compared as
    whole names;
  - `remote:<peer>` buckets with no trust row for `<peer>`, or with a trust
    row but no subscription with `callback` true to that peer. The matcher
    is an explicit whitelist of bucket names built by
    `get_remote_bucket` (`remote_storage.py:30-52`); any other `remote:`
    bucket is reported as unknown and never pruned (the `ListAttribute`
    plan's `remote:<peer>$aux` side bucket extends the whitelist there).
  Exit codes: 0 nothing found, 1 found (report) or pruned (prune), 2 a store
  could not be read. Documented in the module docstring, as the existing
  commands do. It runs no application hook. After `prune --apply`, running
  application processes keep cached permissions until restarted; the
  output says so.
- `docs/guides/database-maintenance.rst` - a section for the command.
- `thoughts/todo/INDEX.md` - the dependency table gains: `attribute-list-v2-port`
  → `peer-authorisation-fixes`, hard: its side bucket must be added to the
  command's whitelist.

### Wire rows

Unchanged; the command is not on the wire.

### New Tests, both unit and integration tests

- Unit, both backends, following `tests/test_deletions_command.py`: each
  kind of stale row is reported and, with `prune --apply`, removed; a row of
  a live trust or subscription is kept, including one whose peer id
  contains `:`; a `remote:` bucket outside the whitelist is reported as
  unknown and kept; `report` changes nothing; `ACTOR_ID` limits the run;
  exit codes 0, 1 and 2 (a read fault injected).
- Integration: a pair set up, a stale permission row, a future-dated one for
  the live peer and a stale pending row planted through the library;
  `prune --apply` removes them and the pair's next callback and permission
  update are applied as before.

### Failure Scenarios

- A row created between the command's read and its delete - the command is
  documented to run after every instance is on 3.16; a row it misreads as
  stale is one that was just created for a new trust or subscription, and
  the next callback recreates it. The guide says to run it in a quiet
  period.
- A stale-looking row that is in use - only whole-name mismatches against
  live trusts and `callback`-true subscriptions qualify.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before the phase commit

### Notes

- `actingweb/maintenance/peer_state.py`, entry `actingweb-peer-state`;
  `docs/guides/database-maintenance.rst`, "Peer State Written Before 3.16";
  the dependency row in `thoughts/todo/INDEX.md` is now hard.
- Kinds as planned, named `peer-permissions`, `future-permissions` (more
  than five minutes ahead or unparsable: the receiver's skew window from
  Phase 1's review, not "any future"), `callback-state`, `remote-data`
  and `remote-unknown` (never removed). The whitelist is a bucket that
  `get_remote_bucket()` builds for an id matching its permissive peer-id
  pattern; anything else under `remote:` is `remote-unknown`.
- Reads per actor (trust rows, subscriptions, attribute bucket names, the
  two buckets), strict; `--rps` default 10, as `actingweb-verify-orphans`;
  a read fault or a failed delete exits 2.
- **Found while writing the integration test, fixed:** the synchronous
  permission sender (`trust_permissions.py`) read a 204 (an empty answer)
  as a failure and logged `Failed to notify peer … {}` at WARNING for every
  successful callback; it is a success now (tested).
- The integration test shows the "restart" the command asks for: the wire
  apps run in the test process, so the store's cached copy is cleared as a
  restart would.
- Release impact: a new console script (the changelog's `ADDED`).
- **Outside voice on the Phase 4 commit and the Phase 3 fold** (codex and
  a fresh-context reviewer), folded in its own commit: the replacement rule
  narrowed to pending rows (owner, Update Log), conditional on both
  backends, a re-pair keeping `verified` as it was; `report` and a dry run
  exit 0 when only `remote-unknown` rows remain. Checked, nothing found:
  the DynamoDB condition on the composite key, `cur.rowcount` for `ON
  CONFLICT DO NOTHING`, whole-name comparisons, the callback-state names,
  that a `validate_peer_id=False` bucket is never removed. The consumer only
  reads `RemotePeerStore`, so `prune` removes nothing it writes itself.

### Implementation Status: Complete

---

## Phase 5: changelog, documentation and records

### Changes

- `CHANGELOG.rst`, `Unreleased`, `SECURITY` (each claim checked against the
  pre-fix runs in the verification document, "Exactly-true" wording):
  - Unauthenticated callbacks were accepted, and a low-granularity callback
    made the receiver send the trust's secret to the URL in the request.
    **Behavior change:** callbacks are authenticated (401), the two peer
    paths require the peer they name (403 for anyone else, the creator
    included), the fetch URL is built from the stored base URI, only `diff`
    and `resync` are accepted on the subscription path (400), and the
    library's hook names are reserved on the generic branch (403).
    **Check:** third parties pointed at `/callbacks/<name>` now receive 401;
    a `FanOutManager` low-granularity downgrade is not fetchable by a 3.16
    subscriber.
  - A peer could reach another peer's permissions, subscriptions and trust
    row through any row that admitted it, application `acl_rules`
    included. **Behavior change:** one rule binds a peer caller to the peer
    its path names; `GET /subscriptions?peerid=` lists a peer's own rows.
  - A trust-creation request for an existing peer replaced the row, reset
    its approval and changed its role. **Behavior change:** it verifies
    against the stored base URI and swaps the secret only; a moved peer is
    re-paired after the owner updates the base URI; a refused re-pair
    changes neither side; a swap fires no `trust_request_received`.
  - A subscriber could post to its publisher under its own subscription id.
  - A permission callback with a far-future timestamp blocked every later
    update in the process. **Behavior change:** clamped to the receiver's
    clock; an unparsable timestamp answers 400.
  - Peer and client views listed every peer's subscriptions.
  - Trust rows replaced before the fix cannot be detected; a deployment
    that suspects it deletes and re-establishes the trust.
- `CHANGELOG.rst`, `CHANGED`: **Breaking:** an access row authorises the
  method a request performs; a PUT or DELETE is no longer admitted by a GET
  row. **Check:** an application type whose peers clear their queue or are
  unsubscribed by their publisher through `("subscriptions/<id>/<subid>",
  "GET", "a")` adds `("subscriptions/<id>/<subid>", "PUT", "a")` and
  `("subscriptions/<id>/<subid>", "DELETE", "a")` on the publisher, or the
  gap-resync clear and the publisher's unsubscribe fail with 403 (logged
  once at WARNING by the publisher). `friend` is unaffected.
- `CHANGELOG.rst`, `ADDED` - `actingweb-peer-state`; `DELETE
  /trust/<rel>/<peer>?notify=false` for the creator.
- `docs/migration/v3.16.rst` - a "Start here" item (and the "first three
  items and item 11" sentence at `:16-17` updated), and a section "Peer
  paths are bound to their peer" with: the two rows as an `acl_rules=[...]`
  block and who adds them (the publisher's deployment); that `friend` is
  unaffected (`config.py:336`); the re-pair recipe (`PUT
  /trust/<rel>/<peer>` with `baseuri` for a moved peer; delete and pair
  again for a new relationship; `?notify=false` for a dead peer; a fixed
  domain for development tunnels); `actingweb-peer-state report`, then
  `prune --apply`, after every instance is on 3.16, then a restart; the log
  lines to grep for; the reserved names and that only a direct
  `/callbacks/<name>` request is affected.
- `docs/protocol/actingweb-spec.rst` - aligned with the decisions: `:1153-1159`
  (callback authentication, one rule), `:1207` and `:2885-2887` (a note
  that the diff GET consumes today and `spec-1-5` owns the change),
  `:1568-1574` and `:1881-1882` (replacement of an existing relationship),
  `:1747-1751` (who updates a row), `:2041-2042` (the creator and admin may
  also query), `:2858-2861` (the receiver fetches under the stored base
  URI).
- `docs/guides/access-control.rst:117-214`, `access-control-simple.rst:171-221`
  - how rows match (first match, string prefix, the method, application
  rows first), the peer binding, and the subscriber examples gain GET, PUT
  and DELETE rows on `subscriptions/<id>/<subid>`.
- `docs/guides/trust-relationships.rst:108-113` and
  `docs/guides/p2p-quickstart.rst:44-49` - the pending-trust contradiction.
- `docs/reference/security.rst`, `docs/reference/routing-overview.rst:36`,
  `docs/reference/hooks-reference.rst:46-53`, `README.rst:255-256` -
  callbacks are authenticated; reserved names; the admin exemption and
  where it does not apply.
- `examples/demo/shared_hooks/app/callback_hooks.py:47`, `:62` and the demo
  README - the `email_verify` link example becomes an authenticated
  example until the opt-in.
- `thoughts/plans/2026-11-06-spec-1-5.md` - T6 rewritten in its body (`:291-292`,
  the test at `:343-345`, the failure scenario at `:360`, the changelog line
  at `:695`): the replacement guard here replaces the 409; and `:317-318`
  corrected (`WA4` is 403). A dated Update Log line says so.
- `thoughts/plans/2026-11-06-subscription-wire-baseline.md:196-199` - "What
  Already Exists" points at `rows.toml` instead of a list.
- The Emm adoption items (the two rows; the re-pair recipe; a fixed preview
  domain) go into this plan's verification document and Emm's inbound note
  when the PR opens.

### New Tests, both unit and integration tests

- None beyond the docs build in the full tier.

### Failure Scenarios

- A docs example still shows a subscriber without PUT and DELETE rows - the
  grep below.

### Verification

- [x] Run the contract's `### Checks` full tier verbatim (docs build included)
- [x] `grep -rln '"subscriptions/<id>/<subid>", "DELETE"' docs/guides/access-control.rst docs/guides/access-control-simple.rst`
      lists both files
- [x] Emm's suite on this branch, as `thoughts/todo/emm-suite-against-master.md`
      describes, with the two rows added on Emm's adoption branch: no failure
      the `master` run did not have; also checked: a re-pair that answers 201
      does not create a second subscription (`../actingweb_mcp/api/trust.py:286-298`);
      the result in the verification document

### Notes

- The changelog, migration guide, specification and guides describe what
  landed, not the first text above: the permission timestamp's five-minute
  window and 400 (not a clamp); the re-pair with the current secret, toward
  the stored base URI only, no verification round trip; a pending row
  replaceable by a verifying request; the one-sided local delete that
  needs the other owner; a peer that cannot approve its own row or write
  its own permissions; the root POST, the client view and the proxy's
  refusal (`FIXED`); the permission sender's 204 (`FIXED`).
- The access-control guides also corrected a statement that was wrong
  before this plan: an access row with `r` does not refuse (any matching
  row admits); the guides say to leave a method out instead.
- `docs/guides/trust-relationships.rst`: a pending peer is refused (403) on
  subscriptions and callbacks, as `p2p-quickstart.rst` already said.
- Emm's suite on this branch (owner decision: the two rows added in the
  adoption worktree only): no failure the `master` run did not have, on
  both backends. The plan's extra check found that Emm's connect flow
  subscribes a second time after a re-pair answering 201: an adoption item
  for Emm (verification, item 6), not a library change.
- The Full tier last ran on `0ce0112` (both backends); this phase changes
  documentation, plans and a demo docstring only: `ruff`, `pyright` and the
  docs build ran on it.

### Implementation Status: Complete

---

## Evaluation Notes

### Third review, 2026-11-07: the redraft

Five evaluators (architecture; security; tests and code quality;
usability; scalability) read Phases 0 to 5 against the code, then the outside
voice (Codex, run outside the command sandbox, and a fresh-context reviewer)
was given their findings. Nothing was run. Disposition:

Taken to the owner and decided (Update Log, "review of the redraft
folded"): the `admin` exemption on `/callbacks`; the initiator's side of a
re-pair; the re-pair remedies and the local delete; the hook on a swap;
403 for refused callback names; clamping the permission timestamp; dropping
the replica rebuild.

Folded as mechanical:

- Architecture: the creator passing the new `any` row on the peer callback
  branches (now `peer_caller_only`); `get()` and the generic `delete()`;
  `trust.py:1061`; the trust DELETE's lookup order (kept, recorded); the
  same-secret check on the swap; the status from the stored row;
  `IndexError` on short paths; reserved names on every method; the body's
  `url` still selecting the branch; `FanOutManager`'s downgrade.
- Security: an empty peer segment; an unparsable timestamp; the
  subscription root's `?peerid=`; prune comparing whole names, counting only
  `callback`-true subscriptions, catching future-dated rows for trusted
  peers, never splitting on `:`, and a `remote:` whitelist; processes
  keeping cached permissions after a prune; devtest writing any bucket when
  on (unchanged; it must stay off in production, as documented).
- Tests and code quality: the existing tests that break, each listed in the
  phase that breaks it; `WA4` recorded at 403; `WA8` and `WT2` needing a
  third listener; mid-row names in the normaliser; the second trust type on
  every app's configuration; the CI step's marker, junit, coverage,
  watchdog, gate and timeout; per-site trust tests; tests for every Phase 4
  behaviour.
- Usability: the publisher logging the GET-row refusal; status codes in the
  subscriber's warnings and `actor.py:2545` at WARNING; concrete migration
  content; a docs grep that can fail; **Breaking:** under `CHANGED`; the
  operator command's subcommand, positional actor, exit codes and `--rps`
  like the existing commands; Emm's preview tunnel as a moved peer.
- Scalability: one read of the existing row in Phase 3; per-actor reads
  and `--rps` in Phase 4.
- Outside voice: the `WD6.subscriber` prediction (the diff GET already
  consumes); the spec ranges the decisions contradict; T6 rewritten in the
  spec plan's body, not only its log; the `remote:<peer>$aux` bucket and the
  INDEX dependency; later plans' statements about these rows (`rows.toml`
  owner column); `peer_approved` and `verified` named in the swap; one
  filter method for the views; the binding being unsound until Phase 3,
  stated in each verification.

Unverified notes:

- How the integrations route `/callbacks/permissions/` with a trailing slash
  (whether `path[1]` arrives empty); the 400 covers both.
- Whether an MCP client token authenticates on `/callbacks` as a peer
  caller; `peer_caller_only` refuses it either way unless its peer id is the
  path's.
- What an unauthenticated generic callback answers today (the handler sets
  no status); the pre-fix run of `WA3` settles the changelog wording.
- A health check configured outside the consumer's repository calling
  `/callbacks/ping` anonymously would go from 2xx to 401.

### Earlier reviews

The sections below are the reviews of the first draft and are kept as they
were. Where they say a review is owed, the third review above is it.

Phases 1 to 3 were written from findings the reviews of the other plans made
(three reviewers reached the callback finding independently) and from one run
against real storage. They have not been through the five-dimension review;
it is owed before approval. Phase 0 and the wire rows were reviewed on
2026-11-06 in their first form (a full baseline as this plan's Phase 0) by
one evaluator for tests, quality and architecture, and by the outside voice;
the findings about the baseline itself are in
`thoughts/plans/2026-11-06-subscription-wire-baseline.md`. What follows is
what concerned this plan.

### Architecture

- The recorder has to see every request to the wire apps, not only
  `/callbacks`: the paths Phase 2 tightens are `/subscriptions`, and a
  subscriber's fetch, acknowledgement and delete are on them.
- A subscriber unsubscribing reaches its publisher through `DELETE
  /callbacks/subscriptions/…` (`actor.py:2520-2529`), and a publisher's
  delete reaches the subscriber through `DELETE /subscriptions/…`. Both are
  the path's own peer; `WC3` and `WC4` are in Phase 0 because of it.

### Security

- **New, taken into Phase 1:** a callback is accepted against a subscription
  the actor holds as publisher. The peer rule does not stop it, because the
  caller is the peer the path names.
- **Corrected:** a wrong bearer is accepted today as no credentials are
  (the authentication result is never looked at); it gets its own test.
- **Corrected:** the consumer does not turn on `auto_delete_on_revocation`
  (it passes `enable=True` only, `../actingweb_mcp/application.py:558-560`;
  the default is off, `interface/app.py:851`). The deletion exposure is for
  deployments that set it.
- **Corrected:** a peer cannot create a subscription under another peer's id
  today.
- Not run: the full security review of Phases 1 to 3.

### Scalability

Not reviewed. Phase 0 adds two test servers per worker, inside its ten ports.

### Usability

Not reviewed.

### Tests and code quality

- A test that passes because a hole is open is not committed; the pre-fix
  run is kept in the phase notes instead (owner's decision on placement).
- The fourteen Phase 0 rows are the legitimate users of the handlers this plan
  changes; "byte-identical after the fix" is a stronger statement than the
  "existing flows still pass" the first draft made, and before Phase 0 there
  was no such flow to pass for permission callbacks, resyncs or low
  granularity.
- CI retries failures twice; the wire marker is exempt.

### Outside voice

Codex (outside the command sandbox) and a fresh-context reviewer,
2026-11-06, on the first form:

- **The baseline delayed the fix, and its access rows were passing exploit
  tests in public history.** The owner moved the baseline to its own plan;
  the access rows are recorded secured.
- **No release path delivers the fix before 3.16.** Put to the owner: it
  stays in 3.16, without a backport (Decisions).
- **An SDK step under a default `Config` would send a trust secret to the
  default host and turn a row red under Phase 1's prefix check.** The driver
  builds its interface from the wire app's configuration, and the normaliser
  fails on a foreign host.
- **Stopping to correct plans that are not approved would gate the fix on
  them.** Only a recording that contradicts this plan gates it.
- **The commit that adds a hole-pinning test stays in `master`'s history
  even when a later commit flips it.** Moot: none is committed.

### Unverified notes

- Nothing in Phase 0 has been run; the expectations in the research are from
  reading.
- Whether the PostgreSQL subscription lookup filters on the `callback` flag;
  only the DynamoDB one was read (`db/dynamodb/subscription.py:69-73`).
- Whether `peer_permissions` on the two wire apps is what a permission
  callback needs: `notify_peer_on_change` defaults to on even without it
  (`trust_permissions.py:175-187`), and the subscriber's follow-up fetch is
  gated by subscription processing (`handlers/callbacks.py:288-304`).
- The subscription-callback and URL findings are traced from the code; only
  the permission-callback and generic-callback cases were run.
- That `AwProxy.create_resource` sends the trust's bearer on the synchronous
  permission-callback path (`aw_proxy.py:123-125`, `:237`) was read, not run;
  `WP1` covers it.
- Whether any deployment relies on a peer with an unapproved trust delivering
  callbacks.

### Second review, 2026-11-06: recorded, not folded

Three evaluators read Phases 1 to 3 against the code (architecture;
security; tests, scalability and usability), then the outside voice (Codex,
outside the command sandbox, and a fresh-context reviewer) was given their
findings. Nothing was run. Marked `[decision]` where the owner chooses,
`[research]` where the plan cannot state the answer from what has been read.

Critical:

- **The trust row is replaceable without credentials.** `POST /trust/<type>`
  is unauthenticated (`config.py:325`, `handlers/trust.py:370-383`) and
  creation is an upsert that replaces `secret`, `baseuri` and `approved` and
  keeps the owner's grants (`trust.py:450-452`,
  `db/postgresql/trust.py:299-308`). No auto-accept is needed for harm: an
  unapproved peer may `DELETE trust/<type>/<id>` (`handlers/trust.py:964-970`),
  which purges the relationship, its subscriptions, replica, callback state
  and permissions (`actor.py:2084-2204`) without telling the real peer; and
  the publisher's callbacks follow the replaced `baseuri` and `secret` with
  no approval test (`actor.py:2631-2633`, `:2674-2684`;
  `trust_permissions.py:365-388`). The verification handshake cannot anchor
  a guard: it calls the base URI from the request body (`actor.py:1939`).
  The only planned guard is the specification plan's 409 (T6), whose own
  review rejects it. `[decision]` whether a guard lands here and in which
  shape (refuse an existing peer id; or replace only when the new secret
  verifies against the stored base URI); each breaks something different for
  a re-initiating peer (`actor.py:1703-1775`,
  `../actingweb_mcp/api/trust.py:256-263`). `[research]` what a pending,
  replaced row may set on itself (`handlers/trust.py:711-885`).

Major:

- **Application access rows defeat Phase 2's permission fix.** A trust
  type's `acl_rules` are inserted at index 0
  (`permission_integration.py:414-416`), and the consumer's `subscriber`
  type has `("permissions/<id>", "GET", "a")`
  (`../actingweb_mcp/application.py:864-868`). The fix has to be a handler
  rule, as for subscriptions, with a test using a type that has its own row.
- **The same defect class on `/trust`.** The empty-role row `trust/<type>`
  prefix-matches `trust/<type>/<id>` for POST, so any authenticated caller
  can set `peer_approved` on another peer's row
  (`handlers/trust.py:634-692`). The consumer's
  `("trust/<type>/<id>", "GET", "a")` row (`application.py:847`) would let a
  `subscriber` peer read another peer's trust row, `secret` included
  (`handlers/trust.py:534-540`, `:596-602`); read, not run. `[decision]` one
  central rule in `check_authorisation` (a matched row whose path holds
  `<id>` requires the caller's peer id to be that id, admin exempt) or
  per-handler rules and a second plan for `/trust`. `[research]` the full
  table, application rows included.
- **The consumer's peers are `subscriber`, not `friend`**
  (`application.py:835-868`), and its GET row admits PUT and DELETE because
  those authorise as "GET" (`handlers/subscription.py:381`, `:440`). The
  changelog's "`friend`" and "four relationship types" understate who is
  affected, and the wire pairs need a `subscriber`-shaped variant.
- **The generic branch dispatches reserved hook names.**
  `/callbacks/permissions` with no peer segment, `/callbacks/subscription`
  and `/callbacks/www` reach `execute_callback_hooks` with the caller's body
  (`handlers/callbacks.py:440-463`); the consumer's `permissions` hook trusts
  that body (`../actingweb_mcp/hooks/actingweb/callback_hooks.py:202-220`).
  Reserve the names. `[decision]` whom the `any` row admits (every approved
  peer of every type today), or creator and trustee only until the opt-in.
- **A bearer that matches nothing answers 403, not 401** (`auth.py:138-144`).
  `WA4` and one unit test expect 401. `[decision]` change `auth.py` for every
  path, or record 403.
- **The `url` rule.** The publisher builds the URL from its own
  configuration; the subscriber's stored base URI is whatever was typed at
  trust creation (`../actingweb_mcp/api/trust.py:168`, `:256-260`), so an
  alias, a tunnel or a port makes every low-granularity callback and the
  fallback full state answer a 400 nobody can diagnose, and only creator,
  trustee or admin can repair the base URI. `[decision]` keep a prefix test
  (then specify it: parsed scheme, host, port and a path segment boundary;
  no redirects) or drop the body's `url` and have the receiver build
  `subscriptions/<own id>/<subid>/<sequence>` under the stored base URI, as
  the acknowledgement and the resync already do
  (`handlers/callbacks.py:558-575`, `:824-833`). The fetch is triggered by
  any body with `url` and no `data`, not only by low granularity (`:515-524`),
  and the legacy branch hands `url` to application hooks (`:402-415`).
- **State forged before the fix survives it.** Pending callbacks are drained
  into the replica by the next genuine one
  (`callback_processor.py:913-939`); no resync removes forged keys
  (`remote_storage.py:550-551`); a body `type` of `permission` bypasses
  sequencing (`callback_processor.py:821-823`); permission rows for peer ids
  with no trust are never reaped; a far-future `fetched_at` outranks genuine
  callbacks in a process (`peer_permissions.py:261-268`). Phase 1 should
  bound the timestamp and refuse unknown types; Phase 3 needs an operator
  remedy that covers stored permissions, pending state, sequences and
  replicas, in an order. `[research]` which backend reaps what.
- **The publisher-row rule** belongs in
  `SubscriptionManager.get_callback_subscription`; neither backend filters on
  the flag (`db/postgresql/subscription.py:59-66`). It must not be applied to
  the callback DELETE as Phase 1 words it: there the row is the publisher's
  and the subscriber is the rightful sender (`actor.py:2520-2529`). That
  branch deletes with `callback=True` regardless today and can wipe a replica
  (`handlers/callbacks.py:122-124`).
- **Tests.** The cited recipe mocks authentication
  (`tests/test_db_fault_callers.py:325-329`); four existing tests pin
  today's behaviour and break (`tests/test_callback_in_progress_answer.py:41-45`,
  `tests/test_permissions_handler.py:150-167`, `:182-214`); the helper for
  "both backends" pins DynamoDB (`tests/_adoption_helpers.py:34`); trustee,
  an OAuth2 or SPA token, an MCP client token and a cookie caller are
  missing; Flask's rendering of the challenge is untested; "phase notes" has
  no home (the record is `verifications/`); Phase 0 records no trust flow.
- **The exposure statement** in Phase 3 is wrong in three places (what
  triggers the fetch; that nothing logs an accepted forgery above DEBUG; that
  an `admin` peer reads every trust's secret), lacks the contract's
  **Behavior change:** and check sentences on three entries, and omits that
  a forged callback DELETE strips the owner's grants in the consumer
  (`../actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:789-795`).
- **The CI step** for the `wire` marker must stay a step of the `tests` job
  with the `changes` gate (`.github/workflows/tests.yml:128-143`), needs its
  own environment, junit and coverage handling, runs on Python 3.11 and
  3.14, and shares a 30-minute job limit; `Makefile:58` deselects nothing.

Minor: `_is_path_peer` must require a non-empty peer id; short callback
paths raise (`handlers/callbacks.py:89-90`, `:342-343`); `post()` needs an
early return; a `creator` role row would match a relationship named
`creator`; the permission branch stores any structure and answers 204 when
the store refuses; the new permission rows omit trustee; an anonymous probe
goes from 200 to a 401 with a Basic challenge; Phase 3's file references
are a few lines off and miss `docs/guides/p2p-quickstart.rst:179-184`,
`docs/guides/access-control.rst:131-136` and
`docs/reference/routing-overview.rst:36`; `/devtest` authenticates and never
authorises when it is on (`handlers/devtest.py:15-19`).

Verified as drafted: both peer branches for callers without credentials and
for the wrong peer; no new storage read on any path; no consumer or demo
call site the new rules refuse; every other secret-bearing request goes to
the stored base URI; `httpx` follows no redirect; one handler class serves
both integrations.

Facts bearing on the release decision, for the owner: the replacement path
needs no credentials and no auto-accept and exists in `v3.15.1`, which the
consumer pins; the tag is held until all six plans merge; this PR's
`SECURITY` entry would say "a peer reaches only its own" while the row
stays replaceable unless a guard lands with it.

## Removed Phases

- **"Phase 0: the subscription wire as it is today, pinned"** (added and
  removed on 2026-11-06). A full baseline of about sixty hand-asserted rows
  as this plan's first commit, including rows that asserted the open holes
  passed. Removed because it put a suite-wide rewrite in front of the fix,
  kept passing exploit tests in history, and its expectations came from
  reading the code, about a dozen of them wrongly. It became
  `thoughts/plans/2026-11-06-subscription-wire-baseline.md`, with recordings
  in place of expectations; this plan keeps the harness and fourteen rows.

## Implementation Summary

**Completed:** 2026-11-08
**All phases:** Complete (0 to 5), each followed by a commit folding the
outside voice on it
**Test status:** Full tier green on both backends at `0ce0112`; the wire
rows identical over five sequential runs per backend at Phase 0 and on
every later run; Emm's suite on this branch matches its `master` baseline.

### Deviations from Plan

- Re-pairing (owner, 2026-11-08): the plan's receiver verified with the new
  secret while its initiator wrote nothing first, which could not both
  hold. A re-pair carries the current secret as bearer instead; no
  verification round trip; the initiator re-pairs only toward the stored
  base URI and relationship.
- Pending rows (owner, 2026-11-08, twice): an unverified row blocked the
  real peer; first any verifying request could replace it, then, after the
  review showed a verification proves only control of a base URI and a
  squatter could promote its own row, only a pending row (neither verified
  nor approved) is replaceable, by a conditional write; a re-pair never
  marks a row verified.
- Permission timestamps (owner, Phase 1 review): a five-minute skew window
  and 400, not a clamp.
- Conditional trust creates on both backends (`only_if_absent`,
  `only_if_pending`), not in the plan, after a race the Phase 3 review
  found.
- Hardening the reviews found, not in the plan: a peer cannot approve its
  own trust row or write its own permissions; the subscription root's
  POST binds the peer; a client view lists what it creates; `AwProxy` no
  longer reads a refusal with no body as success; a refused remote
  unsubscribe is logged with its status.
- `rows.toml` gained a `topologies` key; `WIRE_RECORD` takes row ids; the
  snapshot includes trust rows and permissions from Phase 0.

### Learnings

- Every hole the plan described was open, confirmed by the pre-fix runs
  (verification document), and two it did not predict: an unauthenticated
  trust request rewrote a row's base URI and secret even though its
  verification failed (`WT2`), and a peer with an application GET row read
  another peer's trust row, secret included (`WA16`).
- A trust row's peer id is only a claim and a verification only proves
  control of the requester's base URI: identity is the stored base URI and
  the secret, which is what the re-pair rules now rest on.
- `create_resource`/`change_resource` callers test for `error`, so a
  refusal without a body read as success; the subscriber-type migration
  failure would have been silent without it.
- One-sided local deletes now need the other owner's help to re-pair
  (migration guide).

## Iterations

### 2026-11-08, after verification thoughts/verifications/2026-11-08-peer-authorisation-fixes.md

#### 1. No peer reads another peer's secret

**Category**: Verification fix (Issue 1); Decision changed (owner)

**What changed**: the per-peer trust GET leaves out `secret` and
`verification_token` for every peer caller but the row's own, `admin`
included; the creator, the trustee and the peer itself still receive them.
A peer caller cannot change the base URI of another peer's row (403).

**Files affected**:
- `actingweb/handlers/trust.py` - `TrustPeerHandler.get` (redaction),
  `TrustPeerHandler.put` (base URI)
- `tests/test_peer_paths_binding.py` - `TestNoPeerReadsAnothersSecret`

**Rationale**: an `admin` peer read another peer's secret, then authenticated
as that peer (passing the `/callbacks` binding the owner denied admins) and
re-paired its trust, locking it out.

#### 2. A verified row is bound to its base URI

**Category**: Verification fix (Issue 4); Decision changed (owner)

**What changed**: `create_verified_trust` marks a creation verified only
when, besides the token check, the requester's base URI serves the claimed
peer id (`<baseuri>/meta`'s `id`, one try, `Actor._base_uri_serves`);
otherwise the row is stored unverified (a new peer) or the request is
refused (a pending row is replaced only by a verified request). `WT3`
re-recorded: A's `GET /<N>/meta` after the verification GET.

**Files affected**:
- `actingweb/actor.py` - `create_verified_trust`, `_base_uri_serves`
- `tests/test_trust_re_pair.py` - `_peer_answers`, `TestTheClaimIsBound`;
  the pending-row tests answer `/meta`
- `tests/test_trust_verification_token_missing.py` - the matching-token
  test patches `_base_uri_serves`
- `tests/integration/wire/WT3.*.json`, `rows.toml`

**Rationale**: a verification proved only that the requester controls the
base URI it sent, so a squat under another actor's id was stored verified
and, since a verified row is never replaced, blocked the real peer.

#### 3. A trust modify writes only its own attributes, on a live row

**Category**: Verification fix (Issue 2)

**What changed**: DynamoDB's `DbTrust.modify` sends only the attributes it
changes, in one `UpdateItem` conditioned on the row existing (it saved the
whole loaded item); PostgreSQL's returns False when its `UPDATE` touched no
row. A usage write from a request authenticated just before a re-pair no
longer writes the old secret back, and a modify racing a delete no longer
recreates the row (DynamoDB) or reports success (PostgreSQL).

**Files affected**:
- `actingweb/db/dynamodb/trust.py` - `modify`
- `actingweb/db/postgresql/trust.py` - `modify` (rowcount)
- `tests/test_trust_re_pair.py` - `TestTheSwapIsNotWrittenBack` (both
  tests fail on both backends without the change)

**Rationale**: the re-pair's swap raced `_record_trust_usage`, which modifies
the row on every authenticated bearer request; the two sides then held
different secrets with nothing logged.

#### 4. A lost re-pair answer is probed

**Category**: Verification fix (Issue 3)

**What changed**: when the re-pair's request gets no answer or a 5xx, the
initiator GETs its own trust row at the stored base URI with the new secret
as bearer; a 200 means the peer swapped, and the new secret is stored (with
`peer_approved` from the answer's `approved`); anything else leaves the row
and logs that the peer may have accepted, with the recovery. Sync and async.

**Files affected**:
- `actingweb/actor.py` - `_re_pair_unknown`, `_re_pair_unknown_async`,
  `_re_pair_probe_request`, `_re_pair_probed`; both re-pair branches
- `tests/test_trust_re_pair.py` - `TestALostAnswerIsProbed`; the refusal
  test patches the probe

**Rationale**: a swap committed at the peer whose answer was lost left the
two sides on different secrets, with a log saying nothing changed.

#### 5. Permission callbacks ordered by one clock at a time

**Category**: Verification fix (Issue 7)

**What changed**: a permission callback stores this receiver's clock in
`fetched_at`, as a copy fetched by query does, and the sender's timestamp in
`extra_attributes["sender_timestamp"]` (not a new field: `from_dict` is
`cls(**data)`, so a 3.15 instance would fail on an unknown key during a
rolling deploy). A callback is ignored only when it is older, by the
sender's clock, than the sender's last stored callback; the store compares
`fetched_at` as parsed times, not strings. The five-minute skew window
stays. Every wire row whose snapshot holds B's stored copy (all 44)
re-recorded; the only difference is the added key (checked over all 81
changed files).

**Files affected**:
- `actingweb/handlers/callbacks.py` - the permission branch
- `actingweb/peer_permissions.py` - `SENDER_TIMESTAMP_KEY`, `_parsed_time`,
  `store_permissions`
- `tests/test_peer_binding.py` - `TestThePermissionOrderUsesOneClock`
- `tests/integration/wire/*.json`, `rows.toml` (a reason line per row)

**Rationale**: a copy fetched by query carried the receiver's clock and a
callback the sender's; a sender with a slow clock had its revocation
answered 204 and dropped, and rows stored before 3.16 in another offset
blocked newer updates as strings.

#### 6. `actingweb-peer-state --all-permissions`

**Category**: Verification fix (Issue 5)

**What changed**: `report` and `prune` take `--all-permissions`, which also
lists every live peer's stored permission copy (`permissions-copy`), so a
forged copy for a trusted peer can be removed (each rebuilds from the next
callback or query). The guide and the module docstring also say what
`remote-data` removes for a trusted peer without a subscription (Issue 11).

**Files affected**:
- `actingweb/maintenance/peer_state.py`; `docs/guides/database-maintenance.rst`
- `tests/test_peer_state_command.py` - `TestAllPermissions`

**Rationale**: a pre-3.16 forged copy for a trusted peer with a current
timestamp looked like a real one.

#### 7. `FanOutManager` delivers only with the trust's secret, to its base URI

**Category**: Verification fix (Issue 6)

**What changed**: no trust, secret or base URI: nothing is sent (a failed
result); the callback goes to `<baseuri>/callbacks/subscriptions/<own
id>/<subid>` under the stored base URI, not to a stored `callback_url`.

**Files affected**:
- `actingweb/fanout.py` - `_deliver_single`
- `tests/test_fanout.py` - the mocked trust carries a base URI; the no-trust
  test now asserts nothing is sent; the header test asserts the URL

**Rationale**: it sent unauthenticated callbacks (refused by a 3.16
receiver), and to a URL the trust was not made with.

#### 8. The permission branch's edges, the demo webhooks, a type hint

**Category**: Verification fix (Issues 8, 9, 10)

**What changed**: the `permissions` hook is told the real method (`PUT` for
a PUT); a body or `data` that is not a JSON object answers 400, not 500;
the demo's `sms_webhook` and `payment_webhook` docstrings say a provider
cannot call `/callbacks` without credentials; `_match_access_row` is typed.

**Files affected**:
- `actingweb/handlers/callbacks.py`; `actingweb/auth.py`
- `examples/demo/shared_hooks/app/callback_hooks.py` (docstrings only)
- `tests/test_peer_binding.py` - `TestThePermissionBranchEdges`

**Rationale**: the verification's low findings.

#### 9. Documentation for iterations 1 to 7

**Category**: Verification fix

**What changed**: the changelog's `SECURITY` and `ADDED` entries, the
migration guide, the security reference, the maintenance guide and the
specification note describe the secret redaction, the `/meta` binding, the
field-level trust modify, the lost-answer probe, the one-clock ordering,
`FanOutManager`'s delivery and `--all-permissions`. Decisions Made gains
the two owner decisions.

**Files affected**: `CHANGELOG.rst`, `docs/migration/v3.16.rst`,
`docs/reference/security.rst`, `docs/guides/database-maintenance.rst`,
`docs/protocol/actingweb-spec.rst`, this plan.

#### 10. Emm's suite on the iteration

**Category**: Verification (gate 2)

**What changed**: nothing in the library. Emm's suite re-run against
`d836bd0` (the library worktree re-pointed; the adoption worktree with the
two `subscriber` rows; environment 9): PostgreSQL 2 failed / 7406 passed,
DynamoDB 3 failed / 54 passed, the `master` baseline's failures by name.
The Full tier on `d836bd0`: DynamoDB 6025 passed, PostgreSQL 5822 passed,
the docs build.

**Rationale**: the iteration changed library code; gate 2 asks for the run
before the PR.

### 2026-11-08, after verification thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-1.md

#### 11. Auto-accept approves only a request that verified

**Category**: Verification fix (Issue 1); Decision changed (owner, option (a))

**What changed**: `create_verified_trust` stores an unverified creation
unapproved whatever `approved` it was given (a WARNING says so); the
creation answer follows the stored approval (`201`/`202`, parsed from the
created row's string flags). `_base_uri_serves` uses `get_peer_info`'s
default retries, and its docstring and the comment say it catches a wrong
base URI, not a false id.

**Files affected**:
- `actingweb/actor.py` - `create_verified_trust`, `_base_uri_serves`
- `actingweb/handlers/trust.py` - `TrustRelationshipHandler.post` status
- `tests/test_trust_re_pair.py` - `TestAutoAcceptNeedsAVerifiedRequest`
- `CHANGELOG.rst`, `docs/reference/security.rst`, `docs/migration/v3.16.rst`,
  `docs/protocol/actingweb-spec.rst` - the limitation stated

**Rationale**: the `/meta` check is answered by the squatter, and
auto-accept approved a creation that never verified; an approved row is
never replaced, so the real peer was blocked. An actor id is self-asserted;
no check closes a squat by a host that verifies, which is now documented.

#### 12. An `admin` peer's DELETE of another peer's row: accepted

**Category**: Decision changed (owner, Issue 2 accepted)

**What changed**: nothing in code. The security reference, the changelog
and the migration guide say an `admin` peer can delete any peer's row and
re-create it under that peer's id, and to grant `admin` accordingly.

**Files affected**: `CHANGELOG.rst`, `docs/reference/security.rst`,
`docs/migration/v3.16.rst`

**Rationale**: owner decision; `admin` is the owner-equivalent peer.

#### 13. A lost re-pair answer into a pending trust is confirmed

**Category**: Verification fix (Issue 3)

**What changed**: the per-peer trust `GET` answers the row's own peer while
the row is unapproved (202 with the row, as the creator already got),
where it answered 403; another peer still gets 403. The probe accepts 200
or 202 (the peer authenticated the new secret either way) and sets
`peer_approved` from the answer's `approved`, parsed as `"true"`. The
warning names the probe's status and says 401 or 403 with the existing
secret means the peer accepted. The async probe catches every exception, as
the sync one does (an invalid stored URL raised `httpx.InvalidURL`).

**Files affected**:
- `actingweb/handlers/trust.py` - `TrustPeerHandler.get`
- `actingweb/actor.py` - `_re_pair_probed`, `_re_pair_unknown`,
  `_re_pair_unknown_async`
- `tests/test_trust_re_pair.py` - `TestTheOwnPeerReadsItsPendingRow`

**Rationale**: an unapproved trust answered the probe 403, so an accepted
re-pair (202) whose answer was lost split the pairing. The spec's trust GET
gives "status information about the relationship (ex. approved, pending
etc)".

#### 14. Concurrent permission callbacks: a conditional write

**Category**: Verification fix (Issue 4)

**What changed**: the permission branch reads the stored row from the
database (`PeerPermissionStore.read_stored_permissions`), decides (older by
the sender's clock: ignored), deletes revoked data, and stores with
`replace_permissions`: `conditional_update_attr` over the row it read, or
`create_attr_if_absent` when there was none. A callback that loses the
race reads again and decides against the winner's row; after five lost
races in a row it answers 503 with `Retry-After: 1`.

**Files affected**:
- `actingweb/peer_permissions.py` - `read_stored_permissions`,
  `replace_permissions`
- `actingweb/handlers/callbacks.py` - the permission branch,
  `PERMISSION_STORE_ATTEMPTS`
- `tests/test_peer_binding.py` - `TestConcurrentPermissionCallbacks`
  (older loser ignored, newer loser stored; both fail without the change)

**Rationale**: a grant and its revocation handled at once both read the
same row, and the later write won whatever its timestamp, bringing revoked
data back. A sync after the winner's revocation fetches from the granting
peer, which answers with its current permissions, so it cannot restore
revoked data.

#### 15. `--all-permissions` rebuilds each copy it removes

**Category**: Verification fix (Issue 5)

**What changed**: after `prune --all-permissions --apply` removes a live
peer's copy, the command queries that peer (`fetch_peer_permissions`) and
stores the answer, printing `rebuilt` or `not rebuilt` with the reason.
The help, the module docstring, the guide, the migration guide and the
changelog's `ADDED` entry say so.

**Files affected**:
- `actingweb/maintenance/peer_state.py` - `rebuild_copies`
- `docs/guides/database-maintenance.rst`
- `tests/test_peer_state_command.py` - `TestAllPermissions`

**Rationale**: without a copy the peer's next callback is taken for its
first, and a pattern revoked in it deletes no stored data.

#### 16. A refused trust modify keeps the object as it was

**Category**: Verification fix (Issue 6)

**What changed**: DynamoDB's and PostgreSQL's `DbTrust.modify` restore the
handle when the row is gone (False), and `Trust.modify` restores its copy.
`_record_trust_usage` records nothing when the row is gone; the OAuth
trust update logs a WARNING instead of "Updated". Accepted, not changed: a
modify whose values equal the stored ones returns True on DynamoDB without
a request, while PostgreSQL's `UPDATE` reports a deleted row as False.

**Files affected**:
- `actingweb/db/dynamodb/trust.py`, `actingweb/db/postgresql/trust.py`,
  `actingweb/trust.py` - `modify`
- `actingweb/auth.py` - `_record_trust_usage`
- `actingweb/interface/trust_manager.py` - the OAuth trust update
- `tests/test_trust_re_pair.py` - `TestARefusedModifyKeepsTheCopy`

**Rationale**: a modify on a deleted row reported values that were never
written, and two callers took False for success.

#### 17. `FanOutManager` reports a trust read fault for its peer

**Category**: Verification fix (Issue 8)

**What changed**: a `DbError` reading the trust is a failed delivery for
that peer (`trust read failed`, logged at WARNING), not an anonymous
exception from `gather`; the docstring says `callback_url` is ignored.

**Files affected**: `actingweb/fanout.py` - `_deliver_single`;
`tests/test_fanout.py` - `test_a_trust_read_fault_is_reported_for_its_peer`

**Rationale**: the verification's low finding; Issue 7's remaining parts
(default retries, the async probe's catch) are in iterations 11 and 13.

### 2026-11-08, after verification thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-2.md

Emm's suite on `a8007e5` (gate 2) matched its `master` baseline on both
backends before this batch (recorded in that verification).

#### 18. The permission sender resends a 503

**Category**: Verification fix (Issue 1); Decision (owner)

**What changed**: `TrustPermissionStore._notify_peer` and
`_notify_peer_async` resend a callback answered 503 up to twice with the
same body; the async sender waits the receiver's `Retry-After` (capped at
2 s, `_retry_after`), the sync one 1 s (`AwProxy` keeps no headers). The
spec says a receiver MAY answer 503 and the sender SHOULD resend.

**Files affected**:
- `actingweb/trust_permissions.py` - the two senders, `_retry_after`, the
  three constants
- `docs/protocol/actingweb-spec.rst` - Receiver Behavior
- `tests/test_trust_permissions_unit.py` - `TestThePermissionSenderResendsA503`

**Rationale**: the receiver's 503 asked for a resend nobody made; the
update was lost until the next callback or query.

#### 19. Data a losing callback deleted is fetched again

**Category**: Verification fix (Issue 2)

**What changed**: the callback keeps deleting revoked data before its
conditional write (so a fault still leaves the old copy and the resend
finishes the deletion), and records what each attempt deleted. When the
loop ends, ignored as older or stored, what was deleted and the outcome no
longer revokes is fetched from the granting peer with the incremental sync,
together with newly granted patterns. The sync moved into
`_sync_permitted_patterns`.

**Files affected**:
- `actingweb/handlers/callbacks.py` - the permission branch,
  `_sync_permitted_patterns`
- `tests/test_peer_binding.py` -
  `test_a_revocation_that_loses_to_a_regrant_restores_what_it_deleted`

**Rationale**: a revocation that lost to a newer re-grant left the copy
granting a pattern whose replica data it had deleted, with no error.
Moving the deletion after the write would have lost the fault property, so
the losing side restores instead; the peer answers by its current
permissions, so the sync fetches nothing it no longer grants.

#### 20. Every writer of the stored copy is conditional; a fault is not a lost race

**Category**: Verification fix (Issues 3 and 4)

**What changed**: `PeerPermissionStore.store_permissions` (the query path,
`RemotePeerStore`'s permission update, the rebuild) reads the stored row
from the database, refuses a copy whose `fetched_at` is older (stamped
before the fetch began, so a query that began before a callback was stored
loses in any process), and stores through `replace_permissions`, five
attempts. `replace_permissions` re-reads after a refused conditional
update: a row still equal to what was read means a fault, and it raises
`DbError` (the callback answers 503 through the integration). The
callback's log names lost races only.

**Files affected**:
- `actingweb/peer_permissions.py` - `store_permissions`,
  `replace_permissions`, `STORE_ATTEMPTS`
- `actingweb/handlers/callbacks.py` - the 503 log line
- `tests/test_peer_binding.py` -
  `test_a_query_older_than_the_stored_copy_is_not_stored`,
  `test_a_fault_on_the_conditional_write_raises`

**Rationale**: the query path wrote unconditionally and ordered by the
process's cache only, so a stale query in another worker could overwrite a
revocation; and a DynamoDB throttle was logged as concurrency.

#### 21. A trusted peer's copy is rebuilt right after its removal; a failed query keeps the copy

**Category**: Verification fix (Issue 5)

**What changed**: `prune --apply` rebuilds each removed copy of a trusted
peer (`permissions-copy`, and now `future-permissions`) before the next
removal (`_rebuild_copy`, `REBUILT_KINDS`); a store fault prints `not
rebuilt ... store fault`. `_refresh_peer_metadata` and its async twin no
longer store a failed permission fetch over a good copy, as `sync_peer`
already did not.

**Files affected**:
- `actingweb/maintenance/peer_state.py` - `prune`, `_rebuild_copy`, the
  docstring
- `actingweb/interface/subscription_manager.py` - the two refreshes
- `docs/guides/database-maintenance.rst`
- `tests/test_peer_state_command.py` -
  `test_each_copy_is_rebuilt_before_the_next_is_removed`, the prune test
  patched (it queried a real host)
- `tests/test_subscription_baseline_fetch.py` -
  `test_a_failed_permission_query_keeps_the_stored_copy`
- `tests/integration/test_peer_state_flow.py` - expects the live peer's
  future-dated copy rebuilt (it expected an empty bucket; the Full tier
  failed it on both backends until updated)

**Rationale**: a copy stayed missing for the whole run, a partial run
rebuilt nothing, a future-stamped copy was never rebuilt, and a failed
metadata refresh reached the same "no copy" state without any prune.

#### 22. The lost-answer probe needs our trust row; the `/meta` check is bounded

**Category**: Verification fix (Issues 6 and 8)

**What changed**: the probe confirms a re-pair only on a JSON object whose
`peerid` is this actor's id. `get_peer_info` gains a keyword `timeout`
(default unchanged); `_base_uri_serves` uses `META_CHECK_TRIES = 2` and
`META_CHECK_TIMEOUT = (3, 5)`.

**Files affected**:
- `actingweb/actor.py` - `_re_pair_probed`, `get_peer_info`,
  `_base_uri_serves`, the constants
- `tests/test_trust_re_pair.py` - the probe mocks carry `peerid`;
  `test_an_answer_that_is_not_our_trust_row_confirms_nothing` (three
  cases); `test_the_meta_check_is_two_short_tries`

**Rationale**: a proxy answering 200 split the initiator's pairing; one
unauthenticated request could hold a worker for about a minute.

#### 23. A replaced pending row is logged and documented

**Category**: Verification fix (Issue 7)

**What changed**: a WARNING when a verified request replaces a pending row,
naming both base URIs; the security reference says an honest peer whose
verification failed once is pending too, and can be displaced.

**Files affected**: `actingweb/actor.py` - `create_verified_trust`;
`docs/reference/security.rst`; `tests/test_trust_re_pair.py` -
`test_replacing_a_pending_row_is_logged`

**Rationale**: the displacement was silent and undocumented.

#### 24. The security reference names every re-pair case

**Category**: Verification fix (Issue 9)

**What changed**: "a re-pair when the request proves the row's current
secret, or when the row is verified or approved".

**Files affected**: `docs/reference/security.rst`

**Rationale**: it said "a verified row" only.

The CHANGELOG's SECURITY entry and the migration guide now state what holds
for the stored copy (every writer conditional, the restore, the 503 and the
resend, `store_permissions` reading the database and raising `DbError`),
and the ADDED entry the per-copy rebuild.

### 2026-11-08, after verification thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-3.md

Emm's suite on `dca966f` matched its `master` baseline on both backends
(recorded in that verification).

#### 25. Whether to audit: one whole-branch review, after this batch

**Category**: Decision (owner)

**What changed**: nothing in code. Evaluated whether the branch needs an
audit (owner's request): the issue counts per round went 11, 8, 9, 7, the
severities from takeovers to replica consistency, and the reviews since
`63bed00` saw only their own delta. Decision recorded under Decisions Made.

**Files affected**: this plan.

**Rationale**: delta reviews stopped converging on the permission-copy
path; a fresh read of the whole branch is cheaper than more rounds.

#### 26. The restore follows the stored copy, on every exit

**Category**: Verification fix (Issues 1 and 6)

**What changed**: `_still_granted(permissions, patterns)` keeps only
deleted patterns the final stored copy lists. The stored path filters by
`peer_perms`, the ignored-as-older path by the row read, and the 503 exit
(five lost races) re-reads the stored row and restores what it grants
before answering. A `DbError` from the write leaves the read row stored, so
the resend repeats the same revocation; nothing is restored there.

**Files affected**:
- `actingweb/handlers/callbacks.py` - `_still_granted`, the permission branch
- `tests/test_peer_binding.py` -
  `test_a_revocation_that_loses_to_another_revocation_restores_nothing`,
  `test_the_503_exit_restores_what_the_stored_copy_grants`

**Rationale**: the filter was the last diff, which re-fetched data a
winning revocation had also removed, resting on the granting peer's cache.

#### 27. The sync sender decides success by status

**Category**: Verification fix (Issue 2)

**What changed**: `_notify_peer` treats only a 2xx `last_response_code` as
delivered and logs anything else at WARNING with the status.

**Files affected**: `actingweb/trust_permissions.py`;
`tests/test_trust_permissions_unit.py` (the give-up test now answers `{}`
and expects the WARNING); `tests/test_peer_state_command.py` (the 204 test
sets the status).

**Rationale**: the receiver's 503 has no body, which the proxy returns as
`{}`, so the final failure was logged at DEBUG as delivered.

#### 28. A fault while the rebuild queries the peer is listed

**Category**: Verification fix (Issue 3)

**What changed**: `_rebuild_copy` wraps the query and the store in one
`except DbError`: `not rebuilt ... store fault`.

**Files affected**: `actingweb/maintenance/peer_state.py`;
`tests/test_peer_state_command.py` -
`test_a_fault_while_querying_the_peer_is_listed`

**Rationale**: the query's strict trust read could raise after the copy was
deleted, ending the command in a traceback.

#### 29. A query copy keeps the last callback's sender timestamp

**Category**: Verification fix (Issue 4)

**What changed**: `store_permissions` copies the stored row's
`sender_timestamp` into a copy that has none before the conditional write.

**Files affected**: `actingweb/peer_permissions.py`;
`actingweb/handlers/callbacks.py` (the ordering comment);
`tests/test_peer_binding.py` -
`test_a_query_copy_keeps_the_last_callbacks_timestamp`

**Rationale**: after a query write, an older callback (a resend after a
503) was accepted again.

#### 30. The replacement WARNING follows the write

**Category**: Verification fix (Issue 5)

**What changed**: logged once the conditional write won ("replaced its
pending row").

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_a_replacement_that_loses_is_not_logged_as_one`, the existing test's
wording

**Rationale**: a replacement that lost was logged as made.

#### 31. The 503's causes and the restore's limits are documented

**Category**: Verification fix (Issue 7)

**What changed**: CHANGELOG and migration guide name a storage fault as a
cause of the 503, say the restore is best effort and that a query copy keeps
the sender timestamp, and the sync sender's WARNING.

**Files affected**: `CHANGELOG.rst`, `docs/migration/v3.16.rst`

**Rationale**: they named lost races only, and the restore as certain.


### 2026-11-08, after verification thoughts/verifications/2026-11-08-peer-authorisation-fixes-reverify-4.md

The whole-branch review (iteration 25's decision): the security review found
nothing; the code review and the outside voice found the issues below.

#### 32. The `owner` rows bind to the path's peer

**Category**: Decision changed (owner); Verification fix (Issue 2)

**What changed**: `AuthResult.authorize` passes `peerid=path_peer`.
`_authorize_subscription_write` is a plain `authorize` (its once-per-process
"add two rows" WARNING could no longer fire for a peer and is removed). The
three `.subscriber` wire rows re-recorded: identical to their adopted
variants apart from the relationship name (`Wire-Phase:
peer-authorisation-fixes:2`, the rows' owner). Docs: the CHANGELOG entry
(no longer "Breaking"), the migration guide's step and item 18, both
access-control guides.

**Files affected**: `actingweb/handlers/base_handler.py`,
`actingweb/handlers/subscription.py`; `tests/test_peer_paths_binding.py`
(the method-rule tests now assert the owner row admits a peer's own PUT and
DELETE and refuses another peer's; the trust-permissions GET);
`tests/integration/wire/{WD6,WQ3,WC4}.subscriber.json`, `rows.toml`;
`CHANGELOG.rst`, `docs/migration/v3.16.rst`,
`docs/guides/access-control.rst`, `docs/guides/access-control-simple.rst`

**Rationale**: the `owner` rows were inert on every `authorize()` path,
which is why the method rule needed adoption rows at all.

#### 33. `FanOutManager` sends a large payload in full

**Category**: Decision (owner); Verification fix (Issue 4)

**What changed**: no low-granularity URL; the data is sent, with a WARNING
above the threshold. `_build_resource_url` removed. Docstrings of the
manager, `with_subscription_processing` and `SubscriptionProcessingConfig`.

**Files affected**: `actingweb/fanout.py`, `actingweb/interface/app.py`,
`actingweb/subscription_config.py`; `tests/test_fanout.py`
(`test_a_large_payload_is_sent_in_full`)

**Rationale**: a 3.16 subscriber never fetches the callback's URL, so every
redelivery failed and the peer's circuit opened.

#### 34. Creating the trust approves a peer's pending request

**Category**: Bug fix (Issue 1)

**What changed**: `create_reciprocal_trust` and its async twin, finding an
unapproved row for the peer at the stored base URI and relationship,
approve it through `modify_trust_and_notify` (`_approve_on_create`)
instead of re-pairing.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_creating_the_trust_approves_a_pending_request`

**Rationale**: the re-pair swapped the secret and left the row unapproved,
while the call returned as if it had succeeded; before 3.16 the upsert
approved it.

#### 35. The initiator's create is conditional; a failure removes only its own row

**Category**: Verification fix (Issue 3)

**What changed**: `only_if_absent=True` on both initiator creates;
`_drop_failed_attempt` deletes the row only while it holds this attempt's
secret.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_a_row_written_meanwhile_is_not_replaced`,
`test_a_refused_attempt_keeps_a_row_another_request_wrote`;
`tests/test_actor_logging_redaction.py` (its mocked `get` sequence)

**Rationale**: a request from the peer landing between the read and the
write was overwritten and then possibly deleted.

#### 36. An ignored revocation asks the peer; an untimed callback keeps the timestamp

**Category**: Verification fix (Issues 5 and 6)

**What changed**: a callback ignored as older that would revoke runs
`_reconcile_with_granting_peer` (a permission query; its revocations
deleted when `auto_delete_on_revocation`; stored; WARNING). A callback
without a timestamp carries the stored `sender_timestamp` forward.

**Files affected**: `actingweb/handlers/callbacks.py`;
`tests/test_peer_binding.py` - `test_an_ignored_revocation_asks_the_peer`,
`test_a_callback_without_a_timestamp_keeps_the_last_one`, the stale-update
test (the peer does not answer)

**Rationale**: sender instances with skewed clocks dropped a revocation
silently; an untimed callback erased the ordering.

#### 37. Smaller fixes from the whole-branch review

**Category**: Verification fix (Issues 7 to 15)

**What changed**:
- `prune --apply` exits 2 when a removed copy was not rebuilt (Issue 7;
  docstring, guide, CHANGELOG).
- The async re-pair POST catches `Exception` (Issue 8).
- `DELETE /callbacks/subscriptions/...` loads hook data from the row it
  deletes (`callback=True`) and says so (Issue 9).
- DynamoDB `modify` writes every attribute it is given (Issue 10).
- The security reference: approval applies to the current row (Issue 11);
  the heading "never replaces a verified or approved trust row" (Issue 13).
- PostgreSQL's upsert writes `created_at` as DynamoDB does (Issue 12).
- Type hints on `DbTrust.create`'s new keywords and `CallbacksHandler.post`
  (Issue 14).
- `_re_pair` takes `proven` from `post()` (Issue 15; the sync and async
  initiator twins stay, sharing their request and answer helpers).

**Files affected**: `actingweb/maintenance/peer_state.py`,
`actingweb/actor.py`, `actingweb/handlers/callbacks.py`,
`actingweb/handlers/trust.py`, `actingweb/db/dynamodb/trust.py`,
`actingweb/db/postgresql/trust.py`, `docs/reference/security.rst`,
`docs/guides/database-maintenance.rst`, `CHANGELOG.rst`;
`tests/test_peer_state_command.py` (exit 2),
`tests/test_trust_re_pair.py` - `test_the_async_re_pair_probes_after_any_send_error`,
`test_a_stale_handle_still_writes_what_it_is_given`,
`test_replacing_a_pending_row_renews_its_creation_time`

**Rationale**: the whole-branch review's remaining findings.

Emm's suite on `376b71c` (gate 2, environment 9, its adoption worktree
unchanged): PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54
passed, the `master` baseline's failures by name. The Full tier on
`376b71c`: DynamoDB 6063 passed, PostgreSQL 5860 passed, the docs build;
the three `.subscriber` recordings the only wire change.

### 2026-11-09, after verification thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-5.md

Two of iterations 32 to 37's fixes opened holes (reverify-5 Issues 1 and 2,
found by the security review, the code review and the outside voice); three
owner decisions (Decisions Made, iterations 38 to 40).

#### 38. Creating a trust replaces an unverified pending request

**Category**: Bug fix (security; reverify-5 Issues 1 and 5); Decision (owner)

**What changed**: `create_reciprocal_trust` and its async twin treat a row
neither verified nor approved (`_is_unproven_pending`) as a request nobody
proved: it is replaced by the owner's own request (`only_if_pending=True`,
the owner's secret, the normal creation request to the peer), whatever base
URI or relationship it claimed. Only a verified pending row is approved in
place (`_approve_on_create`), which records the peer in
`Actor.last_trust_approved_on_create`; `TrustManager.create_relationship`
(and async) then runs `trust_fully_approved_local` when the row ends approved
and peer-approved, as the approval PUT does.

**Files affected**: `actingweb/actor.py`,
`actingweb/interface/trust_manager.py`; `tests/test_trust_re_pair.py` -
`TestTheInitiatorAfterReverify5` (the replacement, sync and async; the
verified approval tells the peer; the hook, sync and async; no hook on a
plain creation)

**Rationale**: iteration 34 approved whatever pending row matched the URL,
so a stranger's failed request under a real peer's id, with the real base
URI, became that peer with the stranger's secret once the owner paired
with it. Bearer authentication never reads `verified`.

#### 39. The `owner` row admits no subscription creation; pulled diffs are filtered

**Category**: Bug fix (security; reverify-5 Issue 2); Decision (owner)

**What changed**: the built-in row is `("owner",
"subscriptions/<id>/<subid>", "GET,PUT,DELETE", "a")` (was `("owner",
"subscriptions", "", "a")`, which with iteration 32 admitted `POST
/subscriptions/<own id>` for every relationship). `GET
/subscriptions/<peer>/<subid>` and `/<seq>` pass a `properties` diff through
`_filter_subscription_data_by_permissions` (`_as_permitted`), as
`callback_subscription` does; nothing permitted reads as `{}`, the sequence
kept. A subtarget subscription's diff is the property's value itself (not an
object): it is returned only when the peer may read the subtarget
(`_may_read`); the first Full-tier run caught this (`test_033` of the
subscription flow read `{}` for `"change2"`). The orphaned refusal-log
comment is gone (Issue 11).

**Files affected**: `actingweb/config.py`, `actingweb/handlers/subscription.py`;
`tests/test_peer_paths_binding.py` - `TestAPeersOwnSubscriptionAfterReverify5`
(creation refused through the `owner` row; a narrowed grant pulls `{}`; a
subtarget's value pulled only when readable);
`CHANGELOG.rst` (CHANGED entry; a new one for the pull filter),
`docs/migration/v3.16.rst`, `docs/guides/access-control.rst`

**Rationale**: an `associate` limited to `public/*` could subscribe and poll
every property change. The pull filter also closes the same path for a
`friend` with a narrowed grant, which `master` already had.

#### 40. A peer's own base-URI move must name it on `/meta`

**Category**: Bug fix (security; reverify-5 Issue 3); Decision (owner)

**What changed**: the trust PUT handler, for a peer on its own row moving
its base URI (to a different one), runs `Actor._base_uri_serves` (two short
tries) and answers 400 when `/meta` does not name the peer.

**Files affected**: `actingweb/handlers/trust.py`;
`tests/test_peer_paths_binding.py` - `TestAPeersOwnTrustRowAfterReverify5`
(refused and accepted moves; with the built-in rows only, a description
admitted and an approval refused, Issue 13)

**Rationale**: the move kept `verified` and could point the actor's
authenticated traffic at any host.

#### 41. The reconcile deletes and stores in the callback's order

**Category**: Bug fix (reverify-5 Issue 4)

**What changed**: `_reconcile_with_granting_peer` deletes the revoked data,
then stores; a `DbError` propagates (the callback answers 503 and its resend
repeats); a peer that does not answer is logged; a store refused because a
newer copy won re-fetches what that copy still grants of the deleted data.
The ignored path restores against the copy the reconcile left. Docstring
says the fetch is synchronous.

**Files affected**: `actingweb/handlers/callbacks.py`;
`tests/test_peer_binding.py` - `TestTheReconcileAfterReverify5`

**Rationale**: a fault was swallowed into a 204 (revoked data kept) and a
concurrent newer grant lost its data with nothing logged.

#### 42. Smaller fixes from reverify-5

**Category**: Verification fix (Issues 6 to 10)

**What changed**:
- `_drop_failed_attempt` compares with the secret this attempt wrote (the
  `secret` argument) and keeps a row the peer approved (its answer lost);
  the read-then-delete window is documented (Issue 6).
- A JSON `false` for `approved` on the trust PUT no longer raises (Issue 7).
- DynamoDB `modify` restores the handle on any failed write (Issue 8).
- `FanOutManager` logs the size WARNING once per fan-out;
  `granularity_downgraded` documented as always False (Issue 9).
- `prune`'s rebuild counts a newer copy stored meanwhile as rebuilt
  (Issue 10).

**Files affected**: `actingweb/actor.py`, `actingweb/handlers/trust.py`,
`actingweb/db/dynamodb/trust.py`, `actingweb/fanout.py`,
`actingweb/maintenance/peer_state.py`; `tests/test_trust_re_pair.py` -
`test_a_failed_attempt_keeps_a_row_the_peer_approved`,
`test_a_failed_write_leaves_the_handle_as_it_was`;
`tests/test_fanout.py` - `test_the_size_warning_is_logged_once_per_fan_out`;
`tests/test_peer_state_command.py` -
`test_a_newer_copy_stored_meanwhile_counts_as_rebuilt`

**Rationale**: reverify-5's low findings.

#### 43. The changelog says what changed, exactly

**Category**: Verification fix (Issue 12)

**What changed**: the SECURITY entry's "as before" replaced by what
creating a trust now does (with a **Behavior change:** sentence) and the
base-URI move's check; the CHANGED entry names the new `owner` row; a new
CHANGED entry for the pull filter.

**Files affected**: `CHANGELOG.rst`

Every new test above failed with the library at `5cabc26` (14 of 21; the
other seven are controls or behaviour this iteration keeps).

The Full tier on `325370f`: DynamoDB 6086 passed, PostgreSQL 5883 passed,
lint, format and types clean, the docs build, no recording changed (the
three `.subscriber` rows included). Emm's suite on `325370f` (gate 2,
environment 9, its adoption worktree unchanged): PostgreSQL 2 failed / 7406
passed, DynamoDB 3 failed / 54 passed, the `master` baseline's failures by
name.

#### 44. Every create route approves with the same hooks

**Category**: Verification fix (follow-up to iteration 38)

**What changed**: the web form's create (`www.py`) goes through
`TrustManager.create_relationship`, so an approve-on-create there runs
`trust_fully_approved_local` too (it ran no hook before). `POST /trust` (sync
and async) skips `trust_initiated` when the create approved the peer's
waiting request (`Actor.last_trust_approved_on_create`): no request went
out. The changelog moves the pull filter to SECURITY (it closes a `friend`
case `master` had), says it filters by the path's peer whoever reads, and
that the `owner` row admits polling, not listing or creating.

**Files affected**: `actingweb/handlers/www.py`, `actingweb/handlers/trust.py`,
`actingweb/handlers/async_trust.py`, `CHANGELOG.rst`,
`docs/migration/v3.16.rst`; `tests/test_trust_re_pair.py` -
`TestTheCreateRoutesAfterReverify5` (both failed without the change)

**Rationale**: an approval through the web form ran no hook, and an app's
"request sent" handler ran for an approval.

The Full tier after iteration 44: DynamoDB 6088 passed, PostgreSQL 5885
passed, the docs build, no recording changed. Emm's suite last ran on
`325370f` (the baseline); iteration 44 changes only which hooks the trust
create routes run.


### 2026-11-09, after the audit thoughts/verifications/2026-11-09-peer-authorisation-fixes-audit.md

Scope (owner, Decisions Made): audit A1, A2, A3 with reverify-6 Issues 1 and
2, A9, and reverify-6 Issues 3 to 11; each fix checked against
`docs/protocol/actingweb-spec.rst`.

#### 45. An unapproved row is granted nothing by the permission evaluator

**Category**: Bug fix (security; audit A1, pre-existing on `master`)

**What changed**: `PermissionEvaluator._is_unapproved` reads the peer's
trust row; `evaluate_permission` (so every property, method, action, tool,
resource and prompt check), `evaluate_bulk_property_access` and
`get_allowed_items` answer DENIED (or nothing) for a row this actor has not
approved, before any grant is looked up. NOT_FOUND is not used, since
listings and the legacy fallback treat it permissively.

**Files affected**: `actingweb/permission_evaluator.py`;
`tests/test_peer_paths_binding.py` -
`TestAnUnapprovedRowGetsNothingAfterTheAudit` (an unapproved `friend` and
`admin` refused on properties GET/PUT/DELETE, methods and actions; the
evaluator denies every kind; an approved peer still reads; three failed
before)

**Rationale**: anyone can file a trust request with any relationship, and
its secret authenticates; the access table refused an unapproved row
(`Auth._match_access_row`) but the evaluator, which decides properties,
methods, actions and MCP, never read `approved`. Spec: an associate "MAY be
allowed ... unapproved" (~1949) is an option, not a requirement; the
library's default refuses unapproved access, now on both checks. MCP must
match REST (~1370), which the evaluator gate gives. The pure-function tests
in `tests/test_permission_pattern_matching.py` build the evaluator without a
config; their factory now sets `config = None` (the gate fails closed
without one).

#### 46. An approval lands only on a verified row, on every route

**Category**: Bug fix (security; audit A3 and reverify-6 Issue 1,
pre-existing on `master`)

**What changed**: `Trust.modify(approved=True)` writes with a new backend
condition `only_if_verified` (DynamoDB `Trust.verified == True`; PostgreSQL
`AND verified = true`), so no route approves a row whose secret an unproven
requester chose: the web UI's Approve, `PUT /trust/<rel>/<peer>` (owner,
trustee, admin peer), `TrustManager.approve_relationship(_async)`,
`modify_and_notify`, `modify_trust(**kwargs)`,
`Actor.modify_trust_and_notify(_async)`, `_approve_on_create` (its
read-then-approve race included). Before refusing,
`Actor.reverify_pending_trust` re-runs the verification: a GET to our own
row at the requester's base URI with the row's secret as bearer must answer
2xx with a row naming us (only a host holding that secret does), and the
base URI's `/meta` must name the peer; a pass marks the row verified
(conditioned on its secret). The requester's original `verify` token is not
stored, so the secret is the proof, as in the lost-answer probe.
`modify_trust_and_notify` refuses (False) and the PUT answers 403 "The trust
request is not verified; it cannot be approved".

**Files affected**: `actingweb/trust.py`, `actingweb/db/dynamodb/trust.py`,
`actingweb/db/postgresql/trust.py`, `actingweb/db/protocols.py`,
`actingweb/actor.py`, `actingweb/handlers/trust.py`;
`tests/test_trust_re_pair.py` - `TestIdentityAfterTheAudit`
(`test_every_approval_route_refuses_an_unverified_row`,
`test_a_request_that_verifies_on_a_second_check_is_approved`,
`test_a_meta_that_names_another_id_fails_the_second_check`)

**Rationale**: a stranger's failed request under Q's id, with Q's real base
URI, is shown as "Q wants to connect"; one approval made the stranger Q.
Spec: only automatic approval of an unverified request is forbidden
(~1603); refusing a manual one is a stricter local rule the spec allows
(verification is the requested actor's choice, ~1739). A peer that does not
support verification is paired by the owner creating the trust toward its
URL.

#### 47. A re-pair applies to a verified or approved row, conditioned on the bearer

**Category**: Bug fix (security; audit A2, introduced by the branch)

**What changed**: `TrustRelationshipHandler.post` re-pairs only a verified
or approved row; a pending row's holder goes to the creation path, which
replaces a pending row only with a request that verifies.
`Actor.replace_trust_secret` refuses a pending row and takes a keyword
`proven_secret` (the bearer the request authenticated with,
`auth_obj.token`): the swap is one write conditioned on the row still
holding it (`only_if_secret`), so a row replaced after the request
authenticated never takes the new secret.

**Files affected**: `actingweb/handlers/trust.py`, `actingweb/actor.py`;
`tests/test_trust_re_pair.py` -
`test_the_swap_is_conditioned_on_the_authenticating_secret`,
`test_a_pending_row_is_never_re_paired`,
`test_a_row_replaced_after_the_bearer_authenticated_keeps_its_secret`;
`test_a_squatter_cannot_promote_its_own_row` now expects the refusal

**Rationale**: the holder of a pending row counted as proven, and the swap
was conditioned only on the row existing, so a replacement landing between
authentication and the write (the owner's create, or the real peer's
verifying request under auto-accept) received the attacker's secret. Spec:
a re-pair is accepted "only as a re-pair from the requesting actor itself,
authenticated with the current shared secret" and otherwise 403 (~1595);
a pending row "MAY be replaced by a request that verifies" (~1602).

#### 48. The owner's create re-verifies a pending request before replacing it

**Category**: Bug fix (reverify-6 Issue 2)

**What changed**: `create_reciprocal_trust` (and async, through
`asyncio.to_thread`) runs `reverify_pending_trust` on an unverified pending
row first; one that verifies now is approved in place (the peer is told),
and only one that does not is replaced by the owner's own request.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_the_owners_create_approves_a_request_that_verifies_now`

**Rationale**: a genuine request whose first verification timed out was
replaced; the peer, holding its own approved row, refused the replacement
(403) and both sides were stranded.

#### 49. The revocation probe asks for our own trust row and decides by status

**Category**: Bug fix (audit A9; the probe pre-existing, the stranding
introduced by the branch)

**What changed**: `sync_peer` and `sync_peer_async`, when every
subscription to a peer answers 404, probe `trust/<relationship>/<our id>`
(`_own_trust_path`; `trust/<our id>` routed to the relationship handler,
whose GET answers 404 whatever the peer holds) and decide by
`proxy.last_response_code` (`_peer_trust_state`): 2xx keeps the trust and
cleans up the dead subscriptions; 401, 403 or 404 deletes it locally; no
answer or a server error keeps it ("unknown", logged; the next sync asks
again). A 404 with a JSON body no longer reads as a live trust.

**Files affected**: `actingweb/interface/subscription_manager.py`;
`tests/test_revoked_trust_detection.py` (the two revocation tests give the
proxy a status and assert the path; `test_an_unreachable_peer_keeps_the_trust`,
`test_a_json_refusal_is_not_read_as_a_live_trust`, five failed before);
`tests/test_subscription_manager_helpers.py` (the valid-trust case gives a
200)

**Rationale**: the probe could never succeed, so a subscriber deleted a live
trust whenever a peer deleted its subscriptions, and on this branch the pair
could not re-form (the peer's approved row refuses a bearer-less request).
Spec: a GET on the relationship URL, authenticated with the secret, reports
its status (~1666-1672).


#### 50. One filter for the pushed callback and the pulled diffs

**Category**: Bug fix (security; reverify-6 Issues 4 to 6, and audit A4,
which this closes with them)

**What changed**: `Actor.filter_subscription_blob(peerid, sub, blob)` is the
one filter; `callback_subscription` and the pull paths (`_as_permitted`)
call it. Only a `properties` subscription is filtered. A subscription to one
property sends its value whole when the peer may read `<subtarget>`
(`<subtarget>/<resource>` with a resource), the path a direct read checks,
else nothing (push) or `{}` (pull); a whole-target subscription's object is
filtered per key as before (`_filter_subscription_data_by_permissions`), and
a non-object value there fails closed. The pull's `{}` is kept for a diff
the peer may read none of: the library's subscriber merges it as a no-op and
its sequence advances (`apply_callback_data` iterates keys); the push sends
nothing, and the gap the subscriber then polls reads `{}`. `_may_read` is
gone. Audit A4 is removed from the second plan's todo.

**Files affected**: `actingweb/actor.py`, `actingweb/handlers/subscription.py`;
`tests/test_peer_paths_binding.py` - `TestOneFilterForPushAndPull` (a
resource checked on both paths, an object value under a subtarget follows
the property, a single value not pushed past an exclusion; three failed
before)

**Rationale**: the filter checked the subtarget but not the resource (a
peer excluded from `settings/private` subscribed with that resource and got
it), checked an object under a subtarget per key (an exact grant of
`settings` pulled `{}` where a direct read gives the object), and the push
passed a subtarget's non-object value unfiltered. Spec: callbacks carry
what the peer's permissions allow (permission-filtered subscriptions).

#### 51. A peer lists its own subscriptions again

**Category**: Bug fix (reverify-6 Issue 3; a regression against `master`)

**What changed**: the built-in rows gain
`("owner", "subscriptions/<id>", "GET", "a")` ahead of the
`<subid>` row: a peer lists its own subscriptions whatever its type, as on
`master`; another peer is refused by the path binding; POST stays with the
relationship's rows.

**Files affected**: `actingweb/config.py`; `tests/test_peer_paths_binding.py`
- `TestAPeerListsItsOwnSubscriptions` (one failed before)

**Rationale**: iteration 39's narrowed row did not match the listing, and
`master` admitted it through the old `owner` row.

#### 52. A reconcile store refused for another reason restores nothing

**Category**: Bug fix (reverify-6 Issue 7)

**What changed**: when `store_permissions` refuses the peer's answer,
`_reconcile_with_granting_peer` re-fetches what the stored copy grants only
if that copy is newer (`fetched_at`) than the answer; otherwise (the answer
did not validate, or every attempt lost) it logs that the revoked data
stays deleted.

**Files affected**: `actingweb/handlers/callbacks.py`;
`tests/test_peer_binding.py` - `test_a_refused_answer_restores_nothing`

**Rationale**: the old copy still granted the revoked patterns, so a
refused answer fetched back the data just deleted and logged that a newer
copy had won.

#### 53. A permission callback that fails answers 503

**Category**: Bug fix (reverify-6 Issue 8)

**What changed**: a non-`DbError` failure in the permission branch (a
failed deletion of revoked data, in the main path or the reconcile) answers
503 with `Retry-After: 1`, not 500: the sender resends only a 503, and the
permissions were not stored, so the resend sees the revocation again.

**Files affected**: `actingweb/handlers/callbacks.py`;
`tests/test_peer_binding.py` - `test_a_failed_deletion_answers_503_for_a_resend`

**Rationale**: a 500 left revoked data half deleted with the sender
treating the callback as final. Spec: the sender resends a 503 (the
callback section's resend guidance).

#### 54. The approval flag belongs to one call; the async hook runs off the loop

**Category**: Verification fix (reverify-6 Issues 9 to 11)

**What changed**:
- `Actor.last_trust_approved_on_create` is cleared at the start of each
  `create_reciprocal_trust(_async)`, whatever route calls it, so a stale
  value never reaches `TrustManager` (its own reset is gone).
- `TrustManager.create_relationship_async` runs the
  `trust_fully_approved_local` hook through `asyncio.to_thread`.
- The trustee path (`Actor.create_peer_trustee`) and the replacement of an
  unverified pending request run no hook; the hooks reference says so
  (Issues 9, 10), and the changelog no longer claims every create route.
- DynamoDB `modify`'s handle restore is one `except` (Issue 11, done with
  iteration 46). The pull's evaluation cost is one check per diff for a
  subscription to one property, one per key otherwise; the evaluator is a
  process singleton.

**Files affected**: `actingweb/actor.py`, `actingweb/interface/trust_manager.py`,
`docs/reference/hooks-reference.rst`, `CHANGELOG.rst`;
`tests/test_trust_re_pair.py` - `test_each_create_starts_with_the_flag_cleared`

**Rationale**: reverify-6's residue on the hook routing.

#### 55. Changelog, guides, security reference and spec for iterations 45 to 54

**Category**: Verification fix (documentation)

**What changed**:
- `CHANGELOG.rst`: a new first SECURITY entry (an unapproved row was
  granted its relationship's permissions); the trust entry's re-pair
  (verified or approved rows, conditioned on the bearer) and approval
  (verified only, on every route, after a second verification) sentences,
  and the owner's create re-verifying first; the 503 for any failed
  permission-callback handling; the push-and-pull filter entry rewritten
  (one filter, the resource, a single value); the `owner` rows on
  subscriptions (listing included); a FIXED entry for the revocation probe.
- `docs/migration/v3.16.rst`: unapproved peers get nothing, only verified
  requests are approved, the listing row, the create path.
- `docs/reference/security.rst`: a new item (pending rows granted nothing;
  approvals only on verified rows); the re-pair rule; the "check the base URI
  before approving" advice removed (it did not protect: a squatter names the
  real base URI).
- `docs/reference/hooks-reference.rst`: which approvals fire
  `trust_fully_approved_local`, `trust_approved` or neither; no
  `trust_deleted` for a replaced pending request.
- `docs/protocol/actingweb-spec.rst`: the re-pair applies to a verified or
  approved relationship and SHOULD be conditional on the authenticating
  secret; a pending one is not re-paired; B MAY refuse a manual approval of
  an unverified relationship after repeating the verification; until
  approval B SHOULD grant nothing beyond the relationship's own URL unless
  the type is one it allows unapproved (associate); a failed cleanup of
  revoked data is a reason for the 503.

**Files affected**: as listed.

**Rationale**: the owner's decision asks every fix to be checked against the
specification; the spec now states the rules the library enforces, within
what it already allowed (MAY/SHOULD, the associate option kept).

The Full tier on `d3fd713`: DynamoDB 6113 passed, PostgreSQL 5910 passed,
lint, format and types clean, the docs build, no recording changed. Emm's
suite on `d3fd713` (gate 2, environment 9, its adoption worktree unchanged):
PostgreSQL 2 failed / 7406 passed, DynamoDB 3 failed / 54 passed, the
`master` baseline's failures by name. Not yet exercised in a browser: the web
UI's Approve on an unverified request now answers 403 (for the next
verification's browser walk).

### 2026-11-09, after verification thoughts/verifications/2026-11-09-peer-authorisation-fixes-reverify-7.md

Scope (owner, 2026-11-09: "include all"): reverify-7 Issues 1 to 12 and the
note on non-`properties` targets, in this PR.

#### 56. A verification is answered only by a row its host approved

**Category**: Bug fix (security; reverify-7 Issue 1, introduced by the
branch in `a8007e5`)

**What changed**:
- `create_verified_trust` and `reverify_pending_trust` accept a peer's
  answer only when the answering row is approved there
  (`_answered_by_approved_row`, compared as text: a POST answer carries
  `"true"`, a GET `true`). An initiator creates its own row approved before
  it sends the request, on `master` too (`master:actingweb/actor.py:1709`,
  `:1838`), so released peers still pair.
- The trust GET no longer gives a pending row's own peer its
  `verification_token`; the status is still answered.

**Files affected**: `actingweb/actor.py`, `actingweb/handlers/trust.py`;
`tests/test_trust_re_pair.py` - `TestTheMirroredRequestAfterReverify7`.
- Two actors on one config, verifying each other through the real handlers:
  the mirrored request at B is neither verified nor approved, and A's second
  check and `modify_trust_and_notify` refuse the planted row. Both failed
  before, with B's row verified and A's second check passing.
- A pending row's own peer reads no token, while an approved row's peer
  still does.
- An unapproved answer does not verify a creation.

Four of the five failed before; the approved-row control passed.
`_peer_answers` now answers as an initiator's approved row.

**Rationale**:
- **The hole.** A pending row's own peer could read the row, token
  included (`a8007e5`). A third party filed a request at A under B's id,
  read A's token with its own secret, then filed a request at B under A's
  id with that token. Each side's verification read the row planted at the
  other side.
- **Effect.** It was reproduced live: B auto-accepted, and the third party
  read B's properties. Without auto-accept, one Approve click or the
  owner's create toward B did the same.
- **Spec.** The requested actor verifies by asking the requester for the
  relationship; the requester's side of a genuine request is its approved
  relationship (see iteration 68 for the spec text).

#### 57. A subscription to a property gets no resource an exclusion names

**Category**: Bug fix (security; reverify-7 Issue 2, introduced by
iteration 50; `master` filtered this case per key)

**What changed**:
- **The rule.** `filter_subscription_blob`, for a subscription with a
  subtarget and no resource, still sends a readable property's object
  whole. It now drops each key whose `<subtarget>/<key>` an exclusion names.
- **Why the shape matters.** A resource-level write reaches such a
  subscription as `{resource: value}` (`register_diffs`).
- **New evaluator method.** `PermissionEvaluator.excluded_property_paths`
  names the paths a `denied` or `excluded_patterns` entry matches. It is
  not the DENIED result, because a path the grant merely does not name is
  also DENIED.

**Files affected**: `actingweb/permission_evaluator.py`, `actingweb/actor.py`;
`tests/test_peer_paths_binding.py` -
`test_a_subtarget_subscription_gets_no_excluded_resource` (pull and push;
failed before with `{"private": "hidden"}` pulled)

**Rationale**:
- **The leak.** A friend excluded from `settings/private` subscribed to
  `settings` and received `settings/private`.
- **Why not filter on DENIED.** Dropping DENIED keys would undo reverify-6
  Issue 5: an exact grant of `settings` reads the whole object
  (`test_an_object_value_under_a_subtarget_follows_the_property`). Only an
  exclusion names a key the peer may not read under a property it may.
- **Scope.** The parent read beside it (`GET /properties/settings` returns
  the object whole) is the deferred A5.

#### 58. The whole-target filter evaluates a diff once

**Category**: Verification fix (reverify-7 Issue 11)

**What changed**: `_filter_subscription_data_by_permissions` makes one
`evaluate_bulk_property_access` call per diff, instead of one
`evaluate_property_access` per key. The approval and the grant are read
once, and the results are the same (both go through `_evaluate_rules`).

**Files affected**: `actingweb/actor.py`

**Rationale**: `_is_unapproved` added a trust read to each evaluation, so
an N-key diff cost about 2N reads per subscriber.

#### 59. An approval lands on the row read, and a failed write tells the peer nothing

**Category**: Bug fix (reverify-7 Issue 3)

**What changed**: `modify_trust_and_notify` conditions an approval write on
the secret of the row it read (`only_if_secret`). It returns False, with no
notification, when the write did not land: the row is gone, has been
replaced since, or is not verified.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_a_failed_approval_write_tells_the_peer_nothing` (failed before)

**Rationale**: the result of `dbtrust.modify` was never checked, so a
refused write still POSTed "approved" to the peer. A row replaced between
the read and the write was approved without the owner seeing it, while the
notification went to the old row's base URI.

#### 60. A repeated approval of an approved row changes nothing

**Category**: Bug fix (reverify-7 Issue 4; a behaviour change for rows
approved before 3.16 without a verification)

**What changed**:
- `only_if_verified` now accepts a row that is verified or already
  approved, on both backends (DynamoDB `verified == True | approved ==
  True`; PostgreSQL `(verified = true OR approved = true)`).
- `modify_trust_and_notify` and the PUT re-verify only a row that is not
  approved yet.

**Files affected**: `actingweb/db/dynamodb/trust.py`,
`actingweb/db/postgresql/trust.py`, `actingweb/db/protocols.py`,
`actingweb/trust.py`, `actingweb/actor.py`, `actingweb/handlers/trust.py`;
`tests/test_trust_re_pair.py` -
`test_an_approved_unverified_row_takes_a_repeated_approval` (failed before;
no probe, 204, the description written)

**Rationale**:
- **What broke.** An idempotent `{"approved": true, "desc": ...}` on such a
  row probed the peer, then answered 403, and the description change was
  lost.
- **Why this is safe.** Approving an approved row grants nothing new.

#### 61. A refused Approve says why, and the trust page does not offer it

**Category**: UX refinement (reverify-7 Issue 5)

**What changed**:
- **The refusal.** `TrustPeerHandler._refuse_unverified_approval` answers
  the 403 with a body that says why.
  - The web UI's Approve form (`_method=PUT`) gets a short page with a link
    back to `/www/trust`.
  - An API client gets `{"error": ...}`.
- **The trust page.** The library's template and the demo's mark a pending
  request as "unverified". They show a hint ("create the trust toward the
  peer's URL") instead of Approve. The demo's legend explains the badge.

**Files affected**: `actingweb/handlers/trust.py`,
`actingweb/templates/aw-actor-www-trust.html`,
`examples/demo/templates/aw-actor-www-trust.html`;
`tests/test_trust_re_pair.py` - `test_the_refusal_says_why` (failed
before)

**Rationale**: the browser walk found a blank 403 page with no way back,
and an Approve button that always fails.

**Browser walk** (gstack browse, demo in local QA mode on `:5055`,
throwaway actors deleted afterwards):
- **The trust page.** The planted unverified request shows Pending and
  Unverified (red), a legend entry, no Approve control, and the hint
  "Cannot approve: pair from your side". The hint is shortened and wraps,
  so it and Delete are readable at 1280 px and 375 px; the first version
  was cut off.
- **The old Approve URL, followed from the app.** It answers 403 with the
  explanation and a working link back. The page is unstyled (low,
  accepted).
- **The same URL pasted into the address bar.** It meets the cross-site
  guard first ("Cross-site request refused"), as designed for a
  state-changing GET.
- **By API.** The PUT answers 403 with the JSON `error`, and a pending
  row's own peer reads its row without `verification_token`.

#### 62. `TrustManager.modify_trust` repeats the verification before approving

**Category**: Bug fix (reverify-7 Issue 6)

**What changed**: `modify_trust(approved=True)` runs `reverify_pending_trust`
on a row that is neither approved nor verified, as every other approval
route does, so the security reference's list is now true.

**Files affected**: `actingweb/interface/trust_manager.py`;
`tests/test_trust_re_pair.py` - `test_modify_trust_repeats_the_verification`
(failed before)

**Rationale**: it refused silently, with no second check. The docs said it
repeated the verification.

#### 63. The owner's create re-verifies only a request it would approve

**Category**: Bug fix (reverify-7 Issue 7)

**What changed**: both twins of `create_reciprocal_trust` run the second
check only when the pending request has the create's relationship and URL
(`_re_pair_refusal` is empty). Any other pending request is replaced by the
owner's request, as before iteration 48.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`test_another_relationship_replaces_the_request_unprobed` (failed before)

**Rationale**: a request that verified on the second check took the
re-pair branch, which refused a different relationship or URL, so the
owner's create failed (408) where it used to replace the request.

#### 64. The approving PUT answers 404 for a missing row and 400 for a move with an approval

**Category**: Bug fix (reverify-7 Issue 8)

**What changed**: `TrustPeerHandler.put` reads the row first.
- A missing row answers 404, not 403 "not verified".
- An approval of a pending row that also changes the base URI answers 400
  ("Approve and change the base URI in two requests"). The second check
  asks the stored base URI.

**Files affected**: `actingweb/handlers/trust.py`;
`tests/test_trust_re_pair.py` -
`test_a_missing_row_is_404_and_a_move_with_an_approval_400` (failed before)

**Rationale**: a client could not tell a deleted row from an unverified
one, and an approval with a move was checked against the old host.

#### 65. A peer with no trust row is granted nothing

**Category**: Bug fix (reverify-7 Issue 9)

**What changed**: `_is_unapproved` also answers True when the peer has no
trust row, so a permission override that a faulted delete left behind
grants nothing.

**Files affected**: `actingweb/permission_evaluator.py`;
`tests/test_trust_re_pair.py` - `test_a_peer_with_no_trust_row_gets_nothing`
(failed before); `tests/test_db_fault_permissions.py` (its evaluator test
stubs the gate: its subject is the store fault, not the row)

**Rationale**: "no row" counted as approved, and the override was read
before the trust row.

#### 66. The second verification is bounded in total

**Category**: Bug fix (reverify-7 Issue 10)

**What changed**: `reverify_pending_trust` reads its answer through
`_bounded_get_json`:
- no redirect is followed;
- at most 64 KB is read, within 15 s in all;
- a larger or slower answer does not verify.

**Files affected**: `actingweb/actor.py`; `tests/test_trust_re_pair.py` -
`TestTheSecondCheckIsBounded` (failed before: no `allow_redirects`); the
fakes in `_reverse_answers` and the mirror test give `iter_content`

**Rationale**: the base URI is the requester's choice. `requests` followed
redirects, and its read timeout is per read, so a trickling host held the
owner's PUT or create.

#### 67. The probe, the 503 and the reconcile residue: decided and documented

**Category**: Decision changed (reverify-7 Issue 12, and its note on
non-`properties` targets)

**What changed**: no code. The changelog now states the three accepted
behaviours, and Decisions Made records them with the target decision:
- **The revocation probe.** It reads a gateway's 401, 403 or 404 as a
  revocation. It runs only after every subscription to the peer answered
  404, and it is narrower than `master`, which read any error as revoked.
- **The 503 on a failed permission callback.** It is also answered for a
  failure that would repeat. The resend is bounded at two, and a resend of
  an already stored copy is refused as not newer.
- **The reconcile.** It reads a copy without `fetched_at` (written before
  3.16) as not newer, so it restores nothing.

**Files affected**: `CHANGELOG.rst`; this plan (Decisions Made)

**Rationale**:
- Telling a gateway's 404 from the peer's own needs a second probe and a
  wait in `sync_peer`; deleting is what the peer's real 404 means.
- A deterministic failure costs two extra requests.
- Every 3.16 writer stamps `fetched_at`.

#### 68. Spec, changelog, security reference and migration guide for iterations 56 to 67

**Category**: Verification fix (documentation; reverify-7 Issues 1 and 6)

**What changed**:
- **`docs/protocol/actingweb-spec.rst`**:
  - the relationship that answers a verification is the requester's own,
    approved relationship (the spec's step 1, "200 OK");
  - A MUST NOT return the verification token from a relationship it has
    not approved, and B MUST NOT accept a verification answered by one;
  - the pending row's status read excludes the token;
  - the sentence about the requester's secret is corrected.
- **`CHANGELOG.rst`**:
  - the trust entry: verification by an approved relationship, no token for
    a pending row's peer, the bounded second check, re-approval of an
    approved row, the 403 bodies and the trust page, the 404 and 400, an
    approval landing on the row it was decided for;
  - the SECURITY entry: a peer with no trust row;
  - the filter entry: exclusions under a subtarget.
- **`docs/reference/security.rst`**: the false "only a host holding that
  secret answers" replaced, and the mirror and missing-row cases added.
- **`docs/migration/v3.16.rst`**: the same, plus the create path's
  relationship and URL condition.

**Files affected**: as listed.

**Rationale**: reverify-7 found the guarantee these pages claimed false
(Issue 1), and the security reference's list wrong (Issue 6). The spec
already asked the requester's verification URL to answer 200 OK, which is
its approved relationship. The rule is stated now, within the spec's own
step 1.

The Full tier on the code of iterations 56 to 68:
- DynamoDB: 6127 passed;
- PostgreSQL: 5924 passed;
- ruff, format and pyright are clean;
- `verify_groups` OK, the docs build, and no wire recording changed.

The template-only change after that run (iteration 61's hint and badge)
re-ran the web and trust unit tests: 566 passed.

Not yet run: Emm's suite on this iteration. Iteration 56 changes what a
verification accepts, so it gates the PR.
