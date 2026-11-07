---
status: proposed
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
five-dimension review of the redraft is recorded under "Third review" and
folded where mechanical. Approval is the owner's.

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
  are not peer callers and are unaffected; an `admin` peer is exempt. Every
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
  The owner's `approved`, the stored relationship, base URI, description and
  grants are kept; a failed verification answers 403 and changes nothing.
- **Every unauthenticated callback request answers 401**, and **generic
  `/callbacks/<name>` admits any authenticated caller** (owner, 2026-11-07):
  the empty-role row becomes an `any` row.
- [New 2026-11-07] **The library's own hook names are reserved on the
  generic callback branch** (owner): `permissions`, `subscription`,
  `subscriptions`, `www` and any `resource_*` name answer 404 there, so
  those hooks only receive data the library built.
- [Updated 2026-11-07] **A callback's fetch URL is built from the stored
  base URI** (owner): `<baseuri>/subscriptions/<own id>/<subid>/<sequence>`,
  as the resync and the acknowledgement already do. The body's `url` is
  never fetched.
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
  rightful sender (second review).
- [New 2026-11-07] **An operator command removes state written before the
  fix** (owner), dry run by default.
- [Updated 2026-11-07] **The wire apps are shaped like the consumer's off
  Lambda**: processing with automatic storage, peer capabilities,
  permissions and profiles, and **synchronous callbacks off**. With them on,
  the consumer's import flow deadlocks (the loop blocks in the resync
  callback while the subscriber fetches the publisher's baseline), and a
  REST write's callbacks block whatever the flag says (the handler runs in
  the executor). Two topologies.

Deduced; confirm at approval:

- **A permission callback whose `timestamp` is more than five minutes in
  the future answers 400.** Today it would outrank every genuine callback in
  the process (`peer_permissions.py:259-268`); bounding it is the second
  review's Phase 1 proposal and no sender produces one.
- **The operator command scans actors like `actingweb-verify-orphans`** and
  never rebuilds a replica unless asked: a rebuild deletes the bucket before
  the baseline fetch, and a fetch that fails leaves it empty until the next
  resync.

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
  type, `subscriber_adopted`, so both variants run in one session.
- `tests/integration/test_wire_peer_paths.py` (new) - the rows below.
- `tests/integration/wire/` - one file per row, and `rows.toml`: what each
  records and which phase or plan is expected to change it.
- `.github/workflows/tests.yml` - a step of the `tests` job, inside the
  `changes` gate, after the main step: `pytest tests/integration -m wire -p
  no:rerunfailures`; the main step deselects `-m "not wire"`. Same
  environment, junit and coverage handling as the main step.
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
only adds patterns (spike note, "Findings beyond the questions").

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

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time, both backends
- [ ] `poetry run pytest tests/integration -m wire -p no:rerunfailures` passes
      five times in a row on each backend, sequentially, and once under
      `make test-all-parallel`
- [ ] `git show --stat HEAD -- actingweb examples` is empty
- [ ] Each recording is read against the research notes' "as read" sections
      and every difference is in "Recorded outcomes"

### Recorded outcomes

Filled by the first recording.

### Implementation Status: Not Started

---

## Phase 1: one peer binding, and `/callbacks` requires the peer it names

### Changes

- `actingweb/auth.py` - `check_authorisation(..., *, path_peer: str | None
  = None)`: after a row matches, when `path_peer` is set and
  `self.acl["peerid"]` is non-empty, return False unless the two are equal
  or the caller's relationship is `admin`. The existing `peerid` argument
  and the `owner` match are unchanged.
- `actingweb/handlers/base_handler.py:373-395` - `authorize(method, path,
  subpath, *, path_peer=None)` passes it through.
