# Verification: vouched actors, clean-slate adoption, a closable factory, SPA `prompt` (seventh run)

**Date:** 2026-10-28
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all work uncommitted)

Scope: Iterations entries 39-46, the batch after the sixth verification
(`thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory.md`).
Bug record: `thoughts/research/2026-10-28-tombstone-wipes-and-strict-creator-listing.md`.
The full tier re-checks everything before it.

## Automated Check Results

- **Browser QA:** N/A. Entries 39-46 change no page. BG below is a flow
  issue, found by reading the code.
- **Second opinion:** outside-voice ran Codex (`codex exec -s read-only`,
  unsandboxed, exit 0) and a fresh-context Claude. `/code-review high` found
  10. The **security review** found nothing at confidence 8 or above, for
  the fourth run in a row; its candidates included the new vouched-branch
  sweep, poisoning `factory_sibling_ids`, and the batched revoke.
- `ruff check`: pass. `ruff format --check`: pass (423 files). `pyright`:
  0 errors, 0 warnings.
- `verify_groups.py`: pass (50 groups).
- **DynamoDB** `make test-all-parallel`: **4059 passed, 31 skipped**, no failures.
- **PostgreSQL** `make test-all-parallel`: **3949 passed, 141 skipped**, no
  failures. The extra skip is the DynamoDB-only index-lag test.
- `sphinx-build -W` (with `.claude/**` excluded locally): build succeeded.
- **Benchmarks:** 17 passed in both runs, but the timings are **not reliably
  measured**. Other sessions held the load average at 20 during the full
  tier and at 4-5 during a rerun alone.
  - The rerun's attribute read (0.68 ms) and attribute write (0.90 ms)
    match earlier batches.
  - Actor create read 14.0 ms there and 19.6 ms inside the full tier,
    against 6.3 ms on a quiet machine after the fifth batch. This batch does
    not touch the create path's I/O, which is still one insert, one marker
    write with read-back, and one tombstone clear.
  - Re-measure on a quiet machine before the release (Remaining Tasks).

## Phase Verification

### Entry 39: entry 35 reverted (AW) - VERIFIED

- `oauth2.py`: the vouched return runs before any tombstone read, and its
  comment says why.
- The successor reuse ignores the tombstone.
- The mobile tests' patches are gone.
- `TestVouchedActorMidDeletion` asserts that the tombstoned actor is
  returned with its data. It fails on the pre-batch files.
- Known limitation and todo item are present.

### Entry 40: strict creator listings (AX, AY, AZ) - VERIFIED, ISSUES FOUND

- `db/dynamodb/actor.py:110-122`: a strict per-row `Actor.get`, skipping
  `DoesNotExist`.
- `db/postgresql/actor.py`: strict raises, and answers `[]`.
- `oauth2.py`:
  - `_creator_rows`;
  - `_factory_siblings` checks that the victim was listed (`seen_exclude`);
  - the successor step creates only when nothing is left.
- Tests: `TestStrictCreatorListing` (3). Each fails with its fix disabled
  in place.
- Gaps:
  - The strict row is not compared with the queried creator (BK).
  - A fifth-iteration test now passes through a `TypeError` (BM).

### Entry 41: carried context (BA) - VERIFIED, one gap

- `oauth2.py`: the `carried` merge.
- Test: `TestRecursiveCleanReportsTheReplacement`.
- A nested hand-off drops the outer `carried` (BN).

### Entry 42: vouched sign-in sweeps factory actors; batched SPA revoke (BB) - ISSUES FOUND

- `actor.py`: `factory_sibling_ids`.
- `oauth2.py`: `_sweep_factory_actors`, and the vouched-branch call.
- `oauth_session.py`: `revoke_all_tokens_for_actors`.
- Tests: `TestFactoryActorsBesideAVouchedOne` (2), including the
  one-pass assertion.
- Issues:
  - The sweep's re-read is no longer "just before" each delete (BH).
  - The sweep is unbounded and runs inline (BI).
  - Two concurrent sign-ins double-fire deletion hooks (BL).

