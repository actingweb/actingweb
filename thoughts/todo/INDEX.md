# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Last full re-rank:
2026-11-01.** Rows, files and the todos the 3.16 roll-up touched were
re-checked on 2026-11-05, after it merged; the order still stands. Rows marked
**Planned for 3.16** have an owner-chosen approach and a proposed plan
(2026-11-06); the order they are taken in is the first section below.

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

## Planned for 3.16: order, dependencies and gates

Six plans, all `status: proposed` (2026-11-06). **This section is the one
copy of the order, of what depends on what between the plans, and of the
gates between them.** Each plan keeps a pointer here and its own "This plan"
paragraph, which says what that plan uses from the others and wins on that
detail. One PR per plan, one commit per phase; a plan starts when the one
before it has merged and its gates are met, because the checks allow one
test run at a time. The 3.16 tag stays held until all six have merged.
Proposed is not approved: four of the six (`peer-authorisation-fixes`,
`subscription-wire-baseline`, `attribute-list-v2-port`, `spec-1-5`) say in
their "Readiness" paragraph that they need another draft first, the first
two after a research pass.

| Order | Plan | Todo it closes | Needs first |
| --- | --- | --- | --- |
| Before 0 | [Emm's suite against `master`](emm-suite-against-master.md): the consumer's tests run on the library as it is, so what 3.16 already changes for Emm is known before more lands | Itself | A worktree of this repo, a worktree of Emm on a 3.16 adoption branch with its own virtualenv |
| 0 | [`peer-authorisation-fixes`](../plans/2026-11-06-peer-authorisation-fixes.md): unauthenticated callers refused on `/callbacks`, a callback's URL fetched only from the peer, a peer limited to its own permissions and subscriptions; first, the fourteen legitimate flows the fix must leave unchanged, recorded on the harness the baseline spike builds | None; found by the reviews of the other plans and confirmed by a run | Nothing. Security first |
| 1 | [`subscription-wire-baseline`](../plans/2026-11-06-subscription-wire-baseline.md): what a publisher sends and a subscriber holds today, recorded per flow, so every later change to it is a file diff; the existing subscription tests made to assert one outcome | None; found by the review of the other plans | Its spike, before plan 0 is redrafted; plan 0 merged, which lands the harness |
| 2 | [`subs-list-cache-lifetime`](../plans/2026-11-06-subs-list-cache-lifetime.md): per-request actors on the MCP path, a subscription list that caches empty | [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Plan 0, for the view filter its new accessor inherits; plan 1 |
| 3 | [`attribute-list-v2-port`](../plans/2026-11-06-attribute-list-v2-port.md): replica lists on the rank format, list diffs from REST and web-UI edits, diffs filtered before they are stored | [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Plan 1; ahead of plan 4 because the specification plan waits on it |
| 4 | [`email-as-creator-at-write-time`](../plans/2026-11-06-email-as-creator-at-write-time.md): one read per actor load under the email flag, the vouched rename as one transaction | [The vouched SDK rename](vouched-rename-one-transaction.md) | Plan 2 (it removes a keyword that plan adds) |
| 5 | [`spec-1-5`](../plans/2026-11-06-spec-1-5.md): specification 1.5 and a library that conforms to it, concurrent callback delivery, `FanOutManager` removed | None; it files `outbound-callback-backpressure.md` | Plans 0, 1 and 3 |

Todos these plans edit without closing: [MCP cache lifecycle](mcp-cache-lifecycle-and-revocation.md)
and [DynamoDB known-next](dynamodb-known-next.md) (plan 2);
[whole-list rewrite atomicity](whole-list-rewrite-atomicity.md),
[subscriber fault hardening](subscription-subscriber-fault-hardening.md) and
[the key-prefix scheme](prop-list-key-prefix-scheme.md) (plan 3);
[subscriber fault hardening](subscription-subscriber-fault-hardening.md) again
(plan 5).

### Dependencies between the plans

| Later plan | Needs | Kind | Why |
| --- | --- | --- | --- |
| `spec-1-5` | `attribute-list-v2-port` | Hard | It documents the list diffs that plan creates and edits the same functions after it |
| `email-as-creator-at-write-time` | `subs-list-cache-lifetime` | Hard as written | It removes the `rewrite_email` keyword that plan adds. Open: whether that plan needs the keyword at all |
| `subs-list-cache-lifetime`, `attribute-list-v2-port`, `spec-1-5` | `subscription-wire-baseline` | Hard, for regression safety | Their phases name the recordings they re-record and the ones that must stay identical |
| `subs-list-cache-lifetime` | `peer-authorisation-fixes` | Soft | One verification case (the accessor through a peer view) needs that plan's filter |
| `attribute-list-v2-port` | `peer-authorisation-fixes` | Soft | No phase uses anything that plan adds |
| `email-as-creator-at-write-time` | `subscription-wire-baseline` | Soft | It re-records nothing; the recordings confirm it changed nothing between two actors |

`attribute-list-v2-port` and `email-as-creator-at-write-time` need nothing
from each other and could swap places. Three plans in a row
(`subs-list-cache-lifetime`, `attribute-list-v2-port`, `spec-1-5`) edit the
same publisher and receiver code (`register_diffs`, `callback_subscription`,
`apply_callback_data`, `handlers/subscription.py`); a fault one introduces
and the next exposes is the case the gates below are for.

**The wire harness is built by the baseline plan's spike** (owner,
2026-11-07), not designed on paper in the security plan: the spike builds
the recorder and the two consumer-shaped apps, records a handful of rows on
both backends, repeats the runs, and writes a research note. The security
plan's Phase 0 then lands that harness as its test-only first commit and
records the fourteen flows its fix must leave unchanged; the baseline plan
stays its own PR after the fix. Both plans are redrafted after the spike.

**Before the first PR, in this order:** the Emm run on `master`
(`emm-suite-against-master.md`); the wire spike; the security plan's
research pass (trust replacement, the access table with application rows,
what forged state survives on each backend); then `/update_plan` on the
baseline plan and on the security plan. The runs are sequential because
they share Docker and the local ports.

### Gates

1. **Before plan 0 starts:** [Emm's suite on `master`](emm-suite-against-master.md)
   has run and every failure is triaged. What is left is the baseline for
   the runs below.
2. **Before the PR opens, for each plan that changes library code:** Emm's
   suite on that plan's branch shows no failure the baseline did not have;
   the result is in the plan's verification document. Each such plan's last
   phase carries the checkbox; the baseline plan changes only tests and has
   none.
3. **Before any plan re-records a wire recording:** that recording has been
   shown byte-identical over repeated runs on both backends. One that is not
   cannot tell a regression from noise and stays out of the regression set.
4. **Before plan 2 starts:** the recordings shaped like Emm's use exist,
   the import flow (one subtarget suspended and resumed around list writes)
   included. Whether the remaining rows form a second tier is the baseline
   plan's open decision.
5. **In every commit of plans 2 to 5:** the only changed recordings are the
   ones the phase names; any other is a regression to explain before the
   next phase.

## 1. High leverage

Bigger, designed, and each buys more than it costs. Both now have an
owner-chosen approach and a proposed plan (2026-11-06).

| Item | Impact of doing it | What it needs first |
| --- | --- | --- |
| [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers, and `4 x peers` per page load on a consumer endpoint measured at p50 689 ms | **Planned for 3.16**: `thoughts/plans/2026-11-06-subs-list-cache-lifetime.md` (proposed). The cache-lifetime question is settled there: the MCP path builds its actor per request, and then the guard |
| [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the v2 format, and every peer replica's `insert`/`remove` diff is applied through it (`RemotePeerStore`), so it is on the subscription path, not a side class | **Planned for 3.16**: `thoughts/plans/2026-11-06-attribute-list-v2-port.md` (proposed). Sequenced before whole-list rewrite atomicity, with the documented window |

## 2. Real, not urgent

| Item | Impact of doing it | Why now |
| --- | --- | --- |
| [Deleting a client leaves other local actors' connections](client-deletion-leaves-other-actors-connections.md) | Ends the up-to-an-hour of access other actors keep after an SDK client's owner deletes it, and the inert rows it leaves | Found by the 2026-11-04 client-deletion audit (D2); server-local only. Needs a choice between a client check at token validation and a client-to-actors index |
| [Dynamic client registrations and their trust rows never expire](dcr-registrations-and-client-trust-rows-never-expire.md) | Stops the `mcp_clients` bucket, the global client index and the system-actor trust rows growing by one per connect forever (the per-registration trust-list walk is gone in 3.16; the retention design is the whole item) | Found 2026-09-21 by the consumer's connector audit; verified in code 2026-09-25. Needs a retention decision (never-authorized registrations can expire early; ones with live tokens cannot) before the sweep is designed |
| [MCP OAuth connector conformance follow-ups](mcp-oauth-connector-conformance-followups.md) | Nine audit items with no live failure behind them: loopback redirect URIs, RFC 8707 audience, CIMD, `openid-configuration`, the protected-resource `resources` flag, `resources/templates/list`, the never-sent `listChanged`, shared-registration name flips, a post-auth hook for app middleware | Same audit, verified 2026-09-25. Each is small; none is blocking a client today. Pick the ones a connector-directory submission requires when that is next attempted. CIMD moved up: claude.ai's connector dialog now recommends it (DCR fallback works, seen on rc1 2026-09-28) |
| [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md) | Closes the last documented way an unkeyed v2 list operation can silently duplicate (`append`, `extend`, `insert`) or double-remove (`pop`) under sustained backend trouble alone, no concurrent writer needed; keyed `append_once` and spanned heads already read their own write back | Traced, not reproduced, during the 2026-09-14 touch-fault triage; a strict `xfail` test pins the `append` duplicate. Needs a way to recognise an unkeyed plain write (its bytes are not unique to the call), plus whether PostgreSQL has an equivalent |
| [`set_description()`/`set_explanation()` still create the meta row unconditionally](meta-row-create-unconditional-for-description-writers.md) | Makes every v2 meta-row creation conditional, one creation path — closes the narrower last-writer-wins race the 2026-09-14 first-mutation fix left on `count_hint` (never on the description itself, and self-repaired by the next rank-counting mutation) | Found while implementing that fix; explicitly out of scope for the 3.14.7 patch. Needs a decision on whether the shared `_save_metadata()` creation branch (also used by v1's `create_if_absent=False` writers and `clear()`'s replace) routes through `_v2_create_meta_row()` or grows its own conditional create |
| [Subscription subscriber: recover cleanly from a store fault](subscription-subscriber-fault-hardening.md) | A subscriber that faulted mid-callback re-applies only what it has not applied, records the callbacks that finished, and a quiet subscription recovers without waiting for its next change | Filed 2026-10-29 when 3.16 made the publisher side spec-conformant (plan entry 32). Beyond the spec's minimum; a re-applied `append` can use 3.16's `ListProperty.append_once()` once each diff carries a stable key |
| [The vouched SDK rename is several writes, not one transaction](vouched-rename-one-transaction.md) | Concurrent renames of one actor, a fault past the commit point and a provider-id rename racing a sign-in all end coherently today, but not atomically; one cross-table write would make the rename all-or-nothing | **Planned for 3.16**: `thoughts/plans/2026-11-06-email-as-creator-at-write-time.md` (proposed), whose first phase is the one-transaction rename |
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
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | Cross-process invalidation (the large one), trust-freshness policy, `_mcp_client_info_cache`'s client-supplied key, registration not hard-failing on trust-creation failure, module-global cache keys assuming one app per interpreter, and the trust permission cache having no TTL (sections 1-3, 5, 6 and 8; 4 and 7 were closed by the 3.16 roll-up) |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. One thing worth
repeating because it is easy to get wrong here:

- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
