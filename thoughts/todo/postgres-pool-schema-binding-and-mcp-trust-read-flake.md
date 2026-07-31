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

## Not fixed: residual flake

`tests/integration/test_mcp_resource_regression.py::TestMCPResourceRegressions`
still fails intermittently — roughly **1 run in 6** locally after all of the
above — with `-32003 Access denied: no trust relationship resolved for this
client`.

Two observations that should shorten the next investigation:

- **The failing runs are systematically the slow ones.** Passing runs land at
  ~26s and ~1329 warnings; failing runs at ~36s and ~1273 warnings. That is not
  random jitter — the failing runs take a materially different path through the
  suite, and the lower warning count suggests some fixture work did not happen.
  Start by diffing what a failing run does differently rather than by looking
  at the resolver again.
- **Backend crossover is no longer the mechanism.** Instrumented locally at
  resolve time, `self.config` and the actor's config are the *same object* and
  both bind `actingweb.db.postgresql.trust`, yet the trust list still comes back
  empty. So whatever remains is on the PostgreSQL read/write path itself, not
  in config or singleton scoping.

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

### Where to look next

The remaining candidate is the **write** side rather than the read: whether the
trust `INSERT` performed during dynamic client registration is reliably
committed and visible before the token is issued and the first MCP request
arrives. `create_or_update_oauth_trust` logging "Successfully created" proves
the Python call returned, not that the transaction committed on the pooled
connection it used.

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