### Entry 43: rollback unbind; bridge winner (BC) - VERIFIED

`actor.py` rollback branch, and `mcp.py` `_race_winner`. Tests:
`TestCreateRollbackAndTheBridgeWinner` (2).

### Entry 44: provider-id creator email (BD) - VERIFIED

`oauth2.py`, the clean's `proven_email`. Tests: `TestProviderIdCreatorEmail` (2).

### Entry 45: peer-trustee rows (BE) - ISSUES FOUND

- `actor.py` `purge_relationships`, and the peer-trustee list `fetch(strict)`
  on both backends.
- Test: `TestPeerTrusteeRowsOfUnlistedTypes`.
- The DynamoDB peer-trustee query is eventually consistent, so the purge's
  re-read can be wrong on real DynamoDB (BJ).

### Entry 46: one classifier (BF) - VERIFIED

`classify_store`, `classify_marker`. Used by `_candidate_rank`,
`_factory_siblings` and `_sweep_factory_actors`. Test: `TestClassifyMarker`.

## Security property demonstrated

A squatter's `factory` actors never take the owner's sign-in or data, and
each sign-in that proves the address removes them:
- `TestFactoryActorsBesideAVouchedOne::test_vouched_sign_in_removes_the_factory_actors_beside_it`
  asserts that only the owner's id remains, and that one revoke pass covered
  all three squats;
- `TestOwnersActorBesideFactoryOnes` asserts the owner's data is kept.

The security review found no way for an outside caller to make a victim's
actor carry `factory`, or to point the sweep or the batched revoke at
another creator's actors (its candidates 1-3).

## Thoughts bookkeeping

- The follow-ups todo carries:
  - the tombstone-on-vouched item, which is new;
  - H-L;
  - the load-time pin rewrite;
  - the AK test;
  - the benchmark tables;
  - the type hints (the code review raised them again).
- The root-cause todos (`db-layer-get-bucket-or-empty.md`,
  `creator-uniqueness-not-enforced.md`) exist. The owner has asked for them
  to be implemented as their own plan.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-28-oauth-adoption-vouching-and-open-factory.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| AW: tombstone wipes live vouched actor | Fixed (reverted; known limitation, todo) | Entry 39 |
| AX: index lag fails sign-in | Fixed | Entry 40, strict DynamoDB listing |
| AY: victim not checked in listing | Fixed | Entry 40, `seen_exclude` |
| AZ: successor read fault creates duplicate | Fixed | Entry 40 |
| BA: recursion drops outer record | Fixed (nested case: BN) | Entry 41 |
| BB: O(N) reads with many factory actors | Fixed, but now N wipes inline (BI) | Entry 42 |
| BC: rollback / bridge winner | Fixed | Entry 43 |
| BD: provider-id creator email | Fixed | Entry 44 |
| BE: peer-trustee rows of unlisted types | Fixed (DynamoDB consistency: BJ) | Entry 45 |
| BF: four marker classifiers | Fixed | Entry 46 |

## Remaining Tasks

- [ ] BG, BH, BI, BJ before the release PR. Each is a few lines or a
  sentence.
- [ ] Re-measure the benchmarks on a quiet machine.
- [ ] The owner runs `/code-review ultra` on the branch, the independent
  whole-branch review recommended after the sixth iteration.
- [ ] A plan for the two root causes, which the owner asked for: fault
  semantics in the DB layer, and creator uniqueness.
- [ ] Emm AI prod: decide on `2f4c5bea…`.
- [ ] Release PR.

## Issues Found

