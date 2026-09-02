---
status: active
---

# Implementation Plan: 3.14.4 — identifier matching, attribute contracts, MCP metadata fidelity

**Date:** 2026-09-02
**Research:** no single research document. The inputs are four todo files, each
carrying verified `file:line` findings, plus four adversarial reviews of this
plan's first draft (recorded under "Evaluation Notes"):
`thoughts/todo/glob-to-regex-anchoring-gaps.md`,
`thoughts/todo/attribute-get-bucket-empty-vs-none.md`,
`thoughts/todo/attribute-upsert-bucket-drift.md`,
`thoughts/todo/mcp-discovery-metadata-fidelity.md`.
**Branch:** to be created as `release/3.14.4-identifier-matching` from `master`
after PR #140 (the 2026-09-02 todo review) merges.

## Overview

Four small todo items were each deferred from a patch release because they
"wanted their own release note". Bundling them gives them one. The review of the
bundle found that the first is not a tidy-up: a peer holding the shipped `friend`
or `partner` trust type can **write into `private/`, `security/` or
`_internal/`** by putting a percent-encoded newline in a property path, because
`*` in the exclusion pattern compiles to `.*` and cannot cross a newline. That
finding sets the shape of Phase 1 and the tone of the changelog.

Everything here is about **identifiers** — property names, list names, tool,
method, prompt and resource names, peer ids, the `fqdn`. Nothing touches values:
tool input, property content, list items, markdown, HTML or binary payloads
remain arbitrary.

## Decisions Made

- **Version 3.14.4, a patch.** Owner's call on 2026-09-02, against the
  recommendation of 3.15.0. Consequence: the changelog must carry every
  behaviour change explicitly, and `docs/migration/v3.14.rst` is **not**
  touched — no patch release has ever added to a migration guide, and doing so
  would break the signal that an entry there means a minor release.
- **Control characters in identifiers are rejected in two places.** The
  permission evaluator returns `DENIED` for any target containing one (a single
  funnel that covers every identifier kind), and new property and list names
  containing one are rejected at the store and REST layer. Rationale: `\Z`
  alone narrows matching, which is safe for allow rules and a regression for
  bare-literal deny entries (`denied: ["notes"]` catches `notes\n` today by
  accident and would stop). The evaluator guard closes that regression; the
  write-time check stops the class from being stored again.
- **All seven `$`-anchored identifier validators are fixed**, not just the
  evaluator. Mechanical, one changelog bullet, a test each.
- **MCP permission checks fail closed.** Six sites deny on evaluator exception
  and log at `error`, matching `authenticated_views.py`. Owner accepted the
  risk that an app whose evaluator throws for an unrelated reason loses MCP
  access until fixed — that is the correct failure.
- **Attribute point reads gain the exact bucket compare** that bucket listing
  gained in 3.14.3. Same subsystem, same collision, completes the fix.
- **`/mcp/info` drops its literal fields and derives the rest.** `tools_count`,
  `prompts_count`, `actor_lookup` and the demo `description` go. `mcp_enabled`
  comes from `config.mcp`, `supported_features` from the hook registry via the
  same helpers `initialize` uses, `description` from `config.desc` (the
  endpoint is the `resource_documentation` target of the discovery chain, so
  it keeps a per-app line of prose), `server_name` from
  `config.mcp_server_name`. **No library version**: the endpoint is
  unauthenticated, a version-to-CVE map is what a scanner wants, and no other
  unauthenticated surface discloses it.