- `actingweb/handlers/callbacks.py`
  - `post()`: authenticate with `add_response=True` on every branch; an
    unauthenticated request answers 401 with a challenge.
  - Permission branch: `path_peer=<peer>`; a `timestamp` more than five
    minutes ahead of now answers 400.
  - Subscription branch: `path_peer=<peer>`, checked before the subscription
    lookup, so a caller that is not the peer cannot tell a real subscription
    id from an unknown one.
  - Subscription branch, `type`: absent or `diff` or `resync`; anything else
    400, before the processor.
  - Low-granularity fetch (`:600-628`): the URL is
    `<trust baseuri>/subscriptions/<own id>/<subid>/<sequence>`; the body's
    `url` is not read for the fetch (it is still passed to legacy hooks).
  - `delete()`: `path_peer=<peer>`.
  - Generic branch: names `permissions`, `subscription`, `subscriptions`,
    `www` and `resource_*` answer 404; the rest run the hook as today for an
    authenticated caller.
- `actingweb/interface/subscription_manager.py:524-528`
  (`get_callback_subscription`) - returns only a row with `callback` true,
  on both backends (the backends do not filter on the flag,
  `db/dynamodb/subscription.py:69-73`, `db/postgresql/subscription.py:59-66`).
  Not used by the callback DELETE.
- `actingweb/config.py:286-289` - `("", "callbacks", "", "a")` becomes
  `("any", "callbacks", "", "a")`; the `owner` row above it stays (harmless,
  and an application may depend on its order).
- Docstrings in `callbacks.py` and `auth.py`.

### Wire rows

The Phase 0 recordings are byte-identical after this commit, both
topologies, both backends. The URL rule changes nothing in `WD6` and `WD12`:
the stored base URI and the publisher's own root produce the same URL on the
wire apps.

New rows, recorded with the fix in place. C is a third actor with an
approved `friend` trust to B; `S` a peer of the consumer's `subscriber` type:

| Row | Request to B | Recorded |
| --- | --- | --- |
| WA1 | No credentials: a subscription callback for a real subscription, and for an unknown id | 401 for both; nothing applied |
| WA2 | No credentials: a permission callback for a peer with a trust, and for one without | 401; nothing stored, no hook |
| WA3 | No credentials: `GET`, `POST`, `DELETE` on `/callbacks/<name>` | 401 with a challenge |
| WA4 | A bearer that is nobody's, on the three paths | 403 (unchanged) |
| WA5 | C, and S, post a subscription callback and a permission callback under A's id | 403; nothing applied |
| WA6 | B's creator posts either | 403 |
| WA7 | A peer whose trust is not approved posts a callback | 403 |
| WA8 | A low-granularity callback with A's bearer whose body `url` names another host | B fetches from A's stored base URI; the other host receives nothing |
| WA9 | `DELETE /<B>/callbacks/subscriptions/<A>/<subid>` by C and by B's creator | 403; the subscription remains |
| WA10 | To A, by B with its bearer, under the id of B's own subscription at A | 404; nothing in A's replica store for B |
| WA11 | A peer's `POST` to a generic path a hook handles, to one no hook handles, and to each reserved name | The hook's answer; today's answer for the unhandled one; 404 for each reserved name, no hook run |
| WA15 | A's bearer: a subscription callback with `type` `permission`, and with an unknown type | 400; nothing applied, sequence unchanged |

### New Tests, both unit and integration tests

- Before the handler changes, on the tree as it is: the scenarios of `WA1`
  to `WA15` run once and their output goes into the verification document.
  No recording of it is committed.
- Unit, `check_authorisation` with `path_peer`: a peer equal to it passes; a
  different peer fails whatever row matched, including an application row
  inserted at index 0 and a row without `<id>`; creator and trustee pass; an
  `admin` peer passes; without `path_peer` behaviour is unchanged (the
  existing auth tests pass untouched).
- Unit, real storage, each callback branch: unauthenticated 401 and nothing
  stored, deleted or run; another peer 403; the creator 403; an unapproved
  peer 403; the peer itself 204 for high and low granularity, a resync and a
  permission callback.
- The low-granularity fetch goes to the stored base URI whatever the body's
  `url` says; the HTTP client is patched to fail the test on any other host.
- A subscriber posting to its publisher under its own subscription id, both
  backends: 404, nothing stored.
- A permission callback with a future `timestamp`: 400, nothing stored.
- Reserved names on the generic branch: 404, no hook called; an ordinary
  name with a hook: the hook runs.
