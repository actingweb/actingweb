# Research: the DynamoDB creator record against the actor row

**Date:** 2026-10-30
**Branch:** release/3.16.0-creator-uniqueness (uncommitted, after Iterations 45-51)
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Prompted by:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-2.md
**Addendum:** 2026-10-30, after verification -3 (rules 8-10, rule 2 amended; at the end); second part after verification -4 (M widened, rules 1 and 2 extended); third part after verification -7 (V, rule 11)

## Why this audit

Two verification rounds of PR 2 found 27 issues. In the second round, seven
of eleven (A8, B8, C8, D8, E8, J8, K8) were one problem in different
places: the DynamoDB `creators` record and the actor row disagree, and a
reader or writer treated that as impossible or as damage. A8 was a
regression from the fix for F7. Fixing one site at a time has not
converged. This note states the invariant, lists every writer and reader
across the rollout stages, and proposes the few rules the fixes should
follow.

On PostgreSQL the holder is the actor row itself, through the
`ux_actors_creator` index, so there is no second copy that can drift. Its
remaining findings (F8, G8, I8, the stale-handle rename in L8) belong to
the sign-in path and are listed at the end.

**Owner decision (2026-10-30), K8:** the startup probe fails closed. A
fault while checking stops the application, the same as definite absence.

## The invariant

Once the backfill-complete item `#meta#backfill` exists:

> **I.** There is a record `c → X` exactly when the actor row X exists, its
> stored creator normalised (`normalise_creator`) is `c`, and `c` is not
> exempt.

`normalise_creator` lowercases values containing `@` and leaves others
unchanged (`creator_rules.py`).

### Gaps the design allows

These are short, expected states in which I does not hold. Readers must
tolerate them.

| Gap | State | Opened by | Closed by |
| --- | --- | --- | --- |
| **G1** rename | `old → X` lingers, X's creator is `new`; `new → X` already exists | `_modify_unique` commits (`dynamodb/actor.py:189`) | its `_release_record(old)` |
| **G2** swap | `c → N`; squatter S's row still has `c` | `replace_creator_holder` (`:317`) | `_remove_for_replacement(S)` in `_replace_enforced` (`oauth2.py:2010`) |
| **G3** delete | the record `c → X` remains, X's row is gone | `_delete_as_stored` (`:407`) | `_release_record(c)` |
| **G4** scan skew | none in the store itself: a reader's two scans (actors, then records) disagree | `collect` (`unique_creators.py:298`) | a consistent re-read |

### Gaps that outlive a fault

The same gaps become permanent, with no second attempt, when:
- G1 or G3's release faults: logged at `dynamodb/actor.py:433`;
- G2's removal faults, or the successor's create fails after the swap
  (entry 46);
- an **old flag-off process** writes during the rollout (stages S1-S3
  below). It creates actors without records, leaves records behind when it
  deletes (G3) and when it renames (G1), and never writes the record for
  its new value.

## Rollout stages

| Stage | State | Who writes |
| --- | --- | --- |
| **S0** | flag off, no table (or an empty one auto-created) | flag-off processes |
| **S1** | `enable` running (step 3) | flag-off processes and `enable` |
| **S2** | backfilled; every process still flag off (between steps 3 and 4) | flag-off processes |
| **S3** | rolling deploy (step 4); old and new processes both serve | both |
| **S4** | every process flag on (steps 5-6 run here) | flag-on processes, `enable`, `resolve` |
| **S5** | `disable` (flag already off everywhere) | flag-off processes and `disable` |

S1-S3 and S5 always produce I-violations on DynamoDB; that is why the
rollout runs `enable` and `report` again in S4. In S4 the only sources
are faults and the command itself.

## Writers