- **`fqdn` and `proto` are stripped, then validated, at the end of
  `Config.__init__`.** Not at the default assignment (`config.py:43`, which
  never sees the caller's value) but after the kwargs loop at `config.py:249`.
  Surrounding whitespace is stripped rather than rejected, so an
  `APP_HOST_FQDN` with a trailing newline from a `.env` file keeps booting.
  Rejected: `"`, `\`, interior whitespace, C0/C1 control characters. **Not**
  rejected: `/` (`www.py:18` documents a base-path fqdn) and `:` (`host:port`
  is used throughout the quickstart docs). Coverage is construction-time only;
  `_apply_runtime_changes_to_config()` never touches `fqdn`, so there is no
  setter path to guard.
- **`get_oauth_discovery_metadata()` is removed outright**, under a `REMOVED`
  heading, no deprecation cycle. It is dead (both integrations route
  `/.well-known/oauth-authorization-server` through `OAuth2EndpointsHandler`),
  unpublished (the API docs render `:show-inheritance:` without
  `:inherited-members:`), and wrong (`scopes_supported` is neither the served
  list nor a subset). Precedent: CHANGELOG.rst's v3.11 `REMOVED` section.
- **Phases 1–3 of the first draft are merged** into one security phase, per
  the owner. Four phases total.

## What We're NOT Doing

Each of these is filed as a `thoughts/todo/` entry in Phase 4 rather than
folded in, with the reviewer's `file:line` so nobody re-derives it:

- **Per-request `Config()` construction in `auth.py:83`, `:839`, `:919`.**
  The public `check_and_verify_auth()` helpers build a fresh `Config` when a
  caller omits one; every config-bound singleton compares by identity, so each
  such request rebuilds the permission evaluator, trust registries and their
  caches, and re-runs `logging.basicConfig()`. Largest per-request cost near
  this change set; separate ticket.
- **Five DB-layer `get_bucket(...) or {}` sites** (`attribute_list_store.py:60`,
  `callback_processor.py:547`, `remote_storage.py:200`, `:297`,
  `fanout.py:256`) that turn a now-distinguishable PostgreSQL fault into
  "empty". Not a regression — `None` already meant empty-or-fault — but Phase 2
  is what makes the distinction available, and the changelog says so.
- **The `pattern.endswith("://")` prefix branch** at
  `permission_evaluator.py:622` is an unnormalised `startswith` on
  client-controlled resource URIs (`notes://` matches
  `notes://../../security/key`). Shipped defaults use `notes://*`, which takes
  the regex path; only custom configs are exposed.
- **`re.escape` + `.replace` in `_glob_to_regex()`** mishandles a
  backslash-escaped glob (`a\*b` becomes a wildcard). Fix is a
  character-by-character scanner; not a patch-release change.
- **Unicode normalisation of identifiers.** NFC and NFD forms of one visible
  name are distinct keys. Same failure shape as the newline bug, not closed by
  it.
- **Adjacent unbounded caches** on the permission path
  (`trust_permissions.py:97`, `peer_profile.py:113`, `peer_permissions.py:226`,
  `peer_capabilities.py:480`) grow with traffic, not config.
- **`config.py:143`** builds `oauth["redirect_uri"]` from the pre-kwargs default
  fqdn — masked whenever `oauth=` is passed, a footgun otherwise.
- **Making `fnmatch` and `_glob_to_regex` equivalent.** After Phase 1 they
  agree on anchoring and DOTALL; `fnmatch` additionally supports `[seq]` and
  applies `os.path.normcase`. Not this release's problem.
- **Rejecting a scheme-prefixed `fqdn`** (`https://myapp.example.com`). It
  contains none of the rejected characters and produces a doubled scheme in
  every URL, as it always has. The changelog names it.

---

## Phase 1: Identifier matching hardening (security)

Lands and is verifiable on its own. The evaluator change alone closes the live
`private/` write bypass; the rest closes the class.

### Changes

**`actingweb/permission_evaluator.py`**

- `_glob_to_regex()` (`:635-645`): return `f"^{escaped}\\Z"` instead of
  `f"^{escaped}$"`.
- `_matches_pattern()` (`:604-632`): compile with `re.compile(regex_pattern,
  re.DOTALL)` at `:630`. Add a comment pinning that this is the single compile
  site and the cache key (`pattern` alone) assumes it.
- `_pattern_cache` (`:66`): bound it. Simplest: clear the dict when it exceeds
  1024 entries — patterns are owner-authored config, cardinality is small, a
  cold recompile is cheap. Not an LRU; not worth the dependency.
