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

## Overview

An unauthenticated caller can post a permission callback for any peer id and
have it stored, and with a subscription id can inject diffs and have a trust's
secret sent to a URL it chooses. A peer can read another peer's permissions,
and a `friend` peer can read, clear and delete another peer's subscriptions.
The first was confirmed by running the handler; all four exist in the released
library. This plan closes them. Before it changes a handler it records, as
Phase 0, the legitimate flows that run over the same paths (a subscriber
polling and clearing its own queue, fetching a low-granularity diff,
unsubscribing; a publisher sending callbacks and resyncs), so the fix is shown
to leave them byte-identical. It lands first of the six 3.16 plans of this
date.

## Implementation Order

The order of the six 3.16 plans, what depends on what between them and the
gates between them are kept in one place: `thoughts/todo/INDEX.md`, "Planned
for 3.16: order, dependencies and gates". One PR per plan, one commit per
phase, phases in the order written. What this plan uses from the others is
below.

**Readiness, 2026-11-06.** Not ready to approve as written. A full review
on this date (three evaluators and the outside voice, in the Evaluation Notes
under "Second review") found that the identity Phases 1 and 2 bind a caller
to, the trust row, can be replaced, redirected and deleted by a request with
no credentials, and that an application's own access rows defeat the
permission fix. None of it is folded into the phases. The plan needs a
research pass on trust replacement and the access table, five owner
decisions, and another draft. The redraft follows the baseline plan's spike
(owner, 2026-11-07): Phase 0 below is rewritten from the harness the spike
built, not from the design on paper here.

**This plan: first.** It needs nothing merged. It needs the baseline plan's
spike done, because Phase 0 lands the harness the spike builds. What follows
it: the baseline plan records every other flow on that harness; the
`subs_list` plan's `get_subscriptions_by_peer()` is delegated on the
authenticated view and inherits the filter added here; the `ListAttribute`
plan's receiver changes assume an authenticated peer on the subscription
callback path; the specification plan adds an opt-in for anonymous
third-party webhooks on top of the 401 added here and writes the rules into
the specification.

## Decisions Made

- **Security first**, ahead of the other plans (owner, 2026-11-06).
- **The wire harness is built by the baseline plan's spike, and Phase 0
  here lands it** (owner, 2026-11-07). The spike runs before this plan is
  redrafted and answers what reading could not: whether a callback nests
  inside its write, whether a recording is identical across runs and
  backends, how large one is and how long a run takes. Phase 0 stays this
  PR's test-only first commit; what it lands is the spike's harness, and the
  fourteen rows are recorded on it. The design below is replaced at the
  redraft by what the spike built.
- **The fix ships with 3.16; there is no 3.15.x backport** (owner,
  2026-11-06). Released versions stay open until the 3.16 tag: the consumer
  pins `=3.15.1`, `master` is 97 commits past `v3.15.1` with breaking
  changes, and the publish workflow accepts tags on `master` only
  (`.github/workflows/publish-to-pypi.yml:36-41`). Merging this PR publishes
  the description and the fix ahead of the release; accepted.
- **The baseline is its own plan, after this one** (owner, 2026-11-06). This
  PR records only the flows it must leave unchanged, and its access tests are
  written with the fix, in their secured form. No test in it passes because a
  hole is open.
- **Recordings, not hand-written expectations** (owner, 2026-11-06), for the
  wire rows here as in the baseline plan.
- **The peer is bound by a handler rule on the subscription paths**, not by
  opening the `owner` row: a caller authenticated as a peer must be the peer
  in the path, whatever its relationship type. Passing the peer id into the
  access check and deleting the `friend` row would be tidier, but it would let
  every approved relationship type create and manage subscriptions, where
  today only `friend` and the types an application grants can. Which types
  may subscribe stays where it is. (Deduced; confirm at approval.)
- **Every unauthenticated callback request answers 401.** The generic branch
  answers 200 with an empty body today and runs nothing; 401 says so, and is
  what the specification requires. (Deduced; confirm at approval.)
- **A callback's `url` is fetched only under the peer's stored base URI.** The
  receiver sends the trust's secret with that request.
- **The permission query is for the peer itself, the creator and admin.**
- **A subscription callback is accepted only for a subscription this actor
  made** (a row with `callback` true). Found by the 2026-11-06 review; read,
  not run. (Deduced; confirm at approval.)