| # | Writer | Where | Writes | Leaves | Finding |
| --- | --- | --- | --- | --- | --- |
| W1 | flag-on create | `dynamodb/actor.py:252` | actor + `c → X`, one transaction | nothing | |
| W2 | flag-on rename | `_modify_unique` `:189` | actor + `new → X`, then releases `old` | G1 until the release | **A8:** a case-only rename (`Foo@X.com` → `foo@x.com`) releases the key it just claimed |
| W3 | flag-on delete | `delete` `:379` | actor delete conditioned on its creator, then the release | G3 until the release | F7 fixed |
| W4 | swap | `replace_creator_holder` `:317` | N + `c → N`, one transaction | G2 until the removal | |
| W5 | rollback after the swap | `actor.py` create rollback (entry 46) | keeps N unmarked | G2 until the removal | |
| W6 | old flag-off process | any `DbActor` built with the flag off | actor only | unrecorded actors, G1 and G3 for good | |
| W7 | `resolve` rename | `_rename` `unique_creators.py:436` | actor (flag off), then deletes `old → X` | the kept actor unrecorded until `enable` | **D8:** deletes instead of moving to the kept actor |
| W8 | `resolve` repair | `_repair_record` `:475` | deletes `c → X` if it names X | | **B8:** no re-read, so it deletes a live actor's record listed through G4 |
| W9 | `enable` backfill | `_enable_dynamodb` `:643` | `c → X` if absent, after a consistent re-read | | **C8:** a G2 squatter reads as a collision and stops the run; **E8:** `--creator` writes the backfill-complete item for every creator |
| W10 | `disable` | `:719` | deletes the backfill-complete item and every record | | **J8:** runs against live flag-on processes; a partial run cannot be resumed |
| W11 | the force-email rewrite | `Actor.get` `actor.py:282` | a W2 rename triggered by a read | G1 | **G8:** it runs inside the lookup |

## Readers

| # | Reader | Where | Reads | Must tolerate |
| --- | --- | --- | --- | --- |
| R1 | sign-in lookup (`get_from_creator`), used by OAuth, SPA, `oauth_email`, the factory form and `ActorInterface` | `actor.py:319`, `:370` | the record, then the actor (`DbActor.get` reads consistently, `dynamodb/actor.py:82`) | G1 (the old key names X), G3 (X gone), and the permanent forms of both |
| R2 | create condition | W1/W4 transaction | the record exists | G1 (`new` is taken during it, correctly), G3 (an orphan blocks the address) |
| R3 | `report` | `collect` `:298` | an actor scan, then a record scan | G4 above all; G1 and G2 in flight |
| R4 | `enable` collision check | `_enable_dynamodb` | the record for a pending actor | G2 (two rows share `c`, the record names N) |
| R5 | startup probe | `missing_enforcement` `:775`, `app.py:1535` | the table and the backfill-complete item | a fault (K8: now fails closed) |
| R6 | swap recovery read | `_replace_enforced` except branch | the holder | a fault (**H8:** `strict=False` reads a fault as "the swap did not happen") |

## What each reader sees, and what it should do

**R1, the lookup.** In S4 it can meet each of these:

| Record says | Actor read shows | Today | Should |
| --- | --- | --- | --- |
| `c → X` | X with creator `c` | load X | load X |
| `c → X` | X gone (G3) | False, and the create then raises `CreatorTaken`: 409 for good | repair, then create |
| `c → X` | X with creator `b` (G1) | 503 until `resolve` | repair, then create |
| no record | | create | create |

The repair is safe here because R1's actor read is consistent: the record
is provably stale. The repair is a delete conditioned on `actor_id == X`.
A rename of X back to `c` racing with it re-puts the record (W2's condition
is "absent or mine"), so the worst case is that the rename gets
`CreatorTaken`, which is correct. This replaces entry 45's fail-closed:
it no longer locks the owner out.

G8 sits in R1 too. The comparison must be made on the creator **as
stored**, before `Actor.get`'s force-email rewrite runs. Under the flag,
the rewrite should not run inside a lookup at all; it changes the value
being looked up.

**R3, `report`.** Every classification derived from two scans has to be
confirmed by a consistent read of the actor before it is listed as damage:
- **"missing" (B8):** list it only if X is still gone on a consistent read.
- **"mismatch":** list it only if X's creator still differs.
- **"unrecorded":** list it only if the record is still absent.

G1 and G2 in flight then show up at most as one transient line, which a
re-run clears.

**R4, `enable`.** When the record for a pending actor names another actor
whose consistent row also has `c`, this is a G2 or a real duplicate, not
corruption. `enable` should list it (exit 1) and carry on, rather than stop
with `collision`. `enable` should then write the backfill-complete item
only when nothing was listed (C8). `--creator` is refused for `enable` and
`disable` (E8).

**R6.** A strict read. On a fault, log that the squatter is still live; it
is the tombstone and token state the next sign-in finishes (H8).

## Rules for the fix

