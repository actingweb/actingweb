# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Last full re-rank:
2026-11-01.** Rows marked **Planned for 3.16** have an owner-chosen approach and a
plan (2026-11-02); none is left.

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
| [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the v2 format, and every peer replica's `insert`/`remove` diff is applied through it (`RemotePeerStore`), so it is on the subscription path, not a side class | The chosen approach is the full v2 port, which is mostly a port now that the fractional-rank format and its primitives are proven. Sequencing is unresolved: after [whole-list rewrite atomicity](whole-list-rewrite-atomicity.md), which has two dead designs and no third, or accept the same documented window `ListProperty` shipped with and fix both classes later. Owner's call, not made |

## 2. Real, not urgent

| Item | Impact of doing it | Why now |
| --- | --- | --- |
| [Deleting a client leaves other local actors' connections](client-deletion-leaves-other-actors-connections.md) | Ends the up-to-an-hour of access other actors keep after an SDK client's owner deletes it, and the inert rows it leaves | Found by the 2026-11-04 client-deletion audit (D2); server-local only. Needs a choice between a client check at token validation and a client-to-actors index |
| [Dynamic client registrations and their trust rows never expire](dcr-registrations-and-client-trust-rows-never-expire.md) | Stops the `mcp_clients` bucket, the global client index and the system-actor trust rows growing by one per connect forever (the per-registration trust-list walk is gone in 3.16; the retention design is the whole item) | Found 2026-09-21 by the consumer's connector audit; verified in code 2026-09-25. Needs a retention decision (never-authorized registrations can expire early; ones with live tokens cannot) before the sweep is designed |
| [MCP OAuth connector conformance follow-ups](mcp-oauth-connector-conformance-followups.md) | Nine audit items with no live failure behind them: loopback redirect URIs, RFC 8707 audience, CIMD, `openid-configuration`, the protected-resource `resources` flag, `resources/templates/list`, the never-sent `listChanged`, shared-registration name flips, a post-auth hook for app middleware | Same audit, verified 2026-09-25. Each is small; none is blocking a client today. Pick the ones a connector-directory submission requires when that is next attempted. CIMD moved up: claude.ai's connector dialog now recommends it (DCR fallback works, seen on rc1 2026-09-28) |
| [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md) | Closes the last documented way an unkeyed v2 list operation can silently duplicate (`append`, `extend`, `insert`) or double-remove (`pop`) under sustained backend trouble alone, no concurrent writer needed; keyed `append_once` and spanned heads already read their own write back | Traced, not reproduced, during the 2026-09-14 touch-fault triage; a strict `xfail` test pins the `append` duplicate. Needs a way to recognise an unkeyed plain write (its bytes are not unique to the call), plus whether PostgreSQL has an equivalent |
| [`set_description()`/`set_explanation()` still create the meta row unconditionally](meta-row-create-unconditional-for-description-writers.md) | Makes every v2 meta-row creation conditional, one creation path — closes the narrower last-writer-wins race the 2026-09-14 first-mutation fix left on `count_hint` (never on the description itself, and self-repaired by the next rank-counting mutation) | Found while implementing that fix; explicitly out of scope for the 3.14.7 patch. Needs a decision on whether the shared `_save_metadata()` creation branch (also used by v1's `create_if_absent=False` writers and `clear()`'s replace) routes through `_v2_create_meta_row()` or grows its own conditional create |
| [Subscription subscriber: recover cleanly from a store fault](subscription-subscriber-fault-hardening.md) | A subscriber that faulted mid-callback re-applies only what it has not applied, records the callbacks that finished, and a quiet subscription recovers without waiting for its next change | Filed 2026-10-29 when 3.16 made the publisher side spec-conformant (plan entry 32). Beyond the spec's minimum; a re-applied `append` can use 3.16's `ListProperty.append_once()` once each diff carries a stable key |
| [The vouched SDK rename is several writes, not one transaction](vouched-rename-one-transaction.md) | Concurrent renames of one actor, a fault past the commit point and a provider-id rename racing a sign-in all end coherently today, but not atomically; one cross-table write would make the rename all-or-nothing | Recorded 2026-11-02 by the rename audit (owner-decided plan, entries 21-23). Needs a `DbActor` rename that also writes `_internal` attributes, on both backends |
| [Promote `chain_id` to a top-level attribute with a GSI on DynamoDB](dynamodb-chain-id-gsi.md) | Makes SPA logout and revoke a query by chain instead of a scan of the two shared token buckets, so their cost stops growing with the number of live sessions | Raised by the PR #153 review; 3.15.1 accepted the scan (42 rows, about 3 RCU per call) with a WARNING at 1,000 rows per bucket. Trigger: that WARNING firing, or a partition projected past about 2,000 rows |
| [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Merging the two metadata paths **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent`, so it is not an independent decision. Decide it with the structuredContent research (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove | Two designs died under adversarial review and the file carries the constraints they established — chiefly that `fetch_all_including_lists` is a paginated Query, not a snapshot. Do not propose a third without reading them. Reachability is low (`compact()` is an operator action) and the current failure is loud, which is what makes the wait defensible |
| [v2 list access follow-ups](v2-list-access-verification-followups.md) | The bulk response counts for duplicate deletes of a batch-created index credit each request entry | Noise-level; revisit only if a consumer reads these counts strictly |
| [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Test-infrastructure reliability only, not correctness. Nothing has been instrumented for it |
| [NFC and NFD spellings of one name are distinct keys](unicode-normalisation-of-names.md) | Records that Unicode normalisation of names is a separate question from the (landed) glob escapes: a rule that visibly covers a namespace does not cover a byte-different spelling | A normalisation at the permission choke points and the name write path, plus a migration of stored names |
| [MCP batches are declined; 2025-03-26 requires receiving them](mcp-batch-receive.md) | Full conformance with a protocol revision the server still advertises and assumes for header-less requests | No client we serve is known to batch. Choose between implementing receive (status semantics for mixed results are open) and dropping 2025-03-26 from the supported versions, which is a compatibility decision |
| [`/sessions` has no library support](sessions-endpoint-and-advertised-options.md) | Gives applications a hook to implement `/sessions` like `/actions` and `/methods`; the advertised-tag audit landed in 3.16 | A session-model decision (callback URI vs mirrored URL, WebSocket, MCP mapping) |

## 3. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| Item | Waiting on |
| --- | --- |
| [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | Also the **next major version bump**. Raises or removes the 1 MB per-partition DynamoDB Query ceiling — the consumer's largest list measured at 964 KB in one page, 94% of the limit — and is the only place the remaining out-of-band payload problem and the attribute composite-key collision can be fixed. The legacy GSI is gone (3.16), so the scheme is designed against the lookup-table-only shape |
| [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is, and the library now fires that criterion itself. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision |
| [Drop Python 3.11 after its end of life](drop-python-3-11-after-eol.md) | **October 2027**, CPython 3.11's end of life (owner's policy, 2026-11-04: support what upstream maintains). Then the first minor raises the minimum to 3.12, renaming the required CI contexts in the same change |
| [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | Resources this environment does not have: a Context7 account, a real OAuth2 provider and MCP client, a throwaway consumer repo |

## 4. Registers — deferred items, not schedulable work

Each holds items that were deliberately cut, with the rationale and the trigger
that would justify pulling one forward. **A trigger that hasn't fired means the
register is working**, not that it's stale. Their value is stopping decisions
being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | Six items deferred from the v3.13 scalability plan — the remaining unbatched delete loops, the `consistent_read` audit's ~36 surviving sites, `SubscriptionDiff` seqnr ordering, import-time table-name freezing, GSI-based secret uniqueness, lookup-table write amplification |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | Cross-process invalidation (the large one), trust-freshness policy, `_mcp_client_info_cache`'s client-supplied key, registration not hard-failing on trust-creation failure, module-global cache keys assuming one app per interpreter, and the trust permission cache having no TTL (sections 1-3 and 5-7) |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. One thing worth
repeating because it is easy to get wrong here:

- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