- **The wire apps are shaped like the consumer's**: subscription processing
  with automatic storage, peer capabilities, peer permissions, peer profiles
  and synchronous callbacks, as `../actingweb_mcp/application.py:547-583`
  configures them, in both topologies it has (publisher and subscriber on one
  host, `:567-571`, and on two). (Deduced; confirm at approval.)

## What We're NOT Doing

- **The full baseline** - `thoughts/plans/2026-11-06-subscription-wire-baseline.md`,
  next. Phase 0 here records fourteen flows, chosen because they run over the
  handlers Phases 1 and 2 change.
- **Recording an exposure another plan closes** - `WD9` (an unfiltered
  stored diff reaching a replica through a gap resync) is the baseline
  plan's; the `ListAttribute` plan closes it.
- **Recording the holes as passing tests** - decided above. That each hole is
  open today is shown once, by the unit tests of Phases 1 and 2 failing on
  the tree before the fix, and written into the verification.
- **An opt-in for anonymous third-party webhooks** - a feature, with a design
  (a keyword on the hook registration); the specification plan carries it. The
  demo's three documented webhooks do not run anonymously today either.
- **Default deny, the 409 on a repeated trust request, reserved relationship
  names** - specification plan; each has a design in it.
- **Letting every relationship type subscribe** - see Decisions.
- **Rate limiting on `/callbacks`** - none exists anywhere in the library; a
  deployment's edge has it.
- **Rotating trust secrets that may have been sent to an attacker's URL** -
  cannot be known from the library; the changelog says who is exposed
  (deployments that received low-granularity callbacks on a reachable
  endpoint) and that deleting and re-establishing the trust rotates it.

## What Already Exists

- `actingweb/auth.py:270-290` - a peer bearer sets `acl["peerid"]`, `approved`
  and the relationship; the handler rule compares against it.
- `actingweb/auth.py:786-812` - the `owner` rule and the `any` role, which
  already requires an authenticated caller (`:787-788`).
- `actingweb/handlers/base_handler.py:164-260` - `_authenticate_dual_context`
  with `add_response=True` answers 401 with a challenge.
- `actingweb/handlers/trust.py:1276-1282` (`TrustSharedPropertiesHandler`) -
  an existing handler that compares the bearer's peer with the path's; the
  same shape.
- `actingweb/handlers/subscription.py:235-244` - the per-peer POST already
  refuses a peer id that is not the caller's.
- `tests/_adoption_helpers.py` (`create_core_actor`, `make_config`),
  `tests/test_db_fault_callers.py:314-330` - the recipe for driving
  `CallbacksHandler` with an `AWWebObj`; the scratch test that confirmed the
  finding becomes the first regression test.
- `tests/integration/test_subscription_flow.py`, `test_trust_flow.py` and the
  `trust_helper` fixture (`tests/integration/conftest.py:827`) - two peers
  with real trusts over HTTP.
- `tests/integration/test_harness.py:23-153` (`create_test_app`) - every test
  app is built here and runs as a uvicorn thread of the pytest process, so a
  module-level recorder is readable from a test. Each worker has ten ports
  and uses six (`conftest.py:201-205`, `:223`, `:907`).
- `tests/integration/conftest.py:910-976` (`subscriber_app`) - the one app
  with subscription processing today; the shape the wire apps extend.
- `actingweb/interface/integrations/fastapi_integration.py:634-667`,
  `:2737-2755` - a synchronous handler runs in the executor, so a REST write
  has no running loop and its callbacks are sent before it answers
  (`actor.py:2781-2793`).
- `thoughts/research/2026-11-06-subscription-wire-baseline.md` - what the
  existing suite proves, and what each flow does today as read.

## Phase 0: the wire harness, and the flows this fix must not change

Test-only. No file under `actingweb/` changes. Row identifiers are shared
with the baseline plan, which adds the rest.

**Superseded in part, 2026-11-07.** The harness this phase describes is built
by the baseline plan's spike before this plan is redrafted (owner). The
options, files and recorder below are the design the spike starts from; the
redraft replaces them with what the spike built and keeps the fourteen rows.

### Changes

