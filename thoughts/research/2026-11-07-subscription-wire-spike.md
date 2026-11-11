# Research: the wire harness, built and run (the baseline plan's spike)

**Date:** 2026-11-07
**Branch:** docs/3-16-rollup-records (this note); the harness is on
`spike/subscription-wire-harness` at `c7f4329`, one commit on `master`
(`5a7e07f`), local only
**Library under test:** `master` at `5a7e07f`

The spike `thoughts/plans/2026-11-06-subscription-wire-baseline.md` asks
for (owner, 2026-11-07): build the recorder and two consumer-shaped apps,
record a handful of rows on both backends, repeat the runs until it is known
whether a recording is identical, write this note. Everything here was run.
The redraft of the baseline plan and of the security plan's Phase 0 is
written from it; the three owner decisions the baseline plan lists (full
transcripts or a projection; two tiers; retire or tighten the legacy files)
are taken on it.

## Research Questions

The baseline plan, "Only a spike answers" (its line 619):

1. Does a same-host callback nest inside the write that caused it?
2. Does a target-level row match across backends without a second file?
3. How large is a recording, and how long does one wire run take?
4. Does a resume on the server's loop emit a capability fetch at an
   unpredictable time?
5. Can the teardown pass on both backends?

And the determinism list from its second review: callback order and array
order by random ids, hash-seed order in the permission follow-up fetches,
the gap timeout racing other rows, timestamp normalisation versus `WD2` and
`WD3`, attribution by nesting, teardown against the tombstone.

## Summary

The harness works and the recordings hold: four rows (five files), one file
per row for **both** backends, byte-identical over five runs on DynamoDB and
five on PostgreSQL, under `-n auto` beside other files as well. A wire run
of the five costs 7 s on either backend, 3 s of it one row's gap wait; a
recording is 8 to 13 KB as a full transcript. The teardown passes on both
backends through the library, given two things the design did not have:
suspension rows are removed explicitly, and the tombstone is accepted (one
per actor, 30-day TTL, in the test prefix the session drops).

Two of the plan's premises are wrong and change rows. A grant on a `friend`
trust can only add patterns (`friend` already grants `*`), so "B may read
`allowed` only" needs an `excluded_patterns` grant, not a narrower one. And
the consumer's data hook never sees what arrives through a gap resync: the
resync's handler writes the replica and calls no hook.

The one nondeterminism found is the one the plan asked about: with A's
capability cache for B cold, a resume on the loop schedules a background
refresh that races the resync callback, and the recording's nesting flipped
in 2 of 5 runs. Warming the cache in the pair's setup (as a mutual consumer
pair would have it) removed it; 9 of 9 runs since.

A cross-backend file needs two things from the normaliser: timestamp tokens
carry their format class only, not identity (DynamoDB stamps every diff
with the module-import time; PostgreSQL per row), and object keys are
sorted (jsonb returns them sorted, DynamoDB in insertion order). With
identity kept, every row differs per backend and in nothing else. That is
the owner's first decision, with evidence either way.

## What was built

On `spike/subscription-wire-harness` at `c7f4329` (test-only; 12 files,
`actingweb/` untouched):

- `tests/integration/_wire.py` - the recorder (a pure ASGI middleware:
  method, path, query, who the credentials belong to, the JSON body, the
  status, four headers, the JSON response; a request that starts while
  another is open is its child; an exception is a 500), `record_event` for
  hooks, `WireHost`/`WireActor`, the snapshot (A's queue per subscription
  through `Subscription.get_diffs`, B's replica as scalars and lists read
  separately through `RemotePeerStore`, B's callback state through
  `CallbackProcessor.get_state_info`, both actors' subscription rows, A's
  suspension rows), the `Scenario` driver (a step is a callable; after it,
  optionally a settle condition, then the snapshot), the normaliser and
  `check` (compare, or rewrite under `WIRE_RECORD=1`, refused under `CI`,
  and a mismatch writes `<row>.actual.json` beside the file).
- `tests/integration/test_harness.py` - `create_test_app` gains keyword-only
  `sync_callbacks`, `peer_capabilities`, `peer_permissions`, `peer_profile`
  and `record`; with `record`, the middleware, the recording hooks
  (`subscription_data_hook("properties")`, `subscription_deleted`,
  `trust_deleted`, the `permissions` callback hook) and one method,
  `wire_import`, shaped like the consumer's memory import: an asynchronous
  hook on the server's loop that suspends the list's subtarget, clears and
  refills it through the interface, and resumes.
