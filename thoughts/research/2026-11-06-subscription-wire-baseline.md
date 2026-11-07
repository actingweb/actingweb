# Research: what the suite proves about subscriptions between two actors, and what the library does today

**Date:** 2026-11-06
**Branch:** docs/3-16-rollup-records
**Commit:** fea9e42

Written while reviewing the five 3.16 plans of this date for regression risk
on the subscription path. Nothing here was run: every statement about the
library is from reading the code, most of it read twice by independent
readers. That limit is itself the main finding (see "Reading is not enough").

## Research Questions

1. **Does any integration test write to one actor over REST and assert the
   other actor's state?** No. See "What the existing files assert".
2. **Is the subscriber in those tests a real actor receiving a real
   callback?** Yes, over a real socket, but in most files it lives on an app
   with no subscription processing. See "The harness".
3. **What does the library do today on each flow the plans change?** See
   "Today's behaviour, as read".
4. **Do the plans' premises match it?** Not everywhere. See "Where the plans'
   premises differ".
5. **Is reading the code a sound way to state today's behaviour?** No: a first
   reading got about a dozen flows wrong. See "Reading is not enough".

## Summary

313 integration tests carry "subscription" in their purpose. They prove the
publisher's diff queue well and the subscriber's state almost not at all. One
file asserts a replica after a real callback, for three interface-layer list
operations. No test asserts a replica after a REST write. A 62-test file named
for subscription processing runs against a subscriber that has no processor
and accepts `204` or `400` for every callback it posts.

REST list edits do not reach a replica as list operations today: the REST
handlers and the receiver use two different diff vocabularies. The
`ListAttribute` plan fixes that, as a breaking change no test would notice.

## Detailed Findings

### The harness

- Every test app is built by `create_test_app`
  (`tests/integration/test_harness.py:23-153`) and runs as a uvicorn thread of
  the pytest process, sharing one database prefix.
- Six apps: 5555 `test_app`, 5556 `peer_app`, 5557 `www_test_app`, 5558
  `subscriber_app`, 5559 closed factory, 5560 unique creator
  (`tests/integration/conftest.py:201-205`, `:907`). Each worker has ten
  ports (`:223`); 5561 to 5564 are free.
- Only `subscriber_app` has subscription processing (`conftest.py:934`). Two
  files put their subscriber there: `test_subscription_callback_flows.py` and
  `test_list_diff_peer_replica.py`.
- `with_sync_callbacks()` is never set. Callbacks are still sent before a REST
  write answers, because a synchronous handler runs in the executor
  (`actingweb/interface/integrations/fastapi_integration.py:634-667`,
  `:2737-2755`), so there is no running loop and the sender falls back to a
  blocking request (`actingweb/actor.py:2781-2793`). The fire-and-forget
  branch (`:2744-2786`) is not exercised by any integration test.
- No app enables peer permissions or peer capabilities.
- The consumer runs processing with automatic storage, peer capabilities,
  peer permissions with the default `auto_delete_on_revocation=False`,
  synchronous callbacks on Lambda only, its own host registered as an actor
  type, and one target-level, high-granularity subscription per peer
  (`../actingweb_mcp/application.py:547-583`,
  `hooks/actingweb/lifecycle_hooks.py:165-170`).

### What the existing files assert

| Flow | What exists |
| --- | --- |
| REST write on the publisher, then the subscriber's stored value | Nothing |
| REST list edit, then the subscriber's replica | Nothing; `test_property_list_notifications.py` is seven placeholders |
| Interface-layer list edit, then the replica | `test_list_diff_peer_replica.py`: `append`, `remove_where`, `update_where`, a spanned reference |
| The callback body as the publisher sends it | Nothing; receiver tests post bodies the test built |
| Low granularity (fetch, acknowledge, queue empty) | Creation status only |
| Gap, duplicate, resync at the receiver | Hand-posted callbacks; the pending queue is asserted, content is not (`test_subscription_callback_flows.py:339-368`, `:497-519`) |
| Suspend and resume reaching a subscriber | Nothing over HTTP |
| Permission filtering of diffs | Nothing; one test tolerates the unpermitted key (`test_subscription_flow.py:879-883`) |
| Unsubscribe and trust deletion reaching the subscriber | The publisher's side only |
| Anonymous callbacks, a third peer | Nothing |
| The publisher's queue (list, one diff, clear, per-subscriber sequence) | Covered; many assertions sit inside `if` |

