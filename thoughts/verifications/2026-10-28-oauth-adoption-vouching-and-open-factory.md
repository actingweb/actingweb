# Verification: vouched actors, clean-slate adoption, a closable factory, SPA `prompt` (sixth run)

**Date:** 2026-10-28
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all work uncommitted)

Scope: Iterations entries 31-38 (the batch after the fifth verification,
`thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-5.md`).
Bug record: `thoughts/research/2026-10-28-owners-actor-stranded-and-sweep-read-faults.md`.
The full tier re-checks everything before them.

## Automated Check Results

- **Browser QA:** N/A. Entries 31-38 change no page.
- **Second opinion:** the outside-voice agent ran Codex
  (`codex exec -s read-only`, outside the sandbox, exit 0) and a fresh-context
  Claude. `/code-review high` produced 10 findings. The security review found
  nothing at confidence 8 or above; it flagged one side note, folded into AW.
  All are folded in below, with duplicates merged.
- `ruff check`: pass. `ruff format --check`: pass (422 files).
  `pyright`: 0 errors, 0 warnings.
- `verify_groups.py`: pass (50 groups).
- **DynamoDB** `make test-all-parallel`: **4047 passed, 31 skipped**, no failures.
- **PostgreSQL** `make test-all-parallel`: **3938 passed, 140 skipped**, no
  failures.
- `sphinx-build -W`, with `.claude/**` excluded locally: build succeeded.
- **Benchmarks**, run alone after the reviews finished and after a warm-up run
  of `tests/test_adoption_write_faults.py`: 17 passed. Medians: attribute read
  0.70 ms, attribute write 0.70 ms, actor read 0.74 ms, actor create 6.30 ms,
  actor delete 3.15 ms, trust list 1.00 ms, bulk property read 78 ms. An
  earlier run during the reviews showed actor create at 13.05 ms, which was
  machine load; the alone run matches the last iteration (6.26 ms).

## Phase Verification

### Entry 31: lookup order, and the owner's actor in the successor step (AN) - VERIFIED, ISSUES FOUND

- `actor.py:305-325`: `_candidate_rank` ranks vouched 0, other unvouched or
  unreadable 1, `factory` 2, and the code that reads the store is inside the
  try.
- `actor.py:362-368`: a stable sort.
- `oauth2.py:1981-2022`: successor step. It cleans a non-factory unvouched
  actor in place through a recursive `_adopt_actor`, and hands a tombstoned
  vouched one back the same way.
- Tests: `TestOwnersActorBesideFactoryOnes` (2). Both fail with the fix
  reverted.
- Issues: AZ (a read fault in the step) and BA (the recursion's hook
  record).

### Entry 32: backfill resume hint (AO) - VERIFIED

- `mark_actors_vouched.py`: `_mark_one`, and the line is printed after it
  returns.
- `TestBackfillResumeHint` interrupts the run with KeyboardInterrupt and
  asserts that only the first actor is named.

### Entry 33: sweep order and read faults (AP) - ISSUES FOUND

- `oauth2.py:1761-1826`: `_factory_siblings` and `_still_factory`.
- `oauth2.py:1940-1976`: the sweep is listed before removal and each marker
  is re-read before its delete.
- Tests: `TestSweepReadFaults` (4).
- The docstring says the list "must then include" the victim, but nothing
  checks that (AY). A None row now fails closed, which DynamoDB's index lag
  produces routinely (AX).

### Entry 34: clean resets confirmed, `trustee_root` cleared (AS) - VERIFIED, one gap

- `oauth2.py:2056-2088`.
- Tests: `TestCleanLeavesNothingOfThePreviousCreator` (2).
- `email` is reset only for creators containing `@` (BD).

### Entry 35: tombstone before the vouched return (AT) - ISSUES FOUND (High)

- `oauth2.py:1900-1914` now treats a DELETED tombstone on a live, vouched
  actor as "finish the wipe and replace". See AW: this changed what a
  tombstone means, and the paths that write and clear tombstones were not
  re-checked against the new meaning.

### Entry 36: refused create unbinds (AU) - VERIFIED, one gap

