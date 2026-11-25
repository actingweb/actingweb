# Research: Long-running A2A tasks, task storage and worker hand-over

**Date:** 2026-11-24
**Feature:** thoughts/features/2026-11-24-a2a-actor-interface.md
**Companion to:** thoughts/research/2026-11-24-a2a-actor-interface.md
**Branch:** master
**Commit:** a74ae35

## Owner decisions recorded 2026-11-24

These were made after the companion research was written. The plan carries
them as decisions; neither research document is a place to keep them
current.

1. **No uptake measure.** Uptake will not be observed. The open question
   is closed.
2. **The extended card may differ per caller** (AC-6 stands as written).
   The A2A text says "MAY return different details based on client
   authentication level". Per-caller variation is the owner's reading of
   that permission.
3. **Long-running tasks are in scope.** The work runs outside the request,
   for example in a Fargate container the consumer application starts per
   task. That process updates and completes the task through ActingWeb.
   It is started with context (an environment variable or similar) that
   lets it fetch the task, process it and complete it. The research asked
   for:
   - alternatives for storing an ongoing task for an actor, by id
   - an easy way to execute a task with the library's primitives
4. **One actor at a time, also outside a request.** The library has kept
   out cross-actor functionality: the mini-app model is a security model
   in which only one actor's data is touched at a time. A worker needs a
   single-actor context obtained programmatically when no HTTP request
   names the actor. See "What scopes a worker to one actor" below.

External quotes come from a fetch tool that caps quotes at about 125
characters. **[inference]** marks a conclusion the source does not state.

## Research Questions

