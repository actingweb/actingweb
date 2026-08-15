# todo/ — prioritised index

Every file in this directory, ordered by what to do next. **Built 2026-08-13**
from a full read of every file. **Reviewed 2026-08-14** — an audit of all
27 plans and 17 research docs for uncovered work (6 plan statuses corrected, 4
todos added), followed by an item-by-item walkthrough with the owner (1 todo
dropped, every row given a direction). **Last reviewed 2026-08-15** — the
2026-08-14 directions scoped against the 3.13.0 GA release; see §0.

**Rows 1 and 2 are gone, and the numbering below is deliberately not
re-flowed** — too many rows cite each other by number for renumbering to be a
cheap edit. Row 1 (`migrate_to_v2()` needs a claim) was closed on 2026-08-15 by
an accepted last-writer-wins trade rather than by a claim row; the reasoning now
lives in `docs/guides/property-lists.rst`. Row 2 (`compact()` needs a
recoverable commit protocol) was deferred to 3.14 and survives as row 9b.

Each row's **Decided 2026-08-14** clause is the outcome of that walkthrough. It
records the direction taken and, where it matters, the option *not* taken.
Rows 12 and 13 carry no such clause by design — a blocked item's trigger *is*
its decision, and both triggers were reconfirmed unfired.

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

## 0. 3.13.0 GA scope

**Decided 2026-08-15.** A lens over the rows below, not a second ordering — it
assigns each 2026-08-14 direction to *before GA*, *at GA*, or *3.14*. Nothing
here re-decides a row; if this section and a row disagree, the row wins, and if
a row and its file disagree, the file wins.

The organising argument: **GA is the event that triggers fleet-wide
`actingweb-migrate-property-lists` and `actingweb-verify-property-lists
--repair` runs.** Rows 1 and 2 are what make those two tools safe to run. A
release whose point is "safe to migrate onto" cannot ship with the migration
and repair tools themselves not crash-safe.

| Tier | Items | Note |
| --- | --- | --- |
| **Gated GA — LANDED 2026-08-15** | `thoughts/plans/2026-08-15-property-list-metadata-integrity.md` (`status: done`) | **Not what rows 1+2 asked for.** Three review passes over two candidate designs surfaced something worse than the crash windows they targeted: a concurrent `append()` writes stale cached metadata back over a completed migration, reverting the format flip and **destroying the whole list on ordinary traffic**. Previously unfiled. The plan landed that plus the re-run non-convergence of both format-changing rewrites, closed row 1 by an accepted trade, and deferred row 2 to 3.14. Rows 1 and 2 are gone from §1 as a result; row 2 survives as row 9b |
| **Gating question, not a gating fix** | Rows 3 + 10's shared instrumentation branch | Start **in parallel** — CI turnaround is its latency. If it shows the DELETE matched rows but did not commit, the PG backend can drop a committed write under concurrency and this becomes a hard blocker needing lead time. If it shows 0 rows matched or a wrong `search_path`, it is test infra and does not gate |
| **In GA scope** | Rows 6, 11, 8, and the `dynamodb-known-next` re-verification pass | Small independent branches. The re-verification pass was already decided as GA work; run it *after* the others, so "the settled codebase" is true when you walk the nine items |
| **At GA, not before** | Row 5's re-measurement | The decision is to measure against GA before designing. First post-GA action; the fix is 3.14 |
| **Not GA** | Row 9b ([whole-list rewrite atomicity](whole-list-rewrite-atomicity.md), the former row 2), rows 4, 9, 7's guard, 12, 13 | Row 2 was **deferred on 2026-08-15** after two designs failed adversarial review — rc6 already documents the window, the damage is visible, and `verify()` catches it. Shipping a third design under GA time pressure was judged worse. Row 4 sequences after it either way. Row 9 is post-incident tooling. Rows 12 and 13 are blocked, triggers unfired |

The organising argument above is the one that made rows 1+2 the blocker. It
survives the retiering, but weaker than it looks: the tools operators run at GA
are now *convergent on re-run* (plan Phase 2) and can no longer be reverted by an
ordinary write (Phase 1), while `compact()`'s remaining crash window stays
documented, visible, and detectable. That is the trade — read the plan's
"Designs cut" before reopening it.