- `actor.py:478-487`.
- Test: `TestRefusedCreateUnbinds`.
- The marker-rollback `return False` (`actor.py:517`) still leaves the
  object bound (BC).

### Entry 37: MCP bridge create race (AR) - VERIFIED, one gap

- `mcp.py:2436-2444`.
- Test: `TestMcpBridgeCreateRace`.
- The winner is accepted without checking its marker or tombstone (BC).

### Entry 38: the creator pin in the actor (AV) - VERIFIED

- `actor.py`: `creator_change_pinned` and `modify_creator_unvouched`.
- `trust.py`: `_change_creator`.
- Test: `TestCreatorPinOnTheConsumerPath`.
- The fourth-iteration test now turns the pin off on purpose.

## Security property demonstrated

A squatter's factory actor never receives the owner's sign-in or the owner's
data:
- `TestOwnersActorBesideFactoryOnes::test_sign_in_cleans_the_owners_actor_not_a_lower_factory_one`
  asserts that two sign-ins both return the owner's id, with the owner's
  property kept;
- `TestFactorySiblings::test_one_sign_in_replaces_every_factory_sibling`
  still asserts that a single id remains after a replacement.

The security review confirms that nothing an unauthenticated caller does
writes a vouched marker or a tombstone for someone else's actor (its
candidates 1-3).

## Thoughts bookkeeping

- No new todo files. The plan's own todos were deleted earlier.
- `adoption-fault-and-hygiene-followups.md` still lists:
  - H-L;
  - the load-time rewrite under the pin;
  - the AK test;
  - the benchmark tables.