### BG. A user whose provider gives no verified email is locked out after clicking the verification link
**Severity:** Medium
**Description:** The emailed link cleans the `email_unverified` actor, which
ends its sessions (`oauth_email.py:221`, through `adopt_actor`). Ending them
is right: the session holder may be the squatter who typed the victim's
address. But the user's way back in is the same email-less provider, which
leads to `/oauth/email`, and that form answers 409 `actor_exists` for an
address that already has an actor (`oauth_email.py:464-474`). The 409 is
older than 3.16. Before this release the user kept a two-week session, so
they hit it only when that expired; now they hit it right after the click.
The CHANGELOG's "the user signs in again after the click" is false for this
path.
**Location:** `actingweb/handlers/oauth_email.py:212-236`, `:464-474`;
`CHANGELOG.rst` SECURITY entry.
**Recommendation:** issue a fresh session to whoever clicks the link, since
the click proves the address: redirect with the cookie or SPA token the
callback would set. At least correct the CHANGELOG and migration guide
sentence now, saying a user on an email-less provider must sign in with a
provider that proves the address.

### BH. The sweep's marker re-read is no longer just before each delete
**Severity:** Medium
**Description:** `_sweep_factory_actors` re-classifies every sibling first
(`oauth2.py:1883`), then scans the global SPA token buckets (`:1887`), then
wipes each sibling in turn (`:1901`). A sibling vouched meanwhile, by the
backfill with `--include-factory` during live sign-ins, is deleted with its
data. Entry 33's guarantee no longer holds, and
`test_sibling_vouched_since_listing_is_kept` vouches only before the sweep
starts. The migration guide says not to run `--include-factory` while
serving, which narrows this.
**Location:** `actingweb/oauth2.py:1870-1910`
**Recommendation:** classify again inside the per-sibling loop, right before
`_remove_for_replacement`, and keep the first pass only to decide which
SPA tokens to revoke.

### BI. A vouched sign-in runs an unbounded number of full wipes inline
**Severity:** Medium
**Description:** With an open factory, a squatter can keep any number of
factory actors for the owner's address, and the owner's next sign-in wipes
them all inside the request (`oauth2.py:1987-1996`). Each wipe covers the
buckets, trusts, MCP token revoke, client index, tombstone and two hooks. A
few hundred can push the callback past a Lambda or ALB timeout, and the
squatter can add more before the next sign-in. Before entry 42 the same
sign-in paid N marker reads.
**Location:** `actingweb/oauth2.py:1987-2010`
**Recommendation:** cap the sweep per sign-in (for example 10 in id order),
log what is left, and let later sign-ins continue. Add a known-limitation
sentence that points at `with_open_factory(False)`.

### BJ. DynamoDB peer-trustee reads are eventually consistent, so the purge's check can be wrong
**Severity:** Medium
**Description:** `db/dynamodb/peertrustee.py:152`/`:172` `PeerTrustee.query(self.actor_id)`
uses no `consistent_read`, while the trust and subscription list queries do
(`trust.py:449`, `subscription.py:178`). Right after the deletes, the
purge's re-read (`actor.py:1818-1821`) can list a removed row, which fails
the clean after the passphrase was rotated, or miss a just-written row,
which confirms a purge that is not complete. DynamoDB Local is strongly
consistent, so the suite cannot show either case.
**Location:** `actingweb/db/dynamodb/peertrustee.py:140-172`
**Recommendation:** pass `consistent_read=True` in both queries, and fix the
docstring that says `strict` "changes nothing here".

### BK. The strict DynamoDB listing and the sweep do not check the creator
**Severity:** Low
**Description:** `db/dynamodb/actor.py:112-119` returns the row's own
`creator` without comparing it with the queried one. The sweep likewise
deletes listed ids without comparing (`oauth2.py:1895-1906`). For a moment
after a creator rename, the index can list a factory actor under its old
creator, and the sweep would remove it for that address. It is a `factory`
actor (a rename keeps the marker), so the harm is small. A stale
`factory_sibling_ids` on a reused `Actor` object has the same shape.
**Recommendation:** skip rows whose creator (lowercased when it contains
`@`) differs from the query, in the strict listing and in the sweep.

### BL. Two concurrent sign-ins to a vouched actor fire deletion hooks twice per sibling
**Severity:** Low
**Description:** Both requests load the sibling before either deletes it,
and the second `delete()` still answers True, meaning "no fault"
(`oauth2.py:1780-1781`, `:1895`). Flask's cookie lookup on `GET /`
(`flask_integration.py:685`) runs the adoption on page load, so two tabs are
enough.
**Recommendation:** skip a sibling that is already tombstoned before
`mark_actor_deleted`, or add it to the known limitations.