What makes a green run weak evidence:

- `test_subscription_processing_flow.py` creates its subscriber on `peer_app`
  (`:71-83`), where only the harness's legacy hook runs. It answers
  `bool(data)` (`test_harness.py:129-142`), so a callback with data is a 204
  whatever its sequence; 13 assertions there accept `[204, 400]`.
- 179 status assertions across the subscription, fan-out, notification and
  trust-flow files accept more than one code; 47 more lines guard an
  assertion with `if …status_code`.
- 61 `pytest.skip` calls fire when earlier state is missing.
- `test_fanout_flow.py` says it tests `FanOutManager`, a granularity
  downgrade and a circuit breaker (`:4`, `:412-413`, `:631-637`); none runs on
  the publish path (`actingweb/fanout.py` is only exported). Its first class
  does drive the real publish path with several subscribers.
- `tests/integration/README.md` and `XDIST_GROUPS.md` are out of date.

### Today's behaviour, as read

"Level" is the level of the subscriber's subscription. Each line was read by
two readers unless marked (one reader).

Scalars:

- `PUT /properties/<p>`, target level: the diff is `{p: value}`; the replica
  holds an object as sent and anything else as `{"value": …}`
  (`actingweb/remote_storage.py:376-386`). The diff stays in the publisher's
  queue after the 204 (`actor.py:2721-2724`).
- The same, subtarget level: the diff is the bare value. An object is stored
  as one scalar per key; a string makes the receiver answer 400, because the
  processor calls `.get` on it (`actingweb/callback_processor.py:909`,
  `actingweb/handlers/callbacks.py:428-429`); a falsy value becomes `{}` and
  answers 204 (`:649`).
- What a subtarget-level subscriber receives also depends on the shape of the
  grant: the filter checks `<subtarget>/<key>` (`actor.py:2919-2924`) with a
  full-string glob (`actingweb/permission_evaluator.py:114-134`), so an
  exact-name grant denies every key of an object diff, a sequence number is
  spent and no callback is sent (`actor.py:2642-2643`). A non-object diff is
  not filtered at all (`:2904-2906`).
- `PUT /properties/<p>/<k>`: the replica's `p` is overwritten with `{k: v}`
  and loses its other keys (`remote_storage.py:376-377`).
- `DELETE /properties/<p>`, target level: a diff `{p: ""}` is stored, takes a
  sequence number and is sent, and the replica's key is deleted
  (`actingweb/handlers/properties.py:1841`, `actor.py:4017-4026`,
  `remote_storage.py:373-375`). Only a subscription whose subtarget is `p`
  gets nothing, because a bare `""` is refused
  (`actingweb/subscription.py:155-157`).
  `tests/integration/test_property_notifications.py:134-137` asserts the
  target-level diff.
- `DELETE /properties`: one `{key: ""}` diff per key (one reader).
- `POST /properties` with several names: one diff (one reader).
- A hook that rewrites a value: the diff carries the value as sent
  (`handlers/properties.py:970-981`).

Lists:

- The REST handlers register `{"index", "value"}`, `{"action": "add" |
  "update" | "delete", …}` and `{"action": "metadata_update", …}`
  (`handlers/properties.py:880-888`, `:2269-2282`, `:2352-2361`,
  `:2386-2419`, `:2052-2056`). The receiver treats a value as a list
  operation only when it has `list` and `operation`
  (`remote_storage.py:355-368`), so a target-level subscriber stores a scalar
  named after the list and a subtarget-level subscriber stores scalars named
  `action`, `index`, `value`.
- The interface layer registers `{"list", "operation", …}`
  (`actingweb/interface/property_store.py:300-331`), and a target-level
  replica follows it. A subtarget-level subscriber gets the bare diff and
  stores scalars named `list`, `operation`, `item`, `index`
  (`actor.py:4032-4038`).
- A `pop` with a negative index other than -1 is not applied
  (`remote_storage.py:491-499`).
- The web-UI form routes register nothing, except the `/www` delete, which
  registers an empty diff for lists and scalars
  (`actingweb/handlers/www.py:479-481`, `:496-498`).
- `POST /properties/<list>` with an object body: the 400 is overwritten by a
  201 and root properties are written (`handlers/properties.py:1075-1077`,
  `:1726`; one reader).

Delivery and the receiver:

- The callback body: `id`, `subscriptionid`, `target`, `sequence`,
  `timestamp`, `granularity`, `data`, and `subtarget` and `resource` only
  when set (`actor.py:2646-2662`). Its timestamp is `str()` of a datetime;
  the poll endpoints send ISO with `Z`
  (`actingweb/handlers/subscription.py:349`, `:591`).
- On DynamoDB every diff carries the same timestamp, set when the module was
  imported; PostgreSQL stamps each diff
  (`actingweb/db/dynamodb/subscription_diff.py:34`, `:114-120`,
  `actingweb/db/postgresql/subscription_diff.py:164`). A real backend
  difference (one reader).
- A diff the permission filter empties still takes a sequence number, and no
  callback is sent. The next callback is held pending; a later one past the
  gap timeout triggers a resync, in which the receiver polls the publisher's
  whole queue, which is not filtered. The property the peer may not read
  reaches the replica that way (`callback_processor.py:861-878`,
  `handlers/callbacks.py:851-860`,
  `actingweb/interface/subscription_manager.py:926-928`, `:1080-1096`). The
  gap timeout is only evaluated when a callback arrives
  (`callback_processor.py:422-428`).
- The poll path adds a `timestamp` key to each diff's data
  (`subscription_manager.py:1086-1087`), so a replica filled by a poll holds a
  scalar named `timestamp` (one reader).
- Resume sends `type: "resync"` with a `url` the receiver ignores; it fetches
  the baseline itself (`actor.py:3481-3491`, `handlers/callbacks.py:558-575`).
  A key deleted while suspended stays in the replica
  (`remote_storage.py:549-552`). A `none` subscription is sent a resync too.
- The fallback to a full state needs the trust row to lack
  `subscriptionresync` **and** to have a fresh `capabilities_fetched_at`
  (`actingweb/peer_capabilities.py:81-101`, `:131-145`,
  `actor.py:3423-3427`). The full state is not permission-filtered
  (`actor.py:3497-3512`), and an existing list is doubled
  (`remote_storage.py:476-477`).
- A fire-and-forget callback keeps the `Actor` alive after the call: the
  task's closure holds `self` (`actor.py:2744-2786`). The task itself is not
  referenced by anything (`:2786`).
- The executor has ten workers per app (`fastapi_integration.py:621`). The
  serial sender needs two or three threads per chain. Asynchronous handlers
  (`POST /trust`, `/methods`, `/actions`, MCP) run hooks on the loop
  (`actingweb/interface/hooks.py:936-939`); a hook there that writes a
  property, with synchronous callbacks on and a subscriber on the same host,
  blocks the loop until the 10-second read timeout.

The queue and the life of a subscription:

- `GET …/<subid>` does not clear; `GET …/<subid>/<seq>` consumes the diff;
  `PUT {"sequence": n}` clears up to n, and `0` clears all
  (`handlers/subscription.py:339-372`, `:576-598`, `:428`,
  `db/dynamodb/subscription_diff.py:212-218`). `{"sequence": null}` raises an
  uncaught `TypeError` (`:404-411`; one reader).
- An unknown granularity is accepted; its callback has neither `data` nor
  `url`, and the receiver answers 204 and advances its sequence
  (`actor.py:2658-2663`).