- `tests/integration/test_harness.py` - `create_test_app` gains keyword-only
  options, all off by default so the six existing apps are unchanged:
  `sync_callbacks`, `peer_capabilities`, `peer_permissions`, `peer_profile`
  and `record`. With `record`:
  - a pure ASGI middleware, added after `integrate_fastapi` so it is
    outermost, appends one entry per request to a module-level list: method,
    path and query, who the credentials belong to (never the secret), the
    JSON body, the status, the JSON response and the `Location`,
    `Content-Type`, `WWW-Authenticate` and `Retry-After` headers. A request
    that started while another was open is recorded inside it; an exception
    is recorded as a 500;
  - recording hooks (`subscription_data_hook("properties")`, the
    `subscription_deleted` and `trust_deleted` lifecycle hooks, the
    `permissions` callback hook) append what they were called with to the
    same list.
- `tests/integration/conftest.py` - session fixtures `wire_app` (base port
  5561) and `wire_peer_app` (5562), both with processing (`auto_sequence`,
  `auto_storage`, `auto_cleanup`, a 2-second gap timeout, `max_pending` 5)
  and all the options on. A `wire_pair` factory creates a publisher A and a
  subscriber B (and a third actor C on request) with approved `friend`
  trusts, a grant and a subscription at a given level and granularity, in a
  given topology (`same_host`: all on `wire_app`; `two_hosts`: A on
  `wire_app`, the others on `wire_peer_app`). Its teardown deletes the
  actors through the library by id, removes their suspension rows, and fails
  if a row of theirs is left.
- `tests/integration/_wire.py` (new, not a test file) - the scenario driver.
  A scenario is a list of steps (an HTTP request, or an SDK call through an
  `ActorInterface` built from the wire app's own configuration, for what has
  no route). After each step it snapshots A's queue, B's replica (scalars
  and lists through `RemotePeerStore`), B's callback state, both actors'
  subscription rows and A's suspension rows. The normaliser replaces actor
  ids, subscription ids, hosts, secrets and timestamps with names, keeps
  sequence numbers, and fails if a secret, an id or a port survives. The
  result is compared with the row's file; a mismatch fails with a diff.
  `WIRE_RECORD=1` rewrites the file and is refused when `CI` is set.
- `tests/integration/wire/` (new) - one JSON file per row and variant, and
  `rows.toml`: for each row what it records, any second file for a backend
  or a topology with the reason, and which plan is expected to change it.
- `tests/integration/test_wire_baseline.py` (new) - the fourteen rows below.
- `tests/integration/pytest.ini`, `pyproject.toml:207-215`,
  `.github/workflows/tests.yml` - a `wire` marker; the main test step
  deselects it and a second step runs it with `-p no:rerunfailures`, so a
  recording that holds one run in three is not retried into green
  (`tests.yml:265-269`).
- `tests/integration/verify_groups.py`, `XDIST_GROUPS.md` - the new group;
  every scenario has a recording and every recording a scenario.

The rows. Granularity `high`, a grant of `*`, a target-level subscription
and both topologies unless stated; "SDK" is a step in the test process:

| Row | Steps | Runs over |
| --- | --- | --- |
| WS1.target | `PUT /properties/<p>` with an object, a string and a number | The subscription callback |
| WL11.target | SDK: `append`, `insert` at the front and in the middle, an update by index, `update_where`, a delete by index, `pop()`, `pop(0)`, `remove_where`, `extend`, `clear`, `delete`, `set_description` | The subscription callback, with list diffs |
| WD6 | Granularity `low`: a write | The callback; B's fetch of `…/<subid>/<seq>` with its bearer; B's `PUT {"sequence": n}` |
| WD8 | The recorded callback of an SDK `append`, posted again with the bearer | The callback, as a duplicate |
| WD10 | SDK `suspend("properties")`; two writes and a delete; `resume` | The resync callback and B's baseline fetch |
| WD12 | The same, with A's trust row for B lacking `subscriptionresync` and freshly stamped (through the library), B already holding a list | The fallback: a full state as a low-granularity callback, fetched by B |
| WQ1 | `GET /subscriptions/<B>/<subid>` as B after two writes | The queue |
| WQ2 | `GET …/<subid>/<seq>` as B, twice | One diff, consumed |
| WQ3 | `PUT …/<subid>` as B with `{"sequence": 1}`, `{"sequence": 0}`, no sequence, text, and on an unknown id | Clearing |
| WC1 | `POST /<B>/subscriptions` as B's creator | B creating its subscription at A |
| WC2 | `POST /<A>/subscriptions/<B>` with B's bearer | The same, called directly |
| WC3 | `DELETE /<B>/subscriptions/<A>/<subid>` as B's creator | B's `DELETE /<A>/callbacks/subscriptions/<B>/<subid>` to A |
| WC4 | `DELETE /<A>/subscriptions/<B>/<subid>` as A's creator | A's `DELETE /<B>/subscriptions/<A>/<subid>` to B |
| WP1 | `PUT /<A>/trust/friend/<B>/permissions` | The permission callback, and B's follow-up fetch |