1. **What must a stored A2A task hold, and which rules bind it?** — `id`
   and `status` are required. The server generates the id. A terminal task
   cannot restart. `ListTasks` is filtered, paged, sorted by status time
   and limited to what the caller may see, with a required `totalSize`.
   Cancel may race with completion. No retention period is set. See
   [The A2A task model](#the-a2a-task-model).
2. **Which storage primitive fits a per-actor task record?** — One
   attribute per task gives a point read, a whole-value compare-and-set,
   TTL and private storage. A list item per task does not: handles are not
   stable, and every update contends on one shared metadata row. A
   dedicated table costs a model, a migration and a readiness entry on
   both backends. See [Storage alternatives](#storage-alternatives).
3. **Is anything task-like there already?** — No task, job or
   pending-action store exists. The spec's `/actions` 201 + `Location`
   polling pattern is specified but not implemented. The nearest
   lifecycle record with a lease is the deletion tombstone. See
   [What exists](#what-exists-that-resembles-a-task).
4. **How can a separate process act on an actor?** — Two ways: directly
   against the store, by building a `Config` and loading the actor with
   `ActorInterface.get_by_id`, or over HTTP with a credential. The
   library's own operator commands and Emm's cleanup and WebSocket Lambdas
   do the first. See [Worker execution paths](#worker-execution-paths).
5. **What credential can a worker hold that is limited to one task?** —
   None exists. Every token today binds to an actor plus a client,
   identifier or trust type, never to a resource. The single-use and
   tombstone-lease machinery is the base to build one on. See
   [Worker credentials](#worker-credentials).
6. **How is context handed over, and what limits apply?** — ECS RunTask
   overrides are limited to 8192 characters in total, and an environment
   value is echoed in the task description **[inference for
   DescribeTasks]**. Lambda async payloads are up to 1 MB and may be
   delivered twice. The Step Functions task-token pattern is the closest
   analogue of a completion token. See [Hand-over patterns](#hand-over-patterns).
7. **How do others model this?** — a2a-python's `TaskStore` (4 methods,
   owner-scoped, last write wins) and its cluster mode (versioned
   compare-and-set, cancel overrides) run the agent inside a server
   replica. A third-party Redis design hands tasks between processes with
   leases and fencing. Emm's one-off task queue is a property-list record
   with a claim and lease. See [Prior art](#prior-art).
8. **How is a caller told about progress?** — `GetTask` polling always
   works. Push and streaming are separate capabilities. An ActingWeb peer
   could also subscribe if the task were announced as a subscription
   target. See [Notification](#notifying-the-caller).
9. **How does `SendMessage` behave when the work is handed off?** — When
   `returnImmediately` is false (the default), the server MUST wait for a
   terminal or interrupted state. With an external worker that means
   holding the request open or refusing. See
   [Blocking](#the-blocking-default).

## Summary

A2A allows a task to be created by `SendMessage` and finished later by any
process that writes its state, provided:
- writes after a terminal state are refused
- cancel wins over a running worker
- `ListTasks` shows each caller only its own tasks

Storage:
- **Attributes, one row per task.** These have the right primitives
  already: a point read by name, a whole-value compare-and-set on both
  backends, create-if-absent, TTL, and privacy (no route serves them, no
  subscriber is told).
- **What attributes lack:**
  - paging: `get_bucket` reads a whole bucket, so `ListTasks` filters in
    memory
  - a size cap on DynamoDB for a single attribute: 400 KB per row
    (`db/dynamodb/attribute.py:112`). Since 4.0, *list items* larger than
    one row span (property lists and attribute lists, side bucket
    `<bucket>$aux`, default ceiling 2 MiB, `ListItemTooLargeError` above
    it; `docs/migration/v4.0.rst`, "Spanned list items"). A scalar
    attribute such as the status row does not span, so large history and
    artifacts belong in an attribute list
  - a reaper for a new bucket on PostgreSQL
  - per-peer cleanup on trust deletion
- **A dedicated table** would add paging and indexes. It costs a model, an
  Alembic revision, a `verify_tables` entry and, optionally, a readiness
  check.

Execution:
- **The library already runs outside a request.** Operator commands and
  Emm's Lambdas build a bare `Config` and use the store directly. The
  documented form is `get_by_id(actor_id, config=app.get_config())`,
  which carries the app's hooks, delivery settings, indexed properties and
  list limits; no guide covers a worker as a deployment shape.
- **Nothing scopes such a process to one actor.** `get_by_id` takes any id
  and returns an owner-level view; the one-actor rule holds by convention
  (Decision T2b).
- **What a bare `Config` lacks:** the application's hooks, its delivery
  settings, its indexed-property list (Emm's differs from the default), its
  list-item limits and the readiness check.
- **Nothing in the library or in Emm dispatches work to another process.**
  Emm's long work is pulled by outside MCP clients.
- **No credential can be limited to one task.** The tombstone lease
  (create-if-absent, compare-and-set, lease id, takeover) and
  `single_use.consume_once` are the in-tree patterns for a task-scoped,
  expiring, fenced token.

How context reaches the worker is the consumer's, but the library decides
what that context is:
- **A task id plus a short-lived task token.** The worker reaches the
  actor over HTTP or through a library call that checks the token.
- **A task id plus database access.** The worker uses the library
  directly, and the trust boundary is the container's own permissions.

ECS overrides fit either, at 8192 characters. AWS advises against secrets
in environment variables.

## Detailed Findings

### The A2A task model

Sources: <https://a2a-protocol.org/latest/specification/>,
`a2a.proto` on `main` (`lf.a2a.v1`),
<https://a2a-protocol.org/latest/topics/life-of-a-task/>.

**Task fields.**
- `id` and `status` are REQUIRED.
- `context_id`, `artifacts`, `history` and `metadata` are optional.
- `contextId` is required on the update events, and a2a-python's table
  declares it `NOT NULL`, so it is set in practice.
- `TaskStatus` is `{state (required), message, timestamp}`.
- `Artifact` is `{artifact_id (required, "unique within a task"), parts
  (required, at least one), name, description, metadata, extensions}`.
- `append` and `last_chunk` belong to streaming update events, not to the
  stored artifact.

**States.**
- `SUBMITTED`, `WORKING`
- terminal: `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`
- interrupted: `INPUT_REQUIRED`, `AUTH_REQUIRED`

**Ids.**
- "Task IDs are **server-generated**"
- "Client-provided `taskId` values for creating new tasks is **NOT**
  supported"
- An agent MAY generate a `contextId`.

**Terminal tasks.** A message to a terminal task fails with
`UnsupportedOperationError`. "Once a task reaches a terminal state … it
cannot restart". Follow-up work goes into a new task linked by
`referenceTaskIds`.

**Continuing.** An `INPUT_REQUIRED` task continues when the client sends a
message "with the same `taskId` and `contextId`". The server then has to
wake the worker or hand the task to a new one: a second hand-over.

**GetTask.** `historyLength` caps the messages returned: none means no
limit, 0 means none.

**ListTasks.**
- Filters: `contextId`, `status`, `pageSize` (default 50, max 100),
  `pageToken`, `historyLength`, `statusTimestampAfter`,
  `includeArtifacts` (default false: artifacts omitted).
- The response requires `tasks`, `nextPageToken`, `pageSize` and
  `totalSize`.
- "MUST return only tasks visible to the authenticated client".
- Sorted by status timestamp, newest first.
- "Authorization checks MUST occur before any database queries."

**CancelTask.**
- "success is not guaranteed".
- `TaskNotCancelableError` covers already completed, failed, canceled or
  rejected.
- §3.3.1 also calls cancel idempotent. The spec leaves this conflict
  unresolved.

**Retention.** No period. Agents "SHOULD document" expiry policies.
`TaskNotFoundError` covers an expired or purged task.

### The blocking default

`SendMessageConfiguration.return_immediately`: "If `false` (default), the
operation MUST wait until the task reaches a terminal … or interrupted …
state before returning."

**[inference]** With work handed to another process, a server following
the spec has three choices:
1. Hold the request open and re-read the store until the state changes,
   bounded by the gateway limit (about 29–30 s, companion research
   "Deadlines on serverless").
2. Refuse or reject long skills unless the client sets
   `returnImmediately: true`.
3. Return the task in `WORKING` state when the wait would exceed a bound,
   which bends the MUST.

The spec does not address this. The default Python client sends
`polling: False` and `streaming: True` (companion research), so its
blocking behaviour against a non-streaming card is untested.

### Storage alternatives

Facts from `actingweb/attribute.py`, `actingweb/db/dynamodb/attribute.py`,
`actingweb/db/postgresql/attribute.py` and `actingweb/list_core.py`.

**Attributes (one row per task).**
- **Key:** `(actor_id, "<bucket>:<name>")`. On DynamoDB the item holds
  `data` (JSON), `timestamp` and `ttl_timestamp`
  (`dynamodb/attribute.py:65-84`). On PostgreSQL the table has primary key
  `(id, bucket_name)`, JSONB data and no foreign key to `actors`
  (`postgresql/schema.py:214-255`).
- **`conditional_update_attr`** (`attribute.py:495-594`) is a whole-value
  compare-and-set that never creates a row. A mismatch, a missing row and
  (unless `strict=True`) a fault all return `False`.
  - DynamoDB reads consistently, compares in Python, then runs a
    conditional `UpdateItem` on the value it read
    (`dynamodb/attribute.py:341-442`).
  - PostgreSQL runs one `UPDATE … WHERE data = old::jsonb`
    (`postgresql/attribute.py:586-683`).
  - A lost answer to a landed write also returns `False`. The pattern is a
    per-call unique value in the new data plus a strict re-read
    (`attribute.py:529-534`; `single_use.py:158-191`).
- **`create_attr_if_absent`** (`attribute.py:596-641`) is create-once that
  replaces an expired row. A fault raises `DbError`.
- **`delete_attr_conditional`** lets exactly one caller win.
- **TTL**: `set_attr(ttl_seconds=…)` stores now + TTL + a 3600 s skew
  buffer (`constants.py:269`).
  - DynamoDB relies on native TTL, which the operator must enable.
  - PostgreSQL relies on `delete_expired(buckets=[…])`. Every existing
    caller passes a fixed bucket list, so a new bucket is never reaped
    (`token_manager.py:2197-2236`, `oauth_session.py:1315-1321`,
    `maintenance/deletions.py:357-359`).
  - Expired rows are still returned by `get_attr` and `get_bucket`. Only
    `get_attr_strict` hides them.
  - `set_attr` without `ttl_seconds` clears an existing TTL.
  - Compare-and-set does not check TTL.
- **Size**: DynamoDB `MAX_ROW_BYTES = 409_600`, not enforced on `set_attr`
  and not spanned. PostgreSQL has no practical cap.
- **Listing**: `get_bucket` reads the whole bucket. DynamoDB pages
  internally; PostgreSQL uses one `SELECT`. Neither has a limit or a
  cursor.
- **Falsy data deletes**: `set_attr({})` is a delete on both backends.
- **Backend differences**:
  - a compare-and-set on PostgreSQL overwrites `timestamp` (NULL when none
    is passed); DynamoDB keeps it
  - `delete_attr_conditional` faults return `False`, while
    `create_attr_if_absent` faults raise

**Attribute or property lists (one item per task).**
- **Handles**: a `ListItemHandle` rank can be reissued and is not to be
  persisted (`list_core.py:386-422`), so a task id cannot be a handle.
- **Lookup by id**: `find(identity_key, value)` reads the whole list.
  `append_once(key=…)` gives an idempotent create keyed by a hashed
  identity row.
- **Updates**: `update_by_handle` is single-shot compare-and-set on the
  raw item. Every mutation also re-reads, then does a compare-and-set on
  the list's single metadata row (`list_core.py:2100-2159`). A busy actor
  with many running tasks contends there.
- **Size**: spans large items to `$aux` (DynamoDB above about 390 KB, or
  about 67.5 KB in attribute lists).
- **TTL**: ignored. Paging: none.
- **Property lists additionally**: peer-readable through grants, and
  subscribers are notified of each change (`property_store.py:325-410`).

**Dedicated table (`tasks`).** Cost, from the existing patterns:
- DynamoDB:
  - a PynamoDB model
  - `ensure_table` from the accessor (`db/dynamodb/_ensure.py:73-107`;
    auto-creates unless `AWS_DB_AUTO_CREATE_TABLES=false`, which Emm sets)
  - an entry in `db/verify_tables.required_models` (`:42-78`)
  - native TTL, enabled by the operator
- PostgreSQL:
  - a model in `db/postgresql/schema.py`
  - an Alembic revision under `migrations/versions/`
  - psycopg code
- Both:
  - a protocol in `db/protocols.py`
  - a factory in `db/__init__.py`
  - an import in `config.py:449-472`
  - optionally a readiness check (`interface/app.py:1787-1850`)
- **What it buys:** secondary indexes for `(actor, caller, status time)`
  paging and a version column. The a2a-python schema indexes
  `(owner, last_updated)`.

**Shape of a task across rows (any primitive).**
- **[inference]** One small status row per task lets the worker and
  `CancelTask` compare-and-set without carrying history and artifacts.
  The row holds state, version, owner peer, context id, timestamps, the
  worker lease and the token digest.
- History and artifacts go in rows of their own: attribute rows, or an
  attribute list per task, which spans large parts.
- This keeps every compare-and-set row well under DynamoDB's 400 KB.

**Bucket placement.**
- Under the actor (`bucket a2a_tasks`): the actor wipe deletes every
  bucket of the actor (`actor.py:1611-1722`).
- Under a system actor (as `mcp_auth_codes` indexes and tombstones are):
  survives the actor wipe and needs its own cleanup.
- A global index row from token → task (the `_auth_code_index` pattern on
  `_actingweb_oauth2`, `token_manager.py:1142-1170`) is how a token
  without an actor id in it finds its task.

### What exists that resembles a task

**Spec `/actions`** (`docs/protocol/actingweb-spec.rst:1755-1792`): POST
MAY return 201 with `Location`, and that URL MUST answer GET with status
or progress. DELETE SHOULD cancel.

**The library does not implement it** (`handlers/actions.py:159-341`):
- POST answers 200 with the hook's result; no `Location` is set.
- An application could serve instance URLs with a `"*"` action hook,
  storing everything itself.

**Deletion tombstones with a lease** (`deletion.py:318-620`):
- `create_leased_tombstone` (create-if-absent)
- `claim_lease`, `renew_lease`, `release_lease`, `mark_finished`
  (compare-and-set on `claimed_until` and `lease_id`)
- takeover when the lease lapses
- `DELETION_LEASE = 120 s`
- resumed by the next request or by the `actingweb-deletions` command

This is a multi-process state record with fencing, the closest in-tree
model of a worker claim.

**Single-use records** (`single_use.py:100-191`): `consume_once` stamps
`used` and `consume_id` by compare-and-set, and a strict re-read tells a
lost race from a fault. Used for MCP codes, refresh tokens and pending
authorizations (`token_manager.py:162-230`).

**Pending-style attributes.** `_resync_pending`, `_pending_adoptions` and
`_callback_state` carry no lifecycle beyond set and delete.

### Worker execution paths

**A. Direct library access (no HTTP).**
- **Build:** `Config(aw_type=…, database=…, fqdn=…)` or
  `ActingWebApp(...).get_config()` (`interface/app.py:1669-1738`; builds
  without a web framework).
- **Load:** `ActorInterface.get_by_id(actor_id, config)`
  (`interface/actor_interface.py:172-197`) returns `None` when missing and
  raises `DbError` on a fault.
- **Precedents:**
  - `make_config()` in `maintenance/property_lookup.py:176-184`
  - `maintenance/peer_state.py:120-124`
  - Emm's `helpers/config.get_app_config()`, used by its cleanup Lambda
    and WebSocket Lambdas (`../actingweb_mcp/helpers/config.py:107-149`,
    `cleanup_handler.py:36-77`, `websocket_handlers/default.py:365-437`)
- **What a bare `Config` lacks:**
  - The application's hooks (`config._hooks` is set only on the app path,
    `app.py:1728`). Property and list hooks do not run.
  - Delivery settings (`_subscription_config`). With no event loop,
    `deliver()` waits for every callback before returning
    (`callback_sender.py:278-312`), so a property write from the worker
    sends subscriber callbacks synchronously.
  - `check_ready()` (`app.py:1787-1850`). It runs only from `integrate_*`.
  - The application's `indexed_properties`. A bare `Config` defaults to
    `["oauthId","email","externalUserId"]` (`config.py:420`), while Emm
    configures `["oauthId","email"]` (`application.py:581-583`). A worker
    writing an indexed property would then index differently from the app
    **[inference from the two values]**.
  - The application's list-item limits. A bare `Config` takes the
    backend's defaults for `list_item_span_threshold` and
    `list_item_max_bytes` (`config.py:262`), not the app's
    `with_list_item_limits()`. A worker writing artifacts into an attribute
    list then spans or refuses items differently from the app unless it
    sets the same limits (`docs/migration/v4.0.rst`, "Spanned list items").
  - Request context: logs show `[-:-:-]` unless the worker calls
    `set_request_context()` (`request_context.py:201-240`).
- **The worker's trust boundary** is the container's database credentials.
  It can do anything to any actor. The task is a convention, not a check.

**What is supported today for path A.**
- **Documented:** `ActorInterface.get_by_id(actor_id,
  config=app.get_config())` (`docs/sdk/actor-interface.rst:35-50`).
- **`app.get_config()` wires the application's setup:** hooks and
  subscription config (`app.py:1728-1737`), indexed properties, list-item
  limits and the service registry. The gaps listed above are gaps of a
  bare `Config()`, the form the operator commands and Emm's Lambdas use,
  not of the app-built one.
- **Left to the worker:**
  - `check_ready()`. `docs/migration/v4.0.rst:512-519` requires it of "a
    process that creates actors without `integrate_*` (a worker, …)".
  - Request-context logging (`set_request_context()`).
  - Any notion of which task it serves.
- **Not documented:** no guide describes a worker or background process as
  a deployment shape. The docs show `get_by_id` as an SDK call and name
  workers only in passing (the migration step above;
  `quickstart/configuration.rst:574`; list-item limits in
  `migration/v4.0.rst`, "Spanned list items").

**What scopes a worker to one actor (owner decision 4).**
- **Over HTTP**, the URL names the actor and authentication proves the
  caller may touch it. The scope comes from the request, not from the
  application's code.
- **`get_by_id` has no equivalent.** It takes any actor id and returns that
  actor; the only thing binding a worker to one actor is the id its own
  code passes. `get_by_creator` and `get_by_property` are lookups across
  actors in the same way. **[inference]** In a worker, the one-actor rule
  holds by convention only.
- **The returned `ActorInterface` is an owner-level view.** Every store on
  it reads and writes without a permission check.
  `AuthenticatedActorView` (`authenticated_views.py:894`) enforces a
  peer's or client's permissions but has no production caller (companion
  research), and no task-scoped form exists.
- **What would carry the HTTP shape into a worker [inference]:** an entry
  point that takes a credential, not an actor id, and derives the actor
  from it. A task token resolves to one actor and one task, and the
  returned handle exposes that task and the actor stores the task may
  touch. Such a handle is an API shape. It cannot stop code holding
  database credentials from calling `get_by_id` alongside it. Only path B
  (no database credentials in the worker) makes the one-actor rule an
  enforced boundary.

**B. Over HTTP back to the application.**
- The worker calls the actor's routes with a credential. The application
  enforces scope, and the worker needs no database access.
- **Needs:**
  - a route or method the worker calls (no task route exists)
  - a credential the library checks and limits to one task (none exists;
    see below)

**C. A library "task context" call that checks a token, over either
path.**
- Example: `ActingWebTask.open(config, task_token)` returns a handle with
  `update_status`, `add_artifact`, `complete`, `fail` and `heartbeat`. The
  name is illustrative only.
- Each call does a compare-and-set on the status row, guarded by the token
  digest and the lease or version.
- This is A with a check inside it. The boundary is still the database
  credentials, but a worker using the library cannot write another task by
  accident, and a stale worker is fenced.

### Worker credentials

**What exists, and what each binds to** (none to a resource):

| Credential | Binds to | Lifetime | Where |
|---|---|---|---|
| Trust secret | (actor, peer), relationship | Until the trust is deleted | `auth.py:309-331` |
| `aw_` access token | actor, client, trust type, scope `mcp`; checked only on `/mcp`, not REST | 3600 s | `token_manager.py:1713-1781` |
| SPA token | actor, identifier; authenticates as **creator** | 3600 s, settable | `oauth_session.py:478-534` |
| Authorization codes, email sign-in codes | actor (and client) | 600 s, single use | `constants.py:190-250`, `email_sign_in.py:13-79` |

**Machinery a task token could reuse:**
- A random token whose digest is stored, with TTL. Pending authorizations
  store a SHA-256 of a `pa_` token as the row key (`token_manager.py:162-195`).
- A global index from token digest to (actor, task), on a system actor.
- Compare-and-set state, a lease and takeover, as in the tombstones.
- `consume_once` for the single-use parts.

**Prior art for task-scoped tokens:**
- **GitHub Actions** `GITHUB_TOKEN`: one per job, expires when the job
  finishes, limited to the repository.
- **Buildkite** job tokens: one per job, stop working at job end, but scope
  wider than the job. Expiry limits how long a leak matters, not what the
  token reaches.
- **Step Functions task tokens**: up to 2048 characters, `SendTaskSuccess`
  / `SendTaskFailure` / `SendTaskHeartbeat`, `HeartbeatSeconds`.
  `TaskTimedOut` when "the task token has either expired or the task
  associated with the token has already been closed". A new token is
  issued on retry.
- **Temporal**: completion by task token, or by namespace + workflow id +
  activity id.

**[inference]** A task token that follows these patterns:
- is minted per task and per attempt
- has only its digest stored
- is accepted for one task's status, artifact and completion writes only
- is refused once the task is terminal
- has a deadline that heartbeats extend
- is rotated when another process takes the task over
- loses to cancel

### Hand-over patterns

**ECS RunTask** (<https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RunTask.html>):
- Overrides: "A total of 8192 characters", JSON formatting included.
- `clientToken`: up to 64 characters, for idempotency (the A2A task id
  fits).
- `startedBy`: up to 128 characters, filterable.
- `overrides.taskRoleArn` can be set per run.
- The RunTask response echoes the override environment. **[inference]**
  Anyone with `ecs:DescribeTasks` can read it.
- AWS on secrets: "there's an elevated risk of data leakage with
  environment variables". Use a sidecar or task-role reads instead.

**[inference]** Pass the task id in the environment. Pass either a
short-lived task token there, or nothing secret, and have the worker
exchange its task role for access. A task role is per task definition,
not per job, so it cannot say "only task X" in ActingWeb terms.

**Lambda async invocation:**
- 1 MB payload (raised from 256 KB in October 2025).
- 15 minutes maximum.
- Retried twice on error. "it's possible for it to receive the same event
  … multiple times".

**SQS:**
- 1 MiB messages.
- Visibility timeout up to 12 hours. **[inference]** For longer work,
  claim in the store and rely on the task lease.

**Step Functions `.waitForTaskToken`:** see above. ECS and Fargate support
it, so a consumer could run the worker under Step Functions and map its
token to the A2A task. That is a consumer choice, not a library one.

**Idempotent completion [inference]:**
- Use the A2A task id as the launch idempotency key.
- Make completion a compare-and-set that succeeds only while the task is
  non-terminal and the lease or version matches.
- Treat an identical repeat completion as success.

### Prior art

**a2a-python 1.3.1** (`src/a2a/server/`):
- **`TaskStore`**: `save`, `get`, `list`, `delete`, each with a
  `ServerCallContext`.
- **`DatabaseTaskStore`**:
  - owner-scoped on every operation (`owner_resolver` defaults to
    `context.user.user_name`)
  - `tasks(id, context_id NOT NULL, kind, owner, last_updated, status JSON,
    artifacts JSON, history JSON, protocol_version, metadata)` with index
    `(owner, last_updated)`
  - `save` is an unconditional merge: last write wins
  - the paging cursor is `(last_updated, id)`, and the code warns that a
    task updated mid-listing can be skipped
- **`TaskUpdater`**: `update_status`, `add_artifact`, `complete`,
  `failed`, `reject`, `cancel`, `requires_input`, … It refuses updates
  after terminal in the updater instance only.
- **Cluster mode** (`a2a.server.cluster`, since 1.2.0):
  - `VersionedTaskStore.save(..., prev_version)` raises
    `ConcurrentTaskModificationError` on a version mismatch
  - a write to CANCELED "overwrites a non-terminal stored task without a
    version check", so cancel wins
  - an event log in `task_events`
  - the agent still runs inside one replica, and nothing covers external
    workers
- **Maintainers on out-of-request work** (issues #471, #446): the event
  queue is not request-scoped. Use push notifications. Vendor queues stay
  out of core.

**Redis Agent Mesh A2A integration** (third party, beta, SDK 1.2.x):
- "One process can start a Task and another process can finish it"
- leases by heartbeat (5 s interval, 15 s alive TTL); a lost producer
  fails the task unless takeover is enabled
- fencing: a stale process's save is rejected
- resume by sending a message with `task_id` + `context_id` through the
  handler with an owner context built in trusted code
- "A later write cannot revive a terminal Task"
- "Task IDs and event cursors grant no access"
- retention 7 days active, 1 day terminal

**Emm's one-off task queue** (`../actingweb_mcp`):
- Tasks are items in the property list `memory_requests` with a per-type
  integer id (`repositories/local_memory_repository.py:207-347`).
- States: `active` / `ready` / `completed`.
- Claim: `claimed_at` and `claimed_by` with a 60-minute lease
  (`hooks/mcp/tools/work_on_task.py:52-83, 399-427, 921-931`).
  - The claim write is best-effort: a failed write still hands out the
    task.
  - Release only if `claimed_at` still matches.
- Optimistic `expected_updated_at` on updates.
- Completion stamps `completed_at`, `completed_by` and `result_output_id`
  (`helpers/task_metadata.py:92-111`).
- Run records carry a 3-hour deadline evaluated at read
  (`repositories/run_records_repo.py:99-202`).
- **Worker model:** external MCP clients pull the work. Emm has no ECS,
  SQS, Step Functions or Lambda-invoke code or permissions
  (`serverless.yml:197-241`).

### Notifying the caller

- **Polling:** `GetTask` always works and needs nothing new.
- **A2A push:** a persistent config store, outbound delivery with
  authentication, SSRF guards, at-least-once delivery (companion research,
  "Streaming and push"). `callback_sender` is the nearest outbound
  machinery.
- **An ActingWeb peer as caller:** attributes notify no subscriber.
  `SubscriptionManager.notify_subscribers(target, data, …)` works for any
  target string, with the caller passing the value
  (`interface/subscription_manager.py:724-761`). A task change could be
  announced on a target such as `a2a-tasks` **[inference]**, reusing
  sequence numbers and resync. This is not A2A.
- **Within the server:** blocking `SendMessage` and streaming both need
  the request-serving process to learn of a change written by the worker.
  With no event bus, that means re-reading the store **[inference]**.

### Cleanup

- **Actor deletion** removes every attribute row under the actor id,
  `$aux` included (`actor.py:1711-1712`, `Buckets.delete`). Task rows under
  the actor go with it. Rows under a system actor (a token index) do not.
- **Trust deletion** cleans hard-coded per-peer state only
  (`actor.py:3363-3506`): subscriptions, `remote:<peer>`, callback state,
  peer caches, then `Trust.delete`. A caller's tasks would need a new line
  there or an application `trust_deleted` hook.
- **Operator commands** (`actingweb-peer-state prune`,
  `actingweb-deletions`) know no task bucket.
- **The PostgreSQL reaper** covers a new bucket only if a `delete_expired`
  caller names it.

## MCP tasks: can the same store serve `/mcp` later? (verified 2026-11-25)

Added after the owner made tasks a general actor feature (main note, owner
decision 11). It answers the "to verify" line under decision 13.

**Two incompatible designs exist.**

- **2025-11-25: experimental, in the core protocol.**
  - A client adds a `task` object (with `ttl`) to `tools/call`.
  - The server answers `CreateTaskResult`.
  - The methods are `tasks/get`, `tasks/result`, `tasks/list` and
    `tasks/cancel`.
  - `tasks/result` "MUST block the response until the task reaches a
    terminal status".
  - Tools state `execution.taskSupport` (`required`, `optional` or
    `forbidden`).
  - The library already negotiates this version (`mcp/protocol.py:28-33`)
    but declares no `tasks` capability.
- **2026-07-28: moved out of the core into the extension
  `io.modelcontextprotocol/tasks`.**
  - Upstream's migration note: anyone who shipped the 2025-11-25 version
    "will need to migrate".
  - The server alone decides, per `tools/call`, whether to return a task.
  - The methods are `tasks/get`, `tasks/update` (input responses) and
    `tasks/cancel`, which only acknowledges.
  - `tasks/result` and `tasks/list` are removed. The listing went because,
    without sessions, it "can't be scoped safely".
  - A server "MUST NOT return CreateTaskResult until the task is durably
    created".
  - The library speaks only up to 2025-11-25; supporting 2026-07-28 is
    `thoughts/todo/mcp-2026-07-28-dual-era-support.md`.

**How the decided store fits.**

| Owner decision | MCP 2025-11-25 | MCP 2026-07-28 |
| --- | --- | --- |
| Rows keyed by origin (11) | Fits: tasks "MUST" be bound to the authorization context, and `tasks/list` returns only the caller's. The origin is the MCP client's trust peer id, so each client sees its own tasks. | Fits: authorization is checked "on each task-related request", and there is no listing. |
| The handle and the worker (12, 13) | Front-end neutral | Front-end neutral |
| Return at once (14) | Fits creation (`CreateTaskResult` "as soon as possible"). Conflicts with `tasks/result`, which must block, the same problem as A2A's rule that the server must wait. | Fits: there is no blocking method. |
| Cancel wins (15) | Fits: the server "MUST transition the task to `cancelled`" before answering, and the task stays cancelled "even if execution continues". | Fits: cancel is cooperative, and moving to cancelled at once is allowed. |
| 7 days' retention (15) | Fits: the receiver "MAY override the requested `ttl`" and may delete after it. Report `ttl` as expiry minus `createdAt`. | Fits: `ttlMs` "MAY change", and after it the server may fail or delete the task. |
| Polling only (16) | Fits: requestors "MUST NOT rely on" `notifications/tasks/status`. | Fits: notifications go through `subscriptions/listen`; polling with `pollIntervalMs` is the base case. |

**Status sets.**

| Front end | Statuses |
| --- | --- |
| MCP (both versions) | `working`, `input_required`, `completed`, `failed`, `cancelled` |
| A2A | adds `submitted`, `rejected` and `auth-required`; uses the spelling `canceled` |

The store keeps one internal set, a superset of both, and each front end maps
it to its own names. MCP has no `submitted`: a task "MUST begin in the
`working` status".

**Three things the A2A tasks plan can design in now at no cost:**

1. **The result is stored as opaque JSON together with the task kind.** Each
   front end shapes it: an A2A artifact or message, or an MCP
   `CallToolResult`.
2. **The task row is written before the dispatch hook runs, and before the
   answer.** MCP 2026-07-28 requires this; for A2A it means a worker never
   races its own task's creation.
3. **Task ids come from a secure random generator.** MCP 2026-07-28 allows
   ids to act as bearer handles and requires "sufficient entropy".

**A gap in the decisions: `input_required`.**

- Both protocols let a running task ask its caller for input:
  - A2A: `input-required`, then a `SendMessage` with the task id
  - MCP 2026-07-28: `inputRequests`, then `tasks/update`
- Decisions 11–16 do not cover it.
- The first round can leave it out if the store reserves the state and the
  handle has no method to enter it yet. That is a scope line for the plan.

**Recommendation for MCP:**

- **Serve MCP tasks only under the 2026-07-28 extension,** after dual-era
  support.
- **Do not implement the experimental 2025-11-25 version.**
  - Its `tasks/result` must block, the problem decision 14 avoided for A2A.
  - It needs a listing.
  - Upstream has replaced it with a design that is not wire-compatible.

**Sources:**
- <https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks>
- <https://tasks.extensions.modelcontextprotocol.io/specification/2026-07-28/tasks>
- <https://modelcontextprotocol.io/seps/2663-tasks-extension>: SEP-2663. The
  page was read only in part; the migration details beyond the spec page
  rest on the part that was not read verbatim.
- <https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/>

## Acceptance criteria this adds (candidates for the plan)

The feature document has no AC for long-running tasks. These are areas the
plan would need criteria for; they are not written as ACs here.

- A task created by `SendMessage` is readable by `GetTask` for its caller
  only.
- A worker started with the hand-over context can move the task through
  `WORKING` to a terminal state.
- A write after a terminal state is refused and changes nothing.
- `CancelTask` on a running task wins over a worker's later completion.
- `ListTasks` returns only the caller's tasks, paged and sorted, with
  `totalSize`.
- A stale or second worker is fenced.
- A task token stops working at a terminal state and at its deadline.
- Deleting the caller's trust removes or orphans its tasks by a stated
  rule.
- The blocking default behaves as decided (Decision T5).
- All of this holds on both backends, and the HTTP parts on both
  integrations.

**Test harness.** The deletion-lease tests and `single_use` tests are the
models for compare-and-set races. The two-framework in-process client
covers routes. A worker is a test function that builds a bare `Config` and
uses the same store.

## Decisions Needed

### Decision T1: Where a task lives

**Options:**
1. **Attributes under the actor** (bucket e.g. `a2a_tasks`): one small
   status row per task, history and artifacts in their own rows.
   - Pros:
     - no schema change
     - point read and compare-and-set exist
     - private
     - wiped with the actor
   - Cons:
     - `ListTasks` reads the whole bucket and filters in memory
     - a 400 KB cap per scalar attribute on DynamoDB (spanning covers
       list items only; see option 2)
     - a new PostgreSQL reaper entry
     - a per-peer cleanup line
2. **An attribute list per task for history and artifacts**, plus option
   1's status row.
   - Pros: large artifacts span.
   - Cons: metadata-row contention per append, though limited to one task.
3. **A dedicated `tasks` table.**
   - Pros:
     - indexed paging by (actor, caller, status time)
     - a version column
     - a clean `totalSize`
   - Cons:
     - a model, a migration, `verify_tables` and readiness on both
       backends
     - an operator TTL step on DynamoDB
     - Emm runs with `AWS_DB_AUTO_CREATE_TABLES=false`
4. **A property list item per task.** Listed for completeness.
   - Cons:
     - handles are not stable ids
     - shared-meta contention
     - no TTL
     - peer-visible and subscriber-notified by default

### Decision T2: How the worker reaches the task

**Options:**
1. **Direct library access** with a bare or app-built `Config`, plus a
   library task handle that checks a task token (path C).
   - Pros:
     - matches how Emm's Lambdas and the operator commands already work
     - no route needed
   - Cons:
     - the boundary is the database credentials
     - the worker must replicate the app's configuration (indexed
       properties, hooks, delivery settings) or build the app object
2. **HTTP back to the application** with a task token (path B).
   - Pros:
     - the worker needs no database access
     - the library enforces scope
     - fits any language
   - Cons:
     - a new authenticated route (on A2A itself or ActingWeb-native)
     - a third bearer kind on top of the two in the companion research
3. **Both**, with one token format.

### Decision T2b: What gives a worker its single-actor context

Owner decision 4 rules out a cross-actor entry point. The options for
how a worker gets its one actor:
1. **`get_by_id` with an id from the hand-over** (today's API).
   - Pros: exists and is documented; no new surface.
   - Cons: the id is whatever the worker's code passes; the result is an
     owner-level view of the whole actor, not the task.
2. **A credential-derived handle** (path C): the worker presents the task
   token, and the library resolves the actor and task and returns a handle
   scoped to them, with no actor-id parameter.
   - Pros: the same shape as HTTP (the credential names the actor); the
     handle can limit stores to what the task needs; the token can be
     revoked, fenced and expired.
   - Cons: new API and token; with database credentials in the worker it
     is a discipline the API encourages, not isolation.
3. **HTTP only** (path B): the worker has no database access.
   - Pros: the one-actor rule is enforced by the server, as for any peer.
   - Cons: a new route and bearer kind; each write is a round trip.

Options 2 and 3 can share one token and one handle interface: the
handle's backend is either the store (in-process) or the route (remote).

### Decision T3: The task token

**Options:**
1. **A new task-scoped token.**
   - random, digest stored with the task and in a global index
   - TTL extended by heartbeat
   - refused at terminal, rotated on takeover
   - Pros: matches the GitHub, Step Functions and Temporal patterns.
   - Cons: new code on an authentication path.
2. **Reuse an existing token kind** (an SPA token with a TTL, or an `aw_`
   client-credentials token).
   - Pros: exists.
   - Cons: not limited to the task. An SPA token authenticates as the
     creator, and an `aw_` token is accepted only on `/mcp`.
3. **No token**: the worker is trusted by its database access and passes
   only the task id.
   - Pros: simplest.
   - Cons: no fencing beyond the compare-and-set version; any process with
     the id and the database can complete it.

### Decision T4: What is handed over, and how

**Options:**
1. **Task id + token in environment variables**, with the library's
   environment-variable names as the contract (for example
   `ACTINGWEB_TASK_ID`, `ACTINGWEB_TASK_TOKEN`; names illustrative).
   - Pros: works for ECS, Lambda payloads and SQS messages alike.
   - Cons: ECS echoes environment values in the task description
     **[inference]**, so the token should be short-lived.
2. **Task id only**, with the worker exchanging its own identity (a task
   role, or a database credential) for access.
   - Pros: no secret in transit.
   - Cons: no per-task scope.
3. **The library supplies a dispatch hook** (for example `task_dispatch`)
   that receives a hand-over object and returns. The consumer's hook calls
   ECS, Lambda or SQS. The library never imports AWS SDKs.

### Decision T5: `SendMessage` with the blocking default

**Options:**
1. **Hold the request** and re-read the store until terminal or
   interrupted, bounded by a configured wait. Return the task as it is when
   the bound runs out.
2. **Require `returnImmediately: true`** for skills marked long-running,
   and reject otherwise.
3. **Always return the task in `SUBMITTED` or `WORKING` immediately** for
   handed-off work, and document the deviation.

### Decision T6: Cancel, takeover and retention

**Cancel:**
1. Cancel wins over a non-terminal task without a version check (as in the
   a2a-python cluster store), and the worker's next write is refused.
2. Cancel requests a stop and the worker confirms. A `cancel` hook tells
   the consumer to stop its container.

**Takeover:**
1. A lapsed lease fails the task.
2. A lapsed lease allows a new worker with a rotated token (as with
   deletion tombstones).

**Retention:**
- choose a TTL for terminal tasks and for active ones
- document it (A2A SHOULD)
- decide what deleting the caller's trust does to its tasks: delete them,
  or keep them for the owner

### Decision T7: Notification beyond polling

**Options:**
1. **Polling only** this round. Push and streaming stay undecided.
2. **A2A push** for long tasks, on the callback sender.
3. **An ActingWeb subscription target** for ActingWeb-peer callers.

## Release shape

A task store, a token kind, routes and a dispatch hook make this a minor
at least (`CONTRIBUTING.rst:183-207`). A dedicated table is also a schema
change with an operator step on DynamoDB when tables are not
auto-created. This adds to companion Decision 9; it does not change its
options.

## Code References

**Attributes and lists**
- `actingweb/attribute.py:300-730` - attributes wrapper: compare-and-set, create-if-absent, TTL
- `actingweb/db/dynamodb/attribute.py:65-94, 112, 141-151, 193-226, 255-292, 305-511, 781-798` - DynamoDB attribute semantics
- `actingweb/db/postgresql/attribute.py:234-236, 268-276, 354-392, 428-505, 538-765, 1091-1135` - PostgreSQL attribute semantics
- `actingweb/list_core.py:386-422, 2100-2159, 2809-2872, 3592-3918` - list handles, metadata touch, append_once, find, compare-and-set by handle

**Lifecycle records**
- `actingweb/single_use.py:100-225, 348-369` - consume once, confirmed delete, purge throttle
- `actingweb/deletion.py:318-620` - leased tombstones: claim, renew, release, takeover
- `actingweb/oauth2_server/token_manager.py:162-230, 1142-1170, 1713-1781, 2197-2261` - pending authorizations, code index, access tokens, reaping

**Routes and cleanup**
- `actingweb/handlers/actions.py:159-341` - no Location or 201
- `docs/protocol/actingweb-spec.rst:1755-1792` - specified async action pattern
- `actingweb/actor.py:1611-1741, 3363-3506` - actor and per-peer cleanup

**Running outside a request**
- `actingweb/interface/actor_interface.py:172-197` - `get_by_id`
- `actingweb/interface/app.py:1669-1850` - `get_config`, `check_ready`
- `actingweb/callback_sender.py:110-150, 278-326` - delivery without a request
- `actingweb/interface/subscription_manager.py:724-761` - notify any target
- `actingweb/maintenance/property_lookup.py:176-184`, `actingweb/maintenance/peer_state.py:120-124` - config outside a request
- `actingweb/request_context.py:201-240` - setting context in a worker

**Consumer (Emm AI)**
- `../actingweb_mcp/helpers/config.py:107-149`, `cleanup_handler.py:36-77`, `websocket_handlers/default.py:365-437` - Emm's processes outside a request
- `../actingweb_mcp/hooks/mcp/tools/work_on_task.py:52-83, 399-427, 921-931` and `helpers/task_metadata.py:92-111` - Emm's task claim, lease and completion
- `../actingweb_mcp/serverless.yml:197-347` - Emm's infrastructure: no ECS or queues

## External References

**A2A**
- <https://a2a-protocol.org/latest/specification/> - Task, ListTasks, CancelTask, SendMessageConfiguration, retention
- <https://raw.githubusercontent.com/a2aproject/A2A/main/specification/a2a.proto> - field definitions
- <https://a2a-protocol.org/latest/topics/life-of-a-task/> - terminal tasks, continuation, `referenceTaskIds`

**SDKs and prior art**
- <https://github.com/a2aproject/a2a-python> - `TaskStore`, `DatabaseTaskStore`, `TaskUpdater`, cluster mode (PR #1281); issues #446, #471
- <https://raw.githubusercontent.com/a2aproject/a2a-js/main/src/server/store.ts> - JS `TaskStore` scoping guidance
- <https://redis.io/docs/latest/develop/ai/context-engine/agent-mesh/a2a-sdk/> - cross-process task hand-off with leases and fencing (third party, beta)

**AWS**
- <https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_RunTask.html> - overrides limit, `clientToken`, `startedBy`
- <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data.html> - secrets and environment variables
- <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html> - task roles
- <https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html> - `.waitForTaskToken`
- <https://docs.aws.amazon.com/step-functions/latest/apireference/API_SendTaskSuccess.html> - task token limits and errors
- <https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html> - async retries and duplicates
- <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/AboutVT.html> - visibility timeout

**Job tokens elsewhere**
- <https://docs.github.com/en/actions/concepts/security/github_token> - per-job token
- <https://buildkite.com/docs/platform/security/tokens> - per-job token scope
- <https://docs.temporal.io/develop/python/activities/asynchronous-activity> - async completion by token or ids