1. **One record-delete helper.** It re-reads the actor consistently and
   deletes `c → X`, conditioned on `actor_id == X`, only if X is gone or
   its normalised creator is not `c`. W8 (repair), R1's repair and W7's
   release all use it.
   - **Exception:** the runtime's own release right after its own
     committed write (W2, W3) may skip the read, because it knows the new
     value. It must skip the release when `normalise(old) == new` (A8).
2. **Move, don't delete.** When `resolve` renames the actor a record names,
   it moves the record to the kept actor with a conditional update
   (`actor_id == renamed`) if the kept actor's creator is `c` (D8).
   Otherwise it uses rule 1.
3. **Damage is confirmed by a consistent read**, never by comparing scans
   (B8, C8, and R3's other classes).
4. **Compare as stored.** R1 decides on the stored creator, and under the
   flag the force-email rewrite never runs inside the lookup (G8).
5. **Fail closed at startup** on DynamoDB, on definite absence and on a
   probe fault alike (K8, owner).
   - **PostgreSQL (confirmed by the owner 2026-10-30):** the same rule, so there is
     one rule. On PostgreSQL a probe fault with a missing index leaves only
     concurrent creates unprotected, because the lookup reads the row.
6. **Quiesce what cannot be made safe.**
   - `disable --apply` runs only after every flag-on process has stopped;
     the guide and the command's help say so (J8).
   - `disable` is resumable: it deletes the records even when the
     backfill-complete item is already gone, and finishes with a scan that
     confirms the table is empty.
   - With rules 1-3, `resolve` and `enable` are safe against live S4
     traffic, as the rollout needs at steps 5-6.
7. **Old flag-off processes are accepted, not engineered around.** S1-S3
   violations are repaired by the step 5 and 6 runs, plus R1's repair. The
   guide already tells deployments to keep the window short and the
   factory closed.

## The sign-in path, both backends

These are local fixes and need no change to the rules above:
- **F8:** in `_replace_enforced`, re-raise a `CreatorTaken` from the swap
  before the recovery branch. The caller then looks up once more and adopts
  the successor, as entry 50 does for a first sign-in.
- **H8:** see R6.
- **I8:** `modify_creator_unvouched` checks `is_refused_from_callers`, and
  `ActorInterface.modify_creator` checks `is_reserved`. The command's
  direct `Actor.modify` stays exempt.
- **L8, PostgreSQL stale-handle rename:** add `AND creator = %s` with the
  handle's value, so a stale handle returns False as DynamoDB does.

## Mapping

| Finding | Rule |
| --- | --- |
| A8 | 1 (the exception) |
| B8 | 1, 3 |
| C8 | 3 (R4) |
| D8 | 2 |
| E8 | R4 (`--creator` refused) |
| F8, H8, I8 | sign-in path |
| G8 | 4 |
| J8 | 6 |
| K8 | 5 |
| A7's fail-closed (entry 45) | replaced by R1's repair (rule 1) |

## Testing

The tests should be organised by state, not by finding. A helper seeds each
state directly on DynamoDB Local, writing raw rows and records:
- G1, G2 and G3;
- each of them after a fault;
- an unrecorded actor;
- a scan-skew pair: a record written between the two scans of `collect`,
  through a patched scan.

For each state, assert the outcome of each reader (R1, R3, R4) and of
`resolve --apply`. The matrix in "What each reader sees" is the expected
table. This replaces one-off tests per finding, and covers the cells
nobody has reported yet.

## Open

- **Deletion status on the enforced replace branch:** confirmed by the
  owner 2026-10-30 (keep it as implemented).
- **Rule 5 on PostgreSQL:** confirmed by the owner 2026-10-30.
- **R1's repair replaces entry 45's fail-closed.** This is a decision
  change for the plan's Decisions Made.
- **The L8 low items not covered here** (`actor_created` for a kept
  successor, the retried force-email rewrite, the default-creator sweep,
  custom backends with the flag off, inline normalisation copies, `#…`
  addresses with the flag off) go into the same iteration where they are
  small, or into a todo.

## Addendum (2026-10-30, after verification -3)

**Prompted by:**
thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-3.md
(A9-J9). Iterations 52-58 implemented the rules above, and verification
-3 still found a High (A9) and three Mediums. Three assumptions of this
note were wrong. This section corrects them; the rules above stand where
nothing here replaces them.

### 1. Writers by mechanism, not by intent

The writer table (W1-W11) was built from what each path means to do. A
path that writes `creator` without meaning to was missed. This is every
write to the DynamoDB actor row and the `creators` table, found by
grepping for `save`, `update`, `delete` and `TransactWrite` on both models
(`actingweb/db/dynamodb/actor.py`, `actingweb/maintenance/unique_creators.py`;
`verify_orphans.py` and `verify_tables.py` only read):

| Site | Mechanism | Writes `creator`? | Guard today |
| --- | --- | --- | --- |
| `DbActor.modify`, flag off or no creator change (`:174-182`) | `handle.save()`, a full PutItem | **yes, the handle's copy** | none: it overwrites a concurrent rename, and it re-creates a deleted row |
| `_modify_unique` (W2) | transaction: update, conditioned on the old creator, plus the new record | yes | conditioned |
| `create` flag on (W1), `replace_creator_holder` (W4) | transaction | yes | `id` absent, record absent / names the squatter |
| `create` flag off | `save(condition=id absent)` | yes | conditioned |
| `delete` flag on (W3) | delete conditioned on the creator | - | conditioned |
| `delete` flag off (W6) | unconditional delete | - | none, accepted (rule 7) |
| `_release_record` (W2, W3 tail) | record delete if it names the actor | - | rule 1's exception |
| `release_stale_record` (W8, R1 repair, settle fallback) | consistent actor read, then a record delete conditioned on `actor_id` | - | **read only** (E9) |
| `_rename` (W7) | `Actor.modify` with the flag off, so the full `save()` above | **yes** | none |
| `_settle_record` (W7) | record update conditioned on `actor_id` | - | **read only** (F9) |
| `_enable_dynamodb` (W9) | record put if absent | - | **read only** (G9) |
| `disable` (W10) | record deletes | - | rule 6 |

The missing row is the first one: **W0, the full-row save.** It serves the
password rotation of the clean-in-place sign-in (`oauth2.py:2413`, A9) and
every flag-off rename, the command's own `_rename` included. Under the
flag it can write a creator back without its record. With the flag off it
can still undo a rename or re-create a deleted actor.

**Rule 8. No full-row write of the actor.** `modify` updates only the
attributes it changes, conditioned on the creator the handle holds (or on
the row existing, for a handle without one). A stale handle answers False
on both backends and with the flag in either state; PostgreSQL already
does this since entry 58.

### 2. A read is not a guard

Rules 1-3 read the actor row consistently and then wrote the record with a
condition on the record only. Between the read and the write the actor can
change. D9, E9, F9 and G9 are this one pattern. DynamoDB can check the actor
row in the write's own transaction (`TransactWrite.condition_check`).

**Rule 9, replacing the "re-read" half of rules 1-3.** A record write
whose correctness depends on the actor row commits with a
`condition_check` that the row is still as it was read: the same stored
`creator`, or still absent. A failed check answers "changed meanwhile",
the same as a failed record condition. Which condition failed is
confirmed by a read, because DynamoDB Local reports every cancellation on
the first item (the note at `_actor_exists`).
- rule 1's helper: the record delete plus the check (E9);
- rule 2's move: the record update plus a check on the kept row (F9);
- W9: the record put plus a check on the actor (G9);
- R1 (D9) writes nothing. It loads the actor after the check and
  compares again after the load.

### 3. R1's repair is a writer: W12

Entry 52 made the sign-in lookup delete a stale record and then create.
That makes R1 a writer, and this note never checked it against the gaps.
After the repair, the create assumes nobody else holds the address. That
is false for **an actor that holds `c` without a record**:
- an actor created by an old flag-off process (rule 7, stages S1-S3);
- the kept actor of a group while `resolve` runs (B9). `resolve` renamed
  the record's actor first, so the record looks stale. The repair removes
  it, and the create makes a third actor beside the kept one.

The first is accepted (rule 7). The second is the command's own ordering.

**Rule 2, amended.** `resolve` settles the record before it renames
anyone. If the record names one of the losers, it is moved to the kept
actor (rule 9). If there is no record, one is written for the kept actor
(put if absent, plus a check on the kept row). Then the losers are
renamed. From the first write on, a sign-in loads the kept actor. Only
if the kept actor no longer holds `c` does the old fallback, rule 1's
helper, run after the renames.

### 4. A second invariant: the marker

C9 is not about the record. A race retry (`oauth2.py:1045`, `:1077`)
reads the winner consistently through the record, which can be earlier
than the winner's `auth_method` marker is written (`Actor.create` writes
the row and record, then the marker). The adoption rule treats an
unmarked actor as legacy and cleans it in place.