### BM. A fifth-iteration test passes through a TypeError
**Severity:** Low
**Description:** `tests/test_adoption_fifth_iteration.py:162` patches
`get_by_creator` with `lambda self, creator=None: None`, and
`_creator_rows` now passes `strict=True`. The `TypeError` is caught by
`adopt_actor`, so the empty-listing path is never exercised.
**Recommendation:** accept `*, strict=False` and return `[]` when strict, so
the test reaches `seen_exclude`.

### BN. A nested hand-off drops the outer `carried`
**Severity:** Low
**Description:** `oauth2.py:2104` `return _adopt_actor(successor, ..., carried={...})`
builds a fresh dict, so an incoming `carried` from an outer level is lost.
That happens when the inner actor is itself replaced (an unfinished-wipe
tombstone) and hands off again.
**Recommendation:** merge the incoming `carried` into the one passed down.

### BO. Under `unique_creator`, a faulted DynamoDB row read counts as "no existing actor"
**Severity:** Low
**Description:** `actor.py:426` drops None entries from `get_by_creator`,
which an earlier batch added for index lag. On DynamoDB a faulted `get()`
also answers None, so the uniqueness check passes and a duplicate is
created. Before the filter, `c["passphrase"]` on None raised, failing
closed.
**Recommendation:** use the strict listing there too.

### BP. Redundant I/O on the replace path
**Severity:** Low
**Description:**
- A replacement scans the global SPA buckets twice: once for the victim,
  once for the siblings (`oauth2.py:2057`).
- Each sibling's marker and row are read up to three times in one sign-in.
- The tombstone is written twice, which is the todo's existing duplicate.
**Recommendation:** revoke `[victim, *siblings]` in one pass, and pass the
classified markers and loaded actors along.

### BQ. The SPA completion paths duplicate the resolver
**Severity:** Low
**Description:** `oauth2_spa.py:969` and `:1147` repeat
`get_from_creator` → `adopt_actor` → `lookup_or_create_actor_by_identifier`,
which the resolver does itself.
**Recommendation:** call `lookup_or_create_actor_by_identifier` alone.

### Notes (not findings)

- **Hooks without `**kwargs`** (raised again by the code review): the
  migration guide and CHANGELOG tell consumers to accept `**kwargs`.
  Accepted.
- **An `email_unverified` actor is cleaned, not replaced, so its properties
  survive.** That is by design: properties are reported in `actor_adopted`
  (`property_names`), not removed, because the email form's own users hold
  real data before they verify.
- **Apps that create several actors per creator through `POST /` on
  purpose** now lose them at the owner's next vouched sign-in, not only at
  the first proof. Migration item 2 tells such deployments to use
  `ActorInterface.create()`. `../actingweb_mcp` and `../actingwebdemo` were
  not checked for this pattern.
- **A half-finished sibling wipe** (row left, `_internal` gone) classifies
  as `unvouched` and stays as an inert row.
- **Missing type hints** are in the follow-ups todo.

## Overall Assessment

Entries 39-46 do what they claim. Entry 35's regression is gone, every new
test fails with its fix disabled, the full tier is green on both backends,
and the security review again finds no exploit. The trend is down: no High
this round, four Mediums, all small.
- BJ is a missing `consistent_read=True`.
- BH moves one call into a loop.
- BI needs a cap and a sentence.
- BG needs a docs correction now; the session-at-click fix can follow.

The pattern is unchanged, though. Each Medium is a cost or consistency edge
of the previous batch's change, and two of the four (BJ, BO) are the DB
layer answering a fault or a lagging read as data. That supports the
owner's decision: implement the two root causes as their own plan, and get
an independent whole-branch review (`/code-review ultra`) before the release
PR. I recommend one short iteration for BG (the docs), BH, BI and BJ, with
the Lows filed, then the ultra review, then the root-cause plan.