- Integration, both backends, both topologies: the wire rows.
- Existing tests that pin today's behaviour and change:
  `tests/test_callback_in_progress_answer.py:41-45`,
  `tests/test_permissions_handler.py:150-167`, `:182-214`; each is updated
  in this commit with a line in the verification saying why.

### Failure Scenarios

- A peer on an older library sends an unauthenticated callback - none does;
  every sender has sent the bearer since callbacks existed
  (`actor.py:2683`, `trust_permissions.py:386-388`); the Phase 0 rows staying
  identical is the check.
- A publisher that moved sends a low-granularity callback - the fetch goes to
  the stored base URI and fails there; the callback answers 503 as any failed
  fetch does today and the subscriber retries; the owner updates the base
  URI. Logged with the remedy.
- An application that pointed a third party at `/callbacks/<name>` - it
  received 200 and nothing ran; it now receives 401. Changelog.
- An application whose own hook is named like a reserved name - it was
  reachable only with forged data; 404 now. Changelog.
- A call site that names a peer but forgets `path_peer` - the unit test per
  handler and the `WA` rows catch it; Phase 2 adds the rest of the sites.
- The publisher-row rule refuses a legitimate callback - a subscriber's row
  for its own subscription always has the flag (`WC1`, `WC2`).

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time
- [ ] `grep -n '("", "callbacks"' actingweb/config.py` returns nothing
- [ ] `git show --stat HEAD -- tests/integration/wire` shows `WA1` to `WA11`
      and `WA15` added and no other recording changed
- [ ] The verification document holds the pre-fix run for each row

### Implementation Status: Not Started

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
  sub-handlers (`:1169`, `:1237`) pass `path_peer=<peerid>`. An application
  row such as the consumer's `("trust/<type>/<id>", "GET")` then admits a
  peer to its own row only.
- `actingweb/interface/authenticated_views.py:691-705` - a peer or client
  view lists only its own trust's subscriptions; owner mode unchanged.
- `docs/sdk/authenticated-views.rst` - what a view lists.

### Wire rows

Byte-identical: every Phase 0 row except the three `.subscriber` rows, and
`WA1` to `WA15`. Re-recorded in this commit, with the diff read and written
into the verification: `WD6.subscriber` (B's acknowledgement 403, the diff
stays queued), `WQ3.subscriber` (each clear 403, the queue unchanged),
`WC4.subscriber` (A's delete to B 403, B keeps its callback subscription).
The `.subscriber_adopted` rows stay identical.

New rows:

| Row | Request to A | Recorded |
| --- | --- | --- |
| WA12 | C: `GET /subscriptions/<B>`, and `GET`, `PUT`, `DELETE` and the diff `GET` on `…/<B>/<subid>` | 403 each; nothing listed, cleared, consumed or deleted |
| WA13 | C: `POST /subscriptions/<B>` | 403, as before |
| WA14 | `GET /permissions/<B>` by B for each built-in type and `subscriber`, by C, by A's creator, by an admin peer, for an unknown id | B reads its own for every type; C 403; creator and admin 200; the unknown id the same 403 |
| WA16 | S (`subscriber` type): `GET /trust/subscriber/<B>` on A | 403; its own row 200 |

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
- Trust: a peer of an application type with a `trust/<type>/<id>` GET row
  reads its own row and not another's.
- View filter: two peers' subscriptions; a peer view and a client view each
  see their own; a client view with no trust sees nothing.

### Failure Scenarios

- An application whose peers clear or delete through a GET-only row (the
  consumer) - the clear, the acknowledgement and the publisher's delete fail
  with 403 and a WARNING, the queue grows and a dangling callback
  subscription stays. **Behavior change** with the two rows to add, in the
  changelog and the migration guide; the `.subscriber` re-recordings show it
  and the `.subscriber_adopted` rows show the remedy.
- An application that used a `friend` peer to administer other peers'
  subscriptions - refused. Changelog.
- An admin peer reading every trust row's secret - unchanged (exempt by
  decision); the security reference says so.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit
- [ ] `git show --stat HEAD -- tests/integration/wire` shows `WA12` to
      `WA14`, `WA16` added, the three `.subscriber` files changed, and
      nothing else
