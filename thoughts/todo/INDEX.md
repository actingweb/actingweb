# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Last full re-rank:
2026-09-06.**

**This directory holds only what is *not* done.** When work lands, its file is
deleted — the plan and the verification are the record, and they are where the
decisions and the implementation history live. Nothing here should say what
shipped, when, or in which release, except as a pointer to the plan that says
it properly.

**This file is a table of contents, not a source of truth.** Each row says what
implementing it buys and why it is worth doing — one line each, deliberately.
Everything else lives in the linked file. If a row and its file disagree, the
file wins.

**Maintaining it:** add a row when you add a todo, delete the row when you
delete the todo. Re-rank when something lands or a trigger fires. Don't copy
detail up here — a duplicated fact is a fact that will drift. Rows are
identified by their file, not by a number: numbering a living queue means either
renumbering (which silently changes what an old reference means) or freezing the
numbers (which turns the index into a record of what used to be here).

Ordering is by *impact ÷ effort*, not by severity alone: a cheap fix to a
moderate problem outranks an expensive fix to a slightly worse one.

---

## 1. High leverage

Bigger, designed, and each buys more than it costs. Both are blocked on a
decision nobody has made, not on effort.

| Item | Impact of doing it | What it needs first |
| --- | --- | --- |
| [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers, and `4 x peers` per page load on a consumer endpoint measured at p50 689 ms | **The ordering is the whole item.** The one-line guard fix (`is None`) is unsafe until the cross-request `Actor` cache is dealt with: the falsy guard is what stops a long-lived MCP-cached actor going permanently blind to subscriptions created in another container. Take the cache-lifetime question — should `_actor_cache` hold instance state at all — not the guard. The consumer has a per-call-site workaround, so this is not urgent; it is the highest-value item that is not waiting on a release |
| [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the v2 format | The chosen approach is the full v2 port, which is mostly a port now that the fractional-rank format and its primitives are proven. Sequencing is unresolved: after [whole-list rewrite atomicity](whole-list-rewrite-atomicity.md), which has two dead designs and no third, or accept the same documented window `ListProperty` shipped with and fix both classes later. Owner's call, not made |

## 2. Real, not urgent

| Item | Impact of doing it | Why now |
| --- | --- | --- |
| [Creator uniqueness is not enforced, only logged](creator-uniqueness-not-enforced.md) | Closes the check-then-create race that can duplicate an actor's creator (a WARNING now surfaces existing duplicates; nothing yet stops new ones) | Needs a backfill decision for existing duplicates before a unique index can be added — a unique index cannot be created over data that already violates it |
| [GitHub's `/user/emails` API is called twice on the identifier-extraction failure path](github-emails-api-called-twice.md) | Removes a ≈45s worst-case stall (past API Gateway's 30s Lambda integration timeout) on the `require_email`-and-no-public-email path | Two fix shapes sketched, not evaluated against each other; low-probability edge case, no reported incident |
| [`GET /oauth/spa/session/{id}` has no endpoint-level test](spa-session-retrieve-endpoint-test.md) | Pins the two response transitions 3.14.5 introduced there (a pending email session and a server-PKCE session both became 404) at the layer a consumer actually calls | Coverage only — the manager-level tests already cover the logic carrying the security property, so nothing is at risk while this waits. One file, cases already enumerated |
| [No logout path revokes a refresh token](logout-does-not-revoke-refresh-chain.md) | Makes "log out" end the session **server-side**, not just on the device: today the access token is revoked and the refresh chain lives out its full TTL (14 days at the consumer). Wider than filed — the cookie-revoking branch is dead code, and the live path clears cookie names nothing writes, so a browser keeps a working refresh cookie | Semantics are settled (chain-scoped, per the `create_refresh_token` design); the *storage* cost is not — `delete_by_chain` on DynamoDB scans the whole shared token partition, which its own docstring licenses only for a rare theft event. Three options in the file; pick one before implementing. **Two cheap halves are independent of all that**: fixing the cookie-name list is two lines and the only thing that helps a browser SPA at all — its refresh cookie is HttpOnly, so the client-side `/oauth/revoke` workaround is closed to it; and `docs/guides/spa-authentication.rst:207` advertises `/oauth/logout` as clearing "all tokens", which is false for every client shape |
| [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Merging the two metadata paths **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent`, so it is not an independent decision. Decide it with the structuredContent research (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove | Two designs died under adversarial review and the file carries the constraints they established — chiefly that `fetch_all_including_lists` is a paginated Query, not a snapshot. Do not propose a third without reading them. Reachability is low (`compact()` is an operator action) and the current failure is loud, which is what makes the wait defensible |
| [v2 list access follow-ups](v2-list-access-verification-followups.md) | Two integration tests a plan named and nobody wrote (end-to-end peer-replica diffs, interleaved append), plus the www HTML UI's missing contention mapping | Nothing blocks; waits for the next time someone is in the subscription-delivery or www code |
| [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Test-infrastructure reliability only, not correctness. Nothing has been instrumented for it |
| [`auth.py` per-request `Config()`](auth-per-request-config.md) | Stops the public `check_and_verify_auth()` helpers rebuilding every config-bound singleton — evaluator, registries, caches — and re-running `logging.basicConfig()` on each request that omits a config; the largest per-request cost next to the permission path. Also carries the `redirect_uri`-from-default-`fqdn` footgun | The library's own integrations always pass a config, so the exposure is direct callers; the fix is a signature change and wants a minor |
| [DB-layer `get_bucket(...) or {}`](db-layer-get-bucket-or-empty.md) | Five sites that fold a bucket-read fault into "empty", the same shape that emptied a list in 3.14.2 | The `{}`-empty / `None`-fault distinction exists on both backends now; nothing has consumed it. Audit what each site does next with "empty" — `fanout` and `callback_processor` act on it |
| [`://` prefix branch in `_matches_pattern`](permission-uri-prefix-branch.md) | Closes the last unnormalised `startswith` on a client-controlled resource URI (`notes://` matches `notes://../../security/key`), and the `*/list` MCP filters that still fail open | Custom configs only — every shipped type writes `notes://*`. Decide with the `uri_pattern` metadata question |
| [`_glob_to_regex` backslash escapes; NFC/NFD](glob-backslash-escape.md) | Lets a rule name an identifier containing a literal `*` or `?`, which today cannot be written; records that Unicode-normalised spellings of one name are distinct permission targets | Nothing shipped needs either; a consumer with such names would. Changes what an existing backslash pattern matches, so not a patch |
| [MCP batches are declined; 2025-03-26 requires receiving them](mcp-batch-receive.md) | Full conformance with a protocol revision the server still advertises and assumes for header-less requests | No client we serve is known to batch. Choose between implementing receive (status semantics for mixed results are open) and dropping 2025-03-26 from the supported versions, which is a compatibility decision |
| [Unbounded caches on the permission path](permission-path-unbounded-caches.md) | Bounds four per-process dicts (`trust_permissions`, `peer_profile`, `peer_permissions`, `peer_capabilities`) that grow with distinct trust pairs seen, not with config | Cheap holding fix (bound + LRU) until the MCP cache lifecycle register's cross-process design replaces them |

## 3. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| Item | Waiting on |
| --- | --- |
| [Remove the legacy property GSI machinery](legacy-property-gsi-removal.md) | The **next major version bump**. Five removals, enumerated. Note the sequencing constraint: release notes telling legacy-GSI holdouts to migrate must ship in a release that **still contains the backfill script**, so the note is written before the removal, not alongside it. Also absorbs the `use_lookup_table` three-sources-of-truth wart |
| [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | Also the **next major version bump**. Raises or removes the 1 MB per-partition DynamoDB Query ceiling — the consumer's largest list measured at 964 KB in one page, 94% of the limit — and is the only place the remaining out-of-band payload problem and the attribute composite-key collision can be fixed. Sequence after the legacy-GSI removal so the scheme is designed against the final lookup-table-only shape |
| [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is, and the library now fires that criterion itself. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision |
| [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | Resources this environment does not have: a Context7 account, a real OAuth2 provider and MCP client, a throwaway consumer repo |
| [`demo.actingweb.io` OAuth login unverified](demo-live-oauth-login-unverified.md) | A browser and a Google account. Tick the box in the demo consolidation plan's Phase 5 and delete the file when done |

## 4. Registers — deferred items, not schedulable work

Each holds items that were deliberately cut, with the rationale and the trigger
that would justify pulling one forward. **A trigger that hasn't fired means the
register is working**, not that it's stale. Their value is stopping decisions
being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | Seven items deferred from the v3.13 scalability plan — the remaining unbatched delete loops, the `consistent_read` audit's ~26 surviving sites, `SubscriptionDiff` seqnr ordering, unpaginated `DbActorList.fetch`, import-time table-name freezing, GSI-based secret uniqueness, lookup-table write amplification |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | Cross-process invalidation (the large one), trust-freshness policy, `_mcp_client_info_cache`'s client-supplied key, the surviving substring peer-id match on the deletion path, registration not hard-failing on trust-creation failure, module-global cache keys assuming one app per interpreter, and a sync/async `resources/read` formatting divergence |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. One thing worth
repeating because it is easy to get wrong here:

- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
