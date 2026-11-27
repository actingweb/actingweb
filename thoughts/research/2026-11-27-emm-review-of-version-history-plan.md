# Research: the consumer's review of the version-history plan, triaged

**Date:** 2026-11-27
**Plan:** thoughts/plans/2026-11-26-version-history-and-restore.md (approved 2026-11-26; updated and approved again 2026-11-27; not started)
**Source:** `thoughts/inbound/emm-review-of-version-history-plan.md`, filed
2026-11-27 by the Emm AI repository (`actingweb_mcp`, branch `research-docs`
at `4fd6fdc1`, on 4.0.0rc4), written to see how Emm would use the plan for
memories and Wiki documents.
**Checked against:** this branch at `9414d3b`, and `../actingweb_mcp` at
`4fd6fdc1`.

**State:** the report is deleted; this note, the plan's update of
2026-11-27 and three todos are the record. The owner decided on 2026-11-27:
the library restore of properties and attributes is removed from 4.1
(finding 1, going further than either option below: one write-back story
for all three kinds); a take can carry its own `max_versions` (finding 3,
option b); no retention-by-age call (finding 6, option a). Filed:
`todo/write-with-a-version-in-one-transaction.md`,
`todo/versions-batch-take.md`, `todo/versions-export-import.md`.

## What the check changed

- **No finding shows a defect in the plan's design.** No acceptance
  criterion is wrong. The review changes scope questions and guide text.
- **Finding 2's lost-version race does not happen** with the write Emm
  uses. The cost is a duplicate version, not a missing one.
- **Findings 3 and 6 are marked "blocks Emm" and do not block.** Both can
  be built on the planned calls. What remains is convenience, and a
  decision the owner already made once (plan line 102).
- **Finding 8's ask does not serve its use case.** A cursor over markers
  keyed by name cannot return the newest N.
- **Finding 4 confirms the re-key decision** (Evaluation Notes 12 to 15,
  AC-63). The deferred minted-keys plan has no consumer waiting for it.
- **The age sweep that answers finding 6 reads markers, and a marker can
  lag** after a logged fault. That is a new implication for the plan.
- **Finding 7 is wider than reported.** Emm's snapshot misses `{id}$aux`
  as well as `{id}$ver`, and `docs/` has no backup guidance for either.

## Findings

### 1. Phase 2 serves no known consumer — confirmed; owner decision

- **Checked.** Emm's instructions are one element in a property list
  (`emm:repositories/instruction_repository.py:75,248,322`), as memories
  and documents are. Phase 3 changes `actingweb/versions.py` only (plan
  810-829) and needs nothing from Phase 2.
- **Result.** True. Phase 3 depends on Phase 1 alone, so it can be
  committed before Phase 2 at no cost. Phase 2 holds the release's backend
  risk: two protocol methods, the cross-table transaction, the DynamoDB
  transaction shapes (Evaluation Note 43) and the custom-backend gate
  (AC-54). Its only evidence of demand is the feature's own line "that
  other consumers want this is a hypothesis".
- **Options.** (a) Keep the plan and swap the order of Phases 2 and 3.
  (b) Move Phase 2 to its own plan and release. By the Traceability
  table, AC-23 to AC-28, AC-34, AC-54, AC-57 and AC-67 move with it, and so
  do the restore halves of AC-22, AC-60 and AC-72. The Spec Delta's
  start-up and OPC-9 entries keep AC-66 only. `delete_with_versions`
  (AC-37) needs no backend call (plan 752-753) and can stay. 4.1 then adds
  no backend protocol method, and ships no library restore for any kind:
  every restore is the application's write. Restore would be designed
  together with finding 2's ask, the same primitive for a list row.

### 2. An element write and its version are two calls — the race is not as stated

- **Checked.** `update_by_handle` is a compare-and-swap on the handle's
  stored bytes (`actingweb/list_core.py:3801-3803`) and returns `False`
  when the row changed. Emm's writers read again and retry or raise on a
  lost swap (`emm:repositories/output_repository.py:1095-1142`,
  `emm:repositories/local_memory_repository.py:622-629`).
