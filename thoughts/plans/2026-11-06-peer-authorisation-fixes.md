---
status: active
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

- [ ] Run the contract's `### Checks` full tier verbatim (docs build included)
- [ ] `grep -rln '"subscriptions/<id>/<subid>", "DELETE"' docs/guides/access-control.rst docs/guides/access-control-simple.rst`
      lists both files
- [ ] Emm's suite on this branch, as `thoughts/todo/emm-suite-against-master.md`
      describes, with the two rows added on Emm's adoption branch: no failure
      the `master` run did not have; also checked: a re-pair that answers 201
      does not create a second subscription (`../actingweb_mcp/api/trust.py:286-298`);
      the result in the verification document

### Implementation Status: Not Started

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