**With that landed, nothing in this index gates GA.** The tier above is kept
rather than deleted because it records *why* the release was held and what was
accepted in exchange — the next person to ask "why did 3.13 ship with
`compact()` not crash-safe?" needs this paragraph, not a git log.

Two couplings that decide sequencing inside the GA tier:

- **Row 6 before row 7's guard, and the cache-lifetime question before row 6's
  code.** Both rows point at item 4 of `subs-list-cache-asymmetry.md` — whether
  `_actor_cache` should hold instance state at all. Answer it **on paper before
  writing row 6's eviction wiring**, because what the cache ends up holding
  changes the eviction surface. Any Actor-cache restructuring that answer
  implies, and the `is None` guard itself, are 3.14.
- **Row 11 makes row 13's trigger observable.** Raising the log level is what
  lets a sustained `-32600` stream from one origin be seen before the consumer
  fleet grows past the point where anyone would notice. Do it while the fleet
  is small.

**Release shape.** `rc6` shipped 2026-08-09 with an empty `Unreleased`. The GA
plan landed 2026-08-15 and does touch the migrate path and metadata writes on
every mutation, and every prior property-list change took its own rc — so **an
rc7 soak before the GA tag** remains the safer read, though the case is weaker
than it was, since the migrate/repair machinery was not restructured in the end.
Confirm with the maintainer rather than assuming either way.

## 1. Do next

Real problems, in production or under it, with a known shape.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 3 | [Postgres parallel DELETE not persisting](2026-06-15-postgres-parallel-delete-not-persisting.md) | Answers whether the PG backend can silently drop a committed `DELETE` under concurrency, and lifts the quarantine on two assertions currently dark on postgresql | Open since June with no root cause — but the **decisive step is cheap and nobody has run it**: log `cur.rowcount` and `search_path` from `delete_attr` in CI, and the leading hypothesis (a pooled connection contaminated by the `property_lookup_pkey` error) either falls or stands. **Decided 2026-08-14: one instrumentation branch covering this and row 10** — same matrix, and row 10's process-global psycopg pool is this row's leading hypothesis |

## 2. High leverage

Bigger, designed, and each buys more than it costs.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 4 | [`ListAttribute` shift-loop design](attribute-list-shift-design.md) | Removes the **last instance** of the design that caused the production list corruption — `ListAttribute` still has, verbatim, what `ListProperty` had before the 3.13 fix | Materially cheaper than when filed: the fractional-rank v2 format, its `verify()`/`compact()` primitives and its migration shape now exist and are proven, so option 3 — the only option that closes the corruption class rather than mitigating it — is mostly a port. It waited on **lower blast radius**, not on being safe. **Decided 2026-08-14: option 3, the full v2 port** — the only one that closes the class rather than mitigating it |
| 5 | [Property fetch reads the whole partition](property-fetch-reads-whole-partition.md) (I0) | Cuts the dominant remaining read cost for list-heavy actors: one measured production actor paid **1,027 RCU to return 5 properties**, because ~1,009 `list:*` rows share its partition and are discarded client-side | Called *"the most valuable thing in this document"* by the consumer feedback that drove 3.13, and deferred **to 3.14** only because it is a hot-path rewrite on an already-validated release — that window opens at GA. 3.13 removed the *cross-actor* superlinearity, which was the important half; this is the *within-actor* half. **Invisible without per-call capacity instrumentation**, so it will not resurface on its own. **Decided 2026-08-14: re-measure against GA before designing** — the deferral rationale rests on rc1 numbers, and which fix shape is right depends on how dominant the `list:` rows still are |
| 6 | **Revocation doesn't evict the MCP caches** — §1 of [cache-lifecycle register](mcp-cache-lifecycle-and-revocation.md) | A revoked token, deleted trust or downgraded permission actually stops working, instead of being honoured for up to the 5-minute cache TTL in every warm process | `clear_token_from_cache()` has exactly **one** caller (logout) — `revoke_token`, `revoke_all_tokens`, `/oauth/revoke`, trust deletion and permission downgrade all miss it. The tuple-keyed `_trust_cache` the trust-cache plan added already supports the eviction, so §1 is wiring, not design. Don't let §2 (cross-process invalidation, genuinely large) block it. **Decided 2026-08-14: both paths** — token-keyed eviction on the three revocation endpoints, plus direct `_trust_cache` eviction on trust deletion and permission downgrade |