- `_evaluate_rules()` (`:520`): before the `denied` check, return
  `PermissionResult.DENIED` if the target contains any character in
  `\x00-\x1f` or `\x7f-\x9f`. This is the common funnel for
  `evaluate_property_access`, the bulk path, and every other
  `evaluate_*_access`, so one guard covers property, list, method, action,
  tool, prompt and resource identifiers. Log at `warning` with the identifier
  kind and a `repr()` of the target — an identifier reaching here with a
  control character is either the attack or a bug upstream, and both deserve a
  line.

**Six other identifier validators**, same fix, `$` → `\Z` or `re.fullmatch`:

- `actingweb/remote_storage.py:20` `DEFAULT_PEER_ID_PATTERN` and `:23`
  `PERMISSIVE_PEER_ID_PATTERN`; `:46` `pat.match(...)` → `pat.fullmatch(...)`.
  This is the validator that accepts `<32 hex>\n` today and is how a
  `remote:<id>\n` bucket name comes to exist.
- `actingweb/oauth_state.py:64` and `actingweb/oauth2.py:579`:
  `re.fullmatch(r"[A-Za-z0-9+/_=-]+", state)`. A state with a trailing newline
  was classified as encrypted MCP state.
- `actingweb/property_list.py:82` `_V1_INDEX_RE` → `^\d+\Z` (used at `:1701`
  to filter v1 item rows); `:2760` orphan-row pattern → `\Z`.
- `actingweb/mcp/uri.py:26`: `"^" + ... + "\\Z"`.

**MCP resource dispatch**

- `actingweb/handlers/mcp.py:1597`: `re.match(uri_pattern, str(uri))` →
  `re.fullmatch(...)`. `uri_pattern` is undocumented in `docs/`, `examples/`
  and `skills/`, so no documented contract changes; the changelog states the
  new semantics anyway. Check whether `actingweb/handlers/async_mcp.py` has
  the same dispatch and apply the same change.

**MCP permission checks fail closed** — six sites, one shape:

- `actingweb/handlers/mcp.py:1369` (tools), `:1455` (prompts), `:1565`
  (resources); `actingweb/handlers/async_mcp.py:177`, `:263`, `:370`. Each
  `except Exception: logger.debug("Skipping ... permission check due to
  error")` currently falls through and serves the request. Change to: log at
  `error` with `exc_info=True`, and return the same denial the permission-check
  failure path returns. Model the wording on
  `actingweb/interface/authenticated_views.py:100-108`, which documents why it
  fails closed.

**Write-time rejection of control characters in property and list names**

- `actingweb/property.py`: `PropertyStore.__setattr__` (`:289`) and
  `__setitem__` (`:280`) raise `ValueError` for a name containing a control
  character. `PropertyListStore.__getattr__` (`:250`) raises the same when the
  list does not yet exist and the name contains one — existing lists with such
  a name stay reachable to the owner, so a deployment that already has one is
  not locked out of cleaning it up.
- `actingweb/handlers/properties.py`: the PUT (`:654`) and POST (`:912`)
  handlers map that `ValueError` to `400` with a message naming the offending
  character by `repr()`. GET is unchanged — reads of an existing name go
  through the evaluator, which now denies peers and permits the owner.

### New tests

- `tests/test_permission_pattern_matching.py` (new, unit):
  - `_matches_pattern`: newline-containing targets against exact, `*` and `?`
    patterns, both directions (`notes` vs `notes\n` → False; `memory_*` vs
    `memory_a\nb` → True; `notes?` vs `notes\n` → True and documented as the
    accepted over-match).
  - the three short-circuits at `:614`, `:617`, `:622` pinned as unchanged.
  - `_evaluate_rules` level, the two blocking cases from review:
    `{"denied": ["secret"], "allowed": ["*"]}` with target `secret\n` →
    `DENIED`; `{"patterns": ["*"], "excluded_patterns": ["private/*"],
    "operations": ["read","write"]}` with target `private/x\ny` → `DENIED`.
    Both must be `DENIED` via the control-character guard, and a variant with
    the guard monkeypatched out must show `\Z`+DOTALL alone gives
    `ALLOWED`/`DENIED` respectively — so the test documents *why* the guard
    exists.
  - `_pattern_cache` clears past its bound.
