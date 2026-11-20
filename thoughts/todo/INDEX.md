# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Last full re-rank:
2026-11-01.** Rows, files and the todos the 3.16 roll-up touched were
re-checked on 2026-11-05, after it merged; the order still stands. Every row
was checked against its file, and the todos `spec-1-5` touched against the
code, on 2026-11-16 after #178 merged. The plans that made up the release
after 3.15.1 (4.0.0) and their order were listed here until the last of
them, `3-16-release-validation`, merged; that history is in the plans.

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

Bigger, designed, and each buys more than it costs. Each has an
owner-chosen approach and a proposed plan (2026-11-06).

| Item | Impact of doing it | What it needs first |
| --- | --- | --- |

## 2. Real, not urgent

| Item | Impact of doing it | Why now |
| --- | --- | --- |
| [The 4.0.0 release candidate against real consumers](rc-pass-against-real-consumers.md) | The published rc proven where it runs: the demo deployed on it and a consumer's suite pinned to it (the Agent Skill and the PostgreSQL pair are done) | `v4.0.0rc1` is on TestPyPI (2026-11-20); the demo's pin is a PR waiting on the owner's operator steps. First before the stable tag |
| [A bounded read of a v2 list](bounded-list-read.md) | A tail or page of a long list costs its own rows, not the whole list's range | First after 4.0.0rc1 (owner, 2026-11-19); a consumer's comments feature needs it. Open: a PostgreSQL index revision, the cursor contract across requests, four wrapper layers |
| [`delete_attr_if_data_equals` on a dict value](attribute-conditional-delete-on-dict-values.md) | A conditional delete of a dict attribute matches whatever the key order | A consumer's comments feature; unverified, a test first |
| [List items: an append that creates nothing, a TTL, retained generations](list-items-conditional-create-ttl-and-retained-bodies.md) | Comments and versioning on lists without application workarounds | Additive; each needs a design (creation path, body-row expiry, a locating field) |
| [Vouching and adoption follow-ups](marking-and-adoption-followups.md) | Unmarked actors with no sign-in left alone, peers told of a clean, the bridge's vouch bound to its address | Left by the 2026-11-19 plan; each needs a definition or a protocol answer first |
| [Deleting a client leaves other local actors' connections](client-deletion-leaves-other-actors-connections.md) | Ends the up-to-an-hour of access other actors keep after an SDK client's owner deletes it, and the inert rows it leaves | Found by the 2026-11-04 client-deletion audit (D2); server-local only. Needs a choice between a client check at token validation and a client-to-actors index |
| [Dynamic client registrations and their trust rows never expire](dcr-registrations-and-client-trust-rows-never-expire.md) | Stops the `mcp_clients` bucket, the global client index and the system-actor trust rows growing by one per connect forever (the per-registration trust-list walk is gone in 4.0; the retention design is the whole item) | Found 2026-09-21 by the consumer's connector audit; verified in code 2026-09-25. Needs a retention decision (never-authorized registrations can expire early; ones with live tokens cannot) before the sweep is designed |
| [MCP OAuth connector conformance follow-ups](mcp-oauth-connector-conformance-followups.md) | Audit items with no live failure behind them: loopback redirect URIs, RFC 8707 audience, CIMD, a redirect (not 400) for a PKCE refusal, the strict `resources/list` split, a post-auth hook for app middleware (`openid-configuration`, `resources/templates/list`, the name flips and PKCE for every client closed by `2026-11-19-emm-4-0-adoption-findings`) | Same audit, verified 2026-09-25. Each is small; none is blocking a client today. Pick the ones a connector-directory submission requires when that is next attempted. CIMD moved up: claude.ai's connector dialog now recommends it (DCR fallback works, seen on rc1 2026-09-28) |
| [A conditional write retried by the SDK can report False for a write that landed](conditional-write-ambiguous-after-sdk-retry.md) | Closes the last documented way an unkeyed v2 list operation can silently duplicate (`append`, `extend`, `insert`) or double-remove (`pop`) under sustained backend trouble alone, no concurrent writer needed; keyed `append_once` and spanned heads already read their own write back | Traced, not reproduced, during the 2026-09-14 touch-fault triage; a strict `xfail` test pins the `append` duplicate. Needs a way to recognise an unkeyed plain write (its bytes are not unique to the call), plus whether PostgreSQL has an equivalent |
| [`set_description()`/`set_explanation()` still create the meta row unconditionally](meta-row-create-unconditional-for-description-writers.md) | Makes every v2 meta-row creation conditional, one creation path — closes the narrower last-writer-wins race the 2026-09-14 first-mutation fix left on `count_hint` (never on the description itself, and self-repaired by the next rank-counting mutation) | Found while implementing that fix; explicitly out of scope for the 3.14.7 patch. Needs a decision on whether the shared `_save_metadata()` creation branch (also used by v1's `create_if_absent=False` writers and `clear()`'s replace) routes through `_v2_create_meta_row()` or grows its own conditional create |
| [Old-layout attribute lists: remove the reader](attribute-list-old-layout-removal.md) | One list layout to read and test, not two | Filed 2026-11-13 by `attribute-list-v2-port`: 4.0 reads the pre-4.0 attribute list layout in place and converts on the first change; the reader and converter go once a release has been live long enough that no deployment holds old-layout lists (`actingweb-verify-property-lists --attributes` reports them) |
| [Subscribers after specification 1.5: the previous value is read apart from the write](subscriber-hooks-and-resource-diffs-after-1-5.md) | A resource subscriber is told its key went even when another writer changed the parent between the read and the write | Filed 2026-11-15 by the codex review of `spec-1-5` Phase 3; the same race exists for ordinary diffs. The file's other two items (hooks on polled rebuilds, the SDK's resource notification) closed with `3-16-pre-validation-fixes` Phase 2 |
| [Outbound callbacks: back-off, a per-peer breaker, payload limits](outbound-callback-backpressure.md) | A publisher stops spending the timeouts on a subscriber that keeps failing, backs off on 429 and 503, and bounds sends per process | Filed 2026-11-15 by `spec-1-5` Phase 4 (concurrent delivery, `FanOutManager` removed); optional in specification 1.5 |
| [Subscription subscriber: recover cleanly from a store fault](subscription-subscriber-fault-hardening.md) | A subscriber that faulted mid-callback re-applies only what it has not applied, records the callbacks that finished, and a quiet subscription recovers without waiting for its next change | Filed 2026-10-29 when 4.0 made the publisher side spec-conformant (plan entry 32). Beyond the spec's minimum; a re-applied `append` can use 4.0's `ListProperty.append_once()` once each diff carries a stable key |
| [Promote `chain_id` to a top-level attribute with a GSI on DynamoDB](dynamodb-chain-id-gsi.md) | Makes SPA logout and revoke a query by chain instead of a scan of the two shared token buckets, so their cost stops growing with the number of live sessions | Raised by the PR #153 review; 3.15.1 accepted the scan (42 rows, about 3 RCU per call) with a WARNING at 1,000 rows per bucket. Trigger: that WARNING firing, or a partition projected past about 2,000 rows |
| [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Merging the two metadata paths **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent`, so it is not an independent decision. Decide it with the structuredContent research (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove | Two designs died under adversarial review and the file carries the constraints they established — chiefly that `fetch_all_including_lists` is a paginated Query, not a snapshot. Do not propose a third without reading them. Reachability is low (`compact()` is an operator action) and the current failure is loud, which is what makes the wait defensible |
| [v2 list access follow-ups](v2-list-access-verification-followups.md) | The bulk response counts for duplicate deletes of a batch-created index credit each request entry | Noise-level; revisit only if a consumer reads these counts strictly |
| [What was left of the root `TODO.md`](root-todo-leftovers.md) | A display name for a trust apart from its type in the web UI; a client's token revocation that does not read all of the actor's tokens | Filed 2026-11-17 when the root `TODO.md` was checked against the tree and deleted. Both low; neither has a report behind it |
| [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Test-infrastructure reliability only, not correctness. Nothing has been instrumented for it |
| [NFC and NFD spellings of one name are distinct keys](unicode-normalisation-of-names.md) | Records that Unicode normalisation of names is a separate question from the (landed) glob escapes: a rule that visibly covers a namespace does not cover a byte-different spelling | A normalisation at the permission choke points and the name write path, plus a migration of stored names |
| [MCP batches are declined; 2025-03-26 requires receiving them](mcp-batch-receive.md) | Full conformance with a protocol revision the server still advertises and assumes for header-less requests | No client we serve is known to batch. Choose between implementing receive (status semantics for mixed results are open) and dropping 2025-03-26 from the supported versions, which is a compatibility decision |
| [`/sessions` has no library support](sessions-endpoint-and-advertised-options.md) | Gives applications a hook to implement `/sessions` like `/actions` and `/methods`; the advertised-tag audit landed in 4.0 | A session-model decision (callback URI vs mirrored URL, WebSocket, MCP mapping) |
| [`actingweb-verify-orphans` does not sweep subscriptions, diffs or suspensions](verify-orphans-subscription-tables.md) | An operator can find and remove subscription, diff and suspension rows left without an actor (the deletion race `subs-list-cache-lifetime` narrows but does not close); today nothing reports them | The three tables added to the sweep on both backends; a decision on whether a subscription without a trust counts |

## 3. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| Item | Waiting on |
| --- | --- |
| [A start that serves 503 while its check repeats](startup-check-served-503-mode.md) | **A consumer's report** of what a failed function initialisation does on its platform; 4.0 retries the check three times and then refuses |
| [A public fault-injection helper for consumers' tests](consumer-test-fault-injection.md) | **Its own API design**; nothing a consumer patches moves between 4.0.0rc1 and final |
| [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | **A measured trigger, not a version** (owner, 2026-11-18: left out of 4.0.0; planned when an actor needs more than two Query pages for its plain properties and list heads, or a consumer needs a per-field out-of-band payload). Raises or removes the 1 MB per-partition DynamoDB Query ceiling — the consumer's largest list measured at 964 KB in one page, 94% of the limit — and is the only place the remaining out-of-band payload problem and the attribute composite-key collision can be fixed. The legacy GSI is gone (4.0), so the scheme is designed against the lookup-table-only shape |
| [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is, and the library now fires that criterion itself. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision |
| [Drop Python 3.11 after its end of life](drop-python-3-11-after-eol.md) | **October 2027**, CPython 3.11's end of life (owner's policy, 2026-11-04: support what upstream maintains). Then the first minor raises the minimum to 3.12, renaming the required CI contexts in the same change |
| [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | **The stable 4.0.0 tag and its docs on Read the Docs**: only the Context7 submission is left (the MCP client and the Agent Skill checks were done by `3-16-release-validation`, 2026-11-18) |

## 4. Registers — deferred items, not schedulable work

Each holds items that were deliberately cut, with the rationale and the trigger
that would justify pulling one forward. **A trigger that hasn't fired means the
register is working**, not that it's stale. Their value is stopping decisions
being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | Judged for 4.0.0 and left out, every item (owner, 2026-11-18). Six items deferred from the v3.13 scalability plan — the remaining unbatched delete loops, the `consistent_read` audit's ~36 surviving sites, `SubscriptionDiff` seqnr ordering, import-time table-name freezing, GSI-based secret uniqueness, lookup-table write amplification |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | Cross-process invalidation (the large one), trust-freshness policy, `_mcp_client_info_cache`'s client-supplied key, and module-global cache keys assuming one app per interpreter (sections 1-3 and 6; 4 and 7 were closed by the 4.0 roll-up, 5 and 8 by `3-16-pre-rc1-fixes`, which bounds the override cache to 300 seconds) |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. One thing worth
repeating because it is easy to get wrong here:

- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