## 3. Real, not urgent

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 7 | [`subs_list` cache asymmetry](subs-list-cache-asymmetry.md) | Drops one **strongly-consistent Query per property write** for every actor with no subscribers | **The ordering is the whole item.** The one-line guard fix (`is None`) is unsafe until the cross-request `Actor` cache is dealt with: the falsy guard is exactly what stops a long-lived MCP-cached actor going permanently blind to subscriptions created in another container. The correctness half landed in rc2; landing the cost half first trades a bounded cost bug for an unbounded correctness one. **Decided 2026-08-14: take the cache-lifetime question (item 4) rather than the guard** — does `_actor_cache` hold identity/auth only, or do instance caches need a request-boundary reset? That unblocks the guard and de-risks every future memo. **Pair with row 6**, same cache module |
| 8 | [`output_schema` on `action_hook` never reaches MCP](action-hook-output-schema-not-visible-to-mcp.md) | Closes an ergonomic trap: an author who declares `output_schema=` or annotates a `TypedDict` return reasonably believes their MCP tool advertises `outputSchema`, and it does not | Documented in rc4, unfixed, and the two decorators keep diverging. Merging **by default** would newly advertise `outputSchema` for every TypedDict-annotated tool and break the ones that return no `structuredContent` — so that decision belongs with the structuredContent research, not on its own. **Decided 2026-08-14: option 4 now** — warn at `tools/list` when `_hook_metadata` carries an `output_schema` and `_mcp_metadata` does not. Cheap, cannot false-positive, catches the confusion at registration rather than call time, and forecloses nothing |
| 9 | [Orphan detection in the offline verifier](orphan-detection-in-verifier.md) (DEL5) | Ships the sweep every consumer writes for themselves after a deletion incident — and ships it with the four edge cases that make it safe | Purely additive; `verify_tables` already exists to host it. The reason to do it in the library is that the classification is **not obvious**: an empty actor set must yield *zero* orphans, not "everything", and system actors like `_actingweb_websocket` hold live data under ids deliberately absent from the actors table. All four cases are already written into `docs/reference/actor-deletion.rst` — start there. **Decided 2026-08-14: ship it in `verify_tables`** rather than leaving each consumer to write their own |
| 9b | [Whole-list rewrite atomicity](whole-list-rewrite-atomicity.md) | An interrupted `compact()` stops leaving a double of the list that `--repair` will not itself remove — the former row 2's problem, still unsolved | **Deferred from GA on 2026-08-15, and the reason is the value of this file.** Two designs died under adversarial review — a lease-plus-journal whose replay destroys data a plain re-run preserves, and a stage-and-flip whose metadata marker silently permutes lists on the documented `--repair` → `--migrate` sequence. The successor todo carries the constraints they established, chiefly that **`fetch_all_including_lists` is a paginated DynamoDB query, not a snapshot**, which rules out storing "which namespace is live" in the item partition. Do not propose a third design without reading them. Reachability is low and the current failure is loud, which is what makes deferring defensible |
| 10 | [Postgres parallel CI flakiness](ci-postgres-parallel-flakiness.md) | Removes the remaining instability the hang watchdog only bounds — a fixed-`creator` test racing two process-global singletons, a full alembic chain per xdist worker, and an unexamined `--dist loadgroup` requirement | Not the same defect as row 3 (that one is correctness, this is test infra), but same matrix and same conditions, and follow-up 1's process-global psycopg pool is row 3's leading hypothesis. **Decided 2026-08-14: one instrumentation branch shared with row 3**, which promotes this off "not urgent" as a passenger |

## 4. Cheap cleanups