- **Result.** If Emm takes the value it read with the handle and then
  swaps, a writer landing in between makes the swap fail. Emm never
  overwrites a value nobody versioned. The other writer took its own
  version; Emm re-reads and takes the new current value. What is left:
  - a duplicate version after a lost swap or a failed write, which Emm can
    remove by the id `take` returned;
  - at the limit, that take has already trimmed the oldest real version,
    and removing the duplicate does not bring it back (the report says
    this too).

  The claim "that writer's value is never versioned" holds only for a
  write that is not conditional.
- **Disposition.** Phase 4 guide: the pattern (take what the handle read,
  swap, remove the version on a lost swap). The one-transaction write is a
  todo, with less value than the report gives it.

### 3. One app-wide limit — real, not blocking; owner decision

- **Checked.** `MAX_STORED_BYTES = 380_000` (`emm:helpers/output_limits.py:9`).
  The larger-documents feature exists and says "several megabytes". Plan
  line 102 rules out per-item limits and time-based retention (owner).
- **Result.**
  - `max_bytes` is a ceiling, not a reservation. Raising it app-wide costs
    memories nothing, so it needs no per-kind value.
  - A limit per kind can be built today: after a take, `all()` and
    `remove(id)` for the surplus. That repeats the library's trim in the
    application, without the guarantee of AC-72.
  - The storage arithmetic is right: 20 copies of a 5 MB document is about
    100 MB.
- **Options.** (a) Line 102 stands; the guide shows the application-side
  trim. (b) `take(..., max_versions=N)` overrides the app-wide value for
  that take: stateless, no prefix rules, the library's own trim. (c) The
  prefix map the report asks for; it needs a rule for which namespace a
  prefix matches (property names, element keys, buckets).

### 4. Emm's keys — confirmed

- **Checked.** A memory id is never reissued: the counter is kept past
  deletes and type deletes (`emm:repositories/memory_id_seq.py:1-24`,
  `emm:repositories/local_memory_repository.py:834-867`). A move allocates
  a new id (`:475-477`). A document's identity is `(origin_category, seq)`
  and survives a move (`emm:repositories/output_repository.py:350-370`).
