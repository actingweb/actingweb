# TODO: PostgreSQL pool schema binding, and a residual MCP trust-read flake

Found while getting `bug/trust_mcp_cache` (PR #117) green in CI. The
authorization work in `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md`
made missing trust **fail-closed**, which turned a previously-silent class of
failure into a visible one. Part of it is fixed; part is not.

## What this is, in one line

An MCP trust lookup can read an **empty trust list** for an actor whose trust
row exists. Before fail-closed that granted **full access** and every test
passed. After fail-closed it returns `-32003`.

That is the important part and it is worth restating: the empty-read path was
always there, and the old behavior was to treat "I could not read this actor's
trust relationships" as "allow everything."

## Fixed: pool connections bound to the wrong schema

**Cause.** `actingweb/db/postgresql/connection.py` keeps a module-level `_pool`.
`psycopg_pool` runs the `configure` hook (which issues `SET search_path`) **once
per physical connection, when that connection is created** — not per checkout.
So each connection permanently carries whatever `PG_DB_PREFIX` said at the
moment it was opened.

In a parallel test worker, unit tests do not use the `setup_database` fixture.
Any PostgreSQL access before that fixture runs creates the pool with connections
bound to the bare `public` schema. Connections created later — as the pool grows
from `min_size=2` toward `max_size=10` under load — bind to the worker schema.
The pool then holds a **mix**, and which connection a query gets is
load-dependent. A write could land in `public` while the read went to
`test_wN_public` and came back empty, **with no error**, because CI migrates
`public` too, so the table exists and is simply empty.

**Evidence.** Instrumenting the resolver to log `current_schema()` and row
counts produced, on a failing run:

```
client=mcp_fa861... actor=_actingweb_oauth2 n=0 schema=test_w2_public total=0 mine=0
```

— the read was on the correct worker schema and the entire `trusts` table was
empty. Querying the database directly then found the leaked row sitting in
`public`:

```
_actingweb_oauth2 | oauth2_client:mcp_76d6...:mcp_76d6... | oauth2_client | mcp_76d6...
```

**Fix applied.** `tests/integration/conftest.py::setup_database` now sets the
`PG_DB_*` environment (mirroring the DynamoDB branch, which always did) and then
calls `close_pool()`, so any pool built before the prefix was known is discarded
and rebuilt against the worker schema.

**Result.** Failure rate on `pytest tests/ -n 4 --dist loadgroup --cov` against
PostgreSQL dropped from roughly 40–50% of runs to about 12% (1 of 8), and stray
rows in `public` went from present to **zero** across 8 consecutive full runs.

## Also fixed: config-bound singletons served one app's state to another

This was the mechanism **in CI**, proven with a temporary diagnostic pushed to
the branch and read back from the CI logs. At client-registration time the
ActingWeb API reported 37 trust relationships for `_actingweb_oauth2` while a
direct SQL query on the same worker's schema, in the same process, reported
`trusts_total=0` — and every worker saw the *same* 37 peers. Two different
stores were in play.

Cause: `get_actingweb_oauth2_server(config)` (and five siblings) bound to the
**first** config the process ever passed and ignored the argument thereafter —
one of them documented this outright ("config parameter kept for interface
consistency but not used"). So a PostgreSQL-configured app was handed an OAuth2
server still bound to an earlier DynamoDB-configured one: registration wrote
the trust row to DynamoDB while resolution read PostgreSQL. In the PostgreSQL
CI leg DynamoDB Local is running too, and `AWS_DB_PREFIX` is only set in the
DynamoDB branch of `setup_database`, so those writes went to unprefixed tables
shared by all four workers — exactly the observed signature.

Fixed by making all six getters rebuild when handed a different `Config`, with
`tests/test_config_bound_singletons.py` as a regression test. Two related
scoping fixes went in alongside: `_actor_cache` in `mcp.py` now records which
config built each `ActorInterface` (it is keyed by actor id alone, and the
`_actingweb_oauth2` system actor is shared), and `get_pool()` now rebuilds when
the configured schema changes instead of serving a pool with connections bound
to different schemas.

## Root cause, found: the singleton fix did not go deep enough

The first round of singleton fixes rebuilt `get_actingweb_oauth2_server()` when
handed a new config — but `ActingWebOAuth2Server.__init__` immediately pulls
**three further singletons** (`oauth2_server.py:40-42`):

```python
self.client_registry = get_mcp_client_registry(config)
self.token_manager  = get_actingweb_token_manager(config)
self.state_manager  = get_oauth2_state_manager(config)
```

None of those three consulted the config they were given. So the wrapper
rebound and its children did not. `get_mcp_client_registry` is the **write**
side of the crossover — it is what dynamic client registration uses to create
the trust row — which is exactly the `CREATE ... db=dynamodb` half of the CI
diagnostic. Reproduced in four lines:

```python
get_actingweb_oauth2_server(dynamo_cfg)
s = get_actingweb_oauth2_server(postgres_cfg)
s.config.database            # 'postgresql'  -- the wrapper rebound
s.client_registry.config.database  # 'dynamodb'  <-- registration writes here
```

An AST sweep of the package found four unguarded getters in total:
`get_mcp_client_registry`, `get_actingweb_token_manager`,
`get_oauth2_state_manager`, and the `peer_profile` store pair. All four now
rebuild on a different config, and `tests/test_config_bound_singletons.py`
gained a structural test that walks `actingweb/` and fails on any future
`global`-caching function that takes a `config` without comparing against it —
so there cannot be a batch four.

**Provenance of the DynamoDB config, answered.** A pytest plugin recording the
first bind of each singleton per xdist worker, run against PostgreSQL:

```
gw0  client_registry <- tests/test_oauth2_server_lazy_authenticator.py::...::test_backward_compat_properties  db=dynamodb
gw3  client_registry <- tests/test_oauth2_server_lazy_authenticator.py::...::test_caches_per_provider          db=dynamodb
gw1  client_registry <- tests/integration/test_mcp_basic.py::...                                              db=postgresql
```

A **unit test** constructing `Config(database="dynamodb")` binds the registry
for the life of the worker. Whether that happens before the MCP integration
group lands on the same worker is pure scheduling luck — which is the whole
explanation for the intermittency, and for the "failing runs are the slow ones
with fewer warnings" observation: those are runs with a different distribution
of tests across workers.

### Two earlier leads in this document were wrong

Both are struck out rather than deleted, because following them costs real time:

- ~~"The remaining candidate is the **write** side: whether the trust `INSERT`
  is reliably committed and visible."~~ The INSERT committed fine. It committed
  to **DynamoDB**. Nothing was wrong with PostgreSQL transaction visibility.
- ~~"Backend crossover is no longer the mechanism."~~ That observation was taken
  at *resolve* time, where the config genuinely was PostgreSQL. Resolve was
  always correct; the **write** was the one going to the wrong backend, so
  instrumenting the reader could never see it.

## Fixed: residual flake

`tests/integration/test_mcp_resource_regression.py::TestMCPResourceRegressions`
failed intermittently — roughly **1 run in 6** locally after the pool fix —
with `-32003 Access denied: no trust relationship resolved for this client`.

### The mechanism, and its provenance

A second CI diagnostic (pushed temporarily, read back from the logs, then
reverted) pinned it down for the client that failed:

```
CREATE  ... client=mcp_fd89... cfg=139984130144080 db=actingweb.db.dynamodb.trust
RESOLVE ... client=mcp_fd89... cfg=139984128041488 db=actingweb.db.postgresql.trust
```

Same process, same actor, same client: **registration writes the trust row to
DynamoDB while resolution reads PostgreSQL.** Two distinct `Config` objects
with two different backends are live at once, and the trust is simply not where
the reader looks. Everything else — the empty list, `trusts_total=0` in the
worker schema, all workers seeing an identical peer list (unprefixed, shared
DynamoDB tables, since `AWS_DB_PREFIX` is only set in the DynamoDB branch of
`setup_database`) — follows from that one fact.

The DynamoDB `Config` at CREATE comes from
`get_mcp_client_registry()`, which was still bound to whichever config first
reached it in that worker — see "Root cause, found" above. The three earlier
exclusions were each individually correct and collectively misleading: the
*wrapper* rebound per config, `ActingWebApp` does memoize its `Config`, and the
route wiring does pass the right one. All true, and none of it reached the
three child singletons the wrapper constructs.

The "failing runs are the slow ones" observation now has an explanation too:
run-to-run timing differences come from how xdist distributes tests, and that
distribution is exactly what decides whether a DynamoDB unit test binds
`_client_registry` before the MCP integration group runs on the same worker.

### Reproduction recipe

```bash
docker compose -f docker-compose.test.yml up -d
cd actingweb/db/postgresql && PG_DB_HOST=localhost PG_DB_PORT=5433 \
  PG_DB_NAME=actingweb_test PG_DB_USER=actingweb PG_DB_PASSWORD=testpassword \
  poetry run alembic upgrade head && cd -

# Loop this; expect a failure roughly 1 run in 8.
DATABASE_BACKEND=postgresql PG_DB_HOST=localhost PG_DB_PORT=5433 \
PG_DB_NAME=actingweb_test PG_DB_USER=actingweb PG_DB_PASSWORD=testpassword \
poetry run pytest tests/ -m "not benchmark" -n 4 --dist loadgroup \
  --max-worker-restart=0 --timeout=300 --timeout-method=thread \
  -q --tb=line --cov=actingweb --cov-report=
```

Notes that matter for reproducing it:

- **`--cov` is load-bearing.** Without coverage the flake essentially does not
  appear; coverage slows execution and changes thread interleaving and pool
  growth.
- **The full `tests/` set is required.** `tests/integration/` alone does not
  reproduce it.
- **DynamoDB never reproduces it.** It has no connection pool and reads its
  prefix per operation.
- **CI reruns do not help.** `regression_oauth2_client` is a *module-scoped*
  fixture, so all three tests and all `--reruns` attempts share one already-
  registered client. If its trust is unreadable once, every retry fails too —
  which is why CI reported "no flakiness detected" alongside 3 failures.

### What has been ruled out

- **Resolver matching.** Both arms provably match the peer id in question
  (`oauth2_client:<client_id>:<client_id>`, `established_via="oauth2_client"`,
  `oauth_client_id` set). The diagnostic shows the resolver receives an **empty
  list**, so it never gets as far as matching.
- **A cap or `LIMIT` on the trust list read.** There is none.
- **Column mapping.** The PostgreSQL list path returns both `established_via`
  and `oauth_client_id`.
- **A stale cached list.** `get_trust_relationships()` builds a fresh `Trusts`
  each call, and `get_trust_list()` returns a fresh instance.
- **Cross-worker interference.** Each worker has its own schema.
- **A stale negative cache entry.** The failing runs show the resolver executing
  twice, ~10s apart (the negative TTL), both times reading empty.

### What this masked — the part that outlives the flake

The flake was the *visible* symptom. The more consequential finding is what the
crossover did to test coverage while everything was green.

Measured directly, by wrapping each getter to record any caller handed an
instance bound to a backend other than the one it asked for, on a full
PostgreSQL run **before** the fix:

```
10 tests served a wrong-backend singleton
   7  tests/integration/test_trust_oauth_integration.py
   1  tests/integration/test_mcp_basic.py
   1  tests/integration/test_mcp_client_descriptions.py
   1  tests/integration/test_oauth2_client_manager.py
```

After the fix, the same measurement reports **0**.

Named, from that run — every one of these *passed*:

- `test_trust_oauth_integration.py::TestTrustCreationOnClientRegistration::test_client_registration_creates_trust_relationship`
- `…::test_multiple_clients_create_multiple_trusts`
- `…::test_trust_relationship_has_correct_trust_type`
- `…::TestTrustAttributesForOAuth::test_trust_has_oauth_client_id_attribute`
- `…::TestTrustAttributesForOAuth::test_trust_has_peer_type_mcp`
- `…::TestPermissionChecksWithOAuth::test_oauth_client_trust_uses_mcp_client_permissions`
- `…::TestPermissionChecksWithOAuth::test_individual_permissions_can_override_oauth_client_defaults`
- `test_mcp_basic.py::TestMCPAuthentication::test_mcp_initialize`
- `test_mcp_client_descriptions.py::TestClientDescriptionDetection::test_chatgpt_client_detection`
- `test_oauth2_client_manager.py::TestOAuth2ClientRetrieval::test_get_client_wrong_actor_returns_none`

**They passed against DynamoDB Local, which is running in the PostgreSQL CI leg
too.** So the PostgreSQL leg was not exercising MCP dynamic client
registration, token management, or OAuth2 state handling against PostgreSQL at
all on the affected workers — it was re-testing DynamoDB and reporting green.
That is a coverage hole that looked like passing coverage, and it is the
"something deeper" underneath the flake.

The exact membership of that set varies per run, because it depends on which
worker binds the singleton first. The *shape* does not: it is the OAuth2/MCP
registration surface, and it was reachable on any run.

Compounding it: `AWS_DB_PREFIX` is set only in the DynamoDB branch of
`setup_database`, so in the PostgreSQL leg those stray DynamoDB writes landed
in **unprefixed tables shared by all four xdist workers**. That is the origin
of the earlier "every worker reported the same 37 peers" observation — any
count assertion over trusts, peers, clients or tokens in the PostgreSQL leg was
reading a cross-worker-polluted shared table.

Worth noting what is *not* affected: `_token_cache`, `_mcp_client_info_cache`
and `_trust_cache` in `mcp.py` are keyed by token, client id, and
`(actor_id, client_id)` respectively. Those keys are unique per application, so
they cannot collide across apps the way `_actor_cache` did — `_actor_cache` was
keyed by actor id alone and the `_actingweb_oauth2` system actor is shared,
which is why it needed the config-scoping fix and these do not.

## Library-level footgun worth fixing separately

Independent of the tests: `get_pool()` binds the schema at pool creation and
never revisits it. Any application that changes `PG_DB_PREFIX`/`PG_DB_SCHEMA`
after first database use — or that runs two ActingWeb configurations with
different schemas in one interpreter — silently keeps querying the first schema,
and reads come back **empty rather than erroring**. Consider having `get_pool()`
detect a schema change and rebuild, or refuse to serve a connection whose bound
schema no longer matches the configured one. This is the same "module-global
state assumes one application per interpreter" theme recorded in
[[mcp-cache-lifecycle-and-revocation]].

## Related

- `thoughts/plans/2026-07-30-mcp-trust-cache-crosses-clients.md`
- `thoughts/verifications/2026-07-31-mcp-trust-cache-crosses-clients.md`
- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — item 6 there
  ("registration doesn't hard-fail when trust creation fails") is the sibling
  case: both end in a client holding valid credentials that can never authorize.