- `tests/integration/conftest.py` - `wire_app` (5561) and `wire_peer_app`
  (5562), processing on (gap 2 s, `max_pending` 5), capabilities,
  permissions and profile on, **`sync_callbacks` off** (see below), and
  `wire_pair`: A and B in `same_host` or `two_hosts`, B initiates the
  trust, both approve, A grants (a list or a full permission object), A's
  capability cache for B is warmed, B subscribes; teardown through the
  library by id.
- `tests/integration/test_wire_spike.py` - the rows; `tests/integration/wire/`
  the five files; the `wire` marker; group `wire_spike`.

The rows, and what the recording shows:

| Row | File | Shows |
| --- | --- | --- |
| `WS1.target` | `same_host`, `two_hosts` | An object diff `{color: {...}}`, the callback nested in the `PUT`, the data hook nested in the callback; the replica holds the object as sent, a string as `{"value": "blue"}`, a number as `{"value": 3}`; the diffs stay queued after the 204 |
| `WL1.target` | one | `POST /properties {"notes": {"_type": "list"}}` sends `{"notes": "[Empty list property created]"}`; the three `/items` actions send `{"notes": {"action", "index", "value"}}`; the replica holds a **scalar** named `notes` after each, no list, as the research read |
| `WD9` | one | The excluded write spends sequence 1 and sends nothing; sequence 2 is held (`pending_sequences: [2]`, `last_seq 0`); 2.5 s later sequence 3 triggers the resync: B's `GET /<A>/subscriptions/<B>/<sub1>` (the whole, unfiltered queue), `denied` reaches the replica with a scalar named `timestamp`, B's `PUT {"sequence": 3}` clears the queue; **no data hook fires for 2 or 3** |
| `WD10.import` | one | Two SDK appends from the test thread (synchronous callbacks, as top-level requests: no HTTP request caused them); the import method answers `{"callbacks_sent": 1, "length": 3}` and *then* the resync callback (`type: resync`, no data, `subtarget: memories`) arrives as a top-level request with B's baseline fetch `GET /<A>/properties/memories` and the data hook (`{"memories": {"_list": true, "items": [...]}}`) nested in it; the replica equals A's list; A's queue still holds diffs 1 and 2 and the resync stored none |

## Answers

**1. Nesting.** Yes. On both topologies a REST write's callback is a child of
the write, B's data hook a child of the callback, and in `WD9` B's queue
poll and clear are children of the callback that triggered them. The REST
handlers run in the executor with no running loop, so the sender takes the
blocking branch whatever `with_sync_callbacks` says
(`actingweb/actor.py:2784-2793`); the flag only matters on the loop.

**2. One file per backend, or one file.** With identity-preserving
timestamp tokens, every row differed between backends, in timestamps only
(plus key order). DynamoDB's diff rows carry one value for every diff
(`db/dynamodb/subscription_diff.py:34`, a default evaluated at import),
PostgreSQL's one per row; the stored row read back is an aware datetime on
DynamoDB and a naive one on PostgreSQL. With class-only tokens
(`<ts:space>`, `<ts:iso-z>`, `<ts:iso-offset>`, `<ts:stored>`) and sorted
keys, one file per row holds on both. The switch is `WIRE_TS_IDENTITY=1`,
which also names the file per backend. What class-only loses: `WD3`'s
"DynamoDB: one timestamp for both" cannot be shown by a recording in that
mode, and a change from one value to two would pass. What it keeps: a
format change (space to ISO, Z to offset) still fails.

**3. Size and time.** 8.1 to 12.8 KB per file as full transcripts with the
snapshot after every step; the snapshot is most of it (about 60 %). A run
of the five: 6.0 to 7.6 s on either backend, of which `WD9` is 2.8 to 3.3 s
(its 2.5 s wait) and the other rows 0.3 to 0.9 s each; session start adds
the two wire apps (about 2 s). At that rate the plan's 87 row-variants in
two topologies are about two minutes per backend, not a CI problem; the
five-run rule is ten minutes.