- **Result.** True, and it is what Evaluation Notes 12 to 15 decided:
  `rename` after a move is enough. The plan's Decisions Deferred entry
  calls minted keys "the next plan"; no consumer is waiting for it now.
  Emm's own caveat stands: an id written by a CSV
  import or a restore can equal a deleted memory's id, and that item then
  joins the old history (plan: "two elements filed under one key share one
  history").
- **Disposition.** Phase 4 guide: the move pattern. A rename that has
  started is recorded in the old marker, listed (`renaming_to`) and
  finished by a repeat; only a rename that never started is "owed". The
  guide should give an order that needs no extra state.

### 5. Inline embeddings — confirmed, no ask

- **Checked.** 1024-dimension vectors (`emm:hooks/mcp/services/ai_service.py:1961`).
  The 10–20 KB size is the report's figure, not measured here.
- **Disposition.** Phase 4 guide, one sentence: pass what a restore needs,
  not derived fields. AC-61 already defines content as what was passed.

### 6. Deletes: bulk takes and retention by age

- **Checked.** A take is create marker, read newest id, write head,
  advance marker, plus a range read when a limit is set (plan 583-589):
  the report's 4–5 calls, from the plan, not measured. A trim runs only in
  a take, so a deleted item's versions stay until removed.
- **Bulk take — real, a todo.** 500 takes are about 2,500 calls. A batch
  call could share the reads; it still writes a head and a marker per
  item. The guide should give the cost of versioning a bulk delete, so the
  application chooses.
- **Retention by age — not blocking; owner decision.** It can be built on
  the plan: Emm puts `action: delete` in the metadata of the take before a
  delete; `list_elements(prefix)` returns each key's newest timestamp and
  metadata from the markers alone (AC-69); `remove_all()` removes the ones
  past 30 days. One marker read per actor.
  - The listing is an index that can lag. A marker write that faults
    after the head is logged, not raised (plan 585-586), and only `all()`
    or the item's next take repairs it (551-552). A deleted item never
    takes again. So a pre-delete take whose marker write faulted shows its
    older version in the listing, or is not listed at all if it was the
    item's first, and the sweep misses it. Emm can close this by calling
    `all()` after a pre-delete take. The plan should say so in the guide,
    or let a listing repair what it reads.
  - Any library call (`remove_older_than`) would need the same per-actor
    caller, and the library cannot tell a deleted item from a live one.
  - An actor that never returns keeps its deleted content until a job
    visits it or the account is deleted (AC-38). That is the statement Emm
    makes to users either way.
- **Options.** (a) Line 102 stands; the guide shows the sweep. (b) A
  library call that removes versions older than a timestamp under a prefix.

### 7. Backup and restore of an account — confirmed, and wider

- **Checked.** `import --full` creates the actor through the library with
  its own id (the script's docstring, `emm:scripts/restore_actor.py:43`), so AC-73 purges
  `{id}$ver` first. `export` reads `fetch_all_including_lists(actor_id)`,
  which queries the actor's own partition (`actingweb/db/dynamodb/property.py:910`);
  `apply` queries by the actor id as hash key. Neither reads `{id}$ver`,
  and neither reads `{id}$aux`.
- **Result.** True. The `$aux` half matters once Emm's documents pass the
  row cap. No guide in `docs/` says a backup of one actor must include the
  hidden partitions.
- **Disposition.** Phase 4 guide (`database-maintenance.rst`): a per-actor
  backup includes `{id}$ver` and `{id}$aux`; version rows are written back
  after the create, since the create clears them. An export/import command
  is a todo.

### 8. Listings at scale — the ask does not fit

- **Checked.** `list_elements(prefix)` returns a list from one range read
  of marker rows (plan 497-500, 540-552). Markers are keyed by name.
- **Result.** "Newest N" needs every marker read and sorted, with or
  without a cursor. The read is markers only (an estimated few hundred
  bytes each with Emm's metadata), against today's dump of every list
  (`emm:repositories/audit_log_repository.py:206-249`). A prefix narrows it
  to one type.
- **Disposition.** No change. Revisit with `todo/bounded-list-read.md` if
  a marker listing shows up in measurements.

### 9. Cost per take — accepted

- **Disposition.** Phase 4 guide: publish the counts
  `S::test_take_cost_per_kind` pins, and the body-row arithmetic for large
  content (one 350,000-byte row per 350 KB). The single-partition throttle
  note (plan 1028) stays unverified; a measured threshold is not promised.

### 10. Rollout — no action

- **Checked.** `emm:scripts/reset_database.sh:98-99` and
  `emm:scripts/migrate_db.py` run the library's `alembic upgrade head`.
  The plan's header already gates on the `v4.0.0` tag.

## Not checked

Whether one transaction could cover a spanned element.
`emm:api/merge_api.py`, the batch delete's 25-item bound, the whole-type
and whole-category delete tools, `emm:helpers/write_origin.py`, and every
size the report gives for embeddings and memories.

## For the plan (`/update_plan`), whatever the owner decides

Phase 4's guide gains: the edit pattern for a list element (2), the
move pattern (4), derived fields (5), the cost of a bulk delete (6), the
age sweep (6), backup of both hidden partitions (7), measured take costs
(9), and that a listing can lag behind a take (6). Decisions Deferred
loses "It is the next plan". No acceptance criterion changes unless option
(b) is chosen for 1, 3 or 6.

## Todos filed

- A list-element write with its version in one transaction (2).
- A batch take (6).
- An export and import of an actor's versions (7).
