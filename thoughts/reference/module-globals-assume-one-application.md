# Module globals assume one application per interpreter

ActingWeb caches a lot of state in module-level globals: singleton stores,
registries, connection pools, request caches. Every one of them carries an
unwritten assumption — **that the process hosts exactly one ActingWeb
application**. When that assumption breaks, the failures are quiet: reads
return empty instead of raising, and callers that treat "no rows" as "nothing
there" carry on.

This note records the pattern, its three known instances, and the checks that
now guard it. It exists because the same defect was found three separate times
by tripping over three different symptoms.

## The pattern

```python
_thing: Thing | None = None

def get_thing(config: Config) -> Thing:
    global _thing
    if _thing is None:          # <-- ignores `config` forever after the first call
        _thing = Thing(config)
    return _thing
```

The getter advertises that it depends on `config` and then binds to whichever
config arrived first. A second application in the same interpreter is served
the first application's instance. If the two use different database backends,
**writes and reads land in different stores**.

That last part is what makes it dangerous rather than merely untidy. A missing
row is not an error. Code downstream sees an empty list and does something
reasonable with it — which, before MCP trust resolution was made fail-closed,
meant granting full access.

## Where this actually bites

Two ActingWeb applications in one interpreter is not exotic:

- The test suite does it routinely — unit tests build `Config(database="dynamodb")`
  while the session runs under `DATABASE_BACKEND=postgresql`.
- A host process embedding two ActingWeb apps (multi-tenant, or a migration
  running old and new side by side) does it in production.

`Config.__init__` reads `os.getenv("DATABASE_BACKEND", "dynamodb")` at
**construction time** (`actingweb/config.py`), and `ActingWebApp.__init__` does
the same. A `Config` built before that variable is set is a DynamoDB config for
its entire life, whatever the environment later says.

## The three instances found

### 1. Config-bound singletons (ten getters)

`get_actingweb_oauth2_server`, `get_mcp_client_registry`,
`get_actingweb_token_manager`, `get_oauth2_state_manager`,
`get_permission_evaluator`, `get_registry` (trust types),
`get_trust_permission_store`, `get_peer_permission_store`,
`get_peer_profile_store`, `get_cached_capabilities_store`.

One of them documented the bug in its own source: *"config parameter kept for
interface consistency but not used"*.

Observed consequence: MCP dynamic client registration wrote the client's trust
row to one backend while trust resolution read the other, so the trust was
never found.

**The wrapper trap.** Fixing `get_actingweb_oauth2_server` was not enough.
`ActingWebOAuth2Server.__init__` constructs three further singletons, and those
stayed bound to the first config — so the server rebound while everything it
composes did not. *Rebinding a container does not rebind what it holds.*

### 2. Caches keyed by something that is not unique per application

`_actor_cache` in `handlers/mcp.py` is keyed by actor id. The OAuth2 system
actor `_actingweb_oauth2` has the same id in every application, so the cache
handed one app's `ActorInterface` to another. It now records which config built
each entry.

Sibling caches in the same module are fine, and it is worth knowing why:
`_token_cache`, `_mcp_client_info_cache` and `_trust_cache` are keyed by token,
client id, and `(actor_id, client_id)` — all unique per application, so they
cannot collide.

The test: **is any key value shared across applications?** Actor ids of system
actors are. Tokens and generated client ids are not.

### 3. The PostgreSQL connection pool

`psycopg_pool` runs its `configure` hook — which issues `SET search_path` —
**once per physical connection at creation time**, not per checkout. Each
connection permanently carries whatever schema was configured when it opened.

Change `PG_DB_PREFIX`/`PG_DB_SCHEMA` after first database use and the pool ends
up holding a **mix**: connections opened before the change are bound to the old
schema, ones opened as the pool grows under load to the new one. Which
connection a query gets is load-dependent, so a write can land in one schema
while the read goes to another and returns empty — with no error, because the
table exists in both.

`get_pool()` now tracks `_pool_schema` and rebuilds when the configured schema
changes.

## Guards now in place

- `tests/test_config_bound_singletons.py` — per-getter rebind tests, a test
  that the OAuth2 server rebinds **everything it composes**, and a structural
  test that walks `actingweb/` and fails on any function caching a module
  global built from a `config` argument without comparing against that
  argument. That last one is what prevents a fourth instance.
- `tests/integration/conftest.py::setup_database` sets the `PG_DB_*`
  environment in-process and calls `close_pool()`, so no pool survives from
  before the worker's schema was known.

## Diagnosing a suspected instance

The symptom is always "the data is not where the reader looks", never an
exception. Two techniques that worked:

1. **Log the backend module, not the config id.** `config.DbTrust.__name__`
   distinguishes `actingweb.db.dynamodb.trust` from
   `actingweb.db.postgresql.trust` at a glance; `id(config)` only tells you
   the objects differ, not which one is wrong.
2. **Instrument the getter, not the caller.** Wrap it to compare the returned
   instance's `config.database` against the argument's. Every mismatched
   caller falls out in one run, which turns "is this reachable?" into a count.
   Applied to the test suite pre-fix, this named ten tests that were passing
   against the wrong backend.

Instrumenting the *reader* cannot find these — the reader is usually correct.
It is the writer that went somewhere else.

## Related

- `thoughts/verifications/2026-07-31-mcp-trust-cache-crosses-clients.md` —
  second addendum has the full evidence trail and the affected-test list.
- `thoughts/todo/mcp-cache-lifecycle-and-revocation.md` — same theme applied
  to cache invalidation.