### New Tests, both unit and integration tests

- The fourteen rows, integration, both backends, both topologies.
- The recorder: a callback posted to a wire app is recorded once, nested in
  the request that caused it, with the status the caller received and
  without the secret; a handler exception is recorded as a 500.
- The normaliser: a recording made twice with different actors is
  byte-identical; a planted secret, actor id or port fails the comparison.
- The driver refuses `WIRE_RECORD` when `CI` is set.

### Failure Scenarios

- A recording differs between the backends or the topologies - a second file
  with a reason in the registry when the reason is understood (the
  permission and capability stores are rebuilt per application,
  `actingweb/peer_permissions.py:423`, so the second host never has a warm
  cache); otherwise the phase stops and reports it.
- A recording is not repeatable - order is recorded as nesting, never as
  times, and no row here waits on a clock. The rows pass five consecutive
  runs before the commit and never rerun in CI.
- The recorder changes what it observes - it is on the two wire apps only,
  it tees the body without consuming it, and its own test compares the
  recorded status with the caller's.
- A synchronous callback to the publisher's own host waits for itself - the
  REST handler runs in the executor, so the loop is free; every row here
  runs in `same_host`.
- A recording shows something this plan's premise contradicts - written into
  "Recorded outcomes" and the phases below are corrected before Phase 1
  starts. This is the one place a recording gates this plan; nothing here
  waits on another plan.
- An SDK step runs under the wrong configuration and sends a secret to the
  default host - the driver takes its `Config` from the wire app, and the
  normaliser fails on any host that is not a wire app.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time, both backends
- [ ] `poetry run pytest tests/integration -m wire -p no:rerunfailures` passes
      five times in a row on each backend, sequentially
- [ ] `git show --stat HEAD -- actingweb examples` is empty
- [ ] Each recording is read against
      `thoughts/research/2026-11-06-subscription-wire-baseline.md`, "Today's
      behaviour, as read", and every difference is in "Recorded outcomes"

### Recorded outcomes

Filled by the first recording.

### Implementation Status: Not Started

---

## Phase 1: `/callbacks` requires the peer it names

### Changes

- `actingweb/handlers/callbacks.py`
  - `post()` (`:176-184`): authenticate with `add_response=True`; an
    unauthenticated request answers 401 on every callback path.
  - A helper `_is_path_peer(check, peer_id) -> bool`: the caller is
    authenticated as a peer, `check.acl["peerid"] == peer_id`, and the trust is
    approved.
  - Permission branch (`:187-205`): 403 unless `_is_path_peer`. The comment at
    `:183-184` goes.
  - Subscription branch (`:340-366`): 403 unless `_is_path_peer`, checked
    before the subscription lookup so an unknown subscription id is not told
    apart from a wrong peer for a caller that is not the peer.
  - Subscription branch, after the lookup: 404 unless the row is one this
    actor made as subscriber (`callback` true). The lookup asks for such a
    row (`interface/subscription_manager.py:524-528`) but the backend does
    not filter on the flag (`db/dynamodb/subscription.py:69-73`), so today a
    subscriber can post "diffs" to its publisher under its own subscription
    id and have them stored in the publisher's replica store for it.
  - `delete()` (`:78-100`): the same rule in place of the access-table check.
  - Low-granularity fetch (`:600-628`): refuse a `url` that does not start
    with the trust's `baseuri` (normalised, trailing slash); answer 400 and
    log at WARNING with the actor and peer, without the URL's query string.
  - `get()` (`:33-56`): `add_response=True`.
- `actingweb/config.py:286-289` - the empty-role row
  `("", "callbacks", "", "a")` becomes `("any", "callbacks", "", "a")` (an
  authenticated caller of any kind, for application callback hooks); the
  `owner` row above it goes (the handler rule replaces it).