- `tests/integration/test_property_path_control_chars.py` (new): the exploit
  chain end to end on both integrations — a `friend` peer issuing
  `PUT /{actor}/properties/private/%0Asecret` gets `403` (evaluator) and the
  owner issuing the same gets `400` (write-time rejection); the owner can still
  `GET` and `DELETE` a pre-seeded property whose name contains `\n`.
- `tests/test_remote_storage.py`: `<32 hex>\n` rejected by both patterns.
- `tests/test_oauth_state.py` (or nearest existing): a >50-char state with a
  trailing newline is not classified as encrypted.
- `tests/test_property_list*.py`: `_V1_INDEX_RE` rejects `"12\n"`.
- `tests/test_mcp_resource_uri.py` (or nearest): `uri.py` pattern rejects a
  trailing newline; handler dispatch no longer matches a prefix-only URI.
- `tests/test_mcp_fail_closed_authorization.py` (exists): add six cases, one
  per site, where the evaluator raises and the request is denied and an
  `error` log line is emitted. Async cases via the existing async fixtures.

### Verification

- [ ] `poetry run pytest tests/test_permission_pattern_matching.py tests/test_mcp_fail_closed_authorization.py tests/test_remote_storage.py -v` passes
- [ ] `poetry run pytest tests/integration/test_property_path_control_chars.py -v` passes on **both** backends
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` and `ruff format --check` pass
- [ ] `make test-all-parallel` passes
- [x] Manual: the pre-fix and post-fix status of the live vector captured in the PR body (see correction below)

**Correction, 2026-09-02, during implementation.** The URL-path form of the
exploit (`PUT /{actor}/properties/private/%0Asecret`) does not reach a
handler on either integration: Starlette's `{name:path}` and Werkzeug's
`<path:name>` converters both stop at a newline and answer 404. The reachable
form is the JSON body of `POST /{actor}/properties`, whose keys are property
names: at the pre-fix tree a `friend` peer's `{"private/\nx": "v"}` and
`{"_internal/\nx": "v"}` both returned 201 and appeared in the owner's
listing (harness run against `e8eddf1` with `actingweb/` stashed). After the
change both return 400. Tab, NUL and CR *do* reach the handler through the
path, but `*` already matched them, so they were never a bypass; they are
now refused on write. The integration test and the changelog describe the
POST vector, not the path one. MCP `resources/read` URIs are body-carried
too and were covered by the same evaluator guard.

### Implementation Status: Complete

---

## Phase 2: Attribute storage contracts

### Changes

- `actingweb/db/postgresql/attribute.py` `get_bucket()` (`:180-221`): `if not
  rows: return None` → `return {}`. `None` stays for the caught exception
  (`:219-221`) and for missing `actor_id`/`bucket` (`:193`), matching
  DynamoDB (`db/dynamodb/attribute.py:67-68`).
- `actingweb/db/postgresql/attribute.py` upsert (`:405-410`): add
  `bucket = EXCLUDED.bucket, name = EXCLUDED.name` to the `DO UPDATE SET`
  list. Verified safe: the table has only `PrimaryKeyConstraint("id",
  "bucket_name")` plus two partial indexes on other columns
  (`migrations/versions/3307e3616c5e:34-52`), neither column is indexed, and
  PostgreSQL writes a whole tuple on any UPDATE so the cost delta is zero.
- **Exact bucket compare on the four point-read paths.**
  `db/postgresql/attribute.py:252` and `:296` (`get_attr`, `get_attr_strict`):
  `WHERE id = %s AND bucket_name = %s` → add `AND bucket = %s`.
  `db/dynamodb/attribute.py:95` and `:123`: after `Attribute.get(...)`, `if r.bucket != bucket: return None`
  (mirror the guard at `:81` in `get_bucket`). Apply the same to any `delete_attr`
  point path that keys on `bucket_name` alone — check `delete_attr` on both
  backends and `delete_by_chain`'s neighbours.
- `actingweb/db/protocols.py:1020-1032`: rewrite the `get_bucket` docstring to
  state the contract — `{}` for an empty bucket, `None` only for a caught
  backend fault or missing arguments — and note that on DynamoDB most faults
  raise through rather than returning `None`, because the `try` wraps only
  Query construction and PynamoDB fires lazily.
- `actingweb/attribute.py` `Attributes.get_bucket()` (`:77-124`): delete the
  paragraph at `:105-118` that cites `attribute-get-bucket-empty-vs-none.md`
  and argues for the conservative behaviour; replace the `:113` comment.
  State the new consequence plainly: on PostgreSQL an empty bucket is now
  authoritative, so `get_attr(name)` after `get_bucket() == {}` answers `None`
  without a backend read for the life of the instance. Verified during review
  that every `Attributes` instance is request-local except
  `InternalStore._db`, which loads once via `_ensure_loaded` on both backends
  regardless and does not use this path.
- `tests/integration/test_db_attribute_buckets.py:258`: flip to
  `assert attrs._bucket_loaded is True`; rewrite the docstring at `:251-254`.
- `tests/integration/test_db_attribute_buckets.py:155`
  `test_colliding_composite_key_answers_to_exactly_one_bucket`: stop accepting
  either winner; assert the **last** writer owns the row on both backends, and
  that `delete_bucket()` of the loser's bucket leaves it untouched.

### New tests

- `tests/integration/test_db_attribute_buckets.py`: point-read isolation —
  seed the colliding row under bucket `remote:abc`/name `x`, then
  `get_attr(bucket="remote", name="abc:x")` and `get_attr_strict(...)` return
  `None` on both backends; the owning bucket still reads it.
- Same file: PostgreSQL empty bucket → `{}`, and `Attributes.get_attr()` on it
  makes no backend call (patch `DbAttribute.get_attr` and assert not called).
- `tests/test_db_protocols*.py` or nearest: a fake backend returning `None`
  from `get_bucket` leaves `_bucket_loaded` False on both — the fault contract.

### Verification

- [ ] `poetry run pytest tests/integration/test_db_attribute_buckets.py -v` passes on DynamoDB
- [ ] Same with `DATABASE_BACKEND=postgresql` against the test container
- [ ] `poetry run pyright actingweb tests` — 0 errors; ruff check and format pass
- [ ] `make test-all-parallel` passes

### Implementation Status: Complete

---

## Phase 3: MCP metadata fidelity and config validation

### Changes

**Lift the capability helpers.** `MCPHandler._has_mcp_tools` (`handlers/mcp.py:743`),
`_has_mcp_resources` (`:759`), `_has_mcp_prompts` (`:775`) become module-level
functions taking a `HookRegistry` (keep thin method wrappers so
`_handle_initialize` at `:825-841` is unchanged). They are in-memory registry
checks — no DB — which is why they are acceptable on an unauthenticated
endpoint.

**One `/mcp/info` builder.** Add `build_mcp_info(config, hooks) -> dict` in
`actingweb/handlers/mcp.py` next to `mcp_www_authenticate()` (`:412`). No
import cycle: `flask_integration.py:17` already imports `handlers.mcp` at module
level and `app.py` imports integrations lazily. Both integrations'
`_create_mcp_info_response()` (`fastapi_integration.py:2657`,
`flask_integration.py:1793`, byte-identical) become one-line delegations
passing `self.aw_app.get_config()` and `self.aw_app.hooks`. The builder must
stay a pure function of config scalars and the in-memory registry; add a
docstring line saying the endpoint is unauthenticated and must remain DB-free.

Response shape:

| field | source |
| --- | --- |
| `mcp_enabled` | `config.mcp` (today a literal `True` even when MCP is off) |
| `mcp_endpoint`, `authentication.*` | unchanged |
| `server_name` | `getattr(config, "mcp_server_name", None) or "actingweb"` |
| `description` | `config.desc` (`app.py:1279` sets `"ActingWeb app: {aw_type}"`) |
| `supported_features` | derived: `tools`/`resources`/`prompts` present only when the registry has any |
| removed | `tools_count`, `prompts_count`, `actor_lookup` |

**`GET /mcp`** (`handlers/mcp.py:641-647`): `server_name` uses the same
`getattr(...) or "actingweb"` expression as `:847` — not a bare attribute read,
several suites build the handler config from `Mock()`. `capabilities` uses the
lifted helpers instead of three `True` literals, so `GET /mcp`, `initialize`
and `/mcp/info` can no longer disagree. Update `tests/test_mcp_auth_challenge.py:110`
and `tests/test_mcp_disabled.py:64` to expect `"actingweb"`.

**Delete the dead metadata builder.** `BaseActingWebIntegration.get_oauth_discovery_metadata()`
(`base_integration.py:255-273`) and its only callers,
`tests/test_base_integration.py:259` and `tests/test_flask_integration.py:52`.

**`fqdn` / `proto` validation.** In `Config.__init__`, immediately after the
kwargs loop (`config.py:249-250`) and before `self.root`/`self.auth_realm` are
derived (`:353-355`): `.strip()` both, then reject `"`, `\`, interior
whitespace, and any character in `\x00-\x1f` / `\x7f-\x9f` with `ValueError`.
Message names the character class, shows `repr(value)` so a `\n` is visible,
names `APP_HOST_FQDN` / `APP_HOST_PROTOCOL` as likely sources, and states the
accepted form (`host[:port][/base]`, no scheme) — explicitly not "invalid
hostname", which sends an operator chasing DNS. Also strip in
`ActingWebApp.__init__` (`app.py:54-55`) so the value the app holds matches
what Config will accept.