**4. The unpredictable fetch.** Yes, exactly where the plan feared. A
resume with A's capability cache for B cold or expired assumes resync
support and schedules a background refresh on the loop
(`actor.py:3423-3454`): unauthenticated `GET /<B>/meta/actingweb/supported`
and `/version`. It races the resync callback; in 2 of 5 cold runs the
callback was recorded inside the refresh's `GET`, in 3 the other way round.
The pair's setup now warms the cache (`PeerCapabilities(a, b.id).refresh()`),
which is the consumer's state too: a mutual pair refreshes metadata on
subscribe when there is data. The row that wants the cold case (`WD12`'s
sibling, "assumes support") must declare the two requests unordered or
record the refresh out of band; with a warm cache no row saw it again.

**5. Teardown.** Passes on both backends. `ActorInterface.delete()` wipes
properties, subscriptions, trusts and every attribute bucket (`remote:*`,
`_callback_state`, `_peer_permissions`, `_resync_pending`) and sends the
peer trust deletes; it leaves (a) the suspension rows, which the fixture
removes first through the store's `resume` (the protocol has no
`delete_all`), and (b) a finished tombstone with a 30-day TTL. Nothing in
the package removes a tombstone from a fully deleted actor
(`actingweb-deletions clear` acts only on live actors). The fixture accepts
it: it is in the worker's prefix, which the session drops, and it affects no
later row. The recorder is closed before teardown, so the trust deletes are
not in any file.

**Determinism list.**

- Random-id order: one subscriber per row so far; the snapshot sorts rows by
  the peer's *name* then subscription id, so a two-subscriber row sorts by
  first appearance, not by id. Not yet exercised (`WD13`, `WD14`).
- Hash-seed order in the permission follow-up fetches: not exercised (the
  grant is given before recording starts).
- The gap timeout: `WD9` waits 2.5 s against the apps' 2 s and passed 10 of
  10. No other row holds a callback.
- Nesting attribution: holds for everything that runs off a REST request.
  It cannot hold for fire-and-forget: in `WD10.import` the resync callback
  is a sibling of the method request, not its child, because the method had
  answered (the comparison is still stable: the order is deterministic, the
  task runs after the response). A driver step that expects a callback it
  cannot nest needs its `settle` condition, as the import row has.
- `_received_at`, `claimed_at`, `nonce`, `version`: `_received_at` is
  replaced with an epoch token by first appearance; the rest did not appear
  in these rows' states (only `last_seq`, `version`, `resync_pending`,
  `pending_count`, `pending_sequences` are in `get_state_info`).
- Secrets: bearer tokens are mapped to `bearer:trust:A-B` through the
  trust's `secret` from setup; basic auth to `basic:<A.creator>`; the guard
  fails on any surviving 32-hex string, `localhost:55xx`, known secret or
  unknown bearer. The subscription ids are named by first appearance in a
  pre-pass so they are replaced inside paths too. Nothing leaked in nine
  runs; the one 32-hex family seen was subscription ids.

## Findings beyond the questions

- **`friend` grants `*`, and a grant only adds.** `trust_type_registry.py:346-358`
  gives `friend` `patterns: ["*"]` with `excluded_patterns` for `private/*`,
  `security/*`, `_internal/*`; `trust_permissions.py:656-668` unions
  patterns and exclusions. So `PUT .../permissions {"properties": ["allowed"]}`
  changes nothing a `friend` can read, and the first `WD9` recording showed
  `denied` delivered. The row needs `{"patterns": [...], "operations":
  ["read"], "excluded_patterns": ["denied"]}`, which the fixture now takes.
  The same applies to the consumer: Emm's per-peer property grants
  (`memory_*` and the like) add nothing to what a `friend` already reads;
  only exclusions restrict. That belongs to the security plan's research
  pass (the access table with application rows), not here.
- **The gap resync bypasses the data hook.** `sync_subscription`'s handler
  (`interface/subscription_manager.py:1059`) writes the replica and calls
  nothing else, and the triggering callback's own data is dropped
  (`callback_processor.py:861-878`). A consumer whose data hook drives
  notifications (Emm's `callback_hooks.py`) misses every diff that arrived
  via a gap. `WD9`'s registry entry should say so; which plan owns it is
  open (the `attribute-list-v2-port` plan changes the filter so a filtered
  diff takes no sequence number, which removes the gap, not the bypass).
- **A `PUT` of a scalar sends the raw request body** (`handlers/properties.py:981`),
  not the hook-transformed value: `"blue"` arrives as the JSON text `blue`
  wrapped by `register_diffs` into `{"color": "blue"}`. The research's `WS7`
  expectation ("the diff carries the value as sent") is confirmed by the
  mechanism; the row itself is not recorded yet.
- **The grant and the subscribe answer 201 then 204 on repeat** (first
  creation 201); the fixture accepts both. `POST /subscriptions` answered 204
  with no body on this run; the subscription id is read from the snapshot,
  not the response.
- **One "Failed to notify peer ... : {}" warning per pair** from
  `trust_permissions.py:316` during setup: the permission callback to B
  after the grant. B still held the grant's effect (its follow-up fetch
  ran, `callbacks.py:295`), so the warning is about the response the notify
  read, not the delivery. Unexplained; not in any recording because setup is
  not recorded. Worth a row (`WP1` records this callback) before it is
  called harmless.
