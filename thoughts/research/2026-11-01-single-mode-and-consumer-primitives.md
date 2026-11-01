# Research: One mode after the 3.16 upgrade, and the two consumer primitives

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** master
**Commit:** 99b2885

## Research Questions

1. **Which tests construct `DbProperty`/`DbPropertyList`/lookup accessors without a config, and does any production path?** — 67 test call sites build property accessors without a `Config` and 49 build `DbPropertyList`/`DbPropertyLookup()`. No production path builds a property accessor that way, but `DbPropertyLookup()` is built without a config inside both backends and in the backfill script. See [Legacy lookup](#legacy-lookup-removal).
2. **Does PostgreSQL have a v2 lookup backfill, and what does a PG deployment that never set `indexed_properties` look like after the removal?** — No. The script is DynamoDB-only. A PG deployment that ran on the pre-3.13 defaults answers lookups today through the `(name, value)` sequential scan, and it would get `None` after the removal. See [PostgreSQL](#postgresql).
3. **Can the startup lookup probe be made definite, and at what cost?** — The cost is constant (2–3 `Scan Limit=1`). It is not definite today: it never reads `indexed_properties`, there is no backfill-complete marker, a fault is swallowed, PG has no probe, and the public `check_ready()` does not call it. See [The startup probe](#the-startup-probe).
4. **Can a trust row carry a TTL on both backends? If not, what deletes the system-actor trust row?** — No, on neither backend. Nothing deletes a DCR client's system-actor trust row or its `mcp_clients` record today. See [Registration expiry](#registration-expiry).
5. **Where is the one place a token issue or refresh can raise the registration's TTL, and does rotation already touch the client record?** — The three post-success points in `OAuth2Server` (code, refresh, client-credentials) each have `client_data` in scope. Rotation writes no row keyed by client, so the feature's "which already writes" does not hold. See [Token issue and refresh](#token-issue-and-refresh).
6. **What does an expired registration look like to authorize and token, and does claude.ai re-register?** — `/oauth/authorize` reads the record non-strictly and accepts an expired-but-present record (400 `invalid_request` once it is physically gone). `/oauth/token` reads strictly and answers 401 `invalid_client`. Claude Code ≥ 2.1.233 re-registers after a `/token` rejection but gets stuck after an `/authorize` rejection. For claude.ai there is one unconfirmed report of no recovery. See [Unknown client answers](#unknown-or-expired-client_id).
7. **Which SPA error sites have no stable code, and is there a vocabulary to reuse?** — None of the ~60 `_json_error` sites carries a code. The body's `error` is the boolean `true`. The logout path and the fault handler each have a small vocabulary. Both SPA translators drop any handler header except `Retry-After`. See [SPA 401 marker](#spa-401-marker).
8. **Which callers read `False` from `conditional_update_attr`/`delete_attr_conditional` as "lost" and would now see `DbError`?** — The most consequential is `single_use.consume_once`, the SPA and MCP refresh-token and auth-code consume path, which relies on False-on-fault for its lost-acknowledgement recovery. Also `try_claim_session`, `MobileTicketStore.consume`, `Actor._restore_marker`, and two consumer sites. See [Conditional writes](#create-if-absent-and-the-conditional-fault-contract).
9. **Which permission rules contain a backslash?** — None in the library, the demo, the docs, the tests or `actingweb_mcp`. The todo also misdescribes what such a pattern matches today. See [Glob escapes](#glob-escapes).
10. **Does the FastAPI MCP path read the body before or after authentication?** — Before, in both integrations; a parse failure is folded into `{}`. Non-object JSON bodies already get 400/`-32600` before auth. See [MCP parse error](#post-mcp-parse-error).
11. **With `unique_creator` on by default, which tests and fixtures must change?** — About 25 unit-test files through `_adoption_helpers.make_config()`, about 15 `integrate_*` call sites that would hit `UniqueCreatorNotReady`, three default-pinning tests, and two quickstart examples. Nothing auto-enables an empty database. See [Uniqueness default](#uniqueness-default).
12. **Do PyPI users still run the legacy lookup?** — Unanswerable from here. The feature's own answer is the fail-closed start.
13. **What does claude.ai do on `invalid_client`?** — Partly answered. One unconfirmed third-party report says it does not recover (anthropics/claude-ai-mcp#247), and Anthropic has said nothing.
14. **The consumer's 2026-09-21 audit numbers** — unanswered; the consumer holds them.

Also answered: the only direct `check_and_verify_auth()` caller (in `actingweb_mcp`) already passes config, and nothing pins `/meta/actingweb/supported`.

## Summary

The research leaves two parts of the hypothesis as stated, qualifies three, and finds that one does not work as written.

**Hold as stated:**
- **Create-if-absent** has a clean model to copy in the property layer's `create_if_not_exists`.
- **The small items** (auth config, glob escapes, advertised tags) touch no shipped or consumer pattern or caller.

**Hold, but each is larger than the hypothesis says:**
- **Legacy lookup removal.** PostgreSQL has no backfill, so a PG deployment from before 3.13 would silently lose reverse lookups. The probe it would promote to a refusal would also refuse healthy deployments.
- **Uniqueness default.** Every fresh deployment and every fresh test database would need `actingweb-unique-creators enable --apply` before its first served request. It also reverses a decision recorded in three places.
- **401 marker.** A header set in the handler is dropped by both framework translators today.

**Qualified:**
- **The `-32700` design** was argued from "auth is decided before the body is read". The code reads the body first, and non-object JSON bodies already get a 400 before auth.
- **Turning conditional-write faults into `DbError`** is not a local change. `single_use.consume_once`, the shared consume step for SPA and MCP refresh tokens and auth codes, relies on False-on-fault for its recovery.

**Does not work as written: registration expiry.**
- Trust rows have no TTL on either backend.
- A DCR client has two trust rows. User-token MCP auth reads the one on the user's actor, while the hypothesis targets the system-actor one.
- Token rotation writes nothing keyed by client.
- On PostgreSQL, nothing would ever purge an expired `mcp_clients` row.
- `/authorize` would keep accepting an expired client while `/token` refuses it. External evidence shows the `/authorize` rejection is the case clients cannot recover from.

On the user experience:
- The operator's main path ("`check_ready()` passes") holds for the two known deployments, because both already run the lookup table and uniqueness.
- The consumer's two client changes (header check, create-if-absent) are supported once the header actually reaches the browser.
- The edge path "the client re-registers, so nobody notices" holds for Claude Code at `/token` only.

On the success measures:
- **Observable today:** the startup refusals (testable), the legacy-code grep, and the todo count.
- **Need the consumer:** the registry growth and the sign-out and duplicate-ask measures, using the consumer's audit script and `TokenManager` diagnostics.
- **Not observable:** third-party deployments, as the feature says.

## Detailed Findings

### Legacy lookup removal

**What would be removed**

- **DynamoDB:**
  - `PropertyIndex` (`actingweb/db/dynamodb/property.py:24-33`) and `PropertyLegacy` (`:77-98`).
  - The `use_lookup_table`/`USE_PROPERTY_LOOKUP_TABLE` and `INDEXED_PROPERTIES` env fallbacks in `DbProperty.__init__` (`:141-173`) and `DbPropertyList.__init__` (`:737-769`). The `INDEXED_PROPERTIES` fallback is not mentioned in the feature.
  - The gate in `_should_index_property` (`:187-191`).
  - The three tiers of `_get_actor_id_from_property` (`:258-366`):
    - v1 `get_v1` (`:280-292`);
    - the name-filtered legacy GSI (`:294-318`);
    - value-only legacy mode (`:333-366`).
  - The v1 `PropertyLookup` model (`property_lookup.py:74-89`), `get_v1` (`:169-193`), and `is_missing_resource` (`:97-113`, used only at `property.py:308`).
  - The exports in `dynamodb/__init__.py:19-20,52,56`.
- **PostgreSQL:**
  - The same env fallbacks (`actingweb/db/postgresql/property.py:54-80, 804-832`).
  - The gate (`:94-98`).
  - The `(name, value)` "migration fallback" scan (`:198-226`). It is unindexed since migration `c3d4e5f6a7b8` dropped `idx_properties_value`.
  - The value-only legacy branch (`:257-283`).
  - The list-delete gate (`:965`).
- **Config and builder:**
  - `config.py:101-109` and the env override at `:337-340`.
  - Factory plumbing in `db/__init__.py:88-91, 112-115`.
  - In `interface/app.py`: `_use_lookup_table` at `:105-111`, `:219-227`, `:1458-1465`; `with_legacy_property_index()` at `:473-495`, whose docstring at `:491` still calls legacy the default and contradicts `config.py:109`; the pre-warm mode at `:1527-1529`; and the v1 branch of the probe at `:1574-1588`.
- **`db/verify_tables.py`:** `lookup_mode_enabled` (`:43-53`), the mode in `required_models` (`:56-107`), and `--lookup-table`/`--legacy` (`:162-175`).
- **Docs:**
  - `docs/quickstart/configuration.rst:455-493, 557-579`
  - `docs/reference/database-backends.rst:410-478`
  - `docs/guides/database-maintenance.rst:69`
  - `docs/contributing/architecture.rst:490-494`
  - `docs/migration/v3.13.rst` is historical.
  - The `CLAUDE.md` "Property Reverse Lookup" section says lookup mode is disabled by default, which is stale.
- **Demo:** `examples/demo/application.py:85-87` calls `.with_legacy_property_index(...)`.
- **Tests:** 159 matches in 10 files.
  - Most are in `tests/test_property_lookup.py`, `test_property_lookup_v2.py` (`TestV1Fallback`, legacy contract cases), and `test_lookup_migration.py` (`TestV1CohortFallback`, `TestGsiCohortFallback`, `TestStartupCheck`, `TestDefaultFlip`; `TestBackfillScript` stays).
  - The rest: `test_verify_tables.py`, `test_db_fault_contract.py`, `test_conditional_gsi_schema.py`, `test_billing_mode.py`, `test_cold_start_budget.py`, and `tests/integration/_isolated_store.py:40-54`.

**Direct construction without a config**

| Kind | Sites | Main files |
|---|---|---|
| `DbProperty()`/`DbPropertyList()` with no args | 54 | `test_property_lookup.py` (21), `test_v2_cost_plain_property_partition.py` (15), `performance/test_backend_performance.py` (8) |
| Same with kwargs, no `Config` | 13 | `test_property_lookup_v2.py` (7), `test_db_fault_contract.py` (5) |
| `DbPropertyLookup()` (takes no args on either backend) | 49 | `test_property_lookup.py` (33) |

- **Production:** no path builds a property accessor without a config. Every one goes through `get_property`/`get_property_list`, which matches the scalability plan's note (`thoughts/plans/2026-07-23-dynamodb-scalability.md:614-616`). The exception is `DbPropertyLookup()`, built without a config at `dynamodb/property.py:277, 457, 487, 870`, `postgresql/property.py:195`, and `scripts/backfill_property_lookup.py:158`.
- **Other accessor classes** (`DbActor`, `DbTrust`, `DbAttribute`, …) take no config at all. They are built directly 135 times across 14 test files. Only `get_property`, `get_property_list` and `get_actor` pass anything from `Config` (`db/__init__.py:88-91, 112-115, 138`).

**Import-time table names are a separate problem from factory injection**

- Every DynamoDB model reads `AWS_DB_PREFIX`/`AWS_DEFAULT_REGION`/`AWS_DB_HOST` in its class `Meta`: `actor.py:54-57`, `trust.py:70-73`, `attribute.py:50-53`, `property.py:50-53`, `property_lookup.py:63-67`, and the rest.
- `dynamodb/__init__.py:15-27` imports them all.
- `Config` carries no prefix or host.
- Making factory injection mandatory therefore leaves every table-name read where it is. Classmethods, the probe, `verify_tables`, the maintenance tools and the backfill script all address tables through `Meta`.
- The test harness depends on the freeze: `tests/conftest.py:11-28` sets the prefix before import, and `tests/integration/_isolated_store.py:111-133` rewrites `Meta.table_name`.
- This is the "import-time table-name freezing" item in `thoughts/todo/dynamodb-known-next.md:77-85`.

#### PostgreSQL

- **The table:** a single `property_lookup` table (PK `(property_name, value)`, FK to `actors.id` with cascade), from Alembic `70d60420526`. There is no v1/v2 split.
- **How it is written:** only at write time, inside `DbProperty.set()` (`postgresql/property.py:330-353`, helper `:367-419`, `ON CONFLICT DO NOTHING`).
- **No PG backfill exists.** `scripts/backfill_property_lookup.py` imports the DynamoDB modules (`:145-149`), scans `Property.scan(segment=...)` (`:159`), and builds `Config(database="dynamodb")` (`:229`).
- **Before v3.13 the default was legacy mode** (`CHANGELOG.rst:4346`). A PG deployment that ran on defaults then never wrote `property_lookup` rows for its existing values. Since 3.13 its lookups have been answered by the `:198-226` scan, which logs DEPRECATED on a hit.
- **After the removal** those lookups return `None`. That is the "no such actor → second actor at next sign-in" failure the feature says must never happen.
- **No PG startup diagnostic exists:** `app.py:1555` returns early for non-DynamoDB.
- **Cost of a PG backfill:** because the lookup table and `properties` live in one database, a backfill is one `INSERT INTO property_lookup (property_name, value, actor_id) SELECT name, value, id FROM properties WHERE name = ANY(%s) ON CONFLICT DO NOTHING`, which can be a migration step or a script mode. This is an inference from the schema, not existing code.

#### The startup probe

`ActingWebApp._check_lookup_backfill_needed` (`interface/app.py:1545-1599`):

- **Where it runs:** from `integrate_flask` (`:1656`) and `integrate_fastapi` (`:1688`), after the pre-warm and before `_check_unique_creator_ready`. The public `check_ready()` (`:1601-1616`) does not call it.
- **What it reads:** `PropertyLookupV2.scan(limit=1)` (any row means pass), then `Property.scan(limit=1)` (empty means a fresh deployment, pass), then the v1 scan.
- **What it does on failure:** logs `logger.error` (`:1579-1597`). Any exception is logged at DEBUG and the app starts (`:1598-1599`).
- **Cost:** constant. 2–3 scans that evaluate one item each, with an item of up to `MAX_ROW_BYTES` = 409,600 (`property.py:139`), once per process. It needs `dynamodb:Scan`.

**Why it is not definite:**

- **It refuses healthy deployments.** It never reads `indexed_properties` (default `["oauthId", "email", "externalUserId"]`, `config.py:103`). "Properties exist" means any row: plain properties, `list:` rows, meta rows. The library writes no `oauthId`/`email` property itself; reverse lookup is reached only through `Actor.get_from_property` (`actor.py:378-397`) and `ActorInterface.get_by_property` (`actor_interface.py:279-282`). So a deployment whose actors hold none of the indexed names would be refused, and so would one with `with_indexed_properties([])`.
- **It has no completion marker.** The backfill writes lookup rows and deletes its checkpoint (`scripts/backfill_property_lookup.py:282-290`). One v2 row from a partial run passes.
- **Checking that tables exist needs `DescribeTable`.** That grant is documented as absent when auto-create is off (`docs/reference/database-backends.rst:377-383`). A data-plane read on a missing table raises `ResourceNotFound`, which `is_missing_resource()` already classifies.

**The model to copy.** `UniqueCreatorNotReady(RuntimeError)` (`app.py:29-31`, exported at `interface/__init__.py:15,46`) and `_check_unique_creator_ready` (`app.py:1618-1644`): once per process, a fault refuses, a missing reason refuses with the named commands. `missing_enforcement` (`maintenance/unique_creators.py:964-984`):
- **PostgreSQL:** reads index state from `pg_index` (`:753-769`).
- **DynamoDB:** `Creator.exists()`, then a consistent `GetItem` of the `#meta#backfill` marker (`:274-287`).

**Sequencing constraint.** `thoughts/todo/INDEX.md:78` and `legacy-property-gsi-removal.md:31-34` require that holdout migration notes ship in a release that still contains the backfill script. The feature keeps the script in 3.16, so the constraint is met. It is met only for DynamoDB, since there is no PG script.

**Recorded decisions:**
- The removal was scheduled for "the next major": `thoughts/todo/legacy-property-gsi-removal.md:1-4`, `thoughts/plans/2026-07-23-dynamodb-scalability.md:501`, and the deprecation strings at `dynamodb/property.py:291,317` and `postgresql/property.py:224-225`.
- The feature records the owner's rejection of "notice now, remove later" (`features/…:212-213`).

### Uniqueness default

**Where the default lives:**
- `Config.unique_creator = False` (`config.py:89`).
- `ActingWebApp._unique_creator = False` (`interface/app.py:84`), passed into `Config` at `:1444` and re-applied at `:188`. `with_unique_creator()` is at `:537-541`.
- There is no environment variable.
- **The default is pinned by:**
  - `tests/test_unique_creator_default.py:14-20`
  - `tests/test_config.py:29`
  - `tests/test_actingweb_app.py:49`
- **Must stay off after any flip:** the maintenance command's own config (`maintenance/unique_creators.py:143-160`). The command writes the records itself, and `#dup-` renames must work before `enable`.

**No auto-enable on either backend.**
- Only `enable --apply` writes the DynamoDB marker (`unique_creators.py:872`, skipped on collisions at `:866-871`) or builds `ux_actors_creator` concurrently (`:772-806`).
- Alembic leaves the index out on purpose (`db/postgresql/schema.py:42-46`, `docs/migration/v3.16.rst:518-520`).
- **What happens on first start:**
  - **DynamoDB needs two starts.** The pre-warm creates an empty `creators` table (`app.py:1527-1529`, `db/verify_tables.py:103-106`). The check then refuses with "…is not backfilled". `enable --apply` cannot run earlier, because `collect()` raises `StoreUnavailable` on a missing actor table (`unique_creators.py:345-350`). That is the demo's start → enable → start sequence (`examples/demo/README.md:68-73`).
  - **PostgreSQL needs one:** `alembic upgrade head`, then `enable --apply`, then start.
- **So with the default on:**
  - every fresh deployment refuses its first start;
  - so does every new user following `examples/p2p_quickstart.py:122` or `examples/mcp_quickstart.py:89`, which call `integrate_fastapi` without the flag;
  - and so does every test that integrates an app against the shared `test` prefix.

**Test blast radius.** I did not audit every one of the 202 `Config(` calls in 67 files.
- **Write path (enforced create, holder lookup, `_replace_enforced`):** `tests/_adoption_helpers.py:30-40` `make_config()` passes no flag and is imported by 25 files (the adoption and `test_db_fault_*` suites, among others). Also `tests/integration/test_factory_squat_adoption.py:26`.
- **Readiness (`integrate_*` without the flag):**
  - `test_db_fault_http.py:60,109`
  - `test_db_fault_third_pass.py:299,312`
  - `test_db_fault_fifth_pass.py:355,375`
  - `test_fastapi_template_response.py:33,97,125,152`
  - `test_flask_factory_fallback.py:26`
  - `test_spa_token_retry_after.py:44,53`
  - `test_oauth2_logout_mcp_tokens.py:154,162`
  - In `tests/integration/`: `test_mcp_notification_integrations.py:88,95`, `test_flask_items_route_parity.py:46`, `test_mcp_info_route.py:59,66`, `test_property_path_control_chars.py:232`
- **The shared unit-test tables cannot be enforced for real.** They hold deliberate duplicates; `tests/test_demo_example.py:28-39` monkeypatches `missing_enforcement` for this reason.
- **The integration harness is insulated.** `create_test_app` defaults its own `unique_creator=False` (`tests/integration/test_harness.py:32,63`).

**What a consumer would see change** with the flag on (by default):
- A JSON `POST /` with a held creator answers 403, not 201 (`handlers/factory.py:291-307`).
- OAuth lookup goes through one holder (`actor.py:440-485`) instead of ranking and `SWEEP_LIMIT` (`:487-537`).
- Unvouched replacement becomes atomic (`oauth2.py:2315-2336`) and answers 503 on `UNKNOWN`.
- `PUT /<id>/trust/trustee` to a held creator answers 409 (`handlers/trust.py:310-314`).
- Operations: `ConditionCheckItem` IAM; about 4–6 WCU per create, delete or rename on DynamoDB; two apps can no longer bootstrap system actors on one shared table (`CHANGELOG.rst:306-313`).
- `#…` addresses are refused with the flag on or off (`creator_rules.py:43-48`).

**The recorded decision this reverses:**
- `CHANGELOG.rst:319-320` (Unreleased): "``unique_creator`` stays off by default in 3.16 and turns on at the next major."
- `docs/migration/v3.16.rst:526`: the same.
- `thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md:144-146`, `:229-236`, `:333`: "It is a forced migration for every deployment with duplicates; the flip is recorded for the next major instead."
- `thoughts/todo/unique-creator-default-on-next-major.md:12-13`: "A minor must not do that."

All of this text is in `Unreleased`/unreleased docs. 3.16.0 has not been tagged, so it can be rewritten.

### Registration expiry

**What a registration writes**

- **The route:** `POST /oauth/register` → `_handle_client_registration` (`handlers/oauth2_endpoints.py:162-211`) → `handle_client_registration` with no actor. It falls back to the system actor `_actingweb_oauth2` (`oauth2_server/oauth2_server.py:80-118`).
- **`MCPClientRegistry.register_client`** (`oauth2_server/client_registry.py:46-149`) writes three things, all with no TTL:
  - the client record, `Attributes(system_actor, "mcp_clients").set_attr(client_id, …)` (`:409`);
  - the global index, `Attributes(OAUTH2_SYSTEM_ACTOR, "_client_index")` (`:682`);
  - a trust row, `oauth2_client:{client_id}:{client_id}`, on the system actor (`:545-557` → `interface/trust_manager.py:476-628`).
- **The trust-list walk** (`client_registry.py:563-577`) only builds a log string. It has no side effect, and the peer id is already known.
- **A second trust row is written at the OAuth callback** on the **user's** actor: `oauth2_client:{email}:{client_id}` with `oauth_client_id` (`oauth2_server.py:403-418` → `oauth2.py:1529-1575`). A re-authorization updates it in place (`trust_manager.py:495-541`).

**Which trust row MCP auth reads.**
- `validate_mcp_token` resolves `(actor_id, client_id)`, then `_lookup_mcp_trust_relationship(actor, client_id)` (`handlers/mcp.py:2364-2431, 2554-2643`).
- For user tokens the actor is the user's, so the row read is the callback's. With no row, tool calls fail closed with `-32003`.
- The system-actor row is read only for client-credentials tokens (`oauth2_server.py:656`).

**TTL support**

- **Attribute rows** have a TTL on both backends: `ttl_seconds` through `set_attr` (`attribute.py:264-319`) and `conditional_update_attr` (`:335-376`). The stored value is `now + ttl + 3600` skew (`TTL_CLOCK_SKEW_BUFFER`, `constants.py:245`).
  - **DynamoDB:** native TTL must be enabled by the operator, once per table (`docs/reference/database-backends.rst:253-285`). `_ensure.py` never enables it. Deletion "typically within a few days" with no bound (AWS docs below).
  - **PostgreSQL:** rows are removed only by `delete_expired(buckets=…)` (`db/postgresql/attribute.py:641-679`). Its callers pass token buckets only: MCP `purge_expired_tokens` (`token_manager.py:1820-1864`) and SPA `oauth_session.py:1223-1284`. **`mcp_clients` and `_client_index` are in neither list**, so on PostgreSQL a TTL on them would never be physically purged.
- **Trust rows have no TTL on either backend:** the DynamoDB `Trust` model (`db/dynamodb/trust.py:66-117`), the PG `trusts` table (`db/postgresql/schema.py:104-144`), and `DbTrustProtocol` (`db/protocols.py:698-822`). Adding one would mean:
  - **DynamoDB:** a model attribute; read filtering in `DbTrust.get`/`DbTrustList.fetch`; a second manual `update-time-to-live` on `<prefix>_trusts`.
  - **PostgreSQL:** an Alembic revision (head `e5f6a7b8c9d0`), read filtering, and a reaper.
  - **Both:** protocol changes (a Breaking entry for custom backends).
  - **A behaviour change:** a row removed by native TTL skips `Trust.delete()`'s cascade, including MCP cache eviction (`actingweb/trust.py:123-187`).
- **Expired rows stay readable.** `get_attr`/`get_bucket` return them, and only `get_attr_strict` hides them, one hour after the logical TTL. DynamoDB keeps them until the sweep; PostgreSQL until a purge that names the bucket.
- **The documented guarantee changes.** `docs/reference/database-backends.rst:263-271` says `ttl_timestamp` is written "only for temporary data that is *meant* to expire … Every permanent write goes through ``set_attr`` with no ``ttl``". A TTL on registrations changes that sentence. The registration response also says `client_secret_expires_at: 0` (`client_registry.py:144-146`, `CHANGELOG.rst:1467`); RFC 7591 defines that field only for the secret, not for the `client_id`.

#### Token issue and refresh

- **Code grant:** `_handle_authorization_code_grant` (`oauth2_server.py:543-591`) → `exchange_authorization_code` (`token_manager.py:137-268`).
- **Refresh grant:** `oauth2_server.py:593-624` → `refresh_access_token` (`token_manager.py:308-494`). It consumes the old token by CAS, runs the grace/theft/expired ladder, and mints in the same chain.
- **Client-credentials:** `oauth2_server.py:626-683`. No refresh token.
- **Refresh tokens are minted in one place:** `_create_refresh_token` (`token_manager.py:857-892`), with a 30-day sliding lifetime (`:72`, `MCP_REFRESH_TOKEN_TTL` in `constants.py:202`). It does not know where the client record lives.
- **`client_data` (with `actor_id`) is in scope** at the post-success points: `oauth2_server.py:590-591` (code), `:623-624` (refresh), `:680-683` (client-credentials). The pre-grant `_authenticate_client` read is at `:497-524`.
- **Rotation writes nothing keyed by client:** token rows on the user's actor, index rows on the system actor (`token_manager.py:1044+, 1278-1312`). The feature's "(one write per refresh, which already writes)" does not hold; raising the TTL is a new write per grant.

#### Unknown or expired `client_id`

- **`/oauth/authorize`:** `validate_client` → `_load_from_global_index`, a non-strict `get_attr` (`client_registry.py:462-507`). An expired-but-present record is accepted. A missing one gives `invalid_client` (`oauth2_server.py:161-163`), which the handler turns into **HTTP 400 `{"error":"invalid_request","error_description":"invalid_client: Invalid client_id"}`** (`oauth2_endpoints.py:315-319, 1289-1290`).
- **`/oauth/token`:** `_authenticate_client` → `load_client_strict` (`client_registry.py:189-223`). Expired reads as absent, which gives **HTTP 401 `invalid_client` with `WWW-Authenticate: Basic … error="invalid_client"`** (`oauth2_endpoints.py:449-458`). A store fault (`TokenStoreUnavailable`, not a `DbError`) becomes a 500 (`oauth2_server.py:491-495`, `oauth2_endpoints.py:467-469`).
- **`/oauth/callback`** does not check the client (`oauth2_server.py:335-440`).
- **Existing tokens:** access tokens validate without the client record (`token_manager.py:270-306`) and live out their hour. A TTL expiry would not revoke tokens, whereas `delete_client` does (`client_registry.py:333-352`).
- **Today:**
  - `Trust.delete()` on the user-actor row calls `delete_client(client_id, actor_id=user)` (`actingweb/trust.py:161-176, 205-223`). That deletes the global index row (enough to disable the client) but not the system-actor record or trust row.
  - Nothing deletes those two.
  - The verification that made the `/token` read strict did it because `invalid_client` is what connectors act on (`thoughts/verifications/2026-09-25-…md:271-293`).

**External evidence (authorize vs token):**

- **RFC 6749 §4.1.2.1:** an invalid `client_id` at `/authorize` must not be redirected, so the client never sees the error.
- **Claude Code** (anthropics/claude-code#84614, open, reproduced):
  - v2.1.233 and later discard the cached registration and re-register on an `invalid_client` at `/token`.
  - A rejection at `/authorize` leaves authentication "permanently broken" until `claude mcp logout`.
- **Claude Desktop** shows the authorize error page with no in-app recovery (#72818).
- **claude.ai connectors:** one third-party report of a stale `client_id` with no `/register` traffic after reconnecting (anthropics/claude-ai-mcp#247). Anthropic has not replied.
- **TypeScript SDK:** re-registers only if the host implements `invalidateCredentials`.
- **Rate limits:** a `/register` that rate-limits locks users out (#59460).
- **CIMD:** MCP 2025-11-25 makes DCR a MAY and Client ID Metadata Documents a SHOULD. A CIMD client creates no registration at all. It is already noted in `thoughts/todo/mcp-oauth-connector-conformance-followups.md:25-37`.

**Other readers of registrations:**
- The web UI trust page lists the **user's** `mcp_clients` bucket (`handlers/www.py:917-945`), where DCR clients do not live, plus the user's trust rows.
- Actor deletion reads the actor's own bucket (`oauth2.py:1817-1844`).
- No admin listing of the system actor's registrations exists in `actingweb/` or `examples/`.
- What the consumer's Connections page lists was not checked (`../actingweb_mcp`).

**Recorded decisions:**
- `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md:19-28` sketched `last_used_at`, a short TTL on never-authorized registrations, and a sweep.
- The feature rejects the idle clock and the sweep (`features/…:217-222`).
- `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md:283-285` deferred it for "a retention policy decision and a scan design".

### SPA 401 marker

**Routes:** `OAuth2SPAHandler` (`handlers/oauth2_spa.py`) serves `/oauth/spa/token|authorize|revoke|session|config|callback`, `/oauth/revoke`, `/oauth/session` and `/oauth/config` (Flask `flask_integration.py:260-296`, FastAPI `fastapi_integration.py:859-913`). Logout goes through `OAuth2EndpointsHandler._handle_logout_request` (`oauth2_endpoints.py:899`). `GET /oauth/spa/session/{id}` exists in FastAPI only, inline (`fastapi_integration.py:2361-2440`).

**Body shape:** every error goes through `_json_error(status, message)` (`oauth2_spa.py:1834-1844`), which returns `{"error": true, "status_code": N, "message": "..."}`.
- No site carries a stable code. Because `error` is a boolean, a code needs a new key.
- A precedent exists: `handlers/oauth_email.py:122-127` (`"code": "actor_exists"`) and `:600` (`"code": "authentication_rejected"`).
- The SPA guide documents "the same shape without a `code` field" (`docs/guides/spa-authentication.rst:1702-1734`).

**The 401 sites on the token endpoint (`oauth2_spa.py`):**

| Grant | Lines |
|---|---|
| refresh | `697` (invalid/expired), `703` (bad data), `769` (reuse past the window), `808` (theft) |
| `authorization_code` | `935`, `947`, `963`, `966` |
| jwt-bearer | `1309` |
| mobile_ticket | `1374`, `1386`, `1395` |
| passphrase | `1471` |

There are also about 45 400/403/404/500 sites. The 503 at `:1829` comes from `_store_unavailable` and sets `Retry-After: 5`.

**Existing code vocabularies elsewhere:**
- Logout `error_response` (`oauth2_endpoints.py:1284-1294`): `invalid_request`/`invalid_client`/`server_error`, plus `temporarily_unavailable` at `:1004-1011`.
- The fault handler, `db_error_answer` (`interface/integrations/_errors.py:26-39, 78-90`): `temporarily_unavailable`/`internal_error`/`conflict`.
- RFC 6750 defines `invalid_request`/`invalid_token`/`insufficient_scope` for `WWW-Authenticate error=`.

**The header would be dropped today.**
- Both SPA translators copy only `Retry-After` and cookies from the handler: Flask `flask_integration.py:1463-1466, 1481-1486` and FastAPI `fastapi_integration.py:2321-2343`. A header set in `_json_error` never reaches the client.
- The logout translator copies all handler headers (Flask `:1389-1392`, FastAPI `:2259-2263`).
- The fault handler (`_db_error_response` Flask `flask_integration.py:50-75`, FastAPI `fastapi_integration.py:73-93`) and the FastAPI session-retrieve build their responses inline.

**CORS:**
- `spa_cors_headers()` sets `Access-Control-Expose-Headers: Retry-After` (`oauth2_spa.py:135-174`, literal at `:172`). It also covers fault answers on SPA paths (`_errors.py:195-198`).
- `error_cors_headers()` has two more literals: `_errors.py:193` (`/`) and `:200` (other `/oauth/*`).
- Per Fetch/MDN: `*` does not act as a wildcard on credentialed requests, so the header must be named. `WWW-Authenticate` is not exposed by default either.

**The guide's rule 7** (`docs/guides/spa-authentication.rst:846-851`): "Treat a 401 on refresh as final … A 503 is not final". Related text at `:1017-1019` (`Retry-After` exposure) and `:1771-1773`/`:1811-1812` (theft 401).

### POST /mcp parse error

**The body is parsed before authentication** in both integrations: Flask `flask_integration.py:1546-1557` and FastAPI `fastapi_integration.py:2484-2493`. An empty body, a `JSONDecodeError` or a form body (Flask `:674-678`) becomes `data = {}`.

**Order of checks in the handler** (`handlers/mcp.py:890-998`; async `async_mcp.py:48-147`):
1. disabled check;
2. `_reject_non_object_body`, **before auth** (`:903-904`): array/string/number → 400 `-32600`, `id: null` (`:861-888`, `CHANGELOG.rst:1763-1774`);
3. `initialize`;
4. protocol-version header → 400 `-32600` (`:924, 2144-2149`);
5. notifications → 202;
6. `ping`;
7. auth (`:952`);
8. 401 + `WWW-Authenticate` `-32002` (`:955-966`).

**What a non-JSON or empty body gets today:**
- Unauthenticated: 401 with the challenge.
- Authenticated: HTTP 200 with `-32601 "Method not found: None"` (`:988-990`).

The feature's premise ("auth is decided before the body is read", `features/…:147-150`) does not match the code. The non-object rule already answers 400 to an unauthenticated `[]`. "After auth" therefore needs a sentinel from the integrations that also gets past `:903`.

**Not a conflict:** the dual-era guard (`mcp.py:2098-2109`, `tests/test_mcp_dual_era_signal.py`) concerns only the version answer.

**Tests:** `tests/integration/test_mcp_tools.py:292-304` accepts 200 or 400.

**External:**
- JSON-RPC: `-32700` with `id: null`.
- MCP transports (2025-11-25): an HTTP error status (for example 400) for a message the server cannot accept, with no explicit rule for unparseable bodies.
- The TypeScript SDK answers 400/`-32700`.

### Advertised option tags

- **The list is built in** `config.py:393-415` and sorted in `update_supported_options` (`:509-534`).
- **What it serves today:**
  - advertises `sessions` (`:404`), which has no route;
  - never advertises `listproperties`, though `/{actor_id}/properties/{name}/items` exists (`flask_integration.py:427`, `fastapi_integration.py:1070-1071`, `handlers/properties.py:2066`);
  - is served at `handlers/meta.py:74-75`.
- **The spec** defines `listproperties` (`docs/protocol/actingweb-spec.rst:443-446, 951-957`). `subscriptionbatch`, `mcp`, `permissioncallback` and `permissionquery` are advertised but are not spec tags.
- **No test pins** `sessions` or `listproperties`. `tests/test_trustpermissions_feature_tag.py` checks other tags.
- **No peer reads either tag** (`peer_capabilities.py:114-148`).
- **The todo's wider audit** (`sessions-endpoint-and-advertised-options.md:44-50`) also covers `onewaytrust`, `actions`/`methods`, and `callbackcompression`.

### Create-if-absent and the conditional fault contract

**Where the methods are:**

| Method | Protocol | DynamoDB | PostgreSQL | `Attributes` |
|---|---|---|---|---|
| `delete_attr_conditional` | `protocols.py:1322-1348` | `dynamodb/attribute.py:247-278` | `postgresql/attribute.py:482-527` | `attribute.py:410-427` |
| `conditional_update_attr` | `protocols.py:1350-1380` | `dynamodb/attribute.py:280-367` | `postgresql/attribute.py:529-607` | `attribute.py:335-390` |

**Today both answer `False` for a fault, a missing row and a lost condition alike.**
- **DynamoDB:** `except Exception: return False` at `:268-270`, `:275-278` and `:365-367`.
- **PostgreSQL:** `rowcount == 1`, and exceptions log and return `False` (`:523-527`, `:603-607`).
- **The contract is written in four places:** `protocols.py:25-27`, `:1345-1347`, `:1377-1378`, and `attribute.py:356-358`. The migration guide repeats it at `docs/migration/v3.16.rst:471-472`.

**The model to copy is the property layer's `create_if_not_exists`** (`protocols.py:447-472`): `True` when created, `False` when the row exists, `DbError` on a fault.
- **DynamoDB:** `save(condition=id.does_not_exist())`. `ConditionalCheckFailedException` maps to `False`; any other error raises (`dynamodb/property.py:601-621`).
- **PostgreSQL:** `INSERT … ON CONFLICT (id, name) DO NOTHING` and `rowcount == 1` (`postgresql/property.py:623-654`).
- Properties have no TTL, so this model never had to deal with expiry.

**Attribute-specific traps for a create-if-absent:**
- **Expired but present rows count as "exists".** Every conditional path today ignores the TTL: DynamoDB compares `item.data` or `id.exists()`, and the PG `UPDATE`/`DELETE` have no TTL predicate. A plain `attribute_not_exists` or `ON CONFLICT DO NOTHING` would answer `False` for an ask that expired an hour ago (plus the skew) but has not been swept yet. That lasts up to days on DynamoDB, or until a purge on PostgreSQL.
- **The key `(id, bucket_name)` can collide across buckets**, because `bucket_name = bucket + ":" + name` (DynamoDB docstring `:83-92`). Reads guard this with an exact `bucket` comparison; a conditional create on the key would not.
- **An SDK-retried conditional create can answer `False` after landing** (`docs/migration/v3.16.rst:806-807`; `thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md`).

**Callers that would behave differently if a fault raised `DbError`:**

| Caller | Today | After |
|---|---|---|
| `single_use.consume_once` → `conditional_update_attr` (`single_use.py:158`, recovery `:165-187`). Callers: `oauth_session.py:807` (SPA refresh) and `oauth2_server/token_manager.py:663` (MCP codes and refresh tokens), both catching `StoreFault` only | `False` → strict re-read. Own `consume_id` = a lost acknowledgement, counted as a win. Unused row → `StoreFault` → 503 with `Retry-After`. Otherwise reuse | `DbError` escapes `consume_once` uncaught and reaches the app-level 503. A swap that landed but raised leaves the row used under this call's id; the client's retry then takes the reuse/theft ladder instead of the lost-acknowledgement win |
| `single_use.delete_confirmed` (`:215-221`, inside `try/except Exception`), used by ~13 sites | Fault → `False` → strict re-read | Goes straight to `except` → `False`. A delete that landed but faulted reads as not deleted |
| `OAuth2SessionManager.try_claim_session` (`oauth_session.py:215`) → `oauth_email.py:475` | 400 "Invalid or expired session" | 503 |
| `MobileTicketStore.consume` (`oauth_state_store.py:170, 176`) → `oauth2_spa.py:1342-1344` | 400 "Invalid or expired ticket", including the expired-ticket burn whose result is ignored | 503 |
| `Actor._restore_marker` (`actor.py:301`) via `modify_creator_unvouched` (`:939`) | Misleading "changed since" warning on an outage (`unique-creator-small-followups.md:45-48`) | Raises `DbError`, matching `:878`. It would mask a pending `modify()` fault (`:919-922, 945-946`) |
| Consumer `api/memory_review.py:233` (inside `except Exception :276-278`) | 200 with `won=False` | 500 |
| Consumer `api/memory_review.py:104` (`_adjust_pending_review_count`) | Its callers wrap it, except `memory_review.py:244` | `memory_review.py:244` is unprotected |

Other consumer callers (`helpers/shares.py:731, 921, 973`; `helpers/guided_settings.py:309, 347, 371`; `api/service_info.py:85`) already wrap the call. The consumer's read-then-`set_attr` bootstraps that create-if-absent would replace are at `api/memory_review.py:92, 237` and `helpers/shares.py:919`, with comments at `:74-75` and `:229-231`.

**Custom-backend Breaking entries already in Unreleased:** `DbActor(unique_creator=…)` (`CHANGELOG.rst:343-352`), `increment_seq` (`:354-360`), and `strict` on list fetches and `get_by_creator` (`:443-450`). A new protocol method would be the fourth; the feature says "two".

### Glob escapes

- **Where:** `_glob_to_regex` (`permission_evaluator.py:711-723`) does `re.escape`, then `\*`→`.*` and `\?`→`.`.
- **Only caller:** `_matches_pattern` (`:669-709`). It short-circuits on `"*"` (`:682`) and on equality (`:685`), and keeps a 1024-entry compiled cache. `_evaluate_rules` uses it for `denied`/`allowed`/`patterns`/`excluded_patterns` (`:588-623`).
- **What a backslash pattern does today:** `a\*b` compiles to `^a\\.*b\Z`, which matches a literal backslash, then anything, then `b`. Through the equality shortcut it also matches the string `a\*b` itself. `thoughts/todo/glob-backslash-escape.md` says such a pattern matches `aXYZb`, which is wrong.
- **A second engine is not covered:** `fnmatch.fnmatch` in `peer_permissions.py:210-212` and `handlers/callbacks.py:845, 873, 989, 1026, 1043`. Escapes added to `_glob_to_regex` would not apply there.
- **No backslash in any permission pattern:** none in `actingweb/`, `examples/`, `docs/` or `tests/`, and none in `actingweb_mcp`'s trust types (`application.py:713-822`). That repo's runtime-built patterns come from names restricted to `memory_[a-z0-9_-]+` (`repositories/validation.py:14, 41`). `"actingweb://activity/recent?days=*"` uses `?` as a wildcard on purpose (`application.py:766-774`).
- **Tests that pin the output:** `tests/test_permission_pattern_matching.py:53, 97`.

### Auth config

- **Where `Config()` is built per call:**
  - `check_and_verify_auth(appreq=None, actor_id=None, config=None)` builds one at `auth.py:848-849`.
  - The async variant builds one at `:928-929`.
  - `Auth.__init__(…, config=None)` builds one at `:84-85`.
- **No library caller of either helper.** `base_handler.py:235` builds `Auth` with `self.config`.
- **The only consumer call** passes config: `actingweb_mcp/helpers/template_helpers.py:286`.
- **The docs examples pass `config=`,** but the signature listings show `config=None` (`docs/guides/authentication.rst:499, 755`).
- **Behaviour pinned by a test:** only `tests/test_auth.py:101-115`, which covers `Auth(config=None)`, not the helpers.

## Decisions Needed

### Decision 1: What happens to PostgreSQL deployments with no lookup rows?

**Options:**
1. **Ship a PG backfill.** One `INSERT … SELECT … ON CONFLICT DO NOTHING` over the configured indexed names, as an Alembic step or a script mode. Pros: small. It closes the second-actor failure for pre-3.13 PG deployments. It makes the "a backfill exists in the release that removes the fallback" constraint true on both backends. Cons: needs `indexed_properties` at migration time, which a migration does not have, so a script mode is the natural home. A probe is still needed to tell the operator to run it.
2. **Refuse to start on PG without lookup rows, and document a manual SQL statement.** Pros: no new code path. Cons: every such operator types SQL by hand.
3. **Keep the `(name, value)` scan on PG only.** Pros: no migration. Cons: contradicts "one mechanism", and the scan is unindexed.

**Recommendation:** option 1. The schema makes it one statement, and without it the removal reintroduces, on PG, the failure the feature is written to prevent.

### Decision 2: What counts as "not ready" for the lookup refusal?

**Options:**
1. **Probe per indexed name:** refuse when some property row has an indexed name and v2 has no row for that name. Pros: no false refusals; `[]` and unused names pass. Cons: on DynamoDB a per-name probe of `properties` is a Scan with a filter, so not constant cost. On PG it is cheap (`EXISTS … WHERE name = ANY`).
2. **Completion marker written by the backfill** (like `#meta#backfill`), checked by a consistent `GetItem`. Pros: definite and constant cost, the same shape as `UniqueCreatorNotReady`. Cons: every existing deployment, including the two known ones, must re-run the backfill (or a `--mark-complete` mode) to get the marker. A fresh deployment needs the marker written on first start when `properties` is empty.
3. **Keep the current probe as a refusal.** Cons: refuses healthy deployments (shown above).

The decision also has to say whether the public `check_ready()` runs this probe (it does not today), and what PG probes.

### Decision 3: Is mandatory config injection in scope, and does it include table names?

**Options:**
1. **Mandatory `Config` for `DbProperty`/`DbPropertyList` only.** Pros: removes the env fallbacks and `use_lookup_table`. Cons: about 116 test call sites change. Table names stay frozen at import, so the feature's "removes import-time table-name reads" is not delivered.
2. **Also move table names to `Config`.** Cons: touches every model `Meta`, the harness freeze (`conftest.py`, `_isolated_store.py`) and the maintenance CLIs. This is the `dynamodb-known-next.md` item 5 design, which is plan-sized.
3. **Drop only the `use_lookup_table`/`INDEXED_PROPERTIES` env fallbacks** and leave constructors optional. Cons: config-less accessors keep defaulting silently.

### Decision 4: Flip the `unique_creator` default in 3.16?

This reopens a decision recorded in `CHANGELOG.rst:319-320`, `docs/migration/v3.16.rst:526` and the 2026-10-28 plan.

**Options:**
1. **Flip, with no auto-enable.** Every fresh deployment, every quickstart user and every test app must run `enable --apply` first (two starts on DynamoDB). About 40 test files change.
2. **Flip, and auto-enable an empty store.** When the actor table is empty (and only then), write the marker or build the index at startup. Pros: fresh deployments and the quickstarts just work, and the refusal stays for stores with data. Cons: a new write at startup; a race between two first starts; the "wrong prefix reads as empty" hazard `collect()` guards against (`unique_creators.py:345-350`) applies here too. PostgreSQL `CREATE INDEX CONCURRENTLY` at startup needs DDL rights the app may not have.
3. **Keep the default off** (the recorded decision). The feature's "one mode" outcome is not reached for uniqueness.

Whichever is picked, the maintenance command's config stays off.

### Decision 5: Registration expiry design

The hypothesis as written cannot be implemented as is: trust rows have no TTL, the row that matters for user tokens is on the user's actor, rotation writes nothing keyed by client, and PG never purges `mcp_clients`.

**Options:**
1. **TTL on the client record and the global index only; delete the system-actor trust row as part of the expiry.**
   - Raise the TTL at the three `OAuth2Server` post-success points: a new conditional write per grant.
   - Add `mcp_clients`/`_client_index` to the PG purge bucket lists.
   - Pros: no trust-row TTL, no protocol change.
   - Cons: on DynamoDB the system-actor trust row still needs a deleter, because a native TTL sweep fires no code. The user-actor row stays until the user's trust is removed, which is arguably correct: it is the user's connection record.
2. **TTL on trust rows on both backends.** Model attribute, Alembic migration, read filtering, PG reaper, a protocol Breaking entry, a second manual TTL enablement, and loss of the `Trust.delete()` cascade on sweep. Pros: matches the hypothesis. Cons: the largest change, and it targets a row user tokens do not read.
3. **A sweep from the existing throttled purge** (`maybe_purge_expired_tokens` before every `/oauth/token`). It removes registrations with no live refresh token, plus their system-actor trust row, through `delete_client(…, actor_id=system)`. Pros: runs the existing cascade, works the same on both backends, needs no new trust schema. Cons: the feature rejected sweeps for needing "a global index walk". It also requires knowing which clients have live tokens.
4. **Defer, and prefer CIMD.** Supporting Client ID Metadata Documents (MCP 2025-11-25 SHOULD) stops registrations being created for CIMD clients. It does not clean up existing DCR rows.

Whatever is picked, the trust-list walk at `client_registry.py:563-577` can be dropped on its own, since it only builds a log string.

### Decision 6: Where an expired registration is rejected

**Options:**
1. **Reject at `/token` and keep `/authorize` lenient** (non-strict read, as today). Pros: Claude Code ≥ 2.1.233 recovers from a `/token` `invalid_client`. A `/authorize` rejection cannot be redirected (RFC 6749 §4.1.2.1) and leaves clients stuck (#84614, #72818). Cons: an expired registration can still start an authorization that then fails at the code exchange. The client re-registers at that point.
2. **Make `/authorize` strict as well.** Pros: consistent. Cons: produces the stuck state for every client the evidence covers.

**Recommendation:** option 1. That is today's asymmetry, and it is the only answer clients are shown to recover from. Separately, the TTL should be long enough that a client used within its refresh lifetime is never expired at `/authorize`.

### Decision 7: How the SPA error code reaches the client

**Options:**
1. **Forward `X-ActingWeb-Error` by name in both SPA translators**, next to `Retry-After`. Also add it to `spa_cors_headers()` and to the `_errors.py:193,200` literals, set it in the fault handler and in the FastAPI session-retrieve. Pros: a narrow, explicit diff; follows the `Retry-After` precedent.
2. **Copy all handler headers in the SPA translators,** as logout does. Pros: future headers come along. Cons: widens what the handler can leak onto the SPA routes.
3. **Use RFC 6750 `WWW-Authenticate: Bearer error="…"`** instead of a custom header. Pros: standard. Cons: covers only `invalid_request`/`invalid_token`/`insufficient_scope` and 401/400/403. It still needs Expose-Headers, and it does not label 400/404/500/503 answers.

**Recommendation:** option 1.

### Decision 8: The code's body key and vocabulary

**Options:**
1. **A new `code` key** next to `error: true`, following the `oauth_email.py` precedent. The vocabulary is OAuth-shaped where it fits (`invalid_grant`, `invalid_request`, `unsupported_grant_type`, `temporarily_unavailable`) plus library codes for theft and reuse (for example `refresh_token_reused`).
2. **Change `error` to a string.** Cons: breaks every client that reads `error === true`.

**Recommendation:** option 1. The vocabulary itself is a plan-level decision: about 60 sites, and the theft, reuse and expired 401s at `:769/:808/:697` are the ones the consumer's client branches on.

### Decision 9: `-32700` placement, given the body is read before auth

**Options:**
1. **After auth, as the feature says.** The integrations pass a parse-failure sentinel that skips `_reject_non_object_body`; the handler answers 400 `-32700` only once authenticated. Unauthenticated callers still get the 401 challenge.
2. **Before auth, alongside the non-object rule.** Pros: one consistent rule ("malformed body → 400 before auth"), matching the TypeScript SDK. Cons: an unauthenticated client sending garbage misses the discovery challenge. The feature rejected this, but on the premise that auth already came first, which it does not.

### Decision 10: Conditional writes raising on a fault

**Options:**
1. **Raise `DbError` on a fault** (the feature's choice). This needs `consume_once` reworked: catch `DbError` around the swap, then take the existing strict re-read path, so the lost-acknowledgement win survives. It also needs a decision on whether `try_claim_session` and `MobileTicketStore.consume` answer 503 (arguably correct), and four contract texts plus the migration guide rewritten.
2. **Keep `False`-on-fault for the two existing methods; only the new `create_attr_if_absent` raises.** Pros: no caller changes. Cons: two contracts side by side in one protocol.

### Decision 11: `create_attr_if_absent` semantics on expired rows and the cross-bucket key

Does an expired-but-present row count as absent? A TTL-aware condition: DynamoDB `attribute_not_exists(id) OR ttl_timestamp <= :now`; PG `ON CONFLICT … DO UPDATE … WHERE attributes.ttl_timestamp <= now`. The consumer's unlock ask has a TTL, so this decides whether a second ask is refused for up to days after the first expired.

Also decide whether the condition includes `bucket = :bucket` to stay safe against cross-bucket key collisions, and whether a `False` after an SDK retry is recognised (the `append_once` read-back pattern).

### Decision 12: Glob escapes, and the second engine

Escapes in `_glob_to_regex` only, or also replacing the `fnmatch` uses in `peer_permissions.py` and `callbacks.py` with the same function. The todo's description of current behaviour also needs correcting.

### Decision 13: Auth config scope

Require `config` on the two helpers only, or on `Auth.__init__` as well (`tests/test_auth.py:101-115` changes). Neither choice affects a known caller.

### Decision 14: Tag audit scope

Only `sessions` out and `listproperties` in (the feature), or the todo's full audit (`onewaytrust`, `actions`/`methods`, `callbackcompression`).

## Documentation impact

I swept `docs/`, `README.rst` and `examples/demo/README.md` for each item. This lists every page that states current behaviour the feature changes. Migration guides for already released versions (`v3.10`, `v3.13`, `v3.15`) are historical and left as they are.

### Legacy lookup removal

- **`docs/quickstart/configuration.rst:455-493, 557-579`:** legacy mode, `USE_PROPERTY_LOOKUP_TABLE`, the rollback path, and the "Legacy GSI/Index" table row. These are removed or rewritten as "the only mode".
- **`docs/reference/database-backends.rst:410-478`:** legacy GSI and lookup-mode text on both backends. The PG part needs the backfill from Decision 1.
- **`docs/guides/database-maintenance.rst:69`:** capacity for the v1 `<prefix>_property_lookup` table. Becomes a note that the table can be dropped.
- **`docs/contributing/architecture.rst:490-494`:** "Avoid Direct Instantiation" names `use_lookup_table`.
- **No change needed:**
  - `README.rst:218-220` ("on by default") stays true.
  - `docs/reference/security.rst:146-150` and `docs/reference/actor-deletion.rst:233` describe the v2 table and the PG `property_lookup` cascade.
- **Outside `docs/`:** the `CLAUDE.md` "Property Reverse Lookup" section is already stale (it says lookup mode is off by default).
- **New:**
  - A `docs/migration/v3.16.rst` section for the removal, with the startup refusal text, the DynamoDB script, the PG backfill, and dropping the `property-index` GSI and the v1 table.
  - A row in `docs/migration/index.rst`.

### Uniqueness default (only if Decision 4 flips it)

- **`docs/quickstart/configuration.rst:43`:** "default ``False``, on at the next major".
- **`docs/quickstart/configuration.rst:238`:** IAM ("With ``with_unique_creator()`` the tables include ``<prefix>_creators`` … ``ConditionCheckItem``") becomes the default IAM set.
- **`docs/reference/security.rst:89`:** "Off by default in 3.16".
- **`docs/reference/security.rst:90`:** the limitations clause on `unique_creator` off becomes the opt-out case.
- **`docs/quickstart/getting-started.rst:186, 205`:** sets the flag explicitly and says to run `enable --apply` first. That stays correct, but the explicit call becomes redundant. If Decision 4 adds an empty-store auto-enable, the first-run instructions change.
- **`docs/guides/authentication.rst:1039-1047, 1340`:** examples that set the flag explicitly.
- **`docs/reference/database-backends.rst:546-573`:** written as "under ``with_unique_creator()``".
- **Migration guide:** `docs/migration/index.rst:49` and `docs/migration/v3.16.rst:526` ("stays off by default in 3.16").
- **`examples/demo/README.md:68-73`:** the start → enable → start sequence is unchanged, but it becomes the path for every new deployment, not just the demo.
- **Quickstart guides:** none currently tells a new user they need `actingweb-unique-creators enable --apply`. Under option 1 of Decision 4, every quickstart path needs that step.

### Create-if-absent and the conditional fault contract

- **`docs/sdk/attributes-buckets.rst:52-112` ("Atomic Operations"):**
  - The example is the read-then-CAS pattern.
  - "How It Works" says `False` means "modified by another request", without mentioning that a fault answers `False` too. That is already inaccurate against the code today, whichever option Decision 10 picks.
  - This is where `create_attr_if_absent` would be documented, next to the CAS.
- **`docs/reference/database-backends.rst:523-525`:** custom-backend contract ("Conditional operations keep their meaning … answer True only when *this* call changed the row"). Rewritten under Decision 10 option 1. The new protocol method is added here.
- **`docs/migration/v3.16.rst:457-480`:** the "Custom database backends" list (`:467-472`), which gains the new method and, if chosen, the fault change.
- **API reference:** generated from docstrings (`protocols.py:25-27, 1345-1347, 1377-1378`, `attribute.py:356-358`), so it follows the code.

### Registration expiry

- **`docs/sdk/attributes-buckets.rst:182-185`:** the bucket table lists `mcp_clients` as "Permanent / Client deletion". Its lifetime and cleanup change.
- **`docs/sdk/attributes-buckets.rst:300-310` ("MCP Client Deletion"):** describes `delete_client()` only. Expiry needs its own paragraph, and so does the system-actor trust row, which no doc mentions.
- **`docs/guides/oauth2-setup.rst:168`:** "``client_secret_expires_at: 0``, it does not expire". This is true of the secret, but a reader will take it to mean the registration.
- **`docs/guides/oauth2-setup.rst:236-276` (system actor storage):**
  - Names the index bucket `mcp_clients_index`, but the code uses `_client_index` (`client_registry.py:682`). This doc error already exists.
  - Lists trust relationships only under the user's actor and omits the system-actor trust row written at registration.
- **`docs/reference/routing-overview.rst:227-246`:**
  - Covers the register, authorize and token answers.
  - Does not say what an unknown or expired `client_id` gets at `/oauth/authorize` (400 `invalid_request` with `invalid_client` in the description).
  - Needs the expiry rule and the authorize/token asymmetry from Decision 6.
- **`docs/guides/troubleshooting.rst:163-192`:** "The reconnect reuses the connector's registration, so it is one sign-in, not a new connector" (`:189-190`) stops being true once a registration has expired. Needs a new entry: "connector asks to reconnect / `invalid_client` after a long absence".
- **`docs/reference/database-backends.rst:253-285`:**
  - TTL enablement. Under Decision 5 option 2 it also needs a second table (`<prefix>_trusts`).
  - The guarantee at `:263-271` ("``ttl_timestamp`` only for temporary data") gains registrations.
- **`docs/guides/mcp-applications.rst:1170-1183, 1340-1341`:** the registration example and "Secure Deletion" bullet. Mention expiry.

### SPA 401 marker

- **`docs/guides/spa-authentication.rst:846-851` (rule 7):** rewritten around the header.
- **`docs/guides/spa-authentication.rst:1017-1019`:** names only `Retry-After` as exposed.
- **`docs/guides/spa-authentication.rst:1535-1541`:** the 503 body example.
- **`docs/guides/spa-authentication.rst:1702-1734`:** already documents `code` on the email endpoints and says the others have "the same shape without a ``code`` field". This becomes the general rule.
- **`docs/guides/spa-authentication.rst:1771-1773, 1811-1812`:** the theft 401, which gets its code.
- **`docs/guides/troubleshooting.rst:158-161`:** refers to rule 7.
- **New:** a code vocabulary table, either in the SPA guide or in `docs/reference/`.

### POST /mcp parse error

- **`docs/guides/mcp-quickstart.rst:102-104`:** "A body that is not a single JSON-RPC object … is answered ``400`` with a ``-32600`` error". Add the `-32700` case and its order relative to the 401.
- **`docs/reference/routing-overview.rst:247-248`:** lists `/mcp` answers (401, 503). Add 400.

### Advertised option tags

- **`docs/guides/access-control-simple.rst:461-468`** and **`docs/guides/access-control.rst:743-750`:**
  - Both show an example `/meta/actingweb/supported` response that includes `sessions` and omits `listproperties`.
  - Both are unsorted, but the server sorts the list (`config.py:534`).
- **No change needed:** `docs/quickstart/configuration.rst:1023` and `docs/guides/trust-relationships.rst:449` name the endpoint only.
- **`docs/protocol/actingweb-spec.rst:396-457`:** already defines `listproperties`.

### Glob escapes

- **`docs/protocol/actingweb-spec.rst:2241`:** "Evaluate patterns using glob matching with ``*`` (any characters) and ``?`` (single character)". This is the protocol spec, so escapes are a spec change as well as a library one. A peer evaluating the same rules (`peer_permissions.py`, which uses `fnmatch`) must agree.
- **`docs/guides/access-control.rst:20`** ("Flexible glob and URI pattern support"): no page documents the pattern syntax in detail. The escape rule needs a home, most naturally a short "Pattern syntax" section in `access-control.rst`.

### Auth config

- **`docs/guides/authentication.rst:499, 755`:** the signature listings show `config=None`. All examples (`:543, 688, 719, 796`) already pass `config=`.
- **`docs/sdk/advanced-topics.rst:53-77`:** example already passes config.
- **No change needed:** `docs/reference/security.rst:126`. `docs/reference/interface-api.rst:64` is `autofunction`, so it follows the code.

## Release shape

A **minor**, riding 3.16.0, which is held untagged (`thoughts/todo/INDEX.md`; owner memory). It changes:
- **Config options:** `with_legacy_property_index`, `USE_PROPERTY_LOOKUP_TABLE`, the `unique_creator` default.
- **A protocol method:** a fourth custom-backend Breaking entry.
- **Response fields and headers:** `code`, `X-ActingWeb-Error`.
- **The MCP error answer.**
- **The advertised tags.**
- **A public signature:** `check_and_verify_auth`.

It needs `docs/migration/v3.16.rst` sections for each of these. If Decision 4 flips the default, it also needs the "stays off until the next major" lines in `CHANGELOG.rst:319-320` and `v3.16.rst:526` rewritten.

**Still open after this research:**
- What claude.ai does on `invalid_client`: one unconfirmed third-party report.
- The consumer's 2026-09-21 audit numbers.
- Whether any PyPI deployment runs the legacy lookup: unknowable.
- Which rows the consumer's Connections page lists: `../actingweb_mcp` was not read for this.

## Code References

- `actingweb/db/dynamodb/property.py:24-98, 141-191, 258-366, 601-621, 737-769` - legacy models, env fallbacks, lookup tiers, conditional create model
- `actingweb/db/dynamodb/property_lookup.py:74-113, 169-193` - v1 model and tier
- `actingweb/db/postgresql/property.py:54-98, 178-283, 330-419, 623-654` - PG fallbacks, scans, write-time lookup, conditional create
- `actingweb/interface/app.py:29-31, 84, 473-495, 1527-1529, 1545-1644` - `UniqueCreatorNotReady`, defaults, legacy builder, probe, readiness
- `actingweb/maintenance/unique_creators.py:143-160, 274-287, 345-350, 753-984` - enable, marker, readiness
- `actingweb/config.py:89, 101-109, 337-340, 393-415, 509-534` - defaults, tags
- `scripts/backfill_property_lookup.py:145-159, 229, 282-290` - DynamoDB-only backfill
- `actingweb/oauth2_server/client_registry.py:46-149, 189-223, 333-352, 462-507, 563-577` - registration, strict and non-strict loads, walk
- `actingweb/oauth2_server/oauth2_server.py:80-118, 161-163, 497-683` - registration owner, authorize/token client checks, post-success points
- `actingweb/oauth2_server/token_manager.py:137-494, 857-892, 1820-1864` - grants, refresh mint, purge
- `actingweb/handlers/mcp.py:861-998, 2364-2643` - body/auth order, trust lookup
- `actingweb/handlers/oauth2_spa.py:135-174, 1823-1844` - CORS, `_json_error`, `_store_unavailable`
- `actingweb/interface/integrations/flask_integration.py:1463-1486, 1546-1557` and `fastapi_integration.py:2321-2343, 2484-2493` - header drop, body parse
- `actingweb/interface/integrations/_errors.py:26-39, 78-90, 179-201` - fault answers and CORS
- `actingweb/db/protocols.py:25-27, 447-472, 698-822, 1322-1380` - contracts
- `actingweb/single_use.py:145-221` - consume and delete-confirmed recovery
- `actingweb/permission_evaluator.py:669-723` - glob
- `actingweb/auth.py:83-85, 810-932` - per-call `Config()`

## External References

- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization - DCR is a MAY, CIMD a SHOULD; nothing on registration lifetime
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports - HTTP error status for messages the server cannot accept
- https://github.com/anthropics/claude-code/issues/84614 - Claude Code re-registers on `/token` `invalid_client`, stuck on `/authorize`
- https://github.com/anthropics/claude-code/issues/72818 - Desktop shows the authorize error page with no recovery
- https://github.com/anthropics/claude-code/issues/59460 - re-registration per authenticate; `/register` rate limits lock users out
- https://github.com/anthropics/claude-ai-mcp/issues/247 - claude.ai connector with a stale `client_id`, unconfirmed
- https://app.unpkg.com/@modelcontextprotocol/sdk@1.25.1/files/dist/cjs/client/auth.js - TypeScript SDK re-registers only via `invalidateCredentials`
- https://www.rfc-editor.org/rfc/rfc6749.html - §4.1.2.1 no redirect for an invalid client; §5.2 `invalid_client`
- https://www.rfc-editor.org/rfc/rfc7591.html - `client_secret_expires_at` is for secrets only
- https://www.rfc-editor.org/rfc/rfc6750.html - `WWW-Authenticate error=` codes
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/howitworks-ttl.html - TTL deletion "typically within a few days"; expired items stay readable
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Access-Control-Expose-Headers - `*` does not act as a wildcard with credentials
- https://www.jsonrpc.org/specification - `-32700` with `id: null`