**Docstrings and docs.**

- `app.py:508-510` `with_mcp(server_name=...)`: "announced in the MCP initialise
  handshake" → "…and on `GET /mcp` and `/mcp/info`".
- `docs/quickstart/configuration.rst:1265` same wording; `:29` tighten `fqdn`'s
  documented form to `host[:port][/base]`, no scheme, no trailing slash.
- `docs/guides/access-control.rst:289`: one sentence — patterns must match the
  whole identifier; `*` and `?` also match newline; identifiers containing
  control characters are always denied.

### New tests

- `tests/test_mcp_info.py` (new): the builder on both integrations — `mcp_enabled`
  follows `config.mcp`; `supported_features` follows the registry (empty
  registry → `[]`; a tool registered → `["tools"]`); `description` is
  `config.desc`; `server_name` follows `with_mcp(server_name=...)`; no
  `tools_count`/`prompts_count`/`actor_lookup`/`version` key; the route is
  reachable without auth on both frameworks (pin the current behaviour so a
  later change is deliberate).
- `tests/test_mcp_server_name.py` (exists): `GET /mcp` and `initialize` report
  the same name; `GET /mcp` capabilities match `initialize`'s.
- `tests/test_config.py` (exists): `fqdn="myapp.example.com\n"` → accepted as
  `"myapp.example.com"`; `fqdn='my"app'`, `"my app"`, `"my\x00app"` → `ValueError`
  whose message contains `repr(value)` and `APP_HOST_FQDN`; `"localhost:5000"`
  and `"demo.actingweb.io/base"` accepted; same matrix for `proto`. A test that
  `ActingWebApp(fqdn=" x.example.com ").get_config().fqdn == "x.example.com"`.