- [ ] The verification document holds the pre-fix runs and the read diff of
      the three `.subscriber` files

### Implementation Status: Not Started

---

## Phase 3: a trust-creation request cannot replace an existing row

### Changes

- `actingweb/actor.py:1913-2005` (`create_verified_trust`) - when a row for
  the peer id exists: verify with a GET to `<stored baseuri>/trust/<stored
  relationship>/<own id>` carrying the request's `secret` as bearer, and
  compare the request's `verify` with the returned `verification_token`, as
  today but against the stored base URI. On a match:
  `Trust.modify(secret=<new>, verification_token=<fresh>, verified=True,
  peer_approved=True)` and nothing else; the answer is the row as stored
  (201 when approved, 202 otherwise, as today). On anything else: return
  False, row untouched, and the handler answers 403 as for any refused
  creation. A row that does not exist is created as today.
- `actingweb/trust.py:391-482` (`Trust.create`) - no longer reached for an
  existing peer id from this path; its same-secret refusal stays.
- `actingweb/handlers/trust.py:370-495` - unchanged apart from the log line
  naming a refused replacement (actor, peer id; never the base URI from the
  body).

### Wire rows

Phases 0 to 2 recordings are byte-identical. New, two hosts:

| Row | Steps | Recorded |
| --- | --- | --- |
| WT1 | B re-initiates its trust to A (the library's `create_relationship`, as the consumer does), then A writes | A's row keeps `approved` and relationship; the next callback carries the new secret; the replica updates |
| WT2 | A creation request for B's id naming another base URI | 403; A's row unchanged; the verification request goes to B's stored base URI and the named host receives nothing |
| WT3 | A creation request for a new peer id | As today (201 or 202) |

### New Tests, both unit and integration tests

- Before the change: `WT1` and `WT2` run once on the tree as it is (expected
  from reading: the row overwritten, `approved` reset), output into the
  verification document.
- Unit, both backends: replacement with a verifying peer swaps the secret
  and token and keeps `approved`, relationship, base URI, description,
  `created_at` and the grants; with a non-verifying peer (unreachable,
  wrong token, non-JSON) 403 and every field unchanged; the same secret
  again 403 as today.
- The consumer's re-pair: `create_reciprocal_trust` against an existing
  approved row succeeds and leaves both rows approved.

### Failure Scenarios

- A peer that genuinely moved re-initiates from its new address - refused;
  the owner deletes the trust and the peer pairs again. Migration guide.
- A peer unreachable at the moment of re-initiation - refused, row kept; the
  initiator deletes its own new row on the 403 (`actor.py:1751-1775`) and
  retries later.
- An initiator that relied on a re-POST to reset approval - none found in the
  library or the consumer.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit
- [ ] `git show --stat HEAD -- tests/integration/wire` shows `WT1` to `WT3`
      added and nothing else

### Implementation Status: Not Started

---

## Phase 4: an operator command for state written before the fix

### Changes

- `actingweb/maintenance/peer_state.py` (new) and the script entry
  `actingweb-peer-state = "actingweb.maintenance.peer_state:main"` - same
  environment as the application; `report` (default) and `prune --apply`.
  Per actor (all actors, or `--actor <id>`):
  - `_peer_permissions` rows whose peer id has no trust row;
  - `_callback_state` `state:` and `pending:` rows whose `<peer>:<subid>` has
    no callback subscription;
  - `remote:<peer>` buckets whose peer has no trust row;
  - with `--rebuild-replicas` and `--apply` only: for each subscription, the
    replica is replaced by a fresh baseline fetch (keys absent from the
    baseline are removed).
  Prints one line per item and a total; exits 1 when `report` finds any.
- `docs/guides/database-maintenance.rst` - a section for the command.

### Wire rows

Unchanged; the command is not on the wire.

### New Tests, both unit and integration tests

- Unit, both backends: each kind of stale row is reported and, with
  `--apply`, removed; a row that belongs to a live trust or subscription is
  kept; `report` changes nothing; `--rebuild-replicas` without `--apply` is
  refused.
- Integration: after a pair is set up and a stale permission row and a stale
  pending row are planted through the library, `prune --apply` removes them
  and the pair's next callback is applied as before.

### Failure Scenarios

- A stale-looking row that is in use - only rows with no trust or no
  subscription qualify; both are read strictly (a read fault stops the
  command with a non-zero exit, never prunes on a guess).
- A replica rebuild whose fetch fails - the old replica is kept (the fetch
  happens before anything is deleted) and the item is reported as failed.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit

### Implementation Status: Not Started

---

## Phase 5: changelog, documentation and records

### Changes

- `CHANGELOG.rst`, `Unreleased`, `SECURITY` (each claim checked against the
  pre-fix runs in the verification document):
  - Unauthenticated callbacks were accepted; the trust's secret could be
    sent to a URL from the request. **Behavior change:** callbacks are
    authenticated, the peer paths require the peer they name, the fetch URL
    is built from the stored base URI, only `diff` and `resync` are accepted
    on the subscription path, and the library's hook names are reserved on
    the generic branch. **Check:** third parties pointed at `/callbacks/<name>`
    now receive 401.
  - A peer could reach another peer's permissions, subscriptions and trust
    row through any row that admitted it, application rows included.
    **Behavior change:** one rule binds a peer to its own.
  - **Breaking:** a PUT or DELETE is no longer admitted by a GET row.
    **Check:** an application type with `("subscriptions/<id>/<subid>",
    "GET")` and no PUT and DELETE rows (the pattern the access-control guide
    shows) adds them, or its subscribers' queue clears and the publisher's
    unsubscribe fail quietly.
  - A trust-creation request could replace an existing trust row, resetting
    its approval. **Behavior change:** it verifies against the stored base
    URI and swaps credentials only; a moved peer is re-paired by deleting the
    trust.
  - A subscriber could post to its publisher under its own subscription id.
  - Peer and client views listed every peer's subscriptions.
- `CHANGELOG.rst`, `ADDED` - `actingweb-peer-state`.
- `docs/migration/v3.16.rst` - a "Start here" item and a section "Peer paths
  are bound to their peer": the method rule and the two rows, the
  replacement rule and the re-pair remedy, the command, the 401s.
- `docs/protocol/actingweb-spec.rst:1153-1159` (the contradictory callback
  rule), `:2036-2042` (true after Phase 2), `:1747-1751` (who updates a
  row), `:1568-1574` (replacement) - aligned.
- `docs/guides/access-control.rst`, `access-control-simple.rst` - how rows
  match (first match, prefix, the method), the peer binding, and the
  subscriber example gains PUT and DELETE rows.
- `docs/guides/trust-relationships.rst:108-113` and
  `docs/guides/p2p-quickstart.rst:44-49` - the pending-trust contradiction.
- `docs/reference/security.rst`, `docs/reference/routing-overview.rst:36`,
  `docs/reference/hooks-reference.rst:46-53`, `README.rst:255-256` -
  callbacks are authenticated; reserved names.
- `examples/demo/shared_hooks/app/callback_hooks.py` and the demo README -
  the webhook examples need an authenticated caller until the opt-in.
- `thoughts/research/2026-11-07-emm-suite-against-master.md` is a snapshot
  and stays; the Emm adoption items (the two rows; a re-pair from a new
  address needs a delete) go into this plan's verification document and
  Emm's inbound note when the PR opens.
- `thoughts/plans/2026-11-06-spec-1-5.md` - a dated Update Log line: T6 is
  replaced by Phase 3 here.

### New Tests, both unit and integration tests

- None beyond the docs build in the full tier.

### Failure Scenarios

- The access-control guide's example still shows a GET-only subscriber -
  the grep below.

### Verification

- [ ] Run the contract's `### Checks` full tier verbatim (docs build included)
- [ ] `grep -rn '"subscriptions/<id>/<subid>", "GET"' docs` shows each
      example with PUT and DELETE rows beside it
- [ ] Emm's suite on this branch, as `thoughts/todo/emm-suite-against-master.md`
      describes, with the two rows added on Emm's adoption branch: no failure
      the `master` run did not have; the result in the verification document

### Implementation Status: Not Started

---

## Evaluation Notes

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