- Unsubscribing at the subscriber deletes the publisher's row through `DELETE
  /<publisher>/callbacks/subscriptions/<subscriber>/<subid>`, and the
  subscriber's replica bucket goes with its last subscription
  (`actor.py:2520-2529`, `:2564-2614`). Deleting at the publisher sends
  `DELETE /<subscriber>/subscriptions/<publisher>/<subid>`. Both are
  legitimate uses of the paths the security plan tightens.
- Actor deletion removes diffs with their subscriptions
  (`actingweb/subscription.py:280-296`); suspension rows remain, on both
  backends (`delete_all` has no caller outside `db/`).

Access:

- No credentials on the two peer callback paths: 204 and applied. A wrong
  bearer: the same, because the authentication result is never looked at
  (`handlers/callbacks.py:178-205`, `:358-366`). Another peer, or the
  creator: the same, through the empty-role row (`actingweb/config.py:289`).
  An unapproved peer: 403 (`actingweb/auth.py:751-761`).
- `DELETE` on a generic callback path without credentials already answers 401
  (`handlers/callbacks.py:80-84`).
- An authenticated request to a callback path no hook handles answers 200
  with the body `false` when the application registers any callback hook
  (`interface/hooks.py:706-709`, `handlers/callbacks.py:465-469`).
- A peer cannot create a subscription under another peer's id: 403
  (`handlers/subscription.py:235-244`).
- **New finding.** A subscription callback is accepted against a row the
  actor holds as publisher: the lookup asks for `callback=True`
  (`subscription_manager.py:524-528`) but the backend does not filter on it
  (`db/dynamodb/subscription.py:69-73`). A subscriber can therefore post
  "diffs" to its publisher under its own subscription id, and a publisher
  with automatic storage writes them into its replica store for that peer.
  The caller is the peer the path names, so the rule the security plan adds
  does not stop it.

### Where the plans' premises differ

- `peer-authorisation-fixes` and its research: "The consumer turns the
  deletion on (`application.py:558-560`)". It passes `enable=True` only; the
  default is off (`actingweb/interface/app.py:851`). The exposure stands for
  deployments that set it. Also: a peer cannot create a subscription under
  another peer's id (corrected in the research on this date).
- `spec-1-5`, rows S1 and S2: a deletion is already a diff for every
  subscription broader than the deleted name; what is missing is the exact
  subtarget-level and resource-level cases. Row C1: an overlapping `append`
  is not applied twice today, because the subtarget-level copy is stored as
  scalars; it will be once the `ListAttribute` plan teaches the receiver the
  subtarget-level form. The overlap rule is needed because of that plan, not
  before it.
- `attribute-list-v2-port`, row S8b: the unfiltered stored diff reaches a
  subscriber without any poll of its own, through the gap resync a filtered
  diff causes. "A diff filtered to nothing takes no sequence number" removes
  the gap as well, so the two halves of that change have to land together.
- `attribute-list-v2-port`, Phase 4: "a subscriber whose trust row says it
  lacks `subscriptionresync` (written through the library, with a fresh
  `capabilities_fetched_at`)" is right, and the timestamp is what matters.
- `spec-1-5`, Phase 4: with a concurrent sender, five low-granularity or
  gap-resyncing subscribers on the publisher's own host need eleven executor
  threads of ten.

## Reading is not enough

A first reading of the code, by one careful reader, stated today's behaviour
for about sixty flows. A second, independent reading found about a dozen of
those wrong or true at one subscription level only (deletes, list deletes,
the web-UI delete, subtarget-level list diffs, string diffs, the fallback
condition, what an authenticated unhandled callback answers). Several of the
five plans carry the same kind of statement. A baseline has to come from a
run, and has to capture more than an author thought to assert.

## Documentation Impact

- `docs/contributing/testing.rst` - no description of a two-actor baseline:
  none. Needs one.
- `tests/integration/README.md`, `XDIST_GROUPS.md` - stale counts and file
  names.
- `docs/guides/subscriptions.rst` - already listed as wrong in three places
  by the `ListAttribute` plan; nothing further found here.

## Decisions Needed

All three were put to the owner on 2026-11-06 and decided:

1. **Release of the security fix**: it stays in 3.16; no 3.15.x backport.
2. **Where the baseline goes**: its own plan and PR after the security fix
   and before the other four plans. The security PR carries only the
   legitimate flows it must keep unchanged, and its access tests in their
   secured form.
3. **How a row proves today's behaviour**: recorded transcripts, one per row,
   not hand-written expectations.

## Code References

- `tests/integration/test_harness.py:23-153`, `tests/integration/conftest.py:201-226`, `:827-1100` - the harness
- `actingweb/actor.py:2623-2793`, `:2876-2943`, `:3110-3660`, `:3856-4080` - the sender, the filter, resync, `register_diffs`
- `actingweb/handlers/callbacks.py:176-471`, `:473-900` - the receiver
- `actingweb/handlers/subscription.py` - the queue endpoints
- `actingweb/handlers/properties.py:880-888`, `:1075-1077`, `:1721-1726`, `:1769-1770`, `:1806`, `:1841`, `:2052-2056`, `:2269-2419` - what each REST write registers
- `actingweb/remote_storage.py:328-522`, `:524-620` - what a subscriber stores
- `actingweb/callback_processor.py:422-428`, `:792-1022` - sequencing
- `actingweb/interface/subscription_manager.py:498-530`, `:859-1223` - lookup and the poll path
- `actingweb/peer_capabilities.py:81-145` - the resync capability

## External References

None.