> **M.** An actor a retry adopts carries its marker.

**Rule 10.** A retry that finds a winner with no marker does not adopt it.
The winner is still being created, so the conflict stands (`CreatorTaken`,
409) and the user's next attempt finds it marked. *(Confirmed by the
owner 2026-10-30; a short wait and re-read would turn some of those 409s into a
sign-in, at the cost of a sleep on the request path.)*

### Mapping (verification -3)

| Finding | Rule |
| --- | --- |
| A9 | 8 |
| B9 | 2, amended |
| C9 | 10 |
| D9, E9, F9, G9 | 9 |
| H9 | local: on the last attempt a failed condition wins over a conflict |
| I9, J9 | docs and a comment |

### Testing (addendum)

States to add to `tests/integration/test_unique_creator_states.py`:
- a handle loaded before a concurrent rename, then a password-only modify
  (rule 8);
- a concurrent change slipped between the read and the write of each
  rule 9 site, through a patched read;
- `resolve` with a sign-in between the settle and the renames (rule 2);
- a retry winner without its marker (rule 10).

### Addendum, second part (2026-10-30, after verification -4)

Verification -4 (A10, B10) found two rules applied to fewer sites than
they cover.

**M, widened.** "An actor a retry adopts carries its marker" was too
narrow: the first sign-in lookup reads through the record just as
consistently (A10). The invariant is:

> **M.** An actor a sign-in can find through the record or the unique row
> carries its marker.

It now holds by construction for generated ids: `Actor.create` writes the
marker before the row, and removes it if the create does not happen.
Fixed ids (system actors) keep the marker after the row; no sign-in finds
them. Rule 10's retry check stays as defence against rows old flag-off
processes write.

**Rule 2, amended again.** Settling before the renames has three outcomes:
- settled: the record names the kept actor, moved or written;
- skip: no table yet, or the kept actor no longer holds the key, so the
  old fallback runs after the renames;
- conflict: the record names a live holder outside the group, or something
  changed meanwhile. The group is skipped and counted (exit 1).

A stale record naming an actor outside the group is released first
(rule 1), then written for the kept actor (B10).

**Rule 1, extended.** After the orphan pass removes a record, a lone live
holder of the key (listed and re-read consistently) gets its record
(rule 9). Before, it waited for the next `enable`, and a sign-in in
between created a second actor.

**Values.** Every condition on the stored creator uses one helper,
`creator_is`, which renders `None` as "absent" (D10). An empty creator
cannot be stored on DynamoDB at all, because it is the creator index's key,
so C10 is unreachable there.

### Addendum, third part (2026-10-30, after verification -7)

Verification -7 showed entry 76 ("write `creator_changed` again after a
landed change") moved the A12 race without closing it, and found the same
shape in the clean-in-place sign-in (`oauth2.py`, the vouched marker
written last). Every unconditional write of a vouched marker that can land
after a rename has it. A marker write cannot be conditioned on the actor
row without a cross-table compare-and-set on both backends.

> **V.** An actor is vouched for an address only if a vouched marker was
> written for that address.

**Rule 11.** Every vouched-marker write records the address it vouches
for (`vouched_creator`, in the `_internal` bucket) before the marker:
`Actor.create`, the restore of a failed creator change, the clean-in-place
sign-in, and `mark_actors_vouched`. `is_vouched_store(store, creator)`
compares it with the creator being judged: the actor's own
(`is_vouched_actor`) or the address a sign-in resolves (the ranking). The
actor's own stored `email` also counts, which keeps the existing "rename to
one's own email keeps the vouch" rule. A missing address (vouched before
3.16) falls back to the marker alone; any new vouched write binds it.

This holds by construction at the read: no ordering of a rename and a
marker write ends vouched under the renamed address. Entry 76's re-write
is removed.

**Also:** on DynamoDB with the flag off, a stale handle's save is
conditioned on the passphrase it is not changing, so a rename through a
handle loaded before a rotation cannot write the old passphrase back
(A9's fix was partial).