- `actingweb/handlers/callbacks.py` docstrings and
  `docs/reference/security.rst` - callbacks are authenticated.

### Wire rows

The fourteen recordings of Phase 0 are byte-identical after this commit, in
both topologies and on both backends. A changed file among them is a
regression, not a recording to refresh: the library's own senders
authenticate, a subscriber's delete reaches its publisher as the peer the
path names (`WC3`), and a low-granularity `url` is under the publisher's base
URI (`WD6`, `WD12`).

New rows, recorded in this commit with the fix in place. C is a third actor
with an approved `friend` trust to B:

| Row | Request to B | Recorded |
| --- | --- | --- |
| WA1 | No credentials: a high-granularity subscription callback for a real subscription, and for an unknown id | 401 for both; nothing applied |
| WA2 | No credentials: a permission callback for a peer with a trust, and for one without | 401; nothing stored, no hook |
| WA3 | No credentials: `GET`, `POST`, `DELETE` on `/callbacks/<name>` | 401 with a challenge |
| WA4 | A bearer that is nobody's, on the three paths | 401 |
| WA5 | C posts a subscription callback and a permission callback under A's id | 403; nothing applied |
| WA6 | B's creator posts either | 403 |
| WA7 | A peer whose trust is not approved posts a callback | 403 |
| WA8 | A subscription callback with A's bearer whose `url` is a recording server outside A's base URI | 400; the server receives nothing |
| WA9 | `DELETE /<B>/callbacks/subscriptions/<A>/<subid>` by C and by B's creator | 403; the subscription remains |
| WA10 | To A, by B with its bearer: a callback under the id of B's own subscription at A | 404; nothing in A's replica store for B |
| WA11 | A peer's `POST` to a generic callback path a hook handles, and to one no hook handles | The hook's answer; and what the unhandled case answers today (read: 200 with `false`), which the specification plan changes |

### New Tests, both unit and integration tests

- Before the handler changes, on the tree as it is: the unit tests below and
  the scenarios of `WA1` to `WA10` are run once and their output kept in the
  phase notes. That run is the proof each hole is open (expected, from
  reading: 204 and applied for `WA1`, `WA2`, `WA4`, `WA5`, `WA6` and `WA10`;
  the secret received for `WA8`; the subscription deleted for `WA9`). No
  recording of it is committed.
- Unit, real storage: an unauthenticated POST to
  `/callbacks/permissions/<peer>`, with and without a trust relationship,
  answers 401, stores nothing, deletes nothing and runs no hook. (Fails
  today: 204 and stored.)
- The same for `/callbacks/subscriptions/<peer>/<subid>` with a real
  subscription: 401, no diff applied, no fetch.
- A peer authenticated with its own secret posting a permission callback and
  a subscription callback under ANOTHER peer's id: 403, nothing stored.
- The creator (basic auth) posting either: 403.
- A peer with an unapproved trust: 403 (as today, `auth.py:751-761`).
- A bearer that matches no trust: 401, nothing applied. (Fails today: the
  authentication result is never looked at, `handlers/callbacks.py:178-205`.)
- A subscriber posting a callback to its publisher under its own
  subscription id, on both backends: 404, nothing stored. (Fails today on
  DynamoDB; PostgreSQL as the run shows.)
- The peer itself: 204 as before, for high and low granularity, a resync and
  a permission callback (the existing flows).
- A low-granularity callback whose `url` is outside the peer's base URI: 400,
  and no request leaves the process (the HTTP client is patched to fail the
  test if called). One whose `url` is under it: fetched as before.
- `DELETE /callbacks/subscriptions/<peer>/<subid>` by another peer and by the
  creator: 403, the subscription remains; by the peer: as before.
- Unauthenticated `GET`, `POST`, `DELETE` on a generic callback path: 401
  with a challenge. An authenticated caller on a generic path with a hook: the
  hook runs, as before.
- Integration, both backends, both topologies: the wire rows above. The
  fourteen unchanged recordings replace the "existing flows still pass" this
  plan first relied on: before Phase 0 no integration test sent a permission
  callback, a resync or a low-granularity callback between two actors.

### Failure Scenarios

- A peer running an older library version sends an unauthenticated callback -
  none does: every sender in the library has sent the bearer since callbacks
  existed (`actor.py:2683`, `trust_permissions.py:386-388`). Covered by the
  fourteen recordings staying identical.