- BE below extends its `purge_relationships` item.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| AN: owner's actor stranded | Fixed (a read-fault variant remains: AZ) | Entry 31 |
| AO: resume hint skips one | Fixed | Entry 32 |
| AP: sweep reads faults as absence | Fixed, but over-tightened on DynamoDB (AX); victim check missing (AY) | Entry 33 |
| AQ: guide contradiction | Fixed | `docs/migration/v3.16.rst` "What stays the same" |
| AR: MCP bridge race | Fixed (winner unchecked: BC) | Entry 37 |
| AS: `trustee_root` kept | Fixed | Entry 34 |
| AT: vouched mid-deletion returned | Changed, and the change is the High issue AW | Entry 35 |
| AU: refused create bound | Fixed for the not-created branch (rollback branch: BC) | Entry 36 |
| AV: leftovers | Fixed | Entries 33, 34, 38 |
| Emm prod actor `2f4c5bea…` | Still open (owner's decision) | - |

## Remaining Tasks

- [ ] AW before the release (revert or narrow entry 35), then AX, AY, AZ
  and BA.
- [ ] The Low items, or file them in the follow-ups todo.
- [ ] Emm AI prod: decide what to do with `2f4c5bea…`.
- [ ] Release PR (version, `Unreleased` rename, migration `.. note::`).

## Issues Found

### AW. A tombstone on a live vouched actor now deletes it at the next sign-in
**Severity:** High
**Description:** Entry 35 makes `oauth2.py:1906-1907`
("`unfinished_wipe = … == DeletionStatus.DELETED`" /
"`if is_vouched_actor(existing) and not unfinished_wipe:`") send a vouched
actor down the replace path whenever a tombstone exists. That covers more
than a wipe that stalled:
- **A stale tombstone on a reused fixed id.** `actor.py:474-475` ignores
  `clear_actor_tombstone`'s result, and DynamoDB's `delete_attr` answers
  True after swallowing the exception (`db/dynamodb/attribute.py:182-191`).
  An MCP bridge actor recreated at its fixed id with a stale tombstone is
  deleted, data and all, at its owner's next sign-in, at any time within
  the 30-day retention window.
- **A DELETE that stalls or raises.** `handlers/root.py:100` writes the
  tombstone and `:113` fires `actor_deleted` before `:115`
  `myself.delete()`. If the delete raises (DynamoDB), times out, or a hook
  raises, the actor stays live, vouched and tombstoned. The next sign-in
  then fires `actor_deleted` and `actor_deleted_complete` again with
  `reason="replaced_at_adoption"`, so a consumer that cancels a paid
  subscription there runs it twice, and the second time looks like a
  replacement.
- **The emailed link, which has no provider** (`oauth2.py:1917-1922`): a
  stale tombstone fails every attempt for the whole retention window.
- **Successor reuse.** It recurses on a tombstoned vouched actor in the same
  way (`oauth2.py:1988-2002`).

There is also no CHANGELOG **Behavior change:** sentence for this.
**Location:** `actingweb/oauth2.py:1900-1914`, `:1988-2002`
**Recommendation:** revert entry 35. Return a vouched actor as before, and
reuse a vouched successor whatever its tombstone says. AT was Low, a
pre-3.16 behaviour on the vouched branch. Keep it as a known limitation in
the CHANGELOG and the follow-ups todo. If it is kept instead, it needs a
confirmed tombstone clear on create, no second `actor_deleted` on a resumed
user DELETE, and a CHANGELOG entry.

### AX. A DynamoDB index row for a just-deleted actor fails every sign-in for that address
**Severity:** Medium
**Description:** `oauth2.py:1789-1796` fails closed on a None row. DynamoDB's
`get_by_creator` returns None for any actor the creator index still lists
after its row was deleted; `actor.py:417-421` and `get_from_creator` filter
exactly that. Two consequences:
- A squatter can delete one of their factory actors (they hold its
  passphrase) just before the owner signs in, and repeat it, so the owner's
  first sign-in keeps failing.
- The recursive successor call (AW's path) re-lists right after the outer
  sweep's deletes, so it fails almost every time on DynamoDB.
**Location:** `actingweb/oauth2.py:1789-1796`
**Recommendation:** skip a None row, as the other two lookups do. What
remains is a factory sibling whose row read faulted: it is inert, and it is
the next replacement's to sweep. Record that as a known limitation.

### AY. `_factory_siblings` never checks that the victim was listed
**Severity:** Medium
**Description:** The docstring (`oauth2.py:1767-1768`) says the list "must
then include it". The loop (`:1798`) skips `exclude` without recording that
it saw it, so a partial index read that omits the victim passes. The victim
is then removed while the siblings the read missed stay.
**Location:** `actingweb/oauth2.py:1761-1814`
**Recommendation:** track `seen_exclude`, and return None when it is
missing. On DynamoDB this still fails closed only during index lag, before
the victim was ever indexed. That window is milliseconds after its create.

### AZ. A read fault in the successor step creates a duplicate vouched actor
**Severity:** Medium
**Description:** `oauth2.py:1983-1987` counts the successor as found only if
`get_from_creator` succeeded **and** its store `loaded`. Otherwise `:2019`
creates a new actor:
- on PostgreSQL, a faulted `get_by_creator` answers None;
- a faulted bucket read leaves `loaded` False;
- on DynamoDB, a faulted `get` drops the candidate.

With `unique_creator` off (the default), the result is a second vouched
actor that outranks the owner's unvouched one on every later sign-in. That
is AN again, this time permanent.
**Location:** `actingweb/oauth2.py:1981-2022`
**Recommendation:** create only when `get_by_creator` confirmed that no other
rows exist. A listed actor whose row or store did not answer returns None,
and the victim's tombstone lets the next sign-in resume.

### BA. The recursion drops the outer replacement from `actor_adopted`
**Severity:** Medium
**Description:** Both `return _adopt_actor(successor, …)` calls
(`oauth2.py:1995`, `:2011`) return only the inner result. Two things go
missing:
- No `actor_adopted` names the factory victim, its removed trusts, its
  client ids or the swept siblings; only per-actor `actor_deleted` events
  are left, with no old-to-new mapping.
- In the cleaned-owner case the hook reports `mode="cleaned"` with
  `previous_actor_id=None`, although this sign-in also replaced a factory
  actor.

The todo's "lost successor mapping" covers only a successor create that
raises.
**Location:** `actingweb/oauth2.py:1988-2018`
**Recommendation:** pass the outer `previous_actor_id`, `removed_trusts`,
`client_ids` and `swept_ids` into the inner call (keyword-only), and merge
them into its hook kwargs and log line.

### BB. Many factory actors beside a vouched one cost O(N) reads on every sign-in
**Severity:** Low
**Description:** `actor.py:368` ranks every candidate, and each rank reads
the full `_internal` bucket. Factory actors beside a vouched one are never
swept, because the vouched one wins and no replacement runs. An attacker on
an open factory can add thousands for the owner's address. The replace path
also revokes per sibling, and each revoke scans the global SPA token buckets
(`oauth2.py:1731`).
**Recommendation:** stop at the first vouched candidate in id order. Or,
when a vouched actor wins a lookup with factory siblings, sweep them with
the same `_remove_for_replacement`. Revoke once over all removed ids.
Otherwise document closing the factory as the mitigation.

### BC. Two binding and winner gaps around `Actor.create`
**Severity:** Low
- `actor.py:517`: the marker-rollback `return False` leaves `id`, `store`
  and `handle` bound. If the rollback also failed, the unmarked row is live.
- `mcp.py:2442`: the bridge accepts any loaded winner, which could be that
  unmarked row (the owner's next sign-in then cleans it and purges the MCP
  clients just connected) or one mid-deletion.

**Recommendation:** unbind on the rollback path too. In the bridge, accept a
winner only if it carries a marker and no tombstone.

### BD. A clean resets `email` only for creators containing "@"
**Severity:** Low
**Description:** `oauth2.py:2076-2077`. An actor whose creator is a provider
id (`apple:…`) keeps the `store.email` its previous creator wrote. If
`force_email_prop_as_creator` is turned on later, `Actor.get` moves the
creator to that address.
**Recommendation:** for creators without `@`, delete `email` or set it from
the provider's `user_info`.

### BE. `purge_relationships` misses peer-trustee rows of types not in config
**Severity:** Low
**Description:** `actor.py` `delete_peer_trustee("*")` visits only the
`config.actors` short types, and `confirmed` does not re-read peer-trustee
rows. This extends the todo's existing item.
**Recommendation:** add it to the todo item: list the actor's peer-trustee
rows directly, and re-read them for `confirmed`.

### BF. The marker classification exists four times
**Severity:** Low
**Description:** `_candidate_rank`, `_factory_siblings`, `_still_factory`
and `_mark_one` each read `_internal` and classify the marker, with
different unreadable semantics.
**Recommendation:** one `classify_marker(config, actor_id)`, returning
vouched, unvouched, replace or None.

### Notes (not findings)

- **The emailed-link rename chain** was raised again by the code review:
  an `email_unverified` actor renamed through `PUT /trust/trustee`, then
  verified through the attacker's own link. It is still blocked by default,
  because the email form needs the pin and the pin refuses the rename, and
  the security review again did not raise it. The cheap hardening is
  unchanged: clear `email_verification_token` in
  `modify_creator_unvouched`, or store the target address in the token
  index.
- **Codes and provider token data survive a clean in place** (security
  review candidate 5, confidence 4): the `mcp_auth_codes` bucket. Minting
  a code needs a provider login for the creator, which the pin blocks, and a
  code lives 10 minutes. Hygiene: add it to the clean.
- **Altitude** (code review): most per-call `strict`/`loaded`/`set_confirmed`
  workarounds exist because backends turn faults into empty answers.
  `thoughts/todo/db-layer-get-bucket-or-empty.md` already tracks the
  DB-layer fix.

## Overall Assessment

Entries 31-38 fix what they claim, every new test fails without its fix, and
the full tier is green on both backends. The security review finds no way for
an outside caller to plant a vouched marker or a tombstone.

Entry 35 is a net regression. Before it, a tombstone meant "suppress late
writes". It now means "delete this live actor at the next sign-in", and two
existing paths leave a tombstone on a live vouched actor under ordinary
faults: an unconfirmed clear on create, and a DELETE that stalls. Reverting
entry 35 and keeping AT as a documented limitation is the smaller and safer
change. AX, AY and AZ are also fault edges of entries 31 and 33, and one of
them (AX) can be triggered on purpose by a squatter on DynamoDB. I recommend
one more short iteration:
1. revert 35;
2. skip None rows;
3. check the victim was listed;
4. fail closed in the successor step instead of creating;
5. carry the outer context into the recursion.

Then verify again.
