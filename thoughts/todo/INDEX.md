# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Built 2026-08-13**
from a full read of every file. **Reviewed 2026-08-14** — an audit of all
27 plans and 17 research docs for uncovered work, followed by an item-by-item
walkthrough with the owner that gave every row a direction. **Reviewed
2026-08-15** — those directions scoped against the pending 3.13.0 release.
**Last reviewed 2026-08-16** — post-GA pass: v3.13.0 is tagged (#132), so the
release lens is gone and the rows it was holding are live again. See §0.
**Reviewed 2026-08-21** — v3.14.0 is tagged; rows 5, 9, 9c, 14, 15, 16 and 17
closed with it (see `thoughts/plans/2026-08-20-v2-positional-access-cost.md`
for what each shipped as — this file tracks what's left, not what landed).
**Reviewed 2026-09-02** — every open row re-checked against the tree, CI,
the live docs and the consumer repo; all code rows still stand. The demo
consolidation plan was found `active` a week after its last two phases landed
in `actingwebdemo` and is now closed; row 3 reached its deletion date; row 20
lost its first item; row 7 moved up on the 09-01 consumer evidence.
**Released 2026-09-02** — v3.14.4 closed rows 21, 23, 24 and 25 (§1) and
opened rows 27–31 (§3).

**Rows 1, 2, 5, 6, 9, 9c, 11, 14, 15, 16 and 17 are gone, and the numbering
below is deliberately not re-flowed** — too many rows cite each other by
number for renumbering to be a cheap edit. Their files stay where the work
they carried is not finished — a landed row is not the same as a closed
file. §4 (cheap cleanups) went with row 11 and the section numbers are not
re-flowed either, for the same reason: other files cite them.

**This file is a table of contents, not a source of truth.** Each row says what
implementing it buys and why it's worth doing — one line each, deliberately.
Everything else lives in the linked file. If a row and its file disagree, the
file wins.

**Maintaining it:** add a row when you add a todo, delete the row when you delete
the todo. Re-rank when something lands or a trigger fires. Don't copy detail up
here — a duplicated fact is a fact that will drift.

Ordering is by *impact ÷ effort*, not by severity alone: a cheap fix to a
moderate problem outranks an expensive fix to a slightly worse one.

---

## 0. 3.13.0 shipped — 2026-08-16

Tagged `v3.13.0` on 2026-08-16 (#132), straight to GA with no rc7. What that
settles for this list, in one place, so no row has to re-explain it:

- **The GA blocker — former rows 1 and 2 — landed** as
  `thoughts/plans/2026-08-15-property-list-metadata-integrity.md`
  (`status: done`). Not what those rows asked for: three review passes over two
  candidate designs surfaced something worse than the crash windows they
  targeted — a concurrent `append()` writing stale cached metadata back over a
  completed migration, reverting the format flip and **destroying the whole list
  on ordinary traffic**. The plan landed that plus re-run convergence for both
  format-changing rewrites, closed row 1 by an accepted last-writer-wins trade
  (the reasoning now lives in `docs/guides/property-lists.rst`), and deferred
  row 2 — which survives as **row 9b**, whose file records why shipping a third
  design under time pressure was judged worse than shipping the documented
  window.
- **Rows 6 and 11 landed in full, and row 8's cheap half with them**, grouped
  per subsystem rather than as independent branches: #129 (MCP protocol signal,
  row 11), #130 (MCP cache eviction and hook metadata, rows 6 + 8). Row 8's
  actual fix is still open and stays in §3. The `dynamodb-known-next`
  re-verification ran last (#131), against the settled codebase.
- **Row 3's quarantine was lifted and the path instrumented** (#128). The
  postgres matrix has been green on every run since. Row 3 is now *waiting*, not
  *working* — it moved to §5.
- **Row 5's re-measurement was scheduled "at GA, not before".** GA has happened,
  so it is live and sits in §1, behind only row 9c.

**GA-day finding.** Consumer verification of the tag (actingweb_mcp) reproduced
two defects in the property-list tooling, and #132 closed **one** of them:
`--repair` blessing a *reverted* migration as healthy and stranding the only
surviving copy of the data now refuses. The second — a write from a
`ListProperty` held across a migration landing silently in a row shape the
current format never reads — got a WARNING and nothing more at the 3.13.0 tag
point; it was row 9c (dispatch on a cached format), closed in 3.14.0.

## 1. Do next

**Row 22 landed in v3.14.3** — scoped bulk list reads and the
attribute-bucket cache. See
`thoughts/plans/2026-08-29-bulk-list-reads-from-a-consumer.md` (all seven
phases `Complete`) for what each shipped as, and
`thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md` for the
measurements. Three items surfaced while implementing it and were filed as
rows 23, 24 and 25.

**Rows 21, 23, 24 and 25 landed in v3.14.4** — see
`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`.
Row 23 turned out to be a live security fix, not a tidy-up (a `friend` peer
could `POST` a property named `private/\nx` past the exclusion), and the
release is written up as one. Five items the plan's reviews surfaced are filed
below as rows 27–31. This section is otherwise empty.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |

The previous contents of this section — the 3.14.0 verification's findings (see
`thoughts/verifications/2026-08-21-v2-positional-access-cost.md`) — were
actioned same-day on the release branch, including the release-blocking
cross-version wording fix.

## 2. High leverage

Bigger, designed, and each buys more than it costs.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 7 | [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers | **The ordering is the whole item.** The one-line guard fix (`is None`) is unsafe until the cross-request `Actor` cache is dealt with: the falsy guard is exactly what stops a long-lived MCP-cached actor going permanently blind to subscriptions created in another container. The correctness half landed in rc2. **Decided 2026-08-14: take the cache-lifetime question (item 4) rather than the guard** — does `_actor_cache` hold identity/auth only, or do instance caches need a request-boundary reset? The *does it* half was answered on 2026-08-15 (`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`: it holds a live `ActorInterface`) and that was enough to make the revocation-eviction work correct (#130); the *should it* is this row's alone, and the guard stays blocked on it. **Consumer evidence 2026-09-01** widens the severity: this is not only a per-*write* cost. `actingweb_mcp`'s trust-relationships endpoint pays it `4 x peers` per **page load** — **40 subscription fetches for 5 peers**, measured — because an MCP-client-only account has relationships and zero subscriptions, which is exactly the falsy-guard case. Raises the value of item 4; offers no shortcut past it. **Moved up here 2026-09-02**: the consumer has a per-call-site workaround, so this is not urgent, but it is now the highest-value item that is not blocked on a design nobody has |
| 4 | [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the 3.13 fix | Materially cheaper than when filed: the fractional-rank v2 format, its `verify()`/`compact()` primitives and its migration shape now exist and are proven, so option 3 — the only option that closes the corruption class rather than mitigating it — is mostly a port. It waited on **lower blast radius**, not on being safe. **Decided 2026-08-14: option 3, the full v2 port.** Sequence it after row 9b, or the port reproduces that gap in a second class. **Note 2026-09-02:** 9b has two dead designs and no third, so that sequencing makes this row effectively blocked. The alternative is to port with the same documented window `ListProperty` shipped with — strictly better than the shift loop, at the cost of fixing 9b in two classes later. Owner's call; not made yet |

## 3. Real, not urgent

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 8 | [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | The cheap half (option 4, warn at `tools/list`) **landed 2026-08-15**; the asymmetry itself is untouched. What is left is options 2 and 3, and merging **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent` — so it is not an independent decision. **Decide it with the structuredContent research** (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| 9b | [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove — the former row 2's problem, still unsolved | **Deferred from GA on 2026-08-15, and the reason is the value of this file.** Two designs died under adversarial review — a lease-plus-journal whose replay destroys data a plain re-run preserves, and a stage-and-flip whose metadata marker silently permutes lists on the documented `--repair` → `--migrate` sequence. The file carries the constraints they established, chiefly that **`fetch_all_including_lists` is a paginated DynamoDB query, not a snapshot**, which rules out storing "which namespace is live" in the item partition. Do not propose a third design without reading them. Reachability is low and the current failure is loud, which is what makes deferring defensible. **Smaller as of 3.14.0**: the missing-CAS constraint that former row 9c shared this file for is closed — what remains is `compact()`'s crash-atomicity alone |
| 19 | [v2 list access verification follow-ups](v2-list-access-verification-followups.md) | The residue after the 2026-08-21 same-day actioning of the 3.14.0 verification's findings: two plan-named integration tests never written (Phase 10 end-to-end peer-replica, Phase 9B interleaved-append), and the www HTML UI's missing contention mapping | None block anything — the compounding item (the 19-file `ruff format` drift) was closed post-tag with `ruff format --check` added to CI; what's left waits for the next time someone is in the subscription-delivery or www code |
| 10 | [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the remaining instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Not the same defect as row 3 (that one is correctness, this is test infra), but same matrix and same conditions. **Decided 2026-08-14: one instrumentation branch shared with row 3.** That branch ran 2026-08-15 and **collected for row 3 only** — the shared surface was follow-up 1's process-global singletons, and the pool half of it had already been rebuilt in #117, leaving nothing here to instrument. All three follow-ups stay open |
| 27 | [`auth.py` per-request `Config()`](auth-per-request-config.md) | Stops the public `check_and_verify_auth()` helpers rebuilding every config-bound singleton — evaluator, registries, caches — and re-running `logging.basicConfig()` on each request that omits a config; the largest per-request cost next to the permission path. Also carries the `redirect_uri`-from-default-`fqdn` footgun at `config.py:170` | Filed from the 3.14.4 review. The library's own integrations always pass a config, so the exposure is direct callers; the fix is a signature change and wants a minor |
| 28 | [DB-layer `get_bucket(...) or {}`](db-layer-get-bucket-or-empty.md) | Five sites that still fold a bucket-read fault into "empty", the same shape that emptied a list in 3.14.2. 3.14.4 made the distinction available (`{}` empty, `None` fault, both backends) but did not touch the callers | Audit what each site does next with "empty" — `fanout` and `callback_processor` act on it |
| 29 | [`://` prefix branch in `_matches_pattern`](permission-uri-prefix-branch.md) | Closes the last unnormalised `startswith` on a client-controlled resource URI (`notes://` matches `notes://../../security/key`), and the `*/list` MCP filters that still fail open | Custom configs only — every shipped type writes `notes://*`. Decide with the `uri_pattern` metadata question |
| 30 | [`_glob_to_regex` backslash escapes; NFC/NFD](glob-backslash-escape.md) | Lets a rule name an identifier that contains a literal `*` or `?`, which today cannot be written; records that Unicode-normalised spellings of one name are distinct targets — the same failure shape as the newline bypass, not closed by it | Nothing shipped needs either; a consumer with such names would. Changes what an existing backslash pattern matches, so not a patch |
| 31 | [Unbounded caches on the permission path](permission-path-unbounded-caches.md) | Bounds four per-process dicts (`trust_permissions`, `peer_profile`, `peer_permissions`, `peer_capabilities`) that grow with distinct trust pairs seen, not with config. 3.14.4 bounded the one in the function it changed and left these | Cheap holding fix (bound + LRU) until the MCP cache lifecycle register's §2 replaces them |

## 5. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| # | Item | Waiting on |
| --- | --- | --- |
| 3 | Postgres parallel DELETE not persisting — **closed 2026-09-02, file deleted.** Kept as a ledger row because rows 10 and §0 cite it. Quarantine lifted and path instrumented in #128 (2026-08-15); green on every run through the v3.14.3 tag with zero reruns. The full file is at `git show aaf101f:thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md`; `ACTINGWEB_PG_DELETE_DIAGNOSTICS` stays on in `tests.yml` so a recurrence names its mechanism | Nothing — unless it recurs, in which case reopen from the git history, not from memory |
| 12 | [Remove the legacy property GSI machinery](legacy-property-gsi-removal.md) | The **next major version bump**. Five removals, enumerated. Note the sequencing constraint: release notes telling legacy-GSI holdouts to migrate must ship in a release that **still contains the backfill script** — so the note is written before the removal, not alongside it. Also absorbs I3 (the `use_lookup_table` three-sources-of-truth wart), which was deferred to be paired with exactly this |
| 18 | [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | Also the **next major version bump**. Raises or removes the 1 MB per-partition DynamoDB Query ceiling that 3.14 (rows 14/15 above, closed) made survivable by removing the per-item multiplier against it, but did not remove — the consumer's largest list measured at 964 KB in one page, 94% of the limit. **Second motivation added 2026-08-29:** out-of-band per-item payload. 66.3% of a consumer's partition is embedding bytes no page renders; row 22's scoped read excludes 49.8% of it, but the remaining 16.7% is *inside* rows the page renders, and a consumer-side sidecar provably does not help (outputs already did that and the rows landed in the same partition). Relocating bytes within a partition does not reduce what a partition read costs | Filed alongside row 12 deliberately: both are next-major, both touch property storage layout, and doing the legacy-GSI removal first means this scheme gets designed against the final lookup-table-only shape rather than one still carrying legacy fallback tiers |
| 13 | [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is (a single one is the healthy handshake). Since #129 the library fires that criterion itself: a run from one origin escalates to a WARNING naming it, where previously the rejection was not logged at all. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision, since both of its inputs are removed |
| 20 | [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | Three verification steps the `ai-agent-discoverability` plan (`status: done`) couldn't complete in-session: submit to Context7, connect a real MCP client to the new quickstart, install the Agent Skill in a scratch consumer repo. (The fourth, confirming the readthedocs.io build, was done 2026-09-02 and is recorded in the plan) | Item 1 waits on someone with a Context7 account (a 200 from that host proves nothing, it 200s for made-up paths too); items 2-3 on resources this environment doesn't have — a real OAuth2 provider/MCP client and a throwaway consumer repo |
| 26 | [`demo.actingweb.io` OAuth login unverified](demo-live-oauth-login-unverified.md) | A browser and a Google account. The last owed step of the demo consolidation plan (closed 2026-09-02): nobody has recorded completing one OAuth login against the live site. Tick the plan's box and delete the file when done |

## 6. Registers — records, not schedulable work

Each holds deliberately-deferred items with the rationale they were cut and the
trigger that would justify pulling one forward. **A trigger that hasn't fired
means the register is working**, not that it's stale. Their value is stopping
decisions being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | 9 items deferred from the v3.13 scalability plan — batch writes, the `consistent_read` audit, `SubscriptionDiff` seqnr ordering, import-time table-name freezing. Item 9 is row 7 above. **Re-verified 2026-08-15 against `6187636`**: all nine still stood at that point, item 3 was 27 sites rather than ~22, item 2's proposed fix was partly *already shipped*. **3.14.0 closed two of the nine and part of a third**: item 1's `ListProperty.clear()/delete()` half is batched now (`DbTrustList`/attribute-bucket loops are not — item 1 otherwise stands); item 2 is closed in full by the handle API; item 3's `get_range` sub-item is closed by the `consistent=` parameter, its other ~26 sites stand. Items 4, 5, 6, 7, 8, 9 are untouched |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | 8 items scoped out of the trust-cache plan by name. §1 landed in #130 — with the constraint that eviction must be **actor-wide**, because `_actor_cache` holds a live `ActorInterface` carrying the trust list. §2 (cross-process invalidation) is the large one still open. §5 is worth reading even if never actioned: it records *why* the surviving substring peer-id match on the deletion path is not the bug the resolver fix closed — server-generated high-entropy client ids make it a collision, not a steerable attack |

---

## Conventions

`thoughts/README.md` is authoritative for the directory. Four things worth
repeating because they shape this list:

- **`todo/` is living, undated.** A todo is deleted when its work lands — the
  plan and verification are the record. Every file here is now undated by
  design; the one dated holdout, `2026-06-15-postgres-parallel-delete-not-persisting.md`,
  was deleted on 2026-09-02 when its work closed (row 3's ledger line in §5
  is what remains of it).
- **`mcp-2026-07-28-dual-era-support.md` is not a dated file.** `2026-07-28` is
  the MCP **spec revision** the todo is about, part of the slug. Don't "fix" it
  to an undated name and don't read it as a write date.
- **A todo that grows phases becomes a plan.** `/create_plan` from it, then
  either leave a stub pointing at the plan or delete the todo — the plan
  supersedes it. Rows 1 and 2 were planned jointly on 2026-08-15 and their files
  were deleted when that plan landed; row 2's surviving remainder was refiled as
  `whole-list-rewrite-atomicity.md` rather than kept as a stub, because the
  reasons its designs were cut are worth more than a pointer. Row 4 is the next
  nearest candidate.
- **A closed plan's unfinished remainder belongs here, not in an `active`
  plan.** As of 2026-09-02 every plan in `plans/` is `status: done` again, so
  `grep -l "^status: active"` returning nothing is correct — it means "nobody is
  mid-implementation", not "the grep is broken". It was not true for a week:
  `2026-08-22-demo-app-consolidation.md` stayed `active` after its Phases 4
  and 5 landed in `actingwebdemo` on 2026-08-25–27, because the work happened
  in the other repository and nobody came back to this one. When a plan's
  last phase lands *elsewhere*, closing it here is still owed. Five plans were carrying a
  wrong status from a 2026-07-26 bulk edit (`cc29c03`) that added the
  frontmatter to all 27 at once; their artifacts were on disk all along. The one
  genuine remainder that audit surfaced — the 2025-12 test-coverage plan's
  deferred phases 5 and 6 — was filed, reviewed, and **deliberately dropped**:
  the suite has grown far past that plan's target, so re-deriving today's gaps
  would beat working from its list.
