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

Nothing here currently — the 3.14.0 verification's findings (see
`thoughts/verifications/2026-08-21-v2-positional-access-cost.md`) were
actioned same-day on the release branch, including the release-blocking
cross-version wording fix.

## 2. High leverage

Bigger, designed, and each buys more than it costs.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 4 | [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the 3.13 fix | Materially cheaper than when filed: the fractional-rank v2 format, its `verify()`/`compact()` primitives and its migration shape now exist and are proven, so option 3 — the only option that closes the corruption class rather than mitigating it — is mostly a port. It waited on **lower blast radius**, not on being safe. **Decided 2026-08-14: option 3, the full v2 port.** Sequence it after row 9b, or the port reproduces that gap in a second class |

## 3. Real, not urgent

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 7 | [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers | **The ordering is the whole item.** The one-line guard fix (`is None`) is unsafe until the cross-request `Actor` cache is dealt with: the falsy guard is exactly what stops a long-lived MCP-cached actor going permanently blind to subscriptions created in another container. The correctness half landed in rc2. **Decided 2026-08-14: take the cache-lifetime question (item 4) rather than the guard** — does `_actor_cache` hold identity/auth only, or do instance caches need a request-boundary reset? The *does it* half was answered on 2026-08-15 (`thoughts/research/2026-08-15-mcp-actor-cache-holds-instance-state.md`: it holds a live `ActorInterface`) and that was enough to make the revocation-eviction work correct (#130); the *should it* is this row's alone, and the guard stays blocked on it |
| 8 | [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | The cheap half (option 4, warn at `tools/list`) **landed 2026-08-15**; the asymmetry itself is untouched. What is left is options 2 and 3, and merging **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent` — so it is not an independent decision. **Decide it with the structuredContent research** (`thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`, option C), not on its own |
| 9b | [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove — the former row 2's problem, still unsolved | **Deferred from GA on 2026-08-15, and the reason is the value of this file.** Two designs died under adversarial review — a lease-plus-journal whose replay destroys data a plain re-run preserves, and a stage-and-flip whose metadata marker silently permutes lists on the documented `--repair` → `--migrate` sequence. The file carries the constraints they established, chiefly that **`fetch_all_including_lists` is a paginated DynamoDB query, not a snapshot**, which rules out storing "which namespace is live" in the item partition. Do not propose a third design without reading them. Reachability is low and the current failure is loud, which is what makes deferring defensible. **Smaller as of 3.14.0**: the missing-CAS constraint that former row 9c shared this file for is closed — what remains is `compact()`'s crash-atomicity alone |
| 19 | [v2 list access verification follow-ups](v2-list-access-verification-followups.md) | The residue after the 2026-08-21 same-day actioning of the 3.14.0 verification's findings: two plan-named integration tests never written (Phase 10 end-to-end peer-replica, Phase 9B interleaved-append), and the www HTML UI's missing contention mapping | None block anything — the compounding item (the 19-file `ruff format` drift) was closed post-tag with `ruff format --check` added to CI; what's left waits for the next time someone is in the subscription-delivery or www code |
| 10 | [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the remaining instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Not the same defect as row 3 (that one is correctness, this is test infra), but same matrix and same conditions. **Decided 2026-08-14: one instrumentation branch shared with row 3.** That branch ran 2026-08-15 and **collected for row 3 only** — the shared surface was follow-up 1's process-global singletons, and the pool half of it had already been rebuilt in #117, leaving nothing here to instrument. All three follow-ups stay open |
| 21 | [MCP discovery metadata fidelity](mcp-discovery-metadata-fidelity.md) | Stops the discovery chain the 3.14.2 fixes made load-bearing from reporting literals: `/mcp/info` advertises `tools_count: 4` and "ActingWeb MCP Demo" for every deployment, and `GET /mcp` reports `actingweb-mcp` as the server name while the handshake reports the configured one | Filed from the PR #138 review, none of it the reported bug. Two items are one-liners (the `server_name` disagreement, deleting the dead divergent `get_oauth_discovery_metadata`); the `/mcp/info` one needs a call on whether to derive the counts or drop the fields, and should collapse the duplicated builder across the two integrations while it is open. **Do it the next time anyone is in the MCP metadata surface** — it is exactly the code 3.14.2 touched, and reading it twice is the cost of not doing it then |

## 5. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| # | Item | Waiting on |
| --- | --- | --- |
| 3 | [Postgres parallel DELETE not persisting](2026-06-15-postgres-parallel-delete-not-persisting.md) | **Time, then deletion of the file.** The quarantine was lifted and the path instrumented on 2026-08-15 (#128); the postgres matrix has been green on every run since, across five PRs, with zero reruns. That is evidence the symptom is gone, **not** a diagnosis — both ranked hypotheses had their proximate mechanism removed by #115 and #117 without anyone noticing. `ACTINGWEB_PG_DELETE_DIAGNOSTICS` stays on in CI so a recurrence names its mechanism in the first failing run. **Delete this file after a few more weeks of green (~early September 2026).** If it recurs first, the diagnostics are the whole point and the file is where the evidence goes |
| 12 | [Remove the legacy property GSI machinery](legacy-property-gsi-removal.md) | The **next major version bump**. Five removals, enumerated. Note the sequencing constraint: release notes telling legacy-GSI holdouts to migrate must ship in a release that **still contains the backfill script** — so the note is written before the removal, not alongside it. Also absorbs I3 (the `use_lookup_table` three-sources-of-truth wart), which was deferred to be paired with exactly this |
| 18 | [A `prop#`/`list#` key-prefix scheme](prop-list-key-prefix-scheme.md) | Also the **next major version bump**. Raises or removes the 1 MB per-partition DynamoDB Query ceiling that 3.14 (rows 14/15 above, closed) made survivable by removing the per-item multiplier against it, but did not remove — the consumer's largest list measured at 964 KB in one page, 94% of the limit | Filed alongside row 12 deliberately: both are next-major, both touch property storage layout, and doing the legacy-GSI removal first means this scheme gets designed against the final lookup-table-only shape rather than one still carrying legacy fallback tiers |
| 13 | [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is (a single one is the healthy handshake). Since #129 the library fires that criterion itself: a run from one origin escalates to a WARNING naming it, where previously the rejection was not logged at all. Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision, since both of its inputs are removed |
| 20 | [AI agent discoverability follow-ups](ai-agent-discoverability-followups.md) | Four verification steps the `ai-agent-discoverability` plan (`status: done`) couldn't complete in-session: confirm the readthedocs.io build after merge, submit to Context7, connect a real MCP client to the new quickstart, install the Agent Skill in a scratch consumer repo | Waiting on the PR merging and its docs build going live (items 1-2), and on resources this environment doesn't have — a real OAuth2 provider/MCP client and a throwaway consumer repo (items 3-4) |

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
  plan and verification are the record. Newer files here are undated by design;
  `2026-06-15-postgres-parallel-delete-not-persisting.md` predates that
  convention and is kept for its links.
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
  plan.** Every plan in `plans/` is `status: done`, so
  `grep -l "^status: active"` returning nothing is correct — it means "nobody is
  mid-implementation", not "the grep is broken". Five plans were carrying a
  wrong status from a 2026-07-26 bulk edit (`cc29c03`) that added the
  frontmatter to all 27 at once; their artifacts were on disk all along. The one
  genuine remainder that audit surfaced — the 2025-12 test-coverage plan's
  deferred phases 5 and 6 — was filed, reviewed, and **deliberately dropped**:
  the suite has grown far past that plan's target, so re-deriving today's gaps
  would beat working from its list.