- **`subscription_data` fires on the resync path with `type: resync`** and
  the baseline wrapped as `{name: {"_list": true, "items": [...]}}`, as
  Emm's `_notify_full_sync` expects.
- **The spike's rows contradict nothing** in the research's "Today's
  behaviour, as read" for what they cover: the scalar wrapping, the REST
  list vocabulary landing as a scalar, the filtered diff spending a
  sequence, the unfiltered poll, the `timestamp` scalar, the resync body
  with `type` and `url` and no diff row.

## How to re-point and re-run

```bash
git checkout spike/subscription-wire-harness   # or rebase it on a plan branch
docker compose -f docker-compose.test.yml up -d dynamodb-test postgres-test
DATABASE_BACKEND=dynamodb poetry run pytest tests/integration/test_wire_spike.py -p no:rerunfailures --no-cov -q
DATABASE_BACKEND=postgresql PG_DB_HOST=localhost PG_DB_PORT=5433 PG_DB_NAME=actingweb_test \
  PG_DB_USER=actingweb PG_DB_PASSWORD=testpassword poetry run pytest tests/integration/test_wire_spike.py -p no:rerunfailures --no-cov -q
WIRE_RECORD=1 ...        # rewrite the files (refused under CI)
WIRE_TS_IDENTITY=1 ...   # timestamp identity kept; files named per backend
```

An integration-only invocation does not load `tests/conftest.py`, so a file
that builds `Config()` with the default creator uniqueness fails on a fresh
DynamoDB Local (`test_property_list_collision.py`, four setup errors); that
is documented in `tests/conftest.py:106-118` and CI runs `pytest tests/`.
The wire rows do not depend on it.

## What the redrafts take from this

For the baseline plan (`/update_plan`):

- The three decisions, with the evidence above: **projection** - full
  transcripts proved cheap and stable here, and the snapshot is the bulk;
  the question is whether to keep the setup-free full transcript (this
  spike's form) or project; **timestamps** - class-only tokens give one
  file per row, identity gives one per backend and shows `WD3`; **tiers** -
  at 7 s per five rows the cost argument for two tiers is weaker than the
  review assumed; the argument that remains is the must-stay-identical list
  under redrafted plans.
- `WD9` as recorded, with the exclusion grant and the data-hook finding in
  its registry entry; `WP5`'s premise (a profile fetch at trust
  establishment) is already corrected in the research; the capability
  refresh needs a declared-unordered form or a warm cache per row.
- "What Already Exists" is the list under "What was built"; the security
  plan's Phase 0 lands it as its first commit after the redraft replaces the
  design text with it.
- The harness design points that did not survive: `with_sync_callbacks` on
  the wire apps (it would deadlock the import row: A's loop blocked in the
  callback while B fetches A's baseline), a `delete_all` on the suspension
  protocol (it has none), a tombstone-free teardown (none exists), and the
  claim that the fourteen security rows can stay byte-identical through the
  normaliser fixes (the normaliser is now what it is; they are recorded
  after it).

For the security plan: Phase 0's file list becomes the one above; its
fourteen rows are recorded on this harness with the exclusion form of
grants where a row restricts reads; the `WD9`-class rows run in `same_host`
with a warm cache.

## Open

- The sensitivity check (a scratch change to the library must alter a
  recording) was not run; with full transcripts it is hard to see how a
  wire change would not, but the projection decision changes that.
- Two subscribers in one row, the permission follow-up fetch inside a
  recorded step, and a low-granularity row are not yet exercised; those are
  the remaining determinism questions.
- The "Failed to notify peer" warning on the grant.
- Where the gap-resync data-hook bypass is filed.
