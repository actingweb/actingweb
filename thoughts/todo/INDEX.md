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
| [Dynamic client registrations and their trust rows never expire](dcr-registrations-and-client-trust-rows-never-expire.md) | Stops the `mcp_clients` bucket, the global client index and the system-actor trust rows growing by one per connect forever, and removes a full trust-list walk from every registration | Found 2026-09-21 by the consumer's connector audit; verified in code 2026-09-25. Needs a retention decision (never-authorized registrations can expire early; ones with live tokens cannot) before the sweep is designed |
| [MCP OAuth connector conformance follow-ups](mcp-oauth-connector-conformance-followups.md) | Nine audit items with no live failure behind them: loopback redirect URIs, RFC 8707 audience, CIMD, `openid-configuration`, the protected-resource `resources` flag, `resources/templates/list`, the never-sent `listChanged`, shared-registration name flips, a post-auth hook for app middleware | Same audit, verified 2026-09-25. Each is small; none is blocking a client today. Pick the ones a connector-directory submission requires when that is next attempted. CIMD moved up: claude.ai's connector dialog now recommends it (DCR fallback works, seen on rc1 2026-09-28) |
| [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md) | Closes the last documented way a v2 list operation can silently duplicate (`append`) or double-remove (`pop`) under sustained backend trouble alone, no concurrent writer needed | Traced, not reproduced, during the 2026-09-14 touch-fault triage — a different mechanism from that report (ambiguity inside one primitive, not between two writes), so it stayed a separate todo. Needs reproduction or a decision to fix from the trace, plus whether PostgreSQL has an equivalent |
| [`set_description()`/`set_explanation()` still create the meta row unconditionally](meta-row-create-unconditional-for-description-writers.md) | Makes every v2 meta-row creation conditional, one creation path — closes the narrower last-writer-wins race the 2026-09-14 first-mutation fix left on `count_hint` (never on the description itself, and self-repaired by the next rank-counting mutation) | Found while implementing that fix; explicitly out of scope for the 3.14.7 patch. Needs a decision on whether the shared `_save_metadata()` creation branch (also used by v1's `create_if_absent=False` writers and `clear()`'s replace) routes through `_v2_create_meta_row()` or grows its own conditional create |
| [DynamoDB accepts a non-bool subscription `callback`](benchmark-subscription-tests-pass-url-to-boolean-callback.md) | The two backends agree on what `DbSubscription.create(callback=...)` accepts: PostgreSQL refuses a string, DynamoDB accepts one silently | Found 2026-09-14. Decide: reject or coerce on DynamoDB; library callers always pass a bool, so low priority |
| [Creator uniqueness is not enforced, only logged](creator-uniqueness-not-enforced.md) | Closes the check-then-create race that can duplicate an actor's creator (a WARNING now surfaces existing duplicates; nothing yet stops new ones) | Needs a backfill decision for existing duplicates before a unique index can be added — a unique index cannot be created over data that already violates it |
| [GitHub's `/user/emails` API is called twice on the identifier-extraction failure path](github-emails-api-called-twice.md) | Removes a ≈45s worst-case stall (past API Gateway's 30s Lambda integration timeout) on the `require_email`-and-no-public-email path | Two fix shapes sketched, not evaluated against each other; low-probability edge case, no reported incident |
| [SPA logout can race a refresh rotation](spa-logout-refresh-rotation-race.md) | Closes the millisecond window in which a refresh that consumed its token just before the logout sweep mints a live access and refresh pair after it, so logout answers success for a chain that still works | Found by the 3.15.1 verification, rated Medium by the owner; same shape as the theft response, needs the client or a thief to refresh at the moment of logout. Two fix shapes sketched, not evaluated |
| [Logout with an MCP token and an SPA refresh cookie revokes only the MCP chain](logout-mcp-token-with-spa-refresh-cookie.md) | Closes a mixed request (MCP Bearer plus an SPA `refresh_token` cookie or body field) that answers 200 and clears the SPA cookies while the SPA chain stays live | Found by the 3.15.1 code review, rated Low; a browser that is both an MCP client and an SPA at once is unusual. Two fix shapes sketched, not evaluated |
| [MCP token manager hygiene follow-ups](mcp-token-manager-hygiene-followups.md) | Two Lows from the PR #148 review: `summarize_payload` runs before the DEBUG level check on a performance-sensitive logger, and a pointer to the plan that unifies the two rotation ladders | Filed 2026-09-27 so the hardening PR could merge on the agreed exit rule; each is a few lines, none consumer-visible |
| [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Merging the two metadata paths **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent`, so it is not an independent decision. Decide it with the structuredContent research (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove | Two designs died under adversarial review and the file carries the constraints they established — chiefly that `fetch_all_including_lists` is a paginated Query, not a snapshot. Do not propose a third without reading them. Reachability is low (`compact()` is an operator action) and the current failure is loud, which is what makes the wait defensible |
| [v2 list access follow-ups](v2-list-access-verification-followups.md) | Two integration tests a plan named and nobody wrote (end-to-end peer-replica diffs, interleaved append), plus the www HTML UI's missing contention mapping | Nothing blocks; waits for the next time someone is in the subscription-delivery or www code |
| [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Test-infrastructure reliability only, not correctness. Nothing has been instrumented for it |
| [`auth.py` per-request `Config()`](auth-per-request-config.md) | Stops the public `check_and_verify_auth()` helpers rebuilding every config-bound singleton — evaluator, registries, caches — and re-running `logging.basicConfig()` on each request that omits a config; the largest per-request cost next to the permission path. Also carries the `redirect_uri`-from-default-`fqdn` footgun | The library's own integrations always pass a config, so the exposure is direct callers; the fix is a signature change and wants a minor |
| [`get_bucket(...)` sites that read a fault as empty](db-layer-get-bucket-or-empty.md) | Six sites that fold a bucket-read fault into "empty", the same shape that emptied a list in 3.14.2; the sixth (`list_clients_for_actor`) is one layer up and has `Attributes.loaded` available since 3.15 | The `{}`-empty / `None`-fault distinction exists on both backends now; only the MCP token paths consume it (`_snapshot_bucket` and the expired-token sweep). Audit what each site does next with "empty" — `fanout` and `callback_processor` act on it |
| [`://` prefix branch in `_matches_pattern`](permission-uri-prefix-branch.md) | Closes the last unnormalised `startswith` on a client-controlled resource URI (`notes://` matches `notes://../../security/key`), and the `*/list` MCP filters that still fail open | Custom configs only — every shipped type writes `notes://*`. Decide with the `uri_pattern` metadata question |
| [`_glob_to_regex` backslash escapes; NFC/NFD](glob-backslash-escape.md) | Lets a rule name an identifier containing a literal `*` or `?`, which today cannot be written; records that Unicode-normalised spellings of one name are distinct permission targets | Nothing shipped needs either; a consumer with such names would. Changes what an existing backslash pattern matches, so not a patch |
| [MCP batches are declined; 2025-03-26 requires receiving them](mcp-batch-receive.md) | Full conformance with a protocol revision the server still advertises and assumes for header-less requests | No client we serve is known to batch. Choose between implementing receive (status semantics for mixed results are open) and dropping 2025-03-26 from the supported versions, which is a compatibility decision |
| [`POST /mcp` treats non-JSON as `{}`](mcp-post-parse-error.md) | A malformed body is reported as `-32700 Parse error` instead of a `401` or `Method not found: None` | Decide whether the parse error may pre-empt the `401` discovery challenge for unauthenticated callers, and what an empty body is |
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