Small, mechanical, each removes something actively misleading.

| # | Item | Impact of doing it | Why now |
| --- | --- | --- | --- |
| 11 | **Harden the `-32600` dual-era signal** — "Cheap hardening" in [dual-era support](mcp-2026-07-28-dual-era-support.md) | Pins the behaviour that lets dual-era MCP clients fall back to us, names our supported versions where a client can surface them, and makes modern-only clients visible in telemetry rather than via user reports | **Read the trap before touching the error path.** The HTTP 400 + `-32600` we answer an unknown protocol version with **is** the legacy-server signal a dual-era client falls back on. Replacing it with a spec-shaped `-32022` + `data.supported` looks more correct and converts every dual-era client's working fallback into a retry loop — and **no test asserts it as the fallback signal**. **Decided 2026-08-14: all three items** — regression test, versions named in the `message` string (never `data.supported`), and the log level raised so row 13's trigger is observable. Needs none of the deferred work in row 13 |

## 5. Blocked or waiting on someone else

Nothing to do until the named thing happens. Listed so they aren't mistaken for
neglected work.

| # | Item | Waiting on |
| --- | --- | --- |
| 12 | [Remove the legacy property GSI machinery](legacy-property-gsi-removal.md) | The **next major version bump**. Five removals, enumerated. Note the sequencing constraint: release notes telling legacy-GSI holdouts to migrate must ship in a release that **still contains the backfill script** — so the note is written before the removal, not alongside it. Also absorbs I3 (the `use_lookup_table` three-sources-of-truth wart), which was deferred to be paired with exactly this |
| 13 | [Dual-era MCP support](mcp-2026-07-28-dual-era-support.md) | A client we serve going **modern-only**. A dual-era client needs nothing from us, so "supports 2026-07-28" is not the signal — a *sustained* stream of 400/`-32600` from one origin is (a single one is the healthy handshake). Also blocked-adjacent: `actingweb_mcp`'s `require_mcp_auth_for_init` middleware silently becomes a no-op under the modern revision, since both of its inputs are removed |

## 6. Registers — records, not schedulable work

Each holds deliberately-deferred items with the rationale they were cut and the
trigger that would justify pulling one forward. **A trigger that hasn't fired
means the register is working**, not that it's stale. Their value is stopping
decisions being re-litigated.

| Item | What it holds |
| --- | --- |
| [DynamoDB known-next](dynamodb-known-next.md) | 9 items deferred from the v3.13 scalability plan — batch writes, the `consistent_read` audit, `SubscriptionDiff` seqnr ordering, import-time table-name freezing. Item 9 is row 7 above; row 5 is the adjacent per-partition defect. Line references are from `29783f8` and have **not** been re-verified since July — **decided 2026-08-14: fold a re-verification pass into the 3.13.0 GA work**, when the codebase settles |
| [MCP cache lifecycle and revocation](mcp-cache-lifecycle-and-revocation.md) | 8 items scoped out of the trust-cache plan by name. §1 is row 6 above. §5 is worth reading even if never actioned: it records *why* the surviving substring peer-id match on the deletion path is not the bug the resolver fix closed — server-generated high-entropy client ids make it a collision, not a steerable attack |

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
  supersedes it. Rows 1+2 were planned jointly on 2026-08-15 and now carry
  stubs; both are deleted when that plan lands. Row 4 is next nearest.
- **A closed plan's unfinished remainder belongs here, not in an `active`
  plan.** As of 2026-08-14 every plan in `plans/` is `status: done`, so
  `grep -l "^status: active"` returning nothing is correct — it means "nobody is
  mid-implementation", not "the grep is broken". Five plans were carrying a
  wrong status from a 2026-07-26 bulk edit (`cc29c03`) that added the
  frontmatter to all 27 at once; their artifacts were on disk all along. The one
  genuine remainder that audit surfaced — the 2025-12 test-coverage plan's
  deferred phases 5 and 6 — was filed, reviewed, and **deliberately dropped**:
  the suite has grown far past that plan's target, so re-deriving today's gaps
  would beat working from its list.