- A publisher whose base URI changed (a moved deployment) sends a
  low-granularity callback with its new host - refused with 400 until the
  trust's base URI is updated; logged with the remedy. The alternative is
  sending the secret to any host.
- An application that pointed a third party at `/callbacks/<name>` - it
  received 200 and nothing ran; it now receives 401. Named in the changelog.
- The `any` row matching the two peer branches - the handler rule decides
  there, before and regardless of the table. Covered by the creator and
  other-peer tests.
- The base URI a subscriber stored differs in form from the `url` its
  publisher builds (a trailing slash, the scheme's case, a default port) -
  both are normalised before the prefix test; `WD6` and `WD12` staying
  identical in both topologies is the check, and a unit test covers each
  form.
- The publisher-row rule refuses a legitimate callback - a subscriber's row
  for its own subscription always has the flag (`WC1`, `WC2` record both
  rows); every callback in the fourteen recordings is to such a row.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time
- [ ] `grep -n '("", "callbacks"' actingweb/config.py` returns nothing
- [ ] `git show --stat HEAD -- tests/integration/wire` shows `WA1` to `WA11`
      added and no other recording changed
- [ ] The phase notes hold the pre-fix run's output for each hole

### Implementation Status: Not Started

---

## Phase 2: `/permissions` and `/subscriptions` for the peer they name

### Changes

- `actingweb/handlers/permissions.py:55-91` - authorise first, then look up
  the trust. Allowed: a peer whose id is `<peer>` (any relationship type,
  approved), the creator, and an admin peer. Everyone else 403, whether or
  not the relationship exists.
- `actingweb/config.py:316-319` - the four role rows become
  `("owner", "permissions/<id>", "GET", "a")`,
  `("creator", "permissions", "GET", "a")` and
  `("admin", "permissions/<id>", "GET", "a")`.
- `actingweb/handlers/subscription.py` - in the per-peer handlers (GET
  `:134-200`, POST `:199-291`, the subscription GET `:300-372`, PUT
  `:374-430`, DELETE `:432-500`, the single-diff GET `:540-598`), after the
  existing access check: a caller authenticated as a peer whose id is not the
  `<peerid>` in the URL gets 403. Creator and trustee are unchanged.
- `actingweb/interface/authenticated_views.py:691-705` - for a peer or client
  view, `all_subscriptions`, `outbound_subscriptions` and
  `inbound_subscriptions` return only rows whose `peer_id` is the peer id of
  the view's trust: `auth_context.peer_id` for a peer view, the `peerid` of
  `auth_context.trust_relationship` for a client view, and nothing when a
  client view has no trust. Owner mode is unchanged.
- `docs/sdk/authenticated-views.rst` - what a view lists.

### Wire rows

The fourteen recordings of Phase 0 and `WA1` to `WA11` are byte-identical
after this commit. `WQ1` to `WQ3`, `WD6` and `WC4` are the ones this
rule sits on: a subscriber polling, clearing and fetching its own
subscription, and a publisher's delete reaching the subscriber as the peer
the path names.

New rows, recorded in this commit. C is a third actor with an approved
`friend` trust to A:

| Row | Request to A | Recorded |
| --- | --- | --- |
| WA12 | C: `GET /subscriptions/<B>`, and `GET`, `PUT`, `DELETE` and the diff `GET` on `…/<B>/<subid>` | 403 each; nothing listed, cleared, consumed or deleted |
| WA13 | C: `POST /subscriptions/<B>` | 403, as before the fix (`handlers/subscription.py:235-244`) |
| WA14 | `GET /permissions/<B>` by B for each built-in relationship type and a custom one, by C, by A's creator, by an admin peer, and for an id with no relationship | B reads its own for every type; C 403; the creator and the admin peer 200; the unknown id the same 403 as another peer's |

### New Tests, both unit and integration tests

- Before the handler changes: the scenarios of `WA12` and `WA14` run once on
  the tree as it is, output kept in the phase notes (expected, from reading:
  C succeeds on all five requests; C reads B's permissions; the creator and
  a `viewer` peer are refused their own).
- Permission query: a peer reads its own for each built-in relationship type
  and for a custom type with no row of its own; a peer of each type is
  refused another peer's with 403; the creator reads any; an admin peer reads
  any; a caller asking about a peer id with no relationship gets the same 403
  as one asking about another peer's (no enumeration); a pending peer gets
  403.
- Subscriptions, integration, both backends, two peers with `friend` trusts
  and one with a custom type that has a subscriptions row: each of GET, POST,
  PUT, DELETE and the diff GET on the other peer's path answers 403 and
  changes nothing; on its own path each works as before; the creator still
  reads and manages both.
- [Updated 2026-11-06] No new unit test for a peer creating a subscription
  under another peer's id: the handler refuses it today
  (`handlers/subscription.py:235-244`), and `WA13` records that.
- View: with subscriptions for two peers, a peer view and a client view built
  with `as_client(<client id>, trust)` each return only their own trust's
  rows from the three properties; a client view with no trust returns
  nothing; owner mode returns everything.

### Failure Scenarios

- An application that used a `friend` peer as an administrator of other
  peers' subscriptions - refused. No library or consumer code does; named in
  the changelog.
- A client view filtered on the client id - would hide the client's own
  subscriptions, because rows carry the trust's peer id; the filter uses the
  trust. Covered.
- A relationship type that could read its own permissions only through a
  role row an application added - the `owner` row now covers every type.
  Covered by the custom-type test.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time
- [ ] `git show --stat HEAD -- tests/integration/wire` shows `WA12` to `WA14`
      added and no other recording changed
- [ ] The phase notes hold the pre-fix run's output for each hole

### Implementation Status: Not Started

---

## Phase 3: changelog, documentation and records

### Changes

- `CHANGELOG.rst`, `Unreleased`, `SECURITY`:
  - An unauthenticated request could post a subscription or permission
    callback. Cause, what it allowed (stored permissions for any peer id,
    deletion of replicated data with `auto_delete_on_revocation`, diffs
    injected with a subscription id, and the trust's secret sent to a URL
    from the request). **Behavior change:** every callback request is
    authenticated, and the two peer paths require the peer they name.
    **Check:** third-party systems pointed at `/callbacks/<name>` (they
    received 200 and nothing ran; they now receive 401); a trust whose
    callbacks were reachable from outside can be rotated by deleting and
    re-establishing it.
  - A low-granularity callback's `url` was fetched with the trust's secret
    wherever it pointed. **Behavior change:** only under the peer's base URI.
  - Any approved peer of four relationship types could read another peer's
    permissions, and other types could not read their own.
  - A peer with a `friend` relationship could read, clear and delete another
    peer's subscriptions; any authenticated caller could delete an outbound
    subscription through the callback path. **Behavior change:** a peer
    reaches only its own.
  - A subscriber could post a callback to its publisher under its own
    subscription id and have it stored as replicated data.
  - Each entry claims only what the pre-fix runs of Phases 1 and 2 showed;
    the wording is checked against the phase notes.
  - A peer or client view listed every peer's subscriptions.
- `docs/migration/v3.16.rst` - an item under "Start here" and a short section
  "Callbacks and peer paths are authenticated": the four changes and their
  checks.
- `docs/reference/security.rst` - callbacks; the peer rule.
- `docs/guides/subscriptions.rst` - one sentence where callbacks are
  described: they carry the trust's bearer and are refused without it.
- `examples/demo/shared_hooks/app/callback_hooks.py:47`, `:106-107`, `:161`
  and the demo README - the webhook examples say they need an authenticated
  caller until the opt-in exists.
- `thoughts/todo/INDEX.md` - nothing to remove; this plan closes no todo.
- `thoughts/research/2026-11-06-peer-authorisation-fixes.md` - a dated
  correction line wherever the pre-fix runs differ from what it traced.

### New Tests, both unit and integration tests

- None beyond the docs build in the full tier.

### Failure Scenarios

- The demo's README still promising anonymous webhooks - the grep below.

### Verification

- [ ] Run the contract's `### Checks` full tier verbatim (docs build included)
- [ ] `grep -rn -i "without auth\|unauthenticated" examples/demo docs/guides/subscriptions.rst`
      shows no promise of an anonymous callback
- [ ] Emm's suite on this branch, before the PR opens, run as
      `thoughts/todo/emm-suite-against-master.md` describes: no failure the
      run on `master` did not have, and the result recorded in this plan's
      verification document

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