- `tests/test_mcp_auth_challenge.py`: the challenge for a stripped fqdn is
  well-formed (no stray whitespace inside the quoted `resource_metadata`).

### Verification

- [ ] `poetry run pytest tests/test_mcp_info.py tests/test_mcp_server_name.py tests/test_config.py tests/test_mcp_auth_challenge.py tests/test_mcp_disabled.py -v` passes
- [ ] `grep -rn get_oauth_discovery_metadata actingweb tests docs examples` returns nothing
- [ ] `poetry run pyright actingweb tests` — 0 errors; ruff check and format pass
- [ ] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` succeeds
- [ ] `make test-all-parallel` passes
- [x] Shape and app-derived `description` pinned by `tests/integration/test_mcp_info_route.py` on both frameworks and both backends, in place of the manual curl

### Implementation Status: Complete

---

## Phase 4: Release 3.14.4

### Changes

- `CHANGELOG.rst`: the `Unreleased` section at `:5-6` is **empty** — entries
  are authored, not renamed. Write them under `v3.14.4: <date>`, add a fresh
  empty `Unreleased` above (CLAUDE.md step 3). Headings and content:
  - `SECURITY` (new heading for this release; the house style has used
    `FIXED`/`CHANGED`/`REMOVED` — a security fix warrants its own): the
    exclusion bypass via a newline in a property path, who is affected (any
    deployment granting `friend`/`partner` or any custom type with
    `excluded_patterns` or a bare-literal `denied` entry), what changed
    (whole-identifier anchoring, DOTALL, control-character identifiers always
    denied, six other validators, resource dispatch fullmatch, MCP checks fail
    closed). State plainly that **values are untouched** — only identifiers.
    State the one observable behaviour change for legitimate use: an
    identifier with an embedded newline that a wildcard rule used to miss is
    now matched, and any identifier with a control character is now denied to
    peers and rejected on write. Note the `methods`/`actions` deny bypass was
    closed before it was reachable (dispatch is an exact dict lookup).
  - `FIXED`: PostgreSQL empty-bucket contract **including** the
    `_bucket_loaded` consequence (an empty bucket becomes authoritative on
    PostgreSQL, joining DynamoDB's 3.14.3 contract); upsert attribution
    alignment described as *stored state* alignment and the row-moves-buckets
    consequence; point-read bucket isolation. Phrase as "PostgreSQL now
    reserves `None` for a caught exception" — do **not** claim both backends
    distinguish fault from empty, DynamoDB mostly raises. Name the five
    `or {}` sites as knowingly deferred.
  - `CHANGED`: `/mcp/info` response shape (removed and added fields, the
    discovery-chain reason, "read the tool list from `tools/list`");
    `GET /mcp` `server_name` flip from `"actingweb-mcp"` to `"actingweb"` for
    deployments that never set one; `fqdn`/`proto` validation with the
    accepted form and the scheme-prefix caveat.
  - `REMOVED`: `get_oauth_discovery_metadata()`, with the "wrong while it
    lived" reasoning.
- `pyproject.toml:3` and `actingweb/__init__.py:31`: `3.14.4`.
- **Close the four todos**: delete `glob-to-regex-anchoring-gaps.md`,
  `attribute-get-bucket-empty-vs-none.md`, `attribute-upsert-bucket-drift.md`,
  `mcp-discovery-metadata-fidelity.md`; remove rows 21, 23, 24, 25 from
  `thoughts/todo/INDEX.md`; add a §0-style note that they landed in 3.14.4 and
  point here. `attribute-upsert-bucket-drift.md`'s fix 2 (a delimiter that
  cannot collide) is next-major and already lives in
  `prop-list-key-prefix-scheme.md` — add one line there so it is not lost.
- **File the new todos** from "What We're NOT Doing", one file each with the
  reviewer's `file:line`, and rows in `INDEX.md` §3: `auth-per-request-config.md`,
  `db-layer-get-bucket-or-empty.md`, `permission-uri-prefix-branch.md`,
  `glob-backslash-escape.md`, `permission-path-unbounded-caches.md`. Fold the
  Unicode-normalisation and `config.py:143` items into the nearest of those
  rather than creating seven files.
- Commit as `Release v3.14.4`, PR, CI green on both backends, merge, tag on
  master, push the tag (CLAUDE.md release process).

### New tests

- None beyond `tests/test_version.py` or equivalent if one pins the version
  pair — check; if absent, do not add one for a patch.

### Verification

- [ ] `grep -n '3.14.4' pyproject.toml actingweb/__init__.py` shows both
- [ ] `grep -l "^status: active" thoughts/plans/*.md` returns nothing but this file (set to `active` when Phase 1 starts, `done` after the tag)
- [ ] `make test-all-parallel` passes; CI green on both database backends
- [ ] Tag pushed; GitHub Actions publishes to PyPI and creates the release
- [ ] Post-release: consumer check from `../actingweb_mcp` — bump the pin, run its suite, confirm `/mcp/info` and the trust-relationships page; record the outcome in a verification doc `thoughts/verifications/2026-09-XX-identifier-matching-and-metadata-fidelity.md` and link it from this file's frontmatter

### Implementation Status: Not Started

---

## Evaluation Notes

Four reviewers read the first draft against the tree at `f552747` on
2026-09-02. Everything they cited was re-verified before this plan was written.

### Architecture

- **Blocking, incorporated:** `\Z` narrowing flips a deny into an allow for a
  trailing-newline identifier (`permission_evaluator.py:523`, `:558` → `:566`
  `ALLOWED`); the draft's unit-level test matrix would have passed green while
  shipping it. Now the control-character guard in `_evaluate_rules` plus
  rule-level tests.
- **Blocking, incorporated:** `remote_storage.py:20,23,46` has the same gap
  and is the source of newline bucket names. In Phase 1.
- Should-fix, incorporated: resource dispatch `re.match` → `fullmatch`
  (`mcp.py:1597`); `db/protocols.py` contract docstring; do not overclaim
  DynamoDB fault detection; the `_bucket_loaded` consequence is the real
  behaviour change of Phase 2 and is named in the changelog; `/mcp/info`
  `mcp_enabled` derived; `supported_features` derived via lifted helpers rather
  than a new literal; `server_name` via the `getattr(...) or` expression;
  validate `proto` too; validation placement after the kwargs loop, `host:port`
  must stay legal; the four todo files close in Phase 4; the whole
  `attribute.py:105-118` paragraph goes, not one comment.
- Corrected facts from the draft: `GET /mcp` capabilities are literals, not
  derived; CHANGELOG `Unreleased` is empty, entries are authored; several line
  numbers.

### Security

- **Blocking, incorporated:** the live exploit chain —
  `PUT /{actor}/properties/private/%0Asecret` as a `friend` peer succeeds
  today (`flask_integration.py:404` decodes, `handlers/properties.py:812`
  builds the target, `trust_type_registry.py:323` excludes `private/*`,
  `permission_evaluator.py:645` cannot cross the newline). Impact is integrity
  (injection into a protected namespace), not disclosure. Phase 1 is a security
  fix and the changelog says so.
- **Blocking, incorporated:** `\Z` alone regresses bare-literal deny entries;
  write-time rejection plus the evaluator guard. Owner chose both.
- Should-fix, incorporated: six fail-open MCP permission checks; validation
  location (`config.py:249`, not `:43`); do not reject `/`; omit the library
  version from `/mcp/info`; point-read bucket compare on both backends.
- Deferred with rationale: the `://` prefix branch (custom configs only);
  Unicode normalisation; `re.escape` backslash handling.
- Informational: `fqdn` is never request-derived, so the validation is
  defence in depth; the upsert change cannot cross actors (PK is actor-scoped)
  or forge a bucket boundary (peer id is format-validated).

### Scalability

- Nothing blocking. Regex change is cost-neutral (no nested quantifiers,
  identifiers ≤255 chars); bulk path cost unchanged; Phase 2 removes a point
  read per absent name on PostgreSQL empty buckets; upsert widening is free
  (whole-tuple writes, no index on either column); `/mcp/info` stays DB-free;
  Config is built once per app.
- Incorporated: bound `_pattern_cache` (`permission_evaluator.py:66`) while
  the function is open.
- Filed: per-request `Config()` in `auth.py` fallbacks — the largest per-request
  cost adjacent to this change set; adjacent unbounded caches.

### Usability

- Incorporated: strip before validating so a trailing newline in
  `APP_HOST_FQDN` does not crash a patch upgrade; actionable error message
  naming the source and the accepted form; `description` derived from
  `config.desc` because `/mcp/info` is the discovery chain's documentation
  target; `server_name` docstrings in `app.py:508` and
  `configuration.rst:1265`; the `"actingweb-mcp"` → `"actingweb"` flip named
  as the observable change; changelog only, no migration-guide entry for a
  patch; straight `REMOVED` with precedent.
- The reviewer's proposed changelog wording is the starting text for Phase 4,
  adjusted for the decisions taken after it was written (no `version` field,
  `SECURITY` heading, seven validators, fail-closed MCP checks, point reads).
